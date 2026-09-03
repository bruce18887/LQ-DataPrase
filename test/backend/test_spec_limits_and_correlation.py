"""Regression guard: spec-limit resolution (no phantom limits) and the correlation matrix.

**Phantom spec limits** were a single root cause with five downstream symptoms.
``parse_limit_string`` used to return ``default_min`` (every caller passed 0.0)
for missing/placeholder limits, and returned the *data's own extremes* for the
literal keywords ``'Min'``/``'Max'``:

* CPK became ``-|mean|/(3*sigma)`` -- a large negative number;
* ``detect_outliers_iqr``'s ``min(lower_bound, 0.0)`` clamped the low fence, so
  low-side outliers were never detected;
* the exported PPT histogram binned over -2.5..22.5 and captured **0 of 8**
  points for TEMP-style data (25~33) -- blank chart while the screen was fine;
* ``'Min'``/``'Max'`` made LSL/USL equal the data min/max, which forces
  ``Cpk <= 0.5`` mathematically (mean lies inside [min,max], range ~ 6.9 sigma
  for large n) -- measured ``Test_Time`` cpk=0.4245, graded D/red. Any process
  capability was reported as failing.

``resolve_spec_limit`` now returns ``None`` for both cases, and a real ``[0, 0]``
spec is still honoured because it parses to actual floats.

**Correlation matrix**: an all-1.0 matrix was returned when fewer than 2 clean
rows survived (the heatmap then claimed every pair was perfectly correlated),
and NaN was flattened to 0.0, which made a constant column's *self*-correlation
read as 0.
"""
import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.statistics import (
    calculate_fail_test_item_statistics,
    compute_correlation_matrix,
    compute_cpk,
    compute_range_statistics,
    detect_fail_data,
    detect_outliers_iqr,
    parse_limit_string,
    resolve_spec_limit,
    resolve_spec_limits,
)


class ResolveSpecLimitTests(SimpleTestCase):
    def test_numeric_limits_parse(self):
        self.assertEqual(resolve_spec_limit('1.5'), 1.5)
        self.assertEqual(resolve_spec_limit(' -2.25 '), -2.25)
        self.assertEqual(resolve_spec_limit('1e3'), 1000.0)

    def test_a_real_zero_zero_spec_is_preserved(self):
        """[0, 0] is a legitimate spec and must NOT be confused with 'missing'."""
        self.assertEqual(resolve_spec_limit('0'), 0.0)
        self.assertEqual(resolve_spec_limit('0.0'), 0.0)

    def test_placeholders_return_none(self):
        for raw in ('', '   ', 'n/a', 'NA', 'na', '-', 'none', 'None', 'nan'):
            self.assertIsNone(resolve_spec_limit(raw), f'{raw!r}')

    def test_min_max_keywords_return_none_not_data_extremes(self):
        """The core fix: these are 'no spec limit', not the data's own range."""
        for raw in ('min', 'Min', 'MIN', 'max', 'Max', 'MAX',
                    'lower limit', 'Lower Limit', 'upper limit'):
            self.assertIsNone(resolve_spec_limit(raw), f'{raw!r}')

    def test_garbage_and_none_return_none(self):
        for raw in (None, 'abc', '1.2.3', object()):
            self.assertIsNone(resolve_spec_limit(raw), f'{raw!r}')

    def test_non_finite_returns_none(self):
        self.assertIsNone(resolve_spec_limit('inf'))
        self.assertIsNone(resolve_spec_limit('-inf'))

    def test_resolve_spec_limits_reads_both_sides(self):
        meta = {'mins': {'A': '1.0', 'B': ''}, 'maxs': {'A': '5.0', 'B': 'Max'}}
        self.assertEqual(resolve_spec_limits(meta, 'A'), (1.0, 5.0))
        self.assertEqual(resolve_spec_limits(meta, 'B'), (None, None))

    def test_resolve_spec_limits_tolerates_missing_param_and_bad_metadata(self):
        self.assertEqual(resolve_spec_limits({'mins': {}, 'maxs': {}}, 'Z'), (None, None))
        self.assertEqual(resolve_spec_limits({}, 'Z'), (None, None))
        self.assertEqual(resolve_spec_limits(None, 'Z'), (None, None))
        self.assertEqual(
            resolve_spec_limits({'mins': 'nope', 'maxs': 'nope'}, 'Z'), (None, None))

    def test_deprecated_wrapper_still_returns_float(self):
        """parse_limit_string is kept as a shim for float-expecting callers."""
        self.assertEqual(parse_limit_string('2.5'), 2.5)
        self.assertEqual(parse_limit_string(''), 0.0)
        self.assertEqual(parse_limit_string('', default_min=-1.0), -1.0)


