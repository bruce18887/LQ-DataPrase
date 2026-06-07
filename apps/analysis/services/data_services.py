"""
Data computation service for analysis views.

Each function encapsulates the inline business logic previously embedded
directly in views.py action methods.  This makes the computations testable
and keeps the view layer thin.
"""
import math
import numpy as np
import pandas as pd

from apps.analysis.services.statistics import (
    compute_cpk,
    compute_range_statistics,
    compute_site_stats,
    compute_wafer_fail_data,
    get_1d_from,
    get_site_column,
    get_serial_column,
    get_bin_column,
    safe_gap,
)
from apps.analysis.services.limits import resolve_limits


# ---------------------------------------------------------------------------
# histogram
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# wafer_map
# ---------------------------------------------------------------------------

def compute_wafer_map_data(df, metadata, param, color_by, x_col, y_col):
    """Build wafer-map point list, wafer boundary circle, and die size.

    Returns a dict with ``points``, ``stats`` (from
    :func:`~statistics.compute_wafer_fail_data`) and ``wafer`` info.
    """
    fail_mask, wafer_stats = compute_wafer_fail_data(df, metadata, param)
    site_col = get_site_column(df)
    serial_col = get_serial_column(df)
    # STS8200 fallback: look for columns with 'part' and 'id' in name
    if not serial_col:
        for col in df.columns:
            col_lower = col.lower()
            if 'part' in col_lower and 'id' in col_lower:
                serial_col = col
                break
    bin_col = get_bin_column(df, metadata)

    points = []
    for idx in df.index:
        try:
            x_val = float(df.loc[idx, x_col])
            y_val = float(df.loc[idx, y_col])
            if not math.isfinite(x_val) or not math.isfinite(y_val):
                continue
        except (ValueError, TypeError):
            continue
        point = {
            'x': x_val,
            'y': y_val,
            'status': 'Fail' if fail_mask.loc[idx] else 'Pass',
        }
        if serial_col:
            point['serial'] = str(df.loc[idx, serial_col])
        if bin_col:
            point['bin'] = str(df.loc[idx, bin_col])
        if site_col:
            point['site'] = str(df.loc[idx, site_col])
        if color_by == 'site' and site_col:
            point['color_group'] = f'Site {df.loc[idx, site_col]}'
        points.append(point)

    x_vals = [p['x'] for p in points]
    y_vals = [p['y'] for p in points]
    if not x_vals:
        return {'points': [], 'stats': wafer_stats, 'wafer': None}

    center_x = (min(x_vals) + max(x_vals)) / 2
    center_y = (min(y_vals) + max(y_vals)) / 2
    radius = max(max(x_vals) - min(x_vals), max(y_vals) - min(y_vals)) / 2 * 1.08

    unique_x = sorted(set(x_vals))
    die_x = 1
    if len(unique_x) > 1:
        gaps = [abs(unique_x[i + 1] - unique_x[i]) for i in range(len(unique_x) - 1)]
        die_x = min(gaps)

    return {
        'points': points,
        'stats': wafer_stats,
        'wafer': {
            'center_x': round(center_x, 2),
            'center_y': round(center_y, 2),
            'radius': round(radius, 2),
            'die_size': round(die_x, 2),
        },
    }


# ---------------------------------------------------------------------------
# multi_lot
# ---------------------------------------------------------------------------

