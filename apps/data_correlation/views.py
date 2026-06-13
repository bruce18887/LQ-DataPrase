import io
import pandas as pd
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from django.http import FileResponse

from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.analysis.services.statistics import get_serial_column, get_1d_from

class CorrelationViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def analyze(self, request):
        file1_id = request.data.get('file1_id')
        file2_id = request.data.get('file2_id')
        threshold = float(request.data.get('threshold', 3.0))
        ignore_no_limit = request.data.get('ignore_no_limit', False)

        if not file1_id or not file2_id:
            return Response({'error': 'need_two_files'}, status=400)

        dfs = {}
        for fid, label in [(file1_id, 'ATE'), (file2_id, 'Bench')]:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk)
            if df is None:
                continue
            serial_col = get_serial_column(df)
            if serial_col:
                df['__serial__'] = pd.to_numeric(df[serial_col], errors='coerce')
            dfs[label] = {'df': df, 'metadata': metadata, 'serial': serial_col}

        if len(dfs) < 2:
            return Response({'error': 'parse_failed'}, status=400)

        ate_df = dfs['ATE']['df']
        bench_df = dfs['Bench']['df']
        ate_ser = ate_df['__serial__'] if '__serial__' in ate_df.columns else None
        bench_ser = bench_df['__serial__'] if '__serial__' in bench_df.columns else None

        if ate_ser is None or bench_ser is None:
            return Response({'error': 'no_serial_column'}, status=400)

        common_serials = set(ate_ser.dropna().astype(int)).intersection(set(bench_ser.dropna().astype(int)))
        numeric_cols_ate = [c for c in ate_df.columns if c not in ('__serial__',) and ate_df[c].dtype in ('int64', 'float64')]
        numeric_cols_bench = [c for c in bench_df.columns if c not in ('__serial__',) and bench_df[c].dtype in ('int64', 'float64')]
        common_params = sorted(set(numeric_cols_ate).intersection(numeric_cols_bench))

        summary = []
        for param in common_params[:100]:
            ate_vals = {}
            bench_vals = {}
            ate_idx = ate_df.set_index('__serial__')
            bench_idx = bench_df.set_index('__serial__')

            for ser in common_serials:
                if ser in ate_idx.index and ser in bench_idx.index:
                    try:
                        ate_vals[ser] = float(ate_idx.loc[ser, param].iloc[0] if isinstance(ate_idx.loc[ser, param], pd.Series) else ate_idx.loc[ser, param])
                        bench_vals[ser] = float(bench_idx.loc[ser, param].iloc[0] if isinstance(bench_idx.loc[ser, param], pd.Series) else bench_idx.loc[ser, param])
                    except:
                        pass

            diffs = []
            for ser in ate_vals:
                if ser in bench_vals:
                    try:
                        diff_pct = abs(ate_vals[ser] - bench_vals[ser]) / max(abs(ate_vals[ser]), 1e-9) * 100
                        diffs.append((ser, ate_vals[ser], bench_vals[ser], diff_pct))
                    except:
                        pass

            fail_count = sum(1 for d in diffs if d[3] > threshold)
            summary.append({
                'param': param,
                'compared': len(diffs),
                'fail_count': fail_count,
                'pass_rate': round((len(diffs) - fail_count) / len(diffs) * 100, 2) if diffs else 0,
                'max_diff': round(max(d[3] for d in diffs), 2) if diffs else 0,
            })

        return Response({
            'common_serials': len(common_serials),
            'common_params': len(common_params),
            'summary': summary,
            'params': common_params,
        })
