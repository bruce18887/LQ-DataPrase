"""Tests for apps.analysis.services.statistics.outliers."""
import numpy as np
import pandas as pd
import pytest

from apps.analysis.services.statistics.outliers import detect_outliers_iqr


class TestDetectOutliersIqr:
    """Unit tests for detect_outliers_iqr."""

    def test_no_outliers(self):
        """Normal data within range should have no outliers."""
        data = pd.Series([25.0, 25.1, 25.2, 25.3, 25.4, 25.5, 25.6, 25.7])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False
        assert result['outlier_count'] == 0
        assert result['normal_count'] == 8

    def test_extreme_outlier(self):
        """An extreme value like 99999 should be detected as outlier."""
        rng = np.random.RandomState(42)
        normal = [25.0 + rng.normal(0, 0.5) for _ in range(100)]
        data = pd.Series(normal + [99999.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is True
        assert result['outlier_count'] >= 1
        assert result['upper_bound'] < 99999.0

    def test_multiple_outliers(self):
        """Multiple extreme values should all be detected."""
        normal = [25.0] * 100
        data = pd.Series(normal + [99999.0, 88888.0, -99999.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is True
        assert result['outlier_count'] == 3

    def test_include_values_flag(self):
        """outlier_values should only be present when include_values=True."""
        normal = [25.0] * 100
        data = pd.Series(normal + [99999.0])

        result_clip = detect_outliers_iqr(data, include_values=False)
        assert 'outlier_values' not in result_clip

        result_exclude = detect_outliers_iqr(data, include_values=True)
        assert 'outlier_values' in result_exclude
        assert len(result_exclude['outlier_values']) == 1

    def test_empty_data(self):
        """Empty series should return safe defaults."""
        data = pd.Series([], dtype=float)
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False
        assert result['outlier_count'] == 0
        assert result['normal_count'] == 0

    def test_too_few_points(self):
        """Fewer than 4 points should skip detection."""
        data = pd.Series([1.0, 2.0, 3.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False
        assert result['normal_count'] == 3

    def test_all_same_values(self):
        """All identical values should have no outliers (IQR=0)."""
        data = pd.Series([25.0] * 50)
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False

    def test_nan_handling(self):
        """NaN values should be cleaned before detection."""
        data = pd.Series([25.0, 25.1, np.nan, 25.3, np.nan, 99999.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is True
        assert result['normal_count'] == 3

    def test_inf_handling(self):
        """Infinite values should be cleaned before detection."""
        data = pd.Series([25.0, 25.1, float('inf'), 25.3, 99999.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is True

    def test_all_outliers_fallback(self):
        """If all values would be outliers, treat as no outliers."""
        data = pd.Series([1.0, 1.0, 1.0, 100.0, 100.0, 100.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False

    def test_bounds_are_correct(self):
        """Verify the IQR bounds calculation.

        For range(1, 41): Q1=10.75, Q3=30.25, IQR=19.5
        lower = 10.75 - 1.5*19.5 = -18.5
        upper = 30.25 + 1.5*19.5 = 59.5
        """
        data = pd.Series(range(1, 41), dtype=float)
        result = detect_outliers_iqr(data)
        assert result['lower_bound'] == pytest.approx(-18.5)
        assert result['upper_bound'] == pytest.approx(59.5)

    def test_none_input(self):
        """None input should return safe defaults."""
        result = detect_outliers_iqr(None)
        assert result['has_outliers'] is False

    def test_spec_limits_within_iqr(self):
        """Data within spec limits but outside IQR should NOT be outliers."""
        # Create data where IQR bounds are tighter than spec limits
        # Q1=24.0, Q3=26.0, IQR=2.0
        # IQR bounds: lower=24.0-1.5*2=21.0, upper=26.0+1.5*2=29.0
        data = pd.Series([24.0] * 20 + [26.0] * 20 + [20.0, 30.0])
        result_no_spec = detect_outliers_iqr(data)
        # 20.0 and 30.0 are outside IQR bounds (21.0, 29.0)
        assert result_no_spec['has_outliers'] is True
        assert result_no_spec['outlier_count'] == 2

        # With spec limits that include 20.0 and 30.0
        result_with_spec = detect_outliers_iqr(data, spec_limits=(19.0, 31.0))
        # Now bounds should be expanded to (19.0, 31.0), so no outliers
        assert result_with_spec['has_outliers'] is False
        assert result_with_spec['outlier_count'] == 0
        assert result_with_spec['lower_bound'] == pytest.approx(19.0)
        assert result_with_spec['upper_bound'] == pytest.approx(31.0)

    def test_spec_limits_partial_coverage(self):
        """Data partially within spec limits should have fewer outliers."""
        # IQR bounds: lower=21.0, upper=29.0
        data = pd.Series([24.0] * 20 + [26.0] * 20 + [20.0, 30.0, 35.0])
        # Without spec limits: 20.0, 30.0, 35.0 are outliers
        result_no_spec = detect_outliers_iqr(data)
        assert result_no_spec['outlier_count'] == 3

        # With spec limits (22.0, 32.0): bounds expand to (21.0, 32.0)
        # 20.0 is still outlier, 30.0 is now within bounds, 35.0 is still outlier
        result_with_spec = detect_outliers_iqr(data, spec_limits=(22.0, 32.0))
        assert result_with_spec['outlier_count'] == 2
        assert result_with_spec['lower_bound'] == pytest.approx(21.0)
        assert result_with_spec['upper_bound'] == pytest.approx(32.0)

    def test_spec_limits_outside_iqr(self):
        """Spec limits wider than IQR should expand bounds."""
        data = pd.Series([24.0] * 20 + [26.0] * 20 + [20.0, 30.0])
        # IQR bounds: (21.0, 29.0)
        # Spec limits: (15.0, 35.0) - wider than IQR
        result = detect_outliers_iqr(data, spec_limits=(15.0, 35.0))
        assert result['has_outliers'] is False
        assert result['lower_bound'] == pytest.approx(15.0)
        assert result['upper_bound'] == pytest.approx(35.0)

    def test_spec_limits_none_values(self):
        """Spec limits with None values should be ignored."""
        data = pd.Series([24.0] * 20 + [26.0] * 20 + [20.0, 30.0])
        result = detect_outliers_iqr(data, spec_limits=(None, None))
        # Should behave same as no spec limits
        assert result['has_outliers'] is True
        assert result['outlier_count'] == 2

    def test_spec_limits_one_side(self):
        """Spec limits with only one side should expand only that bound."""
        data = pd.Series([24.0] * 20 + [26.0] * 20 + [20.0, 30.0])
        # IQR bounds: (21.0, 29.0)
        # Only lower spec limit: (15.0, None)
        result = detect_outliers_iqr(data, spec_limits=(15.0, None))
        # Lower bound expanded to 15.0, upper bound stays at 29.0
        assert result['lower_bound'] == pytest.approx(15.0)
        assert result['upper_bound'] == pytest.approx(29.0)
        # 20.0 is now within bounds, 30.0 is still outlier
        assert result['outlier_count'] == 1

    def test_iqr_multiplier_strict(self):
        """Strict multiplier (1.5) should detect more outliers."""
        # Data with some mild outliers
        data = pd.Series([24.0] * 20 + [26.0] * 20 + [20.0, 30.0])
        result_strict = detect_outliers_iqr(data, iqr_multiplier=1.5)
        # IQR bounds: (21.0, 29.0)
        # 20.0 and 30.0 are outliers
        assert result_strict['outlier_count'] == 2

    def test_iqr_multiplier宽松(self):
        """宽松 multiplier (3.0) should detect fewer outliers."""
        # Data with some mild outliers
        data = pd.Series([24.0] * 20 + [26.0] * 20 + [20.0, 30.0])
        result_宽松 = detect_outliers_iqr(data, iqr_multiplier=3.0)
        # IQR bounds with 3.0 multiplier: (24.0-3.0*2.0, 26.0+3.0*2.0) = (18.0, 32.0)
        # 20.0 and 30.0 are within bounds
        assert result_宽松['outlier_count'] == 0
        assert result_宽松['lower_bound'] == pytest.approx(18.0)
        assert result_宽松['upper_bound'] == pytest.approx(32.0)

    def test_iqr_multiplier_extreme_outliers(self):
        """Extreme outliers should still be detected with 3.0 multiplier."""
        # Data with extreme outliers
        data = pd.Series([24.0] * 20 + [26.0] * 20 + [10.0, 40.0])
        result = detect_outliers_iqr(data, iqr_multiplier=3.0)
        # IQR bounds with 3.0 multiplier: (18.0, 32.0)
        # 10.0 and 40.0 are still outliers
        assert result['outlier_count'] == 2
