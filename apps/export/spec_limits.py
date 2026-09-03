"""规格限（LSL/USL）解析：导出侧唯一口径。

范本来自 ``excel_builders.build_sigma_limit_sheet``——全仓唯一处理正确的地方：
限值缺失就写 ``'N/A'``，**不回退 0.0**，也只在双限齐备时才做比较。

``apps/analysis/.../limits.py`` 的 ``parse_limit_string`` 正在改成同一语义
（缺失/占位/字面 ``Min``/``Max`` → ``None``），但它带 ``data_series`` 参数、
旧版本还会把数据自身极值当规格限，导出侧不能直接依赖；这里保持一个
Django-free、无数据依赖的纯字符串解析。
"""

import math
from typing import Optional, Tuple

# 限值占位符（大小写不敏感）：与 excel_builders 原 NON_NUM 列表逐字一致
NON_NUMERIC_LIMITS = frozenset({
    'min', 'max', 'lower limit', 'upper limit', 'n/a', 'na', '-', 'none', '',
})


def parse_spec_limit(raw) -> Optional[float]:
    """限值 → ``float``；缺失/占位/非数值/非有限 → ``None``。

    ``None`` 与 ``0.0`` 语义完全不同：``0.0`` 是一个真实规格限，会让
    ``compute_cpk`` 算出垃圾能力指数、让直方图把网格锚到 0（幻影 limit）。
    """
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def is_placeholder_limit(raw) -> bool:
    """是否是占位符限值（``''`` / ``n/a`` / ``-`` / ``none`` / ``min`` / ``max``）。"""
    return str(raw if raw is not None else '').strip().lower() in NON_NUMERIC_LIMITS


def spec_limits(metadata: Optional[dict], param: str) -> Tuple[Optional[float], Optional[float]]:
    """从 metadata 取 (LSL, USL)；任一侧缺失/占位则该侧为 ``None``。"""
    metadata = metadata or {}
    mins = metadata.get('mins') or {}
    maxs = metadata.get('maxs') or {}
    if param not in mins or param not in maxs:
        return None, None
    return parse_spec_limit(mins.get(param)), parse_spec_limit(maxs.get(param))
