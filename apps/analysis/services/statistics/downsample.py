"""Downsampling utilities for large scatter datasets.

散点类端点（qqplot / serial_distribution / correlation）在数据量超过
``DOWN_SAMPLE_THRESHOLD`` 时做保形降采样，控制响应体量（68k 行文件
2-3MB JSON → ~0.1MB）与前端渲染开销。**统计口径（r² / pass-fail /
pearson_r 等）始终在全量数据上计算**，采样只影响传输与绘制的点集；
小数据（≤ 阈值）行为零变更。

参考：M4 aggregation（Uwe Jugel 2014）——每桶保留首/末/min/max 点，
保留垂直极值轮廓；与 boxplot 既有 ``MAX_RAW_POINTS = 2000`` 先例对齐。
"""

import numpy as np

# 采样目标点数（与 boxplot 的 MAX_RAW_POINTS 对齐）
MAX_POINTS = 2000

# 超过该点数才采样；小文件完全不过采样路径（默认行为零变更）
DOWN_SAMPLE_THRESHOLD = 5000


def uniform_indices(n: int, max_points: int = MAX_POINTS) -> np.ndarray:
    """均匀索引采样（升序去重）。

    用于分位数等**单调序列**（QQ 图的分位数对）：均匀取点视觉等价于
    全量——重叠点不携带额外信息，2k 点与 68k 点画出的曲线重合。
    """
    if n <= max_points:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, max_points).astype(int))


def bucket_minmax_indices(
    bucket_keys: np.ndarray,
    value_keys: np.ndarray | None = None,
    max_points: int = MAX_POINTS,
) -> np.ndarray:
    """分桶 M4/MinMax 保形采样：按 ``bucket_keys``（x 轴，如 serial / x 值）
    排序分桶，每桶保留首/末 + ``value_keys``（y 轴极值依据）的 min/max 点
    共 4 个索引。缺省 ``value_keys`` 时用 ``bucket_keys`` 自身（单调序列
    退化为每桶首末两点）。

    - ``value_keys`` 中的 NaN（无测量值点）不参与极值选择，但该点若恰为
      桶首末仍可能被保留（保留与否不影响渲染——前端不绘制无值点）。
    - 返回升序去重索引数组（指向原数组位置，``points[keep]`` 取点）。
    - 每桶最多 4 点 → 结果 ≤ max_points，保峰值/谷值轮廓。

    用于散点图：序列分布按 serial 分桶保 value 极值、相关性按 x 分桶保
    y 极值。
    """
    n = len(bucket_keys)
    if n <= max_points:
        return np.arange(n)

    vals = bucket_keys if value_keys is None else np.asarray(value_keys, dtype=float)
    order = np.argsort(bucket_keys, kind='stable')
    nbuckets = max(1, max_points // 4)
    keep: set = set()
    edges = np.linspace(0, n, nbuckets + 1).astype(int)
    for b in range(nbuckets):
        lo, hi = int(edges[b]), int(edges[b + 1])
        if hi - lo < 1:
            continue
        bucket = order[lo:hi]
        keep.add(int(bucket[0]))
        keep.add(int(bucket[-1]))
        if hi - lo > 2:
            bvals = vals[bucket]
            valid = ~np.isnan(bvals)
            if valid.any():
                # argmin/argmax 返回过滤后数组内位置，须映射回原桶索引
                valid_pos = np.where(valid)[0]
                keep.add(int(bucket[int(valid_pos[int(np.argmin(bvals[valid]))])]))
                keep.add(int(bucket[int(valid_pos[int(np.argmax(bvals[valid]))])]))
    return np.array(sorted(keep))
