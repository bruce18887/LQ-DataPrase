"""批次 HTML 报告内容测试：KPI、分区块、base64 图表、命名、404 语义。

runner: ``manage.py test test.backend.test_html_report_batch``
"""

from unittest import mock

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.batch_report import services as batch_services
from apps.datafiles.models import DataFile

User = get_user_model()

HTML_URL = '/api/v1/batch-report/batch_html_report/'


def _df():
    return pd.DataFrame({
        'SW_Bin': [1, 1, 2, 1],
        'Site': ['S1', 'S1', 'S2', 'S2'],
        'V1': [1.0, 2.0, 3.0, 4.0],
    })


def _meta():
    return {'format': 'CTA8290D'}


class BatchHtmlReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bhr_user', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.mine = DataFile.objects.create(
            owner=self.user, filename='FT1.csv',
            file_path='data/bhr_user/batch/B1/FT1.csv', file_size=2048,
            format_type='CTA8290D', file_type='batch', batch_name='B1',
            status='ready',
        )
        patcher = mock.patch.object(
            batch_services, 'get_cached_parsed_file',
            return_value=(_df(), _meta(), 'CTA8290D'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_has_kpi_and_charts(self):
        resp = self.client.post(HTML_URL, {'batch_name': 'B1'}, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        html = b''.join(resp.streaming_content).decode('utf-8')
        self.assertIn('data-field="file_count"', html)
        self.assertIn('阶段汇总', html)
        self.assertIn('data:image/png;base64,', html, '批次报告应内联 base64 图表')

    def test_filename_is_html(self):
        resp = self.client.post(HTML_URL, {'batch_name': 'B1'}, format='json')
        cd = resp['Content-Disposition']
        self.assertIn('Batch_Report', cd)
        self.assertIn('.html', cd)

    def test_missing_batch_name_returns_400(self):
        resp = self.client.post(HTML_URL, {}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_unknown_batch_returns_404(self):
        resp = self.client.post(HTML_URL, {'batch_name': 'NOPE'}, format='json')
        self.assertEqual(resp.status_code, 404)
