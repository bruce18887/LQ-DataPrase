"""Site statistics and yield analysis functions."""

from typing import Optional, Dict, List, Tuple, Any

import pandas as pd

from .helpers import ensure_numeric, get_1d_from, site_sort_key
from .limits import resolve_spec_limits

from pandas.api.types import is_bool_dtype, is_numeric_dtype


def _no_mask(site_series: pd.Series) -> pd.Series:
    """全 False 掩码（缺失的规格限侧不参与比较）。"""
    return pd.Series([False] * len(site_series), index=site_series.index)


def compute_site_stats(site_series: pd.Series, site_index, lower_limit: Optional[float], upper_limit: Optional[float],
                       spec_lower: Optional[float], spec_upper: Optional[float], is_serial: bool) -> List[Dict]:
    if isinstance(site_index, pd.DataFrame):
        site_index = site_index.iloc[:, 0]
    lo, hi = (spec_lower, spec_upper) if is_serial else (lower_limit, upper_limit)
    # 缺失侧不参与比较。限值现在可能是 None（``resolve_spec_limit`` 对缺失/
    # 占位/字面 'Min'/'Max' 一律返回 None）。旧代码拿幻影 0.0 当真限值，
    # 单边限参数会产生幽灵 fail：例如真限 min=''(→0.0)、max=5.5，而参数值
    # 分布在 −3~−1 时全部被判 fail，晶圆图整片红。
    mask_below = (site_series < lo) if lo is not None else _no_mask(site_series)
    mask_above = (site_series > hi) if hi is not None else _no_mask(site_series)
    mask_fail = mask_below | mask_above

    grouped = site_series.groupby(site_index)
    totals = grouped.size()
    fail_counts = mask_fail.groupby(site_index).sum()
    exceed_mins = mask_below.groupby(site_index).sum()
    exceed_maxs = mask_above.groupby(site_index).sum()

    total_all = int(totals.sum())
    fail_all = int(fail_counts.sum())
    # total_all == 0 意味着根本没数据，不能报成「100% 良率」（旧行为）。
    yield_all = ((total_all - fail_all) / total_all * 100) if total_all > 0 else None

    site_data_list = []
    # Sort site values: numeric first (sorted numerically), then string (sorted alphabetically)

    def _fmt_count(count: int, total: int) -> str:
        """数量(百分比)格式，百分比 3 位小数：3(0.181%)"""
        pct = (count / total * 100) if total > 0 else 0.0
        return f'{count}({pct:.3f}%)'

    for site in sorted(totals.index, key=site_sort_key):
        total = int(totals.get(site, 0))
        fail_count = int(fail_counts.get(site, 0))
        exceed_min = int(exceed_mins.get(site, 0))
        exceed_max = int(exceed_maxs.get(site, 0))
        yield_rate = ((total - fail_count) / total * 100) if total > 0 else 100
        site_data_list.append({
            'Site': f'Site{site}',
            # Yield: 百分比 3 位小数 + 括号内总数量：99.508%(1626)
            'Yield': f'{yield_rate:.3f}%({total})',
            # Fail/<Min/>Max: 数量(百分比)格式：8(0.493%)
            'FailCount': _fmt_count(fail_count, total),
            'ExceedMin': _fmt_count(exceed_min, total),
            'ExceedMax': _fmt_count(exceed_max, total),
            # 数字字段供前端行样式等逻辑使用（展示用字符串在上面）
            'FailCountNum': fail_count,
            'TotalNum': total,
        })
    site_data_list.append({
        'Site': 'ALL Site',
        'Yield': (f'{yield_all:.3f}%({total_all})' if yield_all is not None
                  else f'N/A({total_all})'),
        'FailCount': _fmt_count(fail_all, total_all),
        'ExceedMin': _fmt_count(int(exceed_mins.sum()), total_all),
        'ExceedMax': _fmt_count(int(exceed_maxs.sum()), total_all),
        'FailCountNum': fail_all,
        'TotalNum': total_all,
    })
    return site_data_list


