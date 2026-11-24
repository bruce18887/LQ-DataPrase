import io
import json
import os
import shutil
import tempfile
import zipfile
from unittest import skipUnless
from unittest.mock import patch

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.datafiles.models import DataCombination, DataFile
from apps.datafiles.serializers import DataFileSerializer
from apps.datafiles.utils import resolve_file_path
from apps.datafiles.views import _helpers, _user_upload_dir


MIN_CSV = (
    '[GENERAL],\nTester_Type,CTA8290DPlus,\n[Data]\n'
    'col1,col2\nu1,u2\nmin1,min2\nmax1,max2\n1,2\n3,4\n'
).encode()


def zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


class CombinationImportTests(APITestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='combo-import-')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        User = get_user_model()
        self.owner = User.objects.create_user('combo_import_owner', password='x')
        self.client.force_authenticate(self.owner)
        self.combo = DataCombination.objects.create(owner=self.owner, name='gage')

    def _upload(self, filename, content, **fields):
        uploaded = SimpleUploadedFile(filename, content)
        return self.client.post('/api/v1/upload/', {
            'files': uploaded, **fields,
        }, format='multipart')

    def _write_batch_csv(self, batch_name, filename, content=MIN_CSV):
        path = os.path.join(_user_upload_dir(self.owner, 'batch'), batch_name, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(content)
        return path

    def _make_single(self, filename='a.csv'):
        path = os.path.join(_user_upload_dir(self.owner, 'single'), filename)
        with open(path, 'wb') as fh:
            fh.write(MIN_CSV)
        return DataFile.objects.create(
            owner=self.owner,
            filename=filename,
            file_path=path,
            file_size=len(MIN_CSV),
            format_type='CTA8290D',
            file_type='single',
            status='ready',
        )

    def test_single_upload_accepts_combination_batch_and_manual_tags(self):
        resp = self._upload(
            'a.csv', MIN_CSV,
            combination_id=str(self.combo.id),
            batch_no='BE01-2608130015',
            tags=json.dumps(['manual']),
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.combination_id, self.combo.id)
        self.assertEqual(row.batch_no, 'BE01-2608130015')
        self.assertEqual(row.tags, ['manual'])
        self.assertEqual(resp.data[0]['managed_tags'], [
            'gage', 'gage / BE01-2608130015',
        ])

    def test_invalid_combination_or_tags_fails_before_file_write(self):
        resp = self._upload(
            'bad.csv', MIN_CSV, combination_id='999', tags='["manual"]')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(DataFile.objects.filter(filename='bad.csv').exists())
        self.assertFalse(os.path.exists(os.path.join(
            _user_upload_dir(self.owner, 'single'), 'bad.csv')))

        resp = self._upload('bad2.csv', MIN_CSV, tags='not-json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(DataFile.objects.filter(filename='bad2.csv').exists())
        self.assertFalse(os.path.exists(os.path.join(
            _user_upload_dir(self.owner, 'single'), 'bad2.csv')))

    def test_zip_uses_parser_lot_id_and_does_not_use_zip_name(self):
        parsed = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {'lot_id': 'BE01-2608130015'}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed):
            resp = self._upload(
                'LOT-NAME.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
            )
        self.assertEqual(resp.status_code, 201, resp.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.batch_name, 'LOT-NAME')
        self.assertEqual(row.batch_no, 'BE01-2608130015')

    def test_zip_without_lot_id_leaves_batch_number_empty(self):
        parsed = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed):
            resp = self._upload(
                'LOT-NAME.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
            )
        self.assertEqual(resp.status_code, 201, resp.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.batch_no, '')
        self.assertEqual(resp.data[0]['managed_tags'], ['gage'])

    def test_new_zip_row_prefers_explicit_batch_over_parser_lot_id(self):
        parsed = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {'lot_id': 'BE01-PARSED'}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed):
            resp = self._upload(
                'LOT-EXPLICIT.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
                batch_no='BE01-EXPLICIT',
            )
        self.assertEqual(resp.status_code, 201, resp.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.batch_no, 'BE01-EXPLICIT')
        self.assertEqual(resp.data[0]['managed_tags'], [
            'gage', 'gage / BE01-EXPLICIT',
        ])

    def test_existing_zip_row_backfills_empty_batch_from_new_parser_lot_id(self):
        parsed_without_lot = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed_without_lot):
            first = self._upload(
                'LOT-BACKFILL.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
            )
        self.assertEqual(first.status_code, 201, first.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.batch_no, '')
        self.assertEqual(first.data[0]['managed_tags'], ['gage'])

        parsed_with_lot = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {'lot_id': 'BE01-BACKFILL'}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed_with_lot):
            second = self._upload(
                'LOT-BACKFILL.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
            )
        self.assertEqual(second.status_code, 201, second.data)
        row.refresh_from_db()
        self.assertEqual(row.batch_no, 'BE01-BACKFILL')
        self.assertEqual(DataFileSerializer(row).data['managed_tags'], [
            'gage', 'gage / BE01-BACKFILL',
        ])

    def test_existing_zip_row_keeps_batch_when_parser_lot_id_changes(self):
        parsed_original = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {'lot_id': 'BE01-ORIGINAL'}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed_original):
            first = self._upload(
                'LOT-KEEP.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
            )
        self.assertEqual(first.status_code, 201, first.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.batch_no, 'BE01-ORIGINAL')

        parsed_changed = (
            'CTA8290D', pd.DataFrame({'col1': [1], 'col2': [2]}),
            {'lot_id': 'BE01-CHANGED'}, 1, 2, 'PTS',
        )
        with patch.object(_helpers, 'parse_file_meta', return_value=parsed_changed):
            second = self._upload(
                'LOT-KEEP.zip', zip_bytes({'a.csv': MIN_CSV}),
                combination_id=str(self.combo.id),
            )
        self.assertEqual(second.status_code, 201, second.data)
        row.refresh_from_db()
        self.assertEqual(row.batch_no, 'BE01-ORIGINAL')
        self.assertEqual(DataFileSerializer(row).data['managed_tags'], [
            'gage', 'gage / BE01-ORIGINAL',
        ])

    def test_reupload_updates_combination_and_merges_manual_tags(self):
        first = self._upload('LOT-R.zip', zip_bytes({'a.csv': MIN_CSV}), tags='["old"]')
        self.assertEqual(first.status_code, 201, first.data)
        second = self._upload(
            'LOT-R.zip', zip_bytes({'a.csv': MIN_CSV}),
            combination_id=str(self.combo.id), tags='["new"]',
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(DataFile.objects.filter(filename='a.csv').count(), 1)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.combination_id, self.combo.id)
        self.assertEqual({tag.lower() for tag in row.tags}, {'old', 'new'})

    @skipUnless(os.name == 'nt', 'Windows paths are case-insensitive')
    def test_zip_reimport_matches_filename_case_and_refreshes_metadata(self):
        first = self._upload(
            'LOT-CASE.zip', zip_bytes({'a.csv': MIN_CSV}), tags='["old"]')
        self.assertEqual(first.status_code, 201, first.data)
        second_combo = DataCombination.objects.create(owner=self.owner, name='buyoff')
        second = self._upload(
            'LOT-CASE.zip', zip_bytes({'A.csv': MIN_CSV}),
            combination_id=str(second_combo.id),
            batch_no='BE01-CASE', tags='["new"]',
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(DataFile.objects.filter(batch_name='LOT-CASE').count(), 1)
        row = DataFile.objects.get(batch_name='LOT-CASE')
        self.assertEqual(row.combination_id, second_combo.id)
        self.assertEqual(row.batch_no, 'BE01-CASE')
        self.assertEqual({tag.lower() for tag in row.tags}, {'old', 'new'})
        self.assertEqual(DataFileSerializer(row).data['managed_tags'], [
            'buyoff', 'buyoff / BE01-CASE',
        ])

    def test_zip_with_duplicate_normalized_target_registers_one_row(self):
        resp = self._upload(
            'LOT-DUP.zip', zip_bytes({'a.csv': MIN_CSV, './a.csv': MIN_CSV}),
            combination_id=str(self.combo.id),
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(DataFile.objects.filter(batch_name='LOT-DUP').count(), 1)

    @skipUnless(os.name == 'nt', 'Windows paths are case-insensitive')
    def test_batch_dir_reimport_matches_filename_case_and_refreshes_metadata(self):
        path = self._write_batch_csv('LOT-DIR-CASE', 'a.csv')
        first = self.client.post('/api/v1/batch-dirs/import/', {
            'dir_name': 'LOT-DIR-CASE', 'tags': json.dumps(['old']),
        }, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        os.rename(path, os.path.join(os.path.dirname(path), 'A.csv'))

        second_combo = DataCombination.objects.create(owner=self.owner, name='buyoff')
        second = self.client.post('/api/v1/batch-dirs/import/', {
            'dir_name': 'LOT-DIR-CASE',
            'combination_id': second_combo.id,
            'batch_no': 'BE01-DIR-CASE',
            'tags': json.dumps(['new']),
        }, format='json')
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(DataFile.objects.filter(batch_name='LOT-DIR-CASE').count(), 1)
        row = DataFile.objects.get(batch_name='LOT-DIR-CASE')
        self.assertEqual(row.combination_id, second_combo.id)
        self.assertEqual(row.batch_no, 'BE01-DIR-CASE')
        self.assertEqual({tag.lower() for tag in row.tags}, {'old', 'new'})
        self.assertEqual(DataFileSerializer(row).data['managed_tags'], [
            'buyoff', 'buyoff / BE01-DIR-CASE',
        ])

    def test_batch_dir_import_and_reimport_update_metadata_without_duplicates(self):
        self._write_batch_csv('LOT-DIR', 'a.csv')
        first = self.client.post('/api/v1/batch-dirs/import/', {
            'dir_name': 'LOT-DIR',
            'combination_id': str(self.combo.id),
            'batch_no': ' BE01-1 ',
            'tags': json.dumps(['manual']),
        }, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        row = DataFile.objects.get(filename='a.csv')
        self.assertEqual(row.combination_id, self.combo.id)
        self.assertEqual(row.batch_no, 'BE01-1')
        self.assertEqual(row.tags, ['manual'])

        second_combo = DataCombination.objects.create(owner=self.owner, name='buyoff')
        second = self.client.post('/api/v1/batch-dirs/import/', {
            'dir_name': 'LOT-DIR',
            'combination_id': second_combo.id,
            'batch_no': 'BE01-2',
            'tags': json.dumps(['Manual', 'new']),
        }, format='json')
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data, [])
        self.assertEqual(DataFile.objects.filter(filename='a.csv').count(), 1)
        row.refresh_from_db()
        self.assertEqual(row.combination_id, second_combo.id)
        self.assertEqual(row.batch_no, 'BE01-2')
        self.assertEqual(row.tags, ['manual', 'new'])

    def test_batch_dir_import_rejects_other_owners_combination(self):
        path = self._write_batch_csv('LOT-DIR', 'a.csv')
        other = get_user_model().objects.create_user('combo_import_other', password='x')
        theirs = DataCombination.objects.create(owner=other, name='theirs')
        resp = self.client.post('/api/v1/batch-dirs/import/', {
            'dir_name': 'LOT-DIR', 'combination_id': theirs.id,
        }, format='json')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(DataFile.objects.filter(filename='a.csv').exists())
        self.assertTrue(os.path.exists(path))

    def test_combine_writes_metadata_and_uncombine_preserves_it(self):
        row = self._make_single()
        resp = self.client.post('/api/v1/files/combine/', {
            'ids': [row.id],
            'batch_name': 'LOT-COMBINED',
            'combination_id': self.combo.id,
            'batch_no': ' BE01-3 ',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        row.refresh_from_db()
        self.assertEqual(row.combination_id, self.combo.id)
        self.assertEqual(row.batch_no, 'BE01-3')
        self.assertEqual(row.file_type, 'batch')

        resp = self.client.post('/api/v1/files/uncombine/', {
            'ids': [row.id],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        row.refresh_from_db()
        self.assertEqual(row.file_type, 'single')
        self.assertEqual(row.batch_name, '')
        self.assertEqual(row.combination_id, self.combo.id)
        self.assertEqual(row.batch_no, 'BE01-3')
        self.assertTrue(os.path.exists(resolve_file_path(row.file_path)))

    def test_combine_rejects_other_owners_combination_before_moving(self):
        row = self._make_single()
        source = resolve_file_path(row.file_path)
        other = get_user_model().objects.create_user('combo_import_other', password='x')
        theirs = DataCombination.objects.create(owner=other, name='theirs')
        resp = self.client.post('/api/v1/files/combine/', {
            'ids': [row.id],
            'batch_name': 'LOT-COMBINED',
            'combination_id': theirs.id,
        }, format='json')
        self.assertEqual(resp.status_code, 404)
        row.refresh_from_db()
        self.assertEqual(row.file_type, 'single')
        self.assertIsNone(row.combination_id)
        self.assertTrue(os.path.exists(source))
