"""Tests for /files/ ``page_size`` query param support.

Regression pins for "分析页文件选择框数量与数据管理页不一致": the DRF
default PageNumberPagination ignores ``page_size`` (``page_size_query_param``
is None), so front-end "load all" calls (``?page_size=9999`` for the analysis
dropdown / dashboard / data-view dropdowns) were silently truncated to
PAGE_SIZE=20 — the dropdown showed 20 files while the data-management table
counted all of them.

Run directly:  python test/backend/test_file_pagination.py
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

# PAGE_SIZE=20 —— 25 个文件保证「全量请求」与「默认分页」可区分
FILE_COUNT = 25


class FilePaginationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user('paginate_tester', 'pt@localhost', PASSWORD)
        cls.other = User.objects.create_user('paginate_other', 'po@localhost', PASSWORD)
        # 另一用户也有文件：验证分页只影响本用户查询集
        DataFile.objects.bulk_create([
            DataFile(owner=cls.other, filename=f'other_{i}.csv', status='ready',
                     file_size=10)
            for i in range(5)
        ])
        cls.ids = [
            DataFile.objects.create(
                owner=cls.user, filename=f'page_test_{i}.csv', status='ready',
                file_size=10).id
            for i in range(FILE_COUNT)
        ]

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_page_size_9999_returns_all_files(self):
        """回归钉：分析页/仪表板/查看数据下拉用 ?page_size=9999 拉全量——
        此前被 DRF 默认分页忽略，静默截断为 20 条。"""
        resp = self.client.get('/api/v1/files/', {'page_size': 9999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], FILE_COUNT)
        self.assertEqual(len(resp.data['results']), FILE_COUNT)

    def test_default_pagination_unchanged(self):
        """无 page_size 参数时仍走 PAGE_SIZE=20 分页（数据管理表格行为不变）。"""
        resp = self.client.get('/api/v1/files/', {})
        self.assertEqual(len(resp.data['results']), 20)
        self.assertEqual(resp.data['count'], FILE_COUNT)

    def test_max_page_size_clamps(self):
        """超大 page_size 被 max_page_size 限制，不会打爆响应。"""
        resp = self.client.get('/api/v1/files/', {'page_size': 999999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), FILE_COUNT)


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_file_pagination'])
    sys.exit(1 if failures else 0)
