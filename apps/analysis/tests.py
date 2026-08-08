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
    def _patched_view(df, datafile=None, metadata=None):
        """Return ``(APIRequestFactory, force_authenticate, restore)`` after
        monkey-patching ``_load_df_from_request`` on the concrete view modules
        so it returns ``df`` without touching the database.

        We don't need a real DataFile / parsed file: the histogram / qqplot
        views branch on df.columns long before the heavy stats run. This
        keeps the test fast and DB-independent.
        """
        import types
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis.views import analysis_views, statistics_views

        if datafile is None:
            datafile = types.SimpleNamespace(
                id=1, filename='fake.csv', format_type='CTA8290D',
            )
        if metadata is None:
            metadata = {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}}

        def fake_load(request):
            return df, datafile, metadata, None

        original_analysis = getattr(analysis_views, '_load_df_from_request', None)
        original_statistics = getattr(statistics_views, '_load_df_from_request', None)

        analysis_views._load_df_from_request = fake_load
        statistics_views._load_df_from_request = fake_load

        def restore():
            if original_analysis is not None:
                analysis_views._load_df_from_request = original_analysis
            if original_statistics is not None:
                statistics_views._load_df_from_request = original_statistics

        return APIRequestFactory(), force_authenticate, restore

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
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0], 'Param1': [4.0, 5.0, 6.0]})
        factory, force_authenticate, restore = self._patched_view(df)
        self.addCleanup(restore)

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
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0], 'Param1': [4.0, 5.0, 6.0]})
        factory, force_authenticate, restore = self._patched_view(df)
        self.addCleanup(restore)

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
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0]})
        factory, force_authenticate, restore = self._patched_view(df)
        self.addCleanup(restore)

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
        from apps.analysis.views import StatisticsViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0]})
        factory, force_authenticate, restore = self._patched_view(df)
        self.addCleanup(restore)

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


class CustomLimitCpkApiTests(SimpleTestCase):
    """``POST /analysis/histogram/`` returns ``custom_cpk`` in CL mode.

    CustomLimit acts as a user-supplied spec-limit override: with
    ``range_type='CL'`` and both bounds provided, the response carries an
    extra ``custom_cpk`` (computed against the custom bounds) alongside the
    RDL-anchored ``cpk`` so the front-end can show before/after values.
    Outside CL the three fields stay ``null``.
    """

    @staticmethod
    def _patched_view(df, metadata):
        """Monkey-patch ``_load_df_from_request`` so no DB/DataFile is needed."""
        import types
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis.views import analysis_views

        datafile = types.SimpleNamespace(
            id=1, filename='fake.csv', format_type=metadata.get('format'),
        )

        def fake_load(request):
            return df, datafile, metadata, None

        original = getattr(analysis_views, '_load_df_from_request', None)
        analysis_views._load_df_from_request = fake_load

        def restore():
            if original is not None:
                analysis_views._load_df_from_request = original

        return APIRequestFactory(), force_authenticate, restore

    @staticmethod
    def _authed_post(factory, force_authenticate, url, payload):
        import types
        request = factory.post(url, payload, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False,
        ))
        return request

    @classmethod
    def _df_meta(cls):
        df = pd.DataFrame({'Param0': [10.4480, 10.4495, 10.4510, 10.4519,
                                      10.4530, 10.4545, 10.4553]})
        metadata = {'format': 'CTA8280F', 'mins': {'Param0': '8.0'},
                    'maxs': {'Param0': '14.3'}, 'units': {'Param0': 'uA'}}
        return df, metadata

    def test_cl_mode_returns_custom_cpk(self):
        """CL with custom bounds → custom_cpk present, differs from RDL cpk."""
        from apps.analysis.views import AnalysisViewSet

        df, metadata = self._df_meta()
        factory, force_authenticate, restore = self._patched_view(df, metadata)
        self.addCleanup(restore)

        request = self._authed_post(factory, force_authenticate,
                                    '/api/v1/analysis/histogram/', {
            'file_id': 1, 'params': ['Param0'],
            'range_type': 'CL', 'custom_low': 10.40, 'custom_high': 10.50,
        })
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        r = response.data['results']['Param0']
        self.assertIsNotNone(r['custom_cpk'], 'custom_cpk must be computed in CL mode')
        self.assertNotEqual(r['custom_cpk'], r['cpk'])
        self.assertLess(r['custom_cpk'], r['cpk'])
        self.assertIsNotNone(r['custom_cpk_level'])
        self.assertIn(r['custom_cpk_color'],
                      ('green', 'orange', 'darkorange', 'red', 'gray'))
        # Custom bounds echoed back so the chart can draw the CL markLines.
        self.assertEqual(r['custom_low'], 10.40)
        self.assertEqual(r['custom_high'], 10.50)

    def test_non_cl_mode_returns_null_custom_cpk(self):
        """Outside CL the custom_cpk fields stay null."""
        from apps.analysis.views import AnalysisViewSet

        df, metadata = self._df_meta()
        factory, force_authenticate, restore = self._patched_view(df, metadata)
        self.addCleanup(restore)

        request = self._authed_post(factory, force_authenticate,
                                    '/api/v1/analysis/histogram/', {
            'file_id': 1, 'params': ['Param0'],
            'range_type': 'RDL',
        })
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        r = response.data['results']['Param0']
        self.assertIsNone(r['custom_cpk'])
        self.assertIsNone(r['custom_cpk_level'])
        self.assertIsNone(r['custom_cpk_color'])
        self.assertIsNone(r['custom_low'])
        self.assertIsNone(r['custom_high'])


