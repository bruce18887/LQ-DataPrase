"""Regression guard: self-service profile writes must not grant privileges.

``PUT /api/v1/auth/profile/`` only requires ``IsAuthenticated``, while
``FeaturePermission`` re-reads ``user.role`` from the DB on *every* request.
When the endpoint shared the admin-facing ``UserSerializer`` (whose ``role`` /
``is_active`` / ``username`` are writable), any regular user could promote itself
with a single request body and immediately reach user management, data delete
and system config. ``UserProfileSerializer`` now makes those read-only.

DRF silently ignores read-only fields in the payload, so the assertions are
"200 + DB unchanged" rather than "400".

The last test is the over-fix guard: administrators must still be able to
change roles through ``UserManagementViewSet``.
"""
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User

PROFILE_URL = '/api/v1/auth/profile/'


class ProfilePrivilegeEscalationTests(TestCase):
    def setUp(self):
        self.plain = User.objects.create_user(
            username='plain-joe', password='strong-pass-123', role='user',
            email='joe@example.com', display_name='Joe',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.plain)

    def test_put_cannot_promote_own_role(self):
        """The exact escalation payload must leave the DB role untouched."""
        resp = self.client.put(
            PROFILE_URL, {'role': 'administrator'}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.role, 'user')
        self.assertFalse(self.plain.is_superuser)

    def test_patch_is_not_a_supported_write_path(self):
        """``UserProfileView`` only implements GET/PUT; PATCH stays 405."""
        resp = self.client.patch(
            PROFILE_URL, {'role': 'administrator'}, format='json',
        )
        self.assertEqual(
            resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.role, 'user')

    def test_put_cannot_deactivate_or_reactivate_self(self):
        """A writable ``is_active`` allowed self-unlock after a lockout."""
        resp = self.client.put(PROFILE_URL, {'is_active': False}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.plain.refresh_from_db()
        self.assertTrue(self.plain.is_active)

    def test_put_cannot_rename_own_username(self):
        """Renaming the login identity is an admin action, not self-service."""
        resp = self.client.put(
            PROFILE_URL, {'username': 'someone-else'}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.username, 'plain-joe')

    def test_put_still_updates_own_display_fields(self):
        """The legitimate self-service surface must keep working."""
        resp = self.client.put(
            PROFILE_URL,
            {'display_name': 'Joseph', 'email': 'joseph@example.com'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.display_name, 'Joseph')
        self.assertEqual(self.plain.email, 'joseph@example.com')

    def test_get_still_returns_role_for_frontend_menus(self):
        """Response contract unchanged: the SPA re-fetches profile on refresh
        to rebuild role-dependent admin menus (``router/index.ts``)."""
        resp = self.client.get(PROFILE_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['role'], 'user')
        for field in ('id', 'username', 'email', 'display_name', 'role',
                      'is_active', 'date_joined', 'last_login'):
            self.assertIn(field, resp.data)


class AdminRoleManagementStillWorksTests(TestCase):
    """Over-fix guard: locking down the profile endpoint must not lock out
    the admin-facing user management CRUD, which shares ``UserSerializer``."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='strong-pass-123', role='administrator',
        )
        self.target = User.objects.create_user(
            username='victim', password='strong-pass-123', role='administrator',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_admin_can_still_change_another_users_role(self):
        resp = self.client.put(
            f'/api/v1/auth/users/{self.target.id}/',
            {'role': 'user'}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, 'user')

    def test_admin_can_still_toggle_is_active(self):
        resp = self.client.put(
            f'/api/v1/auth/users/{self.target.id}/',
            {'is_active': False}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