def compute_multi_lot_distribution(datasets, all_series, param):
    """Compute multi-lot distribution bins and lot-level stats.

    Args:
        datasets: ``{fid: {series, metadata, name, ...}}``.
        all_series: List of ``pd.Series``, one per lot.
        param: Parameter name.

    Returns:
        Dict with keys ``param``, ``global_mean``, ``global_std``,
        ``chart_min``, ``chart_max``, ``bin_centers``, ``lot_data``.
    """
    if not all_series:
        return None

    combined = pd.concat(all_series)
    global_mean = float(combined.mean())
    global_std = float(combined.std(ddof=0)) if len(combined) > 1 else 0
    min_val = float(combined.min())
    max_val = float(combined.max())
    bin_count = 25
    bin_width = (max_val - min_val) / bin_count if max_val != min_val else 1
    bins = np.linspace(min_val - bin_width / 2, max_val + bin_width / 2, bin_count + 1)
    bin_centers = [float((bins[i] + bins[i + 1]) / 2) for i in range(bin_count)]

    colors = ['#E53935', '#1E88E5', '#43A047', '#F9A825', '#8E24AA',
              '#00ACC1', '#F57C00', '#D81B60']
    lot_data = []
    for idx, (fid, ds) in enumerate(datasets.items()):
        hist, _ = np.histogram(ds['series'], bins=bins)
        pcts = [
            round(c / len(ds['series']) * 100, 2) if len(ds['series']) > 0 else 0
            for c in hist
        ]
        bar_data = [[bin_centers[i], pcts[i]] for i in range(bin_count)]
        mean_v = float(ds['series'].mean())
        std_v = float(ds['series'].std(ddof=0)) if len(ds['series']) > 1 else 0
        mins_dict = ds.get('metadata', {}).get('mins', {})
        maxs_dict = ds.get('metadata', {}).get('maxs', {})
        fail = int(
            (
                (ds['series'] < mins_dict.get(param, -1e9))
                | (ds['series'] > maxs_dict.get(param, 1e9))
            ).sum()
        )
        lot_data.append({
            'name': ds.get('name', fid),
            'color': colors[idx % len(colors)],
            'bar_data': bar_data,
            'mean': round(mean_v, 6),
            'std': round(std_v, 6),
            'count': len(ds['series']),
            'fail': fail,
            'yield_pct': round(
                (len(ds['series']) - fail) / len(ds['series']) * 100, 2
            ),
            'min_v': round(float(ds['series'].min()), 6),
            'max_v': round(float(ds['series'].max()), 6),
        })

    return {
        'param': param,
        'global_mean': round(global_mean, 6),
        'global_std': round(global_std, 6),
        'chart_min': round(float(bins[0]), 6),
        'chart_max': round(float(bins[-1]), 6),
        'bin_centers': bin_centers,
        'lot_data': lot_data,
    }


# ---------------------------------------------------------------------------
# correlation
# ---------------------------------------------------------------------------

def compute_correlation_scatter(df, param_x, param_y):
    """Build scatter-point series and Pearson r for two parameters.

    Returns a dict with ``param_x``, ``param_y``, ``n``, ``pearson_r``,
    ``series_data`` (one series per site if a site column exists, otherwise
    a single "Data" series).
    """
    x_series = get_1d_from(df, param_x)
    y_series = get_1d_from(df, param_y)

    # remove inf/nan
    def finite_mask(s):
        return s.apply(lambda v: abs(float(v)) < float('inf')) \
            if hasattr(s, 'apply') else True

    mask = finite_mask(x_series) & finite_mask(y_series)
    x_series = x_series[mask].dropna()
    y_series = y_series[mask].dropna()
    common_idx = x_series.index.intersection(y_series.index)
    x_vals = x_series.loc[common_idx].astype(float)
    y_vals = y_series.loc[common_idx].astype(float)

    site_col = get_site_column(df)
    series_data = []
    if site_col:
        site_idx = get_1d_from(df, site_col).loc[common_idx]
        for site in sorted(site_idx.unique(), key=str):
            smask = site_idx == site
            pts = [
                [float(x_vals[i]), float(y_vals[i])]
                for i in x_vals.index[smask]
                if not np.isnan(x_vals[i]) and not np.isnan(y_vals[i])
            ]
            if pts:
                series_data.append({'name': f'Site {site}', 'data': pts})
    else:
        pts = [
            [float(x_vals[i]), float(y_vals[i])]
            for i in x_vals.index
            if not np.isnan(x_vals[i]) and not np.isnan(y_vals[i])
        ]
        if pts:
            series_data.append({'name': 'Data', 'data': pts})

    n = len(common_idx)
    pearson_r = 0.0
    if n > 2:
        x_arr = x_vals.values
        y_arr = y_vals.values
        sx = np.std(x_arr, ddof=0)
        sy = np.std(y_arr, ddof=0)
        if sx > 0 and sy > 0:
            pearson_r = float(np.corrcoef(x_arr, y_arr)[0, 1])

    return {
        'param_x': param_x,
        'param_y': param_y,
        'n': n,
        'pearson_r': round(pearson_r, 6),
        'series_data': series_data,
    }


