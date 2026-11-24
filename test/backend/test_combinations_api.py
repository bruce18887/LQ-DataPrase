from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APITestCase

from apps.datafiles.models import DataCombination, DataFile


class CombinationApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('combo_api_owner', password='x')
        self.other = User.objects.create_user('combo_api_other', password='x')
        self.client.force_authenticate(self.owner)

    def _file(self, owner, filename, **extra):
        return DataFile.objects.create(
            owner=owner, filename=filename,
            file_path=f'data/{owner.username}/single/{filename}',
            file_size=1, format_type='CTA8290D', status='ready', **extra,
        )

    def test_create_list_rename_and_case_insensitive_duplicate(self):
        resp = self.client.post('/api/v1/combinations/', {'name': 'Gage'}, format='json')
        self.assertEqual(resp.status_code, 201)
        combo_id = resp.data['id']
        self._file(self.owner, 'batched.csv', combination_id=combo_id, batch_no='BE01-1')
        self._file(self.owner, 'unbatched.csv', combination_id=combo_id)
        dup = self.client.post('/api/v1/combinations/', {'name': 'gage'}, format='json')
        self.assertEqual(dup.status_code, 400)
        self.assertEqual(dup.data['code'], 'duplicate_combination')
        renamed = self.client.patch(
            f'/api/v1/combinations/{combo_id}/', {'name': 'Gage Lab'}, format='json')
        self.assertEqual(renamed.status_code, 200)
        listed = self.client.get('/api/v1/combinations/')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([row['name'] for row in listed.data], ['Gage Lab'])
        self.assertEqual(listed.data[0]['file_count'], 2)
        self.assertEqual(listed.data[0]['batched_file_count'], 1)
        self.assertEqual(listed.data[0]['unbatched_file_count'], 1)
        other_combo = self.client.post(
            '/api/v1/combinations/', {'name': 'Other'}, format='json')
        self.assertEqual(other_combo.status_code, 201)
        duplicate_rename = self.client.patch(
            f'/api/v1/combinations/{combo_id}/', {'name': 'other'}, format='json')
        self.assertEqual(duplicate_rename.status_code, 400)
        self.assertEqual(duplicate_rename.data['code'], 'duplicate_combination')

    def test_create_save_time_duplicate_rolls_back(self):
        self.client.raise_request_exception = False
        original_save = DataCombination.save

        def save_then_fail(instance, *args, **kwargs):
            original_save(instance, *args, **kwargs)
            raise IntegrityError('simulated unique constraint race')

        with mock.patch.object(
            DataCombination, 'save', autospec=True, side_effect=save_then_fail,
        ):
            response = self.client.post(
                '/api/v1/combinations/', {'name': 'gage'}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get('code'), 'duplicate_combination')
        self.assertFalse(DataCombination.objects.filter(
            owner=self.owner, name_key='gage').exists())

    def test_rename_save_time_duplicate_rolls_back(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        original_updated_at = combo.updated_at
        self.client.raise_request_exception = False
        original_save = DataCombination.save

        def save_then_fail(instance, *args, **kwargs):
            original_save(instance, *args, **kwargs)
            raise IntegrityError('simulated unique constraint race')

        with mock.patch.object(
            DataCombination, 'save', autospec=True, side_effect=save_then_fail,
        ):
            response = self.client.patch(
                f'/api/v1/combinations/{combo.id}/',
                {'name': 'caliper'}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get('code'), 'duplicate_combination')
        combo.refresh_from_db()
        self.assertEqual(combo.name, 'gage')
        self.assertEqual(combo.updated_at, original_updated_at)

    def test_rename_recomputes_tags_without_touching_file_row(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        row = self._file(self.owner, 'a.csv', combination=combo, batch_no='BE01-1', tags=['manual'])
        before = row.updated_at
        resp = self.client.patch(
            f'/api/v1/combinations/{combo.id}/', {'name': 'buyoff'}, format='json')
        self.assertEqual(resp.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.updated_at, before)
        detail = self.client.get(f'/api/v1/files/{row.id}/')
        self.assertEqual(detail.data['managed_tags'], ['buyoff', 'buyoff / BE01-1'])
        self.assertEqual(detail.data['tags'], ['manual'])

    def test_delete_combination_keeps_file_and_manual_tags(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        row = self._file(self.owner, 'a.csv', combination=combo, batch_no='BE01-1', tags=['manual'])
        resp = self.client.delete(f'/api/v1/combinations/{combo.id}/')
        self.assertEqual(resp.status_code, 204)
        row.refresh_from_db()
        self.assertIsNone(row.combination)
        self.assertEqual(row.batch_no, 'BE01-1')
        self.assertEqual(row.tags, ['manual'])

    def test_bulk_assign_is_owner_scoped_and_atomic(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        mine = self._file(self.owner, 'mine.csv')
        theirs = self._file(self.other, 'theirs.csv')
        resp = self.client.post('/api/v1/files/assign_combination/', {
            'file_ids': [mine.id, theirs.id, theirs.id + 1000],
            'combination_id': combo.id,
            'batch_no': 'BE01-1',
        }, format='json')
        self.assertEqual(resp.status_code, 404)
        mine.refresh_from_db()
        self.assertIsNone(mine.combination)

    def test_bulk_assign_preserves_clears_and_sets_batch_number(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        row = self._file(self.owner, 'a.csv', batch_no='OLD')
        url = '/api/v1/files/assign_combination/'
        self.client.post(url, {'file_ids': [row.id], 'combination_id': combo.id}, format='json')
        row.refresh_from_db()
        self.assertEqual(row.batch_no, 'OLD')
        self.client.post(url, {
            'file_ids': [row.id], 'combination_id': combo.id, 'batch_no': '',
        }, format='json')
        row.refresh_from_db()
        self.assertEqual(row.batch_no, '')
        self.client.post(url, {
            'file_ids': [row.id], 'combination_id': combo.id, 'batch_no': ' BE01-1 ',
        }, format='json')
        row.refresh_from_db()
        self.assertEqual(row.batch_no, 'BE01-1')
        self.client.post(url, {
            'file_ids': [row.id], 'combination_id': combo.id, 'batch_no': None,
        }, format='json')
        row.refresh_from_db()
        self.assertEqual(row.batch_no, '')
        self.client.post(url, {
            'file_ids': [row.id], 'combination_id': None,
        }, format='json')
        row.refresh_from_db()
        self.assertIsNone(row.combination)
        self.assertEqual(row.batch_no, '')

    def test_bulk_assign_rejects_non_integer_combination_ids_without_changes(self):
        combo = DataCombination.objects.create(owner=self.owner, name='gage')
        invalid_ids = [
            True, False, float(combo.id), float(combo.id) + 0.9, str(combo.id),
        ]
        for index, invalid_id in enumerate(invalid_ids):
            with self.subTest(combination_id=invalid_id):
                row = self._file(
                    self.owner, f'invalid-{index}.csv',
                    combination=combo, batch_no='OLD',
                )
                original_updated_at = row.updated_at
                response = self.client.post('/api/v1/files/assign_combination/', {
                    'file_ids': [row.id],
                    'combination_id': invalid_id,
                    'batch_no': 'NEW',
                }, format='json')

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data.get('code'), 'validation_error')
                row.refresh_from_db()
                self.assertEqual(row.combination_id, combo.id)
                self.assertEqual(row.batch_no, 'OLD')
                self.assertEqual(row.updated_at, original_updated_at)

    def test_other_users_combination_is_not_visible_or_assignable(self):
        theirs = DataCombination.objects.create(owner=self.other, name='gage')
        mine = self._file(self.owner, 'mine.csv')
        resp = self.client.get('/api/v1/combinations/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])
        for method in ('get', 'patch', 'delete'):
            blocked = getattr(self.client, method)(
                f'/api/v1/combinations/{theirs.id}/',
                *([{'name': 'stolen'}] if method == 'patch' else []),
                **({'format': 'json'} if method == 'patch' else {}),
            )
            self.assertEqual(blocked.status_code, 404)
        self.assertTrue(DataCombination.objects.filter(pk=theirs.pk).exists())
        resp = self.client.post('/api/v1/files/assign_combination/', {
            'file_ids': [mine.id], 'combination_id': theirs.id,
        }, format='json')
        self.assertEqual(resp.status_code, 404)
        mine.refresh_from_db()
        self.assertIsNone(mine.combination)
