"""Site statistics and yield analysis functions."""

from typing import Optional, Dict, List, Tuple, Any

import pandas as pd

from .helpers import get_1d_from, site_sort_key
from .limits import parse_limit_string


def compute_site_stats(site_series: pd.Series, site_index, lower_limit: float, upper_limit: float,
                       spec_lower: Optional[float], spec_upper: Optional[float], is_serial: bool) -> List[Dict]:
    if isinstance(site_index, pd.DataFrame):
        site_index = site_index.iloc[:, 0]
    if not is_serial:
        mask_below = site_series < lower_limit
        mask_above = site_series > upper_limit
    else:
        mask_below = site_series < spec_lower if spec_lower is not None else pd.Series([False] * len(site_series), index=site_series.index)
        mask_above = site_series > spec_upper if spec_upper is not None else pd.Series([False] * len(site_series), index=site_series.index)
    mask_fail = mask_below | mask_above

    grouped = site_series.groupby(site_index)
    totals = grouped.size()
    fail_counts = mask_fail.groupby(site_index).sum()
    exceed_mins = mask_below.groupby(site_index).sum()
    exceed_maxs = mask_above.groupby(site_index).sum()

    total_all = int(totals.sum())
    fail_all = int(fail_counts.sum())
    yield_all = ((total_all - fail_all) / total_all * 100) if total_all > 0 else 100

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
        'Yield': f'{yield_all:.3f}%({total_all})',
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

        yield_pct = (site_pass_count / site_total * 100) if site_total > 0 else 0.0

        # 格式化Site名称：加Site前缀
        try:
            site_num = float(site)
            if site_num == int(site_num):
                site_display = f'Site{int(site_num)}'
            else:
                site_display = str(site)
        except:
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


def compute_wafer_fail_data(df: pd.DataFrame, metadata: Optional[Dict] = None,
                            selected_param: Optional[str] = None) -> Tuple[pd.Series, Dict]:
    fail_mask = pd.Series([False] * len(df), index=df.index)
    if selected_param and selected_param in df.columns and metadata:
        if selected_param in metadata.get('mins', {}) and selected_param in metadata.get('maxs', {}):
            data_series = pd.to_numeric(get_1d_from(df, selected_param), errors='coerce')
            lower_limit = parse_limit_string(str(metadata['mins'][selected_param]), data_series, 0.0, 0.0)
            upper_limit = parse_limit_string(str(metadata['maxs'][selected_param]), data_series, 0.0, 0.0)
            if lower_limit != 0.0 or upper_limit != 0.0:
                fail_mask = (data_series < lower_limit) | (data_series > upper_limit)
    else:
        if metadata and 'mins' in metadata and 'maxs' in metadata:
            for col in df.columns:
                if df[col].dtype in ['int64', 'float64']:
                    if col in metadata['mins'] and col in metadata['maxs']:
                        data_series = pd.to_numeric(get_1d_from(df, col), errors='coerce')
                        lower_limit = parse_limit_string(str(metadata['mins'][col]), data_series, 0.0, 0.0)
                        upper_limit = parse_limit_string(str(metadata['maxs'][col]), data_series, 0.0, 0.0)
                        if lower_limit != 0.0 or upper_limit != 0.0:
                            col_fail = (data_series < lower_limit) | (data_series > upper_limit)
                            fail_mask = fail_mask | col_fail

    total = len(df)
    pass_count = int((~fail_mask).sum())
    fail_count = int(fail_mask.sum())
    yield_pct = (pass_count / total * 100) if total > 0 else 0.0

    stats = {'total': total, 'pass_count': pass_count, 'fail_count': fail_count, 'yield_pct': yield_pct}
    return fail_mask, stats
