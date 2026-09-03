import io
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import FileResponse
import excelize

from apps.analysis.services.statistics import filter_bin1_rows
from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.buyoff.services import compute_buyoff_stats
from apps.buyoff.excelize_layout import build_buyoff_form
from apps.export.excelize_helpers import save_excelize
from apps.common.export_naming import base_export_context, render_export_filename


class BuyoffViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def identify_common_items(self, request):
        file_ids = request.data.get('file_ids', [])
        if not file_ids or len(file_ids) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        datasets = {}
        all_cols = []
        for fid in file_ids:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk, df_obj)
            if df is None:
                continue
            numeric_cols = [c for c in df.columns if df[c].dtype in ('int64', 'float64')]
            datasets[df_obj.filename] = {'df': df, 'metadata': metadata, 'numeric_cols': numeric_cols}
            all_cols.append(set(numeric_cols))

        if not datasets:
            return Response({'error': 'parse_failed'}, status=400)

        common = all_cols[0]
        for s in all_cols[1:]:
            common = common & s

        file_specific = {}
        for fname, ds in datasets.items():
            specific = [c for c in ds['numeric_cols'] if c not in common]
            file_specific[fname] = specific

        return Response({
            'common_items': sorted(common),
            'common_count': len(common),
            'file_specific': file_specific,
            'file_count': len(datasets),
        })

    @action(detail=False, methods=['post'])
    def generate_form(self, request):
        file_ids = request.data.get('file_ids', [])
        only_bin1 = request.data.get('only_bin1', False)
        role_map = request.data.get('role_map', {})

        if len(file_ids) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        # Load and parse files
        datasets = {}
        for fid in file_ids:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk, df_obj)
            if df is None:
                continue
            if only_bin1:
                # 用统一的 Bin1 判定（支持 1 / '1' / 'Bin1' / 'BIN 1'）；
                # 旧写法 pd.to_numeric(errors='coerce') == 1 会把文本 bin 全变 NaN
                # → 整个 df 被静默清空。
                meta = dict(metadata or {})
                meta.setdefault('format', df_obj.format_type)
                df = filter_bin1_rows(df, meta)
            numeric_cols = [c for c in df.columns if df[c].dtype in ('int64', 'float64')]
            datasets[df_obj.filename] = {
                'df': df, 'metadata': metadata,
                'numeric_cols': numeric_cols, 'file_id': fid,
            }

        # 与兄弟端点 identify_common_items 对齐：全部解析失败时 400，
        # 否则下面的 all_col_sets[0] 会 IndexError → 500。
        if not datasets:
            return Response({'error': 'parse_failed'}, status=400)

        # Find common numeric columns
        all_col_sets = [set(d['numeric_cols']) for d in datasets.values()]
        common = all_col_sets[0]
        for s in all_col_sets[1:]:
            common = common & s
        common_items = sorted(common)

        if not common_items:
            return Response({'error': 'no_common_items'}, status=400)

        # Build role mapping
        role_mapping = {}
        if role_map:
            file_id_to_name = {ds['file_id']: fname for fname, ds in datasets.items()}
            for role, fid in role_map.items():
                if fid and fid in file_id_to_name:
                    role_mapping[role] = file_id_to_name[fid]
        else:
            filenames = list(datasets.keys())
            role_names = ['FT', 'QA1', 'QA2']
            for i, fname in enumerate(filenames):
                r = role_names[i] if i < len(role_names) else f'File{i}'
                role_mapping[r] = fname

        # Compute stats for each (role, param)
        all_stats = {}
        for role_name, fname in role_mapping.items():
            ds = datasets[fname]
            all_stats[role_name] = {}
            for param in common_items:
                s = compute_buyoff_stats(ds['df'], ds['metadata'], param)
                if s:
                    all_stats[role_name][param] = s

        # Determine order: FT, QA1, QA2
        ordered_roles = [r for r in ['FT', 'QA1', 'QA2'] if r in role_mapping]

        # Build Excel with excelize
        f = excelize.new_file()
        build_buyoff_form(f, role_mapping, common_items, all_stats, datasets, ordered_roles)

        buffer = save_excelize(f)
        fname = render_export_filename(
            request.user, 'buyoff', 'xlsx',
            {**base_export_context(request.user), 'file_count': len(file_ids)},
        )
        return FileResponse(io.BytesIO(buffer), as_attachment=True, filename=fname,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
