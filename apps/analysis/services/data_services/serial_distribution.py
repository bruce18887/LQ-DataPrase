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
    site_sort_key,
)
from apps.analysis.services.statistics.limits import is_pass_bin
from apps.analysis.services.range_limits import resolve_limits
from apps.analysis.services.statistics.outliers import detect_outliers_iqr
from apps.analysis.services.statistics.downsample import (
    bucket_minmax_indices,
    DOWN_SAMPLE_THRESHOLD,
)


def anchor_for(value, y_min, y_max):
    """点在该 X 轴上的落位方式：0=正常, 1=无测量值, 2=高于 y_max, 3=低于 y_min。"""
    if pd.isna(value):
        return 1
    if y_max is not None and value > y_max:
        return 2
    if y_min is not None and value < y_min:
        return 3
    return 0


def build_serial_points(sdf, serial_col, value_col, continuous_serials,
                        fail_by_serial, y_min, y_max):
    """一个系列（全量或单个 Site）的散点 [serial, value|null, is_fail, anchor]。

    ``fail_by_serial`` 为 None（文件无 Bin 列）时退化成旧的两元组形状，前端
    据此不画 fail 标记。
    """
    sv = dict(zip(sdf[serial_col].tolist(), sdf[value_col].tolist()))
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
                            fail_d[s], anchor_for(v, y_min, y_max)])
    return pts


def downsample_points(pts):
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


def build_mark_lines(spec_lower, spec_upper, mean_val, std_val, chart_config):
    """规格限与 ±3/4/6σ 的 markLine 系列（每项一个空数据 scatter 系列承载线）。"""
    marks = []
    if 'limit' in chart_config and spec_lower is not None and spec_upper is not None:
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
    for sigma, color in [('3', '#5470c6'), ('4', '#91cc75'), ('6', '#fac858')]:
        if f's{sigma}' not in chart_config:
            continue
        lower = mean_val - int(sigma) * std_val
        upper = mean_val + int(sigma) * std_val
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
    return marks


def _group_final_rows(df, param, serial_col, site_col, bin_col):
    """每个 (site, serial)（无 site 时每个 serial）取**最后一行**。

    重测行追加在后面，所以 ``.last()`` 拿到的就是这颗 die 的最终结果；
    param 为 NaN 的行要保留 —— 没测到值的 die 仍有 Bin，必须继续可见，
    而 inf/非数值经 ``to_numeric`` 变 NaN 后同样留下。
    返回列序 ``[site?, serial, param, bin?]`` 的扁平 DataFrame。
    """
    key_cols = ([site_col] if site_col else []) + [serial_col]
    # 查看的参数**可以就是** Bin 列（用户切到 SW_Bin 看每颗 die 的最终 bin），
    # 此时 param 与 bin_col 同名，必须去重：否则 df[cols] 选出两个同名列，
    # frame[param] 返回 DataFrame 而 pd.to_numeric 只收 1 维 → TypeError，
    # 被视图的 except TypeError 报成 400「数据列存在重复或格式异常」——
    # 重复的正是本函数自己造的列。34d09d1 合并两段分组时丢了这条守卫，
    # 由 test/backend/test_serial_fail_count.py 钉住。
    group_cols = list(dict.fromkeys([param] + ([bin_col] if bin_col else [])))
    cols = key_cols + [c for c in group_cols if c not in key_cols]

    frame = df[cols].copy()
    for key in key_cols:
        frame[key] = get_1d_from(frame, key)
    frame[param] = pd.to_numeric(frame[param], errors='coerce')
    frame = frame[np.isfinite(frame[param].values) | frame[param].isna().values]
    frame = frame.reset_index(drop=True)
    frame[serial_col] = pd.to_numeric(frame[serial_col], errors='coerce')

    keys = [get_1d_from(frame, key) for key in key_cols]
    grouped = frame.groupby(
        keys if len(keys) > 1 else keys[0])[group_cols].last()
    if len(keys) > 1:
        grouped.index.names = ['__idx_0__', '__idx_1__']
    else:
        grouped.index.name = '__idx_0__'
    grouped = grouped.reset_index()

    expected = list(dict.fromkeys(key_cols + group_cols))
    grouped = grouped.iloc[:, :len(expected)]
    grouped.columns = expected
    return grouped


def compute_serial_distribution_data(df, metadata, param, range_type,
                                     chart_config, serial_col=None,
                                     iqr_multiplier: float = 1.5,
                                     custom_low=None, custom_high=None):
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

    # One point per (site, serial) — 分组口径见 _group_final_rows
    serial_grouped = _group_final_rows(df, param, serial_col, site_col, bin_col)

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
        as_int = all_serials.astype(int)
        # 整数性校验：astype(int) 对 2.5 这类非整数序列号**截断成功**，而 sv
        # 的键是原始 2.5 → `s in sv` 永远 False，该 die 的点静默丢失（不是
        # anchor=1，是整个点没了，2026-09-05 审查 L2）。非整数走原值集合路径：
        # 不展开 range、不截断，点按原值匹配（前端数值 x 按值映射类别下标）。
        if (as_int == all_serials).all():
            all_serials = as_int
            continuous_serials = list(
                range(int(all_serials.min()), int(all_serials.max()) + 1))
        else:
            raise ValueError
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
    # CL 语义与 histogram 统一为「用户自定义限」：resolve_limits('CL') 的
    # stats['cl'] 是数据极值，把数据 min/max 画成 "LSL/USL" 虚线是幻影限值
    #（三端点同语义，2026-09-05 审查 契约#4）；未提供 custom 时才回退。
    if range_type == 'CL' and custom_low is not None and custom_high is not None:
        spec_lower, spec_upper = float(custom_low), float(custom_high)
    else:
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

    # -- Build series_data ------------------------------------------------
    value_col = param if param in serial_grouped.columns else serial_col

    def _points(sdf):
        return downsample_points(build_serial_points(
            sdf, serial_col, value_col, continuous_serials,
            fail_by_serial, y_min, y_max))

    series_data = []
    if site_col:
        # site_sort_key 而非 key=str：纯数字站点按数值排序，否则字符串序会把
        # Site10 排在 Site2 前面，与 histogram.py / site_yield.py / correlation.py
        # 的图例顺序不一致。
        for si, site in enumerate(
                sorted(serial_grouped[site_col].unique(), key=site_sort_key)):
            sdf = serial_grouped[serial_grouped[site_col] == site]
            series_data.append({
                'name': f'Site {site}',
                'type': 'scatter',
                'data': _points(sdf),
                'symbolSize': 6,
            })
    else:
        series_data.append({
            'name': param,
            'type': 'scatter',
            'data': _points(serial_grouped),
            'symbolSize': 6,
        })

    marks = build_mark_lines(spec_lower, spec_upper, mean_val, std_val,
                             chart_config)

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
