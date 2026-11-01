"""B2：相关矩阵的参数上限 k=50（用户 2026-11-01 拍板：按列序截断 + 回标记）。

默认参数集是「全部带规格限列」，425 参数的文件会生成 425×425 的矩阵并整体序列化。
上限只作用在**即将进计算**的那份 params 上：总量（`total_params`）与 `truncated`
必须让前端知道「你看到的不是全部」。显式选择同样受上限约束，且截断按**请求顺序**
（列序），不是字典序 —— 否则用户选的前 50 个会被悄悄换掉。

runner: ``python -X utf8 manage.py test test.backend.test_correlation_param_cap``
"""
import types

import numpy as np
import pandas as pd
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.analysis.test_support import fake_datafile, patch_df_loader

LIMIT = 50


def _frame(n):
    rng = np.random.default_rng(20261101)
    return pd.DataFrame({f'P{i:03d}': rng.normal(size=40) for i in range(n)})


def _metadata(n):
    names = [f'P{i:03d}' for i in range(n)]
    return {'format': 'CTA8290D', 'mins': {c: '0' for c in names},
            'maxs': {c: '10' for c in names}, 'units': {c: 'V' for c in names}}


class CorrelationParamCapTests(SimpleTestCase):
    def _post(self, payload, n=60):
        from apps.analysis.views.statistics_views import StatisticsViewSet

        restore = patch_df_loader(_frame(n), fake_datafile(), _metadata(n))
        self.addCleanup(restore)
        request = APIRequestFactory().post(
            '/api/v1/statistics/correlation_matrix/', payload, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        resp = StatisticsViewSet.as_view({'post': 'correlation_matrix'})(request)
        resp.render()
        return resp

    def test_default_param_set_is_capped_and_flagged(self):
        resp = self._post({'file_id': 1}, n=60)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.data
        self.assertEqual(list(data['params']), [f'P{i:03d}' for i in range(LIMIT)])
        self.assertEqual(len(data['matrix']), LIMIT, '矩阵没有跟着截断')
        self.assertEqual(data['total_params'], 60)
        self.assertIs(data['truncated'], True)

    def test_small_param_set_is_not_flagged(self):
        data = self._post({'file_id': 1}, n=12).data
        self.assertEqual(len(data['params']), 12)
        self.assertEqual(data['total_params'], 12)
        self.assertIs(data['truncated'], False)

    def test_exactly_at_the_limit_is_not_truncated(self):
        data = self._post({'file_id': 1}, n=LIMIT).data
        self.assertEqual(len(data['params']), LIMIT)
        self.assertEqual(data['total_params'], LIMIT)
        self.assertIs(data['truncated'], False)

    def test_explicit_params_are_truncated_in_request_order(self):
        n = 55
        requested = [f'P{i:03d}' for i in range(n)][::-1]
        data = self._post({'file_id': 1, 'params': requested}, n=n).data
        self.assertEqual(list(data['params']), requested[:LIMIT])
        self.assertEqual(data['total_params'], n)
        self.assertIs(data['truncated'], True)

    def test_response_keeps_the_computed_payload_keys(self):
        """只加两个标记键：既有消费方读的 params/matrix/sample_size/method 一个不少。"""
        data = self._post({'file_id': 1}, n=6).data
        for key in ('params', 'matrix', 'sample_size', 'method', 'total_params', 'truncated',
                    'file_id', 'filename'):
            self.assertIn(key, data)
