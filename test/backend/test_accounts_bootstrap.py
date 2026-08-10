"""Tests for the superuser → administrator role bootstrap.

The app's permission system (FeaturePermission, the JWT ``role`` claim,
frontend admin checks) reads the custom ``role`` field exclusively —
never ``is_superuser``. Django's stock ``create_superuser`` doesn't set
that field, so a packaged-app first run used to create an admin account
with role='user' that silently logged in as a regular user. These tests
pin the three fixes:

  * ``UserManager.create_superuser`` forces role='administrator';
  * ``standalone._promote_superusers`` upgrades legacy superusers (self-heal);
  * ``seed_users`` repairs mismatched role/flags on existing users and
    never resets their passwords.

Run directly:  python test/backend/test_accounts_bootstrap.py
(Runs against an isolated test DB via DiscoverRunner — dev db.sqlite3 is
never touched.)
"""
import os
import sys

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from django.test import TestCase  # noqa: E402

from apps.accounts.models import User, UserSetting  # noqa: E402
from standalone import _promote_superusers  # noqa: E402

PASSWORD = 'x-pass-12345678'


class UserManagerRoleTests(TestCase):
    def test_create_superuser_forces_administrator_role(self):
        user = User.objects.create_superuser('boss', 'boss@localhost', PASSWORD)
        self.assertEqual(user.role, 'administrator')
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

    def test_create_superuser_ignores_callersupplied_role(self):
        # Even an explicit non-admin role must not produce a superuser that
        # the role-based checks treat as a regular user.
        user = User.objects.create_superuser(
            'boss2', 'boss2@localhost', PASSWORD, role='viewer'
        )
        self.assertEqual(user.role, 'administrator')

    def test_create_user_keeps_default_role(self):
        user = User.objects.create_user('worker', 'worker@localhost', PASSWORD)
        self.assertEqual(user.role, 'user')
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)


class PromoteSuperusersTests(TestCase):
    def _legacy_superuser(self, username):
        """Simulate an install bootstrapped before the manager fix: stock
        create_superuser never set ``role``, so it fell back to 'user'."""
        user = User.objects.create_superuser(username, f'{username}@localhost', PASSWORD)
        user.role = 'user'
        user.is_staff = False
        user.save(update_fields=['role', 'is_staff'])
        return user

    def test_legacy_superuser_is_promoted(self):
        legacy = self._legacy_superuser('legacy_admin')

        promoted = _promote_superusers()

        self.assertEqual(promoted, ['legacy_admin'])
        legacy.refresh_from_db()
        self.assertEqual(legacy.role, 'administrator')
        self.assertTrue(legacy.is_staff)

    def test_healthy_users_untouched(self):
        ok = User.objects.create_superuser('ok_admin', 'ok@localhost', PASSWORD)
        normal = User.objects.create_user('normal_user', 'n@localhost', PASSWORD)

        self.assertEqual(_promote_superusers(), [])

        ok.refresh_from_db()
        normal.refresh_from_db()
        self.assertEqual(ok.role, 'administrator')
        self.assertEqual(normal.role, 'user')


class SeedUsersRepairTests(TestCase):
    def test_repairs_existing_user_role_without_resetting_password(self):
        legacy = User.objects.create_superuser('admin', 'admin@localhost', 'original-pass-9999')
        legacy.role = 'user'
        legacy.display_name = 'old'
        legacy.is_staff = False
        legacy.save(update_fields=['role', 'display_name', 'is_staff'])

        call_command('seed_users')

        legacy.refresh_from_db()
        self.assertEqual(legacy.role, 'administrator')
        self.assertEqual(legacy.display_name, '管理员')
        self.assertTrue(legacy.is_staff)
        self.assertTrue(legacy.is_superuser)
        # Password of an existing user must never be reset.
        self.assertTrue(legacy.check_password('original-pass-9999'))
        # Settings row is created for repaired users too (legacy bootstraps
        # never made one).
        self.assertTrue(UserSetting.objects.filter(user=legacy).exists())

    def test_creates_all_default_users(self):
        call_command('seed_users')

        passwords = {
            'admin': 'admin123', 'user': 'user123', 'viewer': 'viewer123',
        }
        for username, role in (('admin', 'administrator'), ('user', 'user'), ('viewer', 'viewer')):
            user = User.objects.get(username=username)
            self.assertEqual(user.role, role)
            self.assertEqual(user.is_superuser, role == 'administrator')
            self.assertEqual(user.is_staff, role == 'administrator')
            self.assertTrue(user.check_password(passwords[username]))
            self.assertTrue(UserSetting.objects.filter(user=user).exists())


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_accounts_bootstrap'])
    sys.exit(1 if failures else 0)
