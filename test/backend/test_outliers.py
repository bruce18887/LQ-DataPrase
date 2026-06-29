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
