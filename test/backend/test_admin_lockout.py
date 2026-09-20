"""Regression guard: user management must not lock the admin out.

停用 ``is_active`` 会同时掐断两条恢复路径 —— 登录端点在 ``authenticate()``
之前就拦截 ``not user.is_active``（403 ``account_disabled``），SimpleJWT 也会
立刻吊销该 token；而 Django admin 登录同样要求 ``is_active``、``seed_users``
也从不碰这个字段。所以「管理员把自己停用」是一次**没有自助出口**的锁定，
必须由 ``UserManagementViewSet._guard_lockout`` 在写库前拦下。

后两个用例是防过度修复：存在第二个管理员时，自我降级以及停用/删除另一个
管理员都必须照常放行（``test_profile_privilege.py`` 里还有一对同类钉子）。
"""
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User


class AdminLockoutGuardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='strong-pass-123', role='administrator',
        )
        self.target = User.objects.create_user(
            username='victim', password='strong-pass-123', role='user',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _self_url(self):
        return f'/api/v1/auth/users/{self.admin.id}/'

    def test_admin_cannot_disable_self(self):
        resp = self.client.put(self._self_url(), {'is_active': False}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['code'], 'validation_error')
        self.assertIn('自己', resp.data['message'])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_cannot_delete_self(self):
        resp = self.client.delete(self._self_url())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('自己', resp.data['message'])
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_sole_admin_cannot_demote_self(self):
        """把自己降级出管理员同样会永久失去管理入口（UI 未开放，API 可达）。"""
        resp = self.client.put(self._self_url(), {'role': 'user'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('管理员', resp.data['message'])
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, 'administrator')

    def test_admin_can_demote_self_when_another_admin_exists(self):
        User.objects.create_user(
            username='admin2', password='strong-pass-123', role='administrator',
        )
        resp = self.client.put(self._self_url(), {'role': 'user'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, 'user')

    def test_admin_can_still_disable_another_admin(self):
        """目标是别人时请求者本人就是「另一个启用的管理员」，不该被判成锁定。"""
        other = User.objects.create_user(
            username='admin2', password='strong-pass-123', role='administrator',
        )
        resp = self.client.put(
            f'/api/v1/auth/users/{other.id}/', {'is_active': False}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        other.refresh_from_db()
        self.assertFalse(other.is_active)

    def test_admin_can_still_delete_another_user(self):
        resp = self.client.delete(f'/api/v1/auth/users/{self.target.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())
