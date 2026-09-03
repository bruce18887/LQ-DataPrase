"""File CRUD and upload views."""

import logging
import os
import re
import shutil
import time
from datetime import datetime, time as dtime

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.datafiles.models import DataFile
from apps.datafiles.serializers import (
    DataFileListSerializer,
    DataFileSerializer,
    normalize_tags,
)
from apps.datafiles.services import clear_parse_cache
from apps.datafiles.utils import resolve_file_path, store_file_path

from ._helpers import (
    _register_file,
    _register_zip_batch,
    _user_upload_dir,
    _disk_mtime,
    _parse_last_modified,
    _delete_datafile_file_only,
    _remove_empty_dirs_up_to,
    _UNSAFE_NAME_CHARS,
)

logger = logging.getLogger(__name__)


def _parse_date_bound(raw: str):
    """容错解析日期边界参数：纯日期 → date；带时间 → datetime；非法 → None。

    注意：strptime 对纯日期格式也返回 datetime（零点）——必须按「输入是否含
    时间分量」显式转 date，否则 _date_bound 的 isinstance(datetime) 分支恒真，
    纯日期 lte 补不到当天末尾（当天文件被漏）。
    """
    if not raw:
        return None
    has_time = ':' in raw
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed if has_time else parsed.date()
    return None


def _date_bound(raw: str, end_of_day: bool):
    """把日期边界参数转成可用 filter 值：纯日期补全时刻（gte=00:00:00 /
    lte=23:59:59.999999，否则「当天上传」被 lte 漏掉），带时间原样使用。"""
    parsed = _parse_date_bound(raw)
    if parsed is None:
        return None
    if isinstance(parsed, datetime):
        return parsed
    return datetime.combine(parsed, dtime.max if end_of_day else dtime.min)


class DataFilePagination(PageNumberPagination):
    """PageNumberPagination that honors the ``page_size`` query param.

    The DRF default pagination class ignores ``page_size`` (its
    ``page_size_query_param`` is None), so front-end "load all" calls
    (``?page_size=9999`` for file dropdowns / dashboards) were silently
    truncated to PAGE_SIZE=20 — the analysis dropdown showed 20 files while
    the data-management table counted all of them.  ``max_page_size`` keeps
    the param bounded so a huge value cannot balloon the response.
    """

    page_size_query_param = 'page_size'
    max_page_size = 10000


