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
