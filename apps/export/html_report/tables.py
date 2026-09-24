"""HTML 报告表格渲染：通用原语 + 单文件报告各表。

**所有**单元格值都经 ``esc()``；需要着色/对齐的单元格用 ``Cell`` 包装。
"""

from collections import namedtuple

from ._html import esc, fmt_num, fmt_pct

# Cell(value, css_class) —— value 会被 esc()，css_class 为附加样式类。
Cell = namedtuple('Cell', 'value cls', defaults=('',))

CPK_LEVELS = ['A', 'B', 'C', 'D']
CPK_META = {
    'A': ('cpk-a', 'A✓ 优秀'),
    'B': ('cpk-b', 'B● 良好'),
    'C': ('cpk-c', 'C◆ 一般'),
    'D': ('cpk-d', 'D▼ 不足'),
}


def section(title, body):
    """带标题的区块；body 为空串时不渲染。"""
    if not body:
        return ''
    return f'<h2>{esc(title)}</h2>{body}'


def simple_table(headers, rows, left_cols=0, empty_text='无数据'):
    """通用表格。headers/rows 为原始值（自动转义），可含 Cell。"""
    if not rows:
        return f'<div class="empty">{esc(empty_text)}</div>'

    def th(i, h):
        return f'<th class="left">{esc(h)}</th>' if i < left_cols else f'<th>{esc(h)}</th>'

    head = ''.join(th(i, h) for i, h in enumerate(headers))
    body_rows = []
    for row in rows:
        tds = []
        for i, cell in enumerate(row):
            base = 'left' if i < left_cols else ''
            if isinstance(cell, Cell):
                cls = (base + ' ' + cell.cls).strip()
                val = esc(cell.value)
            else:
                cls = base
                val = esc(cell)
            tds.append(f'<td class="{cls}">{val}</td>' if cls else f'<td>{val}</td>')
        body_rows.append('<tr>' + ''.join(tds) + '</tr>')
    return (f'<table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table>')


def yield_cell(pct):
    """良率单元格：>=95 绿 / >=90 橙 / 否则红。"""
    try:
        y = float(pct)
    except (TypeError, ValueError):
        return Cell('-', '')
    cls = 'yield-value good' if y >= 95 else ('yield-value warn' if y >= 90 else 'yield-value bad')
    return Cell(f'{y:.2f}%', cls)


# ── 单文件报告各表 ───────────────────────────────────────────────

def bin_table(bin_pie_data):
    rows = [[b.get('name', ''), fmt_num(b.get('value'))] for b in (bin_pie_data or [])]
    return simple_table(['Bin', '数量'], rows, left_cols=1, empty_text='无 Bin 数据')


def site_table(site_yield_data):
    rows = []
    for s in site_yield_data or []:
        rows.append([
            s.get('Site', ''),
            yield_cell(s.get('Yield')),
            fmt_num(s.get('Total')),
            fmt_num(s.get('PassCount')),
        ])
    return simple_table(['Site', '良率', 'Total', 'Pass'], rows, left_cols=1, empty_text='无 Site 数据')


def bin_site_table(bin_table_data, bin_site_columns):
    cols = list(bin_site_columns or [])
    if not bin_table_data or not cols:
        return ''
    headers = ['Bin'] + [f'Site {c}' for c in cols] + ['合计']
    rows = []
    for r in bin_table_data:
        row = [r.get('bin', '')]
        row += [fmt_num(r.get(c)) for c in cols]
        row.append(fmt_num(r.get('all_site')))
        rows.append(row)
    return simple_table(headers, rows, left_cols=1)


def test_item_table(rows):
    data = []
    for r in (rows or []):
        cpk = r.get('cpk')
        cpk_cell = Cell(f'{cpk:.2f}', '') if cpk is not None else '-'
        fail = fmt_num(r.get('fail_count'))
        pct = fmt_pct(r.get('percentage'))
        data.append([
            r.get('name', ''),
            fmt_num(r.get('data_count')),
            fmt_num(r.get('mean')),
            fmt_num(r.get('std')),
            fmt_num(r.get('min')),
            fmt_num(r.get('max')),
            fmt_num(r.get('lsl')),
            fmt_num(r.get('usl')),
            cpk_cell,
            r.get('cpk_level') or '-',
            f'{fail} ({pct}%)',
        ])
    headers = ['参数名称', '数据点数', 'Mean', 'STD', 'Min', 'Max',
               'LSL', 'USL', 'CPK', 'CPK Level', 'Fail']
    return simple_table(headers, data, left_cols=1, empty_text='无测试项数据')


def cpk_strip(rows):
    """CPK A/B/C/D 四色堆叠比例条 + 图例。"""
    counts = {lv: 0 for lv in CPK_LEVELS}
    for r in (rows or []):
        lv = (r.get('cpk_level') or '').strip()[:1].upper()
        if lv in counts:
            counts[lv] += 1
    total = sum(counts.values())
    if total == 0:
        return ''
    segs = ''.join(
        f'<span class="{CPK_META[lv][0]}" style="flex:{counts[lv]}" '
        f'title="{esc(CPK_META[lv][1])}: {counts[lv]}"></span>'
        for lv in CPK_LEVELS if counts[lv]
    )
    legend = ' · '.join(
        f'{esc(CPK_META[lv][1])} {counts[lv]}' for lv in CPK_LEVELS if counts[lv]
    )
    return (f'<div class="cpk-strip">{segs}</div>'
            f'<div class="cpk-legend">CPK 分级：{legend}</div>')


def top_fail_chips(fail_test_items, limit=10):
    items = sorted(fail_test_items or [], key=lambda x: x.get('fail_count', 0), reverse=True)[:limit]
    if not items:
        return ''
    chips = ''.join(
        f'<span class="chip">{esc(i.get("name"))} · {fmt_num(i.get("fail_count"))}</span>'
        for i in items
    )
    return f'<div class="topfail">{chips}</div>'


def uph_table(uph):
    if not uph:
        return ''
    rows = [['总 UPH', fmt_num(uph.get('uph'))],
            ['平均测试时间', f'{fmt_pct(uph.get("avg_test_time"), 3)} s'],
            ['总测试量', fmt_num(uph.get('total_tested'))],
            ['总耗时', f'{fmt_pct(uph.get("total_time_seconds"), 1)} s']]
    base = simple_table(['指标', '值'], rows, left_cols=1)
    by_site = uph.get('by_site') or []
    if by_site:
        site_rows = [[s.get('site', ''), fmt_num(s.get('tested')), fmt_num(s.get('uph'))]
                     for s in by_site]
        base += simple_table(['Site', '测试量', 'UPH'], site_rows, left_cols=1)
    return base
