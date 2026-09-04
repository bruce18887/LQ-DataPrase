"""Serial distribution computation."""

import numpy as np
import pandas as pd

from apps.analysis.services.statistics import (
    compute_range_statistics,
    filter_finite,
    get_1d_from,
    get_bin_column,
    get_site_column,
    get_serial_column,
    get_serial_candidates,
)
from apps.analysis.services.statistics.limits import is_pass_bin
from apps.analysis.services.limits import resolve_limits
from apps.analysis.services.statistics.outliers import detect_outliers_iqr
from apps.analysis.services.statistics.downsample import (
    bucket_minmax_indices,
    DOWN_SAMPLE_THRESHOLD,
)


def compute_serial_distribution_data(df, metadata, param, range_type,
                                     chart_config, serial_col=None,
                                     iqr_multiplier: float = 1.5):
    """Build serial-distribution scatter data, continuous serials, and mark
    lines.

    ``serial_col`` 显式指定序列列（前端选择器覆盖）；缺省自动检测
    （优先级：Serial_No > Dut_No > PART_ID）。

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
    if serial_col is None:
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
    # 统计量必须与 plotted 数据**同源**：图上每个 serial 只画最后一次重测值
    # （serial_grouped = groupby(serial).last()），而旧写法用含全部重测行的
    # 原始 df 算 mean/std/±σ 标记线/outlier 栅栏——同一响应里 fail/pass_count
    # 来自去重集、统计量来自重测膨胀集，两者互相矛盾。
    # filter_finite 同时完成 bool/str coerce 与 inf 过滤（旧写法只 dropna）。
    if param in serial_grouped.columns:
        data_series = filter_finite(serial_grouped[param])
    else:
        data_series = filter_finite(get_1d_from(df, param))
    stats = compute_range_statistics(data_series, metadata, param)
    outlier_info = detect_outliers_iqr(
        data_series, include_values=False,
        spec_limits=(stats['rdl'][0], stats['rdl'][1]),
        # 跟随用户的「敏感度 (IQR 倍数)」：旧写法写死 1.5，调敏感度后
        # 直方图变了而序列分布的异常值标记不变，同屏矛盾。
        iqr_multiplier=iqr_multiplier,
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

    def _downsample_points(pts):
        """大数据量保形降采样（仅影响传输/绘制点集）：

        - 按 serial 分桶 M4/MinMax 保 value 极值轮廓（value 为 y 轴）；
        - **anchor ≠ 0 的点强制保留**（超界值被锚定到轴边，视觉信息
          不能丢）；无测量值点（value 为 None/NaN）不参与极值选择；
        - pass/fail_count、均值/限值等统计字段由调用方在全量数据上
          计算，不受采样影响。
        """
        if len(pts) <= DOWN_SAMPLE_THRESHOLD:
            return pts
        serials = np.array([p[0] for p in pts], dtype=float)
        values = np.array(
            [np.nan if p[1] is None else float(p[1]) for p in pts],
            dtype=float)
        keep = bucket_minmax_indices(serials, values)
        anchors = [i for i, p in enumerate(pts)
                   if len(p) > 3 and p[3] != 0]
        if anchors:
            keep = np.union1d(keep, np.array(anchors, dtype=int))
        return [pts[i] for i in keep]

    series_data = []
    if site_col:
        for si, site in enumerate(
                sorted(serial_grouped[site_col].unique(), key=str)):
            sdf = serial_grouped[serial_grouped[site_col] == site]
            series_data.append({
                'name': f'Site {site}',
                'type': 'scatter',
                'data': _downsample_points(_build_points(sdf)),
                'symbolSize': 6,
            })
    else:
        series_data.append({
            'name': param,
            'type': 'scatter',
            'data': _downsample_points(_build_points(serial_grouped)),
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
        'serial_candidates': get_serial_candidates(df),
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
