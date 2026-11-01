"""`compute_batch_yield_data` 特征化测试：锁定 payload key 集合与 404 语义。

服务从 batch_report/views.py 抽出（供 /batch-report/batch_yield_data/ API 与
HTML 报告共用）。

runner: ``manage.py test test.backend.test_batch_yield_service``
"""

from unittest import mock

import pandas as pd
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.batch_report import services as batch_services
from apps.batch_report.services import (
    compute_batch_yield_data, BatchNotAvailableError,
)
from apps.datafiles.models import DataFile
from test.backend.batch_report_fixtures import (
    JSON_RESPONSE_KEYS, PARTITION_HISTORY,
)

User = get_user_model()

# JSON 端点的**完整**响应键集合（14 把）。形状历史：D3（`d203ca1`）一度把它删成 9 把
# —— 那是契约变更；2026-10-31 这批补回 5 把**形状兼容空键**（`trend_data` /
# `site_pass_data` / `bin_distribution` / `bin_table_data` / `bin_site_columns`），
# 键回来了、值恒为空，JSON 分支一把都不计算。HTML 分支那份由
# `test_batch_report_payload.py` 钉（13 把 = 9 真实 + 4 真算分区，不带 site_pass_data）。
# 键集合常量不再本地复制一份（两份会各自漂）—— 用的就是
# ``test/backend/batch_report_fixtures.py`` 的 ``JSON_RESPONSE_KEYS`` 那一份。
EXPECTED_KEYS = JSON_RESPONSE_KEYS


def _df():
    return pd.DataFrame({
        'Site': ['S1', 'S1', 'S2', 'S2'],
        'SW_Bin': [1, 2, 1, 1],
        'P1': [1.0, 2.0, 3.0, 4.0],
    })


def _meta():
    return {'format': 'CTA8290D'}


class ComputeBatchYieldDataTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='by_user', password='pw')
        self.client.force_authenticate(self.user)
        self.mine = DataFile.objects.create(
            owner=self.user, filename='FT1.csv',
            file_path='data/by_user/batch/B1/FT1.csv', file_size=2048,
            format_type='CTA8290D', file_type='batch', batch_name='B1',
            status='ready',
        )

    def _patch_parse(self, ret):
        patcher = mock.patch.object(
            batch_services, 'get_cached_parsed_file', return_value=ret)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_payload_key_set_locked(self):
        self._patch_parse((_df(), _meta(), 'CTA8290D'))
        out = compute_batch_yield_data(self.user, 'B1')
        self.assertEqual(set(out.keys()), EXPECTED_KEYS, msg=PARTITION_HISTORY)
        self.assertEqual(out['batch_name'], 'B1')
        self.assertEqual(out['kpi']['total'], 4)
        self.assertEqual(out['kpi']['pass'], 3)

    def test_unparsable_batch_raises(self):
        self._patch_parse((None, None, None))
        with self.assertRaises(BatchNotAvailableError):
            compute_batch_yield_data(self.user, 'B1')

    def test_unknown_batch_raises(self):
        with self.assertRaises(BatchNotAvailableError):
            compute_batch_yield_data(self.user, 'NOPE')

    def test_api_maps_missing_batch_to_404(self):
        resp = self.client.get(
            '/api/v1/batch-report/batch_yield_data/', {'batch_name': 'NOPE'})
        self.assertEqual(resp.status_code, 404)

    def test_api_missing_param_returns_400(self):
        resp = self.client.get('/api/v1/batch-report/batch_yield_data/')
        self.assertEqual(resp.status_code, 400)
