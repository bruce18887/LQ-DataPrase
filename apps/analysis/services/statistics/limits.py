"""
Specification limit parsing and fail-data detection.

Functions for identifying columns with valid limits, parsing limit strings,
detecting fail rows, and computing per-bin / per-test-item fail statistics.
"""
from typing import Optional, Dict, List, Tuple
import pandas as pd

from .helpers import (
    NON_NUMERIC_KEYWORDS,
    get_bin_column_name,
    ensure_numeric,
    get_1d_from,
)


def get_columns_with_limits(df: pd.DataFrame, metadata: Dict) -> List[str]:
    cols_with_limits = []
    for col in df.columns:
        if col not in metadata.get('mins', {}) or col not in metadata.get('maxs', {}):
            continue
        min_str = str(metadata['mins'][col]).strip()
        max_str = str(metadata['maxs'][col]).strip()
        if not min_str or not max_str:
            continue
        if min_str.lower() in NON_NUMERIC_KEYWORDS or max_str.lower() in NON_NUMERIC_KEYWORDS:
            continue
        try:
            float(min_str)
            float(max_str)
            cols_with_limits.append(col)
        except (ValueError, TypeError):
            continue
    return cols_with_limits


def parse_limit_string(limit_str: str, data_series: pd.Series, default_min: float = 0.0, default_max: float = 0.0) -> float:
    limit_str_clean = limit_str.strip()
    if limit_str_clean.lower() in NON_NUMERIC_KEYWORDS or not limit_str_clean:
        if limit_str_clean.lower() in ['min', 'lower limit']:
            return float(data_series.min()) if len(data_series) > 0 else default_min
        elif limit_str_clean.lower() in ['max', 'upper limit']:
            return float(data_series.max()) if len(data_series) > 0 else default_max
        else:
            return default_min
    try:
        return float(limit_str_clean)
    except (ValueError, TypeError):
        return default_min


def detect_fail_data(df: pd.DataFrame, metadata: Dict, ignore_no_limit: bool = True,
                     columns: Optional[List[str]] = None) -> Tuple[List[int], List[str], Dict[int, List[str]]]:
    fail_indices = []
    fail_columns = []
    fail_cells = {}

    format_type = metadata.get('format', 'CTA8290D')
    target_bin_col = get_bin_column_name(format_type)

    fail_row_mask = pd.Series([False] * len(df), index=df.index)
    if target_bin_col in df.columns:
        fail_row_mask = ensure_numeric(df, target_bin_col) != 1

    # ``columns`` narrows the over-limit scan (used by the analysis compute
    # path, which only needs the requested test items) — the bin column
    # bookkeeping below always runs.
    cols_with_limits = columns if columns is not None else get_columns_with_limits(df, metadata)

    for col in cols_with_limits:
        min_val = float(str(metadata['mins'][col]).strip())
        max_val = float(str(metadata['maxs'][col]).strip())
        col_data = ensure_numeric(df, col)
        fail_mask = fail_row_mask & ((col_data < min_val) | (col_data > max_val))
        fail_rows = df.index[fail_mask].tolist()
        for idx in fail_rows:
            fail_indices.append(idx)
            fail_columns.append(col)
            if idx not in fail_cells:
                fail_cells[idx] = []
            fail_cells[idx].append(col)

    if target_bin_col in df.columns:
        fail_bin_indices = df.index[fail_row_mask].tolist()
        # 用集合做去重：每行都重建 set(fail_indices) 是 O(n²)，
        # 10 万行全 fail 时把整次分析拖到数分钟（回归：tiny-fail-bar）
        seen_fail_indices = set(fail_indices)
        for idx in fail_bin_indices:
            if idx not in fail_cells:
                fail_cells[idx] = []
            if target_bin_col not in fail_cells[idx]:
                fail_cells[idx].append(target_bin_col)
            if idx not in seen_fail_indices:
                seen_fail_indices.add(idx)
                fail_indices.append(idx)

    return fail_indices, fail_columns, fail_cells


def calculate_fail_bin_statistics(df: pd.DataFrame, metadata: Dict) -> Dict:
    format_type = metadata.get('format', 'CTA8290D')
    target_bin_col = get_bin_column_name(format_type)

    if target_bin_col not in df.columns:
        return {}

    bin_counts = get_1d_from(df, target_bin_col).value_counts().sort_index()
    total_count = len(df)

    result = {}
    for bin_value, count in bin_counts.items():
        percentage = (count / total_count * 100) if total_count > 0 else 0.0
        # 6 位小数：1/50000 = 0.002% 不因 round(…, 2) 归零（回归：tiny-fail-bar）
        result[bin_value] = {'count': int(count), 'percentage': round(percentage, 6)}

    return result


