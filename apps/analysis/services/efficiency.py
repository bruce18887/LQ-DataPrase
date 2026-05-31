"""
Efficiency analysis service for ATE test data.
Provides UPH (Units Per Hour) calculation for production throughput analysis.
"""
import logging
from typing import Optional, List, Dict, Any
import pandas as pd

logger = logging.getLogger(__name__)

# Column name patterns to search for test time (case-insensitive lookup)
TEST_TIME_PATTERNS = ['test_time', 'testtime', 'cycle_time', 'cycletime']

# Column name patterns to search for site information
SITE_PATTERNS = ['site', 'sites', 'test_site', 'site_id']


def find_test_time_column(df: pd.DataFrame) -> Optional[str]:
    """
    Auto-detect the test time column in a DataFrame.

    Scans columns for known test time column name patterns (case-insensitive).
    Returns the first matching column name, or None if no match is found.

    Args:
        df: DataFrame to scan

    Returns:
        Column name if found, otherwise None
    """
    col_lower_map = {col: col.lower() for col in df.columns}
    for pattern in TEST_TIME_PATTERNS:
        for col, col_lower in col_lower_map.items():
            if col_lower == pattern:
                return col
    return None


def find_site_column(df: pd.DataFrame) -> Optional[str]:
    """
    Auto-detect the site column in a DataFrame.

    Scans columns for known site column name patterns (case-insensitive exact match).
    Returns the first matching column name, or None if no match is found.

    Args:
        df: DataFrame to scan

    Returns:
        Column name if found, otherwise None
    """
    col_lower_map = {col: col.lower() for col in df.columns}
    for pattern in SITE_PATTERNS:
        for col, col_lower in col_lower_map.items():
            if col_lower == pattern:
                return col
    return None


def _count_sites(df: pd.DataFrame, site_col: str) -> int:
    """Count the number of unique site values in a site column, excluding invalid entries."""
    raw_values = pd.unique(df[site_col])
    valid_count = 0
    for val in raw_values:
        try:
            numeric_val = float(val)
            if pd.isna(numeric_val) or numeric_val == float('inf') or numeric_val == float('-inf'):
                continue
            valid_count += 1
        except (ValueError, TypeError):
            continue
    return max(valid_count, 1)


def compute_uph(
    df: pd.DataFrame,
    test_time_col: Optional[str] = None,
    manual_test_time_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute Units Per Hour (UPH) from test data.

    UPH measures how many units are tested per hour, accounting for multi-site
    parallelism. The total time is the average test time multiplied by the number
    of units divided by the number of sites (parallel test heads).

    Args:
        df: DataFrame containing test data
        test_time_col: Optional explicit test time column name. If not provided,
                       the function will auto-detect from known patterns.
        manual_test_time_sec: Optional manual test time in seconds, used only
                             when no test time column is found.

    Returns:
        Dictionary containing:
            - uph: Units per hour (float)
            - avg_test_time: Average test time in seconds (float)
            - total_tested: Total number of units tested (int)
            - total_time_seconds: Total elapsed test time in seconds (float)
            - source: Source of test time ("column" or "manual")
            - by_site: List of per-site UPH breakdowns, if site column found
            - site_count: Number of parallel test sites (int)
            - warnings: List of warning messages (List[str])
    """
    warnings: List[str] = []
    result: Dict[str, Any] = {
        'uph': 0.0,
        'avg_test_time': 0.0,
        'total_tested': 0,
        'total_time_seconds': 0.0,
        'source': None,
        'by_site': [],
        'site_count': 1,
        'warnings': warnings,
    }

    if df is None or len(df) == 0:
        warnings.append('DataFrame is empty or None')
        return result

    total_tested = len(df)
    result['total_tested'] = total_tested

    # --- Step 1: Resolve test time ---
    actual_test_time_col: Optional[str] = None
    avg_test_time_sec: Optional[float] = None
    source: Optional[str] = None

    if test_time_col is not None:
        # Use explicitly provided column
        if test_time_col in df.columns:
            actual_test_time_col = test_time_col
        else:
            warnings.append(f'Specified test_time_col "{test_time_col}" not found in DataFrame')

    if actual_test_time_col is None:
        # Auto-detect
        detected = find_test_time_column(df)
        if detected is not None:
            actual_test_time_col = detected
        else:
            # Fall back to manual value
            if manual_test_time_sec is not None and manual_test_time_sec > 0:
                avg_test_time_sec = manual_test_time_sec
                source = 'manual'
            else:
                warnings.append(
                    'No test time column found and no manual_test_time_sec provided. '
                    'Cannot compute UPH.'
                )
                return result

    if actual_test_time_col is not None:
        # Extract test time values
        test_time_series = pd.to_numeric(df[actual_test_time_col], errors='coerce')
        valid_times = test_time_series.dropna()
        valid_times = valid_times[valid_times > 0]

        if len(valid_times) == 0:
            warnings.append(f'Test time column "{actual_test_time_col}" contains no valid positive numeric values')
            # Fall back to manual value if provided
            if manual_test_time_sec is not None and manual_test_time_sec > 0:
                avg_test_time_sec = manual_test_time_sec
                source = 'manual'
            else:
                return result
        else:
            avg_test_time_sec = float(valid_times.mean())
            source = 'column'

    if avg_test_time_sec is None or avg_test_time_sec <= 0:
        warnings.append('Average test time is zero or negative; cannot compute UPH')
        return result

    result['avg_test_time'] = round(avg_test_time_sec, 6)
    result['source'] = source

    # --- Step 2: Detect site count ---
    site_col = find_site_column(df)
    site_count = 1
    if site_col is not None:
        site_count = _count_sites(df, site_col)
    result['site_count'] = site_count

    # --- Step 3: Calculate total time and UPH ---
    if site_count > 1:
        total_time_seconds = avg_test_time_sec * total_tested / site_count
    else:
        total_time_seconds = avg_test_time_sec * total_tested

    result['total_time_seconds'] = round(total_time_seconds, 6)

    if total_time_seconds > 0:
        uph = (total_tested / total_time_seconds) * 3600
        result['uph'] = round(uph, 2)
    else:
        warnings.append('Total time is zero; cannot compute UPH')
        return result

    # --- Step 4: Per-site UPH breakdown ---
    if site_col is not None and site_count > 1:
        # Group by site and compute per-site UPH
        site_groups = df.groupby(site_col)
        by_site: List[Dict[str, Any]] = []

        # Sort sites: numeric first, then string
        def _site_sort_key(s):
            try:
                return (0, float(s), '')
            except (ValueError, TypeError):
                return (1, 0, str(s))

        for site_val in sorted(site_groups.groups.keys(), key=_site_sort_key):
            group = site_groups.get_group(site_val)
            site_total = len(group)
            # Compute per-site UPH: each site's units / (avg_test_time * site_units)
            site_total_time = avg_test_time_sec * site_total
            site_uph = (site_total / site_total_time * 3600) if site_total_time > 0 else 0.0
            by_site.append({
                'site': str(site_val),
                'tested': site_total,
                'uph': round(site_uph, 2),
            })

        result['by_site'] = by_site

    return result
