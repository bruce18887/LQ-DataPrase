"""T1：直方图 KDE 内存降级（``degraded``）的可见上报契约。

KDE 要把全量数据喂给 scipy 再采样 200 点网格，内存吃紧时 ``MemoryError`` 会把
整个 ``/analysis/histogram/`` 拖成 500，前端只看到「图表区域空白」。加一条
``degraded`` 通道后：带该参数（list）的调用把「哪条曲线没画出来」记进响应，
曲线退成 ``None``，前端据此提示降级；不带该参数的老调用（multi_lot / 导出）
保持原样抛错 —— 那两条链路上没有人会读这个字段。

判据分层（testing-gates §2）：纯函数口径 + 视图接线都落在 T1，用
``SimpleTestCase`` —— ``manage.py test`` 只收集 unittest.TestCase。

Run:  python manage.py test test.backend.test_histogram_degraded
"""
import json
import os
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from django.test import SimpleTestCase  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

from apps.analysis import test_support  # noqa: E402
from apps.analysis.services.data_services import histogram as histogram_module  # noqa: E402
from apps.analysis.services.data_services.histogram import (  # noqa: E402
    compute_histogram_stats,
    compute_kde_curve,
)
from apps.analysis.test_support import fake_datafile  # noqa: E402
from apps.analysis.views import analysis_views as analysis_views_module  # noqa: E402
from apps.analysis.views import AnalysisViewSet  # noqa: E402

PARAM = 'lkg_VCC_EN_float_3P6V'
# 多参数隔离用例的第二个参数：视图在所有参数间共用过同一个 degraded list，
# 必须能证明 A 的降级项不会串到 B 上。
PARAM_B = 'lkg_VCC_EN_float_3P6V_B'
METADATA = {
    'mins': {PARAM: '8.0'},
    'maxs': {PARAM: '14.3'},
    'units': {PARAM: 'uA'},
    'format': 'CTA8280F',
}
METADATA_TWO_PARAMS = {
    'mins': {PARAM: '8.0', PARAM_B: '8.0'},
    'maxs': {PARAM: '14.3', PARAM_B: '14.3'},
    'units': {PARAM: 'uA', PARAM_B: 'uA'},
    'format': 'CTA8280F',
}


def _df(vals):
    return pd.DataFrame({PARAM: vals})


def _clean_vals():
    """确定性无异常值样本：均匀铺开 9~13，落在规格限内（IQR 判不出异常值）。"""
    return np.linspace(9.0, 13.0, 500)


def _vals_with_outliers():
    """确定性样本 + 20 个 30.0（远超展开后的上界 15 → IQR 必然判异常值）。"""
    return np.concatenate([_clean_vals(), [30.0] * 20])


def _fake_user():
    return types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False, settings=None,
    )


