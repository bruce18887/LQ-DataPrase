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


class RoleChoiceApiGuardTests(TestCase):
    """choices 收敛后，API 必须拒掉 viewer。

    拒斥来自 Python 侧的 choices（DRF 的 ModelSerializer 从 `User.role` 字段推
    ChoiceField），与 0013 那道 AlterField 无关：本仓六个 settings 档全是 sqlite3
    （`config/settings/*.py` 的 ENGINE），`manage.py sqlmigrate accounts 0013` 实测
    只输出 `(no-op)`，所以这三条只需改完 models.py 就能跑，不必等迁移。ORM 直写
    仍然不经校验（库里可以留着 viewer 行），那正是 0012 数据归并与 seed_users
    兜底要管的形状。
    """

    def setUp(self):
        from rest_framework.test import APIClient

        self.admin = User.objects.create_superuser('a-guard', 'a@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_create_rejects_viewer(self):
        resp = self.client.post(
            '/api/v1/auth/users/',
            {'username': 'v-new', 'password': PASSWORD, 'role': 'viewer'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'validation_error')
        # 只断 400 分不清「role 被 choices 拒了」与「任何别的字段都 400」，
        # 后者会让这三条在整条端点被写坏时照样绿。
        self.assertIn('role', resp.json()['detail'])

    def test_update_rejects_viewer(self):
        target = User.objects.create_user('v-target', 't@localhost', PASSWORD)
        resp = self.client.put(
            f'/api/v1/auth/users/{target.id}/', {'role': 'viewer'}, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('role', resp.json()['detail'])
        target.refresh_from_db()
        self.assertNotEqual(target.role, 'viewer')

    def test_model_choices_have_two_roles(self):
        self.assertEqual(
            [c[0] for c in User.ROLE_CHOICES], ['administrator', 'user']
        )


class MigrationChainShapeTests(TestCase):
    """迁移图的形状判据：单叶 + 0013 声明在 0012 之后。

    刻意**不**断「叶子叫 0013」——那会把链末端焊死在这批的文件名上，下一批合法
    新增 0014 时立刻假红。三种坏法各自的落点都实测过（`requirements/base.txt:27`
    钉的 Django 6.0.9 里取叶子是 `MigrationGraph.leaf_nodes(app)`，
    `MigrationLoader` 上并没有 `leaf_migrations`）：
    * 0013 漏写/改写 `dependencies` 造成并列两叶：建测试库时 Django 自己先中止，
      报 `CommandError: Conflicting migrations detected; multiple leaf nodes in
      the migration graph: (0012_normalize_user_roles, 0013_remove_viewer_role_choice
      in accounts).`，本用例根本轮不到跑；本条断言因此是那份不变量的**可读副本**，
      不是唯一防线。
    * 0012 被删：同样是建库期先炸 —— `NodeNotFoundError: Migration
      accounts.0013_remove_viewer_role_choice dependencies reference nonexistent
      parent node ('accounts', '0012_normalize_user_roles')`。
    * **两条迁移都还在、图仍然单叶、但声明顺序被倒过来**（0013 挂 0011、0012 改挂
      0013）：Django 不报错，只有本条变红 —— 其余 seed/内核/API 门禁用例全绿。
      代价要说实话：倒序在任何内置后端都不会真的约束住行 —— choices 从不进 SQL，
      `_field_db_check` 只按 `data_type_check_constraints` 生成 CHECK，而那张表里
      只有 Positive* 三类整数（6.0.9 的 `django/db/backends/base/schema.py:925-933`
      与 `postgresql/base.py:126-130`）。本仓 `sqlmigrate accounts 0013` 出来就是
      `(no-op)`。所以这条守的是「先改声明、再动数据」的顺序约定本身：约定一松，
      下一个真动列定义的迁移就会排到归并之前，那时才炸。
    """

    def test_single_leaf_and_parentage(self):
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader

        loader = MigrationLoader(connection)
        leaves = loader.graph.leaf_nodes('accounts')
        self.assertEqual(len(leaves), 1, f'accounts 迁移链应只有一个叶子，实为 {leaves}')

        parent = ('accounts', '0012_normalize_user_roles')
        child = ('accounts', '0013_remove_viewer_role_choice')
        for node in (parent, child):
            self.assertIn(node, loader.graph.nodes, f'{node} 必须在迁移图里')
        self.assertIn(parent, loader.get_migration(*child).dependencies,
                      '0013 必须声明接在 0012 之后')

    def test_0013_declaration_matches_the_model_field(self):
        """0013 的 AlterField 必须与 `User.role` 现在的定义逐字一致。

        没有这条时，把 0013 里的 choices/default/label 改成任何一个别的值都全绿：
        校验走的是 Python 侧的 `ROLE_CHOICES`，`sqlmigrate` 又是 no-op，
        `makemigrations --check` 虽然会退 1，但它不在本仓任何一档门禁里。所以漂移
        只能由这条钉住（它是那句「迁移只是声明卫生」的 enforcement）。
        """
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader

        migration = MigrationLoader(connection).get_migration(
            'accounts', '0013_remove_viewer_role_choice'
        )
        operations = [
            op for op in migration.operations
            if op.model_name == 'user' and op.name == 'role'
        ]
        self.assertEqual(len(operations), 1, f'应恰好一条 role AlterField，实为 {operations}')
        field = operations[0].field
        model_field = User._meta.get_field('role')
        self.assertEqual(field.choices, model_field.choices)
        self.assertEqual(field.default, model_field.default)
        self.assertEqual(field.max_length, model_field.max_length)


class MigrationPrintCodepageTests(TestCase):
    """0012 那句计数 print 必须在非 CJK 码页上写得出 —— 与 seed 侧同一条理由。

    坏法实测：把 `0012_normalize_user_roles.py` 的 print 文案换成中文，本仓所有
    用例照样绿（`call_command(stdout=)` 收不到裸 print，`redirect_stdout` 的代理
    判据又只看字符串），而它一旦炸在迁移事务里，整条升级就停在建库中途。这里拿
    cp1252 的流真的跑一次 RunPython：写不下去就红，改文案措辞不误报。
    """

    def test_merge_print_writes_clean_under_non_cjk_codepage(self):
        import contextlib
        import importlib
        import io

        from django.apps import apps as django_apps

        mod = importlib.import_module(
            'apps.accounts.migrations.0012_normalize_user_roles'
        )
        _mk('mig_cp1252_viewer', 'viewer')

        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='cp1252')
        try:
            with contextlib.redirect_stdout(stream):
                mod.merge_viewer_roles(django_apps, None)
        except UnicodeEncodeError as exc:
            self.fail(f'非 CJK 码页上 0012 的出声写不出（会炸在迁移事务里）：{exc}')
        stream.flush()
        self.assertEqual(User.objects.get(username='mig_cp1252_viewer').role, 'user')
        self.assertIn(b'viewer_to_user', raw.getvalue(), '出声不能因为换码页就丢')


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_role_normalization'])
    sys.exit(1 if failures else 0)
