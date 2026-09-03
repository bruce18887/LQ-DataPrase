"""Buyoff analysis service: statistics computation for buyoff reports."""
import math

from apps.analysis.services.statistics import get_1d_from
from apps.common.constants import NON_NUMERIC_KEYWORDS

# 「无法判定」的统一占位符：限值缺失 / 不可解析 / 公差为 0 / σ 为 0 时使用。
# 与 apps/export/excel_builders.py 的 None + 'N/A' 写法对齐——绝不静默兜底成
# 0.0，否则 tol=0 时 cpk = -|μ|/(3σ) 会在报表里出现巨大负值。
NA = 'N/A'


def parse_limit(raw):
    """把 metadata 里的限值解析为 float；不可用一律返回 ``None``。

    ``'Min'`` / ``'Max'`` / ``'N/A'`` / ``''`` / ``None`` / 垃圾字符串 / NaN / inf
    都归为「限值未知」，由调用方决定如何呈现（N/A），而不是当成 0.0 参与运算。
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text.lower() in NON_NUMERIC_KEYWORDS:
            return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _limit_from(metadata, key, param):
    """从 metadata 的 mins/maxs 里安全取限值（缺 key、缺 dict 都不抛）。"""
    if not isinstance(metadata, dict):
        return None
    table = metadata.get(key)
    if not isinstance(table, dict):
        return None
    return parse_limit(table.get(param))


def compute_buyoff_stats(df, metadata, param) -> dict:
    """Compute full buyoff statistics for a parameter.

    Returns dict with: lower_limit, upper_limit, min, max, range,
                       mean, std, mean_minus_6std, mean_minus_3std,
                       mean_plus_3std, mean_plus_6std, ca, cp, cpk.

    ``lower_limit`` / ``upper_limit`` 可能是 ``None``（限值未知）；
    ``ca`` / ``cp`` / ``cpk`` 在无法判定时为字符串 ``'N/A'``。
    """
    data = get_1d_from(df, param).dropna()
    result = {}
    if len(data) == 0:
        return result

    mean_v = float(data.mean())
    std_v = float(data.std(ddof=0)) if len(data) > 1 else 0.0
    min_v = float(data.min())
    max_v = float(data.max())

    lower = _limit_from(metadata, 'mins', param)
    upper = _limit_from(metadata, 'maxs', param)

    ca = cp = cpk = NA
    if lower is not None and upper is not None:
        tol = upper - lower
        # 公差非正（含 tol == 0）时能力指数无定义：ca=0.0 会被读成「完美居中」，
        # 与事实相反，因此一律 N/A。
        if tol > 0:
            ca = abs(mean_v - (upper + lower) / 2) / (tol / 2)
            if std_v > 0:
                cp = tol / (6 * std_v)
                cpk = min((upper - mean_v) / (3 * std_v),
                          (mean_v - lower) / (3 * std_v))

    return {
        'lower_limit': lower, 'upper_limit': upper,
        'min': min_v, 'max': max_v, 'range': max_v - min_v,
        'mean': mean_v, 'std': std_v,
        'mean_minus_6std': mean_v - 6 * std_v,
        'mean_minus_3std': mean_v - 3 * std_v,
        'mean_plus_3std': mean_v + 3 * std_v,
        'mean_plus_6std': mean_v + 6 * std_v,
        'ca': ca, 'cp': cp, 'cpk': cpk,
    }
