"""Regression guard: batch-directory endpoints must not escape the user's root.

``BatchDirDeleteView`` / ``SubBatchDeleteView`` pass the resolved path straight
to ``shutil.rmtree``, and ``BatchDirImportView`` takes ``dir_name`` from the
*request body* — where no ``<str:>`` URL converter strips separators. Before
``_safe_batch_dir`` existed:

* ``dir_name='..'`` on delete resolved to the per-user upload root and wiped
  both ``batch/`` and ``single/`` (silently, ``ignore_errors=True``);
* ``sub_batch_name='..'`` resolved to the batch dir and wiped the whole batch;
* ``dir_name='../../<other-user>/batch'`` on import walked another user's tree
  and registered their CSVs as the caller's own.

MEDIA_ROOT is redirected to a temp dir so the real ``media/`` is never touched.
"""
import os
import shutil
import tempfile

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.datafiles.views._helpers import _safe_batch_dir, _user_upload_dir


class SafeBatchDirTests(SimpleTestCase):
    """Unit level: the guard itself (no DB, no HTTP)."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-guard-')
        os.makedirs(os.path.join(self.base, 'LOT-A'), exist_ok=True)
        self.addCleanup(shutil.rmtree, self.base, True)

    def test_legitimate_segment_resolves_inside_base(self):
        got = _safe_batch_dir(self.base, 'LOT-A')
        self.assertEqual(
            got, os.path.realpath(os.path.join(self.base, 'LOT-A')))

    def test_rejects_parent_and_self_segments(self):
        """``..`` alone passes the ``<str:>`` converter and is the real bug."""
        for bad in ('..', '.', '  ..  ', '\t..'):
            self.assertIsNone(_safe_batch_dir(self.base, bad), f'{bad!r}')

    def test_rejects_traversal_out_of_base(self):
        for bad in ('../../other', '..\\..\\other', '../LOT-A', 'LOT-A/../../..'):
            self.assertIsNone(_safe_batch_dir(self.base, bad), f'{bad!r}')

    def test_rejects_separators_and_windows_illegal_chars(self):
        for bad in ('a/b', 'a\\b', 'a<b', 'a>b', 'a:b', 'a"b',
                    'a|b', 'a*b', 'a\x00b', 'a\nb'):
            self.assertIsNone(_safe_batch_dir(self.base, bad), f'{bad!r}')

    def test_rejects_absolute_paths(self):
        for bad in (os.path.abspath(os.sep), 'C:\\Windows', '\\\\host\\share'):
            self.assertIsNone(_safe_batch_dir(self.base, bad), f'{bad!r}')

    def test_rejects_empty_and_non_string(self):
        for bad in ('', '   ', None, 123, ['LOT-A'], {'a': 1}, True):
            self.assertIsNone(_safe_batch_dir(self.base, bad), f'{bad!r}')


class BatchDirTraversalTests(TestCase):
    """HTTP level: the three endpoints reject escapes and still work normally."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='lqdp-media-')
        override = override_settings(MEDIA_ROOT=self._tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        self.attacker = User.objects.create_user(
            username='attacker', password='strong-pass-123', role='viewer')
        self.victim = User.objects.create_user(
            username='victim', password='strong-pass-123', role='user')

        # Victim's private batch data, one directory level above attacker's.
        self.victim_batch = _user_upload_dir(self.victim, 'batch')
        self.victim_lot = os.path.join(self.victim_batch, 'LOT-SECRET')
        os.makedirs(self.victim_lot, exist_ok=True)
        with open(os.path.join(self.victim_lot, 'secret.csv'), 'w') as fh:
            fh.write('x')

        self.attacker_batch = _user_upload_dir(self.attacker, 'batch')
        self.client = APIClient()
        self.client.force_authenticate(user=self.attacker)

    # ---- import (dir_name from the request body) ----

    def test_import_rejects_cross_user_traversal(self):
        """The Critical vector: register another user's CSVs as one's own."""
        resp = self.client.post(
            '/api/v1/batch-dirs/import/',
            {'dir_name': '../../victim/batch/LOT-SECRET'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            DataFile.objects.filter(owner=self.attacker).count(), 0)
        # Victim's file is untouched on disk.
        self.assertTrue(
            os.path.isfile(os.path.join(self.victim_lot, 'secret.csv')))

    def test_import_rejects_dotdot(self):
        resp = self.client.post(
            '/api/v1/batch-dirs/import/', {'dir_name': '..'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            DataFile.objects.filter(owner=self.attacker).count(), 0)

    def test_import_rejects_non_string_dir_name(self):
        """A JSON list/dict used to reach os.path.join and raise TypeError."""
        resp = self.client.post(
            '/api/v1/batch-dirs/import/', {'dir_name': ['..']}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_legitimate_import_still_works(self):
        lot = os.path.join(self.attacker_batch, 'LOT-OK')
        os.makedirs(lot, exist_ok=True)
        with open(os.path.join(lot, 'a.csv'), 'w') as fh:
            fh.write('x')
        resp = self.client.post(
            '/api/v1/batch-dirs/import/', {'dir_name': 'LOT-OK'}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            DataFile.objects.filter(
                owner=self.attacker, batch_name='LOT-OK').count(), 1)

    # ---- delete (dir_name from the URL) ----

    def test_delete_rejects_encoded_dotdot(self):
        """``%2e%2e`` decodes to ``..`` before routing and matches ``<str:>``."""
        resp = self.client.delete('/api/v1/batch-dirs/%2e%2e/')
        self.assertEqual(resp.status_code, 400)
        # The per-user upload root (batch/ AND single/) must survive.
        self.assertTrue(os.path.isdir(self.attacker_batch))
        self.assertTrue(os.path.isdir(self.victim_lot))

    def test_delete_rejects_illegal_characters(self):
        resp = self.client.delete('/api/v1/batch-dirs/..%5C..%5Cvictim/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(os.path.isdir(self.victim_lot))

    def test_legitimate_delete_still_works(self):
        lot = os.path.join(self.attacker_batch, 'LOT-DEL')
        os.makedirs(lot, exist_ok=True)
        with open(os.path.join(lot, 'a.csv'), 'w') as fh:
            fh.write('x')
        resp = self.client.delete('/api/v1/batch-dirs/LOT-DEL/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(os.path.isdir(lot))

    # ---- sub-batch delete ----

    def test_sub_batch_delete_rejects_encoded_dotdot(self):
        """``..`` as sub_batch resolves to the batch dir and wiped it wholesale."""
        lot = os.path.join(self.attacker_batch, 'LOT-SUB')
        keep = os.path.join(lot, 'FT1')
        os.makedirs(keep, exist_ok=True)
        with open(os.path.join(keep, 'a.csv'), 'w') as fh:
            fh.write('x')
        resp = self.client.delete('/api/v1/batch-dirs/LOT-SUB/sub/%2e%2e/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(os.path.isdir(lot))
        self.assertTrue(os.path.isdir(keep))

    def test_legitimate_sub_batch_delete_still_works(self):
        lot = os.path.join(self.attacker_batch, 'LOT-SUB2')
        sub = os.path.join(lot, 'FT1')
        os.makedirs(sub, exist_ok=True)
        resp = self.client.delete('/api/v1/batch-dirs/LOT-SUB2/sub/FT1/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(os.path.isdir(sub))
        self.assertTrue(os.path.isdir(lot))