class ComputeKdeCurveDegradedTests(SimpleTestCase):
    """``compute_kde_curve`` 自身的降级开关：只捕获 MemoryError。"""

    def _curve(self, **kwargs):
        return compute_kde_curve(pd.Series([1.0, 2.0, 3.0, 4.0]), 0.0, 5.0, **kwargs)

    def test_memory_error_appends_default_reason(self):
        degraded = []
        with mock.patch.object(histogram_module, 'GaussianKDE', side_effect=MemoryError):
            curve = self._curve(degraded=degraded)
        self.assertIsNone(curve)
        self.assertEqual(degraded, ['kde_curve'])

    def test_memory_error_appends_custom_reason(self):
        degraded = []
        with mock.patch.object(histogram_module, 'GaussianKDE', side_effect=MemoryError):
            curve = self._curve(degraded=degraded, reason='filtered_kde_curve')
        self.assertIsNone(curve)
        self.assertEqual(degraded, ['filtered_kde_curve'])

    def test_memory_error_reraises_without_degraded(self):
        """multi_lot / 导出不传 degraded：必须继续抛，不能被静默吞掉。"""
        with mock.patch.object(histogram_module, 'GaussianKDE', side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                self._curve()

    def test_non_memory_exceptions_keep_old_behavior(self):
        """只有 MemoryError 走降级；其它异常仍按旧口径返回 None（不记 reason）。"""
        degraded = []
        with mock.patch.object(histogram_module, 'GaussianKDE', side_effect=RuntimeError('boom')):
            curve = self._curve(degraded=degraded)
        self.assertIsNone(curve)
        self.assertEqual(degraded, [])


class ComputeHistogramStatsDegradedTests(SimpleTestCase):
    """``compute_histogram_stats`` 透传 degraded，并在返回体里恒带该键。"""

    def test_kde_memory_error_marks_curve_none_and_records_reason(self):
        degraded = []
        with mock.patch.object(histogram_module, 'compute_kde_curve',
                               side_effect=MemoryError):
            r = compute_histogram_stats(_df(_clean_vals()), METADATA, PARAM, None,
                                        range_type='RDL', degraded=degraded)
        self.assertEqual(r['degraded'], ['kde_curve'])
        self.assertIsNone(r['kde_curve'])

    def test_filtered_kde_memory_error_records_own_reason(self):
        """raw 曲线算成功、filtered 曲线炸：reason 必须指向 filtered 那条。"""
        degraded = []
        with mock.patch.object(histogram_module, 'compute_kde_curve',
                               side_effect=[[[0.0, 1.0]], MemoryError]) as patched:
            r = compute_histogram_stats(_df(_vals_with_outliers()), METADATA, PARAM, None,
                                        range_type='DR', degraded=degraded)
        self.assertEqual(patched.call_count, 2)
        self.assertEqual(r['kde_curve'], [[0.0, 1.0]])
        self.assertIsNone(r['filtered_kde_curve'])
        self.assertEqual(r['degraded'], ['filtered_kde_curve'])

    def test_memory_error_reraises_when_degraded_not_requested(self):
        with mock.patch.object(histogram_module, 'compute_kde_curve',
                               side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                compute_histogram_stats(_df(_clean_vals()), METADATA, PARAM, None,
                                        range_type='RDL')

    def test_healthy_path_carries_empty_degraded_list(self):
        r = compute_histogram_stats(_df(_clean_vals()), METADATA, PARAM, None,
                                    range_type='RDL', degraded=[])
        self.assertEqual(r['degraded'], [])
        self.assertIsNotNone(r['kde_curve'])
        # 不传 degraded 也必须带这个键（契约稳定：前端可直接读，不必判存在）
        r2 = compute_histogram_stats(_df(_clean_vals()), METADATA, PARAM, None,
                                     range_type='RDL')
        self.assertEqual(r2['degraded'], [])

    def test_filtered_variant_without_outliers_reports_raw_reason(self):
        """``kde_variant='filtered'`` 但无异常值 → 回退算全量那条，reason 是 raw。"""
        degraded = []
        with mock.patch.object(histogram_module, 'compute_kde_curve',
                               side_effect=MemoryError) as patched:
            r = compute_histogram_stats(_df(_clean_vals()), METADATA, PARAM, None,
                                        range_type='RDL', kde_variant='filtered',
                                        degraded=degraded)
        self.assertEqual(patched.call_count, 1)
        self.assertEqual(r['degraded'], ['kde_curve'])
        self.assertIsNone(r['kde_curve'])
        self.assertIsNone(r['filtered_kde_curve'])

    def test_both_curves_degraded_record_both_reasons_in_compute_order(self):
        """两条曲线都降级：reason 按计算顺序（raw 先、filtered 后）各一条。"""
        degraded = []
        with mock.patch.object(histogram_module, 'compute_kde_curve',
                               side_effect=MemoryError):
            r = compute_histogram_stats(_df(_vals_with_outliers()), METADATA,
                                        PARAM, None, range_type='DR',
                                        degraded=degraded)
        self.assertEqual(r['degraded'], ['kde_curve', 'filtered_kde_curve'])
        self.assertIsNone(r['kde_curve'])
        self.assertIsNone(r['filtered_kde_curve'])


class HistogramViewDegradedTests(SimpleTestCase):
    """视图接线：每个参数各自的 degraded list，结果原样带进响应 JSON。"""

    def _post(self, payload, df=None, metadata=None):
        restore = test_support.patch_df_loader(
            df if df is not None else _df(_clean_vals()),
            fake_datafile(),
            metadata if metadata is not None else METADATA)
        try:
            request = APIRequestFactory().post(
                '/api/v1/analysis/histogram/', dict(payload), format='json')
            force_authenticate(request, user=_fake_user())
            response = AnalysisViewSet.as_view({'post': 'histogram'})(request)
            response.render()
            return response
        finally:
            restore()

    def test_kde_memory_error_surfaces_in_response_json(self):
        with mock.patch.object(histogram_module, 'compute_kde_curve',
                               side_effect=MemoryError):
            response = self._post({'file_id': 1, 'params': [PARAM]})
        self.assertEqual(response.status_code, 200, response.content[:400])
        body = json.loads(response.content)
        result = body['results'][PARAM]
        self.assertEqual(result['degraded'], ['kde_curve'])
        self.assertIsNone(result['kde_curve'])

    def test_view_does_not_strip_service_degraded_field(self):
        fake_result = {'kde_curve': None, 'degraded': ['kde_curve']}
        with mock.patch.object(analysis_views_module, 'compute_histogram_stats',
                               return_value=fake_result):
            response = self._post({'file_id': 1, 'params': [PARAM]})
        self.assertEqual(response.status_code, 200, response.content[:400])
        body = json.loads(response.content)
        self.assertEqual(body['results'][PARAM]['degraded'], ['kde_curve'])

    def test_degraded_reasons_are_isolated_per_param(self):
        """A 降级、B 正常：B 不能沾到 A 的 reason（也不能靠重复项暴露共用 list）。"""
        two_param_df = pd.DataFrame({PARAM: _clean_vals(),
                                     PARAM_B: _clean_vals()})
        healthy_curve = [[0.0, 1.0]]
        with mock.patch.object(histogram_module, 'compute_kde_curve',
                               side_effect=[MemoryError, healthy_curve]):
            response = self._post({'file_id': 1, 'params': [PARAM, PARAM_B]},
                                  df=two_param_df, metadata=METADATA_TWO_PARAMS)
        self.assertEqual(response.status_code, 200, response.content[:400])
        results = json.loads(response.content)['results']
        self.assertEqual(results[PARAM]['degraded'], ['kde_curve'])
        self.assertIsNone(results[PARAM]['kde_curve'])
        self.assertEqual(results[PARAM_B]['degraded'], [])
        self.assertEqual(results[PARAM_B]['kde_curve'], healthy_curve)
