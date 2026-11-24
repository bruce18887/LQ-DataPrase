from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.datafiles.models import DataCombination, DataFile


class CombinationFileQueryTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('combo_query_owner', password='x')
        self.client.force_authenticate(self.owner)
        self.gage = DataCombination.objects.create(owner=self.owner, name='gage')
        self.buyoff = DataCombination.objects.create(owner=self.owner, name='buyoff')
        self.a = self._file('a.csv', self.gage, 'BE01-1', ['shared'])
        self.b = self._file('b.csv', self.buyoff, 'BE01-1', ['shared'])
        self.c = self._file('c.csv', self.gage, '', [])

    def _file(self, name, combination, batch_no, tags):
        return DataFile.objects.create(
            owner=self.owner, filename=name,
            file_path=f'data/{self.owner.username}/single/{name}',
            file_size=1, format_type='CTA8290D', status='ready',
            combination=combination, batch_no=batch_no, tags=tags,
        )

    def test_file_detail_contains_structured_fields_and_managed_tags(self):
        resp = self.client.get(f'/api/v1/files/{self.a.id}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['combination_id'], self.gage.id)
        self.assertEqual(resp.data['combination_name'], 'gage')
        self.assertEqual(resp.data['batch_no'], 'BE01-1')
        self.assertEqual(resp.data['managed_tags'], ['gage', 'gage / BE01-1'])
        self.assertEqual(resp.data['tags'], ['shared'])

    def test_combination_and_batch_filters(self):
        resp = self.client.get('/api/v1/files/', {
            'combination_id': self.gage.id, 'batch_no': 'be01-1', 'include_hidden': 1,
        })
        self.assertEqual([row['id'] for row in resp.data['results']], [self.a.id])

    def test_managed_tag_exact_filter(self):
        resp = self.client.get('/api/v1/files/', {
            'tag': 'gage / be01-1', 'include_hidden': 1,
        })
        self.assertEqual([row['id'] for row in resp.data['results']], [self.a.id])

    def test_search_does_not_bypass_combination_filter(self):
        resp = self.client.get('/api/v1/files/', {
            'combination_id': self.gage.id, 'search': 'shared', 'include_hidden': 1,
        })
        self.assertEqual([row['id'] for row in resp.data['results']], [self.a.id])

    def test_search_matches_full_managed_tag(self):
        resp = self.client.get('/api/v1/files/', {
            'combination_id': self.gage.id,
            'search': 'gage / BE01-1',
            'include_hidden': 1,
        })
        self.assertEqual([row['id'] for row in resp.data['results']], [self.a.id])

    def test_list_tags_returns_manual_and_managed_sets(self):
        resp = self.client.post('/api/v1/files/list_tags/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('shared', resp.data['tags'])
        self.assertIn('gage', resp.data['tags'])
        self.assertIn('gage / BE01-1', resp.data['managed_tags'])
        self.assertNotIn('shared', resp.data['managed_tags'])

    def test_options_adds_scalar_combination_fields_without_tags(self):
        resp = self.client.get('/api/v1/files/options/', {'include_error': 1})
        self.assertEqual(resp.status_code, 200, resp.data)
        row = next(item for item in resp.data['results'] if item['id'] == self.a.id)
        self.assertEqual(row['combination_id'], self.gage.id)
        self.assertEqual(row['combination_name'], 'gage')
        self.assertEqual(row['batch_no'], 'BE01-1')
        self.assertNotIn('combination__name', row)
        self.assertNotIn('tags', row)
        self.assertNotIn('managed_tags', row)

    def test_list_serializer_exposes_complete_structured_fields(self):
        resp = self.client.get('/api/v1/files/', {'include_hidden': 1})
        self.assertEqual(resp.status_code, 200, resp.data)
        row = next(item for item in resp.data['results'] if item['id'] == self.a.id)
        self.assertEqual(set(row), {
            'id', 'owner', 'filename', 'file_size', 'format_type',
            'format_type_display', 'file_type', 'file_type_display',
            'batch_name', 'sub_batch', 'row_count', 'col_count', 'program_name',
            'product_code', 'source_mtime', 'tags', 'stage', 'data_date',
            'combination_id', 'combination_name', 'batch_no', 'managed_tags',
            'is_hidden', 'status', 'status_display', 'created_at', 'updated_at',
        })
        self.assertEqual(row['combination_name'], 'gage')
        self.assertEqual(row['managed_tags'], ['gage', 'gage / BE01-1'])

    def test_list_tags_prefix_is_case_insensitive_and_hides_owner_boundaries(self):
        self.a.tags = ['Gage', 'Manual']
        self.a.save(update_fields=['tags'])
        hidden = self._file('hidden.csv', self.gage, '', ['HiddenOnly'])
        hidden.is_hidden = True
        hidden.save(update_fields=['is_hidden'])
        other = get_user_model().objects.create_user('combo_query_other', password='x')
        DataFile.objects.create(
            owner=other, filename='other.csv', file_path='other.csv', file_size=1,
            format_type='CTA8290D', status='ready', tags=['OtherOnly'],
        )
        resp = self.client.post('/api/v1/files/list_tags/', {'prefix': 'gAg'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('gage', [tag.lower() for tag in resp.data['tags']])
        self.assertIn('gage / be01-1', [tag.lower() for tag in resp.data['tags']])
        self.assertIn('gage / be01-1', [tag.lower() for tag in resp.data['managed_tags']])
        self.assertIn('gage', resp.data['managed_tags'])
        self.assertNotIn('HiddenOnly', resp.data['tags'])
        self.assertNotIn('OtherOnly', resp.data['tags'])

    def test_batch_dirs_exposes_combination_dto_and_managed_tags(self):
        import os
        import shutil
        import tempfile
        from django.test import override_settings
        media = tempfile.mkdtemp(prefix='combo-query-media-')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with override_settings(MEDIA_ROOT=media):
            path = os.path.join(media, 'data', self.owner.username, 'batch', 'LOT', 'a.csv')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as fh:
                fh.write(b'x')
            self.a.file_path = path
            self.a.file_type = 'batch'
            self.a.batch_name = 'LOT'
            self.a.save(update_fields=['file_path', 'file_type', 'batch_name'])
            resp = self.client.get('/api/v1/batch-dirs/')
        self.assertEqual(resp.status_code, 200, resp.data)
        batch = next(item for item in resp.data if item['name'] == 'LOT')
        row = batch['files'][0]
        self.assertEqual(row['combination_id'], self.gage.id)
        self.assertEqual(row['combination_name'], 'gage')
        self.assertEqual(row['batch_no'], 'BE01-1')
        self.assertEqual(row['managed_tags'], ['gage', 'gage / BE01-1'])
        self.assertEqual(batch['files_truncated'], 0)

    def test_twenty_manual_tags_do_not_consume_managed_tag_quota(self):
        tags = [f'tag-{index}' for index in range(20)]
        self.a.tags = tags
        self.a.save(update_fields=['tags'])
        resp = self.client.get(f'/api/v1/files/{self.a.id}/')
        self.assertEqual(resp.data['tags'], tags)
        self.assertEqual(resp.data['managed_tags'], ['gage', 'gage / BE01-1'])
        saved = self.client.post(
            f'/api/v1/files/{self.a.id}/set_tags/', {'tags': tags}, format='json')
        self.assertEqual(saved.status_code, 200, saved.data)
