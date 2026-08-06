"""Unit tests for export filename template rendering (apps.common.export_naming)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from datetime import datetime

from apps.accounts.models import UserSetting
from .export_naming import (
    EXPORT_TEMPLATE_DEFAULTS,
    sanitize_filename_part,
    resolve_template,
    base_export_context,
    render_export_filename,
)

User = get_user_model()


class SanitizeFilenamePartTests(TestCase):
    def test_windows_invalid_chars_replaced(self):
        # \ / : * ? " < > | plus control chars
        dirty = 'a\\b/c:d*e?f"g<h>i|j\x00k\x1fl'
        self.assertEqual(sanitize_filename_part(dirty), 'a_b_c_d_e_f_g_h_i_j_k_l')

    def test_strip_whitespace_and_trailing_dots(self):
        self.assertEqual(sanitize_filename_part('  name  '), 'name')
        self.assertEqual(sanitize_filename_part('name.. '), 'name')

    def test_valid_name_unchanged(self):
        self.assertEqual(sanitize_filename_part('gage_m_S1_20260804_143022'), 'gage_m_S1_20260804_143022')


class ResolveTemplateTests(TestCase):
    def test_known_variables_replaced(self):
        self.assertEqual(
            resolve_template('{filename}_{sigma}sigma',
                             {'filename': 'f1', 'sigma': 3}, ('filename', 'sigma')),
            'f1_3sigma',
        )

    def test_unknown_placeholder_kept(self):
        self.assertEqual(
            resolve_template('{filename}_{typo}', {'filename': 'f1'}, ('filename',)),
            'f1_{typo}',
        )

    def test_allowed_but_missing_variable_renders_empty(self):
        # {sigma} is allowed for this type but absent from context → ''
        self.assertEqual(
            resolve_template('{sigma}_{filename}',
                             {'filename': 'f1'}, ('sigma', 'filename')),
            '_f1',
        )


class BaseExportContextTests(TestCase):
    def test_ctx_format(self):
        user = User(username='tester')
        local = timezone.localtime(datetime(2026, 8, 4, 14, 30, 22, tzinfo=timezone.get_current_timezone()))
        ctx = base_export_context(user, now=local)
        self.assertEqual(ctx['user'], 'tester')
        self.assertEqual(ctx['date'], '20260804')
        self.assertEqual(ctx['time'], '143022')
        self.assertEqual(ctx['datetime'], '20260804_143022')


class RenderExportFilenameTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='x')
        self.ctx = {'filename': 'gage_m_S1', 'sigma': 3, 'batch_name': 'BATCH_001', 'file_count': 2}

    def test_default_template_when_no_setting_row(self):
        # No UserSetting row at all (get_or_create path)
        name = render_export_filename(self.user, 'to_excel', 'xlsx', self.ctx)
        self.assertEqual(name, 'gage_m_S1_analysis.xlsx')

    def test_custom_template_renders_all_variables(self):
        UserSetting.objects.update_or_create(
            user=self.user,
            defaults={'export_filename_templates': {
                'sigma_limit': '{filename}_{sigma}sigma_{datetime}_{user}',
            }},
        )
        now = timezone.localtime(datetime(2026, 8, 4, 14, 30, 22, tzinfo=timezone.get_current_timezone()))
        name = render_export_filename(self.user, 'sigma_limit', 'xlsx',
                                      {**self.ctx, **base_export_context(self.user, now=now)})
        self.assertEqual(name, 'gage_m_S1_3sigma_20260804_143022_tester.xlsx')

    def test_multifile_variables(self):
        UserSetting.objects.update_or_create(
            user=self.user,
            defaults={'export_filename_templates': {'batch_report': 'BR_{batch_name}_{file_count}'}},
        )
        name = render_export_filename(self.user, 'batch_report', 'xlsx', self.ctx)
        self.assertEqual(name, 'BR_BATCH_001_2.xlsx')

    def test_unknown_placeholder_kept_and_not_ext_duplicated(self):
        UserSetting.objects.update_or_create(
            user=self.user,
            defaults={'export_filename_templates': {'to_csv': '{filename}_{typo}.csv'}},
        )
        name = render_export_filename(self.user, 'to_csv', 'csv', self.ctx)
        self.assertEqual(name, 'gage_m_S1_{typo}.csv')

    def test_empty_template_falls_back_to_default(self):
        UserSetting.objects.update_or_create(
            user=self.user,
            defaults={'export_filename_templates': {'to_excel': ''}},
        )
        name = render_export_filename(self.user, 'to_excel', 'xlsx', self.ctx)
        self.assertEqual(name, 'gage_m_S1_analysis.xlsx')

    def test_rendered_empty_falls_back_to_default(self):
        # {batch_name} is allowed for batch_report but missing from ctx → ''
        # → falls back to the default template (rendered with base ctx)
        UserSetting.objects.update_or_create(
            user=self.user,
            defaults={'export_filename_templates': {'batch_report': '{batch_name}'}},
        )
        ctx = {**base_export_context(self.user), 'file_count': 2}  # no batch_name
        name = render_export_filename(self.user, 'batch_report', 'xlsx', ctx)
        self.assertRegex(name, r'^Batch_Report_\d{8}_\d{6}\.xlsx$')

    def test_unknown_export_type_uses_generic_default(self):
        name = render_export_filename(self.user, 'not_a_type', 'xlsx', self.ctx)
        self.assertEqual(name, 'export.xlsx')

    def test_sanitize_applied_to_user_template(self):
        UserSetting.objects.update_or_create(
            user=self.user,
            defaults={'export_filename_templates': {'to_excel': '{filename}:bad?'}},
        )
        name = render_export_filename(self.user, 'to_excel', 'xlsx', self.ctx)
        self.assertEqual(name, 'gage_m_S1_bad_.xlsx')

    def test_defaults_covers_all_export_types(self):
        self.assertEqual(len(EXPORT_TEMPLATE_DEFAULTS), 8)
        for key, default in EXPORT_TEMPLATE_DEFAULTS.items():
            name = render_export_filename(self.user, key, 'xlsx', self.ctx)
            self.assertTrue(name.endswith('.xlsx'), f'{key} default should end with .xlsx: {name}')


# ---------------------------------------------------------------------------
# System storage path configuration (apps.common.system_config + /system/paths/)
# ---------------------------------------------------------------------------

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from rest_framework.test import APIClient, APITestCase

from apps.common import system_config


def _make_sqlite_db(path: Path, marker: str = 'x') -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
        conn.execute('INSERT INTO t VALUES (1, ?)', (marker,))
        conn.commit()
    finally:
        conn.close()


class SystemConfigApplyTests(SimpleTestCase):
    """Pure path/migration logic — no DB, no request context."""

    def setUp(self):
        self._orig_tempdir = tempfile.tempdir
        self._orig_env = {k: os.environ.get(k) for k in ('TMP', 'TEMP', 'TMPDIR')}
        self._tmp = tempfile.TemporaryDirectory()
        self._base = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def tearDown(self):
        tempfile.tempdir = self._orig_tempdir
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_no_config_returns_original_and_keeps_tempfile(self):
        result = system_config.apply_system_config(self._base)
        self.assertEqual(result, self._base)
        self.assertEqual(tempfile.tempdir, self._orig_tempdir)

    def test_data_dir_migrates_db_and_media_then_deletes_originals(self):
        db_src = self._base / 'db.sqlite3'
        _make_sqlite_db(db_src)
        (self._base / 'media').mkdir()
        (self._base / 'media' / 'keep.txt').write_text('data', encoding='utf-8')
        # secret.key must stay anchored to the original dir
        (self._base / 'secret.key').write_text('key', encoding='utf-8')
        with tempfile.TemporaryDirectory() as new_dir:
            new_base = Path(new_dir)
            (self._base / system_config.CONFIG_FILENAME).write_text(
                json.dumps({'data_dir': str(new_base)}), encoding='utf-8'
            )
            result = system_config.apply_system_config(self._base)
            self.assertEqual(result, new_base)
            self.assertTrue((new_base / 'db.sqlite3').is_file())
            self.assertEqual((new_base / 'media' / 'keep.txt').read_text(), 'data')
            self.assertFalse((self._base / 'db.sqlite3').exists())
            self.assertFalse((self._base / 'media').exists())
            # anchor files untouched
            self.assertTrue((self._base / 'secret.key').is_file())
            self.assertTrue((self._base / system_config.CONFIG_FILENAME).is_file())

    def test_target_with_existing_db_wins_no_overwrite(self):
        db_src = self._base / 'db.sqlite3'
        _make_sqlite_db(db_src, marker='old')
        with tempfile.TemporaryDirectory() as new_dir:
            new_base = Path(new_dir)
            _make_sqlite_db(new_base / 'db.sqlite3', marker='target')
            (self._base / system_config.CONFIG_FILENAME).write_text(
                json.dumps({'data_dir': str(new_base)}), encoding='utf-8'
            )
            result = system_config.apply_system_config(self._base)
            self.assertEqual(result, new_base)
            conn = sqlite3.connect(str(new_base / 'db.sqlite3'))
            try:
                marker = conn.execute('SELECT v FROM t').fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(marker, 'target')  # target content preserved
            self.assertTrue(db_src.is_file())   # source kept, not destroyed

    def test_missing_old_db_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as new_dir:
            new_base = Path(new_dir)
            (self._base / system_config.CONFIG_FILENAME).write_text(
                json.dumps({'data_dir': str(new_base)}), encoding='utf-8'
            )
            result = system_config.apply_system_config(self._base)
        self.assertEqual(result, new_base)

    def test_corrupt_config_backed_up_to_bak(self):
        (self._base / system_config.CONFIG_FILENAME).write_text('{not json', encoding='utf-8')
        result = system_config.apply_system_config(self._base)
        self.assertEqual(result, self._base)
        self.assertTrue((self._base / 'system_config.json.bak').is_file())

    def test_temp_dir_applied_to_tempfile_and_env(self):
        with tempfile.TemporaryDirectory() as new_tmp:
            new_tmp_path = Path(new_tmp)
            (self._base / system_config.CONFIG_FILENAME).write_text(
                json.dumps({'temp_dir': str(new_tmp_path)}), encoding='utf-8'
            )
            result = system_config.apply_system_config(self._base)
        self.assertEqual(result, self._base)
        self.assertEqual(tempfile.tempdir, str(new_tmp_path))
        self.assertEqual(os.environ['TMP'], str(new_tmp_path))
        self.assertEqual(os.environ['TEMP'], str(new_tmp_path))
        self.assertEqual(os.environ['TMPDIR'], str(new_tmp_path))

    def test_config_file_env_override(self):
        with tempfile.TemporaryDirectory() as cfg_dir:
            cfg_file = Path(cfg_dir) / 'custom.json'
            os.environ['LQDP_SYSTEM_CONFIG_FILE'] = str(cfg_file)
            self.addCleanup(os.environ.pop, 'LQDP_SYSTEM_CONFIG_FILE', None)
            cfg_file.write_text(
                json.dumps({'data_dir': str(self._base)}), encoding='utf-8'
            )
            result = system_config.apply_system_config(self._base)
            self.assertEqual(result, self._base)  # data_dir == original → no-op
            # config file was read from the override location
            self.assertEqual(system_config.config_file_path(self._base), cfg_file)
            self.assertTrue(cfg_file.is_file())

    def test_save_config_roundtrip_and_none_removes_key(self):
        cfg_file = self._base / 'custom.json'
        system_config.save_config(cfg_file, data_dir='/tmp/data', temp_dir=None)
        self.assertEqual(json.loads(cfg_file.read_text()), {'data_dir': '/tmp/data'})
        system_config.save_config(cfg_file, data_dir=None, temp_dir=None)
        self.assertEqual(json.loads(cfg_file.read_text()), {})

    def test_validate_directory_rejects_bad_paths(self):
        for bad in ('', '  ', 'relative/path', 'C:drive-relative'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    system_config.validate_directory(bad)
        with tempfile.TemporaryDirectory() as ok_dir:
            result = system_config.validate_directory(ok_dir)
            self.assertTrue(result.is_dir())
            self.assertFalse((result / system_config._PROBE_FILENAME).exists())


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
        from django.conf import settings
        self.assertNotEqual(str(settings.BASE_DIR), new_data)
