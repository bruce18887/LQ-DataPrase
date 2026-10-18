"""Data browsing and maintenance views."""

import json
import logging
import os
from typing import Optional

import pandas as pd
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.constants import PAGE_SIZE_MAX
from apps.common.errors import error_response
from apps.common.grid_filters import (
    apply_filter_model as _apply_filter_model,
    apply_sort as _apply_sort,
)
from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import SYSTEM_COLUMNS
from apps.datafiles.serializers import DataFileSerializer, ParseHistorySerializer
from apps.datafiles.services import (
    get_cached_parsed_file,
    get_cached_fail_data,
    clear_parse_cache,
)
from apps.datafiles.utils import extract_product_code, resolve_file_path
from apps.analysis.services.statistics import (
    build_col_meta,
    get_bin_column_name,
)
from apps.analysis.services.statistics.helpers import get_serial_column, get_site_column

from ._helpers import (
    _register_file,
    _resolve_product_code,
    _scan_orphaned_disk,
    _user_upload_dir,
    _find_duplicate_groups,
    _delete_duplicate_files,
)

logger = logging.getLogger(__name__)


class FileActivateView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DataFileSerializer

    def put(self, request, pk):
        datafile = get_object_or_404(DataFile, pk=pk, owner=request.user)
        datafile.status = 'ready'
        datafile.save(update_fields=['status', 'updated_at'])

        return Response(DataFileSerializer(datafile).data)


class ParseHistoryListView(ListAPIView):
    serializer_class = ParseHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ParseHistory.objects.filter(user=self.request.user)[:20]


# ag-grid IRM 的 filterModel/sortModel 算子本体在 apps/common/grid_filters.py：
# 导出 worker（spawn 子进程，无 Django）要用同一套算子，逻辑不能有两份。


class DataBrowserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        datafile_id = request.query_params.get('datafile_id')
        # Safe pagination: non-numeric → default; clamp to valid range.
        try:
            page = int(request.query_params.get('page', 1))
        except (ValueError, TypeError):
            page = 1
        page = max(1, page)
        try:
            # 参数缺失时的兜底块大小维持 50（改动前后一致）；它与「账号设置默认 100」
            # 是两个不同的量，勿合并。
            page_size = int(request.query_params.get('page_size', 50))
        except (ValueError, TypeError):
            page_size = 50
        # 只钳**上界**，且与账号设置域的上界同源（apps/common/constants.PAGE_SIZE_MAX）。
        # 原先这里写死 100000 —— 比合法设置域宽 200 倍，直连 API 可一次要走近乎全表。
        # 下界刻意保持 1 而非 PAGE_SIZE_MIN：设置页的 50 下限是为「滚动别变成请求风暴」，
        # 对端点而言小页只是更小的载荷，不是风险；把它抬到 50 会静默改变调用方要的块大小，
        # 也让按小页验证切片/越界的用例无法表达。勿「对齐」成对称区间。
        page_size = max(1, min(page_size, PAGE_SIZE_MAX))
        # ``search``（全表全文过滤，旧实测 16.2s）已删除，查看数据一律走 filter_model。
        # 存在即拒、空串也拒：静默忽略会让直连调用方以为筛过了，实际拿到全表。
        if 'search' in request.query_params:
            return error_response(
                'unsupported_param',
                'search is not supported on /browse/; filter per column with filter_model',
                param='search',
            )
        pass_filter = request.query_params.get('pass_filter', '')
        site_filter = request.query_params.get('site_filter', '')

        # 排序（服务端分页：ag-grid IRM sortModel → JSON 数组字符串）
        sort_model_raw = request.query_params.get('sort_model', '')
        sort_model = []
        if sort_model_raw:
            try:
                parsed = json.loads(sort_model_raw)
                if isinstance(parsed, list):
                    sort_model = parsed
            except ValueError:
                return error_response(
                    'invalid_sort_model', 'sort_model must be a JSON array')

        # 列过滤（ag-grid IRM filterModel → JSON 对象；白名单算子见 _apply_filter_model）
        filter_model_raw = request.query_params.get('filter_model', '')
        filter_model = {}
        if filter_model_raw:
            try:
                parsed = json.loads(filter_model_raw)
                if isinstance(parsed, dict):
                    filter_model = parsed
            except ValueError:
                return error_response(
                    'invalid_filter_model', 'filter_model must be a JSON object')

        if not datafile_id:
            return error_response('param_required', 'datafile_id is required')

        datafile = get_object_or_404(
            DataFile, pk=datafile_id, owner=request.user
        )

        if not os.path.exists(resolve_file_path(datafile.file_path)):
            return error_response('file_not_found', 'File not found on disk', 404)

        df, metadata, fmt = get_cached_parsed_file(datafile.id, request.user.pk, datafile)
        if df is None:
            return error_response('parse_failed')

        # fail 检测按 (file, mtime) 缓存——文件内容未变时零重算（生产大文件收益明显）
        fail_indices, fail_columns, fail_cells, borderline_cells = get_cached_fail_data(
            datafile.id, request.user.pk, datafile)
        if fail_cells is None or borderline_cells is None:
            return error_response('parse_failed')

        fail_set = set(fail_indices)

        # page==1 时预计算前端所需的全文件元信息（基于过滤前全量 df）
        site_options: list = []
        numeric_columns: list = []
        system_columns: list = []
        serial_column: Optional[str] = None
        if page == 1:
            site_col_full = get_site_column(df)
            if site_col_full:
                site_options = [
                    str(v) for v in df[site_col_full].dropna().astype(str).unique()
                    if str(v) not in ('', 'nan')
                ]
            for col in df.columns:
                if df[col].dtype == object:
                    # 值级判定（镜像旧前端 Number.isFinite 语义）：SW_Bin/X_COORD 等
                    # 数字字符串列保持 object dtype（NON_NUMERIC_COLUMNS），纯 dtype 判定会漏
                    if pd.to_numeric(df[col], errors='coerce').notna().any():
                        numeric_columns.append(col)
                elif (pd.api.types.is_numeric_dtype(df[col])
                      and not pd.api.types.is_bool_dtype(df[col])
                      and df[col].notna().any()):
                    # 排除 bool（Dut_Pass，TRUE/FALSE 非数值）与全 NaN 列（QR_Code 解析后）
                    numeric_columns.append(col)
            # 记录级列（系统列）：按格式权威列表（SYSTEM_COLUMNS）∩ 文件列，
            # 保持文件列序——前端据此恒显+前置，不再用名称前缀启发式
            # （Device_Fused_Flag1/2、SITE_CHECK 等测试项与记录列同名前缀，2026-08-25）。
            sys_set = set(SYSTEM_COLUMNS.get(datafile.format_type, []))
            system_columns = [c for c in df.columns if c in sys_set]
            # 序列列：四种格式名字各不相同（Serial_No / Serial # / PART_ID），且 Dut_No
            # 也是每只 DUT 一个号 —— 前端不许再用名称猜，统一由后端权威解析下发。
            # get_serial_candidates 是全项目唯一的序列列优先级（serial_distribution /
            # wafer_map / file_correlation 共用），这里只是多消费一次。
            serial_column = get_serial_column(df)

        # Apply filters at DataFrame level (fast pandas ops) before paginating
        if site_filter:
            site_col = get_site_column(df)
            if site_col:
                # 字符串比较（与 export_csv site_filter 语义一致；Site_No 是数字字符串 object 列）
                df = df[df[site_col].astype(str) == str(site_filter)]

        # 列过滤（白名单算子，逐列 AND；与 site/pass 组合）
        if filter_model:
            df = _apply_filter_model(df, filter_model)

        if pass_filter:
            if pass_filter.upper() == 'PASS':
                df = df[~df.index.isin(fail_set)]
            elif pass_filter.upper() == 'FAIL':
                df = df[df.index.isin(fail_set)]

        # 排序在切片前（稳定排序保证块间顺序一致）；fail_cells 按原 index 查表，
        # 过滤/排序只改变行序不改变 index 标签 → 与 data 行并行天然对齐
        if sort_model:
            df = _apply_sort(df, sort_model)

        # fail_row_count 为「当前筛选集内」的 fail 行数（IRM 下前端无法本地计算，
        # 原文件级全量语义改为筛选集语义；pass_filter=FAIL 时 == total、PASS 时 0）
        fail_row_count = int(df.index.to_series().isin(fail_set).sum())

        total = len(df)
        start = (page - 1) * page_size
        end = start + page_size

        # 预序列化：pandas to_json（C 引擎）直出 data JSON 字符串，零 Python 级
        # 逐格对象构建。orient='values'（行值数组）：208.9MB records 格式 → 68MB，
        # 前端 parse 提速 4.6x（V8 解析纯数组远快于字符串键对象，Node 实测 1299ms→281ms）。
        # pandas C 引擎对 NaN/+inf/-inf/None 一律输出 null，与旧 replace 语义逐值相等。
        # 切片必须 .copy()：缓存中的 df 只读，不得变异。
        paged_df = df.iloc[start:end].copy()
        data_json = paged_df.to_json(orient='values', date_format='iso')
        # __fail_cells__ 原生数组（不再逐行 json.dumps / 前端逐格 JSON.parse）；
        # 与 data 行并行（恒存在，pass 行为 []），不混入 df 列（headers 不被污染）
        fail_cells_json = json.dumps(
            [fail_cells.get(i, []) for i in paged_df.index], ensure_ascii=False
        )
        # 临界橙格：与 data 并行的原生数组（pass/无临界行 []）。
        # fail_cells 语义不变，Excel 导出/分析页继续只认红格。
        borderline_cells_json = json.dumps(
            [borderline_cells.get(i, []) for i in paged_df.index], ensure_ascii=False
        )

        payload = (
            '{"headers":' + json.dumps(list(df.columns), ensure_ascii=False)
            + ',"data":' + data_json
            + ',"fail_cells":' + fail_cells_json
            + ',"borderline_cells":' + borderline_cells_json
            + ',"total":' + str(total)
            + ',"page":' + str(page)
            + ',"page_size":' + str(page_size)
            + ',"total_pages":' + str((total + page_size - 1) // page_size)
            + ',"fail_row_count":' + str(fail_row_count)
            + ',"col_meta":' + json.dumps(build_col_meta(df, metadata), ensure_ascii=False)
            + ',"bin_column":' + json.dumps(get_bin_column_name(datafile.format_type), ensure_ascii=False)
            + ((',"site_options":' + json.dumps(site_options, ensure_ascii=False) + ',"numeric_columns":' + json.dumps(numeric_columns, ensure_ascii=False)
                + ',"system_columns":' + json.dumps(system_columns, ensure_ascii=False)
                + ',"serial_column":' + json.dumps(serial_column, ensure_ascii=False)) if page == 1 else '')
            + '}'
        )
        return HttpResponse(payload, content_type='application/json; charset=utf-8')


# Consistency-check write actions and the roles allowed to run them. Delete is
# destructive, so it is restricted to administrators; import/fix are additive
# and mirror upload privileges (administrator + user). Viewers may read the
# check results (GET stays IsAuthenticated) but cannot mutate anything.
_DELETE_ACTIONS = ('delete_orphaned_db', 'delete_orphaned_disk', 'delete_duplicates')
_MUTATE_ACTIONS = ('import_orphaned_disk', 'fix_product_codes')
_ALL_ACTIONS = _DELETE_ACTIONS + _MUTATE_ACTIONS


class DataConsistencyCheckView(APIView):
    """Check and fix data consistency between database and disk."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Check consistency: orphaned DB records, orphaned disk files,
        files whose product_code could not be extracted at registration,
        and duplicate files (same filename + size)."""
        user = request.user

        # Orphaned DB records: rows of any file_type whose disk file is gone.
        # file_path is dual-format (relative since 2026-08-21, absolute for
        # legacy rows) — must resolve before the existence check, otherwise
        # every relative-path row is falsely reported as orphaned.
        db_files = DataFile.objects.filter(
            owner=user
        ).values_list('id', 'file_path', 'filename', 'batch_name', 'sub_batch', 'file_type')

        orphaned_db = []
        for f_id, f_path, f_name, f_batch, f_sub, f_type in db_files:
            if not os.path.exists(resolve_file_path(f_path)):
                orphaned_db.append({
                    'id': f_id,
                    'filename': f_name,
                    'batch_name': f_batch,
                    'sub_batch': f_sub,
                    'file_type': f_type,
                    'file_path': f_path,
                })

        # Orphaned disk files: CSVs on disk with no registered DataFile row.
        # Shared scanner so GET/POST agree on the exact set.
        orphaned_disk = [
            {
                'path': fp,
                'filename': os.path.basename(fp),
                'batch_name': batch_name,
                'sub_batch': sub_batch,
            }
            for fp, batch_name, sub_batch in _scan_orphaned_disk(user)
        ]

        # Files missing a product_code (all file_types). GET only previews from
        # the stored program_name — reparsing happens on the fix action.
        missing = []
        for df in (
            DataFile.objects.filter(owner=user, product_code='')
            .order_by('id')
            .values('id', 'filename', 'file_path', 'program_name',
                    'batch_name', 'sub_batch', 'file_type')
        ):
            preview_code = extract_product_code(df['filename'], df['program_name'])
            file_missing = not os.path.exists(resolve_file_path(df['file_path']))
            missing.append({
                'id': df['id'],
                'filename': df['filename'],
                'batch_name': df['batch_name'],
                'sub_batch': df['sub_batch'],
                'file_type': df['file_type'],
                'preview_code': preview_code,
                'reparse_needed': not preview_code and not file_missing,
                'file_missing': file_missing,
            })

        # Duplicate files: same filename + size (all file_types).
        duplicate_groups, duplicate_group_count = _find_duplicate_groups(user)

        return Response({
            'orphaned_db_count': len(orphaned_db),
            'orphaned_disk_count': len(orphaned_disk),
            'missing_product_code_count': len(missing),
            'duplicate_group_count': duplicate_group_count,
            'orphaned_db': orphaned_db[:50],  # Limit to 50 for display
            'orphaned_disk': orphaned_disk[:50],
            'missing_product_code': missing[:50],
            'duplicate_groups': duplicate_groups,
        })

    def post(self, request):
        """Fix consistency issues. Actions always recompute the full affected
        set server-side (not the GET's 50-row display slice)."""
        action = request.data.get('action')
        if action not in _ALL_ACTIONS:
            return error_response(
                'invalid_action', 'action must be one of: ' + ', '.join(_ALL_ACTIONS))

        user = request.user
        role = getattr(user, 'role', '')
        if action in _DELETE_ACTIONS and role != 'administrator':
            return error_response('forbidden', '仅管理员可执行删除操作', 403)
        if action in _MUTATE_ACTIONS and role not in ('administrator', 'user'):
            return error_response('forbidden', '当前角色无权执行该操作', 403)

        if action == 'delete_orphaned_db':
            return self._delete_orphaned_db(user, action)
        elif action == 'delete_orphaned_disk':
            return self._delete_orphaned_disk(user, action)
        elif action == 'delete_duplicates':
            return Response({
                'status': 'ok',
                'action': action,
                'deleted_count': _delete_duplicate_files(user),
            })
        elif action == 'import_orphaned_disk':
            return self._import_orphaned_disk(user, action)
        return self._fix_product_codes(user, action)

    def _delete_orphaned_db(self, user, action):
        # Delete DB records with missing disk files (any file_type; paths
        # must be resolved — see GET above — or relative rows get wiped).
        db_files = DataFile.objects.filter(
            owner=user
        ).values_list('id', 'file_path')

        deleted_ids = []
        for f_id, f_path in db_files:
            if not os.path.exists(resolve_file_path(f_path)):
                deleted_ids.append(f_id)

        deleted_count = DataFile.objects.filter(id__in=deleted_ids).delete()[0]
        clear_parse_cache()

        return Response({
            'status': 'ok',
            'action': action,
            'deleted_count': deleted_count,
        })

    def _delete_orphaned_disk(self, user, action):
        # Delete disk files not in database (scanner = same set as GET)
        batch_base = _user_upload_dir(user, 'batch')

        deleted_count = 0
        for fp, _batch_name, _sub_batch in _scan_orphaned_disk(user):
            try:
                os.remove(fp)
                deleted_count += 1
            except OSError:
                pass

        # Clean up empty directories
        for root, dirs, _files in os.walk(batch_base, topdown=False):
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                except OSError:
                    pass

        return Response({
            'status': 'ok',
            'action': action,
            'deleted_count': deleted_count,
        })

    def _import_orphaned_disk(self, user, action):
        """Register every orphaned disk CSV as a batch DataFile. Per-file
        transaction so one failure (e.g. file deleted since the GET) never
        rolls back the rest; failures are counted in skipped_count."""
        imported_count = 0
        skipped_count = 0
        for fp, batch_name, sub_batch in _scan_orphaned_disk(user):
            try:
                with transaction.atomic():
                    _register_file(user, fp, 'batch', batch_name, sub_batch)
                imported_count += 1
            except Exception:
                logger.warning(
                    '_import_orphaned_disk: failed to register %s', fp,
                    exc_info=True,
                )
                skipped_count += 1

        return Response({
            'status': 'ok',
            'action': action,
            'imported_count': imported_count,
            'skipped_count': skipped_count,
        })

    def _fix_product_codes(self, user, action):
        """Re-extract product_code for rows where it is empty. Uses the stored
        program_name first, then reparses the file header for a fresher
        program name. No ParseHistory row is created — that table is a parse
        audit, not a product-code audit. file_path never changes, so the parse
        cache stays valid.

        Each row commits in its own transaction (like _import_orphaned_disk):
        the action is idempotent, so a mid-way failure is recoverable by
        re-running, and a single long write transaction would hold the
        SQLite write lock for the whole scan — two parallel repair runs
        (e.g. two Playwright workers) would deadlock each other."""
        results = []
        fixed_count = 0
        missing_qs = DataFile.objects.filter(owner=user, product_code='')
        for df in missing_qs.iterator():
            code, refreshed = _resolve_product_code(
                df.filename, resolve_file_path(df.file_path), df.program_name
            )
            if code:
                with transaction.atomic():
                    fields = ['product_code', 'updated_at']
                    if refreshed and refreshed != df.program_name:
                        df.program_name = refreshed
                        fields.insert(0, 'program_name')
                    df.product_code = code
                    df.save(update_fields=fields)
                fixed_count += 1
                results.append({
                    'id': df.id,
                    'filename': df.filename,
                    'product_code': code,
                    'status': 'fixed',
                    'reason': '',
                })
            else:
                    reason = 'file_missing' if not os.path.exists(resolve_file_path(df.file_path)) else 'no_match'
                    results.append({
                        'id': df.id,
                        'filename': df.filename,
                        'product_code': '',
                        'status': 'still_missing',
                        'reason': reason,
                    })

        return Response({
            'status': 'ok',
            'action': action,
            'fixed_count': fixed_count,
            'still_missing_count': len(results) - fixed_count,
            'results': results,
        })
