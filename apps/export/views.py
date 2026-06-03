import io
import pandas as pd
from django.shortcuts import get_object_or_404
from django.http import FileResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import excelize

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser
from apps.datafiles.services import get_cached_parsed_file
from apps.analysis.services.statistics import (
    detect_fail_data, get_site_column,
)
from .excelize_helpers import save_excelize
from .excel_builders import (
    build_to_excel_sheet, build_sigma_limit_sheet, build_batch_charts_xlsx,
)
from .export_ppt import build_batch_charts_pptx
from .export_complete import export_to_xlsx_optimized, export_to_csv


class ExportViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    # ── to_excel ────────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def to_excel(self, request):
        file_id = request.data.get('file_id')
        passfail = request.data.get('passfail', '全部')
        site_filter = request.data.get('site_filter', '全部')

        datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
        df, metadata, fmt = get_cached_parsed_file(int(file_id), request.user.pk)
        if df is None:
            return Response({'error': 'parse_failed'}, status=400)

        export_df = df.copy()

        # Empty string / None means "no filter selected" (frontend default). Only
        # an explicit, non-empty value other than the '全部' sentinel filters rows.
        if site_filter and site_filter != '全部':
            site_col = get_site_column(df)
            if site_col:
                export_df = export_df[export_df[site_col].astype(str) == str(site_filter)]

        export_df = export_df.reset_index(drop=True)

        if passfail and passfail != '全部':
            fail_indices, _, _ = detect_fail_data(export_df, metadata)
            fail_set = set(fail_indices)
            if passfail == 'Fail':
                export_df = export_df.loc[export_df.index.isin(fail_set)]
            elif passfail == 'Pass':
                export_df = export_df.loc[~export_df.index.isin(fail_set)]
            export_df = export_df.reset_index(drop=True)

        # Use old version's complete implementation
        buffer = export_to_xlsx_optimized(export_df, metadata)

        fname = datafile.filename.rsplit('.', 1)[0]
        return FileResponse(io.BytesIO(buffer), as_attachment=True,
                            filename=f'{fname}_analysis.xlsx',
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── to_csv ──────────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def to_csv(self, request):
        file_id = request.data.get('file_id')
        passfail = request.data.get('passfail', '全部')
        keep_header = request.data.get('keep_header', False)
        site_filter = request.data.get('site_filter', '全部')

        datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
        df, metadata, fmt = get_cached_parsed_file(int(file_id), request.user.pk)
        if df is None:
            return Response({'error': 'parse_failed'}, status=400)

        # Use old version's complete CSV export (simplified - no raw_lines support for now)
        csv_content = export_to_csv(
            df, metadata,
            site_filter=site_filter if site_filter != '全部' else None,
            passfail_filter=passfail if passfail != '全部' else None,
            keep_header=False,  # Simplified for now
            match_original_format=False,
            raw_lines=None
        )

        fname = datafile.filename.rsplit('.', 1)[0]
        return FileResponse(io.BytesIO(csv_content), as_attachment=True,
                            filename=f'{fname}_data.csv', content_type='text/csv')

    # ── sigma_limit ─────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def sigma_limit(self, request):
        file_id = request.data.get('file_id')
        sigma_level = request.data.get('sigma', 3)
        only_valid = request.data.get('only_valid_limits', False)

        datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
        df, metadata, fmt = get_cached_parsed_file(int(file_id), request.user.pk)
        if df is None:
            return Response({'error': 'parse_failed'}, status=400)

        f = excelize.new_file()
        build_sigma_limit_sheet(f, df, metadata, sigma_level, only_valid)
        buffer = save_excelize(f)

        fname = datafile.filename.rsplit('.', 1)[0]
        return FileResponse(io.BytesIO(buffer), as_attachment=True,
                            filename=f'{fname}_{sigma_level}sigma_Limit.xlsx',
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── html_report ─────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def html_report(self, request):
        file_id = request.data.get('file_id')
        datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
        df, metadata, fmt = get_cached_parsed_file(int(file_id), request.user.pk)
        if df is None:
            return Response({'error': 'parse_failed'}, status=400)

        total_rows = df.shape[0]
        from apps.analysis.services.statistics import calculate_fail_bin_statistics
        bin_stats = calculate_fail_bin_statistics(df, metadata)
        total_pass = 0
        for bv, s in bin_stats.items():
            try:
                if int(float(bv)) == 1:
                    total_pass = s['count']
            except Exception:
                pass
        yield_pct = (total_pass / total_rows * 100) if total_rows > 0 else 0

        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>ATE Report - {datafile.filename}</title>
<style>body{{font-family:Arial;margin:20px}}h1{{color:#2c3e50}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:center}}th{{background:#2c3e50;color:white}}</style></head>
<body><h1>ATE 数据分析报告</h1><p>文件: {datafile.filename} | 格式: {datafile.format_type} | 程序: {datafile.program_name}</p>
<h2>核心指标</h2><table><tr><th>总记录数</th><th>Pass</th><th>Fail</th><th>Yield</th></tr>
<tr><td>{total_rows}</td><td>{total_pass}</td><td>{total_rows - total_pass}</td><td>{yield_pct:.2f}%</td></tr></table></body></html>"""
        return Response(io.BytesIO(html.encode('utf-8')).read(), status=200,
                        content_type='text/html; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{datafile.filename}_report.html"'})

    # ── batch_charts ────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def batch_charts(self, request):
        file_id = request.data.get('file_id')
        params = request.data.get('params', [])
        fmt = request.data.get('format', 'xlsx')

        if not file_id:
            return Response({'error': 'file_id_required'}, status=400)

        datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
        df, metadata, fmt = get_cached_parsed_file(int(file_id), request.user.pk)
        if df is None:
            return Response({'error': 'parse_failed'}, status=400)

        if not params:
            params = [c for c in df.columns if df[c].dtype in ('int64', 'float64')][:10]

        if fmt == 'pptx':
            pptx_bytes = build_batch_charts_pptx(datafile, df, metadata, params)
            fname = datafile.filename.rsplit('.', 1)[0]
            return FileResponse(io.BytesIO(pptx_bytes), as_attachment=True,
                                filename=f'{fname}_batch_charts.pptx',
                                content_type='application/vnd.openxmlformats-officedocument.presentationml.presentation')
        else:
            f = excelize.new_file()
            build_batch_charts_xlsx(f, df, metadata, params)
            buffer = save_excelize(f)
            fname = datafile.filename.rsplit('.', 1)[0]
            return FileResponse(io.BytesIO(buffer), as_attachment=True,
                                filename=f'{fname}_batch_stats.xlsx',
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
