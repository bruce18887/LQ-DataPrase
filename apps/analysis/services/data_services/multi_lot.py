"""Multi-lot distribution computation."""

import numpy as np
import pandas as pd

from apps.analysis.services.statistics import (
    get_columns_with_limits,
    parse_limit_string,
    safe_gap,
)


def compute_common_params(loaded, ignore_no_limit=False):
    """Intersect numeric test-item names across multiple loaded files.

    Args:
        loaded: list of ``(file_id, df, metadata, filename)`` tuples.
        ignore_no_limit: when True, keep only params that carry valid spec
            limits in *every* selected file (so a per-file limit line can be
            drawn). Otherwise return the plain numeric-column intersection.

    Returns:
        List of column names present (and numeric) in all files,
        ordered by the file with the most parameters (preserving original order).
    """
    param_sets = []
    param_orders = []  # Store original column order for each file
    for _fid, df, metadata, _filename in loaded:
        numeric_cols = [
            c for c in df.columns
            if str(c).strip() and df[c].dtype in ('int64', 'float64')
        ]
        if ignore_no_limit:
            numeric_cols = [c for c in numeric_cols if c in set(get_columns_with_limits(df, metadata))]
        param_sets.append(set(numeric_cols))
        param_orders.append(numeric_cols)
    if not param_sets:
        return []

    common_params = set.intersection(*param_sets)

    # Find the file with the most parameters and use its order
    if not param_orders:
        return sorted(common_params)

    max_idx = max(range(len(param_orders)), key=lambda i: len(param_orders[i]))
    ordered_params = param_orders[max_idx]

    # Filter to only common params, preserving order
    result = [p for p in ordered_params if p in common_params]
    return result


def _resolve_param_limits(df, metadata, param, series):
    """Return ``(lower, upper)`` spec limits for *param*, or ``(None, None)``.

    Only files whose *param* passes the same validity check as
    ``get_columns_with_limits`` yield numeric limits; everything else (missing
    column, non-numeric "MIN"/"MAX" markers, blank) returns ``(None, None)`` so
    the front-end simply omits that file's limit line.
    """
    if param not in set(get_columns_with_limits(df, metadata)):
        return None, None
    lower = parse_limit_string(str(metadata.get('mins', {}).get(param, '')), series)
    upper = parse_limit_string(str(metadata.get('maxs', {}).get(param, '')), series)
    return round(float(lower), 6), round(float(upper), 6)


def _resolve_multi_range(range_type, combined, global_mean, global_std,
                         all_dsets, param, custom_low=None, custom_high=None):
    """Resolve bin range for multi-file chart.

    Args:
        range_type: One of 'RDL', 'DR', 'S3', 'S4', 'S6', 'CL'.
        combined: Concatenated Series of all files.
        global_mean: Mean of *combined*.
        global_std: Std of *combined*.
        all_dsets: List of dataset dicts (each has ``df``, ``metadata``, ...).
        param: Parameter name.
        custom_low/custom_high: Custom bounds for ``CL`` mode.

    Returns:
        ``(bin_min, bin_max)`` following the selected *range_type*.
        Fallback chain: selected → RDL → DR (raw data range).
    """
    if range_type == 'CL' and custom_low is not None and custom_high is not None:
        return float(custom_low), float(custom_high)

    if range_type == 'DR':
        return float(combined.min()), float(combined.max())

    # RDL: use spec limits from metadata (union across files)
    if range_type == 'RDL':
        lowers, uppers = [], []
        for ds in all_dsets:
            lo, hi = _resolve_param_limits(
                ds.get('df'), ds.get('metadata', {}), param, combined)
            if lo is not None:
                lowers.append(lo)
            if hi is not None:
                uppers.append(hi)
        if lowers or uppers:
            return (
                min(lowers) if lowers else float(combined.min()),
                max(uppers) if uppers else float(combined.max()),
            )

    # S3/S4/S6: mean ± N*std
    if range_type in ('S3', 'S4', 'S6') and global_std > 0:
        n = int(range_type[1:])  # S3→3 / S10→10（[1] 只取一位，S10+ 会解析错）
        return global_mean - n * global_std, global_mean + n * global_std

    # Final fallback: raw data range
    return float(combined.min()), float(combined.max())


