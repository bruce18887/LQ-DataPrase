"""GET /api/v1/files/usage/ 的端点契约（T1）。

Run directly: .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_files_usage_api
造树方式与 test_batch_dir_traversal.py:68-72 同一种：临时 MEDIA_ROOT + override_settings，
树本身用 os.makedirs/open 直接写，不走上传流程（上传归 Task 8 的 e2e 管）。
"""
import os
import shutil
import tempfile

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles import storage_usage
from apps.datafiles.models import DataFile

PASSWORD = 'x-pass-12345678'
USAGE_URL = '/api/v1/files/usage/'
FIELDS = (
    'data_dir', 'bytes', 'unique_bytes', 'file_count', 'by_type',
    'db_count', 'db_bytes', 'db_bytes_in_root',
    'db_outside_root_count', 'db_outside_root_bytes',
    'mismatch_over_threshold', 'mismatch_diff_bytes', 'scanned_at',
)


class FileUsageApiTests(TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-api-')
        self.addCleanup(shutil.rmtree, self.base, True)
        storage_usage.clear_usage_cache()
        self.user = User.objects.create_user('usage_a', 'ua@localhost', PASSWORD)
        self.other = User.objects.create_user('usage_b', 'ub@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _write(self, username, rel, size):
        path = os.path.join(self.base, 'data', username, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(b'a' * size)
        return path

    def _get(self, **params):
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.get(USAGE_URL, params)

    def test_unauthenticated_rejected(self):
        resp = APIClient().get(USAGE_URL)
        self.assertIn(resp.status_code, (401, 403))

    def test_路由没被router的详情路由吞(self):
        """排序判据（订正①）：DefaultRouter 生成的是 `^files/(?P<pk>[^/.]+)/$`，
        `usage` 恰好匹配 `[^/.]+` ⇒ files/usage/ 必须排在 include(router.urls) 之前，
        否则这里拿到的是 404/400 而不是 200。"""
        self.assertEqual(self._get().status_code, 200)

    def test_返回体字段齐全且类型正确(self):
        self._write('usage_a', 'single/a.csv', 2048)
        data = self._get().json()
        for field in FIELDS:
            self.assertIn(field, data)
        self.assertEqual(data['bytes'], 2048)
        self.assertEqual(data['file_count'], 1)
        self.assertEqual(data['by_type'], {'single': {'bytes': 2048, 'count': 1}})
        self.assertFalse(data['mismatch_over_threshold'])
        self.assertIsInstance(data['scanned_at'], str)

    def test_data_dir指向本人目录(self):
        data = self._get().json()
        self.assertEqual(
            os.path.normpath(data['data_dir']),
            os.path.normpath(os.path.join(self.base, 'data', 'usage_a')),
        )

    def test_没有任何注册行也没有目录时返回零不报错(self):
        data = self._get().json()
        self.assertEqual(data['bytes'], 0)
        self.assertEqual(data['file_count'], 0)
        self.assertEqual(data['db_count'], 0)
        self.assertEqual(data['db_bytes'], 0)
        self.assertFalse(data['mismatch_over_threshold'])

    def test_owner隔离_只看得到自己的目录(self):
        self._write('usage_a', 'single/a.csv', 1000)
        self._write('usage_b', 'single/b.csv', 9000)
        DataFile.objects.create(
            owner=self.other, filename='b.csv',
            file_path='data/usage_b/single/b.csv', file_size=9000,
            format_type='CTA8290D', status='ready',
        )
        mine = self._get().json()
        self.assertEqual(mine['bytes'], 1000)
        self.assertEqual(mine['db_count'], 0)

    def _post_usage(self):
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.post(USAGE_URL, {})

    def test_只读不接受POST(self):
        self.assertEqual(self._post_usage().status_code, 405)

    def test_清单外的遗留绝对路径单列一条不混进bytes(self):
        """订正②的形状：遗留绝对路径指向根目录外 ⇒ 只进 db_outside_root_*，
        不进 bytes，也不因为可比集合错位而报一条假的不一致。"""
        self._write('usage_a', 'single/a.csv', 1000)
        # 计划正文漏了这条在根内的注册行，而它自己断言 db_count == 2 /
        # db_bytes_in_root == 1000 —— 没有这条行时那两个数按实现必为 0 与 1，
        # 用例红在数据上而不是红在口径上。按断言的形状补上 a.csv 的注册行。
        DataFile.objects.create(
            owner=self.user, filename='a.csv',
            file_path='data/usage_a/single/a.csv', file_size=1000,
            format_type='CTA8290D', status='ready',
        )
        DataFile.objects.create(
            owner=self.user, filename='legacy.csv',
            file_path=os.path.join(self.base, 'legacy', 'legacy.csv'),
            file_size=4000, format_type='CTA8290D', status='ready',
        )
        data = self._get().json()
        self.assertEqual(data['bytes'], 1000)
        self.assertEqual(data['db_bytes_in_root'], 1000)
        self.assertEqual(data['db_outside_root_count'], 1)
        self.assertEqual(data['db_outside_root_bytes'], 4000)
        self.assertEqual(data['db_count'], 2)
        self.assertFalse(data['mismatch_over_threshold'])

    def test_磁盘与清单差5pct以上时报出不一致(self):
        self._write('usage_a', 'single/a.csv', 1000)
        DataFile.objects.create(
            owner=self.user, filename='a.csv',
            file_path='data/usage_a/single/a.csv', file_size=100,
            format_type='CTA8290D', status='ready',
        )
        data = self._get().json()
        self.assertTrue(data['mismatch_over_threshold'])
        self.assertEqual(data['mismatch_diff_bytes'], 900)
