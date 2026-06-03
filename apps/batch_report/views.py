import os, io
import pandas as pd
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from django.http import FileResponse

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser, BaseATEParser
from apps.datafiles.services import get_cached_parsed_file
from apps.analysis.services.statistics import (
    calculate_fail_bin_statistics, get_site_column,
    get_bin_column_name, compute_site_yield_data,
)

class BatchReportViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def list_batches(self, request):
        from django.db.models import Count
        batches = DataFile.objects.filter(owner=request.user)\
            .values('program_name').annotate(count=Count('id')).order_by('-count')
        return Response({'batches': list(batches)})

    @action(detail=False, methods=['post'])
    def scan_directory(self, request):
        dir_path = request.data.get('directory', '')
        if not dir_path or not os.path.isdir(dir_path):
            return Response({'error': 'invalid_directory'}, status=400)

        csv_files = []
        for root, _, files in os.walk(dir_path):
            for f in files:
                if f.endswith('.csv'):
                    csv_files.append(os.path.join(root, f))

        parsed = []
        for fp in csv_files:
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    head = f.read(4096)
                fmt = BaseATEParser.identify_format(head)
                if fmt != 'Unknown':
                    parsed.append({
                        'filename': os.path.basename(fp),
                        'path': fp,
                        'format': fmt,
                        'size': os.path.getsize(fp),
                    })
            except:
                pass

        return Response({'files': parsed, 'total': len(parsed)})

    @action(detail=False, methods=['post'])
    def generate_report(self, request):
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({'error': 'no_files'}, status=400)

        phases = []
        for fid in file_ids:
            df_obj = DataFile.objects.get(pk=fid, owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk)
            if df is None:
                continue

            total_rows = df.shape[0]
            bin_stats = calculate_fail_bin_statistics(df, metadata)
            total_pass = sum(1 for bv, s in bin_stats.items() if int(float(bv)) == 1)

            site_col = get_site_column(df)
            site_data = {}
            if site_col and get_bin_column_name(df_obj.format_type) in df.columns:
                yd = compute_site_yield_data(df, get_bin_column_name(df_obj.format_type), site_col)
                site_data = {d['Site']: {'yield': d['Yield'], 'total': d.get('Total', 0)} for d in yd.get('yield_data', [])}

            phases.append({
                'filename': df_obj.filename,
                'program_name': df_obj.program_name,
                'format': df_obj.format_type,
                'total': total_rows,
                'pass_count': total_pass,
                'fail_count': total_rows - total_pass,
                'yield_pct': round((total_pass / total_rows * 100), 2) if total_rows > 0 else 0,
                'site_yields': site_data,
            })

        wb = Workbook()
        ws = wb.active
        ws.title = "Batch Report"
        hf = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
        hfn = Font(bold=True, color="FFFFFF")
        ca = Alignment(horizontal="center", vertical="center")

        headers = ['文件名', '程序', '格式', '总数', 'Pass', 'Fail', '良率']
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.fill = hf
            cell.font = hfn
            cell.alignment = ca

        for r, p in enumerate(phases, 2):
            for c, v in enumerate([p['filename'], p['program_name'], p['format'], p['total'], p['pass_count'], p['fail_count'], f"{p['yield_pct']}%"], 1):
                ws.cell(row=r, column=c, value=v)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename='Batch_Report.xlsx',
                           content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    @action(detail=False, methods=['post'])
    def import_files(self, request):
        dir_path = request.data.get('directory', '')
        if not dir_path or not os.path.isdir(dir_path):
            return Response({'error': 'invalid_directory'}, status=400)

        imported = 0
        for root, _, files in os.walk(dir_path):
            for fname in files:
                if not fname.endswith('.csv'):
                    continue
                fp = os.path.join(root, fname)
                try:
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                        head = f.read(4096)
                    fmt = BaseATEParser.identify_format(head)
                    if fmt == 'Unknown':
                        continue
                    parser = get_parser(fmt)
                    df, metadata = parser.parse(fp)
                    if df is None:
                        continue
                    DataFile.objects.create(
                        owner=request.user, filename=fname, file_path=fp,
                        file_size=os.path.getsize(fp), format_type=fmt,
                        row_count=df.shape[0], col_count=df.shape[1],
                        program_name=metadata.get('program_name', ''), status='ready',
                    )
                    imported += 1
                except:
                    pass

        return Response({'imported': imported})
