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
import types
from django.test import SimpleTestCase, TestCase

from apps.analysis.services.data_services import compute_histogram_stats
from apps.analysis.services.statistics import compute_boxplot_stats


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


class BoxPlotStatsDtypeToleranceTests(SimpleTestCase):
    """Lock down ``compute_boxplot_stats`` behaviour on non-float dtypes.

    Originally the function did ``data.dropna()`` then
    ``clean_data.apply(lambda x: abs(x) < float('inf'))`` then ``.quantile()``.
    For boolean Series (e.g. ``Dut_Pass``/``PASSFG``):

    * ``pd.to_numeric`` on bool returns the **same** bool Series (no dtype
      change), so ``.quantile(0.25)`` returns ``np.bool_`` and the
      ``q3 - q1`` step raises
      "numpy boolean subtract, the `-` operator, is not supported".
    * For object/string Series, ``abs('foo')`` raises
      "bad operand type for abs(): 'str'".

    The 2026-06-13 fix coerces via ``pd.to_numeric(..., errors='coerce')
    .astype(float)`` at the entry, so these dtypes no longer crash.
    """

    def test_boolean_series_does_not_crash(self):
        s = pd.Series([True, False, True, False, True, True, False] * 10)
        out = compute_boxplot_stats(s)
        # All booleans parse as 0.0/1.0; min=0, max=1, count=70.
        self.assertEqual(out['count'], 70)
        self.assertEqual(out['min'], 0.0)
        self.assertEqual(out['max'], 1.0)
        self.assertEqual(out['q1'], 0.0)
        self.assertEqual(out['q3'], 1.0)

    def test_string_series_does_not_crash(self):
        # Mix of parseable ("1.5") and unparseable ("foo") strings.
        s = pd.Series(['1.5', '2.5', 'foo', '3.5', 'bar', '4.5'] * 10)
        out = compute_boxplot_stats(s)
        # Only the 4 parseable values survive; the rest become NaN and are
        # dropped.
        self.assertEqual(out['count'], 40)
        self.assertEqual(out['min'], 1.5)
        self.assertEqual(out['max'], 4.5)

    def test_pure_string_series_returns_zero_count(self):
        s = pd.Series(['foo', 'bar', 'baz'] * 5)
        out = compute_boxplot_stats(s)
        # No values survive → count=0, defaults returned.
        self.assertEqual(out['count'], 0)
        self.assertEqual(out['min'], 0.0)
        self.assertEqual(out['max'], 0.0)
        self.assertEqual(out['outliers'], [])

    def test_pure_boolean_constant_series_returns_valid_stats(self):
        # Regression: SW_Bin-style "all-same boolean" (pass=1 across the
        # whole file). Pre-fix this raised inside .quantile().
        s = pd.Series([True] * 100)
        out = compute_boxplot_stats(s)
        self.assertEqual(out['count'], 100)
        self.assertEqual(out['min'], 1.0)
        self.assertEqual(out['max'], 1.0)
        self.assertEqual(out['median'], 1.0)
        # iqr == 0 → no outliers
        self.assertEqual(out['outliers'], [])

    def test_numeric_series_still_works(self):
        # Sanity check: the fix must not regress the normal path.
        rng = np.random.default_rng(42)
        s = pd.Series(rng.normal(0, 1, 200))
        out = compute_boxplot_stats(s)
        self.assertEqual(out['count'], 200)
        self.assertLess(out['q1'], out['median'])
        self.assertLess(out['median'], out['q3'])
        self.assertLessEqual(out['min'], out['q1'])
        self.assertLessEqual(out['q3'], out['max'])


