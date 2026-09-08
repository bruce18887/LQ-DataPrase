"""批次 4 回归测试（2026-09-05 分析界面审查）：

1. wafer_map 与 zonal_yield 守卫对齐：stale 参数 → 400 param_not_found，
   不再静默按「全局判定」返回着色错误的晶圆图；空 param 保留全局判定。
2. serial_distribution 的 chart_config 非法输入 → 400 invalid_chart_config。
3. uph 的 manual_test_time_sec 无效值 → 降级告警而非 500（视图层裸 float() 已删）。
4. histogram 计算路径：部分无效带 skipped_params、全部无效 400 no_valid_params；
   响应补 median 字段（前端 Median 卡此前永远显示 '-'）。
5. 'CL' 哨兵三端点统一为「用户自定义限」：site_stats / serial_distribution
   携带 custom_low/high 时按自定义限判定，不再回退数据极值（旧口径下
   CL 模式 Site 表 Fail 恒 0、Yield 恒 100%）。
"""
import types

import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.data_services import (
    compute_histogram_stats,
    compute_serial_distribution_data,
)


def _meta(mins=None, maxs=None) -> dict:
    return {'format': 'CTA8290D', 'mins': mins or {}, 'maxs': maxs or {},
            'units': {}}


def _make_request_factory():
    from rest_framework.test import APIRequestFactory, force_authenticate
    return APIRequestFactory(), force_authenticate


def _authed(request, force_authenticate):
    force_authenticate(request, user=types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False))
    return request


class _PatchedDfTest(SimpleTestCase):
    """monkey-patch ``_load_df_from_request`` 的公共脚手架（addCleanup 还原）。"""

    @classmethod
    def _patch(cls, df, metadata=None):
        datafile = types.SimpleNamespace(
            id=1, filename='fake.csv', format_type='CTA8290D')
        from apps.analysis.views import analysis_views

        def fake_load(request):
            return df, datafile, metadata or _meta(), None

        original = analysis_views._load_df_from_request
        analysis_views._load_df_from_request = fake_load
        cls._restore_target = analysis_views
        cls._restore_value = original
        return datafile

    def setUp(self):
        # 每个用例结束后恢复（_patch 由用例自行调用，tearDown 兜底还原）
        self._patched = False

    def _patch_and_track(self, df, metadata=None):
        self._patched = True
        return type(self)._patch(df, metadata)

    def tearDown(self):
        if getattr(self, '_patched', False):
            self._restore_target._load_df_from_request = self._restore_value


class WaferMapParamGuardTests(_PatchedDfTest):
    """wafer_map 与 zonal_yield 守卫对齐（R3①）。"""

    def test_stale_param_returns_400(self):
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'X_COORD': [0, 1, 0, 1], 'Y_COORD': [0, 0, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5], 'SW_Bin': [1, 1, 2, 1],
        })
        self._patch_and_track(df)
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/wafer_map/', {
            'file_id': 1, 'param': '__bogus__',
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'wafer_map'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'param_not_found')

    def test_empty_param_keeps_global_judgment(self):
        # 空 param = 全局判定语义，不得被守卫误伤
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'X_COORD': [0, 1, 0, 1], 'Y_COORD': [0, 0, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5], 'SW_Bin': [1, 1, 2, 1],
        })
        self._patch_and_track(df)
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/wafer_map/', {
            'file_id': 1,
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'wafer_map'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)

    def test_param_response_carries_spec_limits(self):
        """参数值着色归一口径的数据源：真规格限原样下发。"""
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'X_COORD': [0, 1, 0, 1], 'Y_COORD': [0, 0, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5], 'SW_Bin': [1, 1, 2, 1],
        })
        self._patch_and_track(df, _meta(mins={'Param0': '0'}, maxs={'Param0': '10'}))
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/wafer_map/', {
            'file_id': 1, 'param': 'Param0',
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'wafer_map'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['spec_low'], 0.0)
        self.assertEqual(response.data['spec_high'], 10.0)

    def test_placeholder_limits_serialize_to_null(self):
        """'Min'/'Max' 占位列（无规格限语义）→ spec_low/high 为 null。"""
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'X_COORD': [0, 1, 0, 1], 'Y_COORD': [0, 0, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5], 'SW_Bin': [1, 1, 2, 1],
        })
        self._patch_and_track(df, _meta(mins={'Param0': 'Min'}, maxs={'Param0': 'Max'}))
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/wafer_map/', {
            'file_id': 1, 'param': 'Param0',
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'wafer_map'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.data['spec_low'])
        self.assertIsNone(response.data['spec_high'])

    def test_no_param_spec_fields_still_present(self):
        """未选参数时字段也在（统一契约，前端不用判键存在）。"""
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'X_COORD': [0, 1, 0, 1], 'Y_COORD': [0, 0, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5], 'SW_Bin': [1, 1, 2, 1],
        })
        self._patch_and_track(df)
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/wafer_map/', {
            'file_id': 1,
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'wafer_map'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.data['spec_low'])
        self.assertIsNone(response.data['spec_high'])


class SerialChartConfigGuardTests(_PatchedDfTest):
    """chart_config 非法输入 → 400（此前 json.loads 直接抛 → 500）。"""

    def _post(self, chart_config):
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'Serial_No': [1, 2, 3, 4], 'SW_Bin': [1, 1, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5],
        })
        self._patch_and_track(df)
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/serial_distribution/', {
            'file_id': 1, 'param': 'Param0', 'chart_config': chart_config,
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'serial_distribution'})
        response = view(request)
        response.render()
        return response

    def test_non_json_string_returns_400(self):
        response = self._post('limit')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'invalid_chart_config')

    def test_non_array_json_returns_400(self):
        response = self._post({'limit': True})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'invalid_chart_config')

    def test_valid_list_still_passes_guard(self):
        response = self._post(['limit'])
        self.assertNotEqual(response.data.get('error'), 'invalid_chart_config',
                            response.content)


