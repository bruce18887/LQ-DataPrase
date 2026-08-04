"""Data browsing and maintenance views."""

import json
import os

import numpy as np
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import get_parser
from apps.datafiles.serializers import DataFileSerializer, ParseHistorySerializer
from apps.datafiles.services import get_cached_parsed_file, clear_parse_cache
from apps.datafiles.utils import extract_product_code
from apps.analysis.services.statistics import detect_fail_data, build_fail_mask, build_col_meta

from ._helpers import (
    _register_file,
    _resolve_product_code,
    _scan_orphaned_disk,
    _user_upload_dir,
)


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

        fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata)
        fail_mask = build_fail_mask(fail_cells)
        col_meta = build_col_meta(df, metadata)

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


# Consistency-check write actions and the roles allowed to run them. Delete is
# destructive, so it is restricted to administrators; import/fix are additive
# and mirror upload privileges (administrator + user). Viewers may read the
# check results (GET stays IsAuthenticated) but cannot mutate anything.
_DELETE_ACTIONS = ('delete_orphaned_db', 'delete_orphaned_disk')
_MUTATE_ACTIONS = ('import_orphaned_disk', 'fix_product_codes')
_ALL_ACTIONS = _DELETE_ACTIONS + _MUTATE_ACTIONS


class DataConsistencyCheckView(APIView):
    """Check and fix data consistency between database and disk."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Check consistency: orphaned DB records, orphaned disk files,
        and files whose product_code could not be extracted at registration."""
        user = request.user

        # Orphaned DB records: batch rows whose disk file no longer exists.
        db_files = DataFile.objects.filter(
            owner=user, file_type='batch'
        ).values_list('id', 'file_path', 'filename', 'batch_name', 'sub_batch')

        orphaned_db = []
        for f_id, f_path, f_name, f_batch, f_sub in db_files:
            if not os.path.exists(f_path):
                orphaned_db.append({
                    'id': f_id,
                    'filename': f_name,
                    'batch_name': f_batch,
                    'sub_batch': f_sub,
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
            file_missing = not os.path.exists(df['file_path'])
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

        return Response({
            'orphaned_db_count': len(orphaned_db),
            'orphaned_disk_count': len(orphaned_disk),
            'missing_product_code_count': len(missing),
            'orphaned_db': orphaned_db[:50],  # Limit to 50 for display
            'orphaned_disk': orphaned_disk[:50],
            'missing_product_code': missing[:50],
        })

    def post(self, request):
        """Fix consistency issues. Actions always recompute the full affected
        set server-side (not the GET's 50-row display slice)."""
        action = request.data.get('action')
        if action not in _ALL_ACTIONS:
            return Response(
                {'error': 'action must be one of: ' + ', '.join(_ALL_ACTIONS)},
                status=400,
            )

        user = request.user
        role = getattr(user, 'role', '')
        if action in _DELETE_ACTIONS and role != 'administrator':
            return Response(
                {'error': '仅管理员可执行删除操作'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if action in _MUTATE_ACTIONS and role not in ('administrator', 'user'):
            return Response(
                {'error': '当前角色无权执行该操作'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if action == 'delete_orphaned_db':
            return self._delete_orphaned_db(user, action)
        elif action == 'delete_orphaned_disk':
            return self._delete_orphaned_disk(user, action)
        elif action == 'import_orphaned_disk':
            return self._import_orphaned_disk(user, action)
        return self._fix_product_codes(user, action)

    def _delete_orphaned_db(self, user, action):
        # Delete DB records with missing disk files
        db_files = DataFile.objects.filter(
            owner=user, file_type='batch'
        ).values_list('id', 'file_path')

        deleted_ids = []
        for f_id, f_path in db_files:
            if not os.path.exists(f_path):
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
                df.filename, df.file_path, df.program_name
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
                    reason = 'file_missing' if not os.path.exists(df.file_path) else 'no_match'
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
