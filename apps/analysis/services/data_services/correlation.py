"""Correlation scatter computation."""

import numpy as np

from apps.analysis.services.statistics import (
    get_1d_from,
    get_site_column,
)
from apps.analysis.services.statistics.outliers import detect_outliers_iqr


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

    # Detect outliers for both axes
    x_outlier_info = detect_outliers_iqr(x_vals, include_values=False)
    y_outlier_info = detect_outliers_iqr(y_vals, include_values=False)

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
        'x_outlier_info': x_outlier_info,
        'y_outlier_info': y_outlier_info,
    }