# ---------------------------------------------------------------------------
# serial_distribution
# ---------------------------------------------------------------------------

def compute_serial_distribution_data(df, metadata, param, range_type,
                                     chart_config):
    """Build serial-distribution scatter data, continuous serials, and mark
    lines.

    Returns the full response dict (*except* ``param`` and ``unit`` which
    the caller adds), or ``None`` if no serial column exists.
    """
    serial_col = get_serial_column(df)
    if not serial_col:
        return None

    site_col = get_site_column(df)

    # -- Build grouped data (with / without site) -------------------------
    if site_col:
        sws = df[[serial_col, site_col, param]].copy()
        sws[site_col] = get_1d_from(sws, site_col)
        sws[param] = pd.to_numeric(sws[param], errors='coerce')
        sws = sws.dropna(subset=[param])
        sws = sws.iloc[np.isfinite(sws[param].values)]
        sws = sws.reset_index(drop=True)
        sws[serial_col] = pd.to_numeric(sws[serial_col], errors='coerce')
        site_key = get_1d_from(sws, site_col)
        serial_key = get_1d_from(sws, serial_col)
        serial_grouped = sws.groupby([site_key, serial_key])[param].first()
        serial_grouped.index.names = ['__idx_0__', '__idx_1__']
        serial_grouped = serial_grouped.reset_index()
        expected = []
        seen = set()
        for name in [site_col, serial_col, param]:
            if name not in seen:
                seen.add(name)
                expected.append(name)
        serial_grouped = serial_grouped.iloc[:, :len(expected)]
        serial_grouped.columns = expected
    else:
        serial_site_data = df[[serial_col, param]].copy()
        serial_site_data[param] = pd.to_numeric(
            serial_site_data[param], errors='coerce')
        serial_site_data = serial_site_data.dropna(subset=[param])
        serial_site_data = serial_site_data.iloc[
            np.isfinite(serial_site_data[param].values)]
        serial_site_data = serial_site_data.reset_index(drop=True)
        serial_site_data[serial_col] = pd.to_numeric(
            serial_site_data[serial_col], errors='coerce')
        serial_key = get_1d_from(serial_site_data, serial_col)
        serial_grouped = serial_site_data.groupby(serial_key)[param].first()
        serial_grouped.index.name = '__idx_0__'
        serial_grouped = serial_grouped.reset_index()
        expected = []
        seen = set()
        for name in [serial_col, param]:
            if name not in seen:
                seen.add(name)
                expected.append(name)
        serial_grouped = serial_grouped.iloc[:, :len(expected)]
        serial_grouped.columns = expected

    # -- Build continuous serials -----------------------------------------
    all_serials = serial_grouped[serial_col].dropna()
    try:
        all_serials = all_serials.astype(int)
        continuous_serials = list(
            range(int(all_serials.min()), int(all_serials.max()) + 1))
    except (ValueError, TypeError):
        continuous_serials = sorted(
            list(set(all_serials.dropna().tolist())))

    # -- Build series_data ------------------------------------------------
    series_data = []
    if site_col:
        for si, site in enumerate(
                sorted(serial_grouped[site_col].unique(), key=str)):
            sdf = serial_grouped[serial_grouped[site_col] == site]
            sv_col = param if param in serial_grouped.columns else serial_col
            sv = dict(zip(
                sdf[serial_col].tolist(), sdf[sv_col].tolist()))
            pts = [[s, sv[s]] for s in continuous_serials if s in sv]
            series_data.append({
                'name': f'Site {site}',
                'type': 'scatter',
                'data': pts,
                'symbolSize': 6,
            })
    else:
        sv_col = param if param in serial_grouped.columns else serial_col
        sv = dict(zip(
            serial_grouped[serial_col].tolist(),
            serial_grouped[sv_col].tolist()))
        pts = [[s, sv[s]] for s in continuous_serials if s in sv]
        series_data.append({
            'name': param,
            'type': 'scatter',
            'data': pts,
            'symbolSize': 6,
        })

    # -- Stats & limits ---------------------------------------------------
    data_series = get_1d_from(df, param).dropna()
    stats = compute_range_statistics(data_series, metadata, param)
    mean_val = stats['mean']
    std_val = stats['std']
    spec_lower, spec_upper = resolve_limits(range_type, stats)

    # -- Build marks ------------------------------------------------------
    show_limit = 'limit' in chart_config
    show_3sigma = 's3' in chart_config
    show_4sigma = 's4' in chart_config
    show_6sigma = 's6' in chart_config

    marks = []
    if show_limit and spec_lower is not None and spec_upper is not None:
        marks.append({
            'name': '规格限',
            'type': 'scatter',
            'data': [],
            'markLine': {
                'symbol': 'none',
                'precision': 4,
                'data': [
                    {'yAxis': spec_lower,
                     'lineStyle': {'color': '#FF6384', 'width': 3,
                                   'type': 'dashed'},
                     'label': {'show': True, 'formatter': 'LSL',
                               'position': 'end'}},
                    {'yAxis': spec_upper,
                     'lineStyle': {'color': '#FF6384', 'width': 3,
                                   'type': 'dashed'},
                     'label': {'show': True, 'formatter': 'USL',
                               'position': 'end'}},
                ],
            },
        })
    for sigma, flag, color in [
            (3, show_3sigma, '#5470c6'),
            (4, show_4sigma, '#91cc75'),
            (6, show_6sigma, '#fac858')]:
        if flag:
            lower = mean_val - sigma * std_val
            upper = mean_val + sigma * std_val
            marks.append({
                'name': f'{sigma}σ范围',
                'type': 'scatter',
                'data': [],
                'markLine': {
                    'symbol': 'none',
                    'precision': 4,
                    'data': [
                        {'yAxis': lower,
                         'lineStyle': {'color': color, 'width': 3,
                                       'type': 'dotted'},
                         'label': {'show': True,
                                   'formatter': f'{sigma}σ下限',
                                   'position': 'insideEndTop'}},
                        {'yAxis': upper,
                         'lineStyle': {'color': color, 'width': 3,
                                       'type': 'dotted'},
                         'label': {'show': True,
                                   'formatter': f'{sigma}σ上限',
                                   'position': 'insideEndTop'}},
                    ],
                },
            })

    # -- Y-axis limits with padding ---------------------------------------
    y_min = spec_lower
    y_max = spec_upper
    if y_min is not None and y_max is not None and y_max > y_min:
        pad = (y_max - y_min) * 0.1
        y_min = y_min - pad
        y_max = y_max + pad

    return {
        'param': param,
        'unit': metadata.get('units', {}).get(param, ''),
        'serial_col': serial_col,
        'lower_limit': spec_lower,
        'upper_limit': spec_upper,
        'mean': mean_val,
        'std': std_val,
        'series_data': series_data,
        'continuous_serials': continuous_serials,
        'marks': marks,
        'y_min': y_min,
        'y_max': y_max,
    }


# ---------------------------------------------------------------------------
# cpk (table)
# ---------------------------------------------------------------------------

def compute_cpk_table_data(df, metadata, params):
    """Compute CPK table for the given parameters.

    Returns ``{'results': {param: {...}}, 'count': N}``, matching the
    original response shape of ``AnalysisViewSet.cpk``.
    """
    results = {}
    for param in params:
        data_series = get_1d_from(df, param).dropna()
        data_series = data_series[
            data_series.apply(lambda x: abs(x) < float('inf'))]
        if len(data_series) == 0:
            continue

        stats = compute_range_statistics(data_series, metadata, param)
        cpk_result = compute_cpk(
            stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1]
        )
        results[param] = {
            'mean': round(stats['mean'], 6),
            'std': round(stats['std'], 6),
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
        }
    return {'results': results, 'count': len(results)}
