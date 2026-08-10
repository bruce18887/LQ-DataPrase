"""Tests for the JWT auth flow: login and refresh-token rotation.

Covers the behaviour the front-end axios interceptor relies on:
  * login response includes both ``token`` (access) and ``refresh``
  * ``POST /api/v1/auth/refresh/`` mints a new access token
  * with ``ROTATE_REFRESH_TOKENS=True`` the old refresh token becomes invalid
    after one rotation (blacklisted, ``BLACKLIST_AFTER_ROTATION=True``)
  * an invalid / blacklisted refresh token returns 401, not 500
  * missing ``refresh`` body returns 400 (not 500)
  * login surfaces distinct error codes so the front-end can render
    useful messages (timeout/network/disabled/locked/wrong-password)
"""
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.accounts.models import User


class JwtLoginTests(TestCase):
    """LoginView must hand out both access and refresh tokens, and
    return structured error codes for each failure mode."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', password='strong-pass-123'
        )
        self.url = reverse('login')

    # --- happy path ---
    def test_login_returns_access_and_refresh(self):
        resp = self.client.post(self.url, {
            'username': 'alice', 'password': 'strong-pass-123'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('token', resp.data)
        self.assertIn('refresh', resp.data)
        self.assertTrue(resp.data['token'])
        self.assertTrue(resp.data['refresh'])

    # --- 400 missing_credentials ---
    def test_login_missing_username_returns_400(self):
        resp = self.client.post(self.url, {'password': 'x'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['code'], 'missing_credentials')
        self.assertIn('username', resp.data['missing_fields'])

    def test_login_missing_password_returns_400(self):
        resp = self.client.post(self.url, {'username': 'alice'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['code'], 'missing_credentials')
        self.assertIn('password', resp.data['missing_fields'])

    def test_login_empty_body_returns_400(self):
        resp = self.client.post(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['code'], 'missing_credentials')
        self.assertEqual(
            set(resp.data['missing_fields']), {'username', 'password'}
        )

    # --- 401 user_not_found ---
    def test_login_unknown_username_returns_401_with_code(self):
        resp = self.client.post(self.url, {
            'username': 'ghost', 'password': 'whatever'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data['code'], 'user_not_found')
        self.assertIn('ghost', resp.data['detail'])

    # --- 401 invalid_credentials ---
    def test_login_wrong_password_returns_401_with_remaining(self):
        resp = self.client.post(self.url, {
            'username': 'alice', 'password': 'wrong'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data['code'], 'invalid_credentials')
        # 4 attempts left after this first failure.
        self.assertEqual(resp.data['remaining_attempts'], 4)

    def test_login_remaining_attempts_decrements(self):
        for expected_remaining in (4, 3, 2, 1):
            resp = self.client.post(self.url, {
                'username': 'alice', 'password': 'wrong'
            }, format='json')
            self.assertEqual(resp.data['remaining_attempts'], expected_remaining)
            self.assertEqual(resp.data['code'], 'invalid_credentials')

    # --- 403 account_disabled ---
    def test_login_disabled_account_returns_403(self):
        self.user.is_active = False
        self.user.save()
        resp = self.client.post(self.url, {
            'username': 'alice', 'password': 'strong-pass-123'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data['code'], 'account_disabled')

    def test_login_disabled_overrides_lockout(self):
        """A disabled account must not be 'fixed' by the lockout
        message; we want the user to know it's a permission problem."""
        from django.utils import timezone
        from datetime import timedelta
        self.user.is_active = False
        self.user.lockout_until = timezone.now() + timedelta(minutes=10)
        self.user.save()
        resp = self.client.post(self.url, {
            'username': 'alice', 'password': 'strong-pass-123'
        }, format='json')
        self.assertEqual(resp.data['code'], 'account_disabled')

    # --- 423 account_locked ---
    def test_login_locked_account_returns_423_with_retry_after(self):
        from django.utils import timezone
        from datetime import timedelta
        self.user.lockout_until = timezone.now() + timedelta(minutes=8)
        self.user.save()
        resp = self.client.post(self.url, {
            'username': 'alice', 'password': 'strong-pass-123'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_423_LOCKED)
        self.assertEqual(resp.data['code'], 'account_locked')
        self.assertIn('retry_after_minutes', resp.data)
        self.assertIn('locked_until', resp.data)

    def test_login_5_wrong_attempts_locks_account(self):
        for _ in range(5):
            self.client.post(self.url, {
                'username': 'alice', 'password': 'wrong'
            }, format='json')
        # The 5th wrong attempt triggers the lock; the *next* attempt
        # — even with the right password — should still be locked.
        resp = self.client.post(self.url, {
            'username': 'alice', 'password': 'strong-pass-123'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_423_LOCKED)
        self.assertEqual(resp.data['code'], 'account_locked')
        self.assertEqual(resp.data['retry_after_minutes'], 15)


class TokenRefreshTests(TestCase):
    """``/auth/refresh/`` is what the front-end interceptor calls on 401."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='bob', password='strong-pass-123'
        )
        self.refresh = str(RefreshToken.for_user(self.user))
        self.url = reverse('token-refresh')

    def test_refresh_returns_new_access(self):
        resp = self.client.post(
            self.url, {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertTrue(resp.data['access'])

    def test_refresh_rotates_refresh_token(self):
        """With ROTATE_REFRESH_TOKENS=True the response also includes a
        brand-new refresh token, and the old one ends up blacklisted."""
        # Capture the jti *before* we blacklist the token, because
        # instantiating a RefreshToken from a blacklisted value raises.
        old_jti = RefreshToken(self.refresh)['jti']

        resp = self.client.post(
            self.url, {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('refresh', resp.data)
        new_refresh = resp.data['refresh']
        self.assertNotEqual(new_refresh, self.refresh)

        # Second rotation must use the *new* refresh token; the old one
        # was blacklisted on first use, so reusing it must fail with 401.
        resp2 = self.client.post(
            self.url, {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp2.status_code, status.HTTP_401_UNAUTHORIZED)

        # Sanity: blacklisted token record was actually written.
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=old_jti).exists()
        )

    def test_refresh_with_garbage_token_returns_401(self):
        resp = self.client.post(
            self.url, {'refresh': 'not-a-real-token'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_without_body_returns_400(self):
        resp = self.client.post(self.url, {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refresh_does_not_require_authentication(self):
        """The refresh endpoint is hit by the *response* interceptor
        *after* the access token has already been rejected, so it must
        not sit behind IsAuthenticated."""
        anon = APIClient()
        resp = anon.post(
            self.url, {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class UserManagementViewSetTests(TestCase):
    """``UserManagementViewSet`` is the admin-facing CRUD for users.

    The user-management page (``UserManagement.vue``) sends
    ``PUT /auth/users/<id>/ {is_active: false}`` to disable a user —
    a *partial* update. DRF's default ModelViewSet.update() requires
    every field for PUT, so without ``partial=True`` on the serializer
    every toggle 400s. The fix lives in ``UserManagementViewSet.
    get_serializer()``; this class is the regression guard.
    """

    def setUp(self):
        # The 'user_management' feature is the gate for this ViewSet.
        # In the development profile it is granted to administrators.
        self.admin = User.objects.create_user(
            username='admin', password='strong-pass-123', role='administrator',
        )
        self.target = User.objects.create_user(
            username='victim', password='strong-pass-123', role='user',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_put_only_is_active_disables_user(self):
        """The exact scenario from the bug report: PUT just one field."""
        resp = self.client.put(
            f'/api/v1/auth/users/{self.target.id}/',
            {'is_active': False}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        # Other fields are untouched.
        self.assertEqual(self.target.username, 'victim')
        self.assertEqual(self.target.role, 'user')

    def test_patch_only_is_active_disables_user(self):
        resp = self.client.patch(
            f'/api/v1/auth/users/{self.target.id}/',
            {'is_active': False}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_put_with_full_body_still_works(self):
        """Make the fix doesn't accidentally make PUT-with-all-fields break."""
        resp = self.client.put(
            f'/api/v1/auth/users/{self.target.id}/',
            {
                'username': 'victim',
                'email': 'victim@example.com',
                'display_name': 'Victim User',
                'role': 'viewer',
                'is_active': True,
            }, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.target.refresh_from_db()
        self.assertEqual(self.target.email, 'victim@example.com')
        self.assertEqual(self.target.role, 'viewer')

    def test_put_to_nonexistent_user_returns_404(self):
        resp = self.client.put(
            '/api/v1/auth/users/99999/',
            {'is_active': False}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_put_username_must_remain_unique(self):
        """Partial update must still validate the unique constraint
        — partial=True does not mean 'skip validators'."""
        other = User.objects.create_user(
            username='other-user', password='strong-pass-123',
        )
        resp = self.client.patch(
            f'/api/v1/auth/users/{self.target.id}/',
            {'username': 'other-user'}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        # 统一异常格式后字段错误嵌套在 detail 下（code/message 供前端 toast）。
        self.assertEqual(resp.data['code'], 'validation_error')
        self.assertIn('username', resp.data['detail'])

    def test_unauthenticated_cannot_toggle(self):
        anon = APIClient()
        resp = anon.put(
            f'/api/v1/auth/users/{self.target.id}/',
            {'is_active': False}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_cannot_toggle(self):
        """``FeaturePermission('user_management')`` is granted to
        administrators only — a plain user gets 403."""
        plain = User.objects.create_user(
            username='plain-joe', password='strong-pass-123', role='user',
        )
        self.client.force_authenticate(user=plain)
        resp = self.client.put(
            f'/api/v1/auth/users/{self.target.id}/',
            {'is_active': False}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class UserSettingsApiTests(APITestCase):
    """GET/PUT /api/v1/auth/settings/ with export_filename_templates."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', password='strong-pass-123',
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse('settings')

    def test_get_settings_returns_all_template_keys(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        templates = resp.data['export_filename_templates']
        self.assertEqual(
            set(templates.keys()),
            {'to_excel', 'to_csv', 'sigma_limit', 'html_report',
             'batch_charts', 'batch_report', 'buyoff', 'gage'},
        )
        # Defaults match the built-in templates
        self.assertEqual(templates['to_excel'], '{filename}_analysis')

    def test_put_updates_template_and_round_trips(self):
        resp = self.client.put(
            self.url,
            {'export_filename_templates': {'to_excel': '{filename}_{datetime}'}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        resp = self.client.get(self.url)
        self.assertEqual(resp.data['export_filename_templates']['to_excel'],
                         '{filename}_{datetime}')

    def test_put_unknown_key_returns_400(self):
        resp = self.client.put(
            self.url,
            {'export_filename_templates': {'not_a_type': 'x'}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_non_string_template_returns_400(self):
        resp = self.client.put(
            self.url,
            {'export_filename_templates': {'to_excel': 123}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_oversized_template_returns_400(self):
        resp = self.client.put(
            self.url,
            {'export_filename_templates': {'to_excel': 'x' * 201}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_non_dict_returns_400(self):
        resp = self.client.put(
            self.url,
            {'export_filename_templates': ['to_excel']},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_settings_returns_default_export_timeout(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['export_timeout'], 600)

    def test_put_updates_export_timeout_and_round_trips(self):
        resp = self.client.put(self.url, {'export_timeout': 900}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        resp = self.client.get(self.url)
        self.assertEqual(resp.data['export_timeout'], 900)

    def test_put_export_timeout_below_min_returns_400(self):
        resp = self.client.put(self.url, {'export_timeout': 29}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_export_timeout_above_max_returns_400(self):
        resp = self.client.put(self.url, {'export_timeout': 3601}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_export_timeout_non_integer_returns_400(self):
        resp = self.client.put(self.url, {'export_timeout': 'abc'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_settings_returns_default_chart_renderer(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['chart_renderer'], 'svg')

    def test_put_updates_chart_renderer_and_round_trips(self):
        resp = self.client.put(
            self.url, {'chart_renderer': 'canvas'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        resp = self.client.get(self.url)
        self.assertEqual(resp.data['chart_renderer'], 'canvas')
        # 恢复默认，避免污染其它测试
        self.client.put(self.url, {'chart_renderer': 'svg'}, format='json')

    def test_put_invalid_chart_renderer_returns_400(self):
        resp = self.client.put(
            self.url, {'chart_renderer': 'webgl'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
