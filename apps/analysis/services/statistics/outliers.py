"""Outlier detection utilities for data visualization."""

from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd


def detect_outliers_iqr(
    data: pd.Series,
    include_values: bool = False,
    spec_limits: Optional[Tuple[float, float]] = None,
    iqr_multiplier: float = 1.5,
) -> Dict[str, Any]:
    """Detect outliers using the IQR (Interquartile Range) method.

    Uses the IQR rule with configurable multiplier:
        lower_bound = Q1 - iqr_multiplier * IQR
        upper_bound = Q3 + iqr_multiplier * IQR

    Common multiplier values:
        - 1.5: Standard (Tukey's fences), detects mild outliers
        - 3.0: Extreme outliers only, keeps more data points

    When ``spec_limits`` is provided, the outlier bounds are expanded to
    include the spec limits.  This ensures that data points within the
    spec limits (RowDataLimit) are never flagged as outliers, even if
    they fall outside the IQR range.

    Args:
        data: Raw numeric data series.
        include_values: If True, include the full outlier_values list in the
            response. Set to False for "clip" mode (saves bandwidth) and True
            for "exclude" mode.
        spec_limits: Optional (lower, upper) tuple of spec limits.  When
            provided, the outlier bounds are expanded to include these values,
            so data within spec limits is never treated as outliers.
        iqr_multiplier: Multiplier for IQR (default 1.5). Use 3.0 for extreme
            outliers only, which keeps more "mildly" abnormal data points.

    Returns:
        Dict with keys: has_outliers, outlier_count, lower_bound,
        upper_bound, normal_count, and optionally outlier_values.
    """
    empty_result: Dict[str, Any] = {
        'has_outliers': False,
        'outlier_count': 0,
        'lower_bound': 0.0,
        'upper_bound': 0.0,
        'normal_count': 0,
    }

    if data is None or len(data) == 0:
        return empty_result

    # Basic cleaning: coerce to numeric, drop NaN, remove infinities
    clean = pd.to_numeric(data, errors='coerce').dropna()
    clean = clean[np.isfinite(clean.values)]

    if len(clean) < 4:
        # IQR is unreliable with fewer than 4 data points
        return {
            **empty_result,
            'normal_count': len(clean),
        }

    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1

    lower_bound = q1 - iqr_multiplier * iqr
    upper_bound = q3 + iqr_multiplier * iqr

    # Expand bounds to include spec limits (RDL).
    # Data within spec limits should never be treated as outliers.
    if spec_limits is not None:
        spec_lower, spec_upper = spec_limits
        if spec_lower is not None:
            lower_bound = min(lower_bound, spec_lower)
        if spec_upper is not None:
            upper_bound = max(upper_bound, spec_upper)

    outlier_mask = (clean < lower_bound) | (clean > upper_bound)
    outlier_count = int(outlier_mask.sum())
    normal_count = int(len(clean) - outlier_count)

    # Edge case: if ALL values are outliers, treat as no outliers
    # (data distribution is too extreme for IQR to be meaningful)
    if normal_count == 0:
        return {
            **empty_result,
            'lower_bound': round(lower_bound, 6),
            'upper_bound': round(upper_bound, 6),
        }

    result: Dict[str, Any] = {
        'has_outliers': outlier_count > 0,
        'outlier_count': outlier_count,
        'lower_bound': round(lower_bound, 6),
        'upper_bound': round(upper_bound, 6),
        'normal_count': normal_count,
    }

    if include_values and outlier_count > 0:
        result['outlier_values'] = [
            round(float(x), 6) for x in clean[outlier_mask].tolist()
        ]

    return result
