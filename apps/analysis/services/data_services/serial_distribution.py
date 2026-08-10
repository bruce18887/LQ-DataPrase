"""Serial distribution computation."""

import numpy as np
import pandas as pd

from apps.analysis.services.statistics import (
    compute_range_statistics,
    get_1d_from,
    get_bin_column,
    get_site_column,
    get_serial_column,
)
from apps.analysis.services.statistics.limits import is_pass_bin
from apps.analysis.services.limits import resolve_limits
from apps.analysis.services.statistics.outliers import detect_outliers_iqr


def compute_serial_distribution_data(df, metadata, param, range_type,
                                     chart_config):
    """Build serial-distribution scatter data, continuous serials, and mark
    lines.

    Returns the full response dict (*except* ``param`` and ``unit`` which
    the caller adds), or ``None`` if no serial column exists.

    Points are emitted as ``[serial, value|null, is_fail, anchor]`` when the
    file has a Bin column:

    * ``is_fail`` — the die's FINAL-row bin != 1 (it may have failed another
      test item while this param's value is inside the limits).  The die-level
      ``fail_count`` matches the file's bin summary, independent of the
      viewed param's value or whether it was measured at all.
    * ``anchor`` — how the front-end must place the point on the visible Y
      axis: ``0`` normal, ``1`` no measured value, ``2`` value above
      ``y_max`` (huge fail values would otherwise be clipped off the
      explicit spec-based axis), ``3`` value below ``y_min``.
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

    bin_col = get_bin_column(df, metadata)

    # -- Build grouped data (with / without site) -------------------------
    # One point per (site, serial) carrying the *final* test row (.last():
    # retest rows append later attempts, so the last row is the die's final
    # result).  NaN param rows are kept — a die without a measurement for
    # this param still has a Bin result and must remain visible.
    if site_col:
        cols = [serial_col, site_col, param]
        if bin_col and bin_col not in cols:
            cols.append(bin_col)
        sws = df[cols].copy()
        sws[site_col] = get_1d_from(sws, site_col)
        sws[param] = pd.to_numeric(sws[param], errors='coerce')
        sws = sws[np.isfinite(sws[param].values) | sws[param].isna().values]
        sws = sws.reset_index(drop=True)
        sws[serial_col] = pd.to_numeric(sws[serial_col], errors='coerce')
        site_key = get_1d_from(sws, site_col)
        serial_key = get_1d_from(sws, serial_col)
        group_cols = [param] + ([bin_col] if bin_col else [])
        serial_grouped = sws.groupby([site_key, serial_key])[group_cols].last()
        serial_grouped.index.names = ['__idx_0__', '__idx_1__']
        serial_grouped = serial_grouped.reset_index()
        expected = []
        seen = set()
        for name in [site_col, serial_col, param]:
            if name not in seen:
                seen.add(name)
                expected.append(name)
        if bin_col and bin_col not in seen:
            expected.append(bin_col)
        serial_grouped = serial_grouped.iloc[:, :len(expected)]
        serial_grouped.columns = expected
    else:
        cols = [serial_col, param]
        if bin_col and bin_col not in cols:
            cols.append(bin_col)
        serial_site_data = df[cols].copy()
        serial_site_data[param] = pd.to_numeric(
            serial_site_data[param], errors='coerce')
        serial_site_data = serial_site_data[
            np.isfinite(serial_site_data[param].values)
            | serial_site_data[param].isna().values]
        serial_site_data = serial_site_data.reset_index(drop=True)
        serial_site_data[serial_col] = pd.to_numeric(
            serial_site_data[serial_col], errors='coerce')
        serial_key = get_1d_from(serial_site_data, serial_col)
        group_cols = [param] + ([bin_col] if bin_col else [])
        serial_grouped = serial_site_data.groupby(serial_key)[group_cols].last()
        serial_grouped.index.name = '__idx_0__'
        serial_grouped = serial_grouped.reset_index()
        expected = []
        seen = set()
        for name in [serial_col, param]:
            if name not in seen:
                seen.add(name)
                expected.append(name)
        if bin_col and bin_col not in seen:
            expected.append(bin_col)
        serial_grouped = serial_grouped.iloc[:, :len(expected)]
        serial_grouped.columns = expected

    # -- Final-bin fail judgement (die level, matches the file's bin summary) --
    # A die is a fail when its FINAL row's bin is not pass — regardless of
    # the viewed param's value (it may have failed another test item) or of
    # whether a value was measured at all.
    fail_count = None
    pass_count = None
    fail_by_serial = None
    if bin_col and bin_col in serial_grouped.columns:
        bin_series = serial_grouped[bin_col]
        pass_bins = {b for b in bin_series.unique() if is_pass_bin(b)}
        is_fail_series = ~bin_series.isin(pass_bins)
        fail_by_serial = dict(zip(
            serial_grouped[serial_col].tolist(),
            is_fail_series.astype(int).tolist()))
        fail_count = int(is_fail_series.sum())
        pass_count = len(serial_grouped) - fail_count

    # -- Build continuous serials -----------------------------------------
    all_serials = serial_grouped[serial_col].dropna()
    try:
        all_serials = all_serials.astype(int)
        continuous_serials = list(
            range(int(all_serials.min()), int(all_serials.max()) + 1))
    except (ValueError, TypeError):
        continuous_serials = sorted(
            list(set(all_serials.dropna().tolist())))

    # -- Stats & limits ---------------------------------------------------
    data_series = get_1d_from(df, param).dropna()
    stats = compute_range_statistics(data_series, metadata, param)
    outlier_info = detect_outliers_iqr(
        data_series, include_values=False,
        spec_limits=(stats['rdl'][0], stats['rdl'][1]),
    )
    mean_val = stats['mean']
    std_val = stats['std']
    spec_lower, spec_upper = resolve_limits(range_type, stats)

    # -- Y-axis limits with padding ---------------------------------------
    # Computed before the points so out-of-range values can be anchor-flagged
    # instead of being clipped off the explicit axis.
    y_min = spec_lower
    y_max = spec_upper
    if y_min is not None and y_max is not None and y_max > y_min:
        pad = (y_max - y_min) * 0.1
        y_min = y_min - pad
        y_max = y_max + pad

    def _anchor(value):
        """0=normal, 1=no value, 2=above y_max, 3=below y_min."""
        if pd.isna(value):
            return 1
        if y_max is not None and value > y_max:
            return 2
        if y_min is not None and value < y_min:
            return 3
        return 0

    # -- Build series_data ------------------------------------------------
    def _build_points(sdf):
        sv_col = param if param in serial_grouped.columns else serial_col
        sv = dict(zip(sdf[serial_col].tolist(), sdf[sv_col].tolist()))
        fail_d = None
        if fail_by_serial is not None:
            fail_d = dict(zip(
                sdf[serial_col].tolist(),
                [fail_by_serial.get(s, 0) for s in sdf[serial_col].tolist()]))
        pts = []
        for s in continuous_serials:
            if s in sv:
                v = sv[s]
                if fail_d is None:
                    pts.append([s, v])
                else:
                    pts.append([s, None if pd.isna(v) else v,
                                fail_d[s], _anchor(v)])
        return pts

    series_data = []
    if site_col:
        for si, site in enumerate(
                sorted(serial_grouped[site_col].unique(), key=str)):
            sdf = serial_grouped[serial_grouped[site_col] == site]
            series_data.append({
                'name': f'Site {site}',
                'type': 'scatter',
                'data': _build_points(sdf),
                'symbolSize': 6,
            })
    else:
        series_data.append({
            'name': param,
            'type': 'scatter',
            'data': _build_points(serial_grouped),
            'symbolSize': 6,
        })

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
        'pass_count': pass_count,
        'fail_count': fail_count,
    }