class UphInvalidManualTimeTests(_PatchedDfTest):
    """manual_test_time_sec='abc' → 服务层降级告警，不再视图层 500。"""

    def test_invalid_manual_time_degrades_not_500(self):
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'Site_No': ['1', '1', '2', '2'],
            'Test_Time': ['4.1', '4.2', '4.1', '4.0'],
            'Param0': [1.0, 2.0, 1.5, 2.5],
        })
        self._patch_and_track(df)
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/uph/', {
            'file_id': 1, 'manual_test_time_sec': 'abc',
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'uph'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)


class HistogramSkippedParamsTests(_PatchedDfTest):
    """部分无效带 skipped_params；全部无效 400 no_valid_params。"""

    def test_partial_invalid_returns_skipped_params(self):
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'Param0': [1.0, 2.0, 3.0],
            'Start_T': ['a', 'b', 'c'],  # str 列：compute 返回 None
        })
        self._patch_and_track(df)
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/histogram/', {
            'file_id': 1, 'params': ['Param0', 'Start_T'],
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('Param0', response.data.get('results', {}))
        self.assertEqual(response.data.get('skipped_params'), ['Start_T'])

    def test_all_invalid_returns_400(self):
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Start_T': ['a', 'b', 'c']})
        self._patch_and_track(df)
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/histogram/', {
            'file_id': 1, 'params': ['Start_T'],
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'histogram'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'no_valid_params')

    def test_median_field_present(self):
        out = compute_histogram_stats(
            pd.DataFrame({'Param1': [1.0, 2.0, 3.0, 4.0]}),
            _meta(), 'Param1', None)
        # 前端 Median 统计卡此前永远 '-'（响应从不带该字段）
        self.assertEqual(out['median'], 2.5)


class ClCustomLimitsUnificationTests(SimpleTestCase):
    """'CL' 哨兵三端点统一为「用户自定义限」。"""

    def test_site_stats_view_uses_custom_limits(self):
        from apps.analysis.views import StatisticsViewSet
        from apps.analysis.views import analysis_views  # noqa: F401 (patch target)

        # 值 1.0/4.0：自定义限 [1.5, 3.5] → 两个超限（1.0 < LSL、4.0 > USL）；
        # 若按旧口径回退数据极值（1.0~4.0 当 LSL/USL），Fail 恒 0
        df = pd.DataFrame({
            'Site_No': ['1', '1', '2', '2'],
            'Param0': [1.0, 2.0, 3.0, 4.0],
        })
        datafile = types.SimpleNamespace(
            id=1, filename='fake.csv', format_type='CTA8290D')

        def fake_load(request):
            return df, datafile, _meta(), None

        from apps.analysis.views import statistics_views
        original = statistics_views._load_df_from_request
        statistics_views._load_df_from_request = fake_load
        self.addCleanup(lambda: setattr(statistics_views,
                                        '_load_df_from_request', original))

        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/statistics/site_stats/', {
            'file_id': 1, 'param': 'Param0', 'range_type': 'CL',
            'custom_low': 1.5, 'custom_high': 3.5,
        }, format='json'), force_authenticate)
        view = StatisticsViewSet.as_view({'post': 'site_stats'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        rows = {r['Site']: r for r in response.data.get('site_data', [])}
        self.assertEqual(rows['ALL Site']['FailCountNum'], 2)

    def test_serial_distribution_uses_custom_limits(self):
        df = pd.DataFrame({
            'Serial_No': [1, 2, 3, 4],
            'SW_Bin': [1, 1, 1, 1],
            'Param0': [1.0, 2.0, 3.0, 4.0],
        })
        result = compute_serial_distribution_data(
            df, _meta(), 'Param0', 'CL', ['limit'],
            custom_low=1.5, custom_high=3.5)
        # markLine 的规格限 = 自定义限（而非数据极值 1.0/4.0）
        lsl = result['marks'][0]['markLine']['data'][0]['yAxis']
        usl = result['marks'][0]['markLine']['data'][1]['yAxis']
        self.assertEqual(lsl, 1.5)
        self.assertEqual(usl, 3.5)

    def test_serial_distribution_without_custom_falls_back_to_data_range(self):
        df = pd.DataFrame({
            'Serial_No': [1, 2, 3, 4],
            'SW_Bin': [1, 1, 1, 1],
            'Param0': [1.0, 2.0, 3.0, 4.0],
        })
        result = compute_serial_distribution_data(df, _meta(), 'Param0', 'CL', ['limit'])
        lsl = result['marks'][0]['markLine']['data'][0]['yAxis']
        usl = result['marks'][0]['markLine']['data'][1]['yAxis']
        self.assertEqual(lsl, 1.0)
        self.assertEqual(usl, 4.0)


class DtypeWhitelistTests(SimpleTestCase):
    """file_correlation 的 _numeric_params 对窄整型/浮点不得漏列。"""

    def test_narrow_dtypes_included_bool_excluded(self):
        from apps.analysis.services.file_correlation import _numeric_params

        df = pd.DataFrame({
            'Param_i32': pd.array([1, 2, 3], dtype='int32'),
            'Param_f32': pd.array([1.0, 2.0, 3.0], dtype='float32'),
            'Dut_Pass': [True, False, True],
            'Start_T': pd.array(['a', 'b', 'c'], dtype='str'),
        })
        got = _numeric_params(df)
        self.assertIn('Param_i32', got)
        self.assertIn('Param_f32', got)
        self.assertNotIn('Dut_Pass', got)
        self.assertNotIn('Start_T', got)
