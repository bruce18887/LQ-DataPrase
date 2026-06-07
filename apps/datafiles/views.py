import csv
import io
import json
import os
import shutil
import time
import zipfile

import numpy as np
import pandas as pd
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import BaseATEParser, get_parser
from apps.datafiles.serializers import (
    DataFileListSerializer,
    DataFileSerializer,
    FileUploadSerializer,
    ParseHistorySerializer,
)
from apps.datafiles.tasks import parse_data_file_task
from apps.datafiles.services import get_cached_parsed_file
from apps.datafiles.utils import extract_product_code

ARCHIVE_EXTENSIONS = {'.zip', '.7z', '.rar'}


def _is_archive(filename):
    return os.path.splitext(filename)[1].lower() in ARCHIVE_EXTENSIONS


def _extract_archive(file_path, dest_dir):
    """Extract ZIP/7z/RAR to dest_dir. Returns list of extracted file paths."""
    ext = os.path.splitext(file_path)[1].lower()
    extracted = []

    if ext == '.zip':
        with zipfile.ZipFile(file_path, 'r') as zf:
            for info in zf.infolist():
                if info.is_dir() or info.filename.startswith('__MACOSX'):
                    continue
                # Flatten: use only the basename
                name = os.path.basename(info.filename)
                if not name:
                    continue
                out_path = os.path.join(dest_dir, name)
                with zf.open(info) as src, open(out_path, 'wb') as dst:
                    dst.write(src.read())
                extracted.append(out_path)

    elif ext == '.7z':
        import py7zr
        with py7zr.SevenZipFile(file_path, 'r') as sz:
            for name, bio in sz.readall().items():
                basename = os.path.basename(name)
                if not basename:
                    continue
                out_path = os.path.join(dest_dir, basename)
                with open(out_path, 'wb') as dst:
                    dst.write(bio.read())
                extracted.append(out_path)

    elif ext == '.rar':
        import rarfile
        with rarfile.RarFile(file_path) as rf:
            for info in rf.infolist():
                if info.is_dir():
                    continue
                basename = os.path.basename(info.filename)
                if not basename:
                    continue
                out_path = os.path.join(dest_dir, basename)
                with rf.open(info) as src, open(out_path, 'wb') as dst:
                    dst.write(src.read())
                extracted.append(out_path)

    return extracted


def _register_file(user, file_path, file_type='single', batch_name='', source_mtime=None):
    """Parse a file and create DataFile + ParseHistory records.

    source_mtime: optional aware datetime of the original source file's
    modification time. When None for archive-extracted/disk files, the
    on-disk mtime is used; for direct uploads it stays None unless provided.
    """
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    format_type = 'Unknown'
    program_name = ''
    row_count, col_count = 0, 0

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(4096)
        format_type = BaseATEParser.identify_format(head)
        if format_type != 'Unknown':
            parser = get_parser(format_type)
            df, metadata = parser.parse(file_path)
            if df is not None:
                row_count = df.shape[0]
                col_count = df.shape[1]
                program_name = metadata.get('program_name', '')
    except Exception:
        pass

    datafile = DataFile.objects.create(
        owner=user,
        filename=filename,
        file_path=file_path,
        file_size=file_size,
        format_type=format_type if format_type != 'Unknown' else 'CTA8290D',
        file_type=file_type,
        batch_name=batch_name,
        row_count=row_count,
        col_count=col_count,
        program_name=program_name,
        product_code=extract_product_code(filename),
        source_mtime=source_mtime,
        status='ready' if format_type != 'Unknown' else 'error',
    )

    ParseHistory.objects.create(
        user=user,
        datafile=datafile,
        filename=filename,
        filepath=file_path,
        format_type=datafile.format_type,
        rows=row_count,
        cols=col_count,
    )

    return datafile


def _user_upload_dir(user_id, file_type='single'):
    """Return per-user upload directory: media/data/<user_id>/<file_type>/"""
    path = os.path.join(settings.MEDIA_ROOT, 'data', str(user_id), file_type)
    os.makedirs(path, exist_ok=True)
    return path


def _disk_mtime(file_path):
    """Return the on-disk modification time as an aware datetime (or None)."""
    try:
        return timezone.make_aware(
            timezone.datetime.fromtimestamp(os.path.getmtime(file_path)),
            timezone.get_current_timezone(),
        )
    except (OSError, ValueError):
        return None


