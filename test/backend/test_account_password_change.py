"""自助改密与「改密 / 管理员重置后旧 token 失效」的契约。

覆盖：
  * POST /api/v1/auth/change-password/ 的成功、旧密码错误、两次不一致、弱口令；
  * CHECK_REVOKE_TOKEN：改密后旧 access 立即 401，旧 refresh 已被黑名单；
  * 管理员重置密码会清锁定、吊销目标账号 refresh token，且不影响他人会话；
  * 创建用户 / 管理员重置同样走 AUTH_PASSWORD_VALIDATORS。
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User

CHANGE_URL = reverse('change-password')
LOGIN_URL = reverse('login')
LOGOUT_URL = '/api/v1/auth/logout/'
PROFILE_URL = '/api/v1/auth/profile/'
REFRESH_URL = '/api/v1/auth/refresh/'
USERS_URL = '/api/v1/auth/users/'

OLD_PASSWORD = 'OldPass-12345'
NEW_PASSWORD = 'NewPass-67890'


def _tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token), str(refresh)


def _auth_header(token):
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


class ChangePasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', password=OLD_PASSWORD,
        )
        self.client = APIClient()

    def test_change_password_success_revokes_old_tokens(self):
        access, refresh = _tokens_for(self.user)
        self.client.credentials(**_auth_header(access))

        resp = self.client.post(CHANGE_URL, {
            'old_password': OLD_PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

        # 旧 access 立即失效（CHECK_REVOKE_TOKEN 比较 password hash 指纹）。
        resp = self.client.get(PROFILE_URL)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

        # 旧 refresh 已被黑名单，不能继续换 access。
        self.client.credentials()
        resp = self.client.post(REFRESH_URL, {'refresh': refresh}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

        # 新密码可正常登录。
        resp = self.client.post(LOGIN_URL, {
            'username': 'alice', 'password': NEW_PASSWORD,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_wrong_old_password_is_rejected(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(CHANGE_URL, {
            'old_password': 'not-my-password',
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('当前密码不正确', resp.data['message'])

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_confirm_mismatch_is_rejected(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(CHANGE_URL, {
            'old_password': OLD_PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD + 'x',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('两次输入的新密码不一致', resp.data['message'])

    def test_weak_new_password_is_rejected(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(CHANGE_URL, {
            'old_password': OLD_PASSWORD,
            'new_password': '12345678',
            'confirm_password': '12345678',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('密码不符合要求', resp.data['message'])

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_requires_authentication(self):
        resp = self.client.post(CHANGE_URL, {
            'old_password': OLD_PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_other_users_tokens_survive(self):
        other = User.objects.create_user(
            username='bob', password='BobPass-12345',
        )
        other_access, _ = _tokens_for(other)
        access, _ = _tokens_for(self.user)
        self.client.credentials(**_auth_header(access))

        resp = self.client.post(CHANGE_URL, {
            'old_password': OLD_PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.client.credentials(**_auth_header(other_access))
        resp = self.client.get(PROFILE_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class LogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='logout-user', password=OLD_PASSWORD,
        )
        self.access, self.refresh = _tokens_for(self.user)
        self.client = APIClient()

    def test_logout_blacklists_refresh_token(self):
        self.client.credentials(**_auth_header(self.access))
        resp = self.client.post(
            LOGOUT_URL, {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.client.credentials()
        resp = self.client.post(
            REFRESH_URL, {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_works_without_access_token(self):
        """access 已过期/缺失时，登出仍应吊销 body 里的 refresh。"""
        resp = self.client.post(
            LOGOUT_URL, {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp = self.client.post(
            REFRESH_URL, {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class AdminResetPasswordTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='AdminPass-12345',
            role='administrator',
        )
        self.target = User.objects.create_user(
            username='victim', password=OLD_PASSWORD,
            login_attempts=5,
            lockout_until=timezone.now() + timedelta(minutes=15),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.url = f'{USERS_URL}{self.target.pk}/reset_password/'

    def test_reset_clears_lockout_and_revokes_target_tokens(self):
        target_access, target_refresh = _tokens_for(self.target)

        resp = self.client.post(self.url, {
            'new_password': NEW_PASSWORD,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password(NEW_PASSWORD))
        self.assertEqual(self.target.login_attempts, 0)
        self.assertIsNone(self.target.lockout_until)

        self.client.force_authenticate(user=None)
        self.client.credentials(**_auth_header(target_access))
        resp = self.client.get(PROFILE_URL)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.credentials()
        resp = self.client.post(
            REFRESH_URL, {'refresh': target_refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

        resp = self.client.post(LOGIN_URL, {
            'username': 'victim', 'password': NEW_PASSWORD,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reset_rejects_weak_password_without_clearing_lockout(self):
        resp = self.client.post(self.url, {
            'new_password': '12345678',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('密码不符合要求', resp.data['message'])

        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password(OLD_PASSWORD))
        self.assertEqual(self.target.login_attempts, 5)
        self.assertIsNotNone(self.target.lockout_until)


class UserCreatePasswordPolicyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='AdminPass-12345',
            role='administrator',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_weak_password_is_rejected(self):
        resp = self.client.post(USERS_URL, {
            'username': 'weak-user',
            'password': '12345678',
            'role': 'user',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('密码不符合要求', resp.data['message'])
        self.assertFalse(User.objects.filter(username='weak-user').exists())

    def test_strong_password_still_creates_user(self):
        resp = self.client.post(USERS_URL, {
            'username': 'strong-user',
            'password': 'StrongPass-98765',
            'role': 'user',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='strong-user')
        self.assertTrue(user.check_password('StrongPass-98765'))
