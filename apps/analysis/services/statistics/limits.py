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


def detect_fail_data(df: pd.DataFrame, metadata: Dict, ignore_no_limit: bool = True) -> Tuple[List[int], List[str], Dict[int, List[str]]]:
    fail_indices = []
    fail_columns = []
    fail_cells = {}

    format_type = metadata.get('format', 'CTA8290D')
    target_bin_col = get_bin_column_name(format_type)

    fail_row_mask = pd.Series([False] * len(df), index=df.index)
    if target_bin_col in df.columns:
        fail_row_mask = ensure_numeric(df, target_bin_col) != 1

    cols_with_limits = get_columns_with_limits(df, metadata)

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
        for idx in fail_bin_indices:
            if idx not in fail_cells:
                fail_cells[idx] = []
            if target_bin_col not in fail_cells[idx]:
                fail_cells[idx].append(target_bin_col)
            if idx not in set(fail_indices):
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
        result[bin_value] = {'count': int(count), 'percentage': round(percentage, 2)}

    return result


def calculate_fail_test_item_statistics(df: pd.DataFrame, metadata: Dict, ignore_no_limit: bool = True) -> Dict:
    fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata, ignore_no_limit)

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
        result[test_item] = {'fail_count': int(fail_count), 'percentage': round(percentage, 2)}

    return dict(sorted(result.items(), key=lambda x: x[1]['fail_count'], reverse=True))
