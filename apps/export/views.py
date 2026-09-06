import io
import json
from django.http import FileResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import excelize

from apps.common.file_loading import load_user_file, FileLoadError
from apps.common.export_naming import base_export_context, render_export_filename
from apps.analysis.services.statistics import (
    detect_fail_data, get_site_column,
    calculate_fail_bin_statistics, compute_pass_yield,
    filter_bin1_rows,
)
from apps.datafiles.parsers.base import SYSTEM_COLUMNS
from apps.datafiles.views.browse_views import _apply_filter_model, _apply_sort
from .columns import measurable_numeric_columns
from .formatting import format_percent_value
from .excelize_helpers import save_excelize
from .excel_builders import (
    build_sigma_limit_sheet,
)
from .export_ppt import build_batch_charts_pptx
from .export_complete import export_to_xlsx_optimized
from .export_csv import export_to_csv

# σ 档位合法区间：前端只提供 3/4/6，给个宽裕的上下界拦住 0 / 负数 / 99
MIN_SIGMA_LEVEL = 1
MAX_SIGMA_LEVEL = 10
DEFAULT_SIGMA_LEVEL = 3
DEFAULT_CHART_PARAMS = 10


def parse_sigma_level(raw):
    """请求里的 σ 档位 → ``int``；缺失/非法 → ``None``（调用方据此返回 400）。

    缺陷 #7：旧代码 ``request.data.get('sigma', 3)`` 不做类型转换，表单编码
    把 ``6`` 变成 ``'6'``，下游 ``mean_val - sigma_level * std_val`` 抛
    ``TypeError: can only concatenate str`` → 500。bool 是 int 的子类，但
    ``True`` 不是合法档位，显式排除；``3.5`` / ``'abc'`` / ``[3]`` 同样非法。
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        as_float = float(raw)
    except (TypeError, ValueError):
        return None
    if not as_float.is_integer():
        return None
    level = int(as_float)
    return level if MIN_SIGMA_LEVEL <= level <= MAX_SIGMA_LEVEL else None


def _parse_grid_model(raw, expect):
    """Parse ag-grid sort/filter model from an export request.

    Frontend sends JSON-encoded ``sort_model`` (array) / ``filter_model``
    (object) identical to /browse/ IRM params. Malformed or mistyped values
    degrade to empty (no sorting/filtering) instead of 400 — export must not
    fail because a filter widget sent something odd.
    """
    if not raw:
        return [] if expect == list else {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return [] if expect == list else {}
    return parsed if isinstance(parsed, expect) else ([] if expect == list else {})


def _apply_export_filters(df, metadata, request_data):
    """Apply passfail/site/sort/filter_model to ``df`` like /browse/ does.

    Shared by to_excel/to_csv so both exports match what the grid shows.
    Filter order mirrors DataBrowserView: site → filter_model → passfail →
    sort (search is grid-local and intentionally not exported).
    """
    export_df = df.copy()

    site_filter = request_data.get('site_filter') or ''
    if site_filter and site_filter != '全部':
        site_col = get_site_column(export_df)
        if site_col:
            export_df = export_df[export_df[site_col].astype(str) == str(site_filter)]

    filter_model = _parse_grid_model(request_data.get('filter_model'), dict)
    if filter_model:
        export_df = _apply_filter_model(export_df, filter_model)

    passfail = request_data.get('passfail') or ''
    if passfail and passfail != '全部':
        fail_indices, _, _ = detect_fail_data(export_df, metadata)
        fail_set = set(fail_indices)
        if str(passfail).lower() == 'fail':
            export_df = export_df.loc[export_df.index.isin(fail_set)]
        elif str(passfail).lower() == 'pass':
            export_df = export_df.loc[~export_df.index.isin(fail_set)]
        export_df = export_df.reset_index(drop=True)

    sort_model = _parse_grid_model(request_data.get('sort_model'), list)
    if sort_model:
        export_df = _apply_sort(export_df, sort_model)

    return export_df


class ExportViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    # ── to_excel ────────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def to_excel(self, request):
        file_id = request.data.get('file_id')

        try:
            df, datafile, metadata = load_user_file(request, file_id)
        except FileLoadError as e:
            return Response({'error': e.error_code}, status=400)

        # 与表格一致：passfail/site/sort/filter_model 全量应用
        export_df = _apply_export_filters(df, metadata, request.data)

        # Use old version's complete implementation
        # 默认隐藏列（系统设置 → 表格设置）：列保留在导出文件中但设为 Excel 隐藏列
        user_settings = getattr(request.user, 'settings', None)
        hidden_columns = []
        if user_settings is not None:
            hidden_columns = user_settings.default_hidden_columns or []
        buffer = export_to_xlsx_optimized(export_df, metadata, hidden_columns=hidden_columns)

        fname = render_export_filename(
            request.user, 'to_excel', 'xlsx',
            {**base_export_context(request.user),
             'filename': datafile.filename.rsplit('.', 1)[0]},
        )
        return FileResponse(io.BytesIO(buffer), as_attachment=True,
                            filename=fname,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── to_csv ──────────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def to_csv(self, request):
        file_id = request.data.get('file_id')

        try:
            df, datafile, metadata = load_user_file(request, file_id)
        except FileLoadError as e:
            return Response({'error': e.error_code}, status=400)

        # 与表格一致：passfail/site/sort/filter_model 全量应用
        # （此前走 bin==1 语义，与表格 detect_fail_data 不一致，一并对齐）。
        export_df = _apply_export_filters(df, metadata, request.data)

        csv_content = export_to_csv(export_df, metadata)

        fname = render_export_filename(
            request.user, 'to_csv', 'csv',
            {**base_export_context(request.user),
             'filename': datafile.filename.rsplit('.', 1)[0]},
        )
        return FileResponse(io.BytesIO(csv_content), as_attachment=True,
                            filename=fname, content_type='text/csv')

    # ── sigma_limit ─────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def sigma_limit(self, request):
        file_id = request.data.get('file_id')
        # 缺陷 #7：必须转 int 并校验范围——非法值返回 400，而不是让下游
        # 算 sigma 区间时抛 TypeError 变成 500
        sigma_level = parse_sigma_level(request.data.get('sigma', DEFAULT_SIGMA_LEVEL))
        if sigma_level is None:
            return Response(
                {'error': 'invalid_sigma',
                 'detail': f'sigma 必须是 {MIN_SIGMA_LEVEL}~{MAX_SIGMA_LEVEL} 的整数'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        only_valid = request.data.get('only_valid_limits', False)

        try:
            df, datafile, metadata = load_user_file(request, file_id)
        except FileLoadError as e:
            return Response({'error': e.error_code}, status=400)

        # data_only_bin1: export only pass-bin rows (chart-config switch)
        if request.data.get('data_only_bin1', False):
            df = filter_bin1_rows(df, metadata)

        f = excelize.new_file()
        build_sigma_limit_sheet(f, df, metadata, sigma_level, only_valid)
        buffer = save_excelize(f)

        fname = render_export_filename(
            request.user, 'sigma_limit', 'xlsx',
            {**base_export_context(request.user),
             'filename': datafile.filename.rsplit('.', 1)[0],
             'sigma': sigma_level},
        )
        return FileResponse(io.BytesIO(buffer), as_attachment=True,
                            filename=fname,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── html_report ─────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def html_report(self, request):
        file_id = request.data.get('file_id')
        try:
            df, datafile, metadata = load_user_file(request, file_id)
        except FileLoadError as e:
            return Response({'error': e.error_code}, status=400)

        # data_only_bin1：与 sigma_limit / batch_charts 分支同口径（缺陷 #8）。
        # 此前 HTML 报告不应用该开关，良率与 xlsx 图表对不上。
        if request.data.get('data_only_bin1', False):
            df = filter_bin1_rows(df, metadata)

        total_rows = df.shape[0]
        bin_stats = calculate_fail_bin_statistics(df, metadata)
        yield_result = compute_pass_yield(bin_stats, total_rows)
        total_pass = yield_result['pass_count']
        # 6 位口径（缺陷 #12）：``{:.2f}`` 会把 99.998% 显示成误导性的 100.00%
        yield_text = format_percent_value(yield_result['yield_pct'])

        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>ATE Report - {datafile.filename}</title>
<style>body{{font-family:Arial;margin:20px}}h1{{color:#2c3e50}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:center}}th{{background:#2c3e50;color:white}}</style></head>
<body><h1>ATE 数据分析报告</h1><p>文件: {datafile.filename} | 格式: {datafile.format_type} | 程序: {datafile.program_name}</p>
<h2>核心指标</h2><table><tr><th>总记录数</th><th>Pass</th><th>Fail</th><th>Yield</th></tr>
<tr><td>{total_rows}</td><td>{total_pass}</td><td>{total_rows - total_pass}</td><td>{yield_text}%</td></tr></table></body></html>"""
        # FileResponse (not Response + hand-written header): Django wsgi response
        # headers are latin-1 only — a hand-written Content-Disposition with a
        # Chinese source filename raises UnicodeEncodeError. FileResponse emits
        # RFC 5987 filename*=UTF-8''... encoding automatically.
        fname = render_export_filename(
            request.user, 'html_report', 'html',
            {**base_export_context(request.user),
             'filename': datafile.filename.rsplit('.', 1)[0]},
        )
        return FileResponse(io.BytesIO(html.encode('utf-8')), as_attachment=True,
                            filename=fname, content_type='text/html; charset=utf-8')

    # ── batch_charts ────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def batch_charts(self, request):
        file_id = request.data.get('file_id')
        params = request.data.get('params', [])
        fmt = request.data.get('format', 'xlsx')

        # Chart config from frontend
        show_limit = request.data.get('show_limit', True)
        show_3sigma = request.data.get('show_3sigma', False)
        show_4sigma = request.data.get('show_4sigma', False)
        show_6sigma = request.data.get('show_6sigma', True)
        show_normal = request.data.get('show_normal', False)
        show_kde = request.data.get('show_kde', False)

        try:
            df, datafile, metadata = load_user_file(request, file_id)
        except FileLoadError as e:
            return Response({'error': e.error_code}, status=400)

        # data_only_bin1: export charts for pass-bin rows only. Applied
        # BEFORE the default params branch so the default column list is
        # also derived from the filtered frame.
        if request.data.get('data_only_bin1', False):
            df = filter_bin1_rows(df, metadata)

        if not params:
            # 缺陷 #11：旧白名单 ``dtype in ('int64','float64')`` 漏掉 float32/int32
            # 等窄 dtype，并把 bool / 系统记录列（SW_Bin）当成可分析测量值
            params = measurable_numeric_columns(
                df, exclude=SYSTEM_COLUMNS.get(metadata.get('format', 'CTA8290D'), []),
            )[:DEFAULT_CHART_PARAMS]

        site_col = get_site_column(df)

        base_ctx = {**base_export_context(request.user),
                    'filename': datafile.filename.rsplit('.', 1)[0]}

        if fmt == 'pptx':
            # 缺陷 #6：pptx 分支必须收到与 xlsx 分支完全相同的图形开关，
            # 否则同一份配置导出的 pptx 与 xlsx 图形内容不一致
            pptx_bytes = build_batch_charts_pptx(
                datafile, df, metadata, params,
                show_limit=show_limit, show_3sigma=show_3sigma,
                show_4sigma=show_4sigma, show_6sigma=show_6sigma,
                show_normal=show_normal, show_kde=show_kde,
            )
            fname = render_export_filename(request.user, 'batch_charts', 'pptx', base_ctx)
            return FileResponse(io.BytesIO(pptx_bytes), as_attachment=True,
                                filename=fname,
                                content_type='application/vnd.openxmlformats-officedocument.presentationml.presentation')
        else:
            from .export_complete import build_batch_charts_xlsx_with_charts
            xlsx_bytes = build_batch_charts_xlsx_with_charts(
                df, metadata, params, site_col=site_col,
                show_limit=show_limit, show_3sigma=show_3sigma,
                show_4sigma=show_4sigma, show_6sigma=show_6sigma,
                show_normal=show_normal, show_kde=show_kde,
            )
            fname = render_export_filename(request.user, 'batch_charts', 'xlsx', base_ctx)
            return FileResponse(io.BytesIO(xlsx_bytes), as_attachment=True,
                                filename=fname,
                                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
