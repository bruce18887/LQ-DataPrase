"""Batch report ``generate_report`` 参数校验缺陷回归测试（缺陷 #8）。

原实现用 ``DataFile.objects.get(pk=fid, owner=request.user)``：
- 文件不存在 / 不属于当前用户 → ``DoesNotExist`` → 500；
- ``fid`` 非整数（``'abc'``）→ ``ValueError`` → 500。

buyoff / gage 等同类端点都用 ``get_object_or_404``（404），同一类参数一处 404
一处 500。修复口径：``fid`` 非整数 → 400；查不到 → 404。

runner: ``manage.py test test.backend.test_batch_report_generate``
"""

from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.batch_report import views as batch_views
from apps.datafiles.models import DataFile

User = get_user_model()

URL = '/api/v1/batch-report/generate_report/'


class GenerateReportFileIdTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='br_fid', password='pw')
        self.other = User.objects.create_user(username='br_other', password='pw')
        self.client.force_authenticate(self.user)
        self.mine = DataFile.objects.create(
            owner=self.user, filename='FT1.csv',
            file_path='data/br_fid/batch/B1/FT1.csv', file_size=2048,
            format_type='CTA8290D', file_type='batch', batch_name='B1',
            status='ready',
        )
        self.theirs = DataFile.objects.create(
            owner=self.other, filename='FT2.csv',
            file_path='data/br_other/batch/B1/FT2.csv', file_size=2048,
            format_type='CTA8290D', file_type='batch', batch_name='B1',
            status='ready',
        )
        # 解析一律失败（df is None）→ 视图跳过，仍走到出表分支；
        # 这样测试聚焦在 fid 校验语义上，不依赖真实 CSV。
        patcher = mock.patch.object(
            batch_views, 'get_cached_parsed_file',
            return_value=(None, None, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_non_integer_file_id_returns_400(self):
        resp = self.client.post(URL, {'file_ids': ['abc']}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))

    def test_mixed_valid_and_non_integer_returns_400(self):
        resp = self.client.post(
            URL, {'file_ids': [self.mine.id, 'not-a-number']}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))

    def test_null_file_id_returns_400(self):
        resp = self.client.post(URL, {'file_ids': [None]}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))

    def test_missing_file_returns_404(self):
        resp = self.client.post(URL, {'file_ids': [987654]}, format='json')
        self.assertEqual(resp.status_code, 404, getattr(resp, 'data', resp))

    def test_other_users_file_returns_404(self):
        resp = self.client.post(URL, {'file_ids': [self.theirs.id]}, format='json')
        self.assertEqual(resp.status_code, 404, getattr(resp, 'data', resp))

    def test_empty_file_ids_returns_400(self):
        resp = self.client.post(URL, {'file_ids': []}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_valid_file_id_still_returns_200(self):
        """正向对照：合法 fid 不得因新校验被误伤。"""
        resp = self.client.post(URL, {'file_ids': [self.mine.id]}, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertIn('spreadsheetml', resp['Content-Type'])

    def test_numeric_string_file_id_accepted(self):
        resp = self.client.post(URL, {'file_ids': [str(self.mine.id)]},
                                format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
