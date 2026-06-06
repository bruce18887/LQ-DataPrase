"""
Helper utilities and constants for statistical analysis.

Provides column lookup functions, data accessors, and basic numeric helpers
used across the statistics sub-modules.
"""
from typing import Optional, Dict, List, Tuple
import pandas as pd

NON_NUMERIC_KEYWORDS = ['min', 'max', 'lower limit', 'upper limit', 'n/a', 'na', '-', 'none']

BIN_COLUMN_MAPPING = {
    'CTA8290D': 'SW_Bin',
    'CTA8280F': 'SW_Bin',
    'ETS88': 'Bin',
    'STS8200': 'SOFT_BIN',
}


def get_bin_column_name(format_type: str) -> str:
    return BIN_COLUMN_MAPPING.get(format_type, 'SW_Bin')


def find_column_by_pattern(df: pd.DataFrame, patterns: List[str]) -> Optional[str]:
    for col in df.columns:
        col_lower = col.lower()
        for pattern in patterns:
            if pattern in col_lower:
                return col
    return None


def get_site_column(df: pd.DataFrame) -> Optional[str]:
    return find_column_by_pattern(df, ['site'])


def get_serial_column(df: pd.DataFrame) -> Optional[str]:
    return find_column_by_pattern(df, ['serial'])


def get_coord_columns(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    x_col = None
    y_col = None
    for col in df.columns:
        col_lower = col.lower()
        if 'x' in col_lower and 'coord' in col_lower:
            x_col = col
        elif 'y' in col_lower and 'coord' in col_lower:
            y_col = col
    return x_col, y_col


def get_bin_column(df: pd.DataFrame, metadata: Dict) -> Optional[str]:
    """Return the Bin column name based on metadata format type, if it exists in df."""
    format_type = metadata.get('format', '')
    target_col = get_bin_column_name(format_type)
    if target_col and target_col in df.columns:
        return target_col
    return None


def get_1d(series_or_df):
    if isinstance(series_or_df, pd.DataFrame):
        return series_or_df.iloc[:, 0]
    return series_or_df


def get_1d_from(df: pd.DataFrame, col: str) -> pd.Series:
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s


def ensure_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(get_1d_from(df, col), errors='coerce')


def safe_gap(min_val: float, max_val: float) -> float:
    gap = (max_val - min_val) / 20
    return max(gap, 1e-9)
