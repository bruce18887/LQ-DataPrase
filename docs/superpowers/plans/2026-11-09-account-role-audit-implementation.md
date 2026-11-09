# 账号角色收敛与操作审计 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把角色模型收敛为 administrator/user 两级（历史 viewer 归并），并新增账号安全审计表 `AuditEvent`、审计写入器、管理员查询 API 与独立管理页，同时修复登录不写 `last_login`。

**Architecture:** 后端 Django app `apps/accounts` 承载角色定义、权限判据 `role_can`、审计模型与写入器；审计事件码以 `apps/accounts/audit.py` 的 `AUDIT_EVENTS` 为唯一清单，前端 `utils/audit.ts` 的标签表与之双向钉死。前端新增 `/admin/audit` 页（`requiresAdmin` 守卫已存在并生效）与用户管理「编辑」弹窗；`requiresAdmin` 与后端 `FeaturePermission` 构成纵深防御。

**Tech Stack:** Django 6 + DRF + SimpleJWT（unittest runner，禁 pytest）、Vue 3 + Element Plus + Pinia、vitest（T2，node 环境）、Playwright（T3）。

**Spec:** `docs/superpowers/specs/2026-11-05-account-role-audit-design.md`（提交 `87170d6`）。本计划与 spec 的字面差异只有两处，均写在对应任务里：迁移拆成 0012/0013（Task 1/3）、`admin.spec.ts` 那条竞态断言改为断守卫真实落点（Task 12）。

---

## 全局约定（每个任务都适用）

- 后端测试唯一 runner 是 unittest：`.venv/Scripts/python.exe manage.py test <dotted.path> -v 2`，仓库根执行，默认档 `config.settings.unit`（库落 `test/unit-data`，**永不碰 `db.sqlite3` 与 `~/LQ-DataPrase/db.sqlite3`**）。
- 前端命令一律 `cd frontend`。门禁判绿只取日志末尾 `RESULT:` 行，不取 `$?`；`NO AFFECTED TESTS` 不是绿灯；`verdict=VOID (infra)` 必须按基建轮复跑。
- 批内 `npm run test:e2e:affected`；收口 `node scripts/e2e_pool.mjs --slots=4` + 后端全套。改 `apps/accounts/**` 会被 `scripts/affected-rules.mjs:96` 判成 `GLOBAL`（全量池），预期如此，不是配错。
- 600 行上限适用于被跟踪的 `.py`/`.ts`/`.vue`（**含测试文件**，`.vue` 按整文件计）。新建文件写完即查：`wc -l <文件>`。
- 前端新样式只用 token（`--bg --bg-2 --bg-3 --card --border --border-2 --text --text-2 --text-3 --brand --success --warn --error --p-fs-* --shadow-*`，住在 `src/styles/design-tokens.css`；主题名是 `night` 不是 `dark`）。两套主题都必须在。
- Element Plus 标签受绊线双向钉住：新页面只允许用清单里的 49 件（`src/constants/element-plus-usage.ts`）。本计划用到的 `card/table/table-column/select/option/input/date-picker/pagination/dialog/empty/tag/button/divider` **全部已在清单内**；若你引入了别的标签，必须同时改清单与 `test/unit/elementPlusUsage.spec.ts:147` 的 `expect(list.length).toBe(49)`。
- 提交信息用中文 Conventional Commits（对齐仓内既有风格：`fix(accounts): …（括号给根因）`）。
- `docs/tasks/todo.md` 本轮**不提交**：工作树里有另一会话未提交的 396 行新增，`git add` 会把它的正文带进本批 commit。台账条目照常追加，落地时机在 Task 14 说明。

---

## 文件结构

| 动作 | 文件 | 职责 |
|---|---|---|
| Create | `apps/accounts/role_migration.py` | viewer 归并内核（纯函数，可脱离 RunPython 测试） |
| Create | `apps/accounts/migrations/0012_normalize_user_roles.py` | 数据归并（RunPython，反向 no-op） |
| Create | `apps/accounts/migrations/0013_remove_viewer_role_choice.py` | `role.choices` 收敛（AlterField） |
| Create | `apps/accounts/migrations/0014_auditevent.py` | 建审计表（`makemigrations` 生成） |
| Create | `apps/accounts/audit.py` | 事件码清单 `AUDIT_EVENTS` + best-effort 写入器 `record()` |
| Create | `test/backend/test_role_normalization.py` | T1：归并内核 |
| Create | `test/backend/test_role_can.py` | T1：权限表与 `role_can` |
| Create | `test/backend/test_audit_writer.py` | T1：写入器（快照/截断/IP/异常兜底） |
| Create | `test/backend/test_audit_login_events.py` | T1：登录族事件与 `last_login` |
| Create | `test/backend/test_audit_account_events.py` | T1：CRUD/重置/解锁/改密/存储路径事件 |
| Create | `test/backend/test_audit_api.py` | T1：查询 API 权限/筛选/分页/参数错误 |
| Create | `frontend/src/api/audit.ts` | 审计查询 client |
| Create | `frontend/src/utils/audit.ts` | 事件标签表、筛选转 query、detail 摘要（纯函数） |
| Create | `frontend/test/unit/audit.spec.ts` | T2：上面三件 + 与后端事件码清单一致性 |
| Create | `frontend/src/pages/admin/AuditLogPage.vue` | `/admin/audit` 页 |
| Create | `frontend/e2e/admin/audit.spec.ts` | T3：审计页与编辑弹窗 |
| Modify | `apps/accounts/models.py` | `ROLE_CHOICES` 去 viewer、新增 `AuditEvent` |
| Modify | `apps/accounts/permissions.py` | 权限表收敛 + `role_can` |
| Modify | `apps/accounts/views.py` | 登录 `last_login`、审计接线、`AuditEventListView` |
| Modify | `apps/accounts/urls.py` | `audit-events/` 路由 |
| Modify | `apps/accounts/serializers.py` | `AuditEventSerializer`、docstring 去 viewer |
| Modify | `apps/accounts/management/commands/seed_users.py` | 不再建 viewer + 归并兜底 |
| Modify | `apps/common/views.py` | 存储路径变更审计 |
| Modify | `apps/datafiles/views/browse_views.py` | 角色判定改走 `role_can` |
| Modify | 8 个既有后端测试 + 5 个前端/e2e 文件 + 3 份入库文档 | viewer 引用清理（Task 3/4 给逐串替换表） |

---

## Task 1: viewer 归并内核与数据迁移（不动 choices）

**Files:**
- Create: `apps/accounts/role_migration.py`
- Create: `apps/accounts/migrations/0012_normalize_user_roles.py`
- Test: `test/backend/test_role_normalization.py`

拆成两步的理由：spec §4 把 `RunPython` 与 `AlterField` 写进同一个 0012。但本批每个 commit 都要过门禁——`AlterField` 一旦落地，API 立即拒绝 `role=viewer`，`frontend/e2e/admin/admin.spec.ts:237` 与 6 个后端测试当场变红。所以先落**行为中性的数据归并**（Task 1），再把 choices 与全部引用清理**同一 commit** 落地（Task 3）。

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_role_normalization.py`：

```python
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
        counts = normalize_roles(User)
        viewer.refresh_from_db()
        self.assertEqual(viewer.role, 'user')
        self.assertEqual(counts['viewer_to_user'], 1)
        self.assertEqual(counts['viewer_to_administrator'], 0)

    def test_superuser_viewer_becomes_administrator(self):
        viewer = _mk('v2', 'viewer', superuser=True)
        counts = normalize_roles(User)
        viewer.refresh_from_db()
        self.assertEqual(viewer.role, 'administrator')
        self.assertEqual(counts['viewer_to_administrator'], 1)

    def test_legacy_superuser_with_user_role_is_promoted(self):
        # 与 standalone._promote_superusers 同口径：superuser 必然是管理员。
        stale = _mk('legacy', 'user', superuser=True)
        counts = normalize_roles(User)
        stale.refresh_from_db()
        self.assertEqual(stale.role, 'administrator')
        self.assertEqual(counts['superuser_promoted'], 1)

    def test_healthy_rows_untouched(self):
        admin = _mk('a', 'administrator')
        plain = _mk('u', 'user')
        counts = normalize_roles(User)
        admin.refresh_from_db()
        plain.refresh_from_db()
        self.assertEqual((admin.role, plain.role), ('administrator', 'user'))
        self.assertEqual(
            counts,
            {'viewer_to_user': 0, 'viewer_to_administrator': 0, 'superuser_promoted': 0},
        )

    def test_is_run_after_migration(self):
        # 迁移必须已经落在本测试之前可用：0012 存在且已被应用。
        from django.db import connection
        from django.apps import apps as django_apps
        recorder = django_apps.get_app_config('accounts')
        self.assertTrue(recorder.models['user'].fields)
        self.assertIn('accounts_user', connection.introspection.table_names())
```

最后一条只是「迁移跑得起来」的绊线，真正的 RunPython 覆盖由 Step 3 之后的全量测试轮（测试库建库时就会执行 0012）承担。

- [ ] **Step 2: 跑到红**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_role_normalization -v 2`
Expected: `ModuleNotFoundError: No module named 'apps.accounts.role_migration'`（collection error，非断言失败）

- [ ] **Step 3: 写内核**

创建 `apps/accounts/role_migration.py`：

```python
"""viewer → user/administrator 的归并内核。

被两处调用：迁移 `0012_normalize_user_roles`（历史库升级）与 `seed_users`
（dev/e2e 夹具库的幂等兜底）。收模型类为参数，迁移里传的是 RunPython 的历史
模型，测试里传的是真实模型 —— 因此本模块**不得 import models**（循环 + 拿到
未来 schema）。
"""

VIEWER = 'viewer'
ADMINISTRATOR = 'administrator'
USER = 'user'


def normalize_roles(UserModel):
    """把 viewer 归并进两级模型，并补一遍 superuser→administrator。

    返回三类计数，调用方据此打印，别静默改数据。
    顺序有讲究：先升 superuser 的 viewer（否则第一步就把它们并成 user，
    第三步再升上来会把计数算错）。
    """
    to_admin = UserModel.objects.filter(
        role=VIEWER, is_superuser=True
    ).update(role=ADMINISTRATOR)
    to_user = UserModel.objects.filter(role=VIEWER).update(role=USER)
    promoted = UserModel.objects.filter(is_superuser=True).exclude(
        role=ADMINISTRATOR
    ).update(role=ADMINISTRATOR)
    return {
        'viewer_to_administrator': to_admin,
        'viewer_to_user': to_user,
        'superuser_promoted': promoted,
    }
```

- [ ] **Step 4: 写迁移（RunPython + 反向 no-op）**

创建 `apps/accounts/migrations/0012_normalize_user_roles.py`：

```python
from django.db import migrations

from apps.accounts.role_migration import normalize_roles


def merge_viewer_roles(apps, schema_editor):
    UserModel = apps.get_model('accounts', 'User')
    counts = normalize_roles(UserModel)
    if counts['viewer_to_user'] or counts['viewer_to_administrator']:
        print(f"[0012] viewer 归并：{counts}")


def no_op(apps, schema_editor):
    """反向故意留空：viewer 的独立身份按已批准决策不再恢复，
    只允许后面的 choices 迁移自身回退（spec §4）。"""


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0011_chart_dpi_default_100'),
    ]

    operations = [
        migrations.RunPython(merge_viewer_roles, no_op),
    ]
```

