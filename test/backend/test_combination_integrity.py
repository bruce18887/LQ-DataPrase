import io
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
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

    def test_single_reupload_write_failure_preserves_old_file_and_row(self):
        self.assertEqual(self.upload('a.csv', batch_no='BE01-OLD').status_code, 201)
        row = DataFile.objects.get(filename='a.csv')
        path = _helpers.resolve_file_path(row.file_path)

        real_open = open

        @contextmanager
        def broken_write_open(*args, **kwargs):
            mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
            fh = real_open(*args, **kwargs)
            if 'w' not in mode:
                yield fh
                return
            class BrokenWriter:
                def write(self, chunk):
                    partial = chunk[:max(1, len(chunk) // 2)]
                    fh.write(partial)
                    raise OSError('simulated upload write failure')

                def __getattr__(self, name):
                    return getattr(fh, name)

            try:
                yield BrokenWriter()
            finally:
                fh.close()

        self.client.raise_request_exception = False
        with patch('builtins.open', side_effect=broken_write_open):
            resp = self.client.post('/api/v1/upload/', {
                'file': SimpleUploadedFile('a.csv', b'partial replacement'),
            }, format='multipart')
        self.assertGreaterEqual(resp.status_code, 400)
        with open(path, 'rb') as fh:
            self.assertEqual(fh.read(), MIN_CSV)
        row.refresh_from_db()
        self.assertEqual(row.batch_no, 'BE01-OLD')
        self.assertEqual(DataFile.objects.count(), 1)
        self.assertEqual(os.listdir(os.path.dirname(path)), ['a.csv'])

    def test_single_reupload_parse_failure_preserves_old_file_and_row(self):
        self.assertEqual(self.upload('a.csv', batch_no='BE01-OLD').status_code, 201)
        row = DataFile.objects.get(filename='a.csv')
        path = _helpers.resolve_file_path(row.file_path)
        self.client.raise_request_exception = False
        with patch('apps.datafiles.views._helpers.parse_file_meta',
                   side_effect=ValueError('simulated parse failure')):
            resp = self.client.post('/api/v1/upload/', {
                'file': SimpleUploadedFile('a.csv', MIN_CSV + b'9,10\n'),
            }, format='multipart')
        self.assertGreaterEqual(resp.status_code, 400)
        with open(path, 'rb') as fh:
            self.assertEqual(fh.read(), MIN_CSV)
        row.refresh_from_db()
        self.assertEqual(row.batch_no, 'BE01-OLD')
        self.assertEqual(DataFile.objects.count(), 1)
        self.assertEqual(os.listdir(os.path.dirname(path)), ['a.csv'])

    def test_single_reupload_replaces_final_path_atomically_after_parsing(self):
        self.assertEqual(self.upload('a.csv', batch_no='BE01-OLD').status_code, 201)
        original = DataFile.objects.get(filename='a.csv')
        original_pk = original.pk
        path = _helpers.resolve_file_path(original.file_path)
        replacement = MIN_CSV + b'3,4\n'
        real_replace = os.replace
        real_parse = _helpers.parse_file_meta
        events = []

        def checked_parse(file_path):
            events.append(('parse', file_path))
            return real_parse(file_path)

        def checked_replace(src, dst):
            events.append(('replace', src, dst))
            self.assertEqual(os.path.dirname(src), os.path.dirname(dst))
            self.assertNotEqual(os.path.basename(src), 'a.csv')
            self.assertEqual(dst, path)
            with open(dst, 'rb') as fh:
                self.assertEqual(fh.read(), MIN_CSV)
            with open(src, 'rb') as fh:
                self.assertEqual(fh.read(), replacement)
            return real_replace(src, dst)

        with patch('apps.datafiles.views._helpers.os.replace', side_effect=checked_replace), \
             patch('apps.datafiles.views._helpers.parse_file_meta', side_effect=checked_parse):
            resp = self.client.post('/api/v1/upload/', {
                'file': SimpleUploadedFile('a.csv', replacement),
            }, format='multipart')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual([event[0] for event in events], ['parse', 'replace'])
        parse_path = events[0][1]
        self.assertNotEqual(os.path.basename(parse_path), 'a.csv')
        self.assertEqual(events[1][2], path)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.pk, original_pk)
        self.assertEqual(resp.data[0]['id'], original_pk)
        self.assertEqual(os.path.basename(path), 'a.csv')
        with open(path, 'rb') as fh:
            self.assertEqual(fh.read(), replacement)
        self.assertEqual(os.listdir(os.path.dirname(path)), ['a.csv'])
        self.assertEqual(DataFile.objects.count(), 1)

    def test_single_upload_registers_final_basename(self):
        registered = []
        real_register = _helpers._register_file

        def checked_register(user, file_path, *args, **kwargs):
            registered.append(os.path.basename(file_path))
            return real_register(user, file_path, *args, **kwargs)

        with patch('apps.datafiles.views._helpers._register_file',
                   side_effect=checked_register):
            resp = self.upload('a.csv')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(registered, ['a.csv'])

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
        from django.db.models import QuerySet
        original_update = QuerySet.update
        deleted = False

        def delete_before_update(queryset, **kwargs):
            nonlocal deleted
            if (queryset.model is DataFile and 'combination_id' in kwargs
                    and not deleted):
                DataFile.objects.filter(pk=row.pk).delete()
                deleted = True
            return original_update(queryset, **kwargs)

        with patch.object(QuerySet, 'update', delete_before_update):
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

    def test_assign_combination_deleted_before_update_returns_404_and_rolls_back(self):
        row = DataFile.objects.create(
            owner=self.owner, filename='a.csv', file_path='single/a.csv',
            file_size=1, format_type='CTA8290D', status='ready',
        )
        from django.db.models import QuerySet
        original_update = QuerySet.update
        deleted = False

        def delete_combo_before_update(queryset, **kwargs):
            nonlocal deleted
            if queryset.model is DataFile and 'combination_id' in kwargs and not deleted:
                self.combo.delete()
                deleted = True
            return original_update(queryset, **kwargs)

        with patch.object(QuerySet, 'update', delete_combo_before_update):
            self.client.raise_request_exception = False
            resp = self.client.post('/api/v1/files/assign_combination/', {
                'file_ids': [row.pk], 'combination_id': self.combo.pk,
            }, format='json')
        self.assertEqual(resp.status_code, 404, resp.data)
        row.refresh_from_db()
        self.assertIsNone(row.combination_id)

    def test_refresh_locks_and_rereads_current_row(self):
        from django.db.models.query import ModelIterable
        from apps.datafiles.views.import_coordinator import import_or_refresh_file

        self.assertEqual(self.upload('a.csv').status_code, 201)
        row = DataFile.objects.get(filename='a.csv')
        real_iter = ModelIterable.__iter__
        locked_reads = []

        def checked_iter(iterable):
            queryset = iterable.queryset
            if queryset.model is DataFile:
                locked_reads.append(queryset.query.select_for_update)
            yield from real_iter(iterable)

        with patch.object(ModelIterable, '__iter__', checked_iter):
            refreshed = import_or_refresh_file(
                self.owner, _helpers.resolve_file_path(row.file_path), 'single',
                parsed=('CTA8290D', None, {}, 0, 0, ''), batch_no_override='BE01-NEW',
            )
        self.assertIsNotNone(refreshed)
        self.assertGreaterEqual(sum(locked_reads), 1)
        row.refresh_from_db()
        self.assertEqual(row.batch_no, 'BE01-NEW')

    def test_refresh_conditional_update_zero_rows_does_not_report_success(self):
        self.assertEqual(self.upload('a.csv').status_code, 201)
        row = DataFile.objects.get(filename='a.csv')
        original_pk = row.pk
        from django.db.models import QuerySet
        original_update = QuerySet.update

        def delete_then_report_zero(queryset, **kwargs):
            if queryset.model is DataFile and 'batch_no' in kwargs:
                DataFile.objects.filter(pk=original_pk).delete()
                return 0
            return original_update(queryset, **kwargs)

        with patch.object(QuerySet, 'update', delete_then_report_zero):
            from apps.datafiles.views.import_coordinator import import_or_refresh_file
            result = import_or_refresh_file(
                self.owner, _helpers.resolve_file_path(row.file_path), 'single',
                parsed=('CTA8290D', None, {}, 0, 0, ''), batch_no_override='BE01-NEW',
            )
        self.assertIsNone(result)
        self.assertFalse(DataFile.objects.filter(pk=original_pk).exists())

    def test_single_upload_missing_registration_retries_then_returns_conflict(self):
        from apps.datafiles.views import file_views

        with patch.object(file_views, 'import_or_refresh_file', return_value=None) as coordinator:
            resp = self.upload('a.csv')
        self.assertEqual(coordinator.call_count, 2)
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'file_registration_failed')
        self.assertFalse(DataFile.objects.exists())

    def test_directory_import_reports_paths_that_disappear_during_registration(self):
        from apps.datafiles.views.batch_views import BatchDirImportView

        path = os.path.join(_helpers._user_upload_dir(self.owner, 'batch'), 'LOT', 'a.csv')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(MIN_CSV)
        with patch('apps.datafiles.views.batch_views.import_or_refresh_file', return_value=None):
            resp = BatchDirImportView().post(BatchDirImportView().initialize_request(self._request()))
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'batch_import_incomplete')
        self.assertEqual(resp.data['failed_paths'], [path])

    def test_zip_import_reports_paths_that_disappear_during_registration(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('a.csv', MIN_CSV)
        archive.seek(0)
        with patch('apps.datafiles.views.import_coordinator.import_or_refresh_file', return_value=None):
            resp = self.client.post('/api/v1/upload/', {
                'file': SimpleUploadedFile('LOT.zip', archive.read()),
            }, format='multipart')
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'batch_import_incomplete')
        self.assertEqual(len(resp.data['failed_paths']), 1)
        self.assertTrue(resp.data['failed_paths'][0].endswith('a.csv'))

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

    def test_normalize_tags_empty_string_and_invalid_non_lists(self):
        from rest_framework import serializers
        from apps.datafiles.serializers import normalize_tags

        self.assertEqual(normalize_tags(''), [])
        for raw in ({}, {'tag': 'value'}, 0, False):
            with self.subTest(raw=raw), self.assertRaises(serializers.ValidationError):
                normalize_tags(raw)

    def test_zip_and_directory_share_import_lock(self):
        from apps.datafiles.views.import_coordinator import import_lock_key
        batch = os.path.join(_helpers._user_upload_dir(self.owner, 'batch'), 'LOT')
        self.assertEqual(import_lock_key(self.owner, batch), import_lock_key(self.owner, batch))

    def test_import_lock_lives_outside_user_data_directories(self):
        import hashlib
        from django.conf import settings
        from apps.datafiles.views.import_coordinator import import_path_lock

        single = os.path.join(_helpers._user_upload_dir(self.owner, 'single'), 'a.csv')
        batch = os.path.join(_helpers._user_upload_dir(self.owner, 'batch'), 'LOT')
        user_data_root = os.path.abspath(os.path.join(self.media, 'data'))
        for target in (single, batch):
            with self.subTest(target=target):
                from apps.datafiles.views.import_coordinator import import_lock_key
                expected_name = hashlib.sha256(
                    f'{self.owner.pk}\0{os.path.normcase(os.path.normpath(target))}'.encode('utf-8')
                ).hexdigest() + '.lock'
                with import_path_lock(self.owner, target):
                    lock_path = import_lock_key(self.owner, target)
                    self.assertTrue(os.path.isfile(lock_path))
                    self.assertEqual(os.path.basename(lock_path), expected_name)
                    self.assertNotEqual(
                        os.path.commonpath((os.path.abspath(lock_path), user_data_root)),
                        user_data_root,
                    )
                self.assertTrue(os.path.isfile(lock_path), '导入锁文件必须持久保留')
                for data_dir in (
                    _helpers._user_upload_dir(self.owner, 'single'),
                    _helpers._user_upload_dir(self.owner, 'batch'),
                ):
                    self.assertNotEqual(
                        os.path.commonpath((os.path.abspath(lock_path), os.path.abspath(data_dir))),
                        os.path.abspath(data_dir),
                    )
                self.assertEqual(settings.MEDIA_ROOT, self.media)

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
