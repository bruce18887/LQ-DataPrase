"""Regression tests for the histogram service.

Focus: ``site_histograms`` is populated for every file that has a Site
column, including the single-site case. Previously the backend returned
``site_histograms: None`` for files with only one unique site, so the
front-end histogram had to label the lone bar as "数据分布" instead of
"Site1" — confusing the user. The 2026-06-07 fix removes the
``> 1`` guard on ``site_idx.unique()``; these tests lock in the
behaviour so a future refactor cannot silently regress it.
"""
from unittest import mock

import numpy as np
import pandas as pd
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

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


class HistogramUnknownParamViewTests(TestCase):
    """The histogram view must not 500 when asked for a param that is not in
    the dataframe.

    A stale param can be sent while the user switches files (the front-end
    watcher fires with the previous file's selected param before the new
    param list loads). ``qqplot`` already guards this with a 400
    ``param_not_found``; ``histogram`` used to fall straight through to
    ``df[param]`` -> ``KeyError`` -> 500. The fix skips unknown params so the
    endpoint returns 200 with the param simply absent from ``results``.
    """

    def setUp(self):
        from apps.accounts.models import User
        from apps.datafiles.models import DataFile

        self.user = User.objects.create_user(username='hist_t', password='x')
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='f.csv', file_path='/tmp/f.csv',
            file_size=1, format_type='CTA8290D', status='ready',
        )
        self.df = pd.DataFrame({
            'Site': ['1'] * 20,
            'Param1': np.random.default_rng(0).normal(0, 1, 20).tolist(),
        })
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @mock.patch('apps.analysis.views.get_cached_parsed_file')
    def test_unknown_param_returns_200_not_500(self, mock_cache):
        mock_cache.return_value = (self.df, {'format': 'CTA8290D'}, 'CTA8290D')
        resp = self.client.post(
            '/api/v1/analysis/histogram/',
            {'file_id': self.datafile.id, 'params': ['NoSuchParam'], 'range_type': 'RDL'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        # Unknown param is silently skipped, so results is empty.
        self.assertEqual(resp.data['results'], {})

    @mock.patch('apps.analysis.views.get_cached_parsed_file')
    def test_known_param_still_works(self, mock_cache):
        mock_cache.return_value = (self.df, {'format': 'CTA8290D'}, 'CTA8290D')
        resp = self.client.post(
            '/api/v1/analysis/histogram/',
            {'file_id': self.datafile.id, 'params': ['Param1'], 'range_type': 'RDL'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('Param1', resp.data['results'])

    @mock.patch('apps.analysis.views.get_cached_parsed_file')
    def test_mixed_known_and_unknown_params(self, mock_cache):
        mock_cache.return_value = (self.df, {'format': 'CTA8290D'}, 'CTA8290D')
        resp = self.client.post(
            '/api/v1/analysis/histogram/',
            {'file_id': self.datafile.id, 'params': ['Param1', 'Ghost'], 'range_type': 'RDL'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('Param1', resp.data['results'])
        self.assertNotIn('Ghost', resp.data['results'])
