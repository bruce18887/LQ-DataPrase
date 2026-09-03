"""Buyoff ``generate_form`` 缺陷回归测试。

覆盖缺陷清单：
1. ``views.generate_form`` 在 ``datasets`` 为空时直接 ``all_col_sets[0]`` →
   IndexError → 500；应与兄弟端点 ``identify_common_items`` 一致返回 400。
2. ``only_bin1`` 用 ``pd.to_numeric(...) == 1`` 过滤，对 ``'Bin1'`` / ``'BIN 1'``
   这类**文本** bin 列会把整个 DataFrame 清空；应改用
   ``apps.analysis.services.statistics.filter_bin1_rows``。

runner: ``manage.py test test.backend.test_buyoff_generate_form``
"""

from unittest import mock

import pandas as pd
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.buyoff import views as buyoff_views
from apps.datafiles.models import DataFile

User = get_user_model()

URL = '/api/v1/buyoff/generate_form/'

METADATA = {
    'format': 'CTA8290D',
    'units': {'V_R': 'mV'},
    'mins': {'V_R': '0.5'},
    'maxs': {'V_R': '1.5'},
}


def _make_df(bin_values, param='V_R'):
    """构造带 Bin 列的最小 DataFrame（bin_values 原样保留 dtype）。"""
    return pd.DataFrame({
        'SW_Bin': list(bin_values),
        'Site': [1] * len(bin_values),
        param: [1.0 + i * 0.01 for i in range(len(bin_values))],
    })


class _BuyoffApiBase(APITestCase):
    """两个归属当前用户的 DataFile 行 + 解析结果 monkey-patch 脚手架。"""

    def setUp(self):
        self.user = User.objects.create_user(username='bo_guard', password='pw')
        self.client.force_authenticate(self.user)
        self.files = [
            DataFile.objects.create(
                owner=self.user, filename=f'FT{i + 1}.csv',
                file_path=f'data/bo_guard/single/FT{i + 1}.csv',
                file_size=1024, format_type='CTA8290D',
                file_type='single', status='ready',
            )
            for i in range(2)
        ]

    def _patch_parse(self, side_effect):
        """patch **实际消费模块** 的绑定（apps.buyoff.views）。"""
        patcher = mock.patch.object(
            buyoff_views, 'get_cached_parsed_file', side_effect=side_effect)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _capture_layout(self):
        """拦截 build_buyoff_form，捕获视图算好的 datasets/all_stats。"""
        captured = {}

        def _recorder(f, role_mapping, common_items, all_stats, datasets,
                      ordered_roles):
            captured.update({
                'datasets': datasets, 'all_stats': all_stats,
                'common_items': common_items, 'role_mapping': role_mapping,
            })

        patcher = mock.patch.object(
            buyoff_views, 'build_buyoff_form', _recorder)
        patcher.start()
        self.addCleanup(patcher.stop)
        return captured


class EmptyDatasetsGuardTests(_BuyoffApiBase):
    """缺陷 #1：所有文件解析失败（df is None）时不得 500。"""

    def test_all_files_unparsable_returns_400(self):
        self._patch_parse(lambda *a, **k: (None, None, None))
        resp = self.client.post(
            URL, {'file_ids': [f.id for f in self.files]}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertEqual(resp.data['error'], 'parse_failed')

    def test_sibling_endpoint_already_guards(self):
        """对照：identify_common_items 早已有守卫（复制时漏改的是 generate_form）。"""
        self._patch_parse(lambda *a, **k: (None, None, None))
        resp = self.client.post(
            '/api/v1/buyoff/identify_common_items/',
            {'file_ids': [f.id for f in self.files]}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'parse_failed')

    def test_partial_parse_failure_still_generates(self):
        """只有一个文件解析失败 → 剩余文件不足 2 个也应给出明确 400/200，不 500。"""
        df = _make_df([1, 1, 2])
        results = iter([(df, dict(METADATA), 'CTA8290D'), (None, None, None)])
        self._patch_parse(lambda *a, **k: next(results))
        captured = self._capture_layout()
        resp = self.client.post(
            URL, {'file_ids': [f.id for f in self.files]}, format='json')
        # 单文件仍可出表（common_items 取该文件数值列）；关键是不得 500
        self.assertIn(resp.status_code, (200, 400), getattr(resp, 'data', resp))
        if resp.status_code == 200:
            self.assertEqual(len(captured['datasets']), 1)


class TextBinOnlyBin1Tests(_BuyoffApiBase):
    """缺陷 #2：文本 Bin 列（'Bin1' / 'BIN 1'）不能被整表清空。"""

    def test_only_bin1_keeps_text_bin1_rows(self):
        df = _make_df(['Bin1', 'BIN 1', 'Bin7', '1'])
        self._patch_parse(lambda *a, **k: (df.copy(), dict(METADATA), 'CTA8290D'))
        captured = self._capture_layout()

        resp = self.client.post(
            URL, {'file_ids': [f.id for f in self.files], 'only_bin1': True},
            format='json')

        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertTrue(captured, 'build_buyoff_form 应被调用')
        for fname, ds in captured['datasets'].items():
            self.assertEqual(
                len(ds['df']), 3,
                f'{fname}: 文本 Bin1 行应被保留（Bin1 / BIN 1 / 1），'
                f'实际只剩 {len(ds["df"])} 行')

    def test_only_bin1_drops_fail_rows(self):
        """正向对照：fail 行（Bin7 / Bin2）必须被剔除。"""
        df = _make_df([1, 7, 'Bin1', 2, 'Bin 1'])
        self._patch_parse(lambda *a, **k: (df.copy(), dict(METADATA), 'CTA8290D'))
        captured = self._capture_layout()

        resp = self.client.post(
            URL, {'file_ids': [f.id for f in self.files], 'only_bin1': True},
            format='json')

        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        for ds in captured['datasets'].values():
            self.assertEqual(len(ds['df']), 3)

    def test_only_bin1_without_bin_column_keeps_all_rows(self):
        """无 Bin 列的文件：开关被忽略（filter_bin1_rows 语义），不得清空。"""
        df = pd.DataFrame({'Site': [1, 2, 3], 'V_R': [1.0, 1.1, 1.2]})
        self._patch_parse(lambda *a, **k: (df.copy(), dict(METADATA), 'CTA8290D'))
        captured = self._capture_layout()

        resp = self.client.post(
            URL, {'file_ids': [f.id for f in self.files], 'only_bin1': True},
            format='json')

        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        for ds in captured['datasets'].values():
            self.assertEqual(len(ds['df']), 3)
