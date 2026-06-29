"""Serial distribution computation."""

import numpy as np
import pandas as pd

from apps.analysis.services.statistics import (
    compute_range_statistics,
    get_1d_from,
    get_site_column,
    get_serial_column,
)
from apps.analysis.services.limits import resolve_limits
from apps.analysis.services.statistics.outliers import detect_outliers_iqr


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

    # param must differ from serial/site columns — they are grouping keys
    if param == serial_col or param == site_col:
        return None

    # Deduplicate columns to prevent DataFrame-vs-Series issues
    df = df.loc[:, ~df.columns.duplicated()]

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
    outlier_info = detect_outliers_iqr(data_series, include_values=False)
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
        'outlier_info': outlier_info,
    }
