"""Wafer map data computation."""

import math

import numpy as np
import pandas as pd

from apps.analysis.services.statistics import (
    compute_wafer_fail_data,
    get_site_column,
    get_serial_column,
    get_bin_column,
    get_1d_from,
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


def _str_column(df, col):
    """按位取列并逐元素 str 化（NaN→'nan'、bool→'True'/'False'）。

    与历史逐行 ``str(df.loc[idx, col])`` 保持一致；重名列走 get_1d_from
    的「取首列」语义，而不是整行被丢弃。
    """
    return get_1d_from(df, col).astype(str).tolist()


def compute_wafer_map_data(df, metadata, param, color_by, x_col, y_col):
    """Build wafer-map point list, wafer boundary circle, and die size.

    Returns a dict with ``points``, ``stats`` (from
    :func:`~statistics.compute_wafer_fail_data`) and ``wafer`` info.

    坐标与标签列都按**整列**取一次（历史上每行做 5–6 次 ``df.loc``，
    10 万行实测 4.7s），非有限坐标用掩码剔除。
    """
    fail_mask, wafer_stats = compute_wafer_fail_data(df, metadata, param)
    site_col = get_site_column(df)
    # get_serial_column 已内置 PART_ID 回退（STS8200 无 Serial 列）
    serial_col = get_serial_column(df)
    bin_col = get_bin_column(df, metadata)

    xs = pd.to_numeric(get_1d_from(df, x_col), errors='coerce').to_numpy(dtype='float64', copy=False)
    ys = pd.to_numeric(get_1d_from(df, y_col), errors='coerce').to_numpy(dtype='float64', copy=False)
    valid = np.isfinite(xs) & np.isfinite(ys)

    serial_vals = _str_column(df, serial_col) if serial_col else None
    bin_vals = _str_column(df, bin_col) if bin_col else None
    site_vals = _str_column(df, site_col) if site_col else None
    statuses = np.where(fail_mask.to_numpy(dtype=bool, copy=False), 'Fail', 'Pass')

    points = []
    for i in np.flatnonzero(valid):
        point = {'x': float(xs[i]), 'y': float(ys[i]), 'status': statuses[i]}
        if serial_vals is not None:
            point['serial'] = serial_vals[i]
        if bin_vals is not None:
            point['bin'] = bin_vals[i]
        if site_vals is not None:
            point['site'] = site_vals[i]
            if color_by == 'site':
                point['color_group'] = f'Site {site_vals[i]}'
        points.append(point)

    x_vals = xs[valid].tolist()
    y_vals = ys[valid].tolist()

    return {
        'points': points,
        'stats': wafer_stats,
        'wafer': compute_wafer_geometry(x_vals, y_vals),
    }