def compute_site_yield_data(df: pd.DataFrame, bin_col: str, site_col: str, pass_bin_value: Any = 1) -> Dict:
    # 获取所有唯一的site值，并过滤掉无效数据
    raw_site_values = get_1d_from(df, site_col).unique()

    # 过滤并转换site值：只保留可以转换为数字的值
    valid_sites = []
    for sv in raw_site_values:
        try:
            # 尝试转换为数字
            numeric_val = float(sv)
            # 过滤掉NaN和无穷大
            if not (pd.isna(numeric_val) or numeric_val == float('inf') or numeric_val == float('-inf')):
                valid_sites.append(sv)
        except (ValueError, TypeError):
            # 跳过无法转换为数字的值（如 'Data Collection Start Date'）
            pass

    if not valid_sites:
        return {'yield_data': [], 'yield_values': []}

    # 按数值排序（先转换为float再排序）
    site_values = sorted(valid_sites, key=lambda x: float(x))

    site_bin_cross = pd.crosstab(get_1d_from(df, bin_col), get_1d_from(df, site_col))

    yield_data_list = []
    yield_values = []

    pass_bin_raw = None
    for bv in site_bin_cross.index:
        try:
            if int(float(bv)) == int(float(pass_bin_value)):
                pass_bin_raw = bv
                break
        except (ValueError, TypeError):
            pass

    for site in site_values:
        site_total = int(site_bin_cross[site].sum()) if site in site_bin_cross.columns else 0
        site_pass_count = 0
        if pass_bin_raw is not None:
            if pass_bin_raw in site_bin_cross.index and site in site_bin_cross.columns:
                site_pass_count = int(site_bin_cross.loc[pass_bin_raw, site])

        yield_pct = round((site_pass_count / site_total * 100), 6) if site_total > 0 else 0.0

        # 格式化Site名称：加Site前缀
        try:
            site_num = float(site)
            if site_num == int(site_num):
                site_display = f'Site{int(site_num)}'
            else:
                site_display = str(site)
        except (ValueError, TypeError):
            site_display = str(site)

        yield_data_list.append({
            'Site': site_display,
            'Total': site_total,
            'PassCount': site_pass_count,
            'Yield': f"{yield_pct:.2f}",
        })
        yield_values.append(yield_pct)

    # Build per-site per-bin breakdown: {site_display: {bin_name: count}}
    site_breakdown = {}
    for site in site_values:
        try:
            site_num = float(site)
            site_display = f'Site{int(site_num)}' if site_num == int(site_num) else str(site)
        except (ValueError, TypeError):
            site_display = str(site)
        bin_counts = {}
        if site in site_bin_cross.columns:
            for bv in site_bin_cross.index:
                bin_counts[str(bv)] = int(site_bin_cross.loc[bv, site])
        site_breakdown[site_display] = bin_counts

    result = {'yield_data': yield_data_list, 'yield_values': yield_values, 'site_breakdown': site_breakdown}

    if yield_values:
        max_yield = max(yield_values)
        min_yield = min(yield_values)
        max_idx = yield_values.index(max_yield)
        min_idx = yield_values.index(min_yield)
        result['max_yield_site'] = yield_data_list[max_idx]['Site']
        result['min_yield_site'] = yield_data_list[min_idx]['Site']
        result['max_yield'] = max_yield
        result['min_yield'] = min_yield
        result['yield_diff'] = max_yield - min_yield

    return result


def _limit_fail_mask(data_series: pd.Series, lower_limit: Optional[float],
                     upper_limit: Optional[float]) -> pd.Series:
    """按**存在**的规格限侧构造 fail 掩码；两侧都缺失 → 全 False。

    旧写法 `if lower_limit != 0.0 or upper_limit != 0.0:` 只要一侧是真限值
    就进入 `(data < lower) | (data > upper)`，另一侧的幻影 0.0 仍在参与比较：
    例如真限 min=''(→0.0)、max=5.5，参数值分布在 −3~−1 时全判 fail，
    晶圆图整片红。NaN 与限值比较为 False，不会被当成 fail。
    """
    mask = pd.Series([False] * len(data_series), index=data_series.index)
    if lower_limit is not None:
        mask = mask | (data_series < lower_limit)
    if upper_limit is not None:
        mask = mask | (data_series > upper_limit)
    return mask


def compute_wafer_fail_data(df: pd.DataFrame, metadata: Optional[Dict] = None,
                            selected_param: Optional[str] = None) -> Tuple[pd.Series, Dict]:
    fail_mask = pd.Series([False] * len(df), index=df.index)
    if selected_param and selected_param in df.columns and metadata:
        # ensure_numeric（不 dropna）保留全长与原索引，同时把 bool 转 float、
        # 无法转换的转 NaN；filter_finite 会掉行，不能用于构造全长掩码。
        data_series = ensure_numeric(df, selected_param)
        lower_limit, upper_limit = resolve_spec_limits(metadata, selected_param)
        fail_mask = _limit_fail_mask(data_series, lower_limit, upper_limit)
    else:
        if metadata and 'mins' in metadata and 'maxs' in metadata:
            for col in df.columns:
                # dtype 白名单 ('int64','float64') 漏掉 int32/float32/UInt8，
                # 且 pandas 3.0 下字符串列是 str dtype 而不是 object；
                # bool（真实数据的 Dut_Pass）不是测量值，必须显式排除。
                if not (is_numeric_dtype(df[col]) and not is_bool_dtype(df[col])):
                    continue
                if col not in metadata['mins'] or col not in metadata['maxs']:
                    continue
                data_series = ensure_numeric(df, col)
                lower_limit, upper_limit = resolve_spec_limits(metadata, col)
                fail_mask = fail_mask | _limit_fail_mask(
                    data_series, lower_limit, upper_limit)

    total = len(df)
    pass_count = int((~fail_mask).sum())
    fail_count = int(fail_mask.sum())
    # 6 位小数：对齐项目口径（limits.compute_pass_yield 同为 round(..., 6)），
    # 1/50000 = 0.002% 不因舍入归零（回归：tiny-fail-bar）。
    yield_pct = round((pass_count / total * 100), 6) if total > 0 else 0.0

    stats = {'total': total, 'pass_count': pass_count, 'fail_count': fail_count, 'yield_pct': yield_pct}
    return fail_mask, stats
