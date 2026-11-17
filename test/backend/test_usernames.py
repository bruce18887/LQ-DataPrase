"""`is_safe_username` 的判据本体（批4 刀二）。

第二层与 HTTP 400 的判据按设计稿 §3.6 落在
`test/backend/test_batch_dir_traversal.py`；这里只钉纯函数。
"""
import os

from django.test import SimpleTestCase

from apps.common.usernames import is_safe_username


class SafeUsernameTests(SimpleTestCase):
    def test_rejects_names_that_change_the_directory(self):
        for bad in ('', '.', '..', 'a' + os.sep + 'b'):
            self.assertFalse(is_safe_username(bad), repr(bad))

    def test_allows_dotted_and_normal_names(self):
        for good in ('user', 'a.b', 'a-b', 'a_b', 'a@b', 'a+b'):
            self.assertTrue(is_safe_username(good), repr(good))
