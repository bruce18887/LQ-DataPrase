"""
Parameter/data filtering for single-file analysis (chart config switches).

The four chart-config switches introduced for the analysis page split into
two kinds:

* data-row filters  - ``data_only_bin1`` (only pass-bin rows) applied by
  ``filter_bin1_rows`` before any histogram / serial / site computation;
* test-item filters - ``ignore_no_test_value`` / ``only_fail_test_item`` /
  ``only_low_cpk`` applied to the parameter list (fast path) and replayed
  defensively on the compute path by ``filter_test_items``.

Ordering matters: fail detection (``detect_fail_data``) requires the *full*
DataFrame (fail rows are by definition not Bin1), so the view layer must
compute the fail set from ``df_full`` before applying ``filter_bin1_rows``,
then pass it in as ``fail_items``.  All helpers here return new objects and
never mutate the cached DataFrame in place.
"""
from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd

from .helpers import ensure_numeric, get_1d_from, get_bin_column
from .limits import (
    get_columns_with_limits,
    calculate_fail_test_item_statistics,
    is_pass_bin,
)
from .computations import compute_cpk, compute_range_statistics
from .outliers import detect_outliers_iqr

# A test item whose valid-value ratio falls below this is considered
# "has no TestValue" and hidden from the param list when the switch is on.
NO_TEST_VALUE_MIN_RATIO = 0.05


def get_bin1_mask(df: pd.DataFrame, metadata: Dict) -> Optional[pd.Series]:
    """Return a boolean mask of pass-bin (Bin1) rows, or ``None`` when the
    file has no recognizable Bin column."""
    bin_col = get_bin_column(df, metadata)
    if bin_col is None:
        return None
    bin_series = get_1d_from(df, bin_col)
    # Judge pass-ness on the distinct bin values (cheap) instead of
    # per-row ``is_pass_bin`` calls, reusing its "1"/"Bin1" semantics.
    pass_bins = {b for b in bin_series.unique() if is_pass_bin(b)}
    return bin_series.isin(pass_bins)


def filter_bin1_rows(df: pd.DataFrame, metadata: Dict) -> pd.DataFrame:
    """Keep only pass-bin (Bin1) rows.  Returns the input unchanged when the
    file has no Bin column (the switch is ignored in that case).  The result
    is always a fresh object — never an in-place slice of the cached df."""
    mask = get_bin1_mask(df, metadata)
    if mask is None:
        return df
    return df[mask]


def has_enough_test_values(df: pd.DataFrame, param: str,
                           min_ratio: float = NO_TEST_VALUE_MIN_RATIO) -> bool:
    """True when *param* has at least ``min_ratio`` valid (non-NaN, finite)
    values relative to the total row count.  Used to hide test items that
    carry almost no measurement data."""
    total = len(df)
    if total == 0:
        return False
    series = ensure_numeric(df, param).dropna()
    series = series[series.abs() < np.inf]
    return len(series) / total >= min_ratio


def _display_cpk(series: pd.Series, metadata: Dict, col: str,
                 iqr_multiplier: float) -> float:
    """CPK judged by the same caliber the stats card displays.

    The front end always prefers ``filtered_cpk`` when the backend computed
    one (``useHistogram.ts`` shows ``r.filtered_cpk ?? r.cpk`` regardless of
    the outlier-handling toggle), and histogram.py computes ``filtered_cpk``
    for any column that has outliers.  So this mirrors histogram.py's
    filtered computation unconditionally: bounds from ``detect_outliers_iqr``
    expanded to spec limits, mean/std of the outlier-free subset (ddof=0),
    guard ``normal_count > 1`` and ``std > 0``.  Otherwise the raw all-data
    CPK is used — identical to what the card would show.
    """
    stats = compute_range_statistics(series, metadata, col)
    rdl = stats['rdl']
    cpk = compute_cpk(stats['mean'], stats['std'], rdl[0], rdl[1])['cpk']
    # Only the bounds matter here (no outlier value list needed) — skip
    # ``include_values`` so the hot filter path doesn't build it.
    outlier_info = detect_outliers_iqr(
        series, include_values=False,
        spec_limits=(rdl[0], rdl[1]),
        iqr_multiplier=iqr_multiplier,
    )
    if outlier_info['has_outliers'] and outlier_info['normal_count'] > 1:
        normal = series[
            (series >= outlier_info['lower_bound']) &
            (series <= outlier_info['upper_bound'])
        ]
        if len(normal) > 1:
            filtered_std = normal.std(ddof=0)
            if filtered_std > 0:
                cpk = compute_cpk(
                    normal.mean(), filtered_std, rdl[0], rdl[1]
                )['cpk']
    return cpk