- [ ] **Step 5: 跑到绿**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_role_normalization -v 2`
Expected: `Ran 5 tests … OK`

再验迁移本身可正向应用且无待生成改动：

```
.venv/Scripts/python.exe manage.py migrate accounts 0012 --plan
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
```
Expected: 第一行末条是 `accounts.0012_normalize_user_roles`；第二行 `No changes detected`、退出码 0。

- [ ] **Step 6: 提交**

```bash
git add apps/accounts/role_migration.py apps/accounts/migrations/0012_normalize_user_roles.py test/backend/test_role_normalization.py
git commit -m "feat(accounts): 落 viewer 归并内核与 0012 数据迁移（choices 暂不动，先保证每步绿灯）"
```

### Step 6.5 实施期校正（已回写，后续任务以此为准）

实施 + 双重复审后，上面三个代码块有 5 处偏离，树里落的是校正后的版本：

- **两条 superuser 分支都带 `is_staff=True`**（`.update(role=ADMINISTRATOR, is_staff=True)`）。理由实测在 `standalone.py:73-76`：启动期 `_promote_superusers` 同时写两个字段，且只挑 `exclude(role='administrator')` 的行——0012 若只改 role，那两行启动期再也看不见，`is_staff` 永久留 False，而 admin 准入是 `is_active and is_staff`（`django/contrib/admin/sites.py:208`）。等价性只到「挑哪些行、写哪些值」，不含 save/信号（这里走 queryset.update()，与 spec §4「批量改为」一致）。哨兵用例：`test_promotion_keeps_staff_flag_in_sync`。
- **迁移的打印条件改 `if any(counts.values()):` 且带 `flush=True`**。计划原写法在「库里只有遗留 superuser、没有 viewer」时（`superuser_promoted=1`）会一声不响地改数据，与内核 docstring「不静默改数据」正面冲突；`flush` 是本仓启动期打印惯例（`standalone.py` 15 处）且 Electron 按行消费后端 stdout（`electron/backend.ts:314`）。
- **`test_migration_0012_is_applied` 换成 `test_migration_0012_wires_the_kernel`**：原条只查 `MigrationRecorder` 有无那行，把 `merge_viewer_roles` 函数体改成 `counts = {}` 全仓不红（纯存在性绊线）。新条直接 `importlib` 拿迁移模块调 `merge_viewer_roles(django_apps, None)`，断两支归并结果 + `is_staff` + 「不再残留 viewer」+ stdout 里两类计数都在文案里。变异自证：摘掉内核接线 ⇒ 恰好这一条红（`Ran 6 tests / FAILED (failures=1)`），按字节还原后 `sha256` 与还原前一致。
- **用例数 5 → 6**，故 Step 5 的 `Expected: Ran 5 tests … OK` 实为 `Ran 6 tests in 2.9s / OK`。
- **内核 docstring 两处措辞**：`seed_users` 的接入是 Task 3（当下 grep 只有迁移 + 测试两处引用，计划原文「被两处调用」在落地当时是假话）；「循环引用」改成条件句（models 侧目前不引用它）。
- **spec 勘误**：`§4` 第 3 步原文写的 `_promote_legacy_superusers` 全仓不存在，真实是 `standalone.py:62 _promote_superusers`，已就地改 spec。

**连带要求（Task 3 必须照此办，否则把刚修掉的漏洞装回去）**：Task 3 Step 3 里 `seed_users` 的打印条件同样必须写 `if any(merged.values()):`，不是 `merged['viewer_to_user'] or merged['viewer_to_administrator']`。

Task 1 的门禁实测：`npm run test:e2e:affected` → 4 档全跑（`lint:e2e ok / vitest ok / backend ok / e2e:全量 ok`）、`RESULT: PASS`，池 `结论 MEASURED`；后端全量 `Ran 2388 tests … OK (skipped=8)`。

**质量复审后追加（最终形态以此为准）**：11 记变异里 3 记存活，全是断言缺口而非代码错，已补齐并逐记重验：

- `test_migration_prints_when_only_superuser_promoted`（新）：杀「打印条件退回两类 or」。夹具只有一条遗留 superuser、无 viewer ⇒ 计划原写法静默改数据且全仓不红。
- `test_healthy_rows_untouched` 补 `administrator + is_superuser` 这一行（真实库里最常见的健康行，由 `models.py:22-27` 与 `standalone.py:114` 建出）：杀「promoted 分支丢 `exclude(role=administrator)`」，此前只被计数顺带撞到。
- `test_plain_viewer_becomes_user` 改整行快照，且**先把夹具摆成 `viewer + is_staff=True`**（真实可达：`apps/accounts/admin.py:17` 把 is_staff 列为可编辑字段）：杀「viewer→user 顺手剥掉 is_staff」。**第一版补的快照仍抓不住这记**，因为 `create_user` 自带 `is_staff=False`，整行比对照样相等 —— 又一个「夹具自带断言值」的形状，后续任务写快照类判据时先确认夹具不是零差异起点。
- `0012` 的打印文案改 ASCII（`[0012] role normalization: {counts}`）：局域网服务器上人手 `manage.py migrate` 且输出重定向、码页非 CJK 时，中文 print 抛 `UnicodeEncodeError` 会连带回滚整个迁移 —— 数据无损但「升级当场趴」。`docs/reference/server-deployment.md` 的升级步骤已在要求 `PYTHONIOENCODING=utf-8`，这条是双保险。
- 测试文件补 `if __name__ == '__main__'` runner：有 preamble 没 runner 时，直跑是 `EXIT=0 且 0 条用例` 的假绿形状。
- 内核 docstring 补两条调用方契约（三支互斥 ⇒ `sum(counts.values())` 即被改动行数、判「有没有改」用 `any()` 而不是挑单键；幂等 ⇒ 第二次全 0），这两条正是 Task 3 兜底调用点的地基。
- 删掉一条恒真断言（`'accounts_user' in table_names()` 与 0012 有无无关）；把描述旧版本的现在时句子改成过去时。
- 措辞更正：本文档 Task 1 标题处的「纯函数」不准确 —— `normalize_roles` 会写库、返回值不承载新状态，是**命令**；准确说法是「可脱离 RunPython 独立测试的迁移内核」。
- 采纳复审对控制器一处质疑的否证：`RunPython` 上下文里**没有** `stdout` 可用（Django 6.0.9 `special.py:199` 只传 `(apps, schema_editor)`，`BaseDatabaseSchemaEditor` 无 stdout；而 `standalone.py:97` 用 `verbosity=0` 跑 migrate），所以裸 `print` + `flush=True` 是正解，不是偷懒。
- 推迟到 Task 3 再处理：`superuser_promoted` 键名改成与另两键同构（`superuser_to_administrator`）、用 `MigrationLoader(...).leaf_migrations('accounts')` 换掉 recorder 存在性断言（顺带钉住 Task 3 的依赖边，此刻改会立刻被 0013 翻掉）。

Task 1 最终自证（控制器亲自跑，逐记还原后 sha256 与原始字节一致）：基线 `Ran 7 tests … OK`；M3→1 红、M2→2 红、M6→1 红；`python test/backend/test_role_normalization.py` 直跑 `EXIT=0 Ran 7 OK`。

---

## Task 2: 权限表收敛与 `role_can`

**Files:**
- Modify: `apps/accounts/permissions.py:3-31`
- Modify: `apps/datafiles/views/browse_views.py:248-254`（注释）与 `:343-348`（判定）
- Test: `test/backend/test_role_can.py`

行为中性可证：被删的 4 个键（`dashboard_view`/`data_export`/`analysis_view`/`report_view`）全仓**没有消费者**（`required_feature` 只出现在 `apps/accounts/views.py:304`、`apps/common/views.py:37` 与 `:77`）；`data_delete`/`data_repair_mutate` 的角色集合逐字等于 `browse_views.py:345/347` 现有的硬编码判定。

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_role_can.py`：

```python
"""权限表是唯一判据源：role_can 真值表 + FeaturePermission 接线 + 视图不再硬编码角色。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import TestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.permissions import (  # noqa: E402
    FEATURE_PERMISSIONS,
    FeaturePermission,
    role_can,
)

User = get_user_model()
PASSWORD = 'x-pass-12345678'

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _client(role):
    user = User.objects.create_user(f'u-{role}', f'{role}@localhost', PASSWORD, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class RoleCanTests(TestCase):
    def test_truth_table(self):
        self.assertTrue(role_can('administrator', 'user_management'))
        self.assertTrue(role_can('administrator', 'system_config'))
        self.assertTrue(role_can('administrator', 'audit_log_view'))
        self.assertTrue(role_can('administrator', 'data_delete'))
        self.assertTrue(role_can('user', 'data_repair_mutate'))
        self.assertFalse(role_can('user', 'data_delete'))
        self.assertFalse(role_can('user', 'user_management'))

    def test_two_roles_only(self):
        # viewer 已不存在：任何键都不该再列它（spec §3.1/§3.2）。
        for feature, roles in FEATURE_PERMISSIONS.items():
            self.assertNotIn('viewer', roles, feature)
        self.assertEqual(
            set(FEATURE_PERMISSIONS),
            {'user_management', 'system_config', 'audit_log_view',
             'data_delete', 'data_repair_mutate'},
        )

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

    def test_browse_views_no_longer_hardcodes_roles(self):
        src = open(
            os.path.join(REPO_ROOT, 'apps', 'datafiles', 'views', 'browse_views.py'),
            encoding='utf-8',
        ).read()
        self.assertNotIn("role not in ('administrator', 'user')", src)
        self.assertIn('role_can(role, ', src)
```

- [ ] **Step 2: 跑到红**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_role_can -v 2`
Expected: `ImportError: cannot import name 'role_can' from 'apps.accounts.permissions'`

- [ ] **Step 3: 改权限表**

把 `apps/accounts/permissions.py` 整体替换为：

```python
from rest_framework.permissions import BasePermission

# 唯一判据表：视图里不许再硬编码角色字符串（历史教训：表、文档、实现三处漂过）。
# 只列当前真实需要的功能；未列出的功能名 ⇒ 一律拒绝（fail closed）。
FEATURE_PERMISSIONS = {
    'user_management': ['administrator'],
    'system_config': ['administrator'],
    'audit_log_view': ['administrator'],
    'data_delete': ['administrator'],
    'data_repair_mutate': ['administrator', 'user'],
}


def role_can(role, feature):
    """角色是否具备某功能。FeaturePermission 与自带判定的视图共用。"""
    return role in FEATURE_PERMISSIONS.get(feature, [])


class FeaturePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if hasattr(view, 'required_feature'):
            return role_can(request.user.role, view.required_feature)
        return True

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
```

- [ ] **Step 4: 数据一致性视图改走权限表**

`apps/datafiles/views/browse_views.py`：在 import 段加一行（紧邻既有 `from apps...` 组）：

```python
from apps.accounts.permissions import role_can
```

把注释块 `:248-254` 换成（原文引用了 viewer，删角色后就是假文档）：

```python
# Consistency-check write actions. Delete is destructive, so it is restricted by
# FEATURE_PERMISSIONS['data_delete']; import/fix are additive and mirror upload
# privileges ('data_repair_mutate'). GET stays IsAuthenticated: reading the
# report is not a mutation.
_DELETE_ACTIONS = ('delete_orphaned_db', 'delete_orphaned_disk', 'delete_duplicates')
_MUTATE_ACTIONS = ('import_orphaned_disk', 'fix_product_codes')
_ALL_ACTIONS = _DELETE_ACTIONS + _MUTATE_ACTIONS
```

把判定体 `:343-348` 换成：

```python
        user = request.user
        role = getattr(user, 'role', '')
        if action in _DELETE_ACTIONS and not role_can(role, 'data_delete'):
            return error_response('forbidden', '仅管理员可执行删除操作', 403)
        if action in _MUTATE_ACTIONS and not role_can(role, 'data_repair_mutate'):
            return error_response('forbidden', '当前角色无权执行该操作', 403)
```

- [ ] **Step 5: 跑到绿（含既有角色矩阵回归）**

```
.venv/Scripts/python.exe manage.py test test.backend.test_role_can apps.datafiles.tests.ConsistencyCheckTests -v 2
```
Expected: 两条一起 `OK`。`ConsistencyCheckTests.test_post_role_permissions` 此时仍建一个 `cc_viewer`，但它的断言只依赖「非 admin 且非 user」⇒ 全 403，收敛后行为不变（Task 3 才删它）。

再跑一次受影响面门禁（`apps/accounts/` 与 `apps/datafiles/` 都命中）：

```
cd frontend && npm run test:e2e:affected
```
Expected: 末行 `RESULT: PASS …`；若出现 `RESULT: NO AFFECTED TESTS` 说明本轮没有档执行，**不算绿**，改跑 `node scripts/e2e_pool.mjs --slots=4`。

- [ ] **Step 6: 提交**

```bash
git add apps/accounts/permissions.py apps/datafiles/views/browse_views.py test/backend/test_role_can.py
git commit -m "refactor(accounts): 权限表收敛为五项并新增 role_can，数据一致性判定改走表（行为逐字不变）"
```

---

## Task 3: role choices 收敛 + seed_users 去 viewer + 后端引用清理

**Files:**
- Modify: `apps/accounts/models.py:32-36`
- Create: `apps/accounts/migrations/0013_remove_viewer_role_choice.py`
- Modify: `apps/accounts/serializers.py:41`（docstring 举例）
- Modify: `apps/accounts/management/commands/seed_users.py:10,27-32,97`
- Modify: `test/backend/test_seed_users_guard.py`、`test/backend/test_accounts_bootstrap.py`、`test/backend/test_profile_privilege.py`、`test/backend/test_batch_dir_traversal.py`、`apps/accounts/tests.py`、`apps/common/tests_metrics.py`、`apps/common/tests_system_paths.py`、`apps/datafiles/tests.py`
- Modify: `frontend/e2e/admin/admin.spec.ts:237`（同一 commit，否则 e2e 当场红）

- [ ] **Step 1: 写失败测试**

在 `test/backend/test_role_normalization.py` 末尾追加（同一个类外新增类）：

```python
class RoleChoiceApiGuardTests(TestCase):
    """choices 收敛后，API 必须拒掉 viewer；ORM 仍写库（迁移前的历史行形状），
    所以这条只能在 AlterField 之后跑。"""

    def setUp(self):
        from rest_framework.test import APIClient
        from django.contrib.auth import get_user_model as _gum
        User = _gum()
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

    def test_update_rejects_viewer(self):
        from apps.accounts.models import User as U
        target = U.objects.create_user('v-target', 't@localhost', PASSWORD)
        resp = self.client.put(
            f'/api/v1/auth/users/{target.id}/', {'role': 'viewer'}, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        target.refresh_from_db()
        self.assertNotEqual(target.role, 'viewer')

    def test_model_choices_have_two_roles(self):
        from apps.accounts.models import User as U
        self.assertEqual(
            [c[0] for c in U.ROLE_CHOICES], ['administrator', 'user']
        )
```

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_role_normalization -v 2`
Expected: 新增 3 条红（`400 != 201`、`['administrator','user','viewer'] != [...]`）

- [ ] **Step 2: 改模型并生成 AlterField 迁移**

`apps/accounts/models.py:32-36` 的 `ROLE_CHOICES` 删掉 `('viewer', 'Viewer'),` 一行。

创建 `apps/accounts/migrations/0013_remove_viewer_role_choice.py`：

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0012_normalize_user_roles'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('administrator', 'Administrator'), ('user', 'User')],
                default='user',
                max_length=20,
            ),
        ),
    ]
```

- [ ] **Step 3: seed_users 去 viewer + 归并兜底**

`apps/accounts/management/commands/seed_users.py`：

`help` 行改为：

```python
    help = 'Seed default users (admin, user) for development'
```

`users_to_create` 里删掉整块 viewer 条目（`:27-32`）。在 `self._refuse_weak_seed_outside_dev()` 之后插入归并兜底（spec §4「幂等兜底」），并在末尾提示：

```python
        merged = normalize_roles(User)
        if merged['viewer_to_user'] or merged['viewer_to_administrator']:
            self.stdout.write(
                self.style.WARNING(f'归并历史 viewer：{merged}')
            )
```

import 段加 `from apps.accounts.role_migration import normalize_roles`（已有 `from apps.accounts.models import User, UserSetting`）。

守卫文案 `:97` 改为（两个口令，别留 `viewer123`）：

```python
            'seed_users 写入的是公开已知的弱口令（admin123 / user123），'
```

- [ ] **Step 4: 逐串清理后端既有测试**

下表每行是一次精确替换（old → new），照抄执行；「整段删」指删除该区间。

| 文件:行 | old | new |
|---|---|---|
| `apps/accounts/tests.py:263` | `'role': 'viewer',` | `'role': 'administrator',` |
| `apps/accounts/tests.py:270` | `self.assertEqual(self.target.role, 'viewer')` | `self.assertEqual(self.target.role, 'administrator')` |
| `apps/common/tests_metrics.py:128` | `self.viewer = User.objects.create_user('met_viewer', 'mv@localhost', PASSWORD,` | `self.other_plain = User.objects.create_user('met_plain2', 'p2@localhost', PASSWORD,` |
| `apps/common/tests_metrics.py:129` | `                                               role='viewer')` | `                                               role='user')` |
| `apps/common/tests_metrics.py:142` | 注释「运维数字里有路径、作业量、内存 —— viewer 不该看到。」 | 同句把 `viewer` 换成「普通用户」 |
| `apps/common/tests_metrics.py:143` | `self._get(self.viewer)` | `self._get(self.other_plain)` |
| `apps/common/tests_system_paths.py:27` | `self.viewer = self._mkuser('sysviewer', 'viewer')` | `self.plain2 = self._mkuser('sysplain2', 'user')` |
| `apps/common/tests_system_paths.py:59` | `self._auth_client(self.viewer)` | `self._auth_client(self.plain2)` |
| `apps/common/tests_system_paths.py:76` | 注释含「viewer 能看本机路径」 | 改「非管理员能看本机路径」 |
| `apps/common/tests_system_paths.py:86` `:116` | `for user in (self.plain, self.viewer):` | `for user in (self.plain, self.plain2):` |
| `apps/common/tests_system_paths.py:110` | `self._auth_client(self.viewer).put(` | `self._auth_client(self.plain2).put(` |
| `apps/datafiles/tests.py:1211-1219` | viewer 段（建 `cc_viewer` + GET 200 + 五 action 全 403） | **整段删**，并在 `:1224` 之后补 `self.assertEqual(self._get().status_code, 200)` |
| `apps/datafiles/tests.py:1215` | 尾注 `# viewer may check` | 随段删除（补的那行自带意义） |
| `test/backend/test_batch_dir_traversal.py:75` | `username='attacker', password='strong-pass-123', role='viewer')` | `username='attacker', password='strong-pass-123', role='user')` |
| `test/backend/test_profile_privilege.py:27-28` | `self.viewer = User.objects.create_user(` / `username='plain-joe', ... role='viewer',` | 属性改名 `self.plain`，`role='user'`，其余 `self.viewer` 全部跟着改名（`:41 :52 :59 :68 :78-80 :87`） |
| `test/backend/test_profile_privilege.py:6` | docstring「any viewer could promote itself」 | 「any regular user could promote itself」 |
| `test/backend/test_profile_privilege.py:101-102` | `self.target = User.objects.create_user(username='victim', ... role='user',` | `role='administrator',`（否则 `:110/:114` 改成 user 后断言恒真） |
| `test/backend/test_profile_privilege.py:110` | `{'role': 'viewer'}, format='json',` | `{'role': 'user'}, format='json',` |
| `test/backend/test_profile_privilege.py:114` | `self.assertEqual(self.target.role, 'viewer')` | `self.assertEqual(self.target.role, 'user')` |
| `test/backend/test_accounts_bootstrap.py:50-52` | `create_superuser('boss2', 'boss2@localhost', PASSWORD, role='viewer')` | `role='not_a_role'`（比 `'user'` 更有说服力：默认值也是 user，用无效字面量才证得出「无条件覆盖」） |
| `test/backend/test_accounts_bootstrap.py:131,133` | 三个种子的 dict/元组 | 各去掉 `('viewer', ...)` 项 |
| `test/backend/test_accounts_bootstrap.py:150` | `User.objects.filter(username__in=('admin', 'user', 'viewer')).update(is_active=False)` | 元组去 viewer |
| `test/backend/test_accounts_bootstrap.py:154` | `for username, password in (('admin', 'admin123'), ('user', 'user123'), ('viewer', 'viewer123')):` | 去第三项 |
| `test/backend/test_seed_users_guard.py:61,75` | 元组 `('admin','user','viewer')` | `('admin','user')`；`:75` 的 `count(), 3` → `2` |
| `test/backend/test_seed_users_guard.py:6,71` | 文案里的 `viewer/viewer123`、「这三个种子账号」 | 改成两个 |
| `apps/accounts/serializers.py:41` | docstring「so a writable ``role`` let any viewer promote itself」 | 「let any regular user promote itself」 |

注意 `test_profile_privilege.py:88-90` 只断键存在不断值，与后面的 `last_login`/审计改动无冲突，别顺手改。

- [ ] **Step 5: e2e 里那一处 role 载荷**

`frontend/e2e/admin/admin.spec.ts:237`：

```ts
        data: { username, password: 'e2e-initial-password', role: 'user' },
```
（`:143` 注释「避免污染种子账号（admin/user/viewer）」→「（admin/user）」。该用例测的是重置密码，与角色无关。）

- [ ] **Step 6: 跑到绿**

```
.venv/Scripts/python.exe manage.py test test.backend.test_role_normalization test.backend.test_accounts_bootstrap test.backend.test_seed_users_guard test.backend.test_profile_privilege test.backend.test_batch_dir_traversal apps.accounts apps.common apps.datafiles -v 2
```
Expected: 末行 `OK`，条数与改前一致（`apps/datafiles` 少了一处断言块，条数不变）。

```
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
```
Expected: `No changes detected`。

- [ ] **Step 7: 提交（含 e2e 那一行）**

```bash
git add apps/accounts/models.py apps/accounts/migrations/0013_remove_viewer_role_choice.py apps/accounts/management/commands/seed_users.py apps/accounts/serializers.py test/backend apps/common/tests_metrics.py apps/common/tests_system_paths.py apps/datafiles/tests.py frontend/e2e/admin/admin.spec.ts
git commit -m "feat(accounts): role choices 去掉 viewer，全仓后端引用与种子账号同步收敛"
```
（`git add` 路径请按实际改到的文件列全，别用 `.`；提交前 `git status --porcelain` 复核没有把 `docs/tasks/todo.md` 或别人的未跟踪稿卷进来。）

---

## Task 4: 前端与入库文档的 viewer 清理

**Files:**
- Modify: `frontend/src/types/index.ts:6`、`frontend/src/components/layout/Topbar.vue:129`、`frontend/src/components/layout/AccountDialog.vue:185`、`frontend/src/pages/admin/UserManagement.vue:113,173,179`
- Modify: `frontend/e2e/fixtures/test-data.ts:33-37`、`frontend/e2e/README.md:32,135`、`frontend/e2e/auth/account.spec.ts:8`
- Modify: `README.md:34,180`、`docs/reference/server-deployment.md:242-243,305-317,413`

`docs/user-guide/` 整目录被 `.gitignore:170` 忽略（源页与 dist 都不入库）——本任务只在 Task 13 里就地改本机文件并说明「改不了入库」，不在这里动。

- [ ] **Step 1: 改前端角色展示**

`frontend/src/types/index.ts:6`：

```ts
  role: 'administrator' | 'user'
```

`Topbar.vue` 的 `roleLabel` 与 `AccountDialog.vue` 的 `roleLabel`：各删掉 `if (role === 'viewer') return '查看者'` 一行（保留 `administrator` 分支与「用户」兜底——迁移失败的机器上仍会落到兜底，spec §7.3 要求不显示 viewer）。

`UserManagement.vue`：
- 删 `:113` 的 `<el-option label="查看者" value="viewer" />`。
- `roleIcon`（`:171-175`）删 `if (role === 'viewer') return '👁️'`；`roleLabel`（`:177-181`）删 viewer 行。

- [ ] **Step 2: 改 e2e 夹具与文案**

`frontend/e2e/fixtures/test-data.ts`：删 `:36` 整行（`viewer: { username: 'viewer', … }`）。`ACCOUNTS` 用 `as const`，`:39` 的 `export type Role = keyof typeof ACCOUNTS` 自动收窄成 `'admin' | 'user'`，`loginAs(page,'viewer')` 会变成类型错误（全仓无此调用，已核）。

`frontend/e2e/README.md:32` 与 `:135`、`frontend/e2e/auth/account.spec.ts:8`：把三处 `admin/user/viewer`、`viewer/viewer123` 改成两账号写法。

- [ ] **Step 3: 改入库文档**

`README.md:34`：

```markdown
- **权限管理**：基于角色的访问控制（管理员 / 普通用户）。
```

`README.md:180`：删掉整行 `| 浏览者 | viewer | viewer123 |`。

`docs/reference/server-deployment.md`：探针账号从 viewer 换成 user，并把「为什么用 user 也能证权限闸门」的理由留住。
- `:242-243` 的结论段：`viewer` 角色 → `user` 角色，`同一个 viewer 的 token` → `同一个 user 的 token`。
- `:305-317` 的第 5 条命令块里，把建探针账号那一行换成：

```bash
#    curl -s -X POST $BASE/api/v1/auth/users/ -H "Authorization: Bearer $TOK" \
#      -H 'Content-Type: application/json' \
#      -d '{"username":"probe_user","password":"<够长的口令>","role":"user"}'          # 期望 201
```

并把上方注释里的 `viewer 角色应 403` 同步成 `user 角色应 403`（`/api/v1/system/paths/` 的闸门是 `system_config: ['administrator']`，普通用户同样 403，对照仍然成立）。
- `:413` 升级补做口径里的 `viewer 403 对照` → `user 403 对照`。

- [ ] **Step 4: 验证**

```
cd frontend && npm run build && npx vitest run && npm run lint:e2e
```
Expected: `build` 里 `vue-tsc -b` 无错误；vitest 全绿；`lint:e2e`（tsc -p tsconfig.e2e.json）无错误。

```
grep -rn "viewer" frontend/src frontend/e2e README.md docs/reference | grep -v "\.md:.*历史" 
```
Expected: 只剩注释/历史说明类命中（理想为空）。若 `frontend/e2e/fixtures/test-data.ts` 仍出现 viewer，说明 Step 2 漏了。

```
cd frontend && npm run test:e2e:affected
```
Expected: 末行 `RESULT: PASS`（命中 `auth` + `admin` + `settings` 档）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/components/layout/Topbar.vue frontend/src/components/layout/AccountDialog.vue frontend/src/pages/admin/UserManagement.vue frontend/e2e/fixtures/test-data.ts frontend/e2e/README.md frontend/e2e/auth/account.spec.ts README.md docs/reference/server-deployment.md
git commit -m "refactor(roles): 前端角色展示与部署探针去掉 viewer，README/部署文档同步两级"
```

---

## Task 5: AuditEvent 模型、迁移与 best-effort 写入器

**Files:**
- Modify: `apps/accounts/models.py`（追加模型 + `settings` import）
- Create: `apps/accounts/migrations/0014_auditevent.py`（`makemigrations` 生成）
- Create: `apps/accounts/audit.py`
- Test: `test/backend/test_audit_writer.py`

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_audit_writer.py`：

```python
"""审计写入器：快照、截断、IP、以及「审计炸了业务不许跟着炸」（spec §5.4）。"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import AnonymousUser  # noqa: E402
from django.db import DatabaseError  # noqa: E402
from django.test import TestCase, RequestFactory  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts import audit  # noqa: E402
from apps.accounts.models import AuditEvent, User  # noqa: E402

PASSWORD = 'x-pass-12345678'


class WriterTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser('w-admin', 'a@localhost', PASSWORD)

    def _request(self, ip='10.99.0.31'):
        request = self.factory.post('/api/v1/auth/login/')
        request.META['REMOTE_ADDR'] = ip
        request.user = self.admin
        return request

    def test_records_actor_and_target_snapshot(self):
        target = User.objects.create_user('w-target', 't@localhost', PASSWORD)
        audit.record(self._request(), 'user_updated', actor=self.admin, target=target,
                     detail={'changed_fields': ['role']})
        row = AuditEvent.objects.get()
        self.assertEqual((row.event, row.actor_username, row.target_username),
                         ('user_updated', 'w-admin', 'w-target'))
        self.assertEqual(row.ip_address, '10.99.0.31')
        self.assertEqual(row.detail, {'changed_fields': ['role']})

    def test_anonymous_actor_leaves_empty_snapshot_but_keeps_target(self):
        request = self._request()
        request.user = AnonymousUser()
        audit.record(request, 'login_failure', target_username='ghost',
                     detail={'reason': 'unknown_user'})
        row = AuditEvent.objects.get()
        self.assertIsNone(row.actor_id)
        self.assertEqual(row.actor_username, '')
        self.assertEqual(row.target_username, 'ghost')

    def test_overlong_username_is_truncated_not_raised(self):
        audit.record(self._request(), 'login_failure',
                     target_username='x' * 400)
        row = AuditEvent.objects.get()
        self.assertEqual(len(row.target_username), 150)

    def test_illegal_ip_leaves_null(self):
        audit.record(self._request(ip='not-an-ip'), 'login_success',
                     actor=self.admin, target=self.admin)
        self.assertIsNone(AuditEvent.objects.get().ip_address)

    def test_failure_does_not_escape_and_is_logged(self):
        # 注入点选真实写路径（照 test_sftp_last_visit_writes.py:463-481 的口径）：
        # 把整个 record 换掉只测得到守卫存在，测不到守卫罩得住真 INSERT。
        with mock.patch.object(AuditEvent, 'save',
                               side_effect=DatabaseError('database is locked')):
            with self.assertLogs('apps.accounts.audit', level='WARNING') as cm:
                audit.record(self._request(), 'login_success',
                             actor=self.admin, target=self.admin)
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.assertTrue(any('审计写入失败' in line for line in cm.output), cm.output)
        self.assertIsNotNone(cm.records[0].exc_info, '留痕必须带 traceback')

    def test_event_list_is_the_single_source(self):
        self.assertEqual(
            audit.AUDIT_EVENTS,
            ('login_success', 'login_failure', 'account_locked', 'account_unlocked',
             'password_changed', 'password_reset', 'user_created', 'user_updated',
             'user_deleted', 'system_paths_changed'),
        )


class WriterInsideBusinessTransactionTests(TestCase):
    """审计 INSERT 失败不能把外层业务事务一起带走（登录/改密都是真事务）。"""

    def setUp(self):
        self.user = User.objects.create_user('w-biz', 'b@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_change_password_still_succeeds_when_audit_insert_fails(self):
        # 改密视图本身在 transaction.atomic() 里，这里是「外层有事务」那一支：
        # 少一个 savepoint，这条 INSERT 失败会把改密一起带走。
        with mock.patch.object(
            audit, '_insert', side_effect=DatabaseError('no such table: mock')
        ):
            resp = self.client.post(
                '/api/v1/auth/change-password/',
                {'old_password': PASSWORD,
                 'new_password': 'x-new-pass-12345',
                 'confirm_password': 'x-new-pass-12345'},
                format='json',
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('x-new-pass-12345'))
        self.assertEqual(AuditEvent.objects.count(), 0)
```

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_audit_writer -v 2`
Expected: `ImportError: cannot import name 'audit' from 'apps.accounts'`（或 `No module named 'apps.accounts.audit'`）

- [ ] **Step 2: 加模型**

`apps/accounts/models.py` 顶部 import 段补 `from django.conf import settings`，文件末尾追加：

```python
class AuditEvent(models.Model):
    """账号安全事件流水：只追加，产品内不提供改/删入口（spec §5.1）。

    username 快照与 FK 分开存：账号删除后事件仍要能读出「当时是谁对谁做了什么」，
    而 `target` 的 SET_NULL 会把那条关联抹平。
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    event = models.CharField(max_length=32)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='audit_actions',
    )
    actor_username = models.CharField(max_length=150, blank=True, default='')
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='audit_targets',
    )
    target_username = models.CharField(max_length=150, blank=True, default='')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'accounts_audit_event'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event', 'created_at']),
            models.Index(fields=['actor_username', 'created_at']),
            models.Index(fields=['target_username', 'created_at']),
        ]

    def __str__(self):
        return f'{self.event} {self.actor_username or "-"} → {self.target_username or "-"}'
```

生成迁移（不要手写索引名，交给 Django 生成哈希名）：

```
.venv/Scripts/python.exe manage.py makemigrations accounts
```
Expected: 打印 `apps\accounts\migrations\0014_auditevent.py`，内容包含 `CreateModel(name='AuditEvent', ...)`、`db_table` 与 3 个 `models.Index`；随后 `.venv/Scripts/python.exe manage.py migrate` 无操作（测试库自动建，本机 dev 库需要它——见 Task 14 的升级说明）。

- [ ] **Step 3: 写 `apps/accounts/audit.py`**

```python
"""账号安全事件写入器。

三条硬规矩（spec §5.4）：
1. 业务动作永远优先 —— 审计写失败只留 warning（带 traceback），不外抛；
   注入点选真实的 `_insert`，与 apps/sftp/views.py:288-293 同一口径。
2. 外层有事务时开 savepoint：否则一条失败的 INSERT 会把改密/重置所在的整笔事务
   标成「必须回滚」。外层是 autocommit 时**不**开 atomic —— SQLite 上那会多出
   BEGIN/COMMIT 两条，而登录是最热的路径（见 test_login_path_statements.py 的形状判据）。
3. username 一律截断到列宽，未知账号的探测输入不许把登录请求带崩。
"""

import ipaddress
import logging

from django.db import transaction

from .models import AuditEvent

logger = logging.getLogger(__name__)

# 唯一事件码清单：前端 frontend/src/utils/audit.ts 的标签表与它双向钉死
# （test/unit/audit.spec.ts 读本文件源码比对）。加事件必须同时改两处。
AUDIT_EVENTS = (
    'login_success',
    'login_failure',
    'account_locked',
    'account_unlocked',
    'password_changed',
    'password_reset',
    'user_created',
    'user_updated',
    'user_deleted',
    'system_paths_changed',
)

# 登录失败的四种可区分原因（spec §5.3）。
LOGIN_FAILURE_REASONS = (
    'unknown_user', 'bad_password', 'account_disabled', 'account_locked',
)

USERNAME_MAX_LENGTH = 150


def _snapshot(value):
    """快照列只收字符串，并截到列宽：未知账号的探测输入不许把登录带崩。"""
    if not isinstance(value, str):
        return ''
    return value[:USERNAME_MAX_LENGTH]


def _client_ip(request):
    raw = (request.META.get('REMOTE_ADDR') or '') if request else ''
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        return None
    return raw


def _insert(*, event, actor, actor_username, target, target_username, ip, detail):
    AuditEvent.objects.create(
        event=event,
        actor=actor,
        actor_username=actor_username,
        target=target,
        target_username=target_username,
        ip_address=ip,
        detail=detail or {},
    )


def record(request, event, *, actor=None, target=None, target_username=None,
           detail=None):
    """写一条审计事件。异常一律就地咽掉，绝不影响调用方。"""
    user = actor if actor is not None else getattr(request, 'user', None)
    if user is not None and not getattr(user, 'is_authenticated', False):
        user = None
    conn = transaction.get_connection()
    try:
        if conn.in_atomic_block:
            with transaction.atomic():
                _insert(
                    event=event, actor=user,
                    actor_username=_snapshot(getattr(user, 'username', '')),
                    target=target,
                    target_username=_snapshot(
                        target_username or getattr(target, 'username', '')
                    ),
                    ip=_client_ip(request), detail=detail,
                )
        else:
            _insert(
                event=event, actor=user,
                actor_username=_snapshot(getattr(user, 'username', '')),
                target=target,
                target_username=_snapshot(
                    target_username or getattr(target, 'username', '')
                ),
                ip=_client_ip(request), detail=detail,
            )
    except Exception:
        logger.warning('审计写入失败：event=%s target=%s', event,
                       target_username or getattr(target, 'username', ''),
                       exc_info=True)
```

- [ ] **Step 4: 跑到绿**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_audit_writer -v 2`
Expected: `Ran 7 tests … OK`

> 判读提示：`test_change_password_still_succeeds_when_audit_insert_fails` 会在日志里打一条故意的 `DatabaseError('no such table: mock')`。CI 注解指向 `raise` 那一行的属于噪音，判读口径见 `docs/reference/testing-gates.md:28-37`。

- [ ] **Step 5: 提交**

```bash
git add apps/accounts/models.py apps/accounts/migrations/0014_auditevent.py apps/accounts/audit.py test/backend/test_audit_writer.py
git commit -m "feat(accounts): 新增 AuditEvent 与 best-effort 审计写入器（外层事务用 savepoint 隔离）"
```

---

## Task 6: 登录写 `last_login` + 登录族审计 + 语句形状判据重测

**Files:**
- Modify: `apps/accounts/views.py:107-195`（LoginView 六个分支）
- Modify: `test/backend/test_login_path_statements.py`（判据重测，含模块头三段）
- Test: `test/backend/test_audit_login_events.py`

这是本批唯一「判据必须跟着实现重写」的地方：`test_login_path_statements.py` 的模块头与三条断言，全部建立在「干净账号那条 UPDATE 是 no-op、必须不发」这个前提上；`last_login` 一落地，前提就不成立了。**别只改期望数组，注释里的论述一起改**，否则留下一段与实现相反的说明。

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_audit_login_events.py`：

```python
"""登录族审计事件与 last_login（spec §5.2/§8）。

每条用例独占 REMOTE_ADDR，并显式抬高 login 限速：默认的 200/min 是本人在
unit/e2e_slot/development 三档给的放宽值，多个用例共享 127.0.0.1 会互相吃 429
（口径见 test_login_throttle.py:16-18：THROTTLE_RATES 是 import 期绑定的类属性，
override_settings 改不动，必须 patch.object）。
"""
import os
import sys
from datetime import timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.test import TestCase  # noqa: E402
from django.utils import timezone  # noqa: E402
from django.urls import reverse  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from rest_framework.throttling import SimpleRateThrottle  # noqa: E402

from apps.accounts.models import AuditEvent, User  # noqa: E402

PASSWORD = 'x-pass-12345678'
FAST = {'login': '10000/min'}


class LoginEventsTests(TestCase):
    def setUp(self):
        patcher = patch.object(SimpleRateThrottle, 'THROTTLE_RATES', FAST)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = APIClient()
        self.user = User.objects.create_user('ev-user', 'e@localhost', PASSWORD)

    def _post(self, ip, username, password=PASSWORD):
        return self.client.post(
            reverse('login'),
            {'username': username, 'password': password},
            REMOTE_ADDR=ip,
        )

    def _rows(self):
        return list(AuditEvent.objects.order_by('-id').values(
            'event', 'actor_username', 'target_username', 'ip_address', 'detail'))

    def test_success_writes_last_login_and_one_row(self):
        before = timezone.now()
        resp = self._post('10.98.0.1', 'ev-user')
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)
        self.assertGreaterEqual(self.user.last_login, before)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['event'], 'login_success')
        self.assertEqual(rows[0]['actor_username'], 'ev-user')
        self.assertEqual(rows[0]['target_username'], 'ev-user')
        self.assertEqual(rows[0]['ip_address'], '10.98.0.1')

    def test_unknown_username_records_reason_and_keeps_no_actor(self):
        resp = self._post('10.98.0.2', 'ev-ghost')
        self.assertEqual(resp.status_code, 401)
        row = self._rows()[0]
        self.assertEqual(row['event'], 'login_failure')
        self.assertEqual(row['detail']['reason'], 'unknown_user')
        self.assertEqual(row['target_username'], 'ev-ghost')
        self.assertEqual(row['actor_username'], '')

    def test_overlong_username_is_truncated_not_500(self):
        resp = self._post('10.98.0.3', 'z' * 400)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(len(self._rows()[0]['target_username']), 150)

    def test_wrong_password_records_remaining_attempts(self):
        resp = self._post('10.98.0.4', 'ev-user', password='wrong-pass-12345')
        self.assertEqual(resp.status_code, 401)
        row = self._rows()[0]
        self.assertEqual(row['event'], 'login_failure')
        self.assertEqual(row['detail']['reason'], 'bad_password')
        self.assertEqual(row['detail']['remaining_attempts'], 4)

    def test_fifth_failure_records_failure_then_lock(self):
        for i in range(4):
            self._post('10.98.0.5', 'ev-user', password='wrong-pass-12345')
        resp = self._post('10.98.0.5', 'ev-user', password='wrong-pass-12345')
        self.assertEqual(resp.status_code, 423)
        rows = self._rows()
        self.assertEqual([r['event'] for r in rows[:2]],
                         ['account_locked', 'login_failure'])
        locked = rows[0]
        self.assertEqual(locked['target_username'], 'ev-user')
        self.assertEqual(locked['detail']['retry_after_minutes'], 15)
        self.assertIn('locked_until', locked['detail'])

    def test_disabled_and_locked_attempts_record_their_own_reason(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self._post('10.98.0.6', 'ev-user').status_code, 403)
        self.assertEqual(self._rows()[0]['detail']['reason'], 'account_disabled')

        User.objects.filter(pk=self.user.pk).update(is_active=True)
        User.objects.filter(pk=self.user.pk).update(
            lockout_until=timezone.now() + timedelta(minutes=5)
        )
        self.assertEqual(self._post('10.98.0.7', 'ev-user').status_code, 423)
        self.assertEqual(self._rows()[0]['detail']['reason'], 'account_locked')

    def test_failure_does_not_touch_last_login(self):
        self._post('10.98.0.8', 'ev-user', password='wrong-pass-12345')
        self.user.refresh_from_db()
        self.assertIsNone(self.user.last_login)
```

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_audit_login_events -v 2`
Expected: 全红（0 条审计行 / `last_login` 为 None）

- [ ] **Step 2: 改 LoginView**

`apps/accounts/views.py` import 段加：

```python
from . import audit
```

四个失败分支各在 `return _error(...)` **之前**插一行（变量名照现状）：

```python
        # :107-113 未知用户名
        audit.record(request, 'login_failure', target_username=username,
                     detail={'reason': 'unknown_user'})

        # :118-123 已停用
        audit.record(request, 'login_failure', target=user,
                     detail={'reason': 'account_disabled'})

        # :125-135 仍在锁定期内（remaining_minutes 此时已算出）
        audit.record(request, 'login_failure', target=user,
                     detail={'reason': 'account_locked',
                             'retry_after_minutes': remaining_minutes})
```

密码错误分支（`:141-161`）整体替换为——第 5 次失败要**先记失败再记锁定**，两条行，顺序即时间线：

```python
        if authenticated_user is None:
            user.login_attempts += 1
            if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.lockout_until = timezone.now() + LOCKOUT_DURATION
                user.login_attempts = 0
                user.save()
                audit.record(request, 'login_failure', target=user,
                             detail={'reason': 'bad_password',
                                     'remaining_attempts': 0})
                audit.record(request, 'account_locked', target=user,
                             detail={'retry_after_minutes': 15,
                                     'locked_until': user.lockout_until.isoformat()})
                return _error(
                    LOGIN_ERROR_CODES['ACCOUNT_LOCKED'],
                    f'连续 {MAX_LOGIN_ATTEMPTS} 次登录失败，账号已被锁定 15 分钟',
                    status_code=status.HTTP_423_LOCKED,
                    retry_after_minutes=15,
                    locked_until=user.lockout_until.isoformat(),
                )
            user.save()
            remaining = MAX_LOGIN_ATTEMPTS - user.login_attempts
            audit.record(request, 'login_failure', target=user,
                         detail={'reason': 'bad_password',
                                 'remaining_attempts': remaining})
            return _error(
                LOGIN_ERROR_CODES['INVALID_CREDENTIALS'],
                '密码错误，请重试',
                status_code=status.HTTP_401_UNAUTHORIZED,
                remaining_attempts=remaining,
            )
```

成功路径：把 `:163-180` 那段「只在确有东西要清时写」的长注释 + 条件写，整体换成无条件写：

```python
        # 成功登录统一落三件事：最后登录时刻、失败计数清零、锁定时间清空。
        # 这里不再做「只在脏时才写」的条件判断 —— 「最后登录」是产品要求显示的
        # 字段（用户管理页 :61 一直在渲染它，而此前全仓没有任何通路写入，
        # 因为 authenticate() 走 ModelBackend，不调 contrib.auth.login）。
        # 代价：干净账号的成功路径比 2026-10-30 那次收敛多一条 UPDATE，
        # 语句形状判据已随之重测（test_login_path_statements.py 模块头）。
        user.last_login = timezone.now()
        user.login_attempts = 0
        user.lockout_until = None
        user.save(update_fields=['last_login', 'login_attempts', 'lockout_until'])

        tokens = get_tokens_for_user(user)
        audit.record(request, 'login_success', actor=user, target=user)
```

- [ ] **Step 3: 重测登录语句形状判据**

`test/backend/test_login_path_statements.py` 四处改动：

① 在 `_verbs` 定义之后新增只看 DML 的取数函数（审计写入器在 TestCase 里会走 savepoint 分支，`SAVEPOINT`/`RELEASE` 是事务簿记，不是语句形状）：

```python
_DML = ('SELECT', 'INSERT', 'UPDATE', 'DELETE')


def _dml(captured):
    """语句形状 = DML 序列。SAVEPOINT/RELEASE/BEGIN/COMMIT 是事务簿记，不计入
    （2026-11-09 起登录带审计写入，外层 atomic 必然产生这一对）。"""
    return [v for v in _verbs(captured) if v in _DML]
```

② 模块头第 25-28 行与 30-44 行两段论述作废，替换为：

```
**2026-11-09 变更**：登录成功改为无条件写 `last_login`/`login_attempts`/`lockout_until`
（spec §8：「最后登录」此前全仓没有任何通路写入，管理页一直显示空值）。于是
「干净账号那条 UPDATE 是 no-op、必须不发」这条判据**不再成立**，成功路径统一是
两条 SELECT + 一条 UPDATE + outstanding token INSERT + 审计 INSERT；「确有东西要清」
那半句条件连同它的全部理由（过期 `lockout_until` 自我修复）一起删掉 —— 无条件写
本来就会把它清掉，那半句不再是区分点。过期锁定那条用例保留，改钉库里的值。
```

③ 三条成功用例：`verbs = _verbs(cap)` → `verbs = _dml(cap)`，期望数组统一改为

```python
        self.assertEqual(verbs, ['SELECT', 'SELECT', 'UPDATE', 'INSERT', 'INSERT'],
                         f'成功路径形状：取行 + backend 复取 + last_login UPDATE + '
                         f'outstanding INSERT + 审计 INSERT，实测 {verbs}')
```

并删掉「干净账号」用例里那句 `count('UPDATE') == 0` 的断言及其理由注释；`test_login_success_clean_account_costs_three_statements` 改名为 `test_login_success_clean_account_shape`。

④ 两条失败用例：同样换成 `_dml`，期望改为

```python
        # 未知用户名：视图 SELECT + 审计 INSERT
        self.assertEqual(verbs, ['SELECT', 'INSERT'], f'实测 {verbs}')
        # 密码错误：视图 SELECT + backend SELECT + 计数 UPDATE + 审计 INSERT
        self.assertEqual(verbs, ['SELECT', 'SELECT', 'UPDATE', 'INSERT'], f'实测 {verbs}')
```

- [ ] **Step 4: 以实跑输出为准敲定数组**

Run:

```
.venv/Scripts/python.exe manage.py test test.backend.test_audit_login_events test.backend.test_login_path_statements -v 2
```
Expected: 全绿。**若某条形状断言红，把失败消息里打印的 `实测 [...]` 原样抄回期望数组**，再跑一次；这几个数按本仓规矩必须是本机现量（`test_login_path_statements.py:11-13`），不许按计划正文猜。同时确认审计那条 INSERT 的 SQL 指向 `accounts_audit_event`（可用 `self.assertIn('accounts_audit_event', _sqls(cap)[-1])` 钉住，位置随数组一起敲定）。

- [ ] **Step 5: 回归登录族**

```
.venv/Scripts/python.exe manage.py test test.backend.test_login_throttle test.backend.test_accounts_write_paths apps.accounts test.backend.test_account_password_change
```
Expected: `OK`。`test_login_throttle.test_configured_rate_survives_a_normal_burst` 守的是 200/min 的档位放宽值，**别为了审计用例去调低它**。

- [ ] **Step 6: 提交**

```bash
git add apps/accounts/views.py test/backend/test_audit_login_events.py test/backend/test_login_path_statements.py
git commit -m "feat(accounts): 登录写 last_login 并记 login_success/failure/locked（语句形状按实跑重钉）"
```

---

## Task 7: 账号 CRUD、重置、解锁、改密、存储路径的审计接线

**Files:**
- Modify: `apps/accounts/views.py`（`ChangePasswordView` `:286-298`、`UserManagementViewSet` `:301-392`）
- Modify: `apps/common/views.py:88-100`
- Test: `test/backend/test_audit_account_events.py`

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_audit_account_events.py`：

```python
"""账号写路径的审计接线：actor/target 快照、detail 约定、绝不记密码（spec §5.2/§5.3）。"""
import os
import shutil
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.test import TestCase  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import AuditEvent, User  # noqa: E402

ADMIN_PW = 'x-admin-pass-123'
TARGET_PW = 'x-target-pass-123'
NEW_PW = 'x-brand-new-pass-123'


class AccountEventsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('ev-admin', 'a@localhost', ADMIN_PW)
        self.target = User.objects.create_user('ev-target', 't@localhost', TARGET_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _row(self, event):
        return AuditEvent.objects.filter(event=event).order_by('-id').first()

    def test_user_created(self):
        resp = self.client.post('/api/v1/auth/users/',
                                {'username': 'ev-new', 'password': NEW_PW,
                                 'role': 'user'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        row = self._row('user_created')
        self.assertEqual((row.actor_username, row.target_username),
                         ('ev-admin', 'ev-new'))
        self.assertEqual(row.detail, {'role': 'user', 'is_active': True})

    def test_user_updated_lists_only_allowlisted_fields(self):
        resp = self.client.put(
            f'/api/v1/auth/users/{self.target.id}/',
            {'display_name': 'Renamed', 'is_active': False}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row = self._row('user_updated')
        self.assertEqual(row.detail['changed_fields'], ['display_name', 'is_active'])
        self.assertEqual(row.detail['values']['is_active'], False)
        blob = str(row.detail)
        for secret in (TARGET_PW, NEW_PW, 'password'):
            self.assertNotIn(secret, blob)

    def test_user_deleted_keeps_username_after_fk_gone(self):
        uid = self.target.id
        resp = self.client.delete(f'/api/v1/auth/users/{uid}/')
        self.assertEqual(resp.status_code, 204)
        row = self._row('user_deleted')
        self.assertEqual(row.target_username, 'ev-target')
        self.assertIsNone(row.target_id)
        self.assertEqual(row.detail['role'], 'user')

    def test_password_reset_and_unlock(self):
        User.objects.filter(pk=self.target.pk).update(
            login_attempts=3, lockout_until=timezone.now() + timedelta(minutes=9)
        )
        resp = self.client.post(f'/api/v1/auth/users/{self.target.id}/reset_password/',
                                {'new_password': NEW_PW}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        row = self._row('password_reset')
        self.assertEqual(row.target_username, 'ev-target')
        self.assertEqual(row.detail, {'lockout_cleared': True})

        resp = self.client.post(f'/api/v1/auth/users/{self.target.id}/unlock/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._row('account_unlocked').target_username, 'ev-target')

    def test_self_password_change_records_actor_only(self):
        client = APIClient()
        client.force_authenticate(user=self.target)
        resp = client.post('/api/v1/auth/change-password/',
                           {'old_password': TARGET_PW, 'new_password': NEW_PW,
                            'confirm_password': NEW_PW}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        row = self._row('password_changed')
        self.assertEqual((row.actor_username, row.target_username),
                         ('ev-target', 'ev-target'))
        self.assertEqual(row.detail, {})
        self.assertNotIn(NEW_PW, str(row.detail))
```

再追加一个存储路径用例（同文件，另一个类；隔离手法照抄 `apps/common/tests_system_paths.py:29-40`，那套 env + 临时目录是本仓已验证的写法）：

```python
class SystemPathsEventTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.admin = User.objects.create_superuser('sp-admin', 's@localhost', ADMIN_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._old_env = os.environ.get('LQDP_SYSTEM_CONFIG_FILE')
        os.environ['LQDP_SYSTEM_CONFIG_FILE'] = str(
            Path(self._dir.name) / 'system_config.json'
        )
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._old_env is None:
            os.environ.pop('LQDP_SYSTEM_CONFIG_FILE', None)
        else:
            os.environ['LQDP_SYSTEM_CONFIG_FILE'] = self._old_env

    def test_paths_change_records_before_after(self):
        import tempfile
        new_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(new_dir, ignore_errors=True))
        resp = self.client.put('/api/v1/system/paths/',
                               {'data_dir': new_dir}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        row = AuditEvent.objects.filter(
            event='system_paths_changed'
        ).order_by('-id').first()
        self.assertIsNotNone(row, '存储路径变更必须留审计')
        self.assertEqual(row.actor_username, 'sp-admin')
        self.assertEqual(row.detail['after']['data_dir'], new_dir)
        self.assertIsNone(row.detail['before']['data_dir'])
        self.assertIn('restart_required', row.detail)
```

（`shutil` 与 `timedelta` 已在该文件头 import 段里，别重复加。）

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_audit_account_events -v 2`
Expected: 全部红（`None` 无行 / 0 条）

- [ ] **Step 2: 接线账号写路径**

`apps/accounts/views.py`：

`ChangePasswordView.post` 在 `return Response(...)` 前加：

```python
            audit.record(request, 'password_changed',
                         actor=request.user, target=request.user)
```

`UserManagementViewSet` 里新增两个 `perform_*`（放在 `update` 覆写之后，紧邻既有 `perform_update`），并给审计字段加白名单常量：

```python
    # 审计 detail 允许出现的字段；其余（含任何口令）一律不进 detail。
    AUDITABLE_FIELDS = ('username', 'email', 'display_name', 'role', 'is_active')

    def perform_create(self, serializer):
        instance = serializer.save()
        audit.record(
            self.request, 'user_created', actor=self.request.user, target=instance,
            detail={'role': instance.role, 'is_active': instance.is_active},
        )

    def perform_update(self, serializer):
        self._guard_lockout(
            self.request, serializer.instance, serializer.validated_data
        )
        instance = serializer.save()
        changed = {
            key: value for key, value in serializer.validated_data.items()
            if key in self.AUDITABLE_FIELDS
        }
        audit.record(
            self.request, 'user_updated', actor=self.request.user, target=instance,
            detail={'changed_fields': sorted(changed), 'values': changed},
        )
```

（`perform_update` 是**替换**现有的 `:326-330`，不是再加一个。）

`perform_destroy`（`:332-335`）替换为——名字要在 `delete()` 之前抓住，FK 之后会被 SET_NULL：

```python
    def perform_destroy(self, instance):
        # 删除没有 serializer，构造等价的「停用」变更集交给同一守卫。
        self._guard_lockout(self.request, instance, {'is_active': False})
        username, role = instance.username, instance.role
        instance.delete()
        audit.record(
            self.request, 'user_deleted', actor=self.request.user,
            target_username=username, detail={'role': role},
        )
```

`reset_password`（`:369-384`）的 `return` 前加：

```python
            audit.record(self.request, 'password_reset', actor=self.request.user,
                         target=user, detail={'lockout_cleared': True})
```

`unlock`（`:386-392`）替换为（顺手把英文 detail 换成中文，与同批其余端点一致）：

```python
    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        user = self.get_object()
        with transaction.atomic():
            user.login_attempts = 0
            user.lockout_until = None
            user.save(update_fields=['login_attempts', 'lockout_until'])
            audit.record(request, 'account_unlocked', actor=request.user, target=user)
        return Response({'detail': '账号已解锁。'})
```

- [ ] **Step 3: 接线存储路径**

`apps/common/views.py` import 段加 `from apps.accounts import audit`；`SystemPathsView.put`（`:88-100`）的 `return Response(...)` 前加：

```python
        audit.record(
            request, 'system_paths_changed', actor=request.user,
            detail={
                'before': {k: before.get(k) for k in ('data_dir', 'temp_dir')},
                'after': {k: after.get(k) for k in ('data_dir', 'temp_dir')},
                'restart_required': before != after,
            },
        )
```

（`load_config` 返回的就是 `save_config` 写的 `{data_dir, temp_dir}` 字典，见 `apps/common/system_config.py:151-163`，所以 `before`/`after` 直接取这两个键即可；文件不存在时为 `{}`，`.get` 给 `None`。）

- [ ] **Step 4: 跑到绿**

```
.venv/Scripts/python.exe manage.py test test.backend.test_audit_account_events test.backend.test_account_password_change apps.accounts test.backend.test_profile_privilege test.backend -v 2
```
Expected: 末段全 `OK`（`test.backend` 整目录兜住意外接线）。

- [ ] **Step 5: 提交**

```bash
git add apps/accounts/views.py apps/common/views.py test/backend/test_audit_account_events.py
git commit -m "feat(accounts): 账号 CRUD/重置/解锁/改密与存储路径变更写入审计（detail 白名单，绝不含口令）"
```

---

## Task 8: 审计查询 API

**Files:**
- Modify: `apps/accounts/serializers.py`（`AuditEventSerializer`）
- Modify: `apps/accounts/views.py`（`AuditEventListView` + 参数校验）
- Modify: `apps/accounts/urls.py`
- Test: `test/backend/test_audit_api.py`

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_audit_api.py`：

```python
"""GET /api/v1/auth/audit-events/：权限、筛选、分页、参数错误信封（spec §6）。"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.test import TestCase  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.audit import record as audit_record
from apps.accounts.models import AuditEvent, User  # noqa: E402

PASSWORD = 'x-pass-12345678'
URL = '/api/v1/auth/audit-events/'


def _request(user, ip='127.0.0.1'):
    from django.test import RequestFactory
    request = RequestFactory().post('/fake/')
    request.user = user
    request.META['REMOTE_ADDR'] = ip
    return request


class AuditApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('api-admin', 'a@localhost', PASSWORD)
        self.plain = User.objects.create_user('api-user', 'u@localhost', PASSWORD)
        self.target = User.objects.create_user('api-target', 't@localhost', PASSWORD)
        audit_record(_request(self.admin), 'password_reset', actor=self.admin,
                     target=self.target)
        audit_record(_request(self.plain), 'login_success', actor=self.plain,
                     target=self.plain)

    def _as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_admin_only(self):
        self.assertEqual(self._as(self.admin).get(URL).status_code, 200)
        self.assertEqual(self._as(self.plain).get(URL).status_code, 403)
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_shape_and_newest_first(self):
        page = self._as(self.admin).get(URL).json()
        self.assertEqual(set(page) - {'next', 'previous'}, {'count', 'results'})
        self.assertEqual(len(page['results']), 2)
        self.assertEqual(page['results'][0]['event'], 'login_success')
        self.assertEqual(
            set(page['results'][0]),
            {'id', 'created_at', 'event', 'actor_username', 'target_username',
             'ip_address', 'detail'},
        )

    def test_filter_by_event_and_username(self):
        events = self._as(self.admin).get(URL, {'event': 'password_reset'}).json()
        self.assertEqual([r['event'] for r in events['results']], ['password_reset'])
        # username 同时命中 actor 与 target（大小写不敏感包含）
        by_actor = self._as(self.admin).get(URL, {'username': 'api-admin'}).json()
        self.assertEqual([r['event'] for r in by_actor['results']], ['password_reset'])
        by_target = self._as(self.admin).get(URL, {'username': 'TARGET'}).json()
        self.assertEqual([r['event'] for r in by_target['results']], ['password_reset'])

    def test_date_range_is_inclusive_by_local_day(self):
        today = timezone.localdate().isoformat()
        hit = self._as(self.admin).get(URL, {'date_from': today, 'date_to': today}).json()
        self.assertEqual(hit['count'], 2)
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        miss = self._as(self.admin).get(URL, {'date_from': yesterday, 'date_to': yesterday})
        self.assertEqual(miss.json()['count'], 0)

    def test_invalid_params_return_400_envelope(self):
        for params in ({'event': 'not_an_event'}, {'date_from': '2026-13-01'},
                       {'date_from': '2026-01-05', 'date_to': '2026-01-01'},
                       {'username': 'x' * 151}, {'page_size': '0'},
                       {'page_size': '101'}):
            resp = self._as(self.admin).get(URL, params)
            self.assertEqual(resp.status_code, 400, params)
            self.assertEqual(resp.json()['code'], 'validation_error', params)

    def test_page_size_clamps_result_count(self):
        page = self._as(self.admin).get(URL, {'page_size': 1}).json()
        self.assertEqual(len(page['results']), 1)
        self.assertEqual(page['count'], 2)

    def test_endpoint_is_read_only(self):
        client = self._as(self.admin)
        for method in (client.post, client.put, client.patch, client.delete):
            self.assertIn(method(URL).status_code, (405, 404))

    def test_audit_rows_are_never_written_by_the_api(self):
        before = AuditEvent.objects.count()
        self._as(self.admin).post(URL, {'event': 'login_success'}, format='json')
        self.assertEqual(AuditEvent.objects.count(), before)
```

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_audit_api -v 2`
Expected: `404`（路由不存在）⇒ 全红

- [ ] **Step 2: 序列化器**

`apps/accounts/serializers.py` 的 import 行把 `AuditEvent` 带进来：

```python
from .models import AuditEvent, User, UserSetting, DEFAULT_HIDDEN_COLUMNS
```

文件末尾追加：

```python
class AuditEventSerializer(serializers.ModelSerializer):
    """审计事件只读载荷（无写入通路：spec §6 末段）。"""

    class Meta:
        model = AuditEvent
        fields = [
            'id', 'created_at', 'event', 'actor_username', 'target_username',
            'ip_address', 'detail',
        ]
        read_only_fields = fields
```

- [ ] **Step 3: 视图与分页**

`apps/accounts/views.py` import 段补：

```python
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination

from . import audit as audit_module
from .audit import AUDIT_EVENTS
```

（`from . import audit` 若 Task 6 已加，这里只补 `AUDIT_EVENTS` 与 `audit_module` 里用得上的名字——**别留下两个指向同一模块的名字**。本任务实际只需要 `AUDIT_EVENTS` 和 `AuditEvent`，把 `audit_module` 那行删掉。）

在 `ChangePasswordView` 之后追加：

```python
AUDIT_USERNAME_MAX_LENGTH = 150
AUDIT_PAGE_SIZE_DEFAULT = 50
AUDIT_PAGE_SIZE_MAX = 100


class AuditEventPagination(PageNumberPagination):
    page_size = AUDIT_PAGE_SIZE_DEFAULT
    page_size_query_param = 'page_size'
    # 上限在视图里显式校验（返回 400 信封），不依赖 DRF 的静默夹取。
    max_page_size = AUDIT_PAGE_SIZE_MAX


def _parse_day_bound(raw, *, end_of_day):
    """把 YYYY-MM-DD 解释成项目时区的一日边界（spec §6/§10）。

    date_to 取「次日起点」并用 ``__lt``，等价于包含整日且不受 UTC/本地混用影响。
    """
    try:
        naive = datetime.strptime(raw, '%Y-%m-%d')
    except ValueError:
        raise ValidationError('日期格式应为 YYYY-MM-DD')
    aware = timezone.make_aware(naive, timezone.get_current_timezone())
    if end_of_day:
        aware = aware + timedelta(days=1)
    return aware


class AuditEventListView(ListAPIView):
    """操作审计查询：只读，管理员专属。"""

    permission_classes = [IsAuthenticated, FeaturePermission]
    required_feature = 'audit_log_view'
    serializer_class = AuditEventSerializer
    pagination_class = AuditEventPagination

    def get_queryset(self):
        params = self.request.query_params
        queryset = AuditEvent.objects.order_by('-created_at')

        event = params.get('event', '')
        if event:
            if event not in AUDIT_EVENTS:
                raise ValidationError('未知的事件类型')
            queryset = queryset.filter(event=event)

        username = params.get('username', '')
        if username:
            if len(username) > AUDIT_USERNAME_MAX_LENGTH:
                raise ValidationError('账号关键词过长')
            queryset = queryset.filter(
                Q(actor_username__icontains=username)
                | Q(target_username__icontains=username)
            )

        date_from = params.get('date_from', '')
        date_to = params.get('date_to', '')
        if date_from:
            queryset = queryset.filter(
                created_at__gte=_parse_day_bound(date_from, end_of_day=False)
            )
        if date_to:
            queryset = queryset.filter(
                created_at__lt=_parse_day_bound(date_to, end_of_day=True)
            )
        if date_from and date_to:
            start = _parse_day_bound(date_from, end_of_day=False)
            end = _parse_day_bound(date_to, end_of_day=True)
            if end <= start:
                raise ValidationError('结束日期不能早于开始日期')

        page_size = params.get('page_size', '')
        if page_size:
            try:
                size = int(page_size)
            except ValueError:
                raise ValidationError('page_size 需为整数')
            if not 1 <= size <= AUDIT_PAGE_SIZE_MAX:
                raise ValidationError(
                    f'page_size 需在 1 到 {AUDIT_PAGE_SIZE_MAX} 之间'
                )

        return queryset
```

补 import（缺哪个加哪个，别重复）：`from datetime import datetime, timedelta`（文件头 `:1` 已 import `timedelta`，把 `datetime` 并进去）、`from django.db.models import Q`、`from django.utils import timezone`（已有）、`AuditEvent`（from `.models`）、`AuditEventSerializer`（from `.serializers`）。

- [ ] **Step 4: 路由**

`apps/accounts/urls.py`：import 段加 `AuditEventListView`，`urlpatterns` 里 `settings/` 那行之后插入：

```python
    path('audit-events/', AuditEventListView.as_view(), name='audit-events'),
```

- [ ] **Step 5: 跑到绿**

```
.venv/Scripts/python.exe manage.py test test.backend.test_audit_api -v 2
```
Expected: `Ran 8 tests … OK`。若 `test_invalid_params_return_400_envelope` 里 `{'date_from': '2026-01-05', 'date_to': '2026-01-01'}` 那条不红，说明倒置检查被前面的过滤吞掉了——把该校验提到 `date_from`/`date_to` 过滤**之前**。

```
.venv/Scripts/python.exe manage.py test test.backend apps.accounts -v 2
```
Expected: `OK`。

- [ ] **Step 6: 提交**

```bash
git add apps/accounts/serializers.py apps/accounts/views.py apps/accounts/urls.py test/backend/test_audit_api.py
git commit -m "feat(accounts): 只读审计查询端点 /auth/audit-events/（按项目时区取整日边界，参数错误走统一信封）"
```

---

## Task 9: 审计纯函数与 T2 单测（含与后端事件码清单的双向绊线）

**Files:**
- Create: `frontend/src/utils/audit.ts`
- Test: `frontend/test/unit/audit.spec.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/test/unit/audit.spec.ts`（vitest 是 node 环境，零 DOM）：

```ts
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import {
  AUDIT_EVENT_LABELS,
  auditEventLabel,
  buildAuditQuery,
  defaultAuditFilters,
  summarizeDetail,
} from '../../src/utils/audit'

/**
 * 后端 audit.py 的 AUDIT_EVENTS 是唯一事件码清单。这里读源码而不是导入物，
 * 因为跨语言没有共享类型；双向钉：后端加码而前端标签表没跟上 ⇒ 红；
 * 前端多写一个后端不会产生的码 ⇒ 也红。
 */
function backendEventCodes(): string[] {
  const src = readFileSync(
    fileURLToPath(new URL('../../../apps/accounts/audit.py', import.meta.url)),
    'utf-8',
  )
  const block = src.match(/AUDIT_EVENTS = \(([\s\S]*?)\)/)
  if (!block) throw new Error('没在 apps/accounts/audit.py 里找到 AUDIT_EVENTS 清单')
  return [...block[1].matchAll(/'([^']+)'/g)].map((m) => m[1])
}

describe('审计事件标签', () => {
  it('与后端事件码清单逐字相等', () => {
    expect(Object.keys(AUDIT_EVENT_LABELS).sort()).toEqual(backendEventCodes().sort())
  })

  it('每个事件码都有中文标签', () => {
    for (const [code, label] of Object.entries(AUDIT_EVENT_LABELS)) {
      expect(label, code).toBeTruthy()
      expect(auditEventLabel(code)).toBe(label)
    }
  })

  it('未知事件码回退原码本身，不抛错（迁移失败的旧行）', () => {
    expect(auditEventLabel('legacy_viewer_login')).toBe('legacy_viewer_login')
  })
})

describe('buildAuditQuery', () => {
  it('空筛选只发分页两键', () => {
    expect(buildAuditQuery({ ...defaultAuditFilters(), page: 3, pageSize: 50 })).toEqual({
      page: 3,
      page_size: 50,
    })
  })

  it('只发非空条件，空白串不算条件', () => {
    const q = buildAuditQuery({
      ...defaultAuditFilters(),
      event: 'password_reset',
      username: '  ',
      dateFrom: '2026-11-01',
      dateTo: '',
    })
    expect(q).toEqual({ event: 'password_reset', date_from: '2026-11-01', page: 1, page_size: 50 })
  })

  it('日期必须是 YYYY-MM-DD 才发出去（半成品输入不打扰后端）', () => {
    expect(buildAuditQuery({ ...defaultAuditFilters(), dateFrom: '2026-11' }).date_from).toBeUndefined()
    expect(buildAuditQuery({ ...defaultAuditFilters(), dateTo: '2026-11-09' }).date_to).toBe('2026-11-09')
  })

  it('页码下限 1，非有限数回落 1', () => {
    expect(buildAuditQuery({ ...defaultAuditFilters(), page: 0 }).page).toBe(1)
    expect(buildAuditQuery({ ...defaultAuditFilters(), page: NaN }).page).toBe(1)
  })
})

describe('summarizeDetail', () => {
  it('空对象/非对象给占位符', () => {
    expect(summarizeDetail({})).toBe('—')
    expect(summarizeDetail(null)).toBe('—')
    expect(summarizeDetail('x')).toBe('—')
  })

  it('已知约定字段渲染成人话', () => {
    expect(
      summarizeDetail({ reason: 'bad_password', remaining_attempts: 3 }),
    ).toContain('bad_password')
    expect(summarizeDetail({ changed_fields: ['is_active', 'role'] })).toContain('is_active')
  })

  it('嵌套与超长值不抛错并截断', () => {
    const long = summarizeDetail({ data_dir: '/x'.repeat(200) })
    expect(long.length).toBeLessThanOrEqual(120)
    expect(summarizeDetail({ nested: { deep: [1, 2, { three: 3 }] } })).toBeTypeOf('string')
  })

  it('绝不把口令类字段写进摘要', () => {
    const text = summarizeDetail({ password: 'secret123', new_password: 'secret123' })
    expect(text).not.toContain('secret123')
  })
})
```

Run: `cd frontend && npx vitest run test/unit/audit.spec.ts`
Expected: 整个文件红（`Cannot find module '../../src/utils/audit'`）

- [ ] **Step 2: 写纯函数**

创建 `frontend/src/utils/audit.ts`：

```ts
/**
 * 审计页的三件纯逻辑：事件标签、筛选转 query、detail 单行摘要。
 *
 * 事件码清单住在后端 apps/accounts/audit.py 的 AUDIT_EVENTS；
 * test/unit/audit.spec.ts 读那份源码做双向绊线，加事件必须两边一起改。
 */

export const AUDIT_EVENT_LABELS: Record<string, string> = {
  login_success: '登录成功',
  login_failure: '登录失败',
  account_locked: '账号锁定',
  account_unlocked: '账号解锁',
  password_changed: '自助修改密码',
  password_reset: '管理员重置密码',
  user_created: '创建账号',
  user_updated: '更新账号',
  user_deleted: '删除账号',
  system_paths_changed: '存储路径变更',
}

export interface AuditFilters {
  event: string
  username: string
  dateFrom: string
  dateTo: string
  page: number
  pageSize: number
}

export const defaultAuditFilters = (): AuditFilters => ({
  event: '',
  username: '',
  dateFrom: '',
  dateTo: '',
  page: 1,
  pageSize: 50,
})

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

/** 口令类字段名（大小写不敏感）：摘要里一律不出现其值。 */
const SECRET_KEY_RE = /pass|token|secret/i

export function auditEventLabel(event: string): string {
  return AUDIT_EVENT_LABELS[event] ?? event
}

export function buildAuditQuery(filters: AuditFilters): Record<string, string | number> {
  const query: Record<string, string | number> = {
    page: Number.isFinite(filters.page) && filters.page >= 1 ? Math.trunc(filters.page) : 1,
    page_size: filters.pageSize,
  }
  if (filters.event) query.event = filters.event
  const username = filters.username.trim()
  if (username) query.username = username
  if (DATE_RE.test(filters.dateFrom)) query.date_from = filters.dateFrom
  if (DATE_RE.test(filters.dateTo)) query.date_to = filters.dateTo
  return query
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '空'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return '…'
  }
}

/** 表格单行摘要：只列标量与数组，嵌套压成 JSON，总长 120 以内。 */
export function summarizeDetail(detail: unknown): string {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return '—'
  const entries = Object.entries(detail as Record<string, unknown>)
  if (!entries.length) return '—'
  const parts = entries.map(([key, value]) => {
    if (SECRET_KEY_RE.test(key)) return `${key}=•••`
    if (Array.isArray(value)) return `${key}=${value.join('/')}`
    return `${key}=${renderValue(value)}`
  })
  const text = parts.join('，')
  return text.length > 120 ? `${text.slice(0, 117)}…` : text
}
```

- [ ] **Step 3: 跑到绿**

Run: `cd frontend && npx vitest run test/unit/audit.spec.ts`
Expected: `Test Files 1 passed`、`Tests 12 passed`

再全量跑一次 vitest（新文件会进 CI 的 vitest 步骤，且 600 行绊线要过）：

```
cd frontend && npx vitest run && npm run build
```
Expected: 全绿；`build` 里 `vue-tsc -b` 无错误。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/utils/audit.ts frontend/test/unit/audit.spec.ts
git commit -m "feat(audit): 审计纯函数（标签/筛选转参/详情摘要）与后端事件码双向绊线"
```

---

## Task 10: 用户管理「编辑」弹窗

**Files:**
- Modify: `frontend/src/pages/admin/UserManagement.vue`（操作列、弹窗、script）
- Test: 追加到 `frontend/e2e/admin/admin.spec.ts`（与既有同页用例同处，不新建文件）

契约：弹窗根节点 class `user-edit-dialog`；用户名只读；角色下拉只有两级；保存按钮可访问名 `保存`。

- [ ] **Step 1: 写失败用例**

在 `frontend/e2e/admin/admin.spec.ts` 的 `describe` 内、`@p2 禁用 / 启用用户` 之后追加：

```ts
  test('@p1 编辑弹窗：改显示名与角色后列表即时收敛，用户名不可改', async ({ page }) => {
    // 这条钉的是「API 有、页面没有」的缺口：PUT /auth/users/<id>/ 早就支持
    // display_name/role，但管理页只有禁用/重置/删除，改名字只能直连接口。
    const username = `e2e_edit_${Date.now()}`
    await loginAs(page, 'admin')
    await sidebarLink(page, '用户管理').click()
    await expect(page).toHaveURL(/\/admin\/users/)

    await addUserField(page, '用户名').fill(username)
    await addUserField(page, '密码').fill('e2ePass123')
    await page.getByRole('button', { name: '添加', exact: true }).click()
    await expect(page.getByText('用户已添加')).toBeVisible({ timeout: 15_000 })

    const row = page
      .locator('.el-table tbody tr')
      .filter({ has: page.getByText(username, { exact: true }) })
    await expect(row).toHaveCount(1)

    await row.getByRole('button', { name: '编辑', exact: true }).click()
    const dialog = page.locator('.user-edit-dialog')
    await expect(dialog).toBeVisible()

    // 用户名只读：input 必须 disabled，否则等于给管理员一条改名通路（登录身份会变）
    await expect(dialog.locator('[data-testid="edit-username"] input')).toBeDisabled()

    await dialog.locator('[data-testid="edit-display-name"] input').fill('改名后的名字')
    // 角色下拉只该有两级（viewer 已删）
    await dialog.locator('[data-testid="edit-role"] input').click()
    const options = page.locator('.el-select-dropdown__item:visible')
    await expect(options).toHaveCount(2)
    await options.filter({ hasText: '普通用户' }).first().click()

    const [resp] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes(`/auth/users/`) && r.request().method() === 'PUT',
        { timeout: 20_000 },
      ),
      dialog.getByRole('button', { name: '保存' }).click(),
    ])
    expect(resp.status(), await resp.text()).toBe(200)
    await expect(page.getByText('账号已更新')).toBeVisible({ timeout: 15_000 })

    // 列表刷新后新显示名出现在同一行
    await expect(
      page.locator('.el-table tbody tr').filter({ hasText: '改名后的名字' }),
    ).toHaveCount(1)

    await row.getByRole('button', { name: '删除', exact: true }).click()
    const confirm = page.locator('.el-message-box')
    await confirm.locator('.el-message-box__btns .el-button--primary').click()
    await expect(page.getByText('已删除')).toBeVisible({ timeout: 15_000 })
  })