def _parse_last_modified(value):
    """Parse a browser-provided last_modified epoch-ms value into a datetime.

    Returns an aware datetime, or None if the value is absent/invalid.
    """
    if value in (None, ''):
        return None
    try:
        seconds = float(value) / 1000.0
        return timezone.make_aware(
            timezone.datetime.fromtimestamp(seconds),
            timezone.get_current_timezone(),
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _delete_datafile_on_disk(datafile):
    """Remove the on-disk file(s) backing a DataFile (best-effort)."""
    file_path = datafile.file_path
    try:
        if datafile.file_type == 'batch' and datafile.batch_name:
            # Batch: delete the entire batch directory
            batch_dir = os.path.dirname(file_path)
            if os.path.isdir(batch_dir):
                shutil.rmtree(batch_dir, ignore_errors=True)
        else:
            # Single: delete just the file
            if os.path.exists(file_path):
                os.remove(file_path)
    except OSError:
        pass


class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ['filename', 'batch_name', 'program_name']
    filterset_fields = ['product_code', 'format_type', 'file_type']
    ordering_fields = ['created_at', 'source_mtime', 'filename', 'file_size']

    def get_queryset(self):
        return DataFile.objects.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.action == 'list':
            return DataFileListSerializer
        return DataFileSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def destroy(self, request, *args, **kwargs):
        datafile = self.get_object()
        _delete_datafile_on_disk(datafile)
        datafile.delete()
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
            _delete_datafile_on_disk(datafile)
        deleted_count = qs.count()
        qs.delete()
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


class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        # Support both single 'file' and multiple 'files' keys
        files = request.FILES.getlist('files') or request.FILES.getlist('file')
        if not files:
            return Response({'error': '未选择文件'}, status=400)

        # Optional per-file last_modified (epoch ms), parallel to the files list.
        last_modified_list = request.data.getlist('last_modified')

        upload_dir = _user_upload_dir(request.user.id, 'single')
        created = []

        for idx, uploaded_file in enumerate(files):
            base_name = uploaded_file.name
            file_path = os.path.join(upload_dir, base_name)

            lm_value = last_modified_list[idx] if idx < len(last_modified_list) else None
            browser_mtime = _parse_last_modified(lm_value)

            # Handle filename collision
            if os.path.exists(file_path):
                ts = int(time.time())
                name, ext = os.path.splitext(base_name)
                file_path = os.path.join(upload_dir, f"{name}_{ts}{ext}")

            # Save uploaded file
            with open(file_path, 'wb+') as dest:
                for chunk in uploaded_file.chunks():
                    dest.write(chunk)

            # If archive, extract and register each extracted file
            if _is_archive(base_name):
                extract_dir = file_path + '_extracted'
                os.makedirs(extract_dir, exist_ok=True)
                try:
                    extracted = _extract_archive(file_path, extract_dir)
                    batch_name = os.path.splitext(base_name)[0]
                    for ext_path in extracted:
                        # Archives preserve the original file mtime on disk.
                        df = _register_file(
                            request.user, ext_path, 'batch', batch_name,
                            source_mtime=_disk_mtime(ext_path),
                        )
                        created.append(df)
                except Exception:
                    pass
                # Remove the archive itself (keep extracted files)
                os.remove(file_path)
            else:
                df = _register_file(
                    request.user, file_path, 'single',
                    source_mtime=browser_mtime,
                )
                created.append(df)

        return Response(
            DataFileSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )


class BatchDirListView(APIView):
    """List batch directories on disk that may or may not have DataFile records."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        batch_base = _user_upload_dir(request.user.id, 'batch')
        if not os.path.isdir(batch_base):
            return Response([])

        # Get all batch_names that already have DataFile records
        registered = set(
            DataFile.objects.filter(owner=request.user, file_type='batch')
            .values_list('batch_name', flat=True)
        )

        # Get registered file paths per batch for partial-import detection
        registered_files = {}
        for df in DataFile.objects.filter(owner=request.user, file_type='batch').values('batch_name', 'file_path'):
            registered_files.setdefault(df['batch_name'], set()).add(df['file_path'])

        result = []
        for entry in os.scandir(batch_base):
            if not entry.is_dir():
                continue
            dir_name = entry.name
            # Count CSV files and total size
            file_count = 0
            total_size = 0
            disk_paths = set()
            for root, _dirs, files in os.walk(entry.path):
                for f in files:
                    if not f.lower().endswith('.csv'):
                        continue
                    fp = os.path.join(root, f)
                    disk_paths.add(fp)
                    file_count += 1
                    try:
                        total_size += os.path.getsize(fp)
                    except OSError:
                        pass
            # Skip directories with no CSV files
            if file_count == 0:
                continue
            # Check registration: fully registered, partial, or none
            batch_registered_paths = registered_files.get(dir_name, set())
            is_registered = dir_name in registered
            unregistered_count = len(disk_paths - batch_registered_paths)
            result.append({
                'name': dir_name,
                'path': entry.path,
                'file_count': file_count,
                'total_size': total_size,
                'registered': is_registered and unregistered_count == 0,
            })

        # Sort: unregistered first, then by name
        result.sort(key=lambda x: (x['registered'], x['name']))
        return Response(result)


class BatchDirImportView(APIView):
    """Import all files from a batch directory into DataFile records."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        dir_name = request.data.get('dir_name')
        if not dir_name:
            return Response({'error': 'dir_name is required'}, status=400)

        batch_base = _user_upload_dir(request.user.id, 'batch')
        dir_path = os.path.join(batch_base, dir_name)
        if not os.path.isdir(dir_path):
            return Response({'error': f'目录 "{dir_name}" 不存在'}, status=404)

        # Get already-registered file paths for this batch (skip duplicates)
        existing_paths = set(
            DataFile.objects.filter(
                owner=request.user, file_type='batch', batch_name=dir_name
            ).values_list('file_path', flat=True)
        )

        created = []
        for root, _dirs, files in os.walk(dir_path):
            for f in files:
                if not f.lower().endswith('.csv'):
                    continue
                fp = os.path.join(root, f)
                if fp in existing_paths:
                    continue  # already registered
                try:
                    df = _register_file(request.user, fp, 'batch', dir_name)
                    created.append(df)
                except Exception:
                    continue

        return Response(
            DataFileSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )


class BatchDirDeleteView(APIView):
    """Delete a batch directory from disk and its DataFile records."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, dir_name):
        batch_base = _user_upload_dir(request.user.id, 'batch')
        dir_path = os.path.join(batch_base, dir_name)
        if not os.path.isdir(dir_path):
            return Response({'error': f'目录 "{dir_name}" 不存在'}, status=404)

        # Delete DataFile records for this batch
        deleted_count, _ = DataFile.objects.filter(
            owner=request.user, file_type='batch', batch_name=dir_name
        ).delete()

        # Delete directory from disk
        shutil.rmtree(dir_path, ignore_errors=True)

        return Response({
            'status': 'ok',
            'deleted_files': deleted_count,
            'dir_name': dir_name,
        })


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


class DataBrowserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        datafile_id = request.query_params.get('datafile_id')
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 50))
        search = request.query_params.get('search', '')
        pass_filter = request.query_params.get('pass_filter', '')

        if not datafile_id:
            return Response(
                {'error': 'datafile_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        datafile = get_object_or_404(
            DataFile, pk=datafile_id, owner=request.user
        )

        if not os.path.exists(datafile.file_path):
            return Response(
                {'error': 'File not found on disk'},
                status=status.HTTP_404_NOT_FOUND,
            )

        df, metadata, fmt = get_cached_parsed_file(datafile.id, request.user.pk)
        if df is None:
            return Response({'error': 'parse_failed'}, status=400)

        from apps.analysis.services.statistics import detect_fail_data
        fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata)
        fail_mask = {}
        for idx, cols in fail_cells.items():
            fail_mask[str(idx)] = cols

        col_meta = {}
        units = metadata.get('units', {})
        mins = metadata.get('mins', {})
        maxs = metadata.get('maxs', {})
        for col in df.columns:
            col_meta[col] = {
                'unit': units.get(col, '') if isinstance(units, dict) else '',
                'min': mins.get(col, '') if isinstance(mins, dict) else '',
                'max': maxs.get(col, '') if isinstance(maxs, dict) else '',
            }

        fail_set = set(fail_indices)

        # Apply filters at DataFrame level (fast pandas ops) before paginating
        if search:
            search_lower = search.lower()
            mask = df.apply(
                lambda row: any(search_lower in str(v).lower() for v in row),
                axis=1,
            )
            df = df[mask]
            # Re-index after filter so fail_indices still map correctly
            # Use original index values for fail_cells lookup
            filtered_indices = df.index.tolist()

        if pass_filter:
            if pass_filter.upper() == 'PASS':
                df = df[~df.index.isin(fail_set)]
            elif pass_filter.upper() == 'FAIL':
                df = df[df.index.isin(fail_set)]

        total = len(df)
        start = (page - 1) * page_size
        end = start + page_size

        # Slice first, then convert only the paged rows to dicts
        paged_df = df.iloc[start:end]
        paged_df_clean = paged_df.replace({np.nan: None, np.inf: None, -np.inf: None})
        paged_rows = paged_df_clean.to_dict(orient='records')

        # Attach fail_cells metadata using original DataFrame index
        for i, (orig_idx, row) in enumerate(zip(paged_df.index, paged_rows)):
            row['__fail_cells__'] = json.dumps(fail_cells.get(orig_idx, []))

        parser = get_parser(datafile.format_type)
        bin_column = parser.get_bin_column_name()

        return Response({
            'headers': list(df.columns),
            'rows': paged_rows,
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'fail_row_count': len(set(fail_indices)),
            'fail_mask': fail_mask,
            'col_meta': col_meta,
            'bin_column': bin_column,
        })
