"""Histogram statistics computation."""

import numpy as np
import pandas as pd

from apps.analysis.services.statistics import (
    compute_cpk,
    compute_range_statistics,
    compute_site_stats,
    get_1d_from,
    get_site_column,
    safe_gap,
)
from apps.analysis.services.limits import resolve_limits


def compute_histogram_stats(df, metadata, param, site_col,
                            range_type='RDL', custom_low=None, custom_high=None):
    """Compute histogram binning, CPK stats, and per-site histograms.

    Returns the same dict that ``AnalysisViewSet.histogram`` built inline,
    or ``None`` when there is no valid data for *param*.

    ``range_type`` selects which range drives the histogram binning (and thus
    the X-axis span): ``'RDL'`` (spec limits), ``'DR'``/``'CL'`` (data range),
    ``'S3'``/``'S4'``/``'S6'`` (±3/4/6 sigma).  CPK and per-site yield always
    stay anchored to the spec limits (RDL) regardless of ``range_type``.
    ``custom_low``/``custom_high`` override the binning range when
    ``range_type == 'CL'`` and both are provided.
    """
    data_series = get_1d_from(df, param).dropna()
    data_series = data_series[data_series.apply(lambda x: abs(x) < float('inf'))]
    if len(data_series) == 0:
        return None

    stats = compute_range_statistics(data_series, metadata, param)
    cpk_result = compute_cpk(
        stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1]
    )

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
    bin_start = bin_min - 2.5 * data_gap

    # Build bin edges with underflow (-inf) and overflow (+inf) bins
    # Excel pattern: [underflow] [bin1] [bin2] ... [binN] [overflow]
    inner_edges = [bin_start + j * data_gap for j in range(26)]
    all_bins = np.array([-np.inf] + inner_edges + [np.inf])
    # 27 edges → 26 bins: 1 underflow + 24 normal + 1 overflow

    total_count = len(data_series)
    hist_counts, _ = np.histogram(data_series.dropna(), bins=all_bins)
    bin_percentages = [
        round(c / total_count * 100, 2) if total_count > 0 else 0
        for c in hist_counts
    ]

    # Bin centers: underflow/overflow use edge values, normal bins use midpoint
    bin_centers = [inner_edges[0] - data_gap]  # underflow center
    bin_centers += [(inner_edges[i] + inner_edges[i + 1]) / 2 for i in range(25)]
    bin_centers.append(inner_edges[-1] + data_gap)  # overflow center

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

        def site_sort_key(s):
            try:
                return (0, float(s), '')
            except (ValueError, TypeError):
                return (1, 0, str(s))

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
                site_histograms[str(site)] = [
                    round(c / total_count * 100, 2) if total_count > 0 else 0
                    for c in site_hist
                ]

    return {
        'mean': round(stats['mean'], 6),
        'std': round(stats['std'], 6),
        'unit': stats['unit'],
        'lower_limit': round(stats['rdl'][0], 6),
        'upper_limit': round(stats['rdl'][1], 6),
        'cp': round(cpk_result['cp'], 4),
        'cpk': round(cpk_result['cpk'], 4),
        'pp': round(cpk_result['pp'], 4),
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
        'sigma6_min': round(stats['s6'][0], 6),
        'sigma6_max': round(stats['s6'][1], 6),
        'site_stats': site_data,
        'site_histograms': site_histograms,
        'bin_centers': [round(c, 6) for c in bin_centers],
        'bin_percentages': bin_percentages,
        'total_count': len(data_series),
    }
