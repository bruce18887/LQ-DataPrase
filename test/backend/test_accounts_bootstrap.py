"""Tests for the superuser → administrator role bootstrap.

The app's permission system (FeaturePermission, the JWT ``role`` claim,
frontend admin checks) reads the custom ``role`` field exclusively —
never ``is_superuser``. Django's stock ``create_superuser`` doesn't set
that field, so a packaged-app first run used to create an admin account
with role='user' that silently logged in as a regular user. These tests
pin the three fixes:

  * ``UserManager.create_superuser`` forces role='administrator';
  * ``standalone._promote_superusers`` upgrades legacy superusers (self-heal);
  * ``seed_users`` repairs mismatched role/flags/activation on existing users
    and never resets their passwords.

Run directly:  python test/backend/test_accounts_bootstrap.py
(Runs against an isolated test DB via DiscoverRunner — dev db.sqlite3 is
never touched.)
"""
import io
import os
import re
import sys
from unittest import mock

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

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
        # An explicitly supplied role must not produce a superuser that the
        # role-based checks treat as a regular user. The literal is deliberately
        # not a valid choice: 'user' is also the field default, so only an
        # invalid value proves the manager overrode the caller instead of the
        # value simply being ignored/validated away.
        user = User.objects.create_superuser(
            'boss2', 'boss2@localhost', PASSWORD, role='not_a_role'
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
    """seed_users 的「修复既有账号」语义：补 role/flags，但绝不重置口令。

    显式放行弱口令闸门：``seed_users`` 在非开发档会拒执（``seed_users.py`` 的
    ``_refuse_weak_seed_outside_dev``），而 **Django 测试运行器强制 DEBUG=False**
    （``django.test.utils.setup_test_environment``），所以本类若不放行就会全红。
    闸门自身的行为由 ``test.backend.test_seed_users_guard`` 负责，这里不是被测对象。
    """

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {'LQDP_ALLOW_WEAK_SEED': '1'})
        patcher.start()
        self.addCleanup(patcher.stop)
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
            'admin': 'admin123', 'user': 'user123',
        }
        for username, role in (('admin', 'administrator'), ('user', 'user')):
            user = User.objects.get(username=username)
            self.assertEqual(user.role, role)
            self.assertEqual(user.is_superuser, role == 'administrator')
            self.assertEqual(user.is_staff, role == 'administrator')
            self.assertTrue(user.check_password(passwords[username]))
            self.assertTrue(UserSetting.objects.filter(user=user).exists())

    def test_reactivates_disabled_seed_accounts_without_resetting_password(self):
        """``seed_users`` 必须把两个种子账号钉回可用态，含 ``is_active``。

        它们是 dev/e2e 的夹具账号（``frontend/e2e/fixtures/auth.setup.ts`` 实时以
        ``user``/``user123`` 登录取 storageState），一旦被停用，setup 前置红 → 依赖它的
        用例全部报错；而修复集原先只有 role/display_name/is_staff/is_superuser，重跑
        seed 只打印「User already exists」，停用状态永久留下（2026-11-09 实测）。
        """
        call_command('seed_users')
        User.objects.filter(username__in=('admin', 'user')).update(is_active=False)

        call_command('seed_users')

        for username, password in (('admin', 'admin123'), ('user', 'user123')):
            user = User.objects.get(username=username)
            self.assertTrue(user.is_active, f'{username} 应被重新启用')
            self.assertTrue(
                user.check_password(password),
                '恢复启用不得顺带重置口令（否则等于给停用账号开后门）',
            )

    def test_does_not_reactivate_non_seed_users(self):
        """只管两个夹具账号：管理员主动停用的真实账号不能被 seed 悄悄放回来。"""
        call_command('seed_users')
        real = User.objects.create_user('ops_zhang', 'z@localhost', PASSWORD, role='user')
        real.is_active = False
        real.save(update_fields=['is_active'])

        call_command('seed_users')

        real.refresh_from_db()
        self.assertFalse(real.is_active)

    def test_seed_users_falls_back_to_role_normalization(self):
        """seed_users 必须接上归并兜底（spec §4「幂等兜底」），且三类计数都出声。

        夹具造两条 API 走不到的历史行，各钉一支计数器：
        * `role='viewer'` 的普通行 —— ORM 直写不经 choices 校验，正是 choices 收敛
          前库里会残留的形状（`create_user` 也不校验，所以不必绕过什么）；
        * `is_superuser=True` 而 `role='user'` 的行 —— `create_superuser` 会强制
          `role='administrator'`（见本文件 `UserManagerRoleTests`），所以只能像
          `test_role_normalization._mk` 那样用 `queryset.update()` 绕开它。
        第二条只有 `superuser_promoted` 这一支能修。承重实测：把
        `normalize_roles(User)` 换成不再触碰内核的等价空计数，本用例红在第一条
        断言（viewer 行原样留在库里）；整行删掉则连累所有跑 seed 的用例一起报错
        （`merged` 未定义），红得更响却不指向这条兜底。
        """
        stale = User.objects.create_user('legacy_v', 'lv@localhost', PASSWORD, role='viewer')
        promoted = User.objects.create_superuser('legacy_su', 'ls@localhost', PASSWORD)
        User.objects.filter(pk=promoted.pk).update(role='user', is_staff=False)

        printed = io.StringIO()
        call_command('seed_users', stdout=printed)

        stale.refresh_from_db()
        promoted.refresh_from_db()
        self.assertEqual(stale.role, 'user', 'viewer 行未被归并 —— seed 没接上兜底')
        self.assertEqual((promoted.role, promoted.is_staff), ('administrator', True))
        text = printed.getvalue()
        # 逐支钉「数值」而不只是名字：只查名字的话，把出声的字典换成
        # `dict.fromkeys(merged, 0)`（全 0 的谎报）本用例照样绿。
        self._assert_counter(text, 'viewer_to_user', 1)
        self._assert_counter(text, 'superuser_promoted', 1)
        self._assert_counter(text, 'viewer_to_administrator', 0)

        # 幂等：第二次跑三项全 0 ⇒ 不该再出声。内核那句「e2e 预跑不会重复出声」原本
        # 没有哨兵（把出声条件写成 `if True:` 全绿），这一条就是它的判据。先确认
        # SUCCESS 行在，才让「没有计数」这句断言不是空话。
        again = io.StringIO()
        call_command('seed_users', stdout=again)
        again_text = again.getvalue()
        self.assertIn('Seed users completed.', again_text)
        self.assertNotIn('viewer_to_user', again_text, f'第二次仍在出声：{again_text!r}')

    def _assert_counter(self, text, name, value):
        """钉计数的「值」，打印形态允许 dict repr 或 JSON（键两侧引号不挑）。

        值右侧要收尾（`(?![0-9])`）：不写的话 `12` / `100` 都满足「等于 1」，
        那条「谎报全 0」的坏法之外还会放过把计数写成别的数字。
        """
        pattern = r"['\"]%s['\"]\s*:\s*%d(?![0-9])" % (name, value)
        if not re.search(pattern, text):
            self.fail(f'期望 stdout 里 {name}={value}，实得：{text!r}')

    def test_seed_users_writes_clean_under_non_cjk_codepage(self):
        """整条命令的每一行 stdout 都必须能在 cp1252 下写通 —— 判机制，不判某行文案。

        上一版判据只 `lines[0].encode('ascii')`，是双向放行的替代理：实测把与归并
        无关的 SUCCESS 行换成中文，全绿，而同一命令在 cp1252 stdout 下真的抛
        `UnicodeEncodeError`（位置在数据已改、种子已建之后 —— 手动跑的
        `manage.py seed_users` 因此退 1）。这里拿 cp1252 的流连跑三条分支：建号支
        （`Created user:`）、修复支（`Updated user:`）、幂等支（`User already exists:`），
        外加归并出声与 SUCCESS。末尾逐条要求这五种哨兵都真的出现过 —— 少一种就说明
        那一支的中文行没人判，「任何一行」那句话就又是空话。改文案措辞不误报。
        """
        stale = User.objects.create_user('cp1252_v', 'cv@localhost', PASSWORD, role='viewer')

        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='cp1252')
        try:
            call_command('seed_users', stdout=stream)
            User.objects.filter(username='admin').update(is_active=False)
            call_command('seed_users', stdout=stream)
            call_command('seed_users', stdout=stream)
        except UnicodeEncodeError as exc:
            self.fail(f'非 CJK 码页上 seed 写不出 stdout（命令会退 1）：{exc}')
        stream.flush()
        stale.refresh_from_db()
        self.assertEqual(stale.role, 'user', 'cp1252 之路上兜底仍要真的归并')
        data = raw.getvalue()
        for marker in (b'Created user:', b'Updated user:', b'User already exists:',
                       b'viewer_to_user', b'Seed users completed.'):
            self.assertIn(marker, data, f'这一支没走到，cp1252 判据覆盖不到它：{data!r}')

    def test_seed_users_prints_when_only_superuser_promoted(self):
        """库里没有 viewer、只有一条遗留 superuser 时也必须出声。

        出声条件写成「只挑两类 viewer 计数」的话，这一形态会静默改数据：本用例
        刻意不建任何 viewer 行，让 `viewer_to_user` 与 `viewer_to_administrator`
        双双为 0，只有 `superuser_promoted` 非零。与 0012 迁移通路上的同名判据
        （`test_role_normalization.NormalizeRolesTests.
        test_migration_prints_when_only_superuser_promoted`）成对，差别只在通路。
        """
        stale_su = User.objects.create_superuser('only_su', 'o@localhost', PASSWORD)
        User.objects.filter(pk=stale_su.pk).update(role='user', is_staff=False)

        printed = io.StringIO()
        call_command('seed_users', stdout=printed)

        stale_su.refresh_from_db()
        self.assertEqual(stale_su.role, 'administrator')
        text = printed.getvalue()
        self._assert_counter(text, 'superuser_promoted', 1)
        lines = [line for line in text.splitlines() if 'superuser_promoted' in line]
        self.assertEqual(len(lines), 1, text)
        # 出声行的可编码性不在这里判（只查一行的判据会放过别的中文行）——
        # 由 test_seed_users_writes_clean_under_non_cjk_codepage 拿 cp1252 的流
        # 跑整条命令。


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_accounts_bootstrap'])
    sys.exit(1 if failures else 0)