class RangeStatisticsLimitTests(SimpleTestCase):
    def _series(self):
        return pd.Series(np.linspace(25.0, 33.0, 40))

    def test_missing_limits_give_none_rdl_and_finite_gap(self):
        """safe_gap must never receive None (it would raise TypeError)."""
        stats = compute_range_statistics(
            self._series(), {'mins': {'P': ''}, 'maxs': {'P': ''}}, 'P')
        self.assertIsNone(stats['rdl'][0])
        self.assertIsNone(stats['rdl'][1])
        self.assertIsInstance(stats['rdl'][2], float)
        self.assertGreater(stats['rdl'][2], 0.0)
        # gap falls back to the data range so axis code keeps working
        self.assertAlmostEqual(stats['rdl'][2], stats['dr'][2], places=12)

    def test_min_max_keywords_do_not_become_data_extremes(self):
        s = self._series()
        stats = compute_range_statistics(
            s, {'mins': {'P': 'Min'}, 'maxs': {'P': 'Max'}}, 'P')
        self.assertIsNone(stats['rdl'][0])
        self.assertIsNone(stats['rdl'][1])
        # The old behaviour returned (s.min(), s.max()) here, which forced
        # Cpk <= 0.5 and graded every capability D/red.
        self.assertNotEqual(stats['rdl'][0], float(s.min()))

    def test_real_limits_are_returned(self):
        stats = compute_range_statistics(
            self._series(), {'mins': {'P': '20'}, 'maxs': {'P': '40'}}, 'P')
        self.assertEqual(stats['rdl'][0], 20.0)
        self.assertEqual(stats['rdl'][1], 40.0)
        self.assertAlmostEqual(stats['rdl'][2], 1.0, places=9)

    def test_no_limits_means_no_negative_cpk(self):
        """The user-visible symptom: CPK must not be a large negative number."""
        s = self._series()
        stats = compute_range_statistics(s, {'mins': {}, 'maxs': {}}, 'P')
        result = compute_cpk(stats['mean'], stats['std'],
                             stats['rdl'][0], stats['rdl'][1])
        self.assertEqual(result['cpk'], 0.0)
        self.assertEqual(result['cpk_level'], 'N/A')
        self.assertEqual(result['cpk_color'], 'gray')
        self.assertGreaterEqual(result['cpk'], 0.0)

    def test_outlier_fence_not_clamped_by_phantom_zero(self):
        """A negative-valued param must still expose its low-side outliers."""
        data = pd.Series([-3.0] * 20 + [-1.0] * 20 + [-20.0])
        # no spec limits at all -> pure IQR fences, low outlier detected
        result = detect_outliers_iqr(data, spec_limits=(None, None))
        self.assertIs(result['has_outliers'], True)
        self.assertGreaterEqual(result['outlier_count'], 1)
        self.assertLess(result['lower_bound'], -3.0)


