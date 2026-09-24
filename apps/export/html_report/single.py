"""单文件 HTML 报告编排（仪表板单文件 Tab 的静态快照）。"""

from . import report_charts, sections, tables
from ._html import esc, png_data_uri

PASS_BIN_LABEL = 'Bin 1'


def _img(png: bytes, alt: str):
    if not png:
        return ''
    return (f'<div class="chart"><img alt="{esc(alt)}" '
            f'src="{png_data_uri(png)}" /></div>')


def _render_quiet(renderer, *args, **kwargs) -> bytes:
    """图表渲染失败降级为无图（绝不因单张图失败中断整份报告）。"""
    try:
        return renderer(*args, **kwargs)
    except Exception:
        return b''


def _bin_site_matrix(bin_table_data, cols):
    """从交叉表提取 Fail Bin 矩阵 → (row_labels, matrix)；无 Fail Bin 返回 ([], [])。"""
    rows = [r for r in (bin_table_data or [])
            if r.get('bin') and r.get('bin') not in ('Total', PASS_BIN_LABEL)]
    if not rows:
        return [], []
    labels = [r['bin'] for r in rows]
    matrix = [[int(r.get(c) or 0) for c in cols] for r in rows]
    return labels, matrix


def _meta_items(payload, metadata):
    md = metadata or {}
    return [
        ('文件', payload.get('filename')),
        ('格式', (payload.get('metrics') or {}).get('format')),
        ('程序', payload.get('program_name')),
        ('Lot ID', md.get('lot_id')),
        ('测试开始', md.get('start_time')),
        ('Operator', md.get('operator')),
        ('Station', md.get('station')),
        ('Handler', md.get('handler')),
    ]


def build_single_html_report(payload, metadata, uph, *, dpi, generated_at):
    """payload = compute_dashboard_summary(...)；uph = compute_uph(...) 或 None。"""
    metrics = payload.get('metrics') or {}
    filename = payload.get('filename') or ''

    parts = [
        sections.report_header(
            f'ATE 数据分析报告 - {filename}',
            f'文件: {filename} | 格式: {metrics.get("format") or "-"} | '
            f'程序: {payload.get("program_name") or "-"}',
        ),
        sections.meta_table(_meta_items(payload, metadata)),
        sections.overview_strip(metrics, uph),
        sections.alerts_block(payload.get('quality_alerts')),
    ]

    # Bin 构成（Pareto 图 + 表）
    bin_pie = payload.get('bin_pie_data') or []
    bin_chart = _render_quiet(
        report_charts.render_bin_pareto_payload,
        [b.get('name') for b in bin_pie], [b.get('value') for b in bin_pie], dpi=dpi,
    )
    parts.append(tables.section('Bin 构成',
                                _img(bin_chart, 'Bin Pareto') + tables.bin_table(bin_pie)))

    # Site 良率（柱线图 + 表）
    site_data = payload.get('site_yield_data') or []
    real_sites = [s for s in site_data if s.get('Site') != 'ALL']
    site_chart = _render_quiet(
        report_charts.render_site_yield_payload,
        [s.get('Site') for s in real_sites],
        [_to_float(s.get('Yield')) for s in real_sites],
        _to_float(metrics.get('yield_pct')),
        dpi=dpi,
    )
    parts.append(tables.section('Site 良率',
                                _img(site_chart, 'Site 良率') + tables.site_table(site_data)))

    # Bin×Site 交叉表 + 热力图
    cols = payload.get('bin_site_columns') or []
    labels, matrix = _bin_site_matrix(payload.get('bin_table_data'), cols)
    heat = _render_quiet(report_charts.render_bin_site_heatmap_payload,
                         labels, cols, matrix, dpi=dpi)
    parts.append(tables.section('Bin × Site 交叉表',
                                tables.bin_site_table(payload.get('bin_table_data'), cols)
                                + _img(heat, 'Bin×Site 热力图')))

    # 测试项总览 + CPK 分级 + Top Fail
    overview = payload.get('test_item_overview') or []
    parts.append(tables.section(
        '测试项总览',
        tables.cpk_strip(overview) + tables.test_item_table(overview)))

    top_fail = tables.top_fail_chips(payload.get('fail_test_items'))
    if top_fail:
        parts.append(tables.section('Top 10 Fail 测试项', top_fail))

    uph_body = tables.uph_table(uph)
    if uph_body:
        parts.append(tables.section('UPH 效率明细', uph_body))

    parts.append(sections.report_footer(generated_at))
    return _wrap_html(filename, ''.join(parts))


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _wrap_html(title, body):
    from .styles import REPORT_CSS
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<title>{esc(title)}</title><style>{REPORT_CSS}</style></head>'
            f'<body>{body}</body></html>')
