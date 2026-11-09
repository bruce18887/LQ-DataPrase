"""权限表是唯一判据源：role_can 真值表 + FeaturePermission 接线 + 视图不再硬编码角色。

契约出处：docs/superpowers/specs/2026-11-05-account-role-audit-design.md §3.1（只剩两级角色）
与 §3.2（权限表收敛到 5 个键 + role_can 纯函数）。

源码侧那两条判据各管一头，两条都会红于不同的坏法（都实测过）：
- require 侧：守卫区（`post()` 签名行 → 首个动作分发行）内必须出现两处
  `role_can(role, '<功能键>')`。把任一行退回硬编码 `role != 'administrator'`
  会让那处的表调用消失，于是这一侧红。正则允许换行与实参改名，所以「把调用拆成
  两行」这种无害重排不会误报。
- ban 侧：整份 `browse_views.py` 逐行禁「同一行既有 `role` 又有角色字面量」。
  只查守卫区是不够的：把 `role = 'administrator'` 写在分发行之下、或在别的分支里
  手写角色比较，require 侧两条正则照样命中，行为矩阵也逐字不变 ⇒ 其余判据全绿。
  行为矩阵分不清「视图里硬编码 administrator」与「表里 data_delete 恰好只有
  administrator」，两种实现在那张矩阵上同形，所以这一侧没有替代判据。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import TestCase  # noqa: E402

from apps.accounts.permissions import (  # noqa: E402
    FEATURE_PERMISSIONS,
    FeaturePermission,
    role_can,
)

User = get_user_model()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BROWSE_VIEWS = os.path.join(
    REPO_ROOT, 'apps', 'datafiles', 'views', 'browse_views.py',
)

# 守卫区两端（含 post 签名行，不含首行分发）：按源码文本锚点取，不写行号——
# 行号会随文件上方任何一次增删漂移，而这两段文本是 post() 的结构性边界。
_POST_DEF = '    def post(self, request):'
_FIRST_DISPATCH = "if action == 'delete_orphaned_db'"

# 全文扫描要禁的角色名：viewer 也要禁掉，Task 3 之后它连choices都不该有。
_ROLE_NAMES = ('administrator', 'user', 'viewer')

# 两处判定的期望形状，编译成模块级正则：第一个实参接受 `role` 这类局部变量、
# 改名后的变量，也接受 `request.user.role`；`\s` 覆盖换行，所以调用被折成两行不算红。
_ROLE_CAN_CALL = {
    feature: re.compile(r"role_can\(\s*[\w.]+\s*,\s*'%s'\s*\)" % feature)
    for feature in ('data_delete', 'data_repair_mutate')
}

# 功能键全集：多留一个历史键（收敛后只该有这些）或漏一个都算红。
EXPECTED_FEATURES = {
    'user_management', 'system_config', 'audit_log_view',
    'data_delete', 'data_repair_mutate',
}

# 两级角色 × 五个功能 = 10 格，逐格钉死真值表。这既是对契约的独立表述
# （不是把表抄一遍当断言），也保证「往某个键多加一个角色」这类变异必红。
EXPECTED_CAN = {
    'user_management': {'administrator': True, 'user': False},
    'system_config': {'administrator': True, 'user': False},
    'audit_log_view': {'administrator': True, 'user': False},
    'data_delete': {'administrator': True, 'user': False},
    'data_repair_mutate': {'administrator': True, 'user': True},
}


class RoleCanTests(TestCase):
    def test_truth_table(self):
        self.assertTrue(role_can('administrator', 'user_management'))
        self.assertTrue(role_can('administrator', 'system_config'))
        self.assertTrue(role_can('administrator', 'audit_log_view'))
        self.assertTrue(role_can('administrator', 'data_delete'))
        self.assertTrue(role_can('user', 'data_repair_mutate'))
        self.assertFalse(role_can('user', 'data_delete'))
        self.assertFalse(role_can('user', 'user_management'))
        # 上面 7 条是契约的可读表述，下面这段把 10 格补全（system_config/audit_log_view/
        # data_repair_mutate 各自的另一条腿原本没人钉）。
        for feature, by_role in EXPECTED_CAN.items():
            for role, expected in by_role.items():
                with self.subTest(role=role, feature=feature):
                    self.assertEqual(role_can(role, feature), expected)

    def test_two_roles_only(self):
        # viewer 已不存在：任何键都不该再列它（spec §3.1/§3.2）。
        for feature, roles in FEATURE_PERMISSIONS.items():
            self.assertNotIn('viewer', roles, feature)
        self.assertEqual(set(FEATURE_PERMISSIONS), EXPECTED_FEATURES)

    def test_unknown_feature_is_fail_closed(self):
        self.assertFalse(role_can('administrator', 'not_a_feature'))

    def test_permission_class_uses_the_table(self):
        # required_feature 命中表 ⇒ 判角色；缺失 ⇒ 放行（现状，别改成 403 一片）。
        class View:
            required_feature = 'user_management'

        request = type('R', (), {'user': User(role='user')})()
        self.assertFalse(FeaturePermission().has_permission(request, View()))
        request.user = User(role='administrator')
        self.assertTrue(FeaturePermission().has_permission(request, View()))

        # 「缺失 ⇒ 放行」这一支原本只在注释里，没有断言：把 return True 改成
        # return False 时全仓不红，而那是所有未声明键视图一起 403 的事故。
        class BareView:
            pass

        request.user = User(role='user')
        self.assertTrue(
            FeaturePermission().has_permission(request, BareView()),
            '未声明 required_feature 的视图必须维持放行',
        )

    def test_object_permission_delegates(self):
        # has_object_permission 只是转发；写成 False 会让管理员的详情操作全 403。
        class View:
            required_feature = 'user_management'

        request = type('R', (), {'user': User(role='user')})()
        permission = FeaturePermission()
        self.assertFalse(permission.has_object_permission(request, View(), None))
        request.user = User(role='administrator')
        self.assertTrue(permission.has_object_permission(request, View(), None))

    def test_browse_views_gate_calls_the_table(self):
        with open(BROWSE_VIEWS, encoding='utf-8') as handle:
            src = handle.read()
        start = src.index(_POST_DEF)
        end = src.index(_FIRST_DISPATCH, start)
        guard = src[start:end]

        # 两处判定都得真的走表；模式容忍换行与局部变量名，不焊版式。
        for feature, pattern in _ROLE_CAN_CALL.items():
            with self.subTest(feature=feature):
                self.assertRegex(guard, pattern)

    def test_browse_views_has_no_handwritten_role_gate(self):
        # require 侧只看得见守卫区，且区内的调用还在时它无从分辨实参被改写；
        # 这一侧扫全文，任何一行把「角色比较」和「角色字面量」写在一起都算违规。
        with open(BROWSE_VIEWS, encoding='utf-8') as handle:
            src = handle.read()
        offenders = []
        for line in src.splitlines():
            if line.lstrip().startswith('#'):
                continue
            if not re.search(r'\brole\b', line):
                continue
            if any(f"'{name}'" in line for name in _ROLE_NAMES):
                offenders.append(line.strip())
        self.assertEqual(offenders, [], '视图里仍有手写的角色门禁')


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_role_can'])
    sys.exit(1 if failures else 0)