def is_pass_bin(bin_value) -> bool:
    """Check if a bin value represents 'pass' (Bin 1).

    Handles all known variants: int 1, float 1.0, str "1", "1.0",
    "Bin1", "Bin 1", "BIN1", etc.  Unified to replace 3 divergent
    inline checks across dashboard/batch_report/export.
    """
    s = str(bin_value).strip()
    # Numeric path: "1", "1.0", "1.00" etc.
    try:
        return int(float(s)) == 1
    except (ValueError, TypeError):
        pass
    # Text path: "Bin1", "Bin 1", "BIN1" etc.
    return s.lower().replace(" ", "") in ("bin1",)


def compute_pass_yield(bin_stats: dict, total_rows: int) -> dict:
    """Compute pass/fail counts and yield percentage from bin statistics.

    Parameters
    ----------
    bin_stats : dict
        Output of ``calculate_fail_bin_statistics`` —
        ``{bin_value: {'count': int, 'percentage': float}}``.
    total_rows : int
        Total number of rows in the dataframe.

    Returns
    -------
    dict with keys: ``pass_count``, ``fail_count``, ``yield_pct``.
    """
    pass_count = 0
    for bin_value, info in bin_stats.items():
        if is_pass_bin(bin_value):
            pass_count += info.get('count', 0)
    fail_count = total_rows - pass_count
    # 6 位小数：49999/50000 = 99.998 不显示成误导性的 100.0（0.002% fail 被吞）
    yield_pct = round((pass_count / total_rows * 100), 6) if total_rows > 0 else 0.0
    return {'pass_count': pass_count, 'fail_count': fail_count, 'yield_pct': yield_pct}


def build_fail_mask(fail_cells: Dict[int, List[str]]) -> Dict[str, List[str]]:
    """Convert fail_cells (int keys) to string-keyed mask for JSON serialization.

    Parameters
    ----------
    fail_cells : dict
        Output of ``detect_fail_data`` — ``{row_idx: [col_name, ...]}``.

    Returns
    -------
    dict with string keys: ``{"0": ["col_a", "col_b"], ...}``.
    """
    return {str(idx): cols for idx, cols in fail_cells.items()}


def build_col_meta(df: pd.DataFrame, metadata: Dict) -> Dict[str, Dict[str, str]]:
    """Build per-column metadata (unit, min, max) for frontend display.

    Parameters
    ----------
    df : pd.DataFrame
    metadata : dict
        Must contain ``units``, ``mins``, ``maxs`` keys.

    Returns
    -------
    dict: ``{col_name: {'unit': str, 'min': str, 'max': str}}``.
    """
    units = metadata.get('units', {})
    mins = metadata.get('mins', {})
    maxs = metadata.get('maxs', {})
    return {
        col: {
            'unit': units.get(col, '') if isinstance(units, dict) else '',
            'min': mins.get(col, '') if isinstance(mins, dict) else '',
            'max': maxs.get(col, '') if isinstance(maxs, dict) else '',
        }
        for col in df.columns
    }


def calculate_fail_test_item_statistics(df: pd.DataFrame, metadata: Dict, ignore_no_limit: bool = True,
                                        columns: Optional[List[str]] = None) -> Dict:
    fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata, ignore_no_limit, columns)

    if not fail_cells:
        return {}

    format_type = metadata.get('format', 'CTA8290D')
    target_bin_col = get_bin_column_name(format_type)

    test_item_fail_count = {}
    total_fail_count = 0

    for row_idx, failed_cols in fail_cells.items():
        for col in failed_cols:
            if col == target_bin_col:
                continue
            if col not in test_item_fail_count:
                test_item_fail_count[col] = 0
            test_item_fail_count[col] += 1
            total_fail_count += 1

    result = {}
    for test_item, fail_count in test_item_fail_count.items():
        percentage = (fail_count / total_fail_count * 100) if total_fail_count > 0 else 0.0
        # 6 位小数：占 fail 总数极小份额的测试项不归零（回归：tiny-fail-bar）
        result[test_item] = {'fail_count': int(fail_count), 'percentage': round(percentage, 6)}

    return dict(sorted(result.items(), key=lambda x: x[1]['fail_count'], reverse=True))