def _num_peaks(y):
    """Count strict local maxima (y[i] greater than both neighbours)."""
    return sum(1 for i in range(1, len(y) - 1) if y[i] > y[i - 1] and y[i] > y[i + 1])


class KdeCurveApiTests(SimpleTestCase):
    """POST /analysis/histogram/ must return the non-parametric KDE curve.

    The normal overlay cannot represent bimodal data; ``kde_curve`` (200
    sampled points) lets the front-end draw a density curve that follows the
    actual shape.  Pin both the presence and the bimodal shape semantics.
    """

    @classmethod
    def _df_meta(cls, vals):
        df = pd.DataFrame({'Param0': vals})
        metadata = {'format': 'CTA8280F', 'mins': {'Param0': '8.0'},
                    'maxs': {'Param0': '14.3'}, 'units': {'Param0': 'uA'}}
        return df, metadata

    def test_histogram_api_returns_kde_curve(self):
        from apps.analysis.views import AnalysisViewSet

        rng = np.random.default_rng(42)
        df, metadata = self._df_meta(rng.normal(11.0, 0.8, 500).tolist())
        factory, force_authenticate, restore = StaleParamAcrossFileSwitchTests._patched_view(df, metadata=metadata)
        self.addCleanup(restore)

        request = StaleParamAcrossFileSwitchTests._authed_post(
            factory, force_authenticate, '/api/v1/analysis/histogram/', {
                'file_id': 1, 'params': ['Param0'], 'range_type': 'RDL',
            })
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        r = response.data['results']['Param0']
        curve = r['kde_curve']
        self.assertIsNotNone(curve)
        self.assertEqual(len(curve), 200)
        self.assertGreater(max(p[1] for p in curve), 0)
        # 干净数据无离群值：裁剪口径曲线应缺席（前端回退到全量曲线）
        self.assertIsNone(r['filtered_kde_curve'])

    def test_histogram_api_kde_curve_split_all_vs_filtered(self):
        """离群数据下 KDE 曲线双口径：全量与 IQR 裁剪各一份且不同。

        全量曲线（kde_curve）如实包含离群点（fail 信息），裁剪曲线
        （filtered_kde_curve）与 filtered_mean/std 同源——前端在裁剪
        模式下切换后者，曲线永远与柱形同源。注意：KDE 峰值是众数而非
        均值，样本微偏态时天然偏离（≈带宽量级），因此用定性断言——
        离群点膨胀全量曲线带宽 → 全量峰值显著低于裁剪峰值（实测 ~2x），
        且裁剪峰值落在 filtered_mean ± 1σ 内（同源）。
        """
        from apps.analysis.views import AnalysisViewSet

        rng = np.random.default_rng(42)
        vals = rng.normal(11.0, 0.8, 500).tolist() + [22.0] * 100
        df, metadata = self._df_meta(vals)
        factory, force_authenticate, restore = StaleParamAcrossFileSwitchTests._patched_view(df, metadata=metadata)
        self.addCleanup(restore)

        request = StaleParamAcrossFileSwitchTests._authed_post(
            factory, force_authenticate, '/api/v1/analysis/histogram/', {
                'file_id': 1, 'params': ['Param0'], 'range_type': 'RDL',
            })
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        r = response.data['results']['Param0']
        self.assertTrue(r['outlier_info']['has_outliers'])
        self.assertIsNotNone(r['filtered_mean'])
        full = r['kde_curve']
        filtered = r['filtered_kde_curve']
        self.assertIsNotNone(full)
        self.assertIsNotNone(filtered)
        # 数据源不同（全量含 100 个离群点）→ 采样曲线必须不同
        self.assertNotEqual(full, filtered)
        # 离群点膨胀带宽：全量曲线峰值应显著低于裁剪曲线
        full_peak_y = max(p[1] for p in full)
        filtered_peak_y = max(p[1] for p in filtered)
        self.assertGreater(filtered_peak_y, full_peak_y)
        # 裁剪曲线峰值（众数）与 filtered_mean 同源：落在 ±1σ 内
        peak_x = max(filtered, key=lambda p: p[1])[0]
        self.assertLessEqual(abs(peak_x - r['filtered_mean']), r['filtered_std'])

    def test_histogram_api_kde_curve_shows_two_peaks_for_bimodal(self):
        from apps.analysis.views import AnalysisViewSet

        rng = np.random.default_rng(42)
        vals = np.concatenate([
            rng.normal(9.5, 0.35, 300),
            rng.normal(12.0, 0.35, 300),
        ]).tolist()
        df, metadata = self._df_meta(vals)
        factory, force_authenticate, restore = StaleParamAcrossFileSwitchTests._patched_view(df, metadata=metadata)
        self.addCleanup(restore)

        request = StaleParamAcrossFileSwitchTests._authed_post(
            factory, force_authenticate, '/api/v1/analysis/histogram/', {
                'file_id': 1, 'params': ['Param0'], 'range_type': 'RDL',
            })
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        curve = response.data['results']['Param0']['kde_curve']
        self.assertIsNotNone(curve)
        self.assertEqual(_num_peaks([p[1] for p in curve]), 2)


