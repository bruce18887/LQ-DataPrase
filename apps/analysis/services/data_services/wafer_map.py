"""Wafer map data computation."""

import math

from apps.analysis.services.statistics import (
    compute_wafer_fail_data,
    get_site_column,
    get_serial_column,
    get_bin_column,
)

# 分区半径比例：必须与前端 WaferMapPanel.buildOption 画的圆环一致
ZONE_DEFS = (('中心区', 1.0 / 3.0), ('中间区', 2.0 / 3.0), ('边缘区', 1.0))


def compute_wafer_geometry(x_vals, y_vals):
    """晶圆外接几何（圆心 / 半径 / die 尺寸），无有效坐标时返回 ``None``。

    晶圆图与分区统计共用此单一来源：两处各算一份会导致画出的环和
    分区归属对不上。
    """
    if not x_vals:
        return None

    center_x = (min(x_vals) + max(x_vals)) / 2
    center_y = (min(y_vals) + max(y_vals)) / 2
    radius = max(max(x_vals) - min(x_vals), max(y_vals) - min(y_vals)) / 2 * 1.08

    unique_x = sorted(set(x_vals))
    die_x = 1
    if len(unique_x) > 1:
        gaps = [abs(unique_x[i + 1] - unique_x[i]) for i in range(len(unique_x) - 1)]
        die_x = min(gaps)

    return {
        'center_x': round(center_x, 2),
        'center_y': round(center_y, 2),
        'radius': round(radius, 2),
        'die_size': round(die_x, 2),
    }


def compute_wafer_zone_stats(xs, ys, fail_flags, wafer):
    """按半径 1/3、2/3 把 die 分到中心/中间/边缘三区并统计良率。

    ``wafer`` 须为 :func:`compute_wafer_geometry` 的结果；``None``（无有效坐标）
    时返回空列表。非有限坐标的行跳过，空区的 ``yield`` 为 ``None``
    而不是 0 —— 前端据此区分「没有 die」与「良率 0%」。
    """
    if not wafer:
        return []

    center_x, center_y, radius = wafer['center_x'], wafer['center_y'], wafer['radius']
    bounds = [radius * ratio for _, ratio in ZONE_DEFS]
    # 每区累计 [pass, total]
    counters = [[0, 0] for _ in ZONE_DEFS]

    for x, y, failed in zip(xs, ys, fail_flags):
        try:
            xf, yf = float(x), float(y)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(xf) and math.isfinite(yf)):
            continue
        distance = math.hypot(xf - center_x, yf - center_y)
        # 最后一区是兜底档：外接圆之外的角 die 也必须计入，否则分区总数
        # 小于晶圆图 die 总数（悄悄漏数）。
        zone_index = len(bounds) - 1
        for i, upper in enumerate(bounds[:-1]):
            if distance <= upper:
                zone_index = i
                break
        counters[zone_index][1] += 1
        if not failed:
            counters[zone_index][0] += 1

    zones = []
    for (name, _), (pass_count, total) in zip(ZONE_DEFS, counters):
        zones.append({
            'name': name,
            'total': total,
            'pass': pass_count,
            'fail': total - pass_count,
            'yield': (pass_count / total * 100) if total else None,
        })
    return zones


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

    return {
        'points': points,
        'stats': wafer_stats,
        'wafer': compute_wafer_geometry(x_vals, y_vals),
    }
