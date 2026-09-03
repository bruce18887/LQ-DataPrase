"""导出侧数值/百分比格式化（项目 6 位口径）。

口径依据：``apps/analysis/.../limits.py`` 的 ``round(..., 6)`` 与注释
「回归：tiny-fail-bar，1/50000 = 0.002% 不因 round(…,2) 归零」。
导出侧此前用 ``f'{yield_pct:.2f}%'``，把 99.998% 显示成误导性的 100.00%。
"""

import math

PERCENT_DECIMALS = 6        # 与 analysis 侧 round(..., 6) 同口径
PERCENT_MIN_DECIMALS = 2    # 整数百分比仍显示两位小数（100.00% 而非 100%）


def format_percent_value(value, decimals: int = PERCENT_DECIMALS,
                         min_decimals: int = PERCENT_MIN_DECIMALS) -> str:
    """百分比数值 → 字符串：最多 ``decimals`` 位、去尾零，但至少 ``min_decimals`` 位。

    ``100.0`` → ``'100.00'``；``99.998`` → ``'99.998'``；``0.002`` → ``'0.002'``；
    ``75.0`` → ``'75.00'``。非数值/非有限输入退化为 ``'0.00'``（不得写出
    ``'nan%'`` / ``'inf%'``）。
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    head, _, tail = f'{number:.{decimals}f}'.partition('.')
    return f'{head}.{tail.rstrip("0").ljust(min_decimals, "0")}'
