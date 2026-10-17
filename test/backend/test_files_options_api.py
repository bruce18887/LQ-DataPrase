"""Tests for /files/options/ —— 下拉框专用轻量文件清单契约.

分析页 / 仪表板挂载时曾用 ``GET /files/?page_size=9999`` 只为拿一份下拉清单，
列表序列化器逐行算 stage / data_date 并 join owner。本端点只 ``.values()``
标量列，返回 ``{'results': [...]}``（不分页）。

契约钉点：
* 鉴权沿用 IsAuthenticated（未登录 401/403）；
* 只返回当前用户的文件；
* 默认只返回 status='ready'（``?include_error=1`` 兼容旧下拉的可见范围）；
* 响应键集**完全等于**轻量字段表 —— 多一个 stage/data_date 都算违约；
* ``?limit=`` 生效（默认 5000，上限 20000）。

Run directly:  python test/backend/test_files_options_api.py
(Runs against an isolated test DB via DiscoverRunner — dev db.sqlite3 is
never touched.)
"""
import os
import sys

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import TestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.datafiles.models import DataFile  # noqa: E402

PASSWORD = 'x-pass-12345678'

# 与后端 .values() 字段表逐一对齐；集合相等是契约本身（不多算 stage/data_date）。
EXPECTED_KEYS = {
    'id', 'filename', 'file_type', 'batch_name', 'sub_batch',
    'format_type', 'program_name', 'product_code', 'row_count',
    'col_count', 'file_size', 'source_mtime', 'created_at', 'status',
}


class FileOptionsApiTests(TestCase):
    """API 层：/files/options/ 轻量清单契约（下拉数据源）。"""

    def setUp(self):
        self.user = User.objects.create_user('options_tester', 'ot@localhost', PASSWORD)
        self.other = User.objects.create_user('options_other', 'oo@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _make(self, owner, filename, status='ready'):
        return DataFile.objects.create(
            owner=owner, filename=filename, file_size=10,
            format_type='CTA8290D', status=status,
        )

    def test_unauthenticated_rejected(self):
        """未登录访问 options 被拒（与其它端点一致，不放宽权限）。"""
        resp = APIClient().get('/api/v1/files/options/')
        self.assertIn(resp.status_code, (401, 403))

    def test_only_returns_current_users_files(self):
        """只返回当前用户的文件：另一用户的文件不可见。"""
        self._make(self.user, 'mine.csv')
        self._make(self.other, 'theirs.csv')
        resp = self.client.get('/api/v1/files/options/')
        self.assertEqual(resp.status_code, 200)
        names = [row['filename'] for row in resp.data['results']]
        self.assertEqual(names, ['mine.csv'])

    def test_error_rows_excluded_by_default(self):
        """默认只含 ready 行；?include_error=1 才带上 error 行。"""
        self._make(self.user, 'ok.csv', status='ready')
        self._make(self.user, 'broken.csv', status='error')

        resp = self.client.get('/api/v1/files/options/')
        names = [row['filename'] for row in resp.data['results']]
        self.assertEqual(names, ['ok.csv'])

        resp = self.client.get('/api/v1/files/options/', {'include_error': 1})
        names = {row['filename'] for row in resp.data['results']}
        self.assertEqual(names, {'ok.csv', 'broken.csv'})

    def test_response_keys_match_lightweight_contract(self):
        """响应键集与轻量字段表完全相等（钉住「不多算 stage/data_date」）。"""
        self._make(self.user, 'keys.csv')
        resp = self.client.get('/api/v1/files/options/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, dict)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(set(resp.data['results'][0].keys()), EXPECTED_KEYS)

    def test_limit_param_caps_rows(self):
        """?limit=1 只返回一行（默认 5000 / 上限 20000 之外的可控截断）。"""
        for i in range(3):
            self._make(self.user, f'limit_{i}.csv')
        resp = self.client.get('/api/v1/files/options/', {'limit': 1})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 1)


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_files_options_api'])
    sys.exit(1 if failures else 0)
