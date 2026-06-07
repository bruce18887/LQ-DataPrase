"""
Cross-file and wafer-level analytics.

Bin trends, yield trends, parameter trends, site statistics,
wafer fail maps, zonal yield, and UPH calculations.
"""
import logging
from typing import Optional, Dict, List, Tuple, Any
import pandas as pd
import numpy as np

from .helpers import (
    get_1d_from,
    get_site_column,
    get_coord_columns,
    ensure_numeric,
)
from .limits import (
    parse_limit_string,
    get_columns_with_limits,
    compute_pass_yield,
    calculate_fail_bin_statistics,
)
from .computations import compute_cpk

logger = logging.getLogger(__name__)


def compute_bin_trend(file_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute bin distribution trend across multiple files.

    Args:
        file_data_list: List of dicts with 'df', 'metadata', 'file_id', 'filename', 'timestamp'

    Returns:
        Dictionary with bin trend data
    """
    if not file_data_list:
        return {
            'files': [],
            'bins': [],
            'trend_data': [],
            'yield_trend': []
        }

    files_info = []
    trend_data = []
    yield_trend = []
    all_bins = set()

    for file_data in file_data_list:
        df = file_data['df']
        metadata = file_data.get('metadata', {})
        file_id = file_data.get('file_id')
        filename = file_data.get('filename', 'unknown')
        timestamp = file_data.get('timestamp', '')

        # Get bin statistics for this file
        bin_stats = calculate_fail_bin_statistics(df, metadata)

        # Extract bin percentages
        bin_percentages = {}
        total_count = 0
        pass_count = 0

        for bin_name, bin_info in bin_stats.items():
            count = bin_info.get('count', 0)
            total_count += count
            if bin_name == 'Bin1' or bin_name == '1':
                pass_count = count

        # Calculate percentages
        for bin_name, bin_info in bin_stats.items():
            count = bin_info.get('count', 0)
            percentage = round((count / total_count * 100), 2) if total_count > 0 else 0.0
            bin_percentages[bin_name] = percentage
            all_bins.add(bin_name)

        # Calculate yield
        yield_val = round((pass_count / total_count * 100), 2) if total_count > 0 else 0.0

        files_info.append({
            'file_id': file_id,
            'filename': filename,
            'timestamp': timestamp
        })

        trend_data.append({
            'file_id': file_id,
            'bin_percentages': bin_percentages,
            'total_count': total_count
        })

        yield_trend.append(yield_val)

    # Sort bins (Bin1 first, then others)
    bins_sorted = sorted(list(all_bins), key=lambda x: (x != 'Bin1' and x != '1', x))

    return {
        'files': files_info,
        'bins': bins_sorted,
        'trend_data': trend_data,
        'yield_trend': yield_trend
    }


def compute_yield_trend(file_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute yield trend across multiple files with SPC control limits.

    Args:
        file_data_list: List of dicts with 'df', 'metadata', 'file_id', 'filename', 'timestamp'

    Returns:
        Dictionary with files, trend_data, spc_limits, anomalies
    """
    if not file_data_list:
        return {
            'files': [],
            'trend_data': [],
            'spc_limits': {'ucl': None, 'cl': None, 'lcl': None},
            'anomalies': []
        }

    files_info = []
    trend_data = []
    yield_values = []

    for file_data in file_data_list:
        df = file_data['df']
        metadata = file_data.get('metadata', {})
        file_id = file_data.get('file_id')
        filename = file_data.get('filename', 'unknown')
        timestamp = file_data.get('timestamp', '')

        # Get bin statistics to compute pass/fail counts
        bin_stats = calculate_fail_bin_statistics(df, metadata)
        total_count = sum(info.get('count', 0) for info in bin_stats.values()) or len(df)
        yield_result = compute_pass_yield(bin_stats, total_count)
        pass_count = yield_result['pass_count']
        yield_pct = yield_result['yield_pct']

        files_info.append({
            'file_id': file_id,
            'filename': filename,
            'timestamp': timestamp
        })

        trend_data.append({
            'file_id': file_id,
            'yield': yield_pct,
            'total_count': total_count,
            'pass_count': pass_count,
            'fail_count': total_count - pass_count
        })

        yield_values.append(yield_pct)

    # Calculate SPC control limits
    n = len(yield_values)
    if n > 1:
        mean_yield = float(np.mean(yield_values))
        std_yield = float(np.std(yield_values, ddof=0))
        ucl = round(mean_yield + 3 * std_yield, 2)
        cl = round(mean_yield, 2)
        lcl = round(mean_yield - 3 * std_yield, 2)
        lcl = max(lcl, 0.0)  # yield cannot be negative
    elif n == 1:
        mean_yield = yield_values[0]
        ucl = cl = lcl = round(mean_yield, 2)
    else:
        ucl = cl = lcl = None

    spc_limits = {
        'ucl': ucl,
        'cl': cl,
        'lcl': lcl
    }

    # Identify anomalies (points outside control limits)
    anomalies = []
    if ucl is not None and lcl is not None and n > 1:
        for fd, y in zip(file_data_list, yield_values):
            is_anomaly = y > ucl or y < lcl
            if is_anomaly:
                reason = '超出上控制限' if y > ucl else '低于下控制限'
                anomalies.append({
                    'file_id': fd.get('file_id'),
                    'filename': fd.get('filename', 'unknown'),
                    'timestamp': fd.get('timestamp', ''),
                    'yield': y,
                    'reason': reason
                })

    return {
        'files': files_info,
        'trend_data': trend_data,
        'spc_limits': spc_limits,
        'anomalies': anomalies
    }


def compute_param_trend(file_data_list: List[Dict[str, Any]], param: str) -> Dict[str, Any]:
    """
    Compute parameter statistics trend across multiple files.

    Args:
        file_data_list: List of dicts with 'df', 'metadata', 'file_id', 'filename', 'timestamp'
        param: Parameter name to analyze

    Returns:
        Dictionary with trend data
    """
    if not file_data_list or not param:
        return {
            'param': param,
            'files': [],
            'trend_data': [],
            'limits': {'lsl': None, 'usl': None}
        }

    files_info = []
    trend_data = []
    lsl = None
    usl = None

    for file_data in file_data_list:
        df = file_data['df']
        metadata = file_data.get('metadata', {})
        file_id = file_data.get('file_id')
        filename = file_data.get('filename', 'unknown')
        timestamp = file_data.get('timestamp', '')

        # Check if param exists in this file
        if param not in df.columns:
            continue

        # Get data series
        data_series = get_1d_from(df, param).dropna()
        data_series = data_series[data_series.apply(lambda x: abs(x) < float('inf'))]

        if len(data_series) == 0:
            continue

        # Compute statistics
        mean_val = float(data_series.mean())
        std_val = float(data_series.std(ddof=0)) if len(data_series) > 1 else 0.0
        min_val = float(data_series.min())
        max_val = float(data_series.max())

        # Get limits from metadata (use first file's limits)
        if lsl is None or usl is None:
            mins_dict = metadata.get('mins', {})
            maxs_dict = metadata.get('maxs', {})
            lsl = parse_limit_string(str(mins_dict.get(param, '')), data_series, 0.0, 0.0)
            usl = parse_limit_string(str(maxs_dict.get(param, '')), data_series, 0.0, 0.0)

        # Compute CPK if limits available
        cpk_val = 0.0
        if lsl is not None and usl is not None and std_val > 0:
            cpk_result = compute_cpk(mean_val, std_val, lsl, usl)
            cpk_val = cpk_result['cpk']

        files_info.append({
            'file_id': file_id,
            'filename': filename,
            'timestamp': timestamp
        })

        trend_data.append({
            'file_id': file_id,
            'mean': round(mean_val, 6),
            'std': round(std_val, 6),
            'min': round(min_val, 6),
            'max': round(max_val, 6),
            'cpk': round(cpk_val, 4),
            'count': len(data_series)
        })

    return {
        'param': param,
        'files': files_info,
        'trend_data': trend_data,
        'limits': {
            'lsl': round(lsl, 6) if lsl is not None else None,
            'usl': round(usl, 6) if usl is not None else None
        }
    }


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
    def site_sort_key(s):
        try:
            return (0, float(s), '')
        except (ValueError, TypeError):
            return (1, 0, str(s))

    for site in sorted(totals.index, key=site_sort_key):
        total = int(totals.get(site, 0))
        fail_count = int(fail_counts.get(site, 0))
        exceed_min = int(exceed_mins.get(site, 0))
        exceed_max = int(exceed_maxs.get(site, 0))
        yield_rate = ((total - fail_count) / total * 100) if total > 0 else 100
        site_data_list.append({
            'Site': f'Site{site}',
            'Yield': f'{yield_rate:.2f}%',
            'FailCount': fail_count,
            'ExceedMin': exceed_min,
            'ExceedMax': exceed_max,
        })
    site_data_list.append({
        'Site': 'ALL Site',
        'Yield': f'{yield_all:.2f}%',
        'FailCount': fail_all,
        'ExceedMin': int(exceed_mins.sum()),
        'ExceedMax': int(exceed_maxs.sum()),
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


def compute_zonal_yield(df: pd.DataFrame, metadata: Optional[Dict] = None,
                        param: Optional[str] = None) -> Dict:
    """
    Compute yield breakdown by radial zones on a wafer.

    Divides the wafer into 3 concentric zones (Center, Middle, Edge) based on
    normalized distance from the wafer center, and calculates yield statistics
    for each zone.

    Args:
        df: DataFrame containing wafer test data with X/Y coordinate columns.
        metadata: Metadata dict (used for limit lookups when param is provided,
                  or for auto-detecting fail mask when param is None).
        param: Optional parameter name. If provided, uses the parameter's
               spec limits (from metadata) to determine pass/fail per die.
               If None, uses compute_wafer_fail_data to derive the fail mask
               from all numeric columns with limits.

    Returns:
        Dictionary with:
            zones: List of per-zone dicts {name, total, pass, fail, yield, display_order}
            wafer_radius: Max distance from center in coordinate units
            zone_boundaries: The normalized radius cutoffs [0.33, 0.66]
    """
    x_col, y_col = get_coord_columns(df)
    if x_col is None or y_col is None:
        return {
            'zones': [],
            'wafer_radius': 0,
            'zone_boundaries': [0.33, 0.66],
        }

    x_vals = pd.to_numeric(get_1d_from(df, x_col), errors='coerce')
    y_vals = pd.to_numeric(get_1d_from(df, y_col), errors='coerce')

    cx = float(x_vals.mean())
    cy = float(y_vals.mean())

    distances = np.sqrt((x_vals - cx) ** 2 + (y_vals - cy) ** 2)
    max_dist = float(distances.max())
    if max_dist <= 0:
        max_dist = 1.0  # fallback to avoid division by zero

    norm_distances = distances / max_dist

    # Determine fail pass mask
    if param is not None and metadata is not None:
        # Use the specific parameter's limits for pass/fail determination
        if param in df.columns and param in metadata.get('mins', {}) and param in metadata.get('maxs', {}):
            data_series = pd.to_numeric(get_1d_from(df, param), errors='coerce')
            lower_limit = parse_limit_string(str(metadata['mins'][param]), data_series, 0.0, 0.0)
            upper_limit = parse_limit_string(str(metadata['maxs'][param]), data_series, 0.0, 0.0)
            fail_mask = (data_series < lower_limit) | (data_series > upper_limit)
        else:
            fail_mask = pd.Series([False] * len(df), index=df.index)
    else:
        # Use the generic wafer fail data detection
        fail_mask, _ = compute_wafer_fail_data(df, metadata, selected_param=None)

    # Zone definitions based on normalized radius
    zone_defs = [
        ('center_zone', '中心区', 0.0, 1.0 / 3.0, 0),
        ('middle_zone', '中间区', 1.0 / 3.0, 2.0 / 3.0, 1),
        ('edge_zone', '边缘区', 2.0 / 3.0, float('inf'), 2),
    ]

    zones_result = []
    for zone_key, zone_name, r_low, r_high, display_order in zone_defs:
        if r_high == float('inf'):
            mask = norm_distances > r_low
        else:
            mask = (norm_distances > r_low) & (norm_distances <= r_high)

        zone_total = int(mask.sum())
        if zone_total == 0:
            zones_result.append({
                'name': zone_name,
                'total': 0,
                'pass': 0,
                'fail': 0,
                'yield': 0.0,
                'display_order': display_order,
            })
            continue

        zone_fail = int(fail_mask[mask].sum())
        zone_pass = zone_total - zone_fail
        zone_yield = round((zone_pass / zone_total) * 100, 2) if zone_total > 0 else 0.0

        zones_result.append({
            'name': zone_name,
            'total': zone_total,
            'pass': zone_pass,
            'fail': zone_fail,
            'yield': zone_yield,
            'display_order': display_order,
        })

    return {
        'zones': zones_result,
        'wafer_radius': round(max_dist, 6),
        'zone_boundaries': [round(1.0 / 3.0, 4), round(2.0 / 3.0, 4)],
    }


# Per-unit test-time column candidates, in priority order, across supported formats.
TEST_TIME_COL_CANDIDATES = ['Test_Time', 'Test Time', 'T_TIME', 'TEST_TIME', 'TestTime']


def _detect_test_time_col(df: pd.DataFrame, preferred=None):
    """Return the name of the per-unit test-time column, or None.

    A preferred column (from the request) wins if present. Otherwise the first
    known per-unit candidate is used. We deliberately avoid the many per-test
    ``*_Time`` columns (e.g. ETS88 sub-test timings) and only match whole-unit
    test-time columns.
    """
    if preferred and preferred in df.columns:
        return preferred
    for cand in TEST_TIME_COL_CANDIDATES:
        if cand in df.columns:
            return cand
    return None


def compute_uph(df: pd.DataFrame, metadata: Dict, test_time_col=None,
                manual_test_time_sec=None) -> Dict[str, Any]:
    """Compute UPH (Units Per Hour) using the parallel-site throughput model.

    Throughput assumes ``site_count`` testers run concurrently, so wall-clock
    time ≈ (sum of per-unit test times) / site_count, and::

        UPH = total_tested / total_time_seconds * 3600
            = 3600 * site_count / avg_test_time_seconds

    Test time is read from a per-unit column (auto-detected per format) and
    normalized to seconds (metadata unit ``ms`` is divided by 1000). A manual
    per-unit time (seconds) overrides the column. Per-site UPH reflects a single
    site's throughput (3600 / that site's average test time).

    Returns the shape consumed by the frontend ``UphCard.vue``.
    """
    warnings = []
    empty = {
        'uph': 0.0, 'avg_test_time': 0.0, 'total_tested': 0,
        'total_time_seconds': 0.0, 'source': 'unavailable',
        'by_site': [], 'site_count': 0, 'warnings': warnings,
    }

    # ── Site count (parallel testers) ────────────────────────────────
    site_col = get_site_column(df)
    site_series = None
    site_count = 1
    if site_col:
        site_series = pd.to_numeric(df[site_col], errors='coerce')
        valid_sites = site_series.dropna().astype(int)
        if len(valid_sites) > 0:
            site_count = max(1, int(valid_sites.nunique()))
    else:
        warnings.append('未找到 Site 列，按单站点计算')

    # ── Per-unit average test time (seconds) ─────────────────────────
    source = ''
    per_unit_seconds = None  # pd.Series aligned to df.index, seconds, >0

    if manual_test_time_sec is not None:
        try:
            manual_val = float(manual_test_time_sec)
        except (TypeError, ValueError):
            manual_val = 0.0
        if manual_val > 0:
            per_unit_seconds = pd.Series(manual_val, index=df.index, dtype='float64')
            source = f'manual ({manual_val:g}s)'
        else:
            warnings.append('手动测试时间无效，已忽略')

    if per_unit_seconds is None:
        col = _detect_test_time_col(df, test_time_col)
        if col is None:
            warnings.append('未找到测试时间列，无法计算 UPH')
            empty['warnings'] = warnings
            return empty
        raw = ensure_numeric(df, col)
        unit = str(metadata.get('units', {}).get(col, '')).strip().lower()
        if 'ms' in unit:
            raw = raw / 1000.0
            source = f'{col} (ms→s)'
        else:
            source = col
        per_unit_seconds = raw

    # Keep only rows with a positive, finite test time aligned with a valid site.
    valid_mask = per_unit_seconds.notna() & (per_unit_seconds > 0)
    if site_series is not None:
        valid_mask = valid_mask & site_series.notna()
    per_unit_valid = per_unit_seconds[valid_mask]

    total_tested = int(len(per_unit_valid))
    if total_tested == 0:
        warnings.append('无有效测试时间数据')
        empty['warnings'] = warnings
        empty['site_count'] = site_count
        empty['source'] = source or 'unavailable'
        return empty

    dropped = int(len(df) - total_tested)
    if dropped > 0:
        warnings.append(f'{dropped} 行缺少有效测试时间，已忽略')

    avg_test_time = float(per_unit_valid.mean())
    total_serial_seconds = float(per_unit_valid.sum())
    total_time_seconds = total_serial_seconds / site_count if site_count > 0 else total_serial_seconds
    uph = (total_tested / total_time_seconds * 3600.0) if total_time_seconds > 0 else 0.0

    # ── Per-site breakdown ───────────────────────────────────────────
    by_site = []
    if site_series is not None:
        site_for_valid = site_series[valid_mask].astype(int)
        for site_val in sorted(site_for_valid.unique()):
            site_times = per_unit_valid[site_for_valid == site_val]
            if len(site_times) == 0:
                continue
            site_avg = float(site_times.mean())
            site_uph = (3600.0 / site_avg) if site_avg > 0 else 0.0
            by_site.append({
                'site': str(site_val),
                'tested': int(len(site_times)),
                'uph': round(site_uph, 1),
            })

    return {
        'uph': round(uph, 1),
        'avg_test_time': round(avg_test_time, 3),
        'total_tested': total_tested,
        'total_time_seconds': round(total_time_seconds, 1),
        'source': source,
        'by_site': by_site,
        'site_count': site_count,
        'warnings': warnings,
    }
