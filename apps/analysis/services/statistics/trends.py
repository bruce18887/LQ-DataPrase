"""Cross-file trend analysis functions."""

import logging
from typing import Dict, List, Any

import numpy as np

from .limits import (
    parse_limit_string,
    calculate_fail_bin_statistics,
    compute_pass_yield,
)
from .computations import compute_cpk
from .helpers import NON_NUMERIC_KEYWORDS, get_1d_from, filter_finite

logger = logging.getLogger(__name__)

# parse_limit_string 对 'min'/'max' 等关键字按数据边界解析（真实限值），
# 其余 NON_NUMERIC_KEYWORDS 与空串一律回退 default（0.0）——区分两者
_REAL_LIMIT_KEYWORDS = {'min', 'lower limit', 'max', 'upper limit'}


def _has_real_limit(raw: str) -> bool:
    """限值字符串是否为真实规格限（空串/na/- 等占位不是）。"""
    cleaned = raw.strip().lower()
    if cleaned in _REAL_LIMIT_KEYWORDS:
        return True
    if not cleaned or cleaned in NON_NUMERIC_KEYWORDS:
        return False
    try:
        float(cleaned)
        return True
    except (ValueError, TypeError):
        return False


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
    response_lsl = None
    response_usl = None

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
        data_series = filter_finite(get_1d_from(df, param))

        if len(data_series) == 0:
            continue

        # Compute statistics
        mean_val = float(data_series.mean())
        std_val = float(data_series.std(ddof=0)) if len(data_series) > 1 else 0.0
        min_val = float(data_series.min())
        max_val = float(data_series.max())

        # 每文件独立解析规格限并计算 CPK —— 不同批次/程序版本的规格可能不同，
        # 沿用第一个文件的限值会让后续文件的 CPK 数学上错误
        mins_dict = metadata.get('mins', {})
        maxs_dict = metadata.get('maxs', {})
        min_raw = str(mins_dict.get(param, ''))
        max_raw = str(maxs_dict.get(param, ''))
        file_lsl = parse_limit_string(min_raw, data_series, 0.0, 0.0)
        file_usl = parse_limit_string(max_raw, data_series, 0.0, 0.0)
        # parse_limit_string 对缺失/占位限值回退 0.0，与真实 [0,0] 规格无法
        # 区分——用原始字符串判断是否真有限值，缺失文件不算 CPK（避免负值）
        has_lsl = _has_real_limit(min_raw)
        has_usl = _has_real_limit(max_raw)

        # Compute CPK if limits available
        cpk_val = 0.0
        if has_lsl and has_usl and std_val > 0:
            cpk_result = compute_cpk(mean_val, std_val, file_lsl, file_usl)
            cpk_val = cpk_result['cpk']

        # 响应级 limits 字段取首个完整（双限齐全）对，向后兼容
        if response_lsl is None and response_usl is None and has_lsl and has_usl:
            response_lsl, response_usl = file_lsl, file_usl

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
            'lsl': round(file_lsl, 6) if has_lsl else None,
            'usl': round(file_usl, 6) if has_usl else None,
            'count': len(data_series)
        })

    return {
        'param': param,
        'files': files_info,
        'trend_data': trend_data,
        'limits': {
            'lsl': round(response_lsl, 6) if response_lsl is not None else None,
            'usl': round(response_usl, 6) if response_usl is not None else None
        }
    }
