"""Regression tests for the histogram service.

Focus: ``site_histograms`` is populated for every file that has a Site
column, including the single-site case. Previously the backend returned
``site_histograms: None`` for files with only one unique site, so the
front-end histogram had to label the lone bar as "数据分布" instead of
"Site1" — confusing the user. The 2026-06-07 fix removes the
``> 1`` guard on ``site_idx.unique()``; these tests lock in the
behaviour so a future refactor cannot silently regress it.
"""
import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.data_services import compute_histogram_stats


def _make_df(n: int, sites: list[int], seed: int = 0) -> pd.DataFrame:
    """Build a tiny DataFrame with a Site column and a numeric param."""
    rng = np.random.default_rng(seed)
    # Repeat the site list to get `n` rows, then take the first n.
    sites_full = (sites * (n // len(sites) + 1))[:n]
    return pd.DataFrame({
        'Site': [str(s) for s in sites_full],
        'Param1': rng.normal(0, 1, n).tolist(),
    })


def _meta(format_type: str = 'CTA8290D') -> dict:
    return {'format': format_type, 'unit': 'mV'}


class SiteHistogramsTests(SimpleTestCase):
    """``site_histograms`` must be present whenever a Site column exists."""

    def test_multi_site_populates_per_site_keys(self):
        df = _make_df(200, [1, 2, 3, 4])
        out = compute_histogram_stats(df, _meta(), 'Param1', 'Site')
        self.assertIsInstance(out['site_histograms'], dict)
        self.assertEqual(
            set(out['site_histograms'].keys()), {'1', '2', '3', '4'}
        )
        # Each site's bin list has the same length as bin_centers.
        bin_count = len(out['bin_centers'])
        for site, hist in out['site_histograms'].items():
            self.assertEqual(
                len(hist), bin_count, f'site {site} bin count mismatch'
            )

    def test_single_site_populates_one_key(self):
        # Regression: previously returned site_histograms=None and the
        # front-end mis-labelled the only site as "数据分布".
        df = _make_df(200, [1])
        out = compute_histogram_stats(df, _meta(), 'Param1', 'Site')
        self.assertIsInstance(out['site_histograms'], dict)
        self.assertEqual(set(out['site_histograms'].keys()), {'1'})
        self.assertEqual(len(out['site_histograms']['1']), len(out['bin_centers']))

    def test_no_site_column_keeps_none(self):
        # When the file has no Site column at all, site_histograms stays
        # None and the front-end falls back to the "数据分布" label — this
        # is the only legitimate "no per-site data" case.
        df = _make_df(200, [1])  # has a Site column
        df = df.drop(columns=['Site'])
        out = compute_histogram_stats(df, _meta(), 'Param1', site_col=None)
        self.assertIsNone(out['site_histograms'])

    def test_single_site_percentages_sum_to_about_100(self):
        # Same denominator (total_count = all sites) as multi-site case.
        df = _make_df(300, [1])
        out = compute_histogram_stats(df, _meta(), 'Param1', 'Site')
        site_sum = sum(out['site_histograms']['1'])
        # Allow a small tolerance for overflow/underflow bins and rounding.
        self.assertGreater(site_sum, 95.0)
        self.assertLess(site_sum, 100.05)


class EmptyParamFilterTests(SimpleTestCase):
    """Regression: empty-string column names from trailing-comma CSV headers
    must not appear in the histogram fast-path response.

    The CTA8280F parser historically produced an unnamed column ``""`` from
    a trailing comma in the header. That column was all-NaN, passed the
    ``dtype in ('int64','float64')`` numeric_cols check, and ended up in
    the params list. Selecting it 400'd the QQ plot and other endpoints
    (``if param not in df.columns``). The 2026-06-07 fix filters blanks
    out of the response so the param selector never offers the phantom.
    """

    def test_histogram_fast_path_filters_empty_column(self):
        from apps.analysis.views import _filter_blank_params

        # Simulate the params list as it would be built right before the
        # ``{p: {} for p in params}`` dict comprehension in
        # ``AnalysisViewSet.histogram``.
        raw = ['Index_No', 'Dut_No', '', 'CON_VIN', '   ']
        filtered = _filter_blank_params(raw)
        self.assertNotIn('', filtered, 'empty-string column name must be filtered out')
        self.assertNotIn('   ', filtered, 'whitespace-only column name must be filtered out')
        self.assertEqual(set(filtered), {'Index_No', 'Dut_No', 'CON_VIN'})

    def test_histogram_fast_path_keeps_real_params(self):
        from apps.analysis.views import _filter_blank_params

        # When there are no blanks, the filter must be a no-op.
        raw = ['CON_VIN', 'CON_VCC', 'BV_HS_100uA_1']
        self.assertEqual(_filter_blank_params(raw), raw)


class QqPlotParamGuardTests(SimpleTestCase):
    """``compute_qqplot`` and the qqplot view must reject empty / whitespace
    params gracefully — never 500 — because the user-facing param dropdown
    filters blanks but the endpoint is still callable directly.
    """

    def test_compute_qqplot_handles_empty_series(self):
        import numpy as np
        from apps.analysis.services.statistics.computations import compute_qqplot

        # Empty / all-NaN series — should return zeros, not raise.
        empty = pd.Series([], dtype=float)
        result = compute_qqplot(empty)
        self.assertEqual(result['n'], 0)
        self.assertFalse(result['is_normal'])
        self.assertEqual(result['theoretical_quantiles'], [])

        all_nan = pd.Series([np.nan, np.nan, np.nan])
        result = compute_qqplot(all_nan)
        self.assertEqual(result['n'], 0)
        self.assertFalse(result['is_normal'])


class MultiFileAnalysisTests(SimpleTestCase):
    """Multi-file (多文件分析) tab service logic.

    Covers the common-test-item intersection (by exact column name), the
    ``ignore_no_limit`` filter (keep only params with valid limits in every
    file), and the per-file limit attached to each lot in the distribution.
    """

    @staticmethod
    def _file(cols: dict, mins: dict, maxs: dict, fid: int = 1, name: str = 'f'):
        df = pd.DataFrame(cols)
        meta = {'format': 'CTA8290D', 'mins': mins, 'maxs': maxs, 'units': {}}
        return (fid, df, meta, name)

    def test_common_params_intersects_by_name(self):
        from apps.analysis.services.data_services import compute_common_params

        f1 = self._file(
            {'A': [1.0, 2.0], 'B': [1.0, 2.0], 'Site': ['1', '2']},
            {'A': '0', 'B': '0'}, {'A': '5', 'B': '5'}, fid=1)
        f2 = self._file(
            {'A': [1.0, 2.0], 'C': [1.0, 2.0], 'Site': ['1', '2']},
            {'A': '0', 'C': '0'}, {'A': '5', 'C': '5'}, fid=2)
        # 'Site' is object dtype → excluded; only 'A' is numeric in both.
        self.assertEqual(compute_common_params([f1, f2]), ['A'])

    def test_common_params_ignore_no_limit_keeps_only_limited(self):
        from apps.analysis.services.data_services import compute_common_params

        # 'A' has limits in both files; 'B' has limits only in f1.
        f1 = self._file(
            {'A': [1.0, 2.0], 'B': [1.0, 2.0]},
            {'A': '0', 'B': '0'}, {'A': '5', 'B': '5'}, fid=1)
        f2 = self._file(
            {'A': [1.0, 2.0], 'B': [1.0, 2.0]},
            {'A': '0'}, {'A': '5'}, fid=2)
        self.assertEqual(compute_common_params([f1, f2]), ['A', 'B'])
        # With ignore_no_limit, 'B' drops because f2 has no limit for it.
        self.assertEqual(
            compute_common_params([f1, f2], ignore_no_limit=True), ['A'])

    def test_distribution_attaches_file_id_and_limits(self):
        from apps.analysis.services.data_services import (
            compute_multi_lot_distribution,
        )

        s1 = pd.Series([1.0, 2.0, 3.0])
        s2 = pd.Series([2.0, 3.0, 4.0])
        df1 = pd.DataFrame({'A': s1})
        df2 = pd.DataFrame({'A': s2})
        datasets = {
            '1': {'df': df1, 'metadata': {'mins': {'A': '0'}, 'maxs': {'A': '5'}},
                  'series': s1, 'name': 'f1', 'file_id': 1},
            '2': {'df': df2, 'metadata': {'mins': {'A': 'MIN'}, 'maxs': {'A': 'MAX'}},
                  'series': s2, 'name': 'f2', 'file_id': 2},
        }
        out = compute_multi_lot_distribution(datasets, [s1, s2], 'A')
        lots = {lot['file_id']: lot for lot in out['lot_data']}
        # File 1 has numeric limits → drawn.
        self.assertEqual(lots[1]['lower_limit'], 0.0)
        self.assertEqual(lots[1]['upper_limit'], 5.0)
        # File 2's "MIN"/"MAX" markers are not valid numeric limits → omitted.
        self.assertIsNone(lots[2]['lower_limit'])
        self.assertIsNone(lots[2]['upper_limit'])

