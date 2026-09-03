"""Tests for combine/uncombine transaction safety and filename traversal guard.

Covers:
- Defect 1: DB failure must leave disk unchanged (file not moved).
- Defect 2: filename containing '..' must not escape the batch directory.
- Defect 4: silent exceptions in _register_file now produce log output.
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


class CombineTransactionSafetyTests(TestCase):
    """DB failure in combine/uncombine must not move files on disk."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='lqdp-combine-')
        override = override_settings(MEDIA_ROOT=self._tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        self.user = User.objects.create_user(
            username='testuser', password='pass123', role='user')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create a real file on disk in the single dir
        self.single_dir = os.path.join(self._tmp, 'data', 'testuser', 'single')
        os.makedirs(self.single_dir, exist_ok=True)
        self.src_file = os.path.join(self.single_dir, 'test.csv')
        with open(self.src_file, 'w') as f:
            f.write('col1,col2\n1,2\n')

        # Register the DataFile row
        self.df = DataFile.objects.create(
            owner=self.user,
            filename='test.csv',
            file_path=store_file_path(self.src_file),
            file_size=12,
            format_type='CTA8290D',
            file_type='single',
            status='ready',
        )

    def test_combine_db_failure_leaves_file_in_place(self):
        """If df.save() raises, the file must NOT have been moved."""
        with patch.object(DataFile, 'save', side_effect=RuntimeError('DB exploded')):
            resp = self.client.post(
                '/api/v1/files/combine/',
                {'ids': [self.df.pk], 'batch_name': 'LOT-TEST'},
                format='json',
            )
        # Should get a 500 (unhandled exception in view)
        self.assertEqual(resp.status_code, 500)
        # The file must still exist at the original location
        self.assertTrue(
            os.path.isfile(self.src_file),
            'File was moved despite DB failure — transaction/disk invariant violated',
        )

    def test_uncombine_db_failure_leaves_file_in_place(self):
        """If df.save() raises during uncombine, the file must NOT be moved."""
        # First, set up a batch file
        batch_dir = os.path.join(self._tmp, 'data', 'testuser', 'batch', 'LOT-A')
        os.makedirs(batch_dir, exist_ok=True)
        batch_file = os.path.join(batch_dir, 'batch.csv')
        with open(batch_file, 'w') as f:
            f.write('col1,col2\n3,4\n')

        df_batch = DataFile.objects.create(
            owner=self.user,
            filename='batch.csv',
            file_path=store_file_path(batch_file),
            file_size=12,
            format_type='CTA8290D',
            file_type='batch',
            batch_name='LOT-A',
            status='ready',
        )

        with patch.object(DataFile, 'save', side_effect=RuntimeError('DB exploded')):
            resp = self.client.post(
                '/api/v1/files/uncombine/',
                {'ids': [df_batch.pk]},
                format='json',
            )
        self.assertEqual(resp.status_code, 500)
        self.assertTrue(
            os.path.isfile(batch_file),
            'File was moved despite DB failure — transaction/disk invariant violated',
        )


class CombineFilenameTraversalTests(TestCase):
    """filename containing path traversal must not escape the batch dir."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='lqdp-fname-')
        override = override_settings(MEDIA_ROOT=self._tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        self.user = User.objects.create_user(
            username='attacker', password='pass123', role='user')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.single_dir = os.path.join(self._tmp, 'data', 'attacker', 'single')
        os.makedirs(self.single_dir, exist_ok=True)

        # Create a real source file
        self.src_file = os.path.join(self.single_dir, 'payload.csv')
        with open(self.src_file, 'w') as f:
            f.write('data\n')

    def test_combine_rejects_traversal_filename(self):
        """A filename like '..\\..\\evil.csv' must not write outside batch dir.
        
        os.path.basename strips the traversal → file is moved safely into
        the batch dir as 'evil.csv'. The key assertion: nothing lands outside.
        """
        # Register with a malicious filename (simulates legacy DB state)
        df = DataFile.objects.create(
            owner=self.user,
            filename='..\\..\\evil.csv',
            file_path=store_file_path(self.src_file),
            file_size=5,
            format_type='CTA8290D',
            file_type='single',
            status='ready',
        )

        resp = self.client.post(
            '/api/v1/files/combine/',
            {'ids': [df.pk], 'batch_name': 'LOT-EVIL'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

        # Verify nothing was written outside the batch dir
        evil_path = os.path.join(self._tmp, 'data', 'attacker', 'evil.csv')
        self.assertFalse(os.path.exists(evil_path))
        # The file should have been moved INTO the batch dir with safe name
        batch_dir = os.path.join(self._tmp, 'data', 'attacker', 'batch', 'LOT-EVIL')
        safe_target = os.path.join(batch_dir, 'evil.csv')
        self.assertTrue(
            os.path.exists(safe_target),
            'File should land inside batch dir with sanitized name',
        )

    def test_uncombine_rejects_traversal_filename(self):
        """A filename like '../../evil.csv' must not write outside single dir.
        
        os.path.basename strips the traversal → file is moved safely into
        the single dir as 'evil.csv'. The key assertion: nothing lands outside.
        """
        batch_dir = os.path.join(self._tmp, 'data', 'attacker', 'batch', 'LOT-X')
        os.makedirs(batch_dir, exist_ok=True)
        batch_file = os.path.join(batch_dir, 'real.csv')
        with open(batch_file, 'w') as f:
            f.write('data\n')

        df = DataFile.objects.create(
            owner=self.user,
            filename='../../evil.csv',
            file_path=store_file_path(batch_file),
            file_size=5,
            format_type='CTA8290D',
            file_type='batch',
            batch_name='LOT-X',
            status='ready',
        )

        resp = self.client.post(
            '/api/v1/files/uncombine/',
            {'ids': [df.pk]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

        # Verify nothing escaped to the parent directories
        evil_path = os.path.join(self._tmp, 'data', 'evil.csv')
        self.assertFalse(os.path.exists(evil_path))
        # The file should be moved INTO the single dir with safe name
        single_dir = os.path.join(self._tmp, 'data', 'attacker', 'single')
        safe_target = os.path.join(single_dir, 'evil.csv')
        self.assertTrue(
            os.path.exists(safe_target),
            'File should land inside single dir with sanitized name',
        )

    def test_filename_is_read_only_via_patch(self):
        """PATCH on DataFileViewSet must not allow changing filename."""
        df = DataFile.objects.create(
            owner=self.user,
            filename='original.csv',
            file_path=store_file_path(self.src_file),
            file_size=5,
            format_type='CTA8290D',
            file_type='single',
            status='ready',
        )

        resp = self.client.patch(
            f'/api/v1/files/{df.pk}/',
            {'filename': '..\\..\\evil.csv'},
            format='json',
        )
        # Should succeed (200) but filename should be unchanged
        self.assertEqual(resp.status_code, 200)
        df.refresh_from_db()
        self.assertEqual(df.filename, 'original.csv')


class RegisterFileLoggingTests(TestCase):
    """_register_file must log parse failures (defect 4)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='lqdp-log-')
        override = override_settings(MEDIA_ROOT=self._tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        self.user = User.objects.create_user(
            username='loguser', password='pass123', role='user')

    def test_register_file_logs_parse_failure(self):
        """When parsing fails, a warning must be logged."""
        from apps.datafiles.views._helpers import _register_file

        # Create a file that will fail parsing
        single_dir = os.path.join(self._tmp, 'data', 'loguser', 'single')
        os.makedirs(single_dir, exist_ok=True)
        bad_file = os.path.join(single_dir, 'bad.csv')
        with open(bad_file, 'w') as f:
            f.write('not valid csv content\n')

        with self.assertLogs('apps.datafiles.views._helpers', level='WARNING') as cm:
            # Patch the parser to raise
            with patch(
                'apps.datafiles.views._helpers.BaseATEParser.identify_format',
                side_effect=ValueError('parse boom'),
            ):
                df = _register_file(self.user, bad_file, 'single')

        # Should have logged
        self.assertTrue(any('parse failed' in msg for msg in cm.output))
        # File should still be registered (with status='error')
        self.assertEqual(df.status, 'error')
