"""viewer 归并内核（spec §4）。

内核收 UserModel 为参数，因此能用真实模型直接测，不必构造 ProjectState；
迁移文件只负责在 RunPython 里把历史模型传进来。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.test import TestCase  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.accounts.role_migration import normalize_roles  # noqa: E402

PASSWORD = 'x-pass-12345678'

# 写集边界：内核只该动 role（superuser 两支还该动 is_staff），其余字段一律原样。
SNAPSHOT_FIELDS = ('role', 'is_staff', 'is_superuser', 'is_active', 'login_attempts')


def _snapshot(user):
    user.refresh_from_db()
    return {field: getattr(user, field) for field in SNAPSHOT_FIELDS}


def _mk(username, role, superuser=False):
    user = User.objects.create_user(
        username, f'{username}@localhost', PASSWORD, role=role
    )
    if superuser:
        # 绕开 create_superuser（它会强制 role=administrator），
        # 复现「历史库里 superuser + viewer」这种真实遗留行。
        User.objects.filter(pk=user.pk).update(
            is_superuser=True, is_staff=True
        )
        user.refresh_from_db()
    return user


class NormalizeRolesTests(TestCase):
    def test_plain_viewer_becomes_user(self):
        viewer = _mk('v1', 'viewer')
        # 先把这行摆成「viewer 但 is_staff=True」：那是真实可达形态
        # （apps/accounts/admin.py:17 把 is_staff 列在 Django admin 可编辑字段里）。
        # 不设这行，夹具自带 is_staff=False，下面那句整行快照对「顺手剥掉 is_staff」
        # 的越界写法比不出差异（质量复审 M6 实测存活）。
        User.objects.filter(pk=viewer.pk).update(is_staff=True)
        before = _snapshot(viewer)
        counts = normalize_roles(User)
        after = _snapshot(User.objects.get(username='v1'))
        # 整行快照：只断 role 的话，「顺手把 is_staff/is_active/login_attempts 也
        # 改了」这一类越界写法没人抓。
        self.assertEqual(
            after,
            {**before, 'role': 'user'},
            'viewer→user 这一支只许改 role',
        )
        self.assertTrue(after['is_staff'], '归并不许顺手剥掉后台准入')
        self.assertEqual(counts['viewer_to_user'], 1)
        self.assertEqual(counts['viewer_to_administrator'], 0)

    def test_superuser_viewer_becomes_administrator(self):
        viewer = _mk('v2', 'viewer', superuser=True)
        counts = normalize_roles(User)
        viewer.refresh_from_db()
        self.assertEqual(viewer.role, 'administrator')
        self.assertEqual(counts['viewer_to_administrator'], 1)

    def test_legacy_superuser_with_user_role_is_promoted(self):
        stale = _mk('legacy', 'user', superuser=True)
        counts = normalize_roles(User)
        stale.refresh_from_db()
        self.assertEqual(stale.role, 'administrator')
        self.assertEqual(counts['superuser_promoted'], 1)

    def test_promotion_keeps_staff_flag_in_sync(self):
        """两条 superuser 分支必须同时把 is_staff 钉成 True。

        Django admin 的准入是 `is_active and is_staff`
        （.venv/.../django/contrib/admin/sites.py:208 的 `has_permission` 原文），
        而启动期的 `_promote_superusers`（standalone.py:73-76）只挑
        `role != administrator` 的行、且同时写 role 与 is_staff；0012 若只改
        role，被改过的那两行就再没人补 is_staff（spec §4 第 3 步要求的正是与
        那条命令同口径）。
        """
        stale = _mk('s1', 'user', superuser=True)
        viewer_admin = _mk('s2', 'viewer', superuser=True)
        # 承重：_mk(superuser=True) 顺手把 is_staff 也置了 True，不显式抹掉的话
        # 下面两条 assertTrue 就退化成「断夹具自己写过的值」。删这行 ⇒ 本用例
        # 对 role-only 的错误实现不再红，而它是 is_staff 那笔写法的唯一防线。
        User.objects.filter(pk__in=[stale.pk, viewer_admin.pk]).update(is_staff=False)

        counts = normalize_roles(User)

        stale.refresh_from_db()
        viewer_admin.refresh_from_db()
        self.assertEqual(counts['superuser_promoted'], 1)
        self.assertEqual(counts['viewer_to_administrator'], 1)
        self.assertTrue(stale.is_staff, '遗留 superuser 提升要带上 is_staff')
        self.assertTrue(viewer_admin.is_staff, 'superuser+viewer 同理')

    def test_healthy_rows_untouched(self):
        # `administrator + is_superuser` 是真实库里最常见的健康行（models.py 的
        # create_superuser 与 standalone.py 的 bootstrap 建的就是它）。夹具少了
        # 它，「promoted 分支丢掉 exclude(role=administrator)」这种写法今天只被
        # 计数顺带撞到，「已经健康的库每次启动都误出声」那一形态零判据。
        su_admin = _mk('sa', 'administrator', superuser=True)
        admin = _mk('a', 'administrator')
        plain = _mk('u', 'user')
        counts = normalize_roles(User)
        self.assertEqual(
            counts,
            {'viewer_to_user': 0, 'viewer_to_administrator': 0, 'superuser_promoted': 0},
        )
        for user, expected in (
            (su_admin, 'administrator'), (admin, 'administrator'), (plain, 'user'),
        ):
            self.assertEqual(_snapshot(user)['role'], expected, user.username)
        self.assertTrue(_snapshot(su_admin)['is_staff'])

    def test_migration_0012_wires_the_kernel(self):
        """0012 必须真把内核接上，而不是只在迁移表里登记一行。

        被替换掉的那版判据只查 MigrationRecorder 有无这一行，属于纯存在性绊线：
        当时把 `merge_viewer_roles` 的函数体改成 `pass`，全仓一条都不会红（测试
        建库时库里没有 viewer 行）。所以这里直接调迁移模块里的 RunPython 函数：
        `apps.get_model` 走真实注册表即可。顺带覆盖「不静默改数据」那句 —— 它靠
        裸 print 落地，`call_command(stdout=)` 收不到，只能 redirect_stdout。
        """
        import contextlib
        import importlib
        import io

        from django.apps import apps as django_apps
        from django.db.migrations.recorder import MigrationRecorder

        mod = importlib.import_module(
            'apps.accounts.migrations.0012_normalize_user_roles'
        )
        _mk('mig_plain_viewer', 'viewer')
        su_viewer = _mk('mig_super_viewer', 'viewer', superuser=True)
        User.objects.filter(pk=su_viewer.pk).update(is_staff=False)

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            mod.merge_viewer_roles(django_apps, None)

        self.assertEqual(User.objects.get(username='mig_plain_viewer').role, 'user')
        su_viewer.refresh_from_db()
        self.assertEqual((su_viewer.role, su_viewer.is_staff),
                         ('administrator', True))
        self.assertFalse(User.objects.filter(role='viewer').exists())
        printed = captured.getvalue()
        self.assertIn('viewer_to_administrator', printed)
        self.assertIn('viewer_to_user', printed)
        self.assertTrue(
            MigrationRecorder.Migration.objects.filter(
                app='accounts', name='0012_normalize_user_roles'
            ).exists(),
            '0012 必须已在测试库应用（本仓测试库每次建库都会跑全部迁移）',
        )

    def test_migration_prints_when_only_superuser_promoted(self):
        """库里没有 viewer、只有一条遗留 superuser 时也必须出声。

        这正是计划原写法（只看两类 viewer 计数进文案）会静默改数据的形态；
        质量复审把条件改回那两类跑了一遍 —— 6/6 全绿，说明它当时没有哨兵。
        """
        import contextlib
        import importlib
        import io

        from django.apps import apps as django_apps

        mod = importlib.import_module(
            'apps.accounts.migrations.0012_normalize_user_roles'
        )
        stale = _mk('mig_promoted_only', 'user', superuser=True)
        User.objects.filter(pk=stale.pk).update(is_staff=False)

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            mod.merge_viewer_roles(django_apps, None)

        stale.refresh_from_db()
        self.assertEqual((stale.role, stale.is_staff), ('administrator', True))
        self.assertIn('superuser_promoted', captured.getvalue())


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_role_normalization'])
    sys.exit(1 if failures else 0)
