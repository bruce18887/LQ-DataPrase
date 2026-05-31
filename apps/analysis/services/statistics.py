"""
Statistical analysis service for ATE test data.
Transplanted from Streamlit project's src/analysis/analysis.py.
All Streamlit dependencies (st.cache_data, st.error, etc.) have been removed.
"""
import math
import logging
from typing import Optional, Dict, List, Tuple, Any
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

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


def compute_cpk(mean_val: float, std_val: float, cpk_lower: Optional[float], cpk_upper: Optional[float],
                cpk_a: float = 1.67, cpk_b: float = 1.33, cpk_c: float = 1.0) -> Dict[str, Any]:
    """
    Compute Cp, Cpk, Pp, Ppk with quality levels.

    Args:
        mean_val: Mean of the data
        std_val: Standard deviation (short-term, within-subgroup)
        cpk_lower: Lower specification limit (LSL)
        cpk_upper: Upper specification limit (USL)
        cpk_a: Threshold for A-level quality (default 1.67)
        cpk_b: Threshold for B-level quality (default 1.33)
        cpk_c: Threshold for C-level quality (default 1.0)

    Returns:
        Dictionary with cp, cpk, pp, ppk values and their quality levels/colors
    """
    def get_quality_level(value: float) -> Tuple[str, str]:
        """Get quality level and color for a capability index."""
        if value >= cpk_a:
            return "A级 (优秀)", "green"
        elif value >= cpk_b:
            return "B级 (良好)", "orange"
        elif value >= cpk_c:
            return "C级 (一般)", "darkorange"
        else:
            return "D级 (不足)", "red"

    if std_val <= 0 or cpk_lower is None or cpk_upper is None:
        return {
            'cp': 0.0,
            'cpk': 0.0,
            'pp': 0.0,
            'ppk': 0.0,
            'cp_level': "N/A",
            'cpk_level': "N/A",
            'pp_level': "N/A",
            'ppk_level': "N/A",
            'cp_color': "gray",
            'cpk_color': "gray",
            'pp_color': "gray",
            'ppk_color': "gray"
        }

    # Cp: Process Capability (potential capability, ignores centering)
    cp = (cpk_upper - cpk_lower) / (6 * std_val)

    # Cpk: Process Capability Index (actual capability, considers centering)
    upper_cap = (cpk_upper - mean_val) / (3 * std_val)
    lower_cap = (mean_val - cpk_lower) / (3 * std_val)
    cpk = min(upper_cap, lower_cap)

    # Pp: Process Performance (same as Cp, but uses overall std in practice)
    # For single dataset without subgroups, Pp ≈ Cp
    pp = cp  # In this implementation, we use the same std for both

    # Ppk: Process Performance Index (same as Cpk, but uses overall std)
    ppk = cpk  # In this implementation, we use the same std for both

    cp_level, cp_color = get_quality_level(cp)
    cpk_level, cpk_color = get_quality_level(cpk)
    pp_level, pp_color = get_quality_level(pp)
    ppk_level, ppk_color = get_quality_level(ppk)

    return {
        'cp': cp,
        'cpk': cpk,
        'pp': pp,
        'ppk': ppk,
        'cp_level': cp_level,
        'cpk_level': cpk_level,
        'pp_level': pp_level,
        'ppk_level': ppk_level,
        'cp_color': cp_color,
        'cpk_color': cpk_color,
        'pp_color': pp_color,
        'ppk_color': ppk_color
    }


def compute_correlation_matrix(df: pd.DataFrame, params: List[str], method: str = 'pearson') -> Dict[str, Any]:
    """
    Compute pairwise correlation matrix for selected parameters.

    Args:
        df: DataFrame containing the data
        params: List of parameter names to include in correlation matrix
        method: Correlation method ('pearson' or 'spearman')

    Returns:
        Dictionary with params list, correlation matrix, and sample size
    """
    if not params or len(params) < 2:
        return {
            'params': [],
            'matrix': [],
            'sample_size': 0
        }

    # Filter to only include specified params that exist in df
    valid_params = [p for p in params if p in df.columns]
    if len(valid_params) < 2:
        return {
            'params': valid_params,
            'matrix': [[1.0]] if len(valid_params) == 1 else [],
            'sample_size': len(df)
        }

    # Select only numeric columns and drop NaN
    df_subset = df[valid_params].copy()

    # Convert to numeric, coercing errors to NaN
    for col in df_subset.columns:
        df_subset[col] = pd.to_numeric(df_subset[col], errors='coerce')

    # Drop rows with any NaN values
    df_clean = df_subset.dropna()

    if len(df_clean) == 0:
        # Return identity matrix if no valid data
        n = len(valid_params)
        identity = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        return {
            'params': valid_params,
            'matrix': identity,
            'sample_size': 0
        }

    # Compute correlation matrix
    corr_df = df_clean.corr(method=method)

    # Convert to list of lists, handling NaN values
    matrix = []
    for i, row_param in enumerate(valid_params):
        row = []
        for j, col_param in enumerate(valid_params):
            val = corr_df.loc[row_param, col_param]
            if math.isnan(val) or math.isinf(val):
                val = 1.0 if i == j else 0.0
            row.append(round(float(val), 4))
        matrix.append(row)

    return {
        'params': valid_params,
        'matrix': matrix,
        'sample_size': len(df_clean)
    }


