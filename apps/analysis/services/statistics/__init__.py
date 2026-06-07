"""
Statistical analysis service for ATE test data.

This package provides all statistical functions previously available from the
monolithic ``statistics.py`` module.  Importing directly from this package
preserves full backward compatibility::

    from apps.analysis.services.statistics import detect_fail_data
    from apps.analysis.services.statistics import compute_cpk
"""

# ── helpers ──────────────────────────────────────────────────────────
from .helpers import (
    NON_NUMERIC_KEYWORDS,
    BIN_COLUMN_MAPPING,
    get_bin_column_name,
    find_column_by_pattern,
    get_site_column,
    get_serial_column,
    get_coord_columns,
    get_bin_column,
    get_1d,
    get_1d_from,
    ensure_numeric,
    safe_gap,
)

# ── limits ───────────────────────────────────────────────────────────
from .limits import (
    get_columns_with_limits,
    parse_limit_string,
    detect_fail_data,
    calculate_fail_bin_statistics,
    calculate_fail_test_item_statistics,
    is_pass_bin,
    compute_pass_yield,
    build_fail_mask,
    build_col_meta,
)

# ── computations ─────────────────────────────────────────────────────
from .computations import (
    compute_cpk,
    compute_correlation_matrix,
    compute_boxplot_stats,
    compute_range_statistics,
    compute_qqplot,
)

# ── analytics ────────────────────────────────────────────────────────
from .analytics import (
    compute_bin_trend,
    compute_yield_trend,
    compute_param_trend,
    compute_site_stats,
    compute_site_yield_data,
    compute_wafer_fail_data,
    compute_zonal_yield,
    TEST_TIME_COL_CANDIDATES,
    _detect_test_time_col,
    compute_uph,
)

__all__ = [
    # helpers
    'NON_NUMERIC_KEYWORDS',
    'BIN_COLUMN_MAPPING',
    'get_bin_column_name',
    'find_column_by_pattern',
    'get_site_column',
    'get_serial_column',
    'get_coord_columns',
    'get_bin_column',
    'get_1d',
    'get_1d_from',
    'ensure_numeric',
    'safe_gap',
    # limits
    'get_columns_with_limits',
    'parse_limit_string',
    'detect_fail_data',
    'calculate_fail_bin_statistics',
    'calculate_fail_test_item_statistics',
    'is_pass_bin',
    'compute_pass_yield',
    'build_fail_mask',
    'build_col_meta',
    # computations
    'compute_cpk',
    'compute_correlation_matrix',
    'compute_boxplot_stats',
    'compute_range_statistics',
    'compute_qqplot',
    # analytics
    'compute_bin_trend',
    'compute_yield_trend',
    'compute_param_trend',
    'compute_site_stats',
    'compute_site_yield_data',
    'compute_wafer_fail_data',
    'compute_zonal_yield',
    'TEST_TIME_COL_CANDIDATES',
    '_detect_test_time_col',
    'compute_uph',
]
