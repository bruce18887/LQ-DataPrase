"""B8：同步重活导出端点已移除，唯一入口是作业池。

``/export/to_excel/`` 与 ``/export/batch_charts/`` 会绕过作业池，在请求线程里
``_pick_workers`` 缺省 spawn ``min(8, cpu)`` 个进程，且不排队、不可取消。
删除后同一路径不得再返回 2xx —— 前端与 ``scripts/perf_load20.py`` 都改走
``/jobs/export_excel/`` / ``/jobs/export_batch_charts/``。
"""
import os
import unittest

from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.datafiles.models import DataFile

SAMPLE_DATA_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', 'Data', 'SampleData')
GAGE_S1_PATH = os.path.join(SAMPLE_DATA_DIR, 'Gage', 'gage_m_S1.csv')


@unittest.skipUnless(
    os.path.exists(GAGE_S1_PATH),
    'SampleData/Gage 目录不存在（跳过）',
)
class LegacyExportEndpointsRemovedTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='legacy', password='pw')
        self.client.force_authenticate(self.user)
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename='gage_m_S1.csv',
            file_path=GAGE_S1_PATH,
            file_size=os.path.getsize(GAGE_S1_PATH),
            format_type='CTA8290D',
            status='ready',
        )

    def assert_not_served(self, resp):
        self.assertIn(resp.status_code, (404, 405),
                      f'旧同步端点仍在服务（{resp.status_code}），重活必须只走作业池')

    def test_to_excel_endpoint_is_gone(self):
        resp = self.client.post(
            '/api/v1/export/to_excel/', {'file_id': self.datafile.id})
        self.assert_not_served(resp)

    def test_batch_charts_endpoint_is_gone(self):
        resp = self.client.post(
            '/api/v1/export/batch_charts/',
            {'file_id': self.datafile.id, 'params': []}, format='json')
        self.assert_not_served(resp)

    def test_jobs_replacements_are_still_routed(self):
        """防误删：删的是同步旧端点，作业入口必须仍在（JSON 404 = 路由命中、文件不存在）。"""
        for path in ('/api/v1/jobs/export_excel/',
                     '/api/v1/jobs/export_batch_charts/'):
            with self.subTest(path=path):
                resp = self.client.post(path, {'file_id': 999999}, format='json')
                self.assertEqual(resp.status_code, 404, path)
                self.assertTrue(
                    resp['Content-Type'].startswith('application/json'), path)
                self.assertEqual(resp.json().get('code'), 'not_found', path)