def compute_bin_trend(dfs: List[pd.DataFrame], metadatas: List[Dict]) -> Dict[str, Any]:
    """
    Compute bin distribution trend across multiple files.

    Args:
        dfs: List of DataFrames (one per file)
        metadatas: List of metadata dicts (one per file)

    Returns:
        Dictionary with bins list, trend data, and yield trend
    """
    if not dfs or len(dfs) == 0:
        return {
            'bins': [],
            'trend_data': [],
            'yield_trend': []
        }

    trend_data = []
    yield_trend = []
    all_bins = set()

    for i, (df, metadata) in enumerate(zip(dfs, metadatas)):
        if len(df) == 0:
            continue

        # Calculate bin statistics for this file
        bin_stats = calculate_fail_bin_statistics(df, metadata)

        # Extract bin percentages
        bin_percentages = {}
        total_count = len(df)
        pass_count = 0

        for bin_value, stats in bin_stats.items():
            bin_percentages[str(bin_value)] = stats['percentage']
            all_bins.add(str(bin_value))

            # Bin 1 is typically pass
            if str(bin_value) == '1' or str(bin_value).upper() == 'BIN1':
                pass_count = stats['count']

        # Calculate yield
        yield_pct = (pass_count / total_count * 100) if total_count > 0 else 0.0

        trend_data.append({
            'file_index': i,
            'bin_percentages': bin_percentages,
            'total_count': total_count,
            'pass_count': pass_count,
            'yield': round(yield_pct, 2)
        })

        yield_trend.append(round(yield_pct, 2))

    # Sort bins for consistent ordering
    sorted_bins = sorted(list(all_bins), key=lambda x: (x != '1', x))

    return {
        'bins': sorted_bins,
        'trend_data': trend_data,
        'yield_trend': yield_trend
    }


def compute_boxplot_stats(data: pd.Series) -> Dict[str, Any]:
    """
    Compute five-number summary + outliers using IQR method.

    Args:
        data: Series of numeric values

    Returns:
        Dictionary with min, q1, median, q3, max, and outliers list
    """
    if len(data) == 0:
        return {
            'min': 0.0,
            'q1': 0.0,
            'median': 0.0,
            'q3': 0.0,
            'max': 0.0,
            'outliers': []
        }

    # Remove NaN and infinite values
    clean_data = data.dropna()
    clean_data = clean_data[clean_data.apply(lambda x: not math.isinf(x))]

    if len(clean_data) == 0:
        return {
            'min': 0.0,
            'q1': 0.0,
            'median': 0.0,
            'q3': 0.0,
            'max': 0.0,
            'outliers': []
        }

    # Compute quartiles
    q1 = float(np.percentile(clean_data, 25))
    median = float(np.percentile(clean_data, 50))
    q3 = float(np.percentile(clean_data, 75))

    # IQR method for outliers
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr

    # Find outliers
    outliers = clean_data[(clean_data < lower_fence) | (clean_data > upper_fence)]
    outlier_list = [round(float(x), 6) for x in outliers.tolist()]

    # Min and max excluding outliers (whiskers)
    non_outliers = clean_data[(clean_data >= lower_fence) & (clean_data <= upper_fence)]
    if len(non_outliers) > 0:
        whisker_min = float(non_outliers.min())
        whisker_max = float(non_outliers.max())
    else:
        whisker_min = float(clean_data.min())
        whisker_max = float(clean_data.max())

    return {
        'min': round(whisker_min, 6),
        'q1': round(q1, 6),
        'median': round(median, 6),
        'q3': round(q3, 6),
        'max': round(whisker_max, 6),
        'outliers': outlier_list,
        'count': len(clean_data)
    }


