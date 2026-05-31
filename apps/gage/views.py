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
            parser = get_parser(df_obj.format_type)
            df, metadata = parser.parse(df_obj.file_path)
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
                'df': df, 'metadata': metadata,
            })

        if len(file_datasets) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        # ── Determine common test columns ──
        all_test_cols = set()
        non_numeric_keywords = {'min', 'max', 'lower limit', 'upper limit', 'n/a', 'na', '-', 'none', ''}

        for ds in file_datasets:
            for col in ds['df'].columns:
                if ds['df'][col].dtype not in ('int64', 'float64'):
                    continue
                if ignore_no_limit:
                    mins = ds['metadata'].get('mins', {})
                    maxs = ds['metadata'].get('maxs', {})
                    if col not in mins or col not in maxs:
                        continue
                    min_str = str(mins[col]).strip()
                    max_str = str(maxs[col]).strip()
                    if min_str.lower() in non_numeric_keywords or max_str.lower() in non_numeric_keywords:
                        continue
                    try:
                        float(min_str)
                        float(max_str)
                    except (ValueError, TypeError):
                        continue
                all_test_cols.add(col)

        common_cols = None
        for ds in file_datasets:
            numeric_cols = set(c for c in ds['df'].columns if ds['df'][c].dtype in ('int64', 'float64'))
            file_cols = numeric_cols & all_test_cols if ignore_no_limit else numeric_cols
            if common_cols is None:
                common_cols = file_cols
            else:
                common_cols = common_cols & file_cols

        if not common_cols:
            return Response({'error': 'no_common_items'}, status=400)

        all_test_cols = sorted(common_cols)

        # ── Compute R&R statistics for each test item ──
        test_name_stats = {
            test_name: compute_rr_statistics(file_datasets, test_name)
            for test_name in all_test_cols
        }
        bad1_count = sum(1 for s in test_name_stats.values() if s['is_bad'])

        # ── Build Excel workbook ──
        f = excelize.new_file()
        sheet_list = f.get_sheet_list()
        if sheet_list:
            f.set_sheet_name(sheet_list[0], "Summary")

        build_summary_sheet(f, file_datasets, all_test_cols, test_name_stats, bad1_count)
        build_per_file_sheets(f, file_datasets, all_test_cols)

        save_buffer = save_excelize(f)
        return FileResponse(io.BytesIO(save_buffer), as_attachment=True, filename='Gage_Summary.xlsx',
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
