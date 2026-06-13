"""Data browsing and maintenance views."""

import json
import os

import numpy as np
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
from apps.analysis.services.statistics import detect_fail_data, build_fail_mask, build_col_meta

from ._helpers import (
    _is_data_csv,
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


class DataConsistencyCheckView(APIView):
    """Check and fix data consistency between database and disk."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Check consistency: find orphaned DB records and orphaned disk files."""
        user = request.user
        batch_base = _user_upload_dir(user, 'batch')

        # Get all batch files from database
        db_files = DataFile.objects.filter(
            owner=user, file_type='batch'
        ).values_list('id', 'file_path', 'filename', 'batch_name')

        orphaned_db = []  # DB records with missing disk files
        for f_id, f_path, f_name, f_batch in db_files:
            if not os.path.exists(f_path):
                orphaned_db.append({
                    'id': f_id,
                    'filename': f_name,
                    'batch_name': f_batch,
                    'file_path': f_path,
                })

        # Get all disk files
        disk_files = set()
        if os.path.isdir(batch_base):
            for root, _dirs, files in os.walk(batch_base):
                for f in files:
                    if _is_data_csv(f):
                        disk_files.add(os.path.normpath(os.path.join(root, f)))

        # Get all registered file paths
        registered_paths = set(
            os.path.normpath(p) for p in
            DataFile.objects.filter(
                owner=user, file_type='batch'
            ).values_list('file_path', flat=True)
        )

        orphaned_disk = disk_files - registered_paths

        return Response({
            'orphaned_db_count': len(orphaned_db),
            'orphaned_disk_count': len(orphaned_disk),
            'orphaned_db': orphaned_db[:50],  # Limit to 50 for display
            'orphaned_disk': list(orphaned_disk)[:50],
        })

    def post(self, request):
        """Fix consistency issues."""
        action = request.data.get('action')
        if action not in ('delete_orphaned_db', 'delete_orphaned_disk'):
            return Response(
                {'error': 'action must be delete_orphaned_db or delete_orphaned_disk'},
                status=400,
            )

        user = request.user
        batch_base = _user_upload_dir(user, 'batch')

        if action == 'delete_orphaned_db':
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

        elif action == 'delete_orphaned_disk':
            # Delete disk files not in database
            registered_paths = set(
                os.path.normpath(p) for p in
                DataFile.objects.filter(
                    owner=user, file_type='batch'
                ).values_list('file_path', flat=True)
            )

            deleted_count = 0
            if os.path.isdir(batch_base):
                for root, _dirs, files in os.walk(batch_base):
                    for f in files:
                        if _is_data_csv(f):
                            fp = os.path.normpath(os.path.join(root, f))
                            if fp not in registered_paths:
                                try:
                                    os.remove(fp)
                                    deleted_count += 1
                                except OSError:
                                    pass

            # Clean up empty directories
            for root, dirs, files in os.walk(batch_base, topdown=False):
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
