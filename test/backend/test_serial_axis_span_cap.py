"""B3：连续序列轴的跨度上限 k=2（用户 2026-11-01 拍板）。

整数序列号目前无条件展开成 ``range(min, max+1)``：序列号是 1 与 1,000,000 这种
稀疏编号时，一次生成百万长度的轴。规则：跨度 > 2×实有序列数就退回**已有的**
「原值集合」路径（不展开、点按原值匹配）。稠密序列号的轴形状必须一字不变。

runner: ``python -X utf8 manage.py test test.backend.test_serial_axis_span_cap``
"""
import types

import pandas as pd
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.analysis.test_support import fake_datafile, patch_df_loader

METADATA = {
    'format': 'CTA8280F',
    'mins': {'PARAM_A': '0'},
    'maxs': {'PARAM_A': '10'},
    'units': {'PARAM_A': 'V'},
}


class SerialAxisSpanCapTests(SimpleTestCase):
    def _post(self, serials):
        df = pd.DataFrame({
            'Site_No': [1] * len(serials),
            'SW_Bin': [1] * len(serials),
            'Serial_No': serials,
            'PARAM_A': [1.0 + i * 0.01 for i in range(len(serials))],
        })
        restore = patch_df_loader(df, fake_datafile(format_type='CTA8280F'), METADATA)
        self.addCleanup(restore)
        request = APIRequestFactory().post(
            '/api/v1/analysis/serial_distribution/',
            {'file_id': 1, 'param': 'PARAM_A'}, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        from apps.analysis.views import AnalysisViewSet
        resp = AnalysisViewSet.as_view({'post': 'serial_distribution'})(request)
        resp.render()
        return resp

    def test_dense_serials_still_fill_the_gaps(self):
        """稠密序列号（含小缺口）仍走连续轴：1,2,4 ⇒ 1..4，形状不变。"""
        body = self._post([1, 2, 4]).data
        self.assertEqual(body['continuous_serials'], [1, 2, 3, 4])

    def test_exactly_at_the_factor_is_still_continuous(self):
        """边界：1,3,6 的跨度 6 = 2×3，不超限 ⇒ 仍展开。"""
        body = self._post([1, 3, 6]).data
        self.assertEqual(body['continuous_serials'], [1, 2, 3, 4, 5, 6])

    def test_sparse_serials_fall_back_to_the_value_set(self):
        """跨度 1,000,000 > 2×2 ⇒ 原值集合，绝不生成百万长度的轴。"""
        body = self._post([1, 1000000]).data
        self.assertEqual(body['continuous_serials'], [1, 1000000])

    def test_fallback_keeps_every_die_point(self):
        """降级只改轴，不丢点：两颗 die 仍然各有一个序列点。"""
        body = self._post([1, 1000000]).data
        total = sum(len(s['data']) for s in body['series_data'])
        self.assertEqual(total, 2, '降级把 die 点弄丢了')
        self.assertEqual(body['pass_count'] + body['fail_count'], 2)

    def test_just_past_the_boundary_falls_back(self):
        """1,3,7：跨度 7 > 2×3 ⇒ 降级；三颗 die 的点仍在。"""
        body = self._post([1, 3, 7]).data
        self.assertEqual(body['continuous_serials'], [1, 3, 7])
        self.assertEqual(sum(len(s['data']) for s in body['series_data']), 3)
