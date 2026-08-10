"""Wafer map data computation."""

import math

from apps.analysis.services.statistics import (
    compute_wafer_fail_data,
    get_site_column,
    get_serial_column,
    get_bin_column,
)


def compute_wafer_map_data(df, metadata, param, color_by, x_col, y_col):
    """Build wafer-map point list, wafer boundary circle, and die size.

    Returns a dict with ``points``, ``stats`` (from
    :func:`~statistics.compute_wafer_fail_data`) and ``wafer`` info.
    """
    fail_mask, wafer_stats = compute_wafer_fail_data(df, metadata, param)
    site_col = get_site_column(df)
    # get_serial_column 已内置 PART_ID 回退（STS8200 无 Serial 列）
    serial_col = get_serial_column(df)
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