def compute_param_trend(dfs: List[pd.DataFrame], param: str, metadatas: List[Dict]) -> Dict[str, Any]:
    """
    Compute parameter statistics trend across multiple files.

    Args:
        dfs: List of DataFrames (one per file)
        param: Parameter name to analyze
        metadatas: List of metadata dicts (one per file)

    Returns:
        Dictionary with trend data and limits
    """
    if not dfs or len(dfs) == 0:
        return {
            'param': param,
            'trend_data': [],
            'limits': {'lsl': None, 'usl': None}
        }

    trend_data = []
    lsl = None
    usl = None

    for i, (df, metadata) in enumerate(zip(dfs, metadatas)):
        if param not in df.columns:
            continue

        data_series = get_1d_from(df, param).dropna()
        data_series = data_series[data_series.apply(lambda x: abs(x) < float('inf'))]

        if len(data_series) == 0:
            continue

        # Compute statistics
        mean_val = float(data_series.mean())
        std_val = float(data_series.std(ddof=0))
        min_val = float(data_series.min())
        max_val = float(data_series.max())

        # Handle NaN/Inf
        if math.isnan(mean_val) or math.isinf(mean_val):
            mean_val = 0.0
        if math.isnan(std_val) or math.isinf(std_val):
            std_val = 0.0
        if math.isnan(min_val) or math.isinf(min_val):
            min_val = 0.0
        if math.isnan(max_val) or math.isinf(max_val):
            max_val = 0.0

        # Get limits from metadata (use first file's limits)
        if lsl is None and usl is None:
            from apps.analysis.services.statistics import parse_limit_string
            lsl = parse_limit_string(str(metadata.get('mins', {}).get(param, '')), data_series, 0.0, 0.0)
            usl = parse_limit_string(str(metadata.get('maxs', {}).get(param, '')), data_series, 0.0, 0.0)

        # Compute CPK if limits available
        cpk_val = 0.0
        if lsl is not None and usl is not None and std_val > 0:
            upper_cap = (usl - mean_val) / (3 * std_val)
            lower_cap = (mean_val - lsl) / (3 * std_val)
            cpk_val = min(upper_cap, lower_cap)

        trend_data.append({
            'file_index': i,
            'mean': round(mean_val, 6),
            'std': round(std_val, 6),
            'min': round(min_val, 6),
            'max': round(max_val, 6),
            'cpk': round(cpk_val, 4),
            'count': len(data_series)
        })

    return {
        'param': param,
        'trend_data': trend_data,
        'limits': {
            'lsl': round(lsl, 6) if lsl is not None else None,
            'usl': round(usl, 6) if usl is not None else None
        }
    }


def compute_correlation_matrix(df: pd.DataFrame, params: List[str], method: str = 'pearson') -> Dict[str, Any]:
    """
    Compute pairwise correlation matrix for selected parameters.

    Args:
        df: DataFrame containing the data
        params: List of parameter names to compute correlations for
        method: Correlation method ('pearson', 'spearman', or 'kendall')

    Returns:
        Dictionary with correlation matrix and metadata
    """
    if not params or len(params) < 2:
        return {
            'params': [],
            'matrix': [],
            'sample_size': 0,
            'method': method
        }

    # Filter to only include specified params that exist in df
    valid_params = [p for p in params if p in df.columns]
    if len(valid_params) < 2:
        return {
            'params': valid_params,
            'matrix': [],
            'sample_size': 0,
            'method': method
        }

    # Select only numeric columns and drop NaN
    df_subset = df[valid_params].copy()

    # Convert to numeric, coercing errors to NaN
    for col in df_subset.columns:
        df_subset[col] = pd.to_numeric(df_subset[col], errors='coerce')

    # Drop rows with any NaN values
    df_clean = df_subset.dropna()

    if len(df_clean) < 2:
        return {
            'params': valid_params,
            'matrix': [[1.0] * len(valid_params) for _ in range(len(valid_params))],
            'sample_size': len(df_clean),
            'method': method
        }

    # Compute correlation matrix
    corr_matrix = df_clean.corr(method=method)

    # Convert to list of lists for JSON serialization
    matrix_list = corr_matrix.values.tolist()

    # Round values to 4 decimal places
    matrix_list = [[round(val, 4) if not math.isnan(val) else 0.0 for val in row] for row in matrix_list]

    return {
        'params': valid_params,
        'matrix': matrix_list,
        'sample_size': len(df_clean),
        'method': method
    }


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


