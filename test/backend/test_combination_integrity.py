import io
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.datafiles.models import DataCombination, DataFile
from apps.datafiles.views import _helpers

MIN_CSV = (
    b'[GENERAL],\nTester_Type,CTA8290DPlus,\n[Data]\n'
    b'col1,col2\nu1,u2\nmin1,min2\nmax1,max2\n1,2\n'
)


class CombinationIntegrityTests(TransactionTestCase):
    client_class = APIClient

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='combo-integrity-')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        User = get_user_model()
        self.owner = User.objects.create_user('integrity_owner', password='x')
        self.client.force_authenticate(self.owner)
        self.combo = DataCombination.objects.create(owner=self.owner, name='gage')

    def upload(self, name='a.csv', **fields):
        return self.client.post('/api/v1/upload/', {
            'file': SimpleUploadedFile(name, MIN_CSV), **fields,
        }, format='multipart')

    def test_same_name_single_reupload_reuses_one_row_and_merges_metadata(self):
        first = self.upload('a.csv', tags=json.dumps(['old']))
        self.assertEqual(first.status_code, 201, first.data)
        original = DataFile.objects.get(filename='a.csv')
        second = self.upload(
            'a.csv', combination_id=self.combo.id, batch_no=' BE01-1 ',
            tags=json.dumps(['new']),
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(DataFile.objects.filter(filename='a.csv').count(), 1)
        original.refresh_from_db()
        self.assertEqual(original.pk, second.data[0]['id'])
        self.assertEqual(original.combination_id, self.combo.id)
        self.assertEqual(original.batch_no, 'BE01-1')
        self.assertEqual(original.tags, ['old', 'new'])
        self.assertFalse(any('_17' in name for name in os.listdir(
            os.path.dirname(_helpers.resolve_file_path(original.file_path)))))

    @skipUnless(os.name == 'nt', 'Windows paths are case-insensitive')
    def test_case_only_single_reupload_reuses_one_row(self):
        self.assertEqual(self.upload('case.csv').status_code, 201)
        second = self.upload('CASE.csv', batch_no='BE01-CASE')
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(DataFile.objects.filter(file_type='single').count(), 1)
        self.assertEqual(DataFile.objects.get().batch_no, 'BE01-CASE')

    def test_refresh_after_read_deletion_does_not_resurrect_row(self):
        self.assertEqual(self.upload('a.csv').status_code, 201)
        row = DataFile.objects.get(filename='a.csv')
        def delete_current(*args):
            DataFile.objects.filter(pk=row.pk).delete()
            return None

        with patch(
            'apps.datafiles.views.import_coordinator._refresh_in_transaction',
            side_effect=delete_current,
        ):
            from apps.datafiles.views.import_coordinator import import_or_refresh_file
            result = import_or_refresh_file(
                self.owner, _helpers.resolve_file_path(row.file_path), 'single',
                parsed=('CTA8290D', None, {}, 0, 0, ''),
                combination=self.combo, tags=['new'],
            )
        self.assertIsNone(result)
        self.assertFalse(DataFile.objects.filter(pk=row.pk).exists())

    def test_import_path_lock_serializes_threads(self):
        from apps.datafiles.views.import_coordinator import import_path_lock
        active = 0
        peak = 0
        guard = threading.Lock()

        def worker():
            nonlocal active, peak
            with import_path_lock(self.owner, 'single/a.csv'):
                with guard:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.08)
                with guard:
                    active -= 1

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(peak, 1)

    def test_assign_file_disappearing_after_read_returns_404_and_rolls_back(self):
        row = DataFile.objects.create(
            owner=self.owner, filename='a.csv', file_path='single/a.csv',
            file_size=1, format_type='CTA8290D', status='ready',
        )
        url = '/api/v1/files/assign_combination/'
        original_filter = DataFile.objects.filter
        calls = 0

        def delete_after_first_read(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                return original_filter(*args, **kwargs)
            rows = list(original_filter(*args, **kwargs))
            original_filter(pk=row.pk).delete()
            return rows

        with patch('apps.datafiles.views.combination_views.DataFile.objects.filter',
                   side_effect=delete_after_first_read):
            self.client.raise_request_exception = False
            resp = self.client.post(url, {
                'file_ids': [row.pk], 'combination_id': self.combo.pk,
            }, format='json')
        self.assertEqual(resp.status_code, 404, resp.data)
        row.refresh_from_db()
        self.assertIsNone(row.combination_id)

    def test_assign_deleted_combination_returns_404_without_changes(self):
        row = DataFile.objects.create(
            owner=self.owner, filename='a.csv', file_path='single/a.csv',
            file_size=1, format_type='CTA8290D', status='ready',
        )
        original = DataCombination.objects.get(pk=self.combo.pk)
        with patch('apps.datafiles.views.combination_views.get_object_or_404',
                   side_effect=lambda *a, **kw: self._delete_combo(original, *a, **kw)):
            self.client.raise_request_exception = False
            resp = self.client.post('/api/v1/files/assign_combination/', {
                'file_ids': [row.pk], 'combination_id': self.combo.pk,
            }, format='json')
        self.assertEqual(resp.status_code, 404, resp.data)
        row.refresh_from_db()
        self.assertIsNone(row.combination_id)

    def _delete_combo(self, combo, *args, **kwargs):
        result = combo.__class__.objects.get(pk=combo.pk)
        combo.delete()
        return result

    def test_generic_patch_cannot_change_batch_no(self):
        self.assertEqual(self.upload('a.csv', batch_no='BE01-1').status_code, 201)
        row = DataFile.objects.get(filename='a.csv')
        for value in ('BE01-2', 'bad/value', 'bad\\value', 'bad\x01', 'x' * 41, 123):
            with self.subTest(value=value):
                resp = self.client.patch(f'/api/v1/files/{row.pk}/', {
                    'batch_no': value,
                }, format='json')
                self.assertEqual(resp.status_code, 200, resp.data)
                row.refresh_from_db()
                self.assertEqual(row.batch_no, 'BE01-1')

    def test_zip_and_directory_share_import_lock(self):
        from apps.datafiles.views.import_coordinator import import_lock_key
        batch = os.path.join(_helpers._user_upload_dir(self.owner, 'batch'), 'LOT')
        self.assertEqual(import_lock_key(self.owner, batch), import_lock_key(self.owner, batch))

    def _request(self):
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().post(
            '/api/v1/batch-dirs/import/', json.dumps({'dir_name': 'LOT'}),
            content_type='application/json',
        )
        from rest_framework.test import force_authenticate
        force_authenticate(request, user=get_user_model().objects.get(pk=self.owner.pk))
        return request

    def test_two_concurrent_directory_imports_register_one_row(self):
        from django.db import connections
        from apps.datafiles.views.batch_views import BatchDirImportView
        path = os.path.join(_helpers._user_upload_dir(self.owner, 'batch'), 'LOT', 'a.csv')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(MIN_CSV)
        view = BatchDirImportView()
        barrier = threading.Barrier(2)

        def run():
            barrier.wait()
            return view.post(view.initialize_request(self._request()))

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: run(), range(2)))
        self.assertTrue(all(resp.status_code == 201 for resp in responses), [r.data for r in responses])
        self.assertEqual(DataFile.objects.filter(filename='a.csv').count(), 1)
        connections.close_all()