class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = DataFilePagination
    # 搜索完全自管（get_queryset）：DRF SearchFilter 只查 search_fields 列，
    # 会把「仅标签命中」的行过滤掉——标签搜索必须 OR 进查询集后再整集过滤。
    # search_fields 刻意留空，让 SearchFilter 对该视图变为 no-op。
    search_fields = []
    filterset_fields = ['product_code', 'format_type', 'file_type']
    ordering_fields = ['created_at', 'source_mtime', 'filename', 'file_size']

    def get_queryset(self):
        queryset = DataFile.objects.filter(owner=self.request.user)

        # Custom search for tags (JSONField)
        search = self.request.query_params.get('search', '').strip()
        if search:
            # Search in filename, program_name, batch_name, and tags
            from django.db.models import Q
            q = (
                Q(filename__icontains=search)
                | Q(program_name__icontains=search)
                | Q(batch_name__icontains=search)
            )
            queryset = queryset.filter(q)
            # 全文搜索承诺包含标签：JSONField 无法跨库 SQL 搜索，
            # 与既有 tag 精确参数同款 Python 预过滤——命中标签的行 OR 回来。
            search_lower = search.lower()
            tag_ids = [
                row['id']
                for row in DataFile.objects.filter(owner=self.request.user).values('id', 'tags')
                if any(
                    search_lower in str(t).lower()
                    for t in (row.get('tags') or []) if isinstance(t, str)
                )
            ]
            if tag_ids:
                queryset = queryset | DataFile.objects.filter(
                    owner=self.request.user, id__in=tag_ids,
                )

        # 表头列筛选：文件名 / 测试程序 contains（服务端生效，20 条/页必须后端过滤）
        filename_ic = self.request.query_params.get('filename__icontains', '').strip()
        if filename_ic:
            queryset = queryset.filter(filename__icontains=filename_ic)
        program_ic = self.request.query_params.get('program_name__icontains', '').strip()
        if program_ic:
            queryset = queryset.filter(program_name__icontains=program_ic)

        # Filter by specific tag
        tag = self.request.query_params.get('tag', '').strip()
        if tag:
            # Filter files that have this specific tag (case-insensitive)
            # Since tags is a JSONField with a list, we need to check if the tag exists in the list
            # This is database-specific; for SQLite we'll filter in Python
            # For PostgreSQL, we could use __contains
            tag_lower = tag.lower()
            matching_ids = []
            for df in queryset.values('id', 'tags'):
                tags = df.get('tags') or []
                if any(t.lower() == tag_lower for t in tags if isinstance(t, str)):
                    matching_ids.append(df['id'])
            queryset = queryset.filter(id__in=matching_ids)

        # 上传时间范围筛选（文件列表表头筛选，2026-08-20）：created_at__gte/__lte
        # 容错解析——非法日期静默跳过（对齐 ag-grid 列过滤的宽容跳过惯例，不 400）。
        # 前端传纯日期（YYYY-MM-DD）：gte 取当天 00:00:00，lte 取当天 23:59:59.999999
        #（否则「今天上传」的文件会被 lte 漏掉）。
        created_gte = self.request.query_params.get('created_at__gte', '').strip()
        created_lte = self.request.query_params.get('created_at__lte', '').strip()
        if created_gte:
            bound = _date_bound(created_gte, end_of_day=False)
            if bound is not None:
                queryset = queryset.filter(created_at__gte=bound)
        if created_lte:
            bound = _date_bound(created_lte, end_of_day=True)
            if bound is not None:
                queryset = queryset.filter(created_at__lte=bound)

        # 文件大小范围筛选：file_size__gte/__lte（浮点容错，非法值跳过）
        size_gte = self.request.query_params.get('file_size__gte', '').strip()
        size_lte = self.request.query_params.get('file_size__lte', '').strip()
        try:
            if size_gte:
                queryset = queryset.filter(file_size__gte=float(size_gte))
            if size_lte:
                queryset = queryset.filter(file_size__lte=float(size_lte))
        except ValueError:
            pass  # 非法数值静默跳过

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return DataFileListSerializer
        return DataFileSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def destroy(self, request, *args, **kwargs):
        datafile = self.get_object()
        # 只删该文件（批次行也一样）——整批删除由 /batch-dirs/<name>/ 语义承担，
        # 历史实现（_delete_datafile_on_disk）对批次行 rmtree 整个批次目录，
        # 任何"删单个文件"的操作都可能误删整批。
        _delete_datafile_file_only(datafile)
        datafile.delete()
        clear_parse_cache()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'])
    def bulk_delete(self, request):
        """Delete multiple owned files at once: { "ids": [1, 2, 3] }."""
        ids = request.data.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return Response(
                {'error': 'ids must be a non-empty list'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Owner-scoped: only the requesting user's files are ever touched.
        qs = DataFile.objects.filter(owner=request.user, id__in=ids)
        for datafile in qs:
            _delete_datafile_file_only(datafile)
        deleted_count = qs.count()
        qs.delete()
        clear_parse_cache()
        return Response({'deleted': deleted_count})

    @action(detail=False, methods=['get'])
    def product_codes(self, request):
        """Distinct non-empty product codes for the current user's files."""
        codes = (
            DataFile.objects.filter(owner=request.user)
            .exclude(product_code='')
            .values_list('product_code', flat=True)
            .distinct()
            .order_by('product_code')
        )
        return Response({'product_codes': list(codes)})

    @action(detail=False, methods=['get'])
    def format_types(self, request):
        """Distinct non-empty format types for the current user's files."""
        formats = (
            DataFile.objects.filter(owner=request.user)
            .exclude(format_type='')
            .values_list('format_type', flat=True)
            .distinct()
            .order_by('format_type')
        )
        return Response({'format_types': list(formats)})

    @action(detail=False, methods=['post'])
    def combine(self, request):
        """Combine multiple owned single files into a batch.

        Body: ``{"ids": [1, 2], "batch_name": "LOT-2026"}``.

        The files are physically moved into ``media/data/<user>/batch/<name>/``
        (the batch model is directory-based) and their rows updated (file_type=
        'batch', batch_name set, sub_batch cleared). The batch may be new or
        already exist (append): a target-name collision gets a ``_<ts>`` suffix
        and the row's filename is updated. ParseHistory rows are audit history
        and are left untouched. The parse cache is cleared so browse uses new
        paths.

        Ordering guarantee: DB changes commit first, file moves execute after.
        If the DB transaction fails, no file is touched on disk.
        """
        ids = request.data.get('ids') or []
        batch_name = (request.data.get('batch_name') or '').strip()
        if not isinstance(ids, list) or not ids or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in ids
        ):
            return Response(
                {'error': 'ids must be a non-empty list of integers'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not batch_name:
            return Response(
                {'error': 'batch_name is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if re.search(r'[<>:"/\\|?*]', batch_name):
            return Response(
                {'error': 'batch_name 包含非法字符'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Owner-scoped and single-only: batch rows moving into another batch
        # would leave their original directory behind, breaking batch-dirs.
        qs = DataFile.objects.filter(
            owner=request.user, id__in=ids, file_type='single',
        )
        if qs.count() != len(ids):
            return Response(
                {'error': '部分文件不存在、不属于当前用户或不是单文件（仅支持组合单文件）'},
                status=status.HTTP_404_NOT_FOUND,
            )

        batch_base = _user_upload_dir(request.user, 'batch')
        batch_dir = os.path.join(batch_base, batch_name)
        os.makedirs(batch_dir, exist_ok=True)

        # Phase 1: plan moves — compute (src, target, new_filename) for each row.
        plans = []  # [(df, src, target, new_filename), ...]
        for df in qs.order_by('id'):
            src = resolve_file_path(df.file_path)
            if not os.path.exists(src):
                continue  # cannot move a missing file; skip it
            # Defence-in-depth: basename strips any directory traversal that
            # might have crept into the DB filename field historically.
            safe_name = os.path.basename(df.filename)
            if not safe_name or _UNSAFE_NAME_CHARS.search(safe_name):
                logger.warning(
                    'combine: skipping df id=%s with unsafe filename %r',
                    df.pk, df.filename,
                )
                continue
            target = os.path.join(batch_dir, safe_name)
            if os.path.exists(target):
                ts = int(time.time())
                name, ext = os.path.splitext(safe_name)
                safe_name = f'{name}_{ts}{ext}'
                target = os.path.join(batch_dir, safe_name)
            plans.append((df, src, target, safe_name))

        if not plans:
            return Response({
                'combined': 0,
                'batch_name': batch_name,
                'files': [],
            })

        # Phase 2: DB changes inside transaction (no file I/O here).
        updated = []
        with transaction.atomic():
            for df, _src, target, new_filename in plans:
                df.filename = new_filename
                df.file_path = store_file_path(target)
                df.file_type = 'batch'
                df.batch_name = batch_name
                df.sub_batch = ''
                df.save(update_fields=[
                    'filename', 'file_path', 'file_type', 'batch_name',
                    'sub_batch', 'updated_at',
                ])
                updated.append(df)

        # Phase 3: file moves after successful commit.
        for df, src, target, _ in plans:
            try:
                shutil.move(src, target)
            except OSError:
                logger.warning(
                    'combine: file move failed after DB commit, '
                    'df id=%s src=%s target=%s', df.pk, src, target,
                    exc_info=True,
                )

        if updated:
            clear_parse_cache()

        return Response({
            'combined': len(updated),
            'batch_name': batch_name,
            'files': DataFileSerializer(updated, many=True).data,
        })

    @action(detail=False, methods=['post'])
    def uncombine(self, request):
        """Move batch files back to the single-file pool (reverse of combine).

        Body: ``{"ids": [1, 2]}``. Each owned batch file is physically moved to
        ``media/data/<user>/single/`` and its row becomes ``file_type='single'``
        with batch_name/sub_batch cleared. A target-name collision gets a
        ``_<ts>`` suffix. Once-empty sub-batch / batch directories are removed
        (an emptied batch disappears from the batch listing). ParseHistory rows
        are audit history and are left untouched. Parse cache is cleared.

        Ordering guarantee: DB changes commit first, file moves execute after.
        If the DB transaction fails, no file is touched on disk.
        """
        ids = request.data.get('ids') or []
        if not isinstance(ids, list) or not ids or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in ids
        ):
            return Response(
                {'error': 'ids must be a non-empty list of integers'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Owner-scoped and batch-only: singles are already outside any batch.
        qs = DataFile.objects.filter(
            owner=request.user, id__in=ids, file_type='batch',
        )
        if qs.count() != len(ids):
            return Response(
                {'error': '部分文件不存在、不属于当前用户或不是批次文件（仅支持批次文件）'},
                status=status.HTTP_404_NOT_FOUND,
            )

        single_dir = _user_upload_dir(request.user, 'single')
        batch_base = _user_upload_dir(request.user, 'batch')

        # Phase 1: plan moves.
        plans = []  # [(df, src, target, new_filename, src_dirname), ...]
        for df in qs.order_by('id'):
            src = resolve_file_path(df.file_path)
            if not os.path.exists(src):
                continue  # missing on disk: cannot move; skip it
            safe_name = os.path.basename(df.filename)
            if not safe_name or _UNSAFE_NAME_CHARS.search(safe_name):
                logger.warning(
                    'uncombine: skipping df id=%s with unsafe filename %r',
                    df.pk, df.filename,
                )
                continue
            target = os.path.join(single_dir, safe_name)
            if os.path.exists(target):
                ts = int(time.time())
                name, ext = os.path.splitext(safe_name)
                safe_name = f'{name}_{ts}{ext}'
                target = os.path.join(single_dir, safe_name)
            plans.append((df, src, target, safe_name, os.path.dirname(src)))

        if not plans:
            return Response({'moved': 0, 'files': []})

        # Phase 2: DB changes inside transaction (no file I/O here).
        moved = []
        with transaction.atomic():
            for df, _src, target, new_filename, _ in plans:
                df.filename = new_filename
                df.file_path = store_file_path(target)
                df.file_type = 'single'
                df.batch_name = ''
                df.sub_batch = ''
                df.save(update_fields=[
                    'filename', 'file_path', 'file_type', 'batch_name',
                    'sub_batch', 'updated_at',
                ])
                moved.append(df)

        # Phase 3: file moves + empty dir cleanup after successful commit.
        for df, src, target, _, src_dirname in plans:
            try:
                shutil.move(src, target)
                # 源位置空目录清理（子批次/批次目录，至 batch_base 含其自身）
                _remove_empty_dirs_up_to(src_dirname, batch_base)
            except OSError:
                logger.warning(
                    'uncombine: file move failed after DB commit, '
                    'df id=%s src=%s target=%s', df.pk, src, target,
                    exc_info=True,
                )

        if moved:
            clear_parse_cache()

        return Response({
            'moved': len(moved),
            'files': DataFileSerializer(moved, many=True).data,
        })

    @action(detail=True, methods=['post'])
    def set_tags(self, request, pk=None):
        """Overwrite the file's tag list. Body: ``{"tags": ["a", "b"]}``.

        Owner-scoped: a 404 is returned if the file is not owned by the
        requesting user. Validation (length / count / type) is delegated to
        ``normalize_tags``; on success the response echoes the saved tags.
        """
        datafile = self.get_object()
        try:
            tags = normalize_tags(request.data.get('tags') or [])
        except Exception as e:
            return Response(
                {'tags': [str(e)]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        datafile.tags = tags
        datafile.save(update_fields=['tags', 'updated_at'])
        return Response({'id': datafile.id, 'tags': datafile.tags})

    @action(detail=False, methods=['post'])
    def list_tags(self, request):
        """Return distinct, de-dup'd tags the current user has ever used.

        Body (optional): ``{"prefix": "PR"}`` — case-insensitive prefix filter
        used by the front-end autocomplete. Tags from every file the user
        owns are aggregated and returned in lexicographic order.
        """
        prefix = (request.data.get('prefix') or '').strip()
        seen = {}
        # Iterate over each file's tag list and collect distinct (case-insensitive)
        # entries, preferring the first-seen casing as the canonical form.
        for tag_list in (
            DataFile.objects.filter(owner=request.user)
            .exclude(tags=[])
            .values_list('tags', flat=True)
        ):
            if not isinstance(tag_list, list):
                continue
            for t in tag_list:
                if not isinstance(t, str):
                    continue
                t = t.strip()
                if not t:
                    continue
                key = t.lower()
                if key in seen:
                    continue
                if prefix and not key.startswith(prefix.lower()):
                    continue
                seen[key] = t
        return Response({'tags': sorted(seen.values(), key=str.lower)})


class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        # Support both single 'file' and multiple 'files' keys
        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        if not files:
            return Response({'error': '未选择文件'}, status=400)

        # CSV files and ZIP archives (containing CSVs) are supported.
        allowed_exts = {'.csv', '.zip'}
        for uploaded_file in files:
            ext = os.path.splitext(uploaded_file.name)[1].lower()
            if ext not in allowed_exts:
                return Response(
                    {'error': f'仅支持 CSV 或 ZIP 文件，无法上传 {uploaded_file.name}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Optional per-file last_modified (epoch ms), parallel to the files list.
        last_modified_list = request.data.getlist('last_modified')

        upload_dir = _user_upload_dir(request.user, 'single')
        created = []

        for idx, uploaded_file in enumerate(files):
            base_name = uploaded_file.name
            ext = os.path.splitext(base_name)[1].lower()

            lm_value = last_modified_list[idx] if idx < len(last_modified_list) else None
            browser_mtime = _parse_last_modified(lm_value)

            # ZIP: extract CSVs and register them as batch data.
            if ext == '.zip':
                zip_created, zip_error = _register_zip_batch(request.user, uploaded_file, base_name)
                if zip_error:
                    return Response({'error': zip_error}, status=status.HTTP_400_BAD_REQUEST)
                created.extend(zip_created)
                continue

            file_path = os.path.join(upload_dir, base_name)

            # Handle filename collision
            if os.path.exists(file_path):
                ts = int(time.time())
                name, _ext = os.path.splitext(base_name)
                file_path = os.path.join(upload_dir, f"{name}_{ts}{_ext}")

            # Save uploaded file
            with open(file_path, 'wb+') as dest:
                for chunk in uploaded_file.chunks():
                    dest.write(chunk)

            df = _register_file(
                request.user, file_path, 'single',
                source_mtime=browser_mtime,
            )
            created.append(df)

        return Response(
            DataFileSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )
