"""``GET/PUT /api/v1/system/paths/`` 的契约测试。

从 ``apps/common/tests.py`` 拆出来有两个原因：① 那个文件搬前已 605 行，超了 CLAUDE.md:62
的 600 行上限；② 这个端点的权限**按 settings 档分叉**（桌面：所有登录用户可读；
服务器：仅管理员），值得一个自己的文件把「角色 × 档」这张表钉在一处。

运行：``manage.py test apps.common.tests_system_paths``
"""
import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from apps.common import system_config


class SystemPathsApiTests(APITestCase):
    """GET/PUT /api/v1/system/paths/ — permissions, validation, persistence."""

    def setUp(self):
        self.admin = self._mkuser('sysadmin', 'administrator')
        self.plain = self._mkuser('sysuser', 'user')
        self.viewer = self._mkuser('sysviewer', 'viewer')
        # isolate the config file into a temp location — never pollute the repo
        self._cfg_dir = tempfile.TemporaryDirectory()
        self._cfg_file = Path(self._cfg_dir.name) / 'system_config.json'
        self.addCleanup(self._cfg_dir.cleanup)
        self._old_env = os.environ.get('LQDP_SYSTEM_CONFIG_FILE')
        os.environ['LQDP_SYSTEM_CONFIG_FILE'] = str(self._cfg_file)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._old_env is None:
            os.environ.pop('LQDP_SYSTEM_CONFIG_FILE', None)
        else:
            os.environ['LQDP_SYSTEM_CONFIG_FILE'] = self._old_env

    @staticmethod
    def _mkuser(username, role):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.create_user(
            username=username, password='strong-pass-123', role=role,
        )

    def _auth_client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_get_requires_auth(self):
        resp = APIClient().get('/api/v1/system/paths/')
        self.assertEqual(resp.status_code, 401)

    def test_get_shape_and_editable_flag(self):
        resp = self._auth_client(self.viewer).get('/api/v1/system/paths/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ('data_dir', 'db_path', 'media_path', 'temp_dir', 'config_file',
                    'configured', 'editable', 'restart_required'):
            self.assertIn(key, data)
        self.assertFalse(data['editable'])
        self.assertFalse(data['restart_required'])
        self.assertTrue(data['db_path'])  # test runner uses an in-memory DB here
        self.assertEqual(data['config_file'], str(self._cfg_file))
        self.assertTrue(data['temp_dir'])

    def test_get_admin_editable_true(self):
        resp = self._auth_client(self.admin).get('/api/v1/system/paths/')
        self.assertTrue(resp.json()['editable'])

    # --- SYSTEM_PATHS_VISIBLE_TO_ALL -------------------------------------
    # 桌面形态里「viewer 能看本机路径」不是秘密（上面那条用例就是它的契约）；
    # 同一份代码跑在局域网服务器上时，这些绝对路径披露的是服务器的目录结构、
    # 数据库文件位置和配置文件位置，普通账号没有理由读到。闸门放在 API 上而不是
    # 只藏在界面里（lessons R3②：前端隐藏不等于权限）。

    def test_setting_defaults_visible_for_desktop_profiles(self):
        self.assertTrue(settings.SYSTEM_PATHS_VISIBLE_TO_ALL)

    @override_settings(SYSTEM_PATHS_VISIBLE_TO_ALL=False)
    def test_hidden_get_forbidden_for_non_admin(self):
        for user in (self.plain, self.viewer):
            with self.subTest(user=user.username):
                resp = self._auth_client(user).get('/api/v1/system/paths/')
                self.assertEqual(resp.status_code, 403)
                # 泄漏判据看响应体本身，不看状态码
                body = resp.content.decode()
                for key in ('db_path', 'media_path', 'config_file', 'data_dir'):
                    self.assertNotIn(key, body)

    @override_settings(SYSTEM_PATHS_VISIBLE_TO_ALL=False)
    def test_hidden_get_still_ok_for_admin(self):
        resp = self._auth_client(self.admin).get('/api/v1/system/paths/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['editable'])

    @override_settings(SYSTEM_PATHS_VISIBLE_TO_ALL=False)
    def test_hidden_anonymous_get_is_still_401(self):
        """未登录必须保持 401：这道闸门不能把「没登录」吞成「没权限」，
        前端靠 401 触发重新登录。"""
        resp = APIClient().get('/api/v1/system/paths/')
        self.assertEqual(resp.status_code, 401)

    @override_settings(SYSTEM_PATHS_VISIBLE_TO_ALL=False)
    def test_hidden_put_still_forbidden_for_non_admin(self):
        resp = self._auth_client(self.viewer).put(
            '/api/v1/system/paths/', {'temp_dir': tempfile.gettempdir()}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_put_forbidden_for_non_admin(self):
        for user in (self.plain, self.viewer):
            with self.subTest(user=user.username):
                resp = self._auth_client(user).put(
                    '/api/v1/system/paths/',
                    {'temp_dir': tempfile.gettempdir()}, format='json',
                )
                self.assertEqual(resp.status_code, 403)

    def test_put_rejects_invalid_paths(self):
        client = self._auth_client(self.admin)
        for bad in ('relative/path', 'C:drive-relative', '', '  '):
            with self.subTest(bad=bad):
                resp = client.put('/api/v1/system/paths/', {'temp_dir': bad}, format='json')
                self.assertEqual(resp.status_code, 400, resp.content)
        self.assertFalse(self._cfg_file.exists())

    def test_put_temp_dir_persists_and_marks_restart_required(self):
        client = self._auth_client(self.admin)
        with tempfile.TemporaryDirectory() as new_tmp:
            resp = client.put('/api/v1/system/paths/', {'temp_dir': new_tmp}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data['restart_required'])
        self.assertEqual(data['configured']['temp_dir'], new_tmp)
        self.assertEqual(
            json.loads(self._cfg_file.read_text(encoding='utf-8'))['temp_dir'], new_tmp
        )
        # effective values unchanged until restart
        self.assertNotEqual(data['temp_dir'], new_tmp)

    def test_put_same_value_again_not_restart_required(self):
        client = self._auth_client(self.admin)
        with tempfile.TemporaryDirectory() as new_tmp:
            client.put('/api/v1/system/paths/', {'temp_dir': new_tmp}, format='json')
            resp = client.put('/api/v1/system/paths/', {'temp_dir': new_tmp}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['restart_required'])

    def test_put_null_removes_key(self):
        client = self._auth_client(self.admin)
        with tempfile.TemporaryDirectory() as new_tmp:
            client.put('/api/v1/system/paths/', {'temp_dir': new_tmp}, format='json')
            resp = client.put('/api/v1/system/paths/', {'temp_dir': None}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['restart_required'])
        self.assertEqual(json.loads(self._cfg_file.read_text(encoding='utf-8')), {})

    def test_put_data_dir_writes_config_only(self):
        client = self._auth_client(self.admin)
        with tempfile.TemporaryDirectory() as new_data:
            resp = client.put('/api/v1/system/paths/', {'data_dir': new_data}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            json.loads(self._cfg_file.read_text(encoding='utf-8'))['data_dir'], new_data
        )
        # runtime BASE_DIR untouched — restart applies the change
        self.assertNotEqual(str(settings.BASE_DIR), new_data)
