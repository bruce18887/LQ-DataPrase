import io
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import FileResponse

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser
from apps.datafiles.services import get_cached_parsed_file
from apps.export.excelize_helpers import save_excelize
from apps.common.export_naming import base_export_context, render_export_filename


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
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk, df_obj)
            if df is None:
                continue
            if only_bin1:
                # Use the shared pass-bin filter so text bins ('Bin1'/'BIN 1')
                # are recognized; the old pd.to_numeric(...) == 1 turned every
                # text bin into NaN → False and silently emptied the frame
                # (defect #9). filter_bin1_rows is imported read-only from
                # apps.analysis and never mutates the cached df.
                from apps.analysis.services.statistics import filter_bin1_rows
                df = filter_bin1_rows(df, metadata)
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

        fname = render_export_filename(
            request.user, 'gage', 'xlsx',
            {**base_export_context(request.user), 'file_count': len(file_datasets)},
        )
        return FileResponse(io.BytesIO(save_buffer), as_attachment=True, filename=fname,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
