"""HTML 报告页头 / 元数据 / 总览条 / 质量警报 / 页脚 区块。"""

from apps.export.formatting import format_percent_value

from ._html import esc, fmt_num, fmt_pct
from .tables import simple_table


def report_header(title, subtitle=''):
    sub = f'<p class="report-meta">{esc(subtitle)}</p>' if subtitle else ''
    return f'<h1>{esc(title)}</h1>{sub}'


def meta_table(items):
    """items: list[(label, value)] → 两列键值表（全部转义）。"""
    body = ''.join(
        f'<tr><th class="left">{esc(label)}</th><td class="left">{esc(value)}</td></tr>'
        for label, value in items
    )
    return f'<table><tbody>{body}</tbody></table>'


def _strip(items):
    """items: list[(label, field, css_class, text)] → 总览/ KPI 横条。"""
    cells = ''.join(
        f'<div class="item"><span class="label">{esc(label)}</span>'
        f'<span class="{cls}" data-field="{esc(field)}">{esc(text)}</span></div>'
        for label, field, cls, text in items
    )
    return f'<div class="overview">{cells}</div>'


def kpi_strip(items):
    return _strip(items)


def overview_strip(metrics, uph=None):
    metrics = metrics or {}
    yield_pct = metrics.get('yield_pct')
    try:
        y = float(yield_pct)
        ycls = 'good' if y >= 95 else ('warn' if y >= 90 else 'bad')
    except (TypeError, ValueError):
        ycls = ''
    # 6 位口径（缺陷 #12）：99.998% 不得被 2 位小数吞成误导性的 100.00%
    ytext = format_percent_value(yield_pct)

    items = [
        ('总记录', 'total', 'kpi-value', fmt_num(metrics.get('total_rows'))),
        ('Pass', 'pass', 'kpi-value pass', fmt_num(metrics.get('pass_count'))),
        ('Fail', 'fail', 'kpi-value fail', fmt_num(metrics.get('fail_count'))),
        ('Yield', 'yield', f'{"yield-value " + ycls}'.strip(), f'{ytext}%'),
    ]
    if uph:
        items.append(('UPH', 'uph', 'kpi-value', fmt_num(uph.get('uph'))))
        items.append(('测试时长', 'duration', 'kpi-value',
                      f'{fmt_pct(uph.get("total_time_seconds"), 1)} s'))
    if metrics.get('format'):
        items.append(('格式', 'format', 'kpi-value', metrics.get('format')))

    return _strip(items)


def alerts_block(alerts):
    if not alerts:
        return ''
    out = []
    for a in alerts:
        level = 'error' if a.get('level') == 'error' else 'warning'
        out.append(f'<div class="alert alert--{level}">{esc(a.get("message"))}</div>')
    return f'<div class="alerts">{"".join(out)}</div>'


def report_footer(generated_at):
    return (f'<p class="report-footer">生成于 {esc(generated_at)} · '
            f'LiqunData ATE 数据分析软件</p>')
