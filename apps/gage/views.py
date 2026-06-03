import io
import pandas as pd
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import FileResponse
import excelize

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser
from apps.datafiles.services import get_cached_parsed_file
from apps.export.excelize_helpers import save_excelize
from apps.gage.services.rr_analysis import compute_rr_statistics
from apps.gage.excelize_layout import build_summary_sheet, build_per_file_sheets


class GageViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def generate_summary(self, request):
        file_ids = request.data.get('file_ids', [])
        only_bin1 = request.data.get('only_bin1', False)
        ignore_no_limit = request.data.get('ignore_no_limit', False)

        if len(file_ids) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        # ── Parse files ──
        file_datasets = []
        for fid in file_ids:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk)
            if df is None:
                continue
            if only_bin1:
                from apps.analysis.services.statistics import get_bin_column_name
                bin_col = get_bin_column_name(df_obj.format_type)
                if bin_col in df.columns:
                    bin_numeric = pd.to_numeric(df[bin_col], errors='coerce')
                    df = df[bin_numeric == 1].copy()
            file_datasets.append({
                'filename': df_obj.filename,
                'df': df,
                'metadata': metadata,
            })

        if len(file_datasets) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        # ── Build Excel workbook using old version's complete logic ──
        from apps.gage.excelize_layout import build_gage_summary_excel
        save_buffer = build_gage_summary_excel(file_datasets, ignore_no_limit)

        return FileResponse(io.BytesIO(save_buffer), as_attachment=True, filename='Gage_Summary.xlsx',
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