class ChartConfigFilterTests(SimpleTestCase):
    """Chart-config switches on the analysis endpoints.

    Locks down the four new switches — ignore_no_test_value /
    data_only_bin1 / only_fail_test_item / only_low_cpk — on the
    histogram fast path (param list), the histogram compute path,
    site_stats and serial_distribution. Reuses the fake
    ``_load_df_from_request`` harness from StaleParamAcrossFileSwitchTests
    (no DB); the fake user has no ``settings`` attribute, which also pins
    the ``get_cpk_b_threshold`` fallback path.
    """

    METADATA = {
        'format': 'CTA8290D',
        'mins': {'Param0': '8.0', 'Param1': '0.5', 'FailOnly': '8.0',
                 'ParamBin1Empty': '8.0', 'ParamLowCpk': '8.0',
                 'ParamHighCpk': '8.0', 'ParamMidCpk': '8.0',
                 'ParamOutlierLow': '8.0'},
        'maxs': {'Param0': '14.3', 'Param1': '3.5', 'FailOnly': '14.3',
                 'ParamBin1Empty': '14.3', 'ParamLowCpk': '14.3',
                 'ParamHighCpk': '14.3', 'ParamMidCpk': '14.3',
                 'ParamOutlierLow': '14.3'},
        'units': {'Param0': 'V', 'Param1': 'uA', 'FailOnly': 'V',
                  'ParamBin1Empty': 'V', 'ParamLowCpk': 'V',
                  'ParamHighCpk': 'V', 'ParamMidCpk': 'V',
                  'ParamOutlierLow': 'V'},
    }

    def _frame(self):
        """10 rows: pass-bin rows are 0,2,3,4,6,7,8,9; fail rows 1,5."""
        return pd.DataFrame({
            'serial': list(range(101, 111)),
            'SW_Bin': [1, 2, 1, 1, 1, 2, 1, 1, 1, 1],
            'Site': [1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            'Param0': [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0],
            'Param1': [1.9, 2.0, 2.05, 1.95, 2.1, 1.98, 2.02, 1.96, 2.04, 2.0],
            # fail rows (1,5) exceed USL 14.3 → the only fail test item
            'FailOnly': [10.1, 15.0, 10.3, 10.4, 10.5, 15.0, 10.7, 10.8, 10.9, 11.0],
            'ParamAllNan': [np.nan] * 10,
            # values exist only on fail rows → empty inside Bin1
            'ParamBin1Empty': [np.nan, 10.1, np.nan, np.nan, np.nan,
                               10.2, np.nan, np.nan, np.nan, np.nan],
            # cpk ≈ 0.9 → low
            'ParamLowCpk': [8.5, 8.6, 8.7, 8.8, 8.9, 8.4, 8.6, 8.8, 9.0, 9.2],
            # cpk ≫ 1.33 → not low
            'ParamHighCpk': [10.9, 11.0, 11.05, 11.0, 11.02, 11.03, 10.98, 11.01, 10.99, 11.0],
            # cpk ≈ 1.43 → between 1.33 and 2.0, used for the settings test
            'ParamMidCpk': [8.6, 8.66, 8.72, 8.78, 8.84, 8.96, 9.02, 9.08, 9.14, 9.2],
            # 行 0（bin1）有 14.4 超 usl 14.3 的异常值：全量 CPK 低、filtered CPK 健康
            'ParamOutlierLow': [14.4, 11.0, 11.05, 11.0, 11.02,
                                11.0, 10.98, 11.01, 10.99, 11.0],
            'ParamNoLimit': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        })

    def _post(self, payload, user=None):
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(self._frame(), metadata=self.METADATA)
        self.addCleanup(restore)
        if user is None:
            user = types.SimpleNamespace(
                pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
                is_staff=False, is_superuser=False,
            )
        request = factory.post('/api/v1/analysis/histogram/', payload, format='json')
        force_authenticate(request, user=user)
        return request

    # ── fast path (param list) ──────────────────────────────────────

    def test_fast_path_default_list_keeps_sparse_but_skips_empty(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = set(resp.data['results'].keys())
        self.assertIn('ParamBin1Empty', keys)   # has values on fail rows
        self.assertNotIn('ParamAllNan', keys)   # fully empty, always excluded

    def test_fast_path_data_only_bin1_and_ignore_no_test_value(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'data_only_bin1': True,
                              'ignore_no_test_value': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = set(resp.data['results'].keys())
        self.assertNotIn('ParamBin1Empty', keys)  # empty inside Bin1 → hidden
        self.assertIn('Param0', keys)

    def test_fast_path_only_fail_test_item(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'only_fail_test_item': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(resp.data['results'].keys()), {'FailOnly'})

    def test_fast_path_only_low_cpk_default_threshold(self):
        """Fake user has no settings row → fallback 1.33, no crash."""
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'only_low_cpk': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(resp.data['results'].keys()), {'ParamLowCpk'})
        self.assertNotIn('ParamMidCpk', resp.data['results'])  # 1.43 > 1.33
        # FailOnly 含超限异常值（15.0）→ filtered CPK 健康 → 不列入（显示口径）

    def test_fast_path_only_low_cpk_uses_filtered_cpk(self):
        """低 CPK 判定无条件跟随 CPK 卡显示口径：异常值拉低的参数不列入。

        Regression: 用户反馈「3.1897 (filtered)」这种剔除异常值后 CPK 健康
        的参数也被列入了低 CPK 列表。前端 CPK 卡总是优先显示 filtered_cpk
        （与异常值处理开关无关），因此默认（无 outlier_handling 参数）时
        也不能把 ParamOutlierLow（含 14.4 异常值、filtered 健康）列入。
        """
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'only_low_cpk': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertNotIn('ParamOutlierLow', resp.data['results'])
        self.assertIn('ParamLowCpk', resp.data['results'])

    def test_fast_path_only_low_cpk_reads_user_setting(self):
        user = types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False,
            settings=types.SimpleNamespace(cpk_b_threshold=2.0),
        )
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'only_low_cpk': True}, user=user)
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('ParamMidCpk', resp.data['results'])  # 1.43 < 2.0

    # ── compute path ────────────────────────────────────────────────

    def test_compute_path_data_only_bin1_total_count(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'params': ['Param0'],
                              'data_only_bin1': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['results']['Param0']['total_count'], 8)

    def test_compute_path_only_fail_test_item_drops_non_fail(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'params': ['FailOnly', 'Param1'],
                              'only_fail_test_item': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(resp.data['results'].keys()), {'FailOnly'})

    # ── site_stats / serial_distribution ────────────────────────────

    def test_site_stats_data_only_bin1_drops_bin2_site(self):
        from apps.analysis.views import statistics_views, StatisticsViewSet
        df = pd.DataFrame({
            'serial': list(range(101, 111)),
            'SW_Bin': [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
            'Site': [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
            'Param0': [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0],
        })
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(df, metadata=self.METADATA)
        self.addCleanup(restore)

        request = factory.post('/api/v1/statistics/site_stats/', {
            'file_id': 1, 'param': 'Param0', 'data_only_bin1': True,
        }, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        resp = StatisticsViewSet.as_view({'post': 'site_stats'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        site_names = [s['Site'] for s in resp.data['site_data']]
        self.assertEqual(site_names, ['Site1', 'ALL Site'])  # Site2 gone

    def test_serial_distribution_data_only_bin1(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'Param0',
                              'data_only_bin1': True})
        resp = AnalysisViewSet.as_view({'post': 'serial_distribution'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        total = sum(len(s['data']) for s in resp.data['series_data'])
        self.assertEqual(total, 8)  # 10 rows − 2 fail rows

    def test_serial_distribution_full_frame_keeps_all_points(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'Param0'})
        resp = AnalysisViewSet.as_view({'post': 'serial_distribution'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        total = sum(len(s['data']) for s in resp.data['series_data'])
        self.assertEqual(total, 10)



class FileCorrelationCacheIsolationTests(SimpleTestCase):
    """file_correlation 端点不得污染 LRU 解析缓存。

    回归：file_correlation 曾对 ``get_cached_parsed_file`` 返回的缓存
    DataFrame 原地添加 ``__serial__`` 辅助列，违反缓存"只读"不变量，
    导致后续 browse/histogram/export 请求同一文件时出现幽灵列。
    修复：写列前 ``df = df.copy()``。
    """

    def test_shared_cache_df_not_mutated_by_file_correlation(self):
        import types
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis.views import analysis_views

        shared_df = pd.DataFrame({
            'Serial_No': [1, 2, 3],
            'ParamA': [1.0, 2.0, 3.0],
            'ParamB': [4.0, 5.0, 6.0],
        })
        metadata = {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}}

        orig_404 = analysis_views.get_object_or_404
        orig_load = analysis_views.get_cached_parsed_file
        orig_serial = analysis_views.get_serial_column

        def fake_404(model, *args, **kwargs):
            return types.SimpleNamespace(id=1, filename='fake.csv',
                                         format_type='CTA8290D')

        def fake_load(fid, owner_id, datafile=None):
            # 两个文件返回同一个缓存对象 —— 模拟 LRU 缓存真实行为
            return shared_df, metadata, 'CTA8290D'

        analysis_views.get_object_or_404 = fake_404
        analysis_views.get_cached_parsed_file = fake_load
        analysis_views.get_serial_column = lambda df: 'Serial_No'
        self.addCleanup(lambda: setattr(analysis_views, 'get_object_or_404', orig_404))
        self.addCleanup(lambda: setattr(analysis_views, 'get_cached_parsed_file', orig_load))
        self.addCleanup(lambda: setattr(analysis_views, 'get_serial_column', orig_serial))

        factory = APIRequestFactory()
        request = factory.post('/api/v1/analysis/file_correlation/', {
            'file1_id': 1, 'file2_id': 2,
        }, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False,
        ))

        from apps.analysis.views import AnalysisViewSet
        view = AnalysisViewSet.as_view({'post': 'file_correlation'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        # 缓存对象不允许被端点改写
        self.assertNotIn('__serial__', shared_df.columns)
        # 端点自身逻辑仍可用（3 个共同序列号被匹配；Serial_No 为 int64
        # 数值列，与 ParamA/ParamB 一起计入公共参数）
        self.assertEqual(response.data['common_serials'], 3)
        self.assertEqual(response.data['common_params'], 3)


class HistogramSigmaFieldTests(ChartConfigFilterTests):
    """histogram 响应必须同时提供全量与裁剪口径的 σ 字段。

    回归：前端曾在本地用 displayMean/displayStd 重算 σ（与图表标记线的
    全量 σ 矛盾）；后端现统一返回 sigma4 + filtered_sigma3/4/6，前端
    卡片与标记线消费同一组值。
    """

    def test_compute_path_returns_raw_and_filtered_sigma_fields(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'params': ['ParamOutlierLow']})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        r = resp.data['results']['ParamOutlierLow']

        # 全量 σ 字段齐全（含新增的 4σ）
        self.assertIn('sigma3_min', r)
        self.assertIn('sigma4_min', r)
        self.assertIn('sigma6_min', r)
        # mean/std 先各自 round(6) 再组合，与响应值有 ~1e-6 舍入差，用 places=4
        self.assertAlmostEqual(r['sigma4_min'], r['mean'] - 4 * r['std'], places=4)
        self.assertAlmostEqual(r['sigma4_max'], r['mean'] + 4 * r['std'], places=4)

        # ParamOutlierLow 含异常值 → filtered 统计存在
        self.assertTrue(r['outlier_info']['has_outliers'])
        self.assertIsNotNone(r['filtered_mean'])
        self.assertIsNotNone(r['filtered_std'])
        self.assertGreater(r['filtered_std'], 0)

        # 裁剪口径 σ = filtered_mean ± k*filtered_std（与 filtered_mean/std 同源）
        self.assertAlmostEqual(r['filtered_sigma3_min'],
                               r['filtered_mean'] - 3 * r['filtered_std'], places=6)
        self.assertAlmostEqual(r['filtered_sigma3_max'],
                               r['filtered_mean'] + 3 * r['filtered_std'], places=6)
        self.assertAlmostEqual(r['filtered_sigma4_min'],
                               r['filtered_mean'] - 4 * r['filtered_std'], places=6)
        self.assertAlmostEqual(r['filtered_sigma6_max'],
                               r['filtered_mean'] + 6 * r['filtered_std'], places=6)

    def test_normal_curves_returned_raw_and_filtered(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'params': ['ParamOutlierLow']})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        r = resp.data['results']['ParamOutlierLow']

        # 全量曲线存在（raw mean/std）
        self.assertIsNotNone(r['normal_curve'])
        self.assertGreater(len(r['normal_curve']), 1)
        # 有异常值 → 裁剪口径曲线存在
        self.assertIsNotNone(r['filtered_normal_curve'])
        self.assertGreater(len(r['filtered_normal_curve']), 1)
        # 裁剪曲线峰值在 filtered_mean 附近（用 filtered mean/std 计算）
        peak = max(r['filtered_normal_curve'], key=lambda p: p[1])
        self.assertAlmostEqual(peak[0], r['filtered_mean'], delta=0.05)
        # 无异常值参数：filtered 曲线为 None
        request2 = self._post({'file_id': 1, 'params': ['Param0']})
        resp2 = AnalysisViewSet.as_view({'post': 'histogram'})(request2)
        resp2.render()
        r2 = resp2.data['results']['Param0']
        self.assertIsNotNone(r2['normal_curve'])
        self.assertIsNone(r2['filtered_normal_curve'])


    def test_filtered_cpk_level_and_color_returned_with_filtered_cpk(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'params': ['ParamOutlierLow']})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        r = resp.data['results']['ParamOutlierLow']
        self.assertIsNotNone(r['filtered_cpk'])
        # 评级标签与颜色与 CPK 卡显示格式一致（此前前端显示 '(filtered)' 丢评级）。
        # ParamOutlierLow：含 14.4 异常值 → 全量 CPK 低（D级/red）；剔除后 ≈34 → A级/green
        self.assertIsNotNone(r['filtered_cpk_level'])
        self.assertIsNotNone(r['filtered_cpk_color'])
        self.assertEqual(r['cpk_color'], 'red')
        self.assertEqual(r['filtered_cpk_color'], 'green')
        self.assertNotEqual(r['filtered_cpk_level'], r['cpk_level'])

    def test_no_outlier_param_returns_null_filtered_sigma(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'params': ['Param0']})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        r = resp.data['results']['Param0']
        self.assertFalse(r['outlier_info']['has_outliers'])
        self.assertIsNone(r['filtered_sigma3_min'])
        self.assertIsNone(r['filtered_sigma6_max'])


class ParamTrendPerFileLimitsTests(SimpleTestCase):
    """compute_param_trend 必须按文件独立解析规格限。

    回归：旧实现把第一个文件的 lsl/usl 复用到所有文件——不同批次/
    程序版本的规格不同时，后续文件的 CPK 数学上错误。
    """

    @staticmethod
    def _file(df, fid, mins, maxs):
        return {
            'df': df,
            'metadata': {'mins': mins, 'maxs': maxs, 'units': {}},
            'file_id': fid,
            'filename': f'f{fid}.csv',
            'timestamp': '',
        }

    def test_per_file_limits_drive_per_file_cpk(self):
        from apps.analysis.services.statistics.trends import compute_param_trend
        df = pd.DataFrame({'Param': [10.0, 10.2, 10.4]})
        files = [
            self._file(df.copy(), 1, {'Param': '9.0'}, {'Param': '11.0'}),
            self._file(df.copy(), 2, {'Param': '5.0'}, {'Param': '15.0'}),
        ]
        out = compute_param_trend(files, 'Param')

        self.assertEqual(out['trend_data'][0]['lsl'], 9.0)
        self.assertEqual(out['trend_data'][1]['lsl'], 5.0)
        # 同分布数据：限值越宽 → CPK 越大（文件 2 用自身限值而非文件 1 的）
        self.assertGreater(out['trend_data'][1]['cpk'], out['trend_data'][0]['cpk'])
        self.assertGreater(out['trend_data'][0]['cpk'], 0.0)
        # 响应级 limits 取首个完整对
        self.assertEqual(out['limits']['lsl'], 9.0)

    def test_file_without_limits_zero_cpk_and_later_file_keeps_own(self):
        from apps.analysis.services.statistics.trends import compute_param_trend
        df = pd.DataFrame({'Param': [10.0, 10.2, 10.4]})
        files = [
            self._file(df.copy(), 1, {}, {}),
            self._file(df.copy(), 2, {'Param': '9.0'}, {'Param': '11.0'}),
        ]
        out = compute_param_trend(files, 'Param')

        # 缺失限值（parse 回退 0.0 会算出负 CPK）→ lsl=None、cpk=0
        self.assertIsNone(out['trend_data'][0]['lsl'])
        self.assertEqual(out['trend_data'][0]['cpk'], 0.0)
        self.assertEqual(out['trend_data'][1]['lsl'], 9.0)
        self.assertGreater(out['trend_data'][1]['cpk'], 0.0)
        # 首个完整对来自文件 2
        self.assertEqual(out['limits']['lsl'], 9.0)


class NormalPdfCurveTests(SimpleTestCase):
    """normal_pdf_curve：高斯 PDF 公式单一来源（前端/导出/响应共用）。"""

    def test_formula_values(self):
        import math
        from apps.analysis.services.statistics import normal_pdf_curve
        # 奇数采样点 → 中心点恰为均值 0，可直接断言公式值
        curve = normal_pdf_curve(0.0, 1.0, -3.0, 3.0, n_points=201)
        self.assertEqual(len(curve), 201)
        center = curve[100]
        self.assertAlmostEqual(center[0], 0.0, places=5)
        self.assertAlmostEqual(center[1], 1 / math.sqrt(2 * math.pi), places=5)
        # 对称性
        self.assertAlmostEqual(curve[99][1], curve[101][1], places=6)

    def test_zero_std_returns_none(self):
        from apps.analysis.services.statistics import normal_pdf_curve
        self.assertIsNone(normal_pdf_curve(1.0, 0.0, 0.0, 2.0))
        self.assertIsNone(normal_pdf_curve(1.0, -1.0, 0.0, 2.0))

    def test_sampling_range(self):
        from apps.analysis.services.statistics import normal_pdf_curve
        curve = normal_pdf_curve(5.0, 2.0, 1.0, 9.0, n_points=100)
        self.assertEqual(curve[0][0], 1.0)
        self.assertEqual(curve[-1][0], 9.0)
        # 采样点单调
        xs = [c[0] for c in curve]
        self.assertEqual(xs, sorted(xs))


class ComputeCpkSingleSidedTests(SimpleTestCase):
    """compute_cpk 单边规格限：cp/pp 必须为 None（双侧才可定义），cpk/ppk 单侧可算。

    回归：缺失侧以 -inf/+inf 传入时 cp = inf，破坏 JSON 序列化且语义错误。
    """

    def test_lower_only_limit(self):
        from apps.analysis.services.statistics import compute_cpk
        result = compute_cpk(10.0, 1.0, float('-inf'), 12.0)
        self.assertIsNone(result['cp'])
        self.assertIsNone(result['pp'])
        self.assertEqual(result['cp_level'], 'N/A')
        self.assertEqual(result['cp_color'], 'gray')
        # 单侧能力 = (12-10)/(3*1) = 0.667
        self.assertAlmostEqual(result['cpk'], 0.6667, places=3)
        self.assertEqual(result['ppk'], result['cpk'])

    def test_upper_only_limit(self):
        from apps.analysis.services.statistics import compute_cpk
        result = compute_cpk(10.0, 1.0, 8.0, float('inf'))
        self.assertIsNone(result['cp'])
        self.assertAlmostEqual(result['cpk'], 0.6667, places=3)

    def test_both_limits_still_return_cp(self):
        from apps.analysis.services.statistics import compute_cpk
        result = compute_cpk(10.0, 1.0, 8.0, 12.0)
        self.assertAlmostEqual(result['cp'], 0.6667, places=3)
        self.assertIsNotNone(result['pp'])


class FilterFiniteTests(SimpleTestCase):
    """filter_finite：NaN/±inf 一步移除，等价于 dropna + inf 过滤。"""

    def test_removes_nan_and_inf(self):
        from apps.analysis.services.statistics import filter_finite
        series = pd.Series([1.0, float('nan'), 2.0, float('inf'), 3.0, float('-inf')])
        out = filter_finite(series)
        self.assertEqual(out.tolist(), [1.0, 2.0, 3.0])

    def test_index_preserved(self):
        from apps.analysis.services.statistics import filter_finite
        series = pd.Series([1.0, float('nan'), 2.0], index=['a', 'b', 'c'])
        out = filter_finite(series)
        self.assertEqual(out.index.tolist(), ['a', 'c'])

    def test_non_numeric_coerced_to_nan(self):
        from apps.analysis.services.statistics import filter_finite
        series = pd.Series([1.0, 'x', 2.0])
        out = filter_finite(series)
        self.assertEqual(out.tolist(), [1.0, 2.0])