def compute_low_cpk_test_items(df: pd.DataFrame, metadata: Dict,
                               threshold: float,
                               iqr_multiplier: float = 1.5,
                               params: Optional[List[str]] = None) -> Set[str]:
    """Return the set of test items whose *displayed* CPK (against RDL
    limits) is below *threshold*.

    Only columns with valid spec limits are considered — items without
    limits cannot be judged and are simply not included.  Zero-std columns
    yield cpk == 0.0 and therefore count as low-CPK, consistent with the
    histogram's own cpk value.  The judged CPK follows the stats card
    (``_display_cpk``): columns whose raw CPK is dragged low by an outlier
    but whose filtered CPK is healthy are NOT listed — otherwise the list
    would contain ``3.19 (filtered)`` entries the user sees as healthy.

    ``params`` narrows the scan to the given candidate columns.  The
    compute path passes the requested params only (a param switch must not
    re-evaluate every column in the file), while the fast path passes the
    full candidate list.
    """
    if params is not None:
        # ``params`` may include columns without spec limits (numeric list
        # from the fast path) — they cannot be judged, same as the default.
        valid = set(get_columns_with_limits(df, metadata))
        cols = [p for p in params if p in valid]
    else:
        cols = get_columns_with_limits(df, metadata)
    low_cpk: Set[str] = set()
    for col in cols:
        series = ensure_numeric(df, col).dropna()
        series = series[series.abs() < np.inf]
        if len(series) == 0:
            continue
        if _display_cpk(series, metadata, col, iqr_multiplier) < threshold:
            low_cpk.add(col)
    return low_cpk


def filter_test_items(df: pd.DataFrame, metadata: Dict, params: List[str], *,
                      ignore_no_test_value: bool = False,
                      only_fail_test_item: bool = False,
                      only_low_cpk: bool = False,
                      cpk_threshold: float = 1.33,
                      fail_items: Optional[Set[str]] = None,
                      iqr_multiplier: float = 1.5,
                      low_cpk_items: Optional[Set[str]] = None) -> List[str]:
    """Filter *params* by the test-item-level chart-config switches.

    ``df`` is the working DataFrame (usually the Bin1-filtered one) used for
    the no-test-value and low-CPK judgments, keeping the list consistent with
    the histogram statistics.  ``fail_items`` must be precomputed from the
    *full* DataFrame (``calculate_fail_test_item_statistics(...).keys()``) —
    fail rows are never Bin1, so computing it here on a Bin1-filtered frame
    would wipe out every fail item.  When ``fail_items`` is omitted it is
    derived from ``df`` (correct only when ``df`` is the full frame).

    Without a Bin column the file cannot distinguish fail rows, so
    ``only_fail_test_item`` is treated as off (same boundary as
    ``data_only_bin1``).
    """
    if only_fail_test_item:
        if get_bin_column(df, metadata) is None:
            only_fail_test_item = False
        elif fail_items is None:
            fail_items = set(
                calculate_fail_test_item_statistics(df, metadata).keys()
            )

    if only_low_cpk and low_cpk_items is None:
        # Scope the CPK scan to the candidate list itself — the compute
        # path only passes the requested params, so switching a param does
        # not re-evaluate every column of the file.  The fast path may hand
        # over a cached full-set result via ``low_cpk_items``.
        low_cpk_items = compute_low_cpk_test_items(
            df, metadata, cpk_threshold,
            iqr_multiplier=iqr_multiplier, params=params,
        )

    result = []
    for p in params:
        if only_fail_test_item and p not in fail_items:
            continue
        if only_low_cpk and p not in low_cpk_items:
            continue
        if ignore_no_test_value and not has_enough_test_values(df, p):
            continue
        result.append(p)
    return result
