"""Correlation scatter computation."""

import numpy as np

from apps.analysis.services.statistics import (
    get_1d_from,
    get_site_column,
    compute_range_statistics,
    site_sort_key,
    filter_finite,
)
from apps.analysis.services.statistics.distributions import t_cdf
from apps.analysis.services.statistics.outliers import detect_outliers_iqr
from apps.analysis.services.statistics.downsample import (
    bucket_minmax_indices,
    DOWN_SAMPLE_THRESHOLD,
)


def compute_correlation_scatter(df, param_x, param_y, metadata=None,
                                iqr_multiplier: float = 1.5):
    """Build scatter-point series and Pearson r for two parameters.

    Returns a dict with ``param_x``, ``param_y``, ``n``, ``pearson_r``,
    ``p_value`` (two-sided, ``None`` when r is undefined),
    ``series_data`` (one series per site if a site column exists, otherwise
    a single "Data" series).
    """
    # 向量化去 inf/nan（原实现逐值 lambda，68k 行文件 ~300ms 的元凶之一）。
    # filter_finite 同时完成 str/bool 列 coerce：裸 `.astype(float)` 在 pandas 3.0
    # 的 str 列（真实文件存在 `Start_T`）上抛 ValueError → 500；视图层守卫
    # 400 之外，服务层对任何直连调用也要容错（R3②）。
    x_series = filter_finite(get_1d_from(df, param_x))
    y_series = filter_finite(get_1d_from(df, param_y))
    common_idx = x_series.index.intersection(y_series.index)
    x_vals = x_series.loc[common_idx]
    y_vals = y_series.loc[common_idx]

    # Detect outliers for both axes, respecting spec limits (RDL)
    x_spec_limits = None
    y_spec_limits = None
    if metadata:
        x_stats = compute_range_statistics(x_vals, metadata, param_x)
        y_stats = compute_range_statistics(y_vals, metadata, param_y)
        x_spec_limits = (x_stats['rdl'][0], x_stats['rdl'][1])
        y_spec_limits = (y_stats['rdl'][0], y_stats['rdl'][1])

    # iqr_multiplier 跟随用户的「敏感度 (IQR 倍数)」：旧写法两轴都写死 1.5，
    # 调敏感度后直方图的异常值集合变了而散点图两轴仍按 1.5 标记，同屏矛盾。
    x_outlier_info = detect_outliers_iqr(
        x_vals, include_values=False, spec_limits=x_spec_limits,
        iqr_multiplier=iqr_multiplier,
    )
    y_outlier_info = detect_outliers_iqr(
        y_vals, include_values=False, spec_limits=y_spec_limits,
        iqr_multiplier=iqr_multiplier,
    )

    def _build_pts(xv: np.ndarray, yv: np.ndarray):
        """向量化构建 [x, y] 点列表（原实现逐行 Python 循环，
        68k 行文件 ~300ms；向量化后 ~15ms）。"""
        m = np.isfinite(xv) & np.isfinite(yv)
        return [[float(a), float(b)] for a, b in zip(xv[m], yv[m])]

    def _downsample_pts(pts):
        """大数据量保形降采样：按 x 分桶 M4/MinMax 保 y 极值轮廓
        （仅影响传输/绘制点集；pearson_r 等统计始终全量计算）。"""
        if len(pts) <= DOWN_SAMPLE_THRESHOLD:
            return pts
        x_arr = np.array([p[0] for p in pts], dtype=float)
        y_arr = np.array([p[1] for p in pts], dtype=float)
        keep = bucket_minmax_indices(x_arr, y_arr)
        return [pts[i] for i in keep]

    site_col = get_site_column(df)
    series_data = []
    if site_col:
        site_idx = get_1d_from(df, site_col).loc[common_idx]
        x_arr = x_vals.values
        y_arr = y_vals.values
        # site_sort_key 而非 key=str：纯数字站点按数值排序，否则字符串序会把
        # Site10 排在 Site2 前面，与 histogram.py / site_yield.py 的图例顺序不一致
        #（同一产品不同图的站点顺序不同）。
        for site in sorted(site_idx.unique(), key=site_sort_key):
            smask = (site_idx == site).values
            pts = _build_pts(x_arr[smask], y_arr[smask])
            pts = _downsample_pts(pts)
            if pts:
                series_data.append({'name': f'Site {site}', 'data': pts})
    else:
        pts = _build_pts(x_vals.values, y_vals.values)
        pts = _downsample_pts(pts)
        if pts:
            series_data.append({'name': 'Data', 'data': pts})

    n = len(common_idx)
    pearson_r = 0.0
    p_value = None
    if n > 2:
        x_arr = x_vals.values
        y_arr = y_vals.values
        sx = np.std(x_arr, ddof=0)
        sy = np.std(y_arr, ddof=0)
        if sx > 0 and sy > 0:
            pearson_r = float(np.corrcoef(x_arr, y_arr)[0, 1])
            # p_value 与 correlation_matrix 的 p_values 同一公式同一助手：
            # t = r*sqrt((n-2)/(1-r²))，双侧 p = 2*(1 - t_cdf(|t|, n-2))。
            # n<=2 或 σ=0 时 r 无定义 → None；|r|>=1 → p=0；r==0 → p=1。
            r = pearson_r
            if abs(r) >= 1:
                p_value = 0.0
            elif r != 0:
                t = r * np.sqrt((n - 2) / (1 - r * r))
                p_value = float(2 * (1 - t_cdf(abs(t), n - 2)))

    return {
        'param_x': param_x,
        'param_y': param_y,
        'n': n,
        'pearson_r': round(pearson_r, 6),
        'p_value': round(p_value, 6) if p_value is not None else None,
        'series_data': series_data,
        'x_outlier_info': x_outlier_info,
        'y_outlier_info': y_outlier_info,
    }