class StaleParamAcrossFileSwitchTests(SimpleTestCase):
    """Lock down the "stale selectedParam after file switch" guard.

    Regression: when the user selects ``R_Kelvin_AGND`` on
    ``gage_m_S4.csv`` (file_id=14518) and then switches to
    ``BPD93204_FT1_ETS163550_12252024.csv`` (file_id=14514, an ETS88 file
    with no such column), the persisted Pinia store value carried over
    and the analysis APIs were called with a column that does not exist
    in the new file. ``qqplot`` and ``boxplot`` returned 400, but
    ``histogram`` had no ``param in df.columns`` guard and crashed with
    ``KeyError: 'R_Kelvin_AGND'`` → 500.

    The 2026-06-13 fix:

    1. The frontend ``AnalysisPage.onFileChange`` resets
       ``selectedParam`` and the persisted store value at the start of
       every file change. This is the primary fix.
    2. As defence in depth, the backend ``histogram`` and ``boxplot``
       views now validate that every requested param exists in the
       current DataFrame and return 400 ``no_valid_params`` with a
       structured ``requested``/``missing`` payload instead of 500.

    These tests pin the backend guard so a future refactor that
    re-introduces the ``df[param]`` KeyError fails CI loudly.
    """

    @staticmethod
    def _patched_view(monkey_target_module, df, datafile=None, metadata=None):
        """Return ``(APIRequestFactory, force_authenticate)`` after monkey-patching
        ``_load_df_from_request`` on the views module so it returns ``df``
        without touching the database.

        We don't need a real DataFile / parsed file: the histogram / qqplot
        views branch on df.columns long before the heavy stats run. This
        keeps the test fast and DB-independent.
        """
        import types
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis import views as views_mod

        if datafile is None:
            datafile = types.SimpleNamespace(
                id=1, filename='fake.csv', format_type='CTA8290D',
            )
        if metadata is None:
            metadata = {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}}

        def fake_load(request):
            return df, datafile, metadata, None

        views_mod._load_df_from_request = fake_load
        return APIRequestFactory(), force_authenticate

    @staticmethod
    def _authed_post(factory, force_authenticate, url, payload):
        """POST a JSON payload with an authenticated user."""
        request = factory.post(url, payload, format='json')
        # ``force_authenticate`` short-circuits DRF's auth classes so the
        # ``IsAuthenticated`` permission on the view passes.
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False,
        ))
        return request

    @staticmethod
    def _authed_get(factory, force_authenticate, url, params):
        """GET with query params and an authenticated user."""
        request = factory.get(url, params)
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False,
        ))
        return request

    def test_histogram_view_returns_400_for_unknown_param(self):
        """POST /analysis/histogram/ with a param not in the file → 400."""
        from apps.analysis import views as views_mod
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0], 'Param1': [4.0, 5.0, 6.0]})
        factory, force_authenticate = self._patched_view(views_mod, df)

        request = self._authed_post(factory, force_authenticate,
                                    '/api/v1/analysis/histogram/', {
            'file_id': 1,
            'params': ['__bogus__'],
        })
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        body = response.data
        self.assertEqual(body.get('error'), 'no_valid_params')
        self.assertEqual(body.get('missing'), ['__bogus__'])
        self.assertEqual(body.get('requested'), ['__bogus__'])

    def test_histogram_view_drops_partial_unknown_params(self):
        """When some params exist and others don't, the existing ones still compute.

        Guards against an over-eager fix that would 400 the whole request
        just because one of the params is stale.
        """
        from apps.analysis import views as views_mod
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0], 'Param1': [4.0, 5.0, 6.0]})
        factory, force_authenticate = self._patched_view(views_mod, df)

        request = self._authed_post(factory, force_authenticate,
                                    '/api/v1/analysis/histogram/', {
            'file_id': 1,
            'params': ['Param0', '__bogus__'],
        })
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()

        # The real param must compute; the bogus one is dropped.
        self.assertEqual(response.status_code, 200, response.content)
        body = response.data
        results = body.get('results', {})
        self.assertIn('Param0', results)
        self.assertNotIn('__bogus__', results)

    def test_qqplot_view_returns_param_not_found_for_unknown_param(self):
        """POST /analysis/qqplot/ with a param not in the file → 400 param_not_found."""
        from apps.analysis import views as views_mod
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0]})
        factory, force_authenticate = self._patched_view(views_mod, df)

        request = self._authed_post(factory, force_authenticate,
                                    '/api/v1/analysis/qqplot/', {
            'file_id': 1,
            'param': '__bogus__',
        })
        view = AnalysisViewSet.as_view({'post': 'qqplot'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'param_not_found')

    def test_boxplot_view_returns_400_for_unknown_param(self):
        """GET /statistics/boxplot/ with a param not in the file → 400 no_valid_params."""
        from apps.analysis import views as views_mod
        from apps.analysis.views import StatisticsViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0]})
        factory, force_authenticate = self._patched_view(views_mod, df)

        request = self._authed_get(factory, force_authenticate,
                                   '/api/v1/statistics/boxplot/', {
            'file_id': 1,
            'params': ['__bogus__'],
            'group_by': 'site',
        })
        view = StatisticsViewSet.as_view({'get': 'boxplot'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        body = response.data
        self.assertEqual(body.get('error'), 'no_valid_params')
        self.assertEqual(body.get('missing'), ['__bogus__'])

