"""直方图扩展口径回归：自定义限值 CPK、KDE 曲线、σ 字段。
（自 2473 行的 tests.py 按主题拆出，用例逐字搬迁。）
"""
import numpy as np
import pandas as pd
import types
from django.test import SimpleTestCase
from apps.analysis.tests_chart_config import ChartConfigFilterTests
from apps.analysis.tests_param_guards import StaleParamAcrossFileSwitchTests


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

    def test_histogram_api_kde_curves_split_by_outlier_inclusion(self):
        """「KDE含超限」数据源对：fail 数据 → kde_curve 全量 + filtered_kde_curve
        剔除；无异常值 → filtered_kde_curve 为 None。"""
        from apps.analysis.views import AnalysisViewSet

        rng = np.random.default_rng(42)
        vals = np.concatenate([
            rng.normal(11.0, 0.8, 500),
            [30.0] * 20,  # out-of-spec fail values
        ]).tolist()
        df, metadata = self._df_meta(vals)
        factory, force_authenticate, restore = StaleParamAcrossFileSwitchTests._patched_view(df, metadata=metadata)
        self.addCleanup(restore)

        request = StaleParamAcrossFileSwitchTests._authed_post(
            factory, force_authenticate, '/api/v1/analysis/histogram/', {
                'file_id': 1, 'params': ['Param0'], 'range_type': 'DR',
            })
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        r = response.data['results']['Param0']
        full = r['kde_curve']
        filtered = r['filtered_kde_curve']
        self.assertIsNotNone(full)
        self.assertIsNotNone(filtered, 'fail data must yield a filtered curve')
        tail_y = [y for x, y in full if 29.0 <= x <= 31.0]
        self.assertTrue(tail_y)
        self.assertGreater(max(tail_y), 0.001, 'full curve must show the fail bump')
        self.assertTrue(all(y == 0 for x, y in filtered if 29.0 <= x <= 31.0),
                        'filtered curve must exclude the fail bump')


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
