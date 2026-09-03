"""Regression guard: the numeric entry point must tolerate bool / str / mixed columns.

Two crash families lived in this codebase because ``pd.to_numeric`` was used
without the ``.astype(float)`` step, and because ``abs(series) < inf`` was used
instead of ``filter_finite``:

* **bool columns** (real data has ``Dut_Pass``): ``pd.to_numeric`` returns the
  *same* bool Series, and ``.quantile()`` then raises
  ``TypeError: numpy boolean subtract, the '-' operator, is not supported``.
* **str columns** (``Start_T`` under pandas 3.0 StringDtype -- measured on a
  real CTA8290D file): ``abs(series)`` raises
  ``TypeError: bad operand type for abs(): 'str'``, so a single non-numeric
  column aborted the whole multi-file request instead of being skipped.

Measured dtypes on ``Data/BPD60320_FT.csv`` (CTA8290D, 2301x556):
``Dut_Pass``=bool, ``Start_T``=str, ``SW_Bin``/``Serial_No``/``Site_No``=int64,
the remaining 533 columns float64.

``compute_boxplot_stats`` was already fixed and pinned by
``apps/analysis/tests_param_guards.py``; these tests cover the remaining entry
points so the same mistake cannot survive in one module while being fixed in
another.
"""
import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.statistics import (
    compute_qqplot,
    detect_outliers_iqr,
    ensure_numeric,
    filter_finite,
)


class FilterFiniteDtypeTests(SimpleTestCase):
    def test_bool_series_becomes_float(self):
        """bool must be converted, not passed through as bool."""
        out = filter_finite(pd.Series([True, False, True, True]))
        self.assertEqual(out.dtype, np.float64)
        self.assertEqual(out.tolist(), [1.0, 0.0, 1.0, 1.0])

    def test_str_series_coerced_to_empty_not_raising(self):
        """pandas 3.0 StringDtype: abs() would raise ArrowNotImplementedError."""
        out = filter_finite(pd.Series(['a', 'b', 'c'], dtype='str'))
        self.assertEqual(len(out), 0)

    def test_mixed_numeric_and_text_keeps_only_numbers(self):
        out = filter_finite(pd.Series(['1.5', 'x', 2.5, None, np.inf]))
        self.assertEqual(out.tolist(), [1.5, 2.5])

    def test_int_series_becomes_float(self):
        out = filter_finite(pd.Series([1, 2, 3], dtype='int64'))
        self.assertEqual(out.dtype, np.float64)


class EnsureNumericDtypeTests(SimpleTestCase):
    def test_bool_column_becomes_float(self):
        df = pd.DataFrame({'Dut_Pass': [True, False, True]})
        out = ensure_numeric(df, 'Dut_Pass')
        self.assertEqual(out.dtype, np.float64)
        self.assertEqual(out.tolist(), [1.0, 0.0, 1.0])

    def test_str_column_coerced_to_nan(self):
        df = pd.DataFrame({'Start_T': pd.Series(['a', 'b'], dtype='str')})
        out = ensure_numeric(df, 'Start_T')
        self.assertEqual(out.dtype, np.float64)
        self.assertTrue(out.isna().all())

    def test_nan_is_preserved_not_dropped(self):
        """ensure_numeric keeps NaN (callers decide); filter_finite drops it."""
        df = pd.DataFrame({'v': [1.0, np.nan, 3.0]})
        self.assertEqual(len(ensure_numeric(df, 'v')), 3)
        self.assertEqual(len(filter_finite(df['v'])), 2)


class DetectOutliersBoolTests(SimpleTestCase):
    """``detect_outliers_iqr`` on a bool column used to 500 the histogram endpoint."""

    def test_bool_series_does_not_raise(self):
        data = pd.Series([True] * 40 + [False] * 4)
        result = detect_outliers_iqr(data)
        self.assertIn('has_outliers', result)
        self.assertIn('lower_bound', result)
        self.assertIn('upper_bound', result)
        # All values are 0.0/1.0 -> IQR is 0 or 1, nothing is an extreme outlier.
        self.assertEqual(result['normal_count'] + result['outlier_count'], 44)

    def test_bool_series_bounds_match_float_equivalent(self):
        """The bool path must produce exactly what the float path produces."""
        as_bool = pd.Series([True] * 30 + [False] * 10)
        as_float = pd.Series([1.0] * 30 + [0.0] * 10)
        rb = detect_outliers_iqr(as_bool)
        rf = detect_outliers_iqr(as_float)
        self.assertAlmostEqual(rb['lower_bound'], rf['lower_bound'], places=9)
        self.assertAlmostEqual(rb['upper_bound'], rf['upper_bound'], places=9)
        self.assertEqual(rb['outlier_count'], rf['outlier_count'])

    def test_str_series_does_not_raise(self):
        result = detect_outliers_iqr(pd.Series(['a', 'b', 'c', 'd', 'e'], dtype='str'))
        self.assertIs(result['has_outliers'], False)
        self.assertEqual(result['outlier_count'], 0)


class ComputeQQPlotBoolTests(SimpleTestCase):
    def test_bool_series_does_not_raise(self):
        data = pd.Series([True] * 20 + [False] * 5)
        result = compute_qqplot(data, {}, 'Dut_Pass')
        self.assertIsInstance(result, dict)

    def test_str_series_does_not_raise(self):
        data = pd.Series(['a', 'b', 'c', 'd', 'e'], dtype='str')
        result = compute_qqplot(data, {}, 'Start_T')
        self.assertIsInstance(result, dict)
