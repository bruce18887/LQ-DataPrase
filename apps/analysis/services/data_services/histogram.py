"""Histogram statistics computation."""

import numpy as np
import pandas as pd

from apps.analysis.services.statistics.kde import GaussianKDE
from apps.analysis.services.statistics import (
    compute_cpk,
    compute_range_statistics,
    compute_site_stats,
    get_1d_from,
    get_site_column,
    safe_gap,
    filter_finite,
    site_sort_key,
    normal_pdf_curve,
)
from apps.analysis.services.statistics.helpers import _dense_x_grid
from apps.analysis.services.statistics.outliers import detect_outliers_iqr
from apps.analysis.services.limits import resolve_limits


def compute_kde_curve(data_series, bin_min, bin_max, n_points=200):
    """Gaussian KDE curve sampled over ``[bin_min, bin_max]``.

    Non-parametric density estimate: unlike the normal curve it adapts to
    bimodal / multimodal / skewed shapes (common when sites or process
    populations mix).  Returns ``None`` for degenerate input (< 3 samples,
    zero variance, failed fit) so the front-end simply skips the overlay.
    ``_dense_x_grid`` keeps tight distributions (σ << grid step) from
    slipping between the evenly spaced sample points.
    """
    vals = data_series.astype(float)
    if len(vals) < 3 or np.ptp(vals) == 0:
        return None
    try:
        kde = GaussianKDE(vals, bw_method='silverman')
    except Exception:
        return None
    x = _dense_x_grid(bin_min, bin_max, n_points,
                      float(vals.mean()), float(vals.std(ddof=0)))
    y = kde(x)
    if np.max(y) <= 0:
        return None
    return [[round(float(xi), 6), round(float(yi), 6)] for xi, yi in zip(x, y)]


