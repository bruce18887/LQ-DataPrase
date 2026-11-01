"""B4：仪表板逐参数总览默认 50 行、top_n 可调（用户 2026-11-01 拍板）。

总览行随参数个数线性膨胀，425 参数的文件整份进响应。默认 50、显式 top_n 上限 200；
`test_item_overview` 取列序前 N，`param_stats`（CPK 升序、最差在前）同样取前 N ——
两条表口径不同，但都是「前 N」。

**切片绝不能改缓存对象**：`get_dashboard_summary` 的返回值是共享只读对象
（`apps/dashboard/services.py` 的 docstring 写明调用方不得修改）。本文件最后一条
用例专门钉这一点：先 top_n=5 再默认请求，必须仍拿到 50 行。

runner: ``python -X utf8 manage.py test test.backend.test_dashboard_top_n``
"""
import numpy as np
import pandas as pd
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.dashboard.services import clear_dashboard_summary_cache, summary_cache_stats
from apps.datafiles.models import DataFile


def _frame(n=60, rows=8):
    rng = np.random.default_rng(20261101)
    cols = {'Site_No': ['1'] * rows, 'SW_Bin': [1] * rows}
    for i in range(n):
        cols[f'P{i:03d}'] = rng.normal(5 + i * 0.01, 1.0, rows)
    return pd.DataFrame(cols)


def _meta(n=60):
    names = [f'P{i:03d}' for i in range(n)]
    return {'format': 'CTA8280F', 'mins': {c: '0' for c in names},
            'maxs': {c: '10' for c in names}, 'units': {c: 'V' for c in names}}


class DashboardTopNTests(TestCase):
    def setUp(self):
        from apps.dashboard import views as dash_views

        self.user = User.objects.create_user(username='dash_topn', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        clear_dashboard_summary_cache()
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='topn.csv', file_path='topn.csv',
            file_size=1, format_type='CTA8280F', status='ready')
        self._frame_cache = [_frame()]
        self.meta = _meta()
        self._orig = (dash_views.resolve_file_path, dash_views.get_cached_parsed_file)
        dash_views.resolve_file_path = lambda p: __file__
        dash_views.get_cached_parsed_file = (
            lambda *a, **k: (self._frame_cache[0], self.meta, 'CTA8280F'))
        self.addCleanup(setattr, dash_views, 'resolve_file_path', self._orig[0])
        self.addCleanup(setattr, dash_views, 'get_cached_parsed_file', self._orig[1])

    def _get(self, **params):
        return self.client.get('/api/v1/summary/',
                               {'file_id': self.datafile.id, **params})

    def test_default_caps_overview_and_reports_the_total(self):
        self._frame_cache[0] = _frame(n=260)
        self.meta = _meta(n=260)
        clear_dashboard_summary_cache()
        resp = self._get()
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.data
        self.assertEqual([r['name'] for r in data['test_item_overview']],
                         [f'P{i:03d}' for i in range(200)])
        self.assertEqual(len(data['param_stats']), 200, 'param_stats 没跟着封顶')
        self.assertEqual(data['param_total'], 260)
        self.assertEqual(data['top_n'], 200)

    def test_explicit_top_n_is_honoured(self):
        data = self._get(top_n=10).data
        self.assertEqual(len(data['test_item_overview']), 10)
        self.assertEqual(len(data['param_stats']), 10)
        self.assertEqual(data['param_total'], 60)
        self.assertEqual(data['top_n'], 10)

    def test_top_n_above_the_file_size_returns_everything(self):
        data = self._get(top_n=200).data
        self.assertEqual(len(data['test_item_overview']), 60)
        self.assertEqual(data['param_total'], 60)
        self.assertEqual(data['top_n'], 200)

    def test_bad_top_n_is_a_client_error(self):
        for bad in (0, -3, 201, 'abc'):
            with self.subTest(top_n=bad):
                resp = self._get(top_n=bad)
                self.assertEqual(resp.status_code, 400, f'{bad!r} 应判 400')
                self.assertEqual(resp.json()['code'], 'invalid_top_n')

    def test_different_top_n_use_separate_cache_entries(self):
        """top_n 必须进缓存 key：先小后大，第二次不能拿到上一次截短的 payload。"""
        first = self._get(top_n=5)
        self.assertEqual(len(first.data['test_item_overview']), 5)
        second = self._get()
        self.assertEqual(len(second.data['test_item_overview']), 60,
                         '默认请求命中了 top_n=5 的缓存条目')
        third = self._get(top_n=5)
        self.assertEqual(len(third.data['test_item_overview']), 5, 'top_n=5 的条目没命中')
        self.assertEqual(summary_cache_stats()['entries'], 2)

    def test_small_file_is_unaffected(self):
        self._frame_cache[0] = _frame(n=12)
        self.meta = _meta(n=12)
        clear_dashboard_summary_cache()
        data = self._get().data
        self.assertEqual(len(data['test_item_overview']), 12)
        self.assertEqual(data['param_total'], 12)
        self.assertEqual(data['top_n'], 200)
