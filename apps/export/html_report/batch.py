"""批次 HTML 报告编排（仪表板批次良率 Tab 的静态快照）。"""

from apps.export.formatting import format_percent_value

from . import report_charts, sections, tables
from ._html import fmt_num
from .single import PASS_BIN_LABEL, _img, _render_quiet, _to_float, _wrap_html


def _yield_item(label, field, pct):
    try:
        y = float(pct)
        cls = 'good' if y >= 95 else ('warn' if y >= 90 else 'bad')
    except (TypeError, ValueError):
        cls = ''
    return (label, field, f'{"yield-value " + cls}'.strip(),
            f'{format_percent_value(pct)}%')


def _kpi_items(kpi):
    kpi = kpi or {}
    return [
        ('文件数', 'file_count', 'kpi-value', fmt_num(kpi.get('file_count'))),
        ('投入总数', 'input_total', 'kpi-value', fmt_num(kpi.get('input_total'))),
        ('总记录', 'total', 'kpi-value', fmt_num(kpi.get('total'))),
        ('Pass', 'pass', 'kpi-value pass', fmt_num(kpi.get('pass'))),
        ('Fail', 'fail', 'kpi-value fail', fmt_num(kpi.get('fail'))),
        _yield_item('总良率', 'yield', kpi.get('overall_yield')),
    ]


def _qa_table(qa_checks):
    if not qa_checks:
        return ''
    rows = [[c.get('check', ''), c.get('expected', ''), c.get('actual', ''), c.get('status', '')]
            for c in qa_checks]
    return tables.simple_table(['校验项', '期望', '实际', '结果'], rows, left_cols=1)


def _phase_summary_table(phase_summary):
    rows = [[p.get('phase', ''), p.get('stage', ''), fmt_num(p.get('file_count')),
             fmt_num(p.get('total')), fmt_num(p.get('pass_count')),
             fmt_num(p.get('fail_count')), tables.yield_cell(p.get('yield_pct'))]
            for p in (phase_summary or [])]
    return tables.simple_table(
        ['阶段', 'Stage', '文件数', '总数', 'Pass', 'Fail', '良率'],
        rows, left_cols=2, empty_text='无阶段数据')


def _stage_table(stage_yields):
    rows = [[s.get('stage', ''), fmt_num(s.get('file_count')), fmt_num(s.get('total')),
             fmt_num(s.get('pass_count')), fmt_num(s.get('fail_count')),
             tables.yield_cell(s.get('yield_pct'))]
            for s in (stage_yields or [])]
    return tables.simple_table(
        ['Stage', '文件数', '总数', 'Pass', 'Fail', '良率'],
        rows, left_cols=1, empty_text='无阶段数据')


def _phase_detail_table(phases):
    rows = []
    for p in (phases or []):
        rows.append([
            p.get('phase', ''), p.get('wafer_id', ''), p.get('program_name', ''),
            p.get('lot_id', ''), fmt_num(p.get('total')), fmt_num(p.get('pass_count')),
            fmt_num(p.get('fail_count')), tables.yield_cell(p.get('yield_pct')),
            p.get('start_time', ''), p.get('end_time', ''), p.get('handler', ''),
        ])
    return tables.simple_table(
        ['阶段', 'WAFER_ID', '程序名称', 'Lot ID', '测试总数', 'Pass', 'Fail',
         '良率', '开始时间', '结束时间', 'Handler'],
        rows, left_cols=4, empty_text='无阶段明细')


def _site_matrix_table(site_matrix, sorted_sites):
    sites = list(sorted_sites or [])
    if not site_matrix or not sites:
        return ''
    headers = ['阶段', 'WAFER_ID'] + [f'Site {s}' for s in sites] + ['All Site']
    rows = []
    for r in site_matrix:
        row = [r.get('phase', ''), r.get('wafer_id', '')]
        for s in sites:
            row.append(f'{r.get(f"{s}_ratio", "-")} ({r.get(f"{s}_yield", "-")})')
        row.append(f'{r.get("all_ratio", "-")} ({r.get("all_yield", "-")})')
        rows.append(row)
    return tables.simple_table(headers, rows, left_cols=2)


