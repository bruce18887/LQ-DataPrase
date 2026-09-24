"""HTML 报告的最小渲染工具：转义与 PNG→data-uri。

纯 stdlib，不 import Django —— 供本包内所有模块（含图表模块）共用。
"""

import base64
import html


def esc(value) -> str:
    """所有进入 HTML 的动态值（单元格、属性、title）都必须过这里。

    ``quote=True`` 同时转义引号，属性上下文也安全。None → 空串，避免渲染 "None"。
    """
    if value is None:
        return ''
    return html.escape(str(value), quote=True)


def png_data_uri(png: bytes) -> str:
    """PNG 字节 → ``data:image/png;base64,...``，供自包含 ``<img>`` 内联。"""
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def fmt_num(value) -> str:
    """数字千分位；None/非数 → '-'。"""
    try:
        if value is None:
            return '-'
        num = float(value)
    except (TypeError, ValueError):
        return esc(value)
    if num != num:  # NaN
        return '-'
    if num.is_integer():
        return f'{int(num):,}'
    return f'{num:,}'


def fmt_pct(value, digits: int = 2) -> str:
    """百分比数值（不含 % 号）；None/非数 → '-'。"""
    try:
        if value is None:
            return '-'
        num = float(value)
    except (TypeError, ValueError):
        return '-'
    if num != num:
        return '-'
    return f'{num:.{digits}f}'