class CorrelationMatrixTests(SimpleTestCase):
    def test_insufficient_sample_does_not_claim_perfect_correlation(self):
        df = pd.DataFrame({'A': [1.0, np.nan], 'B': [2.0, np.nan]})
        result = compute_correlation_matrix(df, ['A', 'B'])
        self.assertTrue(result['insufficient_data'])
        self.assertEqual(result['sample_size'], 1)
        for row in result['matrix']:
            for cell in row:
                self.assertIsNone(cell)

    def test_diagonal_is_one_even_for_constant_column(self):
        """A constant column yields NaN from corr(); self-correlation is 1."""
        df = pd.DataFrame({
            'A': [5.0] * 10,
            'B': list(np.linspace(1.0, 10.0, 10)),
        })
        result = compute_correlation_matrix(df, ['A', 'B'])
        self.assertFalse(result['insufficient_data'])
        self.assertEqual(result['matrix'][0][0], 1.0)
        self.assertEqual(result['matrix'][1][1], 1.0)
        # undefined off-diagonal must be None, not 0.0 ("uncorrelated")
        self.assertIsNone(result['matrix'][0][1])
        self.assertIsNone(result['matrix'][1][0])

    def test_normal_case_is_symmetric_with_unit_diagonal(self):
        rng = np.random.RandomState(0)
        x = rng.normal(0, 1, 200)
        df = pd.DataFrame({'A': x, 'B': x * 2 + rng.normal(0, 0.1, 200),
                           'C': rng.normal(0, 1, 200)})
        result = compute_correlation_matrix(df, ['A', 'B', 'C'])
        m = result['matrix']
        self.assertFalse(result['insufficient_data'])
        for i in range(3):
            self.assertEqual(m[i][i], 1.0)
            for j in range(3):
                self.assertEqual(m[i][j], m[j][i])
        self.assertGreater(m[0][1], 0.9)
        self.assertEqual(len(result['p_values']), 3)

    def test_bool_column_does_not_raise(self):
        df = pd.DataFrame({
            'Dut_Pass': [True, False] * 20,
            'V': list(np.linspace(1.0, 40.0, 40)),
        })
        result = compute_correlation_matrix(df, ['Dut_Pass', 'V'])
        self.assertIn('matrix', result)


class DetectFailDataExplicitColumnsTests(SimpleTestCase):
    """``columns=`` bypass: the 500 that e2e caught on /analysis/histogram/.

    ``detect_fail_data`` does::

        cols_with_limits = columns if columns is not None else get_columns_with_limits(...)

    so when a caller passes ``columns`` explicitly (``analysis_views.histogram``
    passes ``columns=params``), the placeholder filtering inside
    ``get_columns_with_limits`` is **bypassed** and the loop used to do a bare
    ``float(str(metadata['mins'][col]))``. On real gage_m_S1.csv, 13 system
    columns carry the literal limits ``'Min'``/``'Max'`` ->
    ``ValueError: could not convert string to float: 'Min'`` -> HTTP 500.
    """

    def _fixture(self):
        df = pd.DataFrame({
            'Good': [1.0, 2.0, 9.0],        # 真限 0.5~8.0：9.0 越上限
            'Test_Time': [5.0, 6.0, 7.0],   # 限值是字面 'Min'/'Max'
            'NoLimit': [1.0, 2.0, 3.0],     # 限值缺失（空串）
            'SW_Bin': [1, 1, 7],
        })
        meta = {
            'format': 'CTA8290D',
            'mins': {'Good': '0.5', 'Test_Time': 'Min', 'NoLimit': ''},
            'maxs': {'Good': '8.0', 'Test_Time': 'Max', 'NoLimit': ''},
        }
        return df, meta

    def test_placeholder_limit_columns_do_not_raise(self):
        df, meta = self._fixture()
        _idx, fail_columns, _cells = detect_fail_data(
            df, meta, columns=['Good', 'Test_Time', 'NoLimit'])
        # 真限列仍正常判越限；占位/缺失限值的列不参与判定也不报错
        self.assertIn('Good', fail_columns)
        self.assertNotIn('Test_Time', fail_columns)
        self.assertNotIn('NoLimit', fail_columns)

    def test_fail_test_item_statistics_with_explicit_columns(self):
        """analysis_views.histogram 走的就是这个入口。"""
        df, meta = self._fixture()
        out = calculate_fail_test_item_statistics(
            df, meta, columns=['Good', 'Test_Time', 'NoLimit'])
        self.assertIn('Good', out)
        self.assertEqual(out['Good']['fail_count'], 1)
        self.assertNotIn('Test_Time', out)
        self.assertNotIn('NoLimit', out)

    def test_column_absent_from_metadata_does_not_keyerror(self):
        """旧写法用 metadata['mins'][col] 下标，显式 columns 多给一个列就 KeyError。"""
        df, meta = self._fixture()
        _idx, fail_columns, _cells = detect_fail_data(
            df, meta, columns=['Good', 'NotInMetadata'])
        self.assertNotIn('NotInMetadata', fail_columns)
        self.assertIn('Good', fail_columns)

    def test_default_path_still_filters_placeholders(self):
        """不传 columns 时走 get_columns_with_limits，行为保持不变。"""
        df, meta = self._fixture()
        _idx, fail_columns, _cells = detect_fail_data(df, meta)
        self.assertIn('Good', fail_columns)
        self.assertNotIn('Test_Time', fail_columns)