def build_batch_html_report(payload, *, dpi, generated_at):
    """payload = ``compute_batch_yield_data(user, batch_name, for_html_report=True)``。

    入口先验载荷形状，**不是**防御式编程的仪式：下面那四段分区（趋势 / Bin 分布 /
    Bin×Site）读的全是 ``payload.get(...) or {}`` / ``or []`` ⇒ 漏掉
    ``for_html_report=True`` 时函数**正常返回**，报告只是静默少三块，
    HTTP 200、文件名照常，用户与日志都看不出差别（2026-10-30 审查 Important 2）。

    认门的依据 2026-10-31 换过一次：原先「那四把 key 同生同灭，验 ``bin_site_columns``
    一把就够」成立，因为 JSON 分支根本不带那四把。现在 JSON 端点为了把响应键集合恢复到
    D3 之前那 14 把，把五把**空占位**也带了回来（``trend_data={}``、其余四把 ``[]``），
    键在不在已分不出两形状 —— 于是改看 ``site_pass_data``：它**只有 JSON 形状才带**
    （HTML 报告不读它，``for_html_report=True`` 那份连这个键都没有；两半各由
    ``test/backend/test_batch_report_payload.py`` 的
    ``test_html_payload_carries_report_partitions_and_drops_site_pass_data`` 与
    ``test_json_compat_keys_are_empty_placeholders_not_computed_data`` 钉住）。
    「``bin_site_columns`` 都不存在」那一半**保留** ⇒ 连服务产物都不是的手搓载荷照样进不来。
    这里不能改用「四把分区是否为空」认门：``aggregate_bin_site_table`` 对**没有 Site 列**
    的批次合法地返回 ``([], [])``（见 ``apps/batch_report/aggregation.py`` 的提前返回），
    那种报告今天能出，拿空当标记就会把它打成 500。
    判据：``test/backend/test_html_report_batch.py`` 的
    ``test_json_shaped_payload_is_refused_not_rendered_empty``、
    ``test_hand_built_payload_missing_the_partitions_is_still_refused`` 与
    ``test_html_shaped_payload_with_empty_site_partitions_passes_the_guard``。
    """
    if 'site_pass_data' in payload or 'bin_site_columns' not in payload:
        raise ValueError(
            '批次 HTML 报告的载荷不是 for_html_report=True 那一份：'
            '带 "site_pass_data" ⇒ 这是 JSON 形状（或至少不是 HTML 分支）的载荷；'
            '缺 "bin_site_columns" ⇒ 压根不是 compute_batch_yield_data 的产物。'
            '必须用 compute_batch_yield_data(user, batch_name, for_html_report=True) '
            '生成载荷')
    batch_name = payload.get('batch_name') or ''
    parts = [
        sections.report_header(f'批次良率报告 - {batch_name}',
                               f'批次: {batch_name} | 文件数: {fmt_num((payload.get("kpi") or {}).get("file_count"))}'),
        sections.kpi_strip(_kpi_items(payload.get('kpi'))),
    ]

    qa = _qa_table(payload.get('qa_checks'))
    if qa:
        parts.append(tables.section('QA 数量校验', qa))

    parts.append(tables.section(
        '阶段汇总',
        _stage_table(payload.get('stage_yields')) + _phase_summary_table(payload.get('phase_summary'))))

    # 良率趋势（x 轴优先用阶段短标签，长文件名不可读）
    trend = payload.get('trend_data') or {}
    phase_by_name = {p.get('filename'): p.get('phase') for p in (payload.get('phases') or [])}
    tlabels = [phase_by_name.get(f.get('filename')) or (f.get('filename') or '')
               for f in (trend.get('files') or [])]
    tyields = [_to_float(d.get('yield')) for d in (trend.get('trend_data') or [])]
    trend_chart = _render_quiet(report_charts.render_yield_trend_payload,
                                tlabels, tyields, dpi=dpi)
    if trend_chart:
        parts.append(tables.section('良率趋势', _img(trend_chart, '良率趋势')))

    parts.append(tables.section('阶段明细表', _phase_detail_table(payload.get('phases'))))
    parts.append(tables.section(
        'Site × 阶段 矩阵',
        _site_matrix_table(payload.get('site_matrix'), payload.get('sorted_sites'))))

    # Bin 分布 + Bin×Site 交叉表 + 热力图
    dist = payload.get('bin_distribution') or []
    dist_chart = _render_quiet(
        report_charts.render_bin_pareto_payload,
        [b.get('name') for b in dist], [b.get('value') for b in dist], dpi=dpi)
    cols = payload.get('bin_site_columns') or []
    labels, matrix = _bin_site_matrix(payload.get('bin_table_data'), cols)
    heat = _render_quiet(report_charts.render_bin_site_heatmap_payload,
                         labels, cols, matrix, dpi=dpi)
    bin_body = (_img(dist_chart, 'Bin 分布')
                + tables.simple_table(['Bin', '数量'],
                                      [[b.get('name', ''), fmt_num(b.get('value'))] for b in dist],
                                      left_cols=1, empty_text='无 Bin 数据')
                + tables.bin_site_table(payload.get('bin_table_data'), cols)
                + _img(heat, 'Bin×Site 热力图'))
    parts.append(tables.section('Bin 分布', bin_body))

    uph_body = tables.uph_table(payload.get('uph'))
    if uph_body:
        parts.append(tables.section('UPH 效率明细', uph_body))

    parts.append(sections.report_footer(generated_at))
    return _wrap_html(f'批次良率报告 - {batch_name}', ''.join(parts))


def _bin_site_matrix(bin_table_data, cols):
    rows = [r for r in (bin_table_data or [])
            if r.get('bin') and r.get('bin') not in ('Total', PASS_BIN_LABEL)]
    if not rows:
        return [], []
    return [r['bin'] for r in rows], [[int(r.get(c) or 0) for c in cols] for r in rows]
