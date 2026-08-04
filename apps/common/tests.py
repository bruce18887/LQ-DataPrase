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