def compute_multi_lot_distribution(datasets, all_series, param,
                                    range_type='S4', custom_low=None,
                                    custom_high=None):
    """Compute multi-lot distribution bins and lot-level stats.

    Args:
        datasets: ``{fid: {series, metadata, name, ...}}``.
        all_series: List of ``pd.Series``, one per lot.
        param: Parameter name.
        range_type: One of 'RDL', 'DR', 'S3', 'S4', 'S6', 'CL'.
        custom_low: Custom lower bound (when ``range_type == 'CL'``).
        custom_high: Custom upper bound (when ``range_type == 'CL'``).

    Returns:
        Dict with keys ``param``, ``global_mean``, ``global_std``,
        ``chart_min``, ``chart_max``, ``bin_centers``, ``lot_data``.
    """
    if not all_series:
        return None

    combined = pd.concat(all_series)
    # Clean data: remove NaN and Inf values
    combined = combined.dropna()
    combined = combined[abs(combined) < float('inf')]
    if len(combined) == 0:
        return None

    global_mean = float(combined.mean())
    global_std = float(combined.std(ddof=0)) if len(combined) > 1 else 0

    # First pass: resolve per-file limits to determine global limit range
    all_dsets = list(datasets.values())
    colors = ['#0077BB', '#EE7733', '#009988', '#CC3311', '#33BBEE', '#EE3377', '#BBBBBB', '#648FFF']
    lot_data_pre = []  # Pre-compute per-file stats
    global_lsl = None  # Minimum LSL across all files
    global_usl = None  # Maximum USL across all files

    for idx, (fid, ds) in enumerate(datasets.items()):
        # Clean per-file data
        series = ds['series'].dropna()
        series = series[abs(series) < float('inf')]
        if len(series) == 0:
            continue

        mean_v = float(series.mean())
        std_v = float(series.std(ddof=0)) if len(series) > 1 else 0
        spec_lower, spec_upper = _resolve_param_limits(
            ds.get('df'), ds.get('metadata', {}), param, series
        )
        # Resolve display limits based on range_type (same logic as single-file)
        if range_type == 'RDL':
            display_lower, display_upper = spec_lower, spec_upper
        elif range_type in ('S3', 'S4', 'S6') and std_v > 0:
            n = int(range_type[1:])  # S3→3 / S10→10（[1] 只取一位，S10+ 会解析错）
            display_lower = mean_v - n * std_v
            display_upper = mean_v + n * std_v
        elif range_type == 'DR':
            display_lower = float(series.min())
            display_upper = float(series.max())
        elif range_type == 'CL' and custom_low is not None and custom_high is not None:
            display_lower, display_upper = custom_low, custom_high
        else:
            display_lower, display_upper = spec_lower, spec_upper
        # Track global min LSL and max USL (for bin range, always use spec limits)
        if spec_lower is not None:
            global_lsl = min(global_lsl, spec_lower) if global_lsl is not None else spec_lower
        if spec_upper is not None:
            global_usl = max(global_usl, spec_upper) if global_usl is not None else spec_upper
        lot_data_pre.append({
            'fid': fid,
            'ds': ds,
            'series': series,  # Use cleaned series
            'idx': idx,
            'mean_v': mean_v,
            'std_v': std_v,
            'lower_limit': spec_lower,
            'upper_limit': spec_upper,
            'display_lower': display_lower,
            'display_upper': display_upper,
        })

    # Resolve bin range: use range_type-based resolution, ensure all limit lines are visible
    bin_min, bin_max = _resolve_multi_range(
        range_type, combined, global_mean, global_std,
        all_dsets, param, custom_low, custom_high,
    )
    # Expand range to include all limit lines (ensure each file's limits are fully visible)
    if global_lsl is not None:
        bin_min = min(bin_min, global_lsl)
    if global_usl is not None:
        bin_max = max(bin_max, global_usl)
    # Degenerate range fallback
    if bin_min == bin_max:
        bin_min = float(combined.min())
        bin_max = float(combined.max())
    if bin_min == bin_max:
        bin_min -= 0.5
        bin_max += 0.5
    data_gap = safe_gap(bin_min, bin_max)
    bin_start = bin_min - 2.5 * data_gap

    # Build bin edges with underflow (-inf) and overflow (+inf) bins
    # Same pattern as single-file: [underflow] [bin1]..[bin24] [overflow]
    # 25 inner edges → 24 normal bins（eedeceb 重构时误写 range(26) 多出 1 个
    # normal bin，X 轴 27 个坐标与单文件直方图 26 个不一致——回归修复）
    inner_edges = [bin_start + j * data_gap for j in range(25)]
    all_bins = np.array([-np.inf] + inner_edges + [np.inf])
    # 27 edges → 26 bins: 1 underflow + 24 normal + 1 overflow

    # Bin centers: underflow/overflow use edge values, normal bins use midpoint
    bin_centers = [inner_edges[0] - data_gap]  # underflow center
    bin_centers += [(inner_edges[i] + inner_edges[i + 1]) / 2 for i in range(24)]
    bin_centers.append(inner_edges[-1] + data_gap)  # overflow center
    bin_count = len(bin_centers)

    # Second pass: compute histograms and assemble lot_data
    lot_data = []
    for pre in lot_data_pre:
        fid = pre['fid']
        ds = pre['ds']
        series = pre['series']  # Use cleaned series
        idx = pre['idx']
        hist, _ = np.histogram(series, bins=all_bins)
        # 6 位小数保精度：小占比 bin 不归零（回归：tiny-fail-bar）
        pcts = [
            round(c / len(series) * 100, 6) if len(series) > 0 else 0.0
            for c in hist
        ]
        bar_data = [[bin_centers[i], pcts[i]] for i in range(bin_count)]
        lower_limit = pre['lower_limit']
        upper_limit = pre['upper_limit']
        display_lower = pre['display_lower']
        display_upper = pre['display_upper']
        # Fail count uses the spec limits (raw metadata mins/maxs are
        # strings like "0" or "MIN", so comparing the series against them
        # directly raises). When a bound is absent, treat it as ±inf.
        lo = lower_limit if lower_limit is not None else -float('inf')
        hi = upper_limit if upper_limit is not None else float('inf')
        fail = int(((series < lo) | (series > hi)).sum())
        lot_data.append({
            'name': ds.get('name', fid),
            'file_id': ds.get('file_id'),
            'color': colors[idx % len(colors)],
            'bar_data': bar_data,
            'lower_limit': lower_limit,
            'upper_limit': upper_limit,
            'display_lower': display_lower,
            'display_upper': display_upper,
            'mean': round(pre['mean_v'], 6),
            'std': round(pre['std_v'], 6),
            'count': len(series),
            'fail': fail,
            'yield_pct': round(
                (len(series) - fail) / len(series) * 100, 2
            ),
            'min_v': round(float(series.min()), 6),
            'max_v': round(float(series.max()), 6),
        })

    return {
        'param': param,
        'global_mean': round(global_mean, 6),
        'global_std': round(global_std, 6),
        'chart_min': round(float(inner_edges[0]), 6),
        'chart_max': round(float(inner_edges[-1]), 6),
        'bin_centers': bin_centers,
        'lot_data': lot_data,
        'global_lsl': round(float(global_lsl), 6) if global_lsl is not None else None,
        'global_usl': round(float(global_usl), 6) if global_usl is not None else None,
    }
