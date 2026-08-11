"""
Pure statistical computations.

Cpk/Cp/Ppk, correlation matrix, box-plot statistics, range statistics,
and QQ-plot computation.  No cross-file analytics -- those live in analytics.py.
"""
import math
from typing import Optional, Dict, List, Tuple, Any
import pandas as pd
import numpy as np

from .distributions import norm_probplot, t_cdf
from .downsample import uniform_indices, DOWN_SAMPLE_THRESHOLD
from .helpers import safe_gap, get_1d_from, get_coord_columns
from .limits import parse_limit_string
from .outliers import detect_outliers_iqr


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

    # 单边规格（缺失侧以 -inf/+inf 传入）：Cp 需要双侧规格才可定义 → None；
    # Cpk/Ppk 单侧可算（缺失侧能力为 +inf，min 取有限侧）
    one_sided = not math.isfinite(cpk_lower) or not math.isfinite(cpk_upper)

    if one_sided:
        cp = None
        pp = None
        cp_level = "N/A"
        cp_color = "gray"
        pp_level = "N/A"
        pp_color = "gray"
    else:
        # Cp: Process Capability (potential capability, ignores centering)
        cp = (cpk_upper - cpk_lower) / (6 * std_val)
        pp = cp  # In this implementation, we use the same std for both
        cp_level, cp_color = get_quality_level(cp)
        pp_level, pp_color = get_quality_level(pp)

    # Cpk: Process Capability Index (actual capability, considers centering)
    upper_cap = (cpk_upper - mean_val) / (3 * std_val) if math.isfinite(cpk_upper) else float('inf')
    lower_cap = (mean_val - cpk_lower) / (3 * std_val) if math.isfinite(cpk_lower) else float('inf')
    cpk = min(upper_cap, lower_cap)

    # Ppk: Process Performance Index (same as Cpk, but uses overall std)
    ppk = cpk  # In this implementation, we use the same std for both

    cpk_level, cpk_color = get_quality_level(cpk)
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

    # Compute p-value matrix (vectorized from correlation coefficients)
    n_obs = len(df_clean)
    r_values = corr_matrix.values
    n_params = len(valid_params)
    if n_obs > 2:
        with np.errstate(divide='ignore', invalid='ignore'):
            t_values = r_values * np.sqrt((n_obs - 2) / (1 - r_values ** 2))
        p_values = 2 * (1 - t_cdf(np.abs(t_values), df=n_obs - 2))
        np.fill_diagonal(p_values, 1.0)
        p_values = np.nan_to_num(p_values, nan=1.0, posinf=1.0, neginf=1.0)
    else:
        p_values = np.ones((n_params, n_params))
    p_matrix_list = [[round(val, 6) for val in row] for row in p_values.tolist()]

    return {
        'params': valid_params,
        'matrix': matrix_list,
        'p_values': p_matrix_list,
        'sample_size': len(df_clean),
        'method': method
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

    # Coerce to float up-front so boolean Series (e.g. Dut_Pass / PASSFG) and
    # string-coercible columns don't trip the bool/string pitfalls below:
    #   - pd.to_numeric on a bool Series returns the SAME bool Series (no dtype
    #     change), so .quantile() later tries `bool - bool` and raises
    #     "numpy boolean subtract, the `-` operator, is not supported".
    #   - abs('str') raises "bad operand type for abs(): 'str'".
    # Errors='coerce' turns unparseable strings into NaN; .astype(float) is
    # the explicit step that flips bool to float (0.0/1.0).
    coerced = pd.to_numeric(data, errors='coerce').astype(float)
    clean_data = coerced.dropna()
    clean_data = clean_data[np.isfinite(clean_data)]

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

    # Raw values for jitter overlay (subsample if too large)
    MAX_RAW_POINTS = 2000
    if len(clean_data) > MAX_RAW_POINTS:
        step = len(clean_data) // MAX_RAW_POINTS
        raw_values = clean_data.iloc[::step].round(6).tolist()
    else:
        raw_values = clean_data.round(6).tolist()

    return {
        'min': round(min_val, 6),
        'q1': round(q1, 6),
        'median': round(median, 6),
        'q3': round(q3, 6),
        'max': round(max_val, 6),
        'outliers': outliers_list,
        'count': len(clean_data),
        'raw_values': raw_values
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


def compute_qqplot(data_series: pd.Series, metadata: dict = None, param: str = None) -> Dict[str, Any]:
    """
    Compute QQ plot data for normality testing (norm_probplot — numpy).

    Args:
        data_series: Numeric data series to test for normality.
        metadata: Optional metadata dict containing spec limits for outlier detection.
        param: Optional parameter name to look up spec limits in metadata.

    Returns:
        Dictionary with theoretical quantiles, observed values, R-squared, and normality verdict.
    """
    clean = pd.to_numeric(data_series, errors='coerce').dropna()
    clean = clean[np.isfinite(clean.values)]

    # Detect outliers, respecting spec limits (RDL) if available
    spec_limits = None
    if metadata and param:
        stats = compute_range_statistics(clean, metadata, param)
        spec_limits = (stats['rdl'][0], stats['rdl'][1])

    outlier_info = detect_outliers_iqr(clean, include_values=False, spec_limits=spec_limits)
    if len(clean) < 3:
        return {
            'theoretical_quantiles': [],
            'observed_quantiles': [],
            'r_squared': 0.0,
            'is_normal': False,
            'n': len(clean),
            'outlier_info': outlier_info,
        }

    try:
        # probplot returns ((osm, osr), (slope, intercept, r)) when fit=True
        pp_result = norm_probplot(clean)
        (osm, osr) = pp_result[0]  # theoretical quantiles and sorted observed values
        r = pp_result[1][2]         # correlation coefficient (R)
        # 大数据量保形降采样：分位数对单调，均匀取 MAX_POINTS 点视觉等价
        # （68k 行文件响应 1.3MB → 0.04MB）；r²/is_normal 仍基于全量数据；
        # 小数据（≤ 阈值）行为零变更
        keep = (uniform_indices(len(osm))
                if len(osm) > DOWN_SAMPLE_THRESHOLD
                else np.arange(len(osm)))
        theoretical = [round(float(v), 6) for v in osm[keep]]
        observed = [round(float(v), 6) for v in osr[keep]]

        r_squared = round(r * r, 4)
        is_normal = r_squared > 0.95

        return {
            'theoretical_quantiles': theoretical,
            'observed_quantiles': observed,
            'r_squared': r_squared,
            'is_normal': is_normal,
            'n': len(clean),
            'outlier_info': outlier_info,
        }
    except Exception:
        return {
            'theoretical_quantiles': [],
            'observed_quantiles': [],
            'r_squared': 0.0,
            'is_normal': False,
            'n': len(clean),
            'outlier_info': outlier_info,
        }
