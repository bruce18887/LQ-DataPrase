import csv
import io
import json
import os

import numpy as np
import pandas as pd
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
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


class DataFileViewSet(viewsets.ModelViewSet):
    serializer_class = DataFileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return DataFile.objects.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.action == 'list':
            return DataFileListSerializer
        return DataFileSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = request.FILES['file']

        upload_dir = os.path.join(settings.BASE_DIR, 'media', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, uploaded_file.name)
        with open(file_path, 'wb+') as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)

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
            owner=request.user,
            filename=uploaded_file.name,
            file_path=file_path,
            file_size=uploaded_file.size,
            format_type=format_type if format_type != 'Unknown' else 'CTA8290D',
            row_count=row_count,
            col_count=col_count,
            program_name=program_name,
            status='ready' if format_type != 'Unknown' else 'error',
        )

        ParseHistory.objects.create(
            user=request.user,
            datafile=datafile,
            filename=uploaded_file.name,
            filepath=file_path,
            format_type=format_type if format_type != 'Unknown' else 'CTA8290D',
            rows=row_count,
            cols=col_count,
        )

        return Response(
            DataFileSerializer(datafile).data,
            status=status.HTTP_201_CREATED,
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

        parser = get_parser(datafile.format_type)
        df, metadata = parser.parse(datafile.file_path)
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

        df_clean = df.replace({np.nan: None, np.inf: None, -np.inf: None})
        all_rows_with_idx = list(enumerate(df_clean.to_dict(orient='records')))

        fail_set = set(fail_indices)

        if search:
            search_lower = search.lower()
            all_rows_with_idx = [
                (orig_idx, row) for orig_idx, row in all_rows_with_idx
                if any(search_lower in str(v).lower() for v in row.values())
            ]

        if pass_filter:
            if pass_filter.upper() == 'PASS':
                all_rows_with_idx = [(orig_idx, row) for orig_idx, row in all_rows_with_idx if orig_idx not in fail_set]
            elif pass_filter.upper() == 'FAIL':
                all_rows_with_idx = [(orig_idx, row) for orig_idx, row in all_rows_with_idx if orig_idx in fail_set]

        for orig_idx, row in all_rows_with_idx:
            row['__fail_cells__'] = json.dumps(fail_cells.get(orig_idx, []))

        all_rows = [row for _, row in all_rows_with_idx]

        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        paged_rows = all_rows[start:end]

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
            'bin_column': parser.get_bin_column_name(),
        })