def compute_boxplot_stats(data: pd.Series) -> Dict[str, Any]:
    """
    Compute five-number summary + outliers for box plot.

    Args:
        data: Pandas Series of numeric data

    Returns:
        Dictionary with min, q1, median, q3, max, and outliers
    """
    if len(data) == 0:
        return {
            'min': 0.0,
            'q1': 0.0,
            'median': 0.0,
            'q3': 0.0,
            'max': 0.0,
            'outliers': [],
            'count': 0
        }

    # Remove NaN and infinite values
    clean_data = data.dropna()
    clean_data = clean_data[clean_data.apply(lambda x: abs(x) < float('inf'))]

    if len(clean_data) == 0:
        return {
            'min': 0.0,
            'q1': 0.0,
            'median': 0.0,
            'q3': 0.0,
            'max': 0.0,
            'outliers': [],
            'count': 0
        }

    # Compute quartiles
    q1 = float(clean_data.quantile(0.25))
    median = float(clean_data.quantile(0.50))
    q3 = float(clean_data.quantile(0.75))
    iqr = q3 - q1

    # Compute whiskers (1.5 * IQR rule)
    lower_whisker = q1 - 1.5 * iqr
    upper_whisker = q3 + 1.5 * iqr

    # Find outliers
    outliers = clean_data[(clean_data < lower_whisker) | (clean_data > upper_whisker)]
    outliers_list = [round(float(x), 6) for x in outliers.tolist()]

    # Min and max within whiskers (non-outlier range)
    non_outliers = clean_data[(clean_data >= lower_whisker) & (clean_data <= upper_whisker)]
    if len(non_outliers) > 0:
        min_val = float(non_outliers.min())
        max_val = float(non_outliers.max())
    else:
        min_val = float(clean_data.min())
        max_val = float(clean_data.max())

    return {
        'min': round(min_val, 6),
        'q1': round(q1, 6),
        'median': round(median, 6),
        'q3': round(q3, 6),
        'max': round(max_val, 6),
        'outliers': outliers_list,
        'count': len(clean_data)
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


def compute_range_statistics(data_series: pd.Series, metadata: Dict, selected_param: str) -> Dict:
    mean_val = float(data_series.mean()) if len(data_series) > 0 else 0.0
    std_val = float(data_series.std(ddof=0)) if len(data_series) > 1 else 0.0
    
    if math.isnan(mean_val) or math.isinf(mean_val):
        mean_val = 0.0
    if math.isnan(std_val) or math.isinf(std_val):
        std_val = 0.0
    
    unit = metadata.get('units', {}).get(selected_param, '')
    
    rdl_min = parse_limit_string(str(metadata.get('mins', {}).get(selected_param, '')), data_series, 0.0, 0.0)
    rdl_max = parse_limit_string(str(metadata.get('maxs', {}).get(selected_param, '')), data_series, 0.0, 0.0)
    rdl_gap = safe_gap(rdl_min, rdl_max)
    
    dr_min = float(data_series.min()) if len(data_series) > 0 else 0.0
    dr_max = float(data_series.max()) if len(data_series) > 0 else 0.0
    dr_gap = safe_gap(dr_min, dr_max)
    
    s3_min = mean_val - 3 * std_val
    s3_max = mean_val + 3 * std_val
    s3_gap = safe_gap(s3_min, s3_max)
    
    s4_min = mean_val - 4 * std_val
    s4_max = mean_val + 4 * std_val
    s4_gap = safe_gap(s4_min, s4_max)
    
    s6_min = mean_val - 6 * std_val
    s6_max = mean_val + 6 * std_val
    s6_gap = safe_gap(s6_min, s6_max)
    
    cl_min = float(data_series.min()) if len(data_series) > 0 else 0.0
    cl_max = float(data_series.max()) if len(data_series) > 0 else 0.0
    cl_gap = safe_gap(cl_min, cl_max)
    
    return {
        'mean': mean_val, 'std': std_val, 'unit': unit,
        'rdl': (rdl_min, rdl_max, rdl_gap),
        'dr': (dr_min, dr_max, dr_gap),
        'cl': (cl_min, cl_max, cl_gap),
        's3': (s3_min, s3_max, s3_gap),
        's4': (s4_min, s4_max, s4_gap),
        's6': (s6_min, s6_max, s6_gap),
    }


def safe_gap(min_val: float, max_val: float) -> float:
    gap = (max_val - min_val) / 20
    return max(gap, 1e-9)


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

        # 格式化Site名称：如果是整数则显示为整数，否则保留原样
        try:
            site_num = float(site)
            if site_num == int(site_num):
                site_display = str(int(site_num))
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

    result = {'yield_data': yield_data_list, 'yield_values': yield_values}

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
