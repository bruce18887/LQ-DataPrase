"""导出直方图网格：与屏幕侧 ``apps.analysis...histogram`` 同源同口径。

为什么单独一个模块
------------------
* ``apps/export/charts.py`` 被 ``chart_workers``（ProcessPoolExecutor，Windows
  spawn）子进程 import，**必须保持 Django-free**；本模块只依赖 numpy 与
  analysis 的纯计算 helper，可以安全被子进程加载。
* 网格构造此前在 ``charts.build_histogram_bins`` 里另算一套（26 条有限边界、
  两端各外扩 2.5·gap、无 ±inf 兜底），与屏幕侧（25 条内边界 + ±inf = 27 边界、
  两端各外扩 2·gap）平移了 0.5·gap，且超范围值被 ``np.histogram`` **静默丢弃**。
  现在两侧共用本模块的几何。

屏幕侧权威实现（只读，不得修改）：
``apps/analysis/services/data_services/histogram.py`` 的
``inner_edges`` / ``bin_centers`` / ``all_bins`` 三段。
"""

from typing import Optional, Sequence, Tuple

import numpy as np

from apps.analysis.services.statistics.helpers import safe_gap

# 内边界条数：25 条 → 24 个常规 bin（前 20 个覆盖 [bin_min, bin_max]）
# + 1 underflow(-inf) + 1 overflow(+inf) = 27 边界 / 26 bin，与屏幕侧一致。
INNER_EDGE_COUNT = 25
# 两侧外扩的细分 bin 数（屏幕侧口径：bin_min - 2*gap 起）
OUTER_BINS = 2


def _usable(value) -> bool:
    """限值是否可用作分箱边界：非 None、可转 float、且有限。

    ``parse_limit_string`` 的新语义下限值缺失/占位（空串、``n/a``、``-``、
    ``none``、字面 ``Min``/``Max``）返回 ``None``；旧的 ``compute_range_statistics``
    则可能回退 ``0.0``（幻影限值）。两者都要在这里被识别为「不可用/退化」。
    """
    if value is None:
        return False
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(as_float))


def finite_or_none(value) -> Optional[float]:
    """可用于绘图/比较的限值：非 None 且有限 → ``float``；否则 ``None``。

    导出侧统一用它把 ``stats['rdl']`` / metadata 里的限值收敛成「画 or 不画」，
    避免 ``axvline(nan)`` / ``round(None, 4)`` 一类崩溃。
    """
    return float(value) if _usable(value) else None


def _data_window(data_series) -> Tuple[Optional[float], Optional[float]]:
    """有限数据的 (min, max)；无数据/全 NaN/全 inf → (None, None)。"""
    if data_series is None:
        return None, None
    try:
        values = np.asarray(data_series, dtype=float).ravel()
    except (TypeError, ValueError):
        return None, None
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None, None
    return float(values.min()), float(values.max())


def resolve_bin_range(low, high, data_series=None) -> Tuple[float, float]:
    """把可能缺失/退化的规格限收敛成可绘制的 ``(bin_min, bin_max)``。

    与屏幕 ``compute_histogram_stats`` 同口径：

    1. 限值可用且 ``low < high`` → 原样使用；
    2. 否则（None/nan/±inf/零宽/倒置——含限值缺失时上游回退 ``0.0`` 造成的
       幻影 ``(0.0, 0.0)``）→ 回退到数据 min/max；
    3. 数据也退化（无数据或所有值相同）→ 中点 ±0.5 窗口，保证 gap > 0。
    """
    low_ok, high_ok = _usable(low), _usable(high)
    if low_ok and high_ok and float(low) < float(high):
        return float(low), float(high)

    data_min, data_max = _data_window(data_series)
    if data_min is not None and data_min < data_max:
        return data_min, data_max

    if low_ok:
        center = float(low)
    elif high_ok:
        center = float(high)
    elif data_min is not None:
        center = data_min
    else:
        center = 0.0
    return center - 0.5, center + 0.5


def build_histogram_grid(low, high, data_series=None):
    """构造与屏幕侧逐值相同的直方图网格。

    Returns
    -------
    (edges, centers, gap)
        * ``edges``   : 27 个边界（``[-inf] + 25 内边界 + [inf]``）→ 26 bin，
          超范围值落入首/尾 catch-all bin，不会被 ``np.histogram`` 丢弃。
        * ``centers`` : 26 个 bin 中心（x 轴刻度**唯一**来源，勿另算公式）：
          ``[内边界0 - gap] + [(内i + 内i+1)/2 …] + [内边界-1 + gap]``。
        * ``gap``     : bin 宽度（``safe_gap`` = 区间/20，下限 1e-9）。
    """
    bin_min, bin_max = resolve_bin_range(low, high, data_series)
    gap = safe_gap(bin_min, bin_max)

    inner_edges = [bin_min - OUTER_BINS * gap + j * gap
                   for j in range(INNER_EDGE_COUNT)]
    edges = np.array([-np.inf] + inner_edges + [np.inf], dtype=float)

    centers = [inner_edges[0] - gap]                                    # underflow
    centers += [(inner_edges[i] + inner_edges[i + 1]) / 2
                for i in range(len(inner_edges) - 1)]
    centers.append(inner_edges[-1] + gap)                                 # overflow

    return edges, np.asarray(centers, dtype=float), float(gap)


def bin_percentages(counts: Sequence, total: int) -> list:
    """计数 → 百分比（6 位口径，与屏幕 ``bin_percentages`` 一致）。

    回归：tiny-fail-bar —— 1/50000 = 0.002% 若 ``round(…, 2)`` 会归零，
    导出图上 fail bin 的柱高为 0，用户看不到超差点。
    """
    if not total or total <= 0:
        return [0.0] * len(counts)
    return [round(float(c) / total * 100, 6) for c in counts]