def compute_histogram_stats(df, metadata, param, site_col,
                            range_type='RDL', custom_low=None, custom_high=None,
                            iqr_multiplier=1.5):
    """Compute histogram binning, CPK stats, and per-site histograms.

    Returns the same dict that ``AnalysisViewSet.histogram`` built inline,
    or ``None`` when there is no valid data for *param*.

    ``range_type`` selects which range drives the histogram binning (and thus
    the X-axis span): ``'RDL'`` (spec limits), ``'DR'``/``'CL'`` (data range),
    ``'S3'``/``'S4'``/``'S6'`` (±3/4/6 sigma).  CPK and per-site yield always
    stay anchored to the spec limits (RDL) regardless of ``range_type``,
    except in ``'CL'`` mode: when ``custom_low``/``custom_high`` are both
    provided they are treated as user-supplied spec limits, so an extra
    ``custom_cpk`` (with level/color) is computed against them while the
    RDL-anchored ``cpk`` is kept so the UI can show before/after values.
    ``custom_low``/``custom_high`` override the binning range when
    ``range_type == 'CL'`` and both are provided.
    ``iqr_multiplier`` controls outlier detection sensitivity (default 1.5).
    """
    data_series = filter_finite(get_1d_from(df, param))
    if len(data_series) == 0:
        return None

    stats = compute_range_statistics(data_series, metadata, param)

    # Detect outliers using IQR method, respecting spec limits (RDL)
    outlier_info = detect_outliers_iqr(
        data_series, include_values=True,
        spec_limits=(stats['rdl'][0], stats['rdl'][1]),
        iqr_multiplier=iqr_multiplier,
    )
    cpk_result = compute_cpk(
        stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1]
    )

    # Custom-limit CPK: in 'CL' mode the user-supplied bounds act as spec
    # limits, so recompute capability against them.  The RDL-anchored cpk
    # above is kept unchanged so the front-end can show both when they differ.
    custom_cpk = None
    custom_cpk_level = None
    custom_cpk_color = None
    if range_type == 'CL' and custom_low is not None and custom_high is not None:
        custom_cpk_result = compute_cpk(
            stats['mean'], stats['std'],
            float(custom_low), float(custom_high),
        )
        custom_cpk = round(custom_cpk_result['cpk'], 4)
        custom_cpk_level = custom_cpk_result['cpk_level']
        custom_cpk_color = custom_cpk_result['cpk_color']

    # Compute filtered statistics (excluding outliers)
    filtered_cpk = None
    filtered_cpk_level = None
    filtered_cpk_color = None
    filtered_mean = None
    filtered_std = None
    filtered_data_min = None
    filtered_data_max = None
    filtered_sigma3_min = filtered_sigma3_max = None
    filtered_sigma4_min = filtered_sigma4_max = None
    filtered_sigma6_min = filtered_sigma6_max = None
    filtered_normal_curve = None
    normal_data = None
    if outlier_info['has_outliers'] and outlier_info['normal_count'] > 1:
        normal_data = data_series[
            (data_series >= outlier_info['lower_bound']) &
            (data_series <= outlier_info['upper_bound'])
        ]
        if len(normal_data) > 1:
            filtered_mean = round(float(normal_data.mean()), 6)
            filtered_std = round(float(normal_data.std(ddof=0)), 6)
            filtered_data_min = round(float(normal_data.min()), 6)
            filtered_data_max = round(float(normal_data.max()), 6)
            if filtered_std > 0:
                # 裁剪口径 σ 区间：与 filtered_mean/std 同源。前端开启异常值
                # 裁剪时卡片与图表标记线必须用这组值，而不是全量数据的
                # sigma3/4/6（否则同一界面出现两套 σ 区间）
                filtered_sigma3_min = round(filtered_mean - 3 * filtered_std, 6)
                filtered_sigma3_max = round(filtered_mean + 3 * filtered_std, 6)
                filtered_sigma4_min = round(filtered_mean - 4 * filtered_std, 6)
                filtered_sigma4_max = round(filtered_mean + 4 * filtered_std, 6)
                filtered_sigma6_min = round(filtered_mean - 6 * filtered_std, 6)
                filtered_sigma6_max = round(filtered_mean + 6 * filtered_std, 6)
                filtered_normal_curve = None  # 需 bin_min/bin_max，响应前计算
                filtered_cpk_result = compute_cpk(
                    filtered_mean, filtered_std,
                    stats['rdl'][0], stats['rdl'][1]
                )
                filtered_cpk = round(filtered_cpk_result['cpk'], 4)
                filtered_cpk_level = filtered_cpk_result['cpk_level']
                filtered_cpk_color = filtered_cpk_result['cpk_color']

    site_data = None
    site_idx = None
    if site_col:
        site_series = get_1d_from(df, param)
        site_idx = get_1d_from(df, site_col)
        site_data = compute_site_stats(
            site_series, site_idx, stats['rdl'][0], stats['rdl'][1],
            None, None, False
        )

    # Binning range follows the selected range_type so the X-axis zooms to the
    # region of interest (e.g. selecting "3 Sigma" spreads a tight distribution
    # across the bins instead of collapsing it into a single RDL-width bin).
    if range_type == 'CL' and custom_low is not None and custom_high is not None:
        bin_min, bin_max = float(custom_low), float(custom_high)
    else:
        bin_min, bin_max = resolve_limits(range_type, stats)
        if bin_min is None or bin_max is None:
            bin_min, bin_max = stats['rdl'][0], stats['rdl'][1]

    # Degenerate range (missing/zero-width limits, or std==0 for sigma ranges):
    # fall back to the actual data range, then to a ±0.5 window, so ECharts
    # never receives a zero-width axis.
    if bin_min == bin_max:
        bin_min = float(data_series.min())
        bin_max = float(data_series.max())
    if bin_min == bin_max:
        bin_min -= 0.5
        bin_max += 0.5
    data_gap = safe_gap(bin_min, bin_max)

    # Bin edges & centers must exist before the density curves: the curves
    # sample over the full visible X-axis — bin_centers[0..-1], which extend
    # one gap past the underflow/overflow bin centres — so they fill the
    # axis edge to edge instead of stopping at the binning bounds.
    # 25 inner edges step from bin_min - 2*data_gap by data_gap → bin 网格以
    # [bin_min, bin_max] 为中心对称：两侧各 2 个细分 bin + underflow/overflow
    #（回归：bin-grid-asymmetry，此前网格锚定 bin_min 使 USL 右侧多出 4 个
    # 细分 bin，X 轴视觉偏左；multi_lot 同构统一）
    inner_edges = [bin_min - 2 * data_gap + j * data_gap for j in range(25)]
    bin_centers = [inner_edges[0] - data_gap]  # underflow center
    bin_centers += [(inner_edges[i] + inner_edges[i + 1]) / 2 for i in range(24)]
    bin_centers.append(inner_edges[-1] + data_gap)  # overflow center

    # KDE curve: non-parametric density overlay.  Two variants mirroring the
    # normal curve pair: ``kde_curve`` covers ALL data (so out-of-spec / fail
    # values surface as their own bump, and off-mode bars stay consistent),
    # ``filtered_kde_curve`` drops IQR outliers (main peak stays faithful).
    # The front-end picks by its「KDE含超限」toggle — no extra request.
    kde_curve = compute_kde_curve(data_series, bin_centers[0], bin_centers[-1])
    filtered_kde_curve = None
    if normal_data is not None and len(normal_data) > 1:
        filtered_kde_curve = compute_kde_curve(normal_data, bin_centers[0], bin_centers[-1])

    # 正态 PDF 曲线（与 KDE 同采样区间，覆盖整个可见 X 轴）：raw 与裁剪口径
    # 各一份，前端按异常值处理开关选择——公式单一来源 normal_pdf_curve
    normal_curve = normal_pdf_curve(stats['mean'], stats['std'], bin_centers[0], bin_centers[-1])
    if filtered_std is not None and filtered_std > 0:
        filtered_normal_curve = normal_pdf_curve(filtered_mean, filtered_std, bin_centers[0], bin_centers[-1])

    # Build bin edges with underflow (-inf) and overflow (+inf) bins.
    # 25 inner edges step from bin_min by data_gap (range/20) → 24 normal
    # bins (first 20 cover [bin_min, bin_max]); the two catch-all bins keep
    # values outside the selected range visible (and colourable as fail bins).
    all_bins = np.array([-np.inf] + inner_edges + [np.inf])
    # 27 edges → 26 bins: 1 underflow + 24 normal + 1 overflow

    total_count = len(data_series)
    hist_counts, _ = np.histogram(data_series.dropna(), bins=all_bins)
    # 6 位小数保精度：1/50000 = 0.002% 若 round 到 2 位会归零，前端柱高为 0
    # 看不到 fail bin（回归：tiny-fail-bar）。count==0 时保持 0.0。
    bin_percentages = [
        round(c / total_count * 100, 6) if total_count > 0 else 0.0
        for c in hist_counts
    ]
    # 原始计数随响应下发（与 bin_centers 对齐），tooltip 显示数量
    bin_counts = [int(c) for c in hist_counts]

    site_histograms = None
    if site_col and site_idx is not None and len(site_idx.unique()) >= 1:
        # Always populate site_histograms when a Site column is present,
        # including the single-site case. Previously the `> 1` guard left
        # the field as None for one-site files, so the front-end histogram
        # mis-labelled the lone site as "数据分布". Single-site series are
        # visually identical to multi-site ones in the chart; only the
        # legend / colour assignment changes.
        site_histograms = {}
        site_idx_aligned = site_idx[data_series.index]

        for site in sorted(site_idx_aligned.unique(), key=site_sort_key):
            mask = (site_idx_aligned == site).values \
                if hasattr(site_idx_aligned, 'values') \
                else (site_idx_aligned == site)
            if isinstance(mask, pd.Series):
                mask = mask.values
            vals = data_series[mask]
            if len(vals) > 0:
                site_hist, _ = np.histogram(vals, bins=all_bins)
                # Use total_count (all sites) as denominator, matching Excel
                # 6 位小数保精度，与 bin_percentages 同口径（小百分比不归零）
                site_histograms[str(site)] = [
                    round(c / total_count * 100, 6) if total_count > 0 else 0.0
                    for c in site_hist
                ]

    return {
        'mean': round(stats['mean'], 6),
        'std': round(stats['std'], 6),
        'unit': stats['unit'],
        'lower_limit': round(stats['rdl'][0], 6),
        'upper_limit': round(stats['rdl'][1], 6),
        'cp': round(cpk_result['cp'], 4) if cpk_result['cp'] is not None else None,
        'cpk': round(cpk_result['cpk'], 4),
        'pp': round(cpk_result['pp'], 4) if cpk_result['pp'] is not None else None,
        'ppk': round(cpk_result['ppk'], 4),
        'cp_level': cpk_result['cp_level'],
        'cpk_level': cpk_result['cpk_level'],
        'pp_level': cpk_result['pp_level'],
        'ppk_level': cpk_result['ppk_level'],
        'cp_color': cpk_result['cp_color'],
        'cpk_color': cpk_result['cpk_color'],
        'pp_color': cpk_result['pp_color'],
        'ppk_color': cpk_result['ppk_color'],
        'data_min': round(stats['dr'][0], 6),
        'data_max': round(stats['dr'][1], 6),
        'sigma3_min': round(stats['s3'][0], 6),
        'sigma3_max': round(stats['s3'][1], 6),
        'sigma4_min': round(stats['s4'][0], 6),
        'sigma4_max': round(stats['s4'][1], 6),
        'sigma6_min': round(stats['s6'][0], 6),
        'sigma6_max': round(stats['s6'][1], 6),
        'site_stats': site_data,
        'site_histograms': site_histograms,
        'bin_centers': [round(c, 6) for c in bin_centers],
        'bin_percentages': bin_percentages,
        'bin_counts': bin_counts,
        'kde_curve': kde_curve,
        'filtered_kde_curve': filtered_kde_curve,
        'normal_curve': normal_curve,
        'filtered_normal_curve': filtered_normal_curve,
        'total_count': len(data_series),
        'outlier_info': outlier_info,
        'filtered_cpk': filtered_cpk,
        'filtered_cpk_level': filtered_cpk_level,
        'filtered_cpk_color': filtered_cpk_color,
        'filtered_mean': filtered_mean,
        'filtered_std': filtered_std,
        'filtered_data_min': filtered_data_min,
        'filtered_data_max': filtered_data_max,
        'filtered_sigma3_min': filtered_sigma3_min,
        'filtered_sigma3_max': filtered_sigma3_max,
        'filtered_sigma4_min': filtered_sigma4_min,
        'filtered_sigma4_max': filtered_sigma4_max,
        'filtered_sigma6_min': filtered_sigma6_min,
        'filtered_sigma6_max': filtered_sigma6_max,
        'custom_cpk': custom_cpk,
        'custom_cpk_level': custom_cpk_level,
        'custom_cpk_color': custom_cpk_color,
        'custom_low': float(custom_low) if range_type == 'CL' and custom_low is not None else None,
        'custom_high': float(custom_high) if range_type == 'CL' and custom_high is not None else None,
    }
