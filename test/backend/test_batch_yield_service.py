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

User = get_user_model()

EXPECTED_KEYS = {
    'batch_name', 'kpi', 'phases', 'phase_summary', 'stage_yields',
    'trend_data', 'site_pass_data', 'bin_distribution', 'sorted_sites',
    'site_matrix', 'bin_table_data', 'bin_site_columns', 'uph', 'qa_checks',
}


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
        self.assertEqual(set(out.keys()), EXPECTED_KEYS)
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