```

并把 `afterAll` 的清理正则扩到该前缀：

```ts
        if (/^e2e_(toggle|reset|edit)_/.test(u.username ?? '')) {
```

- [ ] **Step 2: 跑到红**

Run: `cd frontend && npx playwright test e2e/admin/admin.spec.ts -g "编辑弹窗" --reporter=list`
Expected: 红在 `getByRole('button', { name: '编辑' })`（按钮不存在，超时）。

- [ ] **Step 3: 加按钮与弹窗**

`UserManagement.vue` 操作列（`:64-95`）里，在「禁用/启用」按钮之前插入：

```html
            <el-button size="small" type="primary" plain @click="openEdit(row)">
              编辑
            </el-button>
```

在 `</el-card>`（表格卡片结尾）之后、`<el-divider />` 之前插入弹窗：

```html
    <el-dialog
      v-model="editVisible"
      title="编辑账号"
      width="460px"
      :close-on-click-modal="false"
      append-to-body
      class="user-edit-dialog"
    >
      <el-form :model="editForm" label-width="72px" @submit.prevent="saveEdit">
        <el-form-item label="用户名" data-testid="edit-username">
          <el-input :model-value="editing?.username" disabled />
        </el-form-item>
        <el-form-item label="显示名" data-testid="edit-display-name">
          <el-input v-model="editForm.display_name" maxlength="150" />
        </el-form-item>
        <el-form-item label="邮箱" data-testid="edit-email">
          <el-input v-model="editForm.email" placeholder="可留空" />
        </el-form-item>
        <el-form-item label="角色" data-testid="edit-role">
          <el-select v-model="editForm.role" class="edit-role-select">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="administrator" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
```

script 段（`import { ref, computed, onMounted } from 'vue'` 已就位）追加状态与两个函数，并给 `interface User` 补 `email: string`：

```ts
const editVisible = ref(false)
const editing = ref<User | null>(null)
const saving = ref(false)
const editForm = ref({ display_name: '', email: '', role: 'user' })

function openEdit(user: User) {
  editing.value = user
  editForm.value = {
    display_name: user.display_name ?? '',
    email: user.email ?? '',
    role: user.role,
  }
  editVisible.value = true
}

async function saveEdit() {
  const user = editing.value
  if (!user) return
  saving.value = true
  try {
    // PUT 是整份替换语义的例外：后端 update() 强制 partial=True
    // （apps/accounts/views.py:323），所以只发这三字段不会把 is_active 冲洗掉。
    await api.put(`/auth/users/${user.id}/`, {
      display_name: editForm.value.display_name.trim(),
      email: editForm.value.email.trim(),
      role: editForm.value.role,
    })
    ElMessage.success('账号已更新')
    editVisible.value = false
    loadUsers()
  } catch {
    // 守卫失败（例如拆掉最后一个管理员）由拦截器弹文案，列表保持原样
  } finally {
    saving.value = false
  }
}
```

样式补一段（双主题都靠 token，无硬编码色）：

```css
.edit-role-select {
  width: 100%;
}
```

- [ ] **Step 4: 跑到绿 + 类型/门禁**

```
cd frontend && npx playwright test e2e/admin/admin.spec.ts --reporter=list
cd frontend && npm run build && npx vitest run && npm run lint:e2e
```
Expected: admin 档用例全绿；build/vitest/lint 无错误。若 `elementPlusUsage.spec.ts` 因新用 `<el-dialog>` 之类报数不对，说明用到了清单外的标签 —— 本任务用的 `dialog/form/form-item/input/select/option/button` 均已在 49 件清单内，应当不动。

```
cd frontend && npm run test:e2e:affected
```
Expected: 末行 `RESULT: PASS`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/admin/UserManagement.vue frontend/e2e/admin/admin.spec.ts
git commit -m "feat(admin): 用户管理补编辑弹窗（用户名只读、角色两级、走 partial PUT 不冲洗启用态）"
```

---

## Task 11: 审计 client、`/admin/audit` 页与路由/侧栏接线

**Files:**
- Create: `frontend/src/api/audit.ts`
- Create: `frontend/src/pages/admin/AuditLogPage.vue`
- Modify: `frontend/src/router/index.ts`（`:82` 之后插路由，须排在 `:103-108` 的 404 兜底之前）
- Modify: `frontend/src/components/layout/Sidebar.vue`（`:73-83` 图标 import 补 `Search`；`:104` 之后插菜单项）
- Test: `frontend/e2e/admin/audit.spec.ts`

- [ ] **Step 1: 写失败用例**

创建 `frontend/e2e/admin/audit.spec.ts`：

```ts
import { test, expect } from '@playwright/test'
import { loginAs } from '../helpers/auth'
import { sidebarLink } from '../helpers/nav'

/**
 * 操作审计页（/admin/audit）。
 *
 * 与 admin.spec.ts 同一约定：清空注入的 storageState，用 loginAs 实时登录，
 * 这样 Pinia 里的 user/isAdmin 才可信（requiresAdmin 守卫读的是它）。
 */
test.describe('操作审计', { tag: ['@admin'] }, () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test.afterAll(async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    try {
      const login = await ctx.request.post('/api/v1/auth/login/', {
        data: { username: 'admin', password: 'admin123' },
      })
      if (!login.ok()) return
      const headers = { Authorization: `Bearer ${(await login.json()).token}` }
      const list = await ctx.request.get('/api/v1/auth/users/', { headers, failOnStatusCode: false })
      if (!list.ok()) return
      const body = await list.json()
      const users: Array<{ id: number; username: string }> = body.results ?? body
      for (const u of users) {
        if (/^e2e_audit_/.test(u.username ?? '')) {
          await ctx.request.delete(`/api/v1/auth/users/${u.id}/`, { headers, failOnStatusCode: false })
        }
      }
    } catch {
      // 残留由下一轮兜底
    } finally {
      await ctx.close()
    }
  })

  test('@p1 重置密码后审计页出现该记录，按目标账号筛选命中', async ({ page, browser }) => {
    const username = `e2e_audit_${Date.now()}`
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    let userId: number | null = null
    try {
      const login = await ctx.request.post('/api/v1/auth/login/', {
        data: { username: 'admin', password: 'admin123' },
      })
      const headers = { Authorization: `Bearer ${(await login.json()).token}` }
      const created = await ctx.request.post('/api/v1/auth/users/', {
        headers,
        data: { username, password: 'e2e-initial-password', role: 'user' },
      })
      expect(created.ok(), `临时账号建不出来：${await created.text()}`).toBe(true)
      userId = (await created.json()).id

      await loginAs(page, 'admin')
      await sidebarLink(page, '用户管理').click()
      const row = page
        .locator('.el-table tbody tr')
        .filter({ has: page.getByText(username, { exact: true }) })
      await row.getByRole('button', { name: '重置密码', exact: true }).click()
      const box = page.locator('.el-message-box')
      await box.locator('.el-message-box__input input').fill('e2e-audited-password')
      const [resetResp] = await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes(`/auth/users/${userId}/reset_password/`),
          { timeout: 20_000 },
        ),
        box.getByRole('button', { name: '重置' }).click(),
      ])
      expect(resetResp.status(), await resetResp.text()).toBe(200)

      await sidebarLink(page, '操作审计').click()
      await expect(page).toHaveURL(/\/admin\/audit/)
      const table = page.locator('.audit-table')
      await expect(table).toBeVisible()

      // 不按账号筛就得先看见这条（倒序第一屏），证明写入器与查询端点真接上了
      await expect(
        table.locator('tbody tr').filter({ hasText: '管理员重置密码' }).first(),
      ).toBeVisible({ timeout: 15_000 })

      // 按目标账号筛：只剩这个账号的事件
      const keyword = page.locator('[data-testid="audit-username"] input')
      await keyword.fill(username)
      const [listResp] = await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes('/auth/audit-events/') && r.request().method() === 'GET',
          { timeout: 20_000 },
        ),
        page.getByRole('button', { name: '查询', exact: true }).click(),
      ])
      expect(listResp.status(), await listResp.text()).toBe(200)
      const rows = table.locator('tbody tr')
      await expect(rows.first()).toContainText(username)
      const count = await rows.count()
      for (let i = 0; i < count; i += 1) {
        await expect(rows.nth(i)).toContainText(username)
      }
    } finally {
      if (userId != null) {
        const login = await ctx.request.post('/api/v1/auth/login/', {
          data: { username: 'admin', password: 'admin123' },
          failOnStatusCode: false,
        })
        if (login.ok()) {
          const headers = { Authorization: `Bearer ${(await login.json()).token}` }
          await ctx.request.delete(`/api/v1/auth/users/${userId}/`, { headers, failOnStatusCode: false })
        }
      }
      await ctx.close()
    }
  })

  test('@p1 普通用户：侧栏无审计入口，直达被守卫送回仪表板', async ({ page }) => {
    // 现状已由代码确认（不是 admin.spec.ts 里那段旧说明）：meta.requiresAdmin +
    // 守卫 next('/dashboard') 生效，侧栏用 v-if 过滤 ⇒ 管理员项根本不在 DOM 里。
    // 断言必须等守卫跑完（守卫里有一次 fetchProfile 往返），所以直接断最终 URL。
    await loginAs(page, 'user')
    await expect(sidebarLink(page, '操作审计')).toBeHidden()
    await page.goto('/admin/audit')
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })

    const denied = await page.request.get('/api/v1/auth/audit-events/')
    expect(denied.status()).toBe(401) // 未带凭据；权限闸门另有 user→403 的 T1 覆盖
  })

  test('@p2 筛选与重置：条件清空后回到全量，空结果显示空态不报错', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '操作审计').click()
    await expect(page).toHaveURL(/\/admin\/audit/)

    const keyword = page.locator('[data-testid="audit-username"] input')
    await keyword.fill('zzz-不存在-zzz')
    await page.getByRole('button', { name: '查询', exact: true }).click()
    await expect(page.getByText('暂无符合条件的审计记录')).toBeVisible({ timeout: 15_000 })

    await page.getByRole('button', { name: '重置', exact: true }).click()
    await expect(keyword).toHaveValue('')
    await expect(page.locator('.audit-table tbody tr').first()).toBeVisible({ timeout: 15_000 })
  })
})
```

Run: `cd frontend && npx playwright test e2e/admin/audit.spec.ts --reporter=list`
Expected: 红在 `sidebarLink(page, '操作审计')` / 页面不存在（`/admin/audit` 404 兜底页）。

- [ ] **Step 2: client**

创建 `frontend/src/api/audit.ts`：

```ts
import api from './index'

export interface AuditEventRow {
  id: number
  created_at: string
  event: string
  actor_username: string
  target_username: string
  ip_address: string | null
  detail: Record<string, unknown>
}

export interface AuditPage {
  count: number
  next: string | null
  previous: string | null
  results: AuditEventRow[]
}

/** 只读：后端不提供写通路。 */
export const auditApi = {
  listEvents(params: Record<string, string | number> = {}) {
    return api.get<AuditPage>('/auth/audit-events/', { params })
  },
}
```

- [ ] **Step 3: 页面**

创建 `frontend/src/pages/admin/AuditLogPage.vue`（整文件必须 ≤600 行）：

```vue
<template>
  <div class="audit-log">
    <el-card class="filter-card">
      <el-form :model="filters" inline @submit.prevent="applyFilters">
        <el-form-item label="事件">
          <el-select v-model="filters.event" clearable placeholder="全部事件" data-testid="audit-event">
            <el-option
              v-for="(label, code) in AUDIT_EVENT_LABELS"
              :key="code"
              :label="label"
              :value="code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="账号">
          <el-input
            v-model="filters.username"
            placeholder="操作者或目标账号"
            clearable
            maxlength="150"
            data-testid="audit-username"
          />
        </el-form-item>
        <el-form-item label="起">
          <el-date-picker
            v-model="filters.dateFrom"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="开始日期"
            data-testid="audit-date-from"
          />
        </el-form-item>
        <el-form-item label="止">
          <el-date-picker
            v-model="filters.dateTo"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="结束日期"
            data-testid="audit-date-to"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="table-card">
      <el-table
        v-loading="loading"
        :data="rows"
        class="audit-table"
        row-key="id"
        stripe
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <pre class="detail-json">{{ JSON.stringify(row.detail, null, 2) }}</pre>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="事件" width="150">
          <template #default="{ row }">{{ auditEventLabel(row.event) }}</template>
        </el-table-column>
        <el-table-column label="操作者" min-width="140">
          <template #default="{ row }">{{ row.actor_username || '—' }}</template>
        </el-table-column>
        <el-table-column label="目标账号" min-width="140">
          <template #default="{ row }">{{ row.target_username || '—' }}</template>
        </el-table-column>
        <el-table-column label="IP" width="140">
          <template #default="{ row }">{{ row.ip_address || '—' }}</template>
        </el-table-column>
        <el-table-column label="详情" min-width="220">
          <template #default="{ row }">{{ summarizeDetail(row.detail) }}</template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !rows.length" description="暂无符合条件的审计记录" />

      <div class="audit-pagination">
        <el-pagination
          :current-page="filters.page"
          :page-size="filters.pageSize"
          :page-sizes="[20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { auditApi, type AuditEventRow } from '../../api/audit'
import {
  AUDIT_EVENT_LABELS,
  auditEventLabel,
  buildAuditQuery,
  defaultAuditFilters,
  summarizeDetail,
  type AuditFilters,
} from '../../utils/audit'

const rows = ref<AuditEventRow[]>([])
const total = ref(0)
const loading = ref(false)
const filters = reactive<AuditFilters>(defaultAuditFilters())

function formatTime(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function load() {
  loading.value = true
  try {
    const { data } = await auditApi.listEvents(buildAuditQuery(filters))
    rows.value = data.results ?? []
    total.value = data.count ?? rows.value.length
  } catch {
    // 失败 toast 由 axios 拦截器统一弹出；这里保留筛选条件，便于原地重试
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  filters.page = 1
  load()
}

function resetFilters() {
  Object.assign(filters, defaultAuditFilters())
  load()
}

function onPageChange(page: number) {
  filters.page = page
  load()
}

function onSizeChange(size: number) {
  filters.pageSize = size
  filters.page = 1
  load()
}

onMounted(load)
</script>

<style scoped>
.audit-log {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-card :deep(.el-form--inline .el-form-item) {
  margin-bottom: 8px;
}

.audit-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.detail-json {
  margin: 0;
  padding: 12px 16px;
  background: var(--bg-3);
  color: var(--text);
  border-radius: 8px;
  font-size: var(--p-fs-dense);
  white-space: pre-wrap;
  word-break: break-all;
}

:deep(.el-card) {
  background-color: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-2);
  --el-table-tr-bg-color: var(--bg-2);
  --el-table-header-bg-color: var(--bg-3);
  --el-table-border-color: var(--border-2);
  --el-table-text-color: var(--text);
  --el-table-row-hover-bg-color: var(--bg-3);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg);
  box-shadow: 0 0 0 1px var(--border-2) inset;
}
</style>
```

`v-loading` 是清单里的 `ElLoading` 指令通路（`directives` 已在 `main.ts` 注册），不新增模板标签；用到的模板标签 `card/form/form-item/select/option/input/date-picker/button/table/table-column/empty/pagination` 全部在 49 件清单内。

- [ ] **Step 4: 路由与侧栏**

`frontend/src/router/index.ts`，插在 `admin/users` 那条之后（404 兜底之前）：

```ts
      {
        path: 'admin/audit',
        name: 'AuditLog',
        component: () => import('../pages/admin/AuditLogPage.vue'),
        meta: {
          title: '操作审计',
          requiresAdmin: true,
          icon: Search,
          desc: '登录、锁定、改密与账号变更的留痕',
          parent: { label: '系统管理' },
        },
      },
```

`frontend/src/components/layout/Sidebar.vue`：图标 import 块（`:73-83`）加 `Search,`；`menuItems` 里「用户管理」那条之后加：

```ts
  { path: '/admin/audit', label: '操作审计', icon: Search, requiresAdmin: true },
```

- [ ] **Step 5: 跑到绿 + 全量绊线**

```
cd frontend && npx playwright test e2e/admin/audit.spec.ts --reporter=list
cd frontend && npx vitest run && npm run build && npm run lint:e2e
```
Expected: 3 条用例全绿；vitest 全绿（含 `elementPlusUsage`、`lineLimit`）；build/lint 无错误。

```
wc -l frontend/src/pages/admin/AuditLogPage.vue frontend/src/utils/audit.ts
```
Expected: 都 < 600。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/audit.ts frontend/src/pages/admin/AuditLogPage.vue frontend/src/router/index.ts frontend/src/components/layout/Sidebar.vue frontend/e2e/admin/audit.spec.ts
git commit -m "feat(audit): 独立管理页 /admin/audit（筛选+倒序分页+详情展开），requiresAdmin 守卫与侧栏入口接线"
```

---

## Task 12: 修掉「直达管理页不被拦截」这条抢跑断言

**Files:**
- Modify: `frontend/e2e/admin/admin.spec.ts:26-31`（doc 块）、`:65-85`（用例）

2026-11-09 实测确认：`meta.requiresAdmin`（`router/index.ts:89`）+ 守卫 `next('/dashboard')`（`:184`）确实生效，普通用户 `page.goto('/admin/users')` 最终落在 `/dashboard`；但那条用例只断言了守卫**跑完之前**的 URL，因为守卫里有一次 `fetchProfile` 网络往返，`toHaveURL` 的第一次轮询就抢到了 `/admin/users` 而通过。它现在钉的是假事实，且随时可能因为一次快响应变成 flake。

- [ ] **Step 1: 先证明它是抢跑（可复现的取证步骤）**

临时在该用例 `await expect(page).toHaveURL(/\/admin\/users/)` 之后插入：

```ts
    await page.waitForTimeout(2500)
    // eslint-disable-next-line no-console
    console.log('### 守卫跑完后的落点:', page.url())
```

Run: `cd frontend && npx playwright test e2e/admin/admin.spec.ts -g "不被路由拦截" --reporter=list`
Expected: 用例仍 `ok`，而日志打出 `### 守卫跑完后的落点: http://localhost:<port>/dashboard` —— 这就是假绿的证据。**记下这行输出**，Step 3 删掉临时插段。

- [ ] **Step 2: 改用例与文档块**

把 `:65-85` 整条替换为（标题也跟着改，别留「不被拦截」这个错名）：

```ts
  test('@p1 普通用户：侧边栏无“用户管理”入口，直达被守卫送回仪表板', async ({ page }) => {
    await loginAs(page, 'user')

    // Sidebar.vue 走 v-if 过滤（.menu-item.hidden 的 CSS 方案已废弃），
    // 管理员项根本不在 DOM 里 ⇒ toBeHidden 对「不存在」成立。
    await expect(sidebarLink(page, '用户管理')).toBeHidden()

    await page.goto('/admin/users')
    // 守卫（router beforeEach）里有一次 fetchProfile 往返，所以断最终落点，
    // 不断 goto 之后那一瞬的 URL —— 抢跑式断言 2026-11-09 实测会假绿。
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
    await expect(page.locator('.main-layout')).toBeVisible()
  })
```

doc 块 `:26-31` 里这段（原文）：

```
 *   路由实情（src/router/index.ts beforeEach）：
 *   守卫只判断 `to.meta.requiresAuth && !auth.isLoggedIn`，而 isLoggedIn = !!token。
 *   —— 没有任何基于角色/管理员的拦截。
 *   因此普通用户（持有 token）直接访问 /admin/users 不会被重定向，路由会渲染；
 *   仅靠侧边栏菜单项的 `.hidden`(display:none) CSS 隐藏入口（Sidebar.vue 第 23/79/179 行）。
 *   本测试按此“实情”断言：菜单入口隐藏 + 直达不被拦截（并 log 说明）。
```

替换为：

```
 *   路由实情（src/router/index.ts:184 已实测确认）：
 *   beforeEach 依次判 requiresAuth、/login 回访、requiresAdmin；普通用户直达
 *   /admin/users 会被 next('/dashboard') 送回仪表板（纵深防御，后端 403 是第一道）。
 *   侧栏按 v-if 过滤管理员项 ⇒ 不在 DOM 里，不是 .hidden(display:none)。
 *   断言一律取守卫跑完后的最终 URL：守卫含一次 fetchProfile 往返，
 *   抢在它之前断 goto 的目标地址会假绿（2026-11-09 踩实）。
```

- [ ] **Step 3: 跑到绿**

```
cd frontend && npx playwright test e2e/admin/admin.spec.ts --reporter=list
cd frontend && npm run lint:e2e
```
Expected: 全绿（含 Task 10 的编辑弹窗用例）。临时插段已删。

- [ ] **Step 4: 提交**

```bash
git add frontend/e2e/admin/admin.spec.ts
git commit -m "test(e2e): 管理页直达用例改断守卫最终落点（旧断言抢在 fetchProfile 前匹配，钉的是假事实）"
```

---

## Task 13: 用户指南同步（本机生效，不入库）

**Files:**
- Modify（`docs/user-guide/` 整目录被 `.gitignore:170` 忽略，改完**只能本机生效**）：`README.md`、`01-quickstart.md`、`08-admin.md`
- 生成物：`docs/user-guide/dist/*.html`

- [ ] **Step 1: 改源页**

`docs/user-guide/README.md:14` 删掉读者入口表里的浏览者行；`:60` 与 `README.md:34` 同措辞（管理员 / 普通用户）。

`docs/user-guide/01-quickstart.md:19`：删 `| 浏览者 | viewer | viewer123 |` 行。

`docs/user-guide/08-admin.md`：
- `:22` 字段表：`| 角色 | administrator / user / viewer |` → `| 角色 | administrator / user |`。
- `:32` 删掉整条 viewer 说明。
- `:54` 的权限矩阵整表重写为两级，并且**与代码逐条对齐**（旧表把「删除数据文件」写成 user ✅(自己的)，而代码是 `data_delete: ['administrator']`，属于文档漂移）：

```markdown
| 功能 | administrator | user |
|------|:-------------:|:----:|
| 查看仪表板 / 数据分析 / 报表 | ✅ | ✅ |
| 上传数据文件 | ✅ | ✅ |
| 删除数据文件 | ✅ | ❌ |
| 数据一致性：导入孤立数据、产品名补缺 | ✅ | ✅ |
| 数据一致性：删除孤立/重复数据 | ✅ | ❌ |
| 导出报表 | ✅ | ✅ |
| 使用 SFTP 浏览器 | ✅ | ✅ |
| 系统设置（个人） | ✅ | ✅ |
| 系统设置（存储路径、运维指标） | ✅ | ❌ |
| 用户管理 | ✅ | ❌ |
| 操作审计 | ✅ | ❌ |
```

- 新增两节：`### 编辑账号`（编辑弹窗四字段、用户名只读、角色只有两级、守卫会拒绝拆掉最后一个启用的管理员）与 `### 操作审计`（`/admin/audit`、事件清单、筛选与分页、只读、口令永不入表、账号删除后 username 仍在）。

- [ ] **Step 2: 重新生成 dist，并守住「不混入无关 churn」**

```
cd docs/user-guide && npm run build
```
Expected: 无报错；`dist/01-quickstart.html`、`dist/08-admin.html`、`dist/index.html` 里不再有 viewer（`grep -c viewer dist/08-admin.html` 为 0）。

⚠️ 已实测：`dist/reference/` 落后 3 份（缺 `c3-exit-pool-orphan-forensics-2026-10-29`、`perf-baseline-2026-10-24-dual-profile`、`renderer-memory-baseline-2026-10-22`），`server-deployment.html` 等也会整体重写。spec §9.4 与 §15 明确要求：**生成物差异只接受与本次源页对应的部分**。因此跑完后先 `cd docs/user-guide && git status --porcelain .`（预期空 —— 整目录不入库），再把无关重写当作**已知状态**记录进 todo 台账，不要试图手工回滚个别 html，也不要在提交里带它们。

- [ ] **Step 3: 提交（只提入库文档）**

本轮 `docs/user-guide/**` 无入库文件可提；只把 Step 1 的差异写进台账（Task 14），并在 `docs/reference/server-deployment.md`（Task 4 已改）之外不再动入库文档。

```bash
git status --porcelain docs
```
Expected: 只有 `M docs/tasks/todo.md`（另一会话的未提交改动，**本批不提交**）。若冒出别的文件，说明误改了历史评审稿，回退它。

---

## Task 14: 收口验证、教训与台账

- [ ] **Step 1: 后端全量**

```
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe manage.py test
```
Expected: `Ran NNNN tests … OK (skipped=8)`（基线见 `docs/reference/testing-gates.md:61`：上一轮 1652 OK；本批新增 6 个测试文件，条数只增不减）。任何失败都回到对应任务，不带病收口。

- [ ] **Step 2: 前端三件套 + 全量池**

```
cd frontend && npx vitest run && npm run build && npm run lint:e2e
node scripts/e2e_pool.mjs --slots=4
```
Expected: vitest/build/lint 全绿；池末两行给出 `用例 N · … · unexpected 0` 与 `[pool] 结论 MEASURED`，退出码 0。
判读：`verdict=VOID (infra)`、或某 slot 没出 JSON ⇒ **按基建轮复跑**，不算产品红也不算绿；`unexpected 1` 且指向本轮改动文件 ⇒ 真红。

- [ ] **Step 3: 手工验收一遍（spec §13）**

按 spec §13 的七条逐条走一遍并记录实际观察（在 e2e 档的库上跑，别碰 `~/LQ-DataPrase/db.sqlite3`）：

```
cd frontend && E2E_PORT=8123 E2E_FRONTEND_PORT=3123 npx playwright test e2e/admin/audit.spec.ts e2e/admin/admin.spec.ts --reporter=list --project=P1
```
另外用浏览器打开 `http://localhost:3123/admin/audit`，切一次 night/light 主题，确认表格、展开的 JSON、分页控件与空态在两套主题下都读得清（对照 `e2e/theme/night-visibility.spec.ts` 的口径）。

- [ ] **Step 4: 迁移升级路径实测（历史 viewer 的库）**

```
.venv/Scripts/python.exe -c "import sqlite3;..."   # 先在有历史 viewer 的**副本**上验，不在真库上跑
```
做法：把 `test/e2e-data/db.sqlite3` 复制到一个临时目录，`UPDATE accounts_user SET role='viewer' WHERE username='user'`，再对副本跑 `manage.py migrate`，确认 0012 把它并成 `user`、0013 落 AlterField、`seed_users` 之后库里没有 viewer 残留。**只在副本上跑**（lessons 里 `prune_jobs` 那类事故说明：动库之前先确认自己在动哪一份）。

- [ ] **Step 5: 教训追加**

在 `docs/tasks/lessons.md` 末尾追加一条 `## 2026-11-XX <本批真实踩到的事>`，格式沿用「现象/规则」成对。至少覆盖这两条已经在计划期确认过的：
1. 「点了报错」类报障要分层取证（接口态 → 会话态 → 测试基建态），本次被报的禁用动作本身是绿的。
2. 断言抢在异步守卫之前匹配 = 假绿（Task 12 的实测证据）。
只写实际发生的，别把计划正文抄成教训。

- [ ] **Step 6: 台账**

`docs/tasks/todo.md` 末尾追加 `# 任务：账号角色收敛与操作审计（2026-11-09）`，小节结构照该文件最后一条（`## 边界` → 各批 `- [x]` 带文件路径与门禁结论 → `## 收口` → `## 明确不做`）。**本轮不提交它**（工作树里有另一会话 396 行未提交新增，`git add` 会把别人的正文带进本批 commit）；在收口汇报里说明「台账已本机落地，待另一批提交后一并入库」。

- [ ] **Step 7: 完成前验证（REQUIRED SUB-SKILL: superpowers:verification-before-completion）**

汇报前把每条命令的原始输出行贴进结论（`Ran … OK`、`RESULT:`、`[pool] 结论`、`unexpected 0`），不许用「应该没问题」代替。**未获明确指示不要 push**：`origin` 是公开仓库，一次 push 即全球发布。

---

## 验收对照（spec §13 → 任务）

| 验收标准 | 落在 |
|---|---|
| UI 与 API 都无法选/设 viewer | Task 3（API choices + 后端引用）、Task 4（下拉与标签）、Task 9 绊线 |
| 历史 viewer 不再是半截角色 | Task 1（0012 归并）+ Task 14 Step 4（副本实测） |
| 登录后「最后登录」有变化 | Task 6 |
| 每类安全事件一条正确记录、删除后 username 仍在 | Task 6、Task 7（`test_user_deleted_keeps_username_after_fk_gone`） |
| 管理员可查、普通用户 API 与页面都进不去 | Task 8（403/401）、Task 11（侧栏 + 守卫落点） |
| 能改显示名/邮箱/角色，守卫不变 | Task 10 + Task 3 的 `_guard_lockout` 回归 |
| 后端全量、vitest、build、lint:e2e、一轮无 VOID 的全量池 | Task 14 Step 1–2 |

## 计划自审（写完后自查，已按结论就地修正）

- **spec 覆盖**：§3→Task 2/3/4，§4→Task 1/3，§5→Task 5/6/7，§6→Task 8，§7→Task 9/10/11，§8→Task 6，§9→Task 3/4/13，§10→Task 5/7/8/14，§11→各任务的 Step 1，§12→任务顺序，§13→上表，§14→无任务（明确不做），§15→Task 1/14 的风险说明。
- **与 spec 的两处字面偏离**：① 迁移拆 0012/0013（保每个 commit 可绿，Task 1 首段给了理由）；② `admin.spec.ts` 那条直达用例改成断最终落点（spec §9.3 没要求，但它与 §7.1 的守卫前提直接矛盾，Task 12 给了实测证据）。
- **占位符扫描**：无 TBD/TODO；每个改动步骤都给了代码或精确 old→new 串。Task 6 Step 4 与 Task 8 Step 5 处留的是「以实跑输出抄数组」的判据（本仓对语句形状数的硬规矩：`test_login_path_statements.py:11-13` 要求本机现量），不是省略。
- **类型一致性**：`role_can(role, feature)` 在 Task 2 定义、Task 8 的 `required_feature='audit_log_view'` 用到同一表键；`audit.record(request, event, *, actor, target, target_username, detail)` 签名在 Task 5 定义、Task 6/7 调用参数名逐字一致；前端 `AuditFilters`/`defaultAuditFilters()`/`buildAuditQuery()` 在 Task 9 定义、Task 11 页面按同名导入；`AUDIT_EVENTS`（后端）与 `AUDIT_EVENT_LABELS`（前端）由 Task 9 的绊线锁死。

