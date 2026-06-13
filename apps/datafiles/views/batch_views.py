"""Batch directory management views."""

import os
import shutil

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.datafiles.models import DataFile
from apps.datafiles.serializers import DataFileSerializer
from apps.datafiles.services import clear_parse_cache

from ._helpers import (
    _is_data_csv,
    _register_file,
    _user_upload_dir,
)


class BatchDirListView(APIView):
    """List batch directories on disk that may or may not have DataFile records."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        batch_base = _user_upload_dir(request.user, 'batch')
        if not os.path.isdir(batch_base):
            return Response([])

        # Get all batch_names that already have DataFile records
        registered = set(
            DataFile.objects.filter(owner=request.user, file_type='batch')
            .values_list('batch_name', flat=True)
        )

        # Get registered file paths per batch for partial-import detection.
        # Normalize separators: SFTP folder downloads historically stored
        # mixed-separator paths (``...\batch\dir\sub/file.csv``) while os.walk
        # below yields all-OS-separator paths — without normpath the set diff
        # never matches and a fully-imported batch shows as "unregistered".
        registered_files = {}
        # Per-batch DataFile rows for the frontend's "已导入批次" list, so the
        # batch grouping no longer depends on the paginated /files/ page (which
        # dropped older batches once newer files filled page 1).
        batch_file_rows = {}
        for df in DataFile.objects.filter(owner=request.user, file_type='batch').values(
            'id', 'filename', 'tags', 'batch_name', 'sub_batch', 'file_path',
            'format_type', 'row_count', 'col_count', 'program_name',
            'status', 'created_at',
        ):
            registered_files.setdefault(df['batch_name'], set()).add(
                os.path.normpath(df['file_path'])
            )
            batch_file_rows.setdefault(df['batch_name'], []).append({
                'id': df['id'],
                'filename': df['filename'],
                'tags': df['tags'] or [],
                'format_type': df['format_type'],
                'row_count': df['row_count'],
                'col_count': df['col_count'],
                'program_name': df['program_name'],
                'file_type': 'batch',
                'batch_name': df['batch_name'],
                'sub_batch': df['sub_batch'] or '',
                'status': df['status'],
                'created_at': df['created_at'].isoformat() if df['created_at'] else '',
            })

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
                    if not _is_data_csv(f):
                        continue
                    fp = os.path.join(root, f)
                    disk_paths.add(os.path.normpath(fp))
                    file_count += 1
                    try:
                        total_size += os.path.getsize(fp)
                    except OSError:
                        pass
            # Skip directories with no CSV files
            if file_count == 0:
                continue
            # Check registration: fully registered when all disk files are in DB
            batch_registered_paths = registered_files.get(dir_name, set())
            unregistered_count = len(disk_paths - batch_registered_paths)
            is_fully_registered = dir_name in registered and unregistered_count == 0
            result.append({
                'name': dir_name,
                'path': entry.path,
                'file_count': file_count,
                'total_size': total_size,
                'registered': is_fully_registered,
                'files': batch_file_rows.get(dir_name, []),
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

        batch_base = _user_upload_dir(request.user, 'batch')
        dir_path = os.path.join(batch_base, dir_name)
        if not os.path.isdir(dir_path):
            return Response({'error': f'目录 "{dir_name}" 不存在'}, status=404)

        # Get already-registered file paths for this batch (skip duplicates).
        # normpath both sides so mixed-separator legacy paths still dedup —
        # otherwise re-importing would create duplicate DataFile rows.
        existing_paths = set(
            os.path.normpath(p) for p in
            DataFile.objects.filter(
                owner=request.user, file_type='batch', batch_name=dir_name
            ).values_list('file_path', flat=True)
        )

        created = []
        with transaction.atomic():
            for root, _dirs, files in os.walk(dir_path):
                for f in files:
                    if not _is_data_csv(f):
                        continue
                    fp = os.path.join(root, f)
                    if os.path.normpath(fp) in existing_paths:
                        continue  # already registered
                    # 提取子批次名（相对路径的第一级目录）
                    rel_path = os.path.relpath(root, dir_path)
                    sub_batch = rel_path if rel_path != '.' else ''
                    try:
                        df = _register_file(request.user, fp, 'batch', dir_name, sub_batch)
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
        batch_base = _user_upload_dir(request.user, 'batch')
        dir_path = os.path.join(batch_base, dir_name)
        if not os.path.isdir(dir_path):
            return Response({'error': f'目录 "{dir_name}" 不存在'}, status=404)

        # Use transaction to ensure consistency
        with transaction.atomic():
            # Delete DataFile records for this batch
            deleted_count, _ = DataFile.objects.filter(
                owner=request.user, file_type='batch', batch_name=dir_name
            ).delete()

        # Delete directory from disk (outside transaction to avoid long locks)
        shutil.rmtree(dir_path, ignore_errors=True)
        clear_parse_cache()

        return Response({
            'status': 'ok',
            'deleted_files': deleted_count,
            'dir_name': dir_name,
        })


class SubBatchDeleteView(APIView):
    """Delete a sub-batch (subdirectory) from a batch directory."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, batch_name, sub_batch_name):
        batch_base = _user_upload_dir(request.user, 'batch')
        batch_dir = os.path.join(batch_base, batch_name)
        sub_batch_dir = os.path.join(batch_dir, sub_batch_name)

        if not os.path.isdir(batch_dir):
            return Response({'error': f'批次目录 "{batch_name}" 不存在'}, status=404)

        if not os.path.isdir(sub_batch_dir):
            return Response({'error': f'子批次目录 "{sub_batch_name}" 不存在'}, status=404)

        # Use transaction to ensure consistency
        with transaction.atomic():
            # Delete DataFile records for this sub-batch
            deleted_count, _ = DataFile.objects.filter(
                owner=request.user,
                file_type='batch',
                batch_name=batch_name,
                sub_batch=sub_batch_name,
            ).delete()

        # Delete sub-batch directory from disk
        shutil.rmtree(sub_batch_dir, ignore_errors=True)
        clear_parse_cache()

        return Response({
            'status': 'ok',
            'deleted_files': deleted_count,
            'batch_name': batch_name,
            'sub_batch_name': sub_batch_name,
        })
