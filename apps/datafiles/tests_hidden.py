from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile

User = get_user_model()


def _make(owner, filename, **kwargs):
    defaults = dict(
        file_path=f'/tmp/{filename}',
        file_size=100,
        format_type='CTA8290D',
        status='ready',
    )
    defaults.update(kwargs)
    return DataFile.objects.create(owner=owner, filename=filename, **defaults)


class HiddenToggleTests(APITestCase):
    """is_hidden 字段契约：默认 False、PATCH 单字段切换、他人文件 404。"""

    def setUp(self):
        self.user = User.objects.create_user(username='hidden_owner', password='x')
        self.other = User.objects.create_user(username='hidden_other', password='x')
        self.client.force_authenticate(self.user)
        self.file = _make(self.user, 'toggle.csv')

    def test_new_file_defaults_to_visible(self):
        resp = self.client.get(f'/api/v1/files/{self.file.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['is_hidden'])

    def test_patch_toggles_hidden(self):
        resp = self.client.patch(
            f'/api/v1/files/{self.file.id}/', {'is_hidden': True}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['is_hidden'])
        self.file.refresh_from_db()
        self.assertTrue(self.file.is_hidden)

        resp = self.client.patch(
            f'/api/v1/files/{self.file.id}/', {'is_hidden': False}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.file.refresh_from_db()
        self.assertFalse(self.file.is_hidden)

    def test_patch_other_users_file_is_404(self):
        foreign = _make(self.other, 'foreign.csv')
        resp = self.client.patch(
            f'/api/v1/files/{foreign.id}/', {'is_hidden': True}, format='json')
        self.assertEqual(resp.status_code, 404)
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_hidden)


class VisibilityModeTests(APITestCase):
    """visibility_mode 纯解析：真值判定与 hidden_only 优先级。"""

    def test_modes(self):
        from apps.datafiles.visibility import visibility_mode
        self.assertEqual(visibility_mode({}), 'visible')
        self.assertEqual(visibility_mode({'include_hidden': '1'}), 'all')
        self.assertEqual(visibility_mode({'hidden_only': '1'}), 'hidden')
        self.assertEqual(
            visibility_mode({'hidden_only': '1', 'include_hidden': '1'}), 'hidden')
        self.assertEqual(visibility_mode({'include_hidden': '0'}), 'visible')


class HiddenListApiTests(APITestCase):
    """列表默认排除隐藏；include_hidden / hidden_only；分面与 options 排除。"""

    def setUp(self):
        self.user = User.objects.create_user(username='list_u', password='x')
        self.client.force_authenticate(self.user)
        self.visible = _make(
            self.user, 'visible.csv',
            product_code='PROD_A', format_type='CTA8290D', tags=['open'],
        )
        self.hidden = _make(
            self.user, 'hidden.csv',
            product_code='PROD_H', format_type='ETS88', tags=['secret'],
            is_hidden=True,
        )

    def _list_ids(self, params=None):
        resp = self.client.get('/api/v1/files/', params or {})
        self.assertEqual(resp.status_code, 200)
        return [row['id'] for row in resp.data['results']]

    def test_list_excludes_hidden_by_default(self):
        ids = self._list_ids()
        self.assertIn(self.visible.id, ids)
        self.assertNotIn(self.hidden.id, ids)

    def test_include_hidden_returns_all(self):
        ids = self._list_ids({'include_hidden': 1})
        self.assertIn(self.visible.id, ids)
        self.assertIn(self.hidden.id, ids)

    def test_hidden_only_returns_hidden(self):
        self.assertEqual(self._list_ids({'hidden_only': 1}), [self.hidden.id])

    def test_hidden_only_wins_over_include_hidden(self):
        self.assertEqual(
            self._list_ids({'hidden_only': 1, 'include_hidden': 1}),
            [self.hidden.id],
        )

    def test_list_rows_expose_is_hidden(self):
        resp = self.client.get('/api/v1/files/', {'include_hidden': 1})
        rows = {row['id']: row for row in resp.data['results']}
        self.assertFalse(rows[self.visible.id]['is_hidden'])
        self.assertTrue(rows[self.hidden.id]['is_hidden'])

    def test_search_tag_or_does_not_leak_hidden(self):
        """标签搜索用 OR 拼查询集：隐藏过滤必须在最后收口，不能被 OR 带回来。"""
        resp = self.client.get('/api/v1/files/', {'search': 'secret'})
        self.assertNotIn(self.hidden.id, [row['id'] for row in resp.data['results']])

    def test_options_excludes_hidden(self):
        self.hidden.status = 'error'
        self.hidden.save(update_fields=['status', 'updated_at'])
        err_visible = _make(self.user, 'err_ok.csv', status='error')
        for params in ({}, {'include_error': 1}):
            resp = self.client.get('/api/v1/files/options/', params)
            ids = [row['id'] for row in resp.data['results']]
            self.assertNotIn(self.hidden.id, ids, params)
            if params:
                self.assertIn(err_visible.id, ids)
            else:
                self.assertNotIn(err_visible.id, ids)

    def test_facets_exclude_hidden_only_values(self):
        codes = self.client.get('/api/v1/files/product_codes/').data['product_codes']
        self.assertIn('PROD_A', codes)
        self.assertNotIn('PROD_H', codes)
        formats = self.client.get('/api/v1/files/format_types/').data['format_types']
        self.assertIn('CTA8290D', formats)
        self.assertNotIn('ETS88', formats)
        tags = self.client.post('/api/v1/files/list_tags/', {}, format='json').data['tags']
        self.assertIn('open', tags)
        self.assertNotIn('secret', tags)

    def test_detail_update_delete_of_hidden_are_allowed(self):
        """软隐藏边界：详情/改/删不因隐藏而受限。"""
        self.assertEqual(
            self.client.get(f'/api/v1/files/{self.hidden.id}/').status_code, 200)
        self.assertEqual(
            self.client.patch(f'/api/v1/files/{self.hidden.id}/',
                              {'is_hidden': False}, format='json').status_code, 200)
        self.hidden.refresh_from_db()
        self.assertFalse(self.hidden.is_hidden)
        self.hidden.is_hidden = True
        self.hidden.save(update_fields=['is_hidden', 'updated_at'])
        self.assertEqual(
            self.client.delete(f'/api/v1/files/{self.hidden.id}/').status_code, 204)

    def test_lookup_returns_hidden_file(self):
        """按 id 批量取数（analysis/导出共用口径）不拦隐藏。"""
        from apps.datafiles.lookup import owned_files_by_pk
        found = owned_files_by_pk(self.user, [self.hidden.id])
        self.assertIn(self.hidden.id, found)


class DashboardHiddenFallbackTests(APITestCase):
    """未传 file_id 的默认取文件要跳过隐藏行。"""

    def setUp(self):
        self.user = User.objects.create_user(username='hidden_dash', password='x')
        self.client.force_authenticate(self.user)

    def test_only_hidden_ready_file_yields_no_data(self):
        _make(self.user, 'only_hidden.csv', is_hidden=True)
        resp = self.client.get('/api/v1/summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['code'], 'no_data')

    def test_visible_file_is_picked_even_if_older(self):
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        try:
            _make(self.user, 'older_visible.csv', file_path=path)
            _make(self.user, 'newer_hidden.csv', is_hidden=True)
            resp = self.client.get('/api/v1/summary/')
            self.assertEqual(resp.status_code, 200)
            # 选中可见行（空文件解析失败 ⇒ parse_failed），不是 hidden 行（路径不存在 ⇒ file_not_found）
            self.assertEqual(resp.data['code'], 'parse_failed')
        finally:
            os.unlink(path)
