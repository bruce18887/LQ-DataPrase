"""Cross-file trend analysis functions."""

import logging
from typing import Dict, List, Any

import numpy as np

from .limits import (
    resolve_spec_limits,
    calculate_fail_bin_statistics,
    compute_pass_yield,
    is_pass_bin,
)
from .computations import compute_cpk
from .helpers import get_1d_from, filter_finite

logger = logging.getLogger(__name__)

def _bin_sort_key(bin_value):
    """Bin1 优先，其余按数值序（无法数值化的排最后、按字符串）。

    ``calculate_fail_bin_statistics`` 直接拿 pandas ``value_counts`` 的原始键，
    所以真实 CTA8290D 文件的 ``SW_Bin``（int64）会得到 **int** 键；旧写法
    ``key=lambda x: (x != 'Bin1' and x != '1', x)`` 对 int 键永远为 True
    （排不出 Bin1 优先），而且跨文件 int/str 混用时 ``sorted`` 直接 TypeError。
    """
    priority = 0 if is_pass_bin(bin_value) else 1
    try:
        return (priority, 0, float(bin_value), '')
    except (TypeError, ValueError):
        return (priority, 1, 0.0, str(bin_value))


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
            # is_pass_bin 而非 ``== 'Bin1' or == '1'``：真实文件的 SW_Bin 是
            # int64，bin_stats 的键是 Python int，``1 == '1'`` 恒为 False，
            # pass_count 永远停在 0 → yield_trend 整条归零，而同 app 的
            # compute_yield_trend（走 compute_pass_yield）算出正确良率，
            # 两个良率端点互相矛盾。用 += 与 compute_pass_yield 保持一致。
            if is_pass_bin(bin_name):
                pass_count += count

        # Calculate percentages
        for bin_name, bin_info in bin_stats.items():
            count = bin_info.get('count', 0)
            # 6 位小数保精度：小占比 bin 不归零（回归：tiny-fail-bar）
            percentage = round((count / total_count * 100), 6) if total_count > 0 else 0.0
            bin_percentages[bin_name] = percentage
            all_bins.add(bin_name)

        # Calculate yield
        yield_val = round((pass_count / total_count * 100), 6) if total_count > 0 else 0.0

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

    # Sort bins (Bin1 first, then numeric order)
    bins_sorted = sorted(list(all_bins), key=_bin_sort_key)

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
    # 口径（用户 2026-09-03 确认）：维持 X̄-chart 近似（mean ± 3·std）而不改
    # p-chart；但上下界必须对称钳位——良率是百分比，旧代码只钳 lcl>=0
    # 却不钳 ucl<=100，会画出 >100% 的控制限。精度对齐项目 6 位口径
    # （同文件良率与 limits.compute_pass_yield 均为 round(..., 6)）。
    n = len(yield_values)
    if n > 1:
        mean_yield = float(np.mean(yield_values))
        std_yield = float(np.std(yield_values, ddof=0))
        ucl = round(min(mean_yield + 3 * std_yield, 100.0), 6)
        cl = round(mean_yield, 6)
        lcl = round(max(mean_yield - 3 * std_yield, 0.0), 6)  # yield cannot be negative
    elif n == 1:
        mean_yield = yield_values[0]
        ucl = cl = lcl = round(mean_yield, 6)
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
        # 沿用第一个文件的限值会让后续文件的 CPK 数学上错误。
        # resolve_spec_limits 对缺失/占位/字面 'Min'/'Max' 一律返回 None，
        # 所以不再需要旧的 _has_real_limit 局部绕过（那是为了区分
        # 「真没有限值」与「幻影 0.0」而写的补丁，根因修完就可以删）。
        file_lsl, file_usl = resolve_spec_limits(metadata, param)

        # Compute CPK if limits available
        cpk_val = 0.0
        if file_lsl is not None and file_usl is not None and std_val > 0:
            cpk_result = compute_cpk(mean_val, std_val, file_lsl, file_usl)
            cpk_val = cpk_result['cpk']

        # 响应级 limits 字段取首个完整（双限齐全）对，向后兼容
        if (response_lsl is None and response_usl is None
                and file_lsl is not None and file_usl is not None):
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
            'lsl': round(file_lsl, 6) if file_lsl is not None else None,
            'usl': round(file_usl, 6) if file_usl is not None else None,
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
