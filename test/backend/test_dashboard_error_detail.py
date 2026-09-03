"""Tests for dashboard views error detail leak (defect 5).

Covers:
- Non-DEBUG mode: 500 response must NOT contain 'detail' with exception text.
- DEBUG mode: 500 response MAY contain 'detail'.
"""
import os
import shutil
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.datafiles.utils import store_file_path


class DashboardErrorDetailLeakTests(TestCase):
    """Internal error details must not leak in production (non-DEBUG)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='lqdp-dash-')
        override = override_settings(MEDIA_ROOT=self._tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        self.user = User.objects.create_user(
            username='dashuser', password='pass123', role='user')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create a file record that will trigger an error during parsing
        single_dir = os.path.join(self._tmp, 'data', 'dashuser', 'single')
        os.makedirs(single_dir, exist_ok=True)
        self.csv_file = os.path.join(single_dir, 'dash.csv')
        with open(self.csv_file, 'w') as f:
            f.write('dummy\n')

        self.df = DataFile.objects.create(
            owner=self.user,
            filename='dash.csv',
            file_path=store_file_path(self.csv_file),
            file_size=6,
            format_type='CTA8290D',
            file_type='single',
            status='ready',
        )

    @override_settings(DEBUG=False)
    def test_non_debug_500_does_not_leak_detail(self):
        """In production mode, the 500 body must not contain exception text."""
        # Force an internal error by patching a function to raise
        with patch(
            'apps.dashboard.views.get_cached_parsed_file',
            side_effect=RuntimeError('secret internal path /etc/shadow'),
        ):
            resp = self.client.get(
                '/api/v1/summary/', {'file_id': self.df.pk})

        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertEqual(body.get('error'), 'internal_error')
        # Must NOT contain the exception detail
        self.assertNotIn('detail', body)
        # Double-check: the secret text must not appear anywhere in response
        self.assertNotIn('secret', str(body))

    @override_settings(DEBUG=True)
    def test_debug_500_includes_detail(self):
        """In debug mode, the detail field should be present for developers."""
        with patch(
            'apps.dashboard.views.get_cached_parsed_file',
            side_effect=RuntimeError('debug info here'),
        ):
            resp = self.client.get(
                '/api/v1/summary/', {'file_id': self.df.pk})

        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertIn('detail', body)
        self.assertIn('debug info here', body['detail'])
