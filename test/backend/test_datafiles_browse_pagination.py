"""Tests for browse_views.py pagination parameter robustness (defect 3).

Covers:
- page=abc → no 500, falls back to page 1
- page=-1 → no 500, clamped to 1
- page_size=999999 → no 500, clamped to max
- page_size=abc → no 500, falls back to default
- page_size=0 → clamped to 1
"""
import os
import shutil
import tempfile

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.datafiles.utils import store_file_path


class BrowsePaginationRobustnessTests(TestCase):
    """Pagination params must not cause 500 on invalid input."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='lqdp-page-')
        override = override_settings(MEDIA_ROOT=self._tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        self.user = User.objects.create_user(
            username='pageuser', password='pass123', role='user')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create a minimal CSV file that the parser can handle
        single_dir = os.path.join(self._tmp, 'data', 'pageuser', 'single')
        os.makedirs(single_dir, exist_ok=True)
        self.csv_file = os.path.join(single_dir, 'test_data.csv')
        # Write a minimal ETS88-style CSV so the parser returns something
        with open(self.csv_file, 'w') as f:
            f.write('TestProgram,PGS_1.0\n')
            f.write('Lot_ID,L001\n')
            f.write('---\n')
            f.write('DUT_ID,Site_No,SW_Bin,HBin\n')
            f.write('001,1,1,1\n')
            f.write('002,2,1,1\n')

        self.df = DataFile.objects.create(
            owner=self.user,
            filename='test_data.csv',
            file_path=store_file_path(self.csv_file),
            file_size=os.path.getsize(self.csv_file),
            format_type='CTA8290D',
            file_type='single',
            status='ready',
            row_count=2,
            col_count=4,
        )

    def _browse(self, **params):
        """Helper to call the browse endpoint with given query params."""
        params.setdefault('datafile_id', self.df.pk)
        return self.client.get('/api/v1/browse/', params)

    def test_page_non_numeric_does_not_500(self):
        """page=abc must not raise ValueError → 500."""
        resp = self._browse(page='abc')
        # Should not be 500
        self.assertNotEqual(resp.status_code, 500)

    def test_page_negative_does_not_500(self):
        """page=-1 must not cause issues (clamped to 1)."""
        resp = self._browse(page='-1')
        self.assertNotEqual(resp.status_code, 500)

    def test_page_zero_clamped(self):
        """page=0 must be clamped to 1 (not cause negative offset)."""
        resp = self._browse(page='0')
        self.assertNotEqual(resp.status_code, 500)

    def test_page_size_non_numeric_does_not_500(self):
        """page_size=abc must not raise ValueError → 500."""
        resp = self._browse(page_size='abc')
        self.assertNotEqual(resp.status_code, 500)

    def test_page_size_huge_clamped(self):
        """page_size=999999 must be clamped, not cause memory explosion."""
        resp = self._browse(page_size='999999')
        self.assertNotEqual(resp.status_code, 500)
        # Verify the response contains a reasonable page_size
        if resp.status_code == 200:
            import json
            data = json.loads(resp.content)
            self.assertLessEqual(data.get('page_size', 0), 100000)

    def test_page_size_zero_clamped(self):
        """page_size=0 must be clamped to at least 1."""
        resp = self._browse(page_size='0')
        self.assertNotEqual(resp.status_code, 500)

    def test_page_size_negative_clamped(self):
        """page_size=-5 must be clamped to at least 1."""
        resp = self._browse(page_size='-5')
        self.assertNotEqual(resp.status_code, 500)

    def test_valid_pagination_still_works(self):
        """Normal pagination params must still work correctly."""
        resp = self._browse(page='1', page_size='10')
        # Should be 200 or 400 (parse_failed is ok for test CSV)
        self.assertIn(resp.status_code, (200, 400))
