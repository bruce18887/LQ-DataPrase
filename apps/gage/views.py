import io
import os

from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import FileResponse

from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.common.export_naming import base_export_context, render_export_filename
from apps.gage.site_selection import select_site


def _unique_sheet_name(stem: str, site, used: set) -> str:
    """文件名 stem + 工位拼出唯一且 ≤31 字符的工作表名（Excel 限制）。"""
    base = f"{stem[:25]}_S{site}"
    name = base[:31]
    i = 2
    while name in used:
        suffix = f"_{i}"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


class GageViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def generate_summary(self, request):
        # 每个槽位 = 一个工位：assignments 为 [{file_id, site}, ...]，
        # site 即槽位编号（S1→1 … S8→8）。只导出对应工位的数据。
        assignments = request.data.get('assignments') or []
        only_bin1 = request.data.get('only_bin1', False)
        ignore_no_limit = request.data.get('ignore_no_limit', False)

        if not isinstance(assignments, list) or len(assignments) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        parsed = []
        for item in assignments:
            if not isinstance(item, dict) or item.get('file_id') is None or item.get('site') is None:
                return Response({'error': 'invalid_assignment'}, status=400)
            try:
                site = int(item['site'])
            except (TypeError, ValueError):
                return Response({'error': 'invalid_assignment'}, status=400)
            parsed.append((int(item['file_id']), site))

        # 同一文件+工位重复分配会产生同名工作表，直接拒绝。
        if len(set(parsed)) != len(parsed):
            return Response({'error': 'duplicate_assignment'}, status=400)

        failures = []
        file_datasets = []
        used_sheet_names: set = set()

        for fid, site in parsed:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk, df_obj)
            if df is None:
                continue

            if only_bin1:
                # 复用共享的 pass-bin 过滤（识别文本 'Bin1'/'BIN 1'），只读、不改缓存 df。
                from apps.analysis.services.statistics import filter_bin1_rows
                df = filter_bin1_rows(df, metadata)

            filtered, site_col, available = select_site(df, site)
            if site_col is None:
                failures.append({
                    'file_id': fid, 'filename': df_obj.filename, 'site': site,
                    'error': 'no_site_column', 'available_sites': [],
                })
                continue
            if filtered is None or filtered.empty:
                failures.append({
                    'file_id': fid, 'filename': df_obj.filename, 'site': site,
                    'error': 'site_not_found', 'available_sites': available,
                })
                continue

            label = f"{df_obj.filename}_S{site}"
            stem = os.path.splitext(df_obj.filename)[0]
            file_datasets.append({
                'filename': label,
                'sheet_name': _unique_sheet_name(stem, site, used_sheet_names),
                'site': site,
                'df': filtered,
                'metadata': metadata,
            })

        if failures:
            return Response({
                'error': failures[0]['error'],
                'message': _failure_message(failures),
                'details': failures,
            }, status=400)

        if len(file_datasets) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        # ── Build Excel workbook using old version's complete logic ──
        from apps.gage.gage_legacy_builder import build_gage_summary_excel
        save_buffer = build_gage_summary_excel(file_datasets, ignore_no_limit)

        fname = render_export_filename(
            request.user, 'gage', 'xlsx',
            {**base_export_context(request.user), 'file_count': len(file_datasets)},
        )
        return FileResponse(io.BytesIO(save_buffer), as_attachment=True, filename=fname,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def _failure_message(failures) -> str:
    """把失败项汇总成一条可读的中文提示（前端 toast 直接展示）。"""
    parts = []
    for f in failures:
        if f['error'] == 'no_site_column':
            parts.append(f"文件「{f['filename']}」不含工位（Site）列，无法按工位导出")
        else:
            avail = '、'.join(f['available_sites']) if f['available_sites'] else '无'
            parts.append(
                f"文件「{f['filename']}」不含 Site {f['site']} 的数据（该文件可用 Site：{avail}）"
            )
    return '；'.join(parts)
