import io

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
import excelize
from django.http import FileResponse

from apps.export.excelize_helpers import make_header_style, make_data_style, save_excelize
from apps.export.user_prefs import get_export_dpi
from apps.export.html_report import build_batch_html_report
from apps.common.export_naming import base_export_context, render_export_filename

from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.analysis.services.statistics import (
    calculate_fail_bin_statistics, compute_pass_yield,
)
from apps.batch_report.services import (
    compute_batch_yield_data, BatchNotAvailableError,
)


class BatchReportViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def list_batches(self, request):
        # 单条聚合查询代替逐 batch 循环 count()（N+1 → 1）
        batches = (
            DataFile.objects.filter(owner=request.user, file_type='batch')
            .exclude(batch_name='')
            .values('batch_name')
            .annotate(count=Count('id'))
            .order_by('-batch_name')
        )
        result = [
            {'batch_name': b['batch_name'], 'count': b['count']}
            for b in batches
        ]
        return Response({'batches': result})

    @action(detail=False, methods=['get'])
    def batch_yield_data(self, request):
        """Return computed yield data for a batch of imported files."""
        batch_name = request.query_params.get('batch_name', '')
        if not batch_name:
            return Response({'error': 'batch_name required'}, status=400)

        try:
            payload = compute_batch_yield_data(request.user, batch_name)
        except BatchNotAvailableError as e:
            return Response({'error': str(e)}, status=404)
        return Response(payload)

    @action(detail=False, methods=['post'])
    def batch_html_report(self, request):
        """批次良率的自包含 HTML 报告（含内联 base64 图表）。"""
        batch_name = request.data.get('batch_name', '')
        if not batch_name:
            return Response({'error': 'batch_name required'}, status=400)

        try:
            payload = compute_batch_yield_data(request.user, batch_name)
        except BatchNotAvailableError as e:
            return Response({'error': str(e)}, status=404)

        html = build_batch_html_report(
            payload,
            dpi=get_export_dpi(request.user),
            generated_at=timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S'),
        )
        # 命名复用既有 batch_report 模板 key（不新增 key，守 accounts 契约）
        fname = render_export_filename(
            request.user, 'batch_report', 'html',
            {**base_export_context(request.user),
             'batch_name': batch_name,
             'file_count': (payload.get('kpi') or {}).get('file_count', 0)},
        )
        return FileResponse(io.BytesIO(html.encode('utf-8')), as_attachment=True,
                            filename=fname,
                            content_type='text/html; charset=utf-8')

    @action(detail=False, methods=['post'])
    def generate_report(self, request):
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({'error': 'no_files'}, status=400)

        # fid 非整数 → 400（原实现 int(fid) 抛 ValueError → 500）；
        # 文件不存在 / 不属于当前用户 → 404（原实现 objects.get 抛
        # DoesNotExist → 500）。与 buyoff / gage 等同类端点的
        # get_object_or_404 口径对齐：同一类参数不得一处 404 一处 500。
        normalized_ids = []
        for fid in file_ids:
            try:
                normalized_ids.append(int(fid))
            except (TypeError, ValueError):
                return Response(
                    {'error': 'invalid_file_id', 'detail': f'file_id 必须为整数: {fid!r}'},
                    status=400)

        phases = []
        for fid in normalized_ids:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(fid, request.user.pk, df_obj)
            if df is None:
                continue

            total_rows = df.shape[0]
            bin_stats = calculate_fail_bin_statistics(df, metadata)
            yield_result = compute_pass_yield(bin_stats, total_rows)

            phases.append({
                'filename': df_obj.filename,
                'program_name': df_obj.program_name,
                'format': df_obj.format_type,
                'total': total_rows,
                'pass_count': yield_result['pass_count'],
                'fail_count': yield_result['fail_count'],
                'yield_pct': yield_result['yield_pct'],
            })

        f = excelize.new_file()
        f.set_sheet_name("Sheet1", "Batch Report")
        header_style = make_header_style(f, 11)
        data_style = make_data_style(f)

        headers = ['文件名', '程序', '格式', '总数', 'Pass', 'Fail', '良率']
        f.set_sheet_row("Batch Report", "A1", headers)
        f.set_cell_style("Batch Report", "A1", "G1", header_style)

        for r, p in enumerate(phases, 2):
            row_vals = [
                p['filename'], p['program_name'], p['format'], p['total'],
                p['pass_count'], p['fail_count'], f"{p['yield_pct']}%",
            ]
            f.set_sheet_row("Batch Report", f"A{r}", row_vals)
        if phases:
            f.set_cell_style("Batch Report", "A2", f"G{len(phases) + 1}", data_style)

        fname = render_export_filename(
            request.user, 'batch_report', 'xlsx',
            {**base_export_context(request.user),
             'batch_name': request.data.get('batch_name', ''),
             'file_count': len(phases)},
        )
        return FileResponse(io.BytesIO(save_excelize(f)), as_attachment=True,
                           filename=fname,
                           content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
