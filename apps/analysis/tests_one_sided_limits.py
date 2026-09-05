"""批次 1 回归测试（2026-09-05 分析界面审查）：

1. 直方图单边限值 → 500：LSL='0'、USL='MAX'（'Min'/'Max' 是无规格占位而非数据
   极值）时旧兜底把同一对 (x, None) 原样赋回，safe_gap(None, x) 抛 TypeError。
2. correlation 端点 str 列 → 500：服务层裸 `.astype(float)` 对 pandas 3.0 str
   列抛 ValueError；视图层与兄弟端点（boxplot/correlation_matrix）补同形
   400 no_valid_params 守卫（R3① 守卫一致性）。
3. cpk 端点 stale 参数 → 500：`df[param]` KeyError，补 histogram 同形
   param_not_found 守卫。
"""
import math
import types

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.data_services import (
    compute_histogram_stats,
    compute_correlation_scatter,
)


def _meta(mins=None, maxs=None) -> dict:
    return {'format': 'CTA8290D', 'mins': mins or {}, 'maxs': maxs or {},
            'units': {}}


class OneSidedLimitHistogramTests(SimpleTestCase):
    """单边限值（另一侧 'MIN'/'MAX' 占位 → None）不得 500，bin 网格必须有限。"""

    @staticmethod
    def _df() -> pd.DataFrame:
        rng = np.random.default_rng(7)
        return pd.DataFrame({'Param1': rng.normal(2.0, 0.2, 100).tolist()})

    def test_lsl_only_uses_data_range_for_missing_upper(self):
        # LSL='0' 有效、USL='MAX' 占位 → rdl=(0.0, None)。旧代码在此 500。
        out = compute_histogram_stats(
            self._df(), _meta(mins={'Param1': '0'}, maxs={'Param1': 'MAX'}),
            'Param1', None)
        self.assertIsNotNone(out)
        self.assertEqual(out['lower_limit'], 0.0)
        self.assertIsNone(out['upper_limit'])
        self.assertTrue(all(math.isfinite(c) for c in out['bin_centers']))
        # 左侧仍锚定 LSL（bin 网格向 0 以下延伸），右侧回退数据范围
        self.assertLess(min(out['bin_centers']), 0.0)

    def test_usl_only_uses_data_range_for_missing_lower(self):
        out = compute_histogram_stats(
            self._df(), _meta(mins={'Param1': 'MIN'}, maxs={'Param1': '5'}),
            'Param1', None)
        self.assertIsNotNone(out)
        self.assertIsNone(out['lower_limit'])
        self.assertEqual(out['upper_limit'], 5.0)
        self.assertTrue(all(math.isfinite(c) for c in out['bin_centers']))

    def test_both_placeholder_limits_fall_back_to_data_range(self):
        # 两侧都是占位 → (None, None)，走数据范围兜底（旧行为本就不崩，钉住语义）
        out = compute_histogram_stats(
            self._df(), _meta(mins={'Param1': 'MIN'}, maxs={'Param1': 'MAX'}),
            'Param1', None)
        self.assertIsNotNone(out)
        self.assertTrue(all(math.isfinite(c) for c in out['bin_centers']))


class CorrelationStrColumnTests(SimpleTestCase):
    """str 列做相关性：服务层不再崩溃，视图层 400 与兄弟端点同形。"""

    def test_service_tolerates_str_column(self):
        df = pd.DataFrame({
            'Param1': [1.0, 2.0, 3.0, 4.0],
            'Start_T': ['a', 'b', 'c', 'd'],
        })
        # 旧代码 `astype(float)` 对 str 列抛 ValueError → 500
        out = compute_correlation_scatter(df, 'Param1', 'Start_T')
        self.assertEqual(out['n'], 0)
        self.assertEqual(out['series_data'], [])

    def test_view_returns_400_no_valid_params_for_str_param(self):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis.views import AnalysisViewSet, analysis_views

        df = pd.DataFrame({
            'Param1': [1.0, 2.0, 3.0],
            'Start_T': ['a', 'b', 'c'],
        })
        datafile = types.SimpleNamespace(
            id=1, filename='fake.csv', format_type='CTA8290D')
        metadata = _meta()

        def fake_load(request):
            return df, datafile, metadata, None

        original = analysis_views._load_df_from_request
        analysis_views._load_df_from_request = fake_load
        self.addCleanup(lambda: setattr(analysis_views,
                                        '_load_df_from_request', original))

        request = APIRequestFactory().post(
            '/api/v1/analysis/correlation/',
            {'file_id': 1, 'param_x': 'Param1', 'param_y': 'Start_T'},
            format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        view = AnalysisViewSet.as_view({'post': 'correlation'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'no_valid_params')

    def test_view_still_allows_same_param_both_axes(self):
        # x==y（自相关）在 _sanitize 不去重的前提下必须仍然可用
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis.views import AnalysisViewSet, analysis_views

        df = pd.DataFrame({'Param1': [1.0, 2.0, 3.0, 4.0]})
        datafile = types.SimpleNamespace(
            id=1, filename='fake.csv', format_type='CTA8290D')

        def fake_load(request):
            return df, datafile, _meta(), None

        original = analysis_views._load_df_from_request
        analysis_views._load_df_from_request = fake_load
        self.addCleanup(lambda: setattr(analysis_views,
                                        '_load_df_from_request', original))

        request = APIRequestFactory().post(
            '/api/v1/analysis/correlation/',
            {'file_id': 1, 'param_x': 'Param1', 'param_y': 'Param1'},
            format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        view = AnalysisViewSet.as_view({'post': 'correlation'})
        response = view(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data.get('n'), 4)


class CpkEndpointGuardTests(SimpleTestCase):
    """cpk 端点：stale 参数 → 400 param_not_found（与 histogram 同形）。"""

    def _post_cpk(self, params):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis.views import AnalysisViewSet, analysis_views

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0],
                           'Param1': [4.0, 5.0, 6.0]})
        datafile = types.SimpleNamespace(
            id=1, filename='fake.csv', format_type='CTA8290D')

        def fake_load(request):
            return df, datafile, _meta(), None

        original = analysis_views._load_df_from_request
        analysis_views._load_df_from_request = fake_load
        self.addCleanup(lambda: setattr(analysis_views,
                                        '_load_df_from_request', original))

        request = APIRequestFactory().post(
            '/api/v1/analysis/cpk/',
            {'file_id': 1, 'params': params}, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        view = AnalysisViewSet.as_view({'post': 'cpk'})
        response = view(request)
        response.render()
        return response

    def test_all_stale_params_return_400(self):
        response = self._post_cpk(['__bogus__'])
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'param_not_found')
        self.assertEqual(response.data.get('missing'), ['__bogus__'])

    def test_partial_stale_params_still_compute_valid_ones(self):
        response = self._post_cpk(['Param0', '__bogus__'])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('Param0', response.data.get('results', {}))
        self.assertNotIn('__bogus__', response.data.get('results', {}))

    def test_blank_params_are_filtered_before_guard(self):
        # CTA8280F 尾逗号空列名：过滤后等价于「无参数」→ 默认全列，不 400
        response = self._post_cpk(['', '   '])
        self.assertEqual(response.status_code, 200, response.content)
