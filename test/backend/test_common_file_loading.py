"""Tests for apps/common/file_loading.py parameter validation (defect 6).

Covers:
- Non-numeric file_id must raise FileLoadError (not ValueError → 500).
"""
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.common.file_loading import FileLoadError, load_user_file


class FileLoadingParamValidationTests(SimpleTestCase):
    """load_user_file must reject non-numeric file_id gracefully."""

    def _make_request(self, file_id_value):
        """Build a mock request with the given file_id in query_params."""
        request = MagicMock()
        request.data = {}
        request.query_params = {'file_id': file_id_value}
        request.user = MagicMock()
        request.user.pk = 1
        return request

    def test_non_numeric_file_id_raises_file_load_error(self):
        """file_id='abc' must raise FileLoadError, not ValueError."""
        request = self._make_request('abc')
        with self.assertRaises(FileLoadError) as ctx:
            load_user_file(request)
        self.assertEqual(ctx.exception.error_code, 'file_id_invalid')

    def test_float_file_id_raises_file_load_error(self):
        """file_id='1.5' must raise FileLoadError, not ValueError."""
        request = self._make_request('1.5')
        with self.assertRaises(FileLoadError) as ctx:
            load_user_file(request)
        self.assertEqual(ctx.exception.error_code, 'file_id_invalid')

    def test_empty_file_id_raises_required(self):
        """file_id='' must raise FileLoadError('file_id_required')."""
        request = self._make_request('')
        with self.assertRaises(FileLoadError) as ctx:
            load_user_file(request)
        self.assertEqual(ctx.exception.error_code, 'file_id_required')

    def test_none_file_id_raises_required(self):
        """No file_id at all must raise FileLoadError('file_id_required')."""
        request = MagicMock()
        request.data = {}
        request.query_params = {}
        request.user = MagicMock()
        with self.assertRaises(FileLoadError) as ctx:
            load_user_file(request)
        self.assertEqual(ctx.exception.error_code, 'file_id_required')
