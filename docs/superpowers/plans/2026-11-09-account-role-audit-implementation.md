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

行为中性可证：改动前 `FEATURE_PERMISSIONS` 有 **14** 个键，收敛后 5 个 ⇒ **删 10、加 1（`data_repair_mutate`）、留 4**（控制器 2026-11-09 实测；本句原先写「被删的 4 个键」，那个数是错的）。这 10 个键全仓**没有消费者**：`required_feature` 只出现在 `apps/accounts/views.py:304`（`user_management`）与 `apps/common/views.py:37` 与 `:77`（`system_config`），被删键名在任何 `*.py/*.ts/*.vue/*.js/*.mjs` 里都不出现（只剩注释与文档 prose）。`data_delete`/`data_repair_mutate` 的角色集合逐字等于 `browse_views.py:345/347` 现有的硬编码判定。

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

- [ ] **Step 5.5: 实施期校正与质量复审回写（2026-11-09 控制器，均已实测）**

1. **Step 1 的测试片段有两处不可直接照抄**：① 死码——`import re`、`_client()`、`APIClient`、`PASSWORD` 在那五条断言里一个都没被用到，落地时要么派上用场（`re` 现在是守卫区正则的承重件）要么删掉；② **真值表只钉了 10 格里的 7 格**：照正文抄，把 `system_config` 放宽成 `['administrator','user']` 实测 `Ran 5 tests / OK` 全绿（变异 M12 存活）。落地补成 2×5 逐格 `subTest` 网格（`EXPECTED_CAN`），M12 立刻红在该格上。网格是**独立 oracle**（按 spec §3.2 的口径重述，不是把表抄一遍），所以它有意义；补的两条判据各钉一句原本只活在注释里的话：「未声明 `required_feature` ⇒ 放行」（M10：`return True`→`False` 全仓只红这一条）与 `has_object_permission` 转发（M11）。
2. **Step 4 那句注释不能照抄**：`import/fix are additive and mirror upload privileges (administrator + user)` 在本树是假文档——`FileUploadView`（`apps/datafiles/views/file_views.py:520-521`）只有 `IsAuthenticated`，普通账号今天能上传却被 import/fix 拦，「mirror」说不成立。落地改成只指两处表键，并明写角色集合住在表里。
3. **`permissions.py` 头部不许写「历史教训：表、文档、实现三处漂过」**：`git grep -c FEATURE_PERMISSIONS -e 权限表 -- docs/tasks/lessons.md docs/tasks/lessons-archive.md` → 0 命中，那句话没有仓内出处（本仓反复出现的缺陷类）。落地写法见下：规则 + 两条**已知例外**（都不是门禁）：`apps/accounts/views.py` 的「最后一个启用管理员」校验、`apps/common/views.py` 下发给前端的 `editable` 提示。
4. **质量复审抓到一个 staleness 洞（本批最值钱的一条）**：Step 1 的 `assertNotIn("role not in ('administrator', 'user')", src)` 只覆盖 mutate 行；落地初版把 ban 侧缩到守卫区，仍漏「在守卫区之外/分发行之下再手写一处角色比较」。实测：`role = getattr(user, 'role', '') or 'administrator'`（E1）与在分发行之下插入 `_legacy_gate = role != 'administrator'`（E2）都**只红于新增的全文判据**，require 侧与行为矩阵全绿。最终判据 = 两条各管一头：

```python
    def test_browse_views_has_no_handwritten_role_gate(self):
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
```

   同时**纠正实施报告与本计划正文的一处假话**：「把 delete 行退回硬编码就没有任何判据会红」不成立——退回硬编码会让那处的 `role_can` 调用消失，require 侧正则当场红（M4 实测 2 红）。ban 侧的独家价值是**升权/旁路赋值**（表调用还在、实参被改写），不是防退回。
5. **三记「必须保持绿」的反向探针实测通过**：R1 把 `role_can(role, 'data_delete')` 拆成两行、R2 把局部变量 `role` 改名 `guard_role`、R3 在守卫区上方加一行**注释**里出现 `'administrator'`（判据跳过整行注释）。反向探针不是客套：没有它们，这两条源码判据下次重排时就会误报，然后被后人当噪声删掉。
6. **本批变异表最终 14/14 如预期**（M1/M2/M4/M5/M6/M9/M10/M11/M12/E1/E2 红，R1/R2/R3 绿），基线 `Ran 29 tests / OK`（`test_role_can` 7 例 + `ConsistencyCheckTests` 22 例），每次还原都按脚本自己的字节快照 `write_bytes` 回写并校 sha256。
7. **Task 4 追加一条触点**：`docs/reference/architecture-review-2026-10-15.md:122` 那句「`FeaturePermission` 以 `FEATURE_PERMISSIONS` 表驱动 15 项功能 × 3 角色的 RBAC」现在双重过期（键数与角色数），要一并改成 5 键 × 2 角色口径。

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

- [ ] **Step 6.5: 实施期校正与两轮复审回写（2026-11-09 控制器，全部实测）**

1. **Step 1 的片段不能照抄三处**：① 类里把用户模型 import 了三种方式（`get_user_model`、模块内 `from apps.accounts.models import User as U` × 2），落地统一用文件顶部已有的 `User`；② 两条 400 断言分不清「role 被 choices 拒」与「别的字段 400」——复审把 PUT 改成因 `is_active` 而 400，三条全绿，落地补 `assertIn('role', resp.json()['detail'])`（信封里 `detail` 才是 DRF 的原生字段字典，见 `apps/common/exceptions.py`）；③ 类 docstring 那句「只能在 AlterField 之后跑」**是假的**。
2. **choices 收敛与那道 AlterField 没有因果关系，计划正文与 Step 1 注释都把两者混为一谈**：拒 `viewer` 走的是 Python 侧 choices（ModelSerializer → ChoiceField），`manage.py sqlmigrate accounts 0013` 在本仓六个 settings 档（全是 sqlite3）实测都是 `(no-op)`；倒序（0013 挂 0011、0012 挂 0013）在任何内置后端都不会真的约束住行 —— `_field_db_check` 只按 `data_type_check_constraints` 生成 CHECK，那张表里只有 Positive* 三类整数。落地把注释改成实话，并**新增 `test_0013_declaration_matches_the_model_field`**：迁移里那条 role AlterField 的 `choices/default/max_length` 必须逐字等于 `User._meta.get_field('role')`。没有它时，把 0013 的 choices 加回 viewer、或把 default 改成 administrator、或改 max_length，29 例全绿；而 `makemigrations --check` 会退 1，却**不在本仓任何一档门禁里**（已 grep `package.json`/`scripts/*.mjs`/CI 确认）。
3. **Step 3 的出声条件按正文写会漏第三支**（`if merged['viewer_to_user'] or merged['viewer_to_administrator']:` ⇒ `superuser_promoted` 静默改写），改 `if any(merged.values()):`。更根本的是**计划完全没有给这条兜底配判据**：删掉 `normalize_roles(User)` 调用本可以一条不红。落地补 `test_seed_users_falls_back_to_role_normalization`（两条历史行 + 连跑两次 + 逐支计数值 + 第二次不许出声）与 `test_seed_users_prints_when_only_superuser_promoted`。实测坏法落点：调用换成等价空计数 ⇒ 2 红；条件改回正文那个 or ⇒ 1 红；条件写成 `if True:` ⇒ 1 红（第二条断言先确认 `Seed users completed.` 在场，才让「没有计数」不是空话）。
4. **计数断言要钉值不钉名**：`assertIn('viewer_to_user', text)` 放过 `{dict.fromkeys(merged, 0)}`（谎报全 0，实测 29 例全绿）。落地用 `_assert_counter(text, name, value)`，模式 `['\"]name['\"]\s*:\s*value(?![0-9])` —— 右侧收尾不写的话 `12`、`100` 都满足「=1」；引号两侧都允许，所以 dict repr 与 JSON 两种打印形态都不误报（前缀改写也照样绿）。
5. **ASCII 判据从「查一行」升级成「跑整条命令」**：初版 `lines[0].encode('ascii')` 是双向放行的代理——把与归并无关的 SUCCESS 行换成中文全绿，而同一命令在 cp1252 stdout 下真抛 `UnicodeEncodeError`。落地 `test_seed_users_writes_clean_under_non_cjk_codepage` 用 `TextIOWrapper(BytesIO(), 'cp1252')` 连跑三条分支（建号 / 修复 / 幂等），并要求五种哨兵行（`Created user:`、`Updated user:`、`User already exists:`、`viewer_to_user`、`Seed users completed.`）**都真的出现**，否则「任何一行都判」这句就是空话；反向探针 P4（把夹具里 `is_active=False` 那行删掉 ⇒ marker 断言红）证明这条链有牙。0012 那句裸 print 同族补 `MigrationPrintCodepageTests`（`redirect_stdout` 收裸 print）。
6. **计划正文与初版注释都过声称 e2e**：三条自动通路（`frontend/e2e/global-setup.ts:25`、`scripts/e2e_pool.mjs:77`、`electron/backend-env.ts:36`）都强制 `PYTHONIOENCODING=utf-8`，实测中文 stdout 在那种环境下 rc=0，所以「e2e 预跑因此判失败」不成立，文案改成「只管手动与第三方脚本调用」。另外量到两条：本仓把 console handler 指向 **stdout**（`config/settings/base.py:62`，判据 `test/backend/test_logging_streams.py`），中文日志记录在 cp1252 下不崩而是被吞成 `--- Logging error ---`（静默丢行，不在 stderr 豁免之列）；`CommandError` 走 stderr，标准库对 stderr 用 backslashreplace，确实安全。
7. **控制器给的建议被证证一次**：`MigrationLoader` 在 Django 6.0.9 里**没有** `leaf_migrations`，取叶子是 `MigrationGraph.leaf_nodes(app)`（`requirements/base.txt:27` 钉的版本，实测 `hasattr` 为假）。落地不断言叶子叫什么名字（Task 5 会合法新增 0014，焊名字必假红），只断结构：单叶 + 0012/0013 都在图里 + 0013 声明在 0012 之后。三种坏法的落点也量清了：并列两叶与父节点缺失都在**建库期**就炸（`CommandError: Conflicting migrations detected…` / `NodeNotFoundError`），只有倒序是这条判据独家红。
8. **连带必要修改（计划 Step 7 的 `git add` 清单原本没有）**：`scripts/line-limit.mjs` 的 frozen 行数 1968→1959 —— `findStaleExemptions` 判的是 `now < frozen.lines`，不改就 T2 红（`frontend/test/unit/lineLimit.spec.ts:158`）；`test/backend/test_server_settings_profile.py:194` 一处 prose；`role_migration.py` 两处「Task 3 会把…」的将来时（本批做完就成了假话）。另修一处既有 bug：Django 6.0.9 的 `DiscoverRunner.run_tests(self, test_labels, **kwargs)` 没有默认值，`test/backend/test_seed_users_guard.py:86`、`test_backup_db.py:356`、`test_page_size_bounds.py:228` 三处 `run_tests()` 直跑必 `TypeError` —— 三处一起补 label，只补其一是最坏状态（三个 `__main__` 现在分别跑通 4/9/21 例）。
9. **实施方撞 maxTurns 被中断**：它停在自己那张变异表跑到一半，本机留下一个仍在跑的 `mut2.py reject_no_notify` 变异进程。控制器动作是按纪律先盘现场（`git status` + 逐文件行数 + 四个生产文件 sha256 + 定向跑一遍 + 查残留进程），确认活已全落、树未带变异，杀掉进程后由控制器自己补跑完整变异表（`tasks/t3-mut/` 三个脚本：9/9、7/7、5/5 全部如预期，最终树重跑），再进复审。
10. **基线**：三档 29 例 OK（`test_role_normalization` + `test_accounts_bootstrap` + `test_seed_users_guard`），Step 6 全档 341 例 OK，`makemigrations --check --dry-run` → `No changes detected`，T2 `lineLimit` + `e2eAffectedDecide` 49 例通过。

- [ ] **Step 7: 提交（含 e2e 那一行）**

```bash
git add apps/accounts/models.py apps/accounts/migrations/0013_remove_viewer_role_choice.py \
  apps/accounts/management/commands/seed_users.py apps/accounts/serializers.py \
  apps/accounts/role_migration.py apps/accounts/tests.py \
  test/backend apps/common/tests_metrics.py apps/common/tests_system_paths.py \
  apps/datafiles/tests.py frontend/e2e/admin/admin.spec.ts \
  scripts/line-limit.mjs docs/superpowers/plans/2026-11-09-account-role-audit-implementation.md
git commit -m "feat(accounts): role choices 去掉 viewer，全仓后端引用与种子账号同步收敛"
```
（`git add` 路径请按实际改到的文件列全，别用 `.`；本批实际还连带 `test/backend/test_server_settings_profile.py`（prose）、`test/backend/test_backup_db.py` 与 `test/backend/test_page_size_bounds.py`（`run_tests()` 缺 label 的真 bug），它们都被 `test/backend` 这一条覆盖；提交前 `git status --porcelain` 复核没有把 `docs/tasks/todo.md` 或别人的未跟踪稿卷进来。计划正文原清单漏了 `role_migration.py`、`apps/accounts/tests.py`、`scripts/line-limit.mjs` 与本回写文件，2026-11-09 已补齐。）

---

## Task 4: 前端与入库文档的 viewer 清理

**Files:**
- Modify: `frontend/src/types/index.ts:6`、`frontend/src/components/layout/Topbar.vue:129`、`frontend/src/components/layout/AccountDialog.vue:185`、`frontend/src/pages/admin/UserManagement.vue:113,173,179`
- Modify: `frontend/e2e/fixtures/test-data.ts:33-37`、`frontend/e2e/README.md:32,135`、`frontend/e2e/auth/account.spec.ts:8`
- Modify: `README.md:34,180`、`docs/reference/server-deployment.md:242-243,305-317,413`、`docs/reference/architecture-review-2026-10-15.md:122`（Task 2 回写追加：那句「15 项功能 × 3 角色」键数与角色数双双过期）

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

- [ ] **Step 5.5: 实施期校正与两轮复审回写（2026-11-09/10 控制器，全部实测）**

1. **Step 1 的「三份 roleLabel 各删一行」这个形状本身被复审否掉了。** 删完之后 spec §7.3（迁移没跑到的机器不得显示第三种角色名）在全仓**没有任何判据**：T3 只有 `global.spec.ts` 的「Topbar 与角色」两条（管理员→「管理员」、普通用户→「用户」），而它们测不到兜底 —— 把 viewer 分支加回去那两条照样绿。三份拷贝 + Task 10 还要往这页加编辑弹窗（spec §7.2）= 第四份拷贝在路上。落地按仓内既有做法收敛：**逻辑搬进纯模块 `frontend/src/utils/roleLabel.ts`，三处组件只留委托**，判语义而不是判语法。
2. **初版源扫描判据的四处缺陷（逐条实测，别照抄那一版）**：① `bodyOf` 取的是函数名后第一个 `{` 而不是函数体，所以把 `roleLabel` 重构成三元式/查表时，红的是**邻居函数**（消息 `函数体里一个 return 字符串都没有`）——诊断指错方向；② 文件头那句「重构成查表会红，不是静默放行」**实测为假**：同一文件里放 `ROLE_LABELS = {administrator, guest}` 再加任何后面的链式 helper，9/9 全绿；第 4 个文件写 `if (role === 'guest')` 也绿，因为禁条只禁字面量 `viewer`；③ 下拉锚在字面 `v-model="newUser.role"` 上，Task 10 那种 `<el-select v-model="editForm.role">` 完全看不见（M3 实测）；④ 把 `['administrator','user']` 硬编码进「前端下拉 ↔ 模型 choices」交叉检查，就成了第三个编辑点（T1 已有两处：`test_model_choices_have_two_roles`、`test_0013_declaration_matches_the_model_field`）。
3. **落地后的判据**：`roleLabel` 的语义表（`administrator`→管理员，其余一切——含 `viewer`、`guest`、`undefined`——落「用户」）是真单位测试，任何新增第三角色都被它抓住；委托判据只查「从 `utils/roleLabel` 导入」+「本文件不再定义 roleLabel」，格式容忍多行 import 与无关局部变量改名（两记**必须保持绿**的反向探针实测通过）；交叉检查改成扫**每一个** `v-model="….role"` 下拉、与 `apps/accounts/models.py` 解析出的 `ROLE_CHOICES` 比集合，且**不硬编码期望值**，消息点名动的是哪一侧（M3：前端多加 `guest` ⇒ 1 红说「改页面，本测试不用动」；M4：模型加 `tester` ⇒ T2 1 红说「前端没跟上」+ T1 2 红，都在该改的那一侧）。
4. **明确放弃的三处覆盖（记下来，后来人才不会当噪声删掉别的判据）**：`roleIcon` 的兜底判据（表情符号不属 §7.3，但 roleIcon 里新增第三分支仍被语义禁条抓住 —— M3_ALIAS 实测）；`User.role` 联合类型 ↔ choices 的等值检查（交叉检查的失败消息已经把 `types/index.ts` 点名为同批要改的地方，它只是同一件事的第三次红）；以及「别名取值」这一记洞 —— `const r = u.role` 再 `r === 'guest'` 绕过禁条（实测 `['guest']` vs `[]`），闭它要 AST，T2 不值当，已写在该文件头部。
5. **`.gitignore` 的事实更正**（控制器 brief 与本计划都错过）：被忽略的只有 `/docs/tasks/*.bak-*.md`，`lessons.md` / `lessons-archive.md` / `todo.md` **是跟踪文件**（`git ls-files docs/tasks/` 三条都在，`git check-ignore docs/tasks/lessons.md` 退出 1）。只有 `docs/user-guide/` 整目录忽略。所以引用 lessons 里那条 2026-10-13「处置清单里的行号是易腐数据」是合法出处。
6. **带日期的实跑记录不改写，只补理由**：`server-deployment.md:245`、`:319` 保留「2026-10-23 那次用的是当时还在的 viewer」的身份，另起一句说明这条对照为什么现在照旧成立（闸门读 `FEATURE_PERMISSIONS['system_config'] = ['administrator']`，与角色名无关）；`docs/reference/renderer-memory-baseline-2026-10-22.md:120` 是那份基线文档自己的命令产出摘录，按它自己「只写有命令产出过的数字」的规矩原样留着。`architecture-review-2026-10-15.md` 加头部 ⚠ 快照说明，正文那句「15 项功能 × 3 角色」改成 5 项 × 2 角色并只按符号名指代 —— 初版补的半句「原判据 `permissions.py:21` 已不指向 `FeaturePermission`」**是假的**（21 行确实是 `class FeaturePermission`），规格复审抓到后删掉。`归并进 user` 那种半句话也补全：0012 把 superuser+viewer 行归并进 `administrator`。
7. **顺手修一处既有过期**：`frontend/e2e/README.md` 说 globalSetup 跑 `seed_test_data --clear`，实际 `frontend/e2e/global-setup.ts:51` 跑 `--refresh`（`--clear` 只保留在「若需重置数据」那段，两个 flag 都真实存在，见 `apps/accounts/management/commands/seed_test_data.py:36-37`）。
8. **Step 4 的门禁预期过期**：`Topbar.vue` / `AccountDialog.vue` / `types/index.ts` 都命中 `scripts/affected-rules.mjs` 的全局清单 ⇒ decide 判的是**全量**（82 文件），不是正文那句「命中 auth + admin + settings 档」。
9. **基线与变异表（最终树重跑）**：vitest 55 文件 / 741 例（742→741，roleLabel spec 9→8 例）；`npm run build`（`vue-tsc -b`）干净；`npm run lint:e2e` exit 0。变异：M1 util 加 guest 分支 ⇒ 2 红；M1_TABLE 只放一张含 guest 的查表 ⇒ 1 红（这条就是禁条存在的理由）；M2 Topbar 再留一份本地定义 ⇒ 3 红（控制器亲自复跑）；M3 editForm.role 下拉加 guest ⇒ 1 红（控制器亲自复跑，消息指向前端侧）；M3_ALIAS ⇒ 1 红；M4 模型加 tester ⇒ T2 1 红 + T1 2 红；M5 管理员标签写坏 ⇒ 1 红；**M6 把三元式换成查表必须保持绿**（正是旧版谎报的那件事）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/utils/roleLabel.ts \
  frontend/src/components/layout/Topbar.vue frontend/src/components/layout/AccountDialog.vue \
  frontend/src/pages/admin/UserManagement.vue \
  frontend/test/unit/roleLabelHygiene.spec.ts \
  frontend/e2e/fixtures/test-data.ts frontend/e2e/README.md frontend/e2e/auth/account.spec.ts \
  README.md docs/reference/server-deployment.md docs/reference/architecture-review-2026-10-15.md \
  docs/superpowers/plans/2026-11-09-account-role-audit-implementation.md
git commit -m "refactor(roles): 前端角色展示与部署探针去掉 viewer，README/部署文档同步两级"
```
（计划正文原清单漏了 `frontend/src/utils/roleLabel.ts`、`frontend/test/unit/roleLabelHygiene.spec.ts`、`docs/reference/architecture-review-2026-10-15.md`（它自己的 Files 清单要求改）与本回写文件；`docs/reference/renderer-memory-baseline-2026-10-22.md` 刻意不改，理由见 Step 5.5 第 6 条。提交前 `git status --short` 复核 `docs/tasks/todo.md` 与别人的未跟踪稿没被卷进来。）

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

- [ ] **Step 5.5: 实施期校正与两轮复审回写（2026-11-10 控制器，全部实测）**

1. **Step 1 的最后一条用例是空判据。** `test_change_password_still_succeeds_when_audit_insert_fails` 把 `audit._insert` 换成抛异常再 POST 改密端点，但**本批还没有任何调用点**（接线在 Task 6/7），于是 `_insert` 一次都没被调到，`status_code == 200` 与 `AuditEvent.objects.count() == 0` 都是白过。落地换成直接对机制下判据的两条（外层 `atomic()` 里写业务行 → 调 `record()` → 再写一条 → 退出后两行都必须在），并在 docstring 写明调用点还没接。
2. **控制器（我）给的一处更正是错的，被实施方量出来驳回 —— 这条要留着当反面教材。** 我用 2×2 探针得出「无内层 atomic + 真错误时业务行照样活着」，据此要求把计划正文那句「少一个 savepoint 就会把改密一起带走」降级成「不押在后端行为上的防线」。实施方改用**真** DB 错误重测：`Model._save` 对无父表模型包着 `transaction.mark_for_rollback_on_error()`，真错误没有 savepoint 可退时把**整笔**外层事务标死，下一条写语句抛 `TransactionManagementError`，业务行确实没了。我的探针之所以活着，是因为 mock 抛的是 Python 异常、**SQL 根本没发出去**。结论：计划正文那句成立，savepoint 支保留，四格表与各自落点写进 `test_audit_writer.py` 模块头（第四格「无 atomic + mock 抛」没有单独判据，也如实标出来）。
3. **复审两处 Critical（都已修 + 都有判据）**：① 取用户那几行原本在 `try` 外面，`request.user` 这个属性自己抛（DRF 懒解析的形状）时异常直接溢到调用方 —— 违反「业务动作永远优先」，接线时会 500 端点 ⇒ 整段搬进 `try`，判据 `test_request_user_property_that_raises_is_swallowed`；② `target=` 交给一个已 `delete()` 的实例时 `Model.save()` 抛 `ValueError`，被 best-effort 咽掉的后果是**整行丢失**，而 Task 7 的 `user_deleted` 正是这个形状 ⇒ 新增 `_live()`（只把有主键的实例当 FK 交出去，FK 留 None、快照照写），并如实写下罩不住的那层：pk 还在但行已不在（陈旧实例）时本仓 `PRAGMA foreign_keys=1` 会让 INSERT 在**外层提交时**抛 IntegrityError 到调用方身上，所以删除类事件必须走 `target_username=` 那种写法。
4. **两支重复整个 `_insert(...)` 参数表是缺陷，不是风格问题。** 实测三记「只改其中一份拷贝」的变异（savepoint 支的 `actor_username` 不截断 / autocommit 支的 `target_username` 不截断 / 两份都不截断）全部 10 例绿 —— 本仓「每份拷贝各配一记变异」的前提在这里做不到 ⇒ 合并成一次组装 `fields = dict(...)`、两支共用 `_insert(**fields)`，合并后 M-branch 与 M-nosavepoint 各自仍只红一条（已复跑）。
5. **列宽不抄第二份**：`USERNAME_MAX_LENGTH = 150` 抄死时，把模型列收窄到 60 全绿 ⇒ 改成 `AuditEvent._meta.get_field('actor_username').max_length`，并由 Meta 判据钉住两列同宽。
6. **规格复审点的两处 Missing 已补**：spec §5.1 明写的「删号后事件仍读得出来」（本文件原本 0 个 `delete()` 调用）与「Meta 形状无人判」（复合改 Meta —— 翻 ordering + 撤 `event` 索引 + `db_index=False` —— 原本 10 例全绿；Task 8 的查询靠这两样，漂了只表现为审计页一次全表扫）。
7. **两条边界按量到的行为写死，不假装兜住**：未登记的码名**照写 + warning**（拒写会把「码名写错」升级成「事件丢失」）；`detail` 不可 JSON 序列化时整行静默丢失，所以 spec §5.3 的 ISO 字符串约定必须由接线方遵守（Task 6 传 `locked_until` 前要自己转），这条也写进了模块头。
8. **形状判据合并成一记**：原来「`_dml == ['INSERT']`」+「`_dml == 全体`」两记可被逐个击破 —— 实测把第二记换成恒真再叠 M-branch（永远包 atomic）⇒ 全绿；合并成 `assertEqual(_verbs(cap), ['INSERT'])` 后同一变异必红（N8a 绿 / N8b 红，都复跑过）。`_dml`/`_DML` 随之删除。
9. **注释出处一律按符号名 + 版本**，不写 `.venv` 里的行号：那份树被 `.gitignore` 排除，Django 升级时行号会静默腐烂（本批原本引了 `base.py:957`、`transaction.py:122-125/:275/:279-280` 四处，已全部改成 `Model._save` / `mark_for_rollback_on_error` / `Atomic.__exit__` + 「Django 6.0.9」）。
10. **变异表（两轮）**：首轮 11 记里 N2（`actor=` 交裸实例）、N7（`actor_username` 不截断）、N8（形状断言）三记**存活** ⇒ 补 `test_unsaved_actor_falls_back_to_snapshot_only`（用未保存实例，同时钉 `_live` 的 actor 侧与 `_snapshot` 的 actor 侧）并把形状断言合并；二轮 N2/N7 各 1 红、N8a 绿 N8b 红、R1a（dict 里插注释）绿；R1b（`fields` 整体改名）在变异脚本里误红，独立复跑 `python test/backend/test_audit_writer.py` = 18 例 OK，判为探针脚本自身缺陷而非判据问题。
11. **基线**：`test_audit_writer` 18 例（计划正文 Step 4 那句「Ran 7 tests」已过期）+ `test_login_path_statements` 5 例 = 23 OK；定向 177 例 OK（含 `apps.accounts`、`apps.common`、登录族、角色三批的判据）；`makemigrations --check --dry-run` = `No changes detected`；0014 由 `makemigrations` 生成，`dependencies` 自动挂 0013，Task 3 的单叶判据 `test_single_leaf_and_parentage` 因此继续绿。

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

- [ ] **Step 5.5: 实施期校正与两轮复审回写（2026-11-10 控制器，全部实测）**

1. **Step 2 的成功路径代码块把 `tokens = get_tokens_for_user(user)` 写重复了。** 现状里那一行本来就在（`views.py` 取 token 在写库之后），整块替换会变成**取两次 token** ⇒ outstanding token INSERT 多一笔、refresh 轮换账多一环。计划正文那块应当只把 `audit.record(...)` 接在既有那一行**之后**，不要连取 token 一起抄进去。（这条只有 Step 4 的形状数组能看见，注释与端点状态码全都照常绿。）
2. **Step 3 ③ 的数组只是 DML，完整动词表实测含簿记**：`TestCase` 的外层原子块让 `record()` 走 savepoint 支，干净账号成功路径的**全体**动词是 `['SELECT', 'SELECT', 'UPDATE', 'INSERT', 'SAVEPOINT', 'INSERT', 'RELEASE']`。只钉 DML 一记是 Task 5 评审抓到的漂移口（「多包一层原子块」这类改动在 DML 数组上隐形），所以干净账号那条用例额外把含簿记的完整序列钉一记 —— 两记的分工写在用例注释里。autocommit 支（生产登录）仍由 `test_audit_writer.py::WriterAutocommitShapeTests` 量，本批没动它。
3. **Step 4 那句「用 `self.assertIn('accounts_audit_event', _sqls(cap)[-1])` 钉住」按位置取数，不许照抄。** 位置式（`[-1]`）在语句顺序一变时就悄悄指到别的语句上，判据当场恒真。落地按**内容**认领：动词是 INSERT **且** SQL 里有 `"{AuditEvent._meta.db_table}"`，两者成对判定（`_audit_inserts()`），并且和 outstanding token 那条各钉「恰好 1 条」，把 ① 里两个 INSERT 槽填满。
4. **Step 2 里 `detail={'retry_after_minutes': 15}` 的字面 15 被换成从 `LOCKOUT_DURATION` 推导**（新模块常量 `_AUDIT_LOCKOUT_MINUTES`）。审计是事后取证的，常量若调，抄来的数字开始说谎。反过来，`_error(...)` 载荷里那两个字面 15 **故意不动** —— 那是已下发的 API 契约（`LoginPage.vue` 按 `retry_after_minutes` 出提示、`apps/accounts/tests.py::test_login_5_wrong_attempts_locks_account` 按它取值）。两记判据各钉一边：M5a（审计侧退回字面 15 + 常量改 20 分钟）只有 `test_fifth_failure_records_failure_then_lock` 红；M5b（只把常量改 20 分钟，实现不变）**全绿**，证明审计侧确实同源推导、载荷侧确实不跟着漂。
5. **Step 2 注释里「此前全仓没有任何通路写入 `last_login`」是说过头了，已改口。** 实测：`config/urls.py` 无条件挂着 `path('admin/', admin.site.urls)`，`django.contrib.admin` 在 `base.py` 的 `INSTALLED_APPS` 里，`AdminSite.login` → `contrib.auth.views.LoginView.form_valid` → `auth_login` → `user_logged_in` → `update_last_login`。用测试库探一次 admin 表单登录：302，且 `last_login` 落值。`seed_users.py` 给 administrator `is_staff=True`，所以这条路对真实账号是通的。准确口径是「**本仓这条 JWT 登录通路**从来没写过它」—— Django admin 那条要 session 且要 `is_staff`，产品里没有入口，所以「管理页那一列一直是空的」在实际使用中成立。落点在 `views.py` 成功路径注释、`test_login_path_statements.py` 模块头、`test_audit_login_events.py` 断言消息三处。**同样的话 `docs/tasks/todo.md` 末尾那段也说过一遍，但那个文件此刻带着另一个会话未提交的改动，本批不许碰 ⇒ 留给 Task 14 收口时改。**
6. **Step 1 的用例草稿只数行、不判「恰好一行」**：`self._rows()[0]` 单独用会放过「多记一笔」。落地加了 `_only_row()`（每个分支恰好 1 行）与第 5 次失败的 `AuditEvent.objects.count() == MAX_LOGIN_ATTEMPTS + 1`（四次失败 + 第五次两行）。停用/锁定那条原本也是 `_rows()[0]`，复评审指出「在 `login_failure` 之前多插一笔」能放过它 ⇒ 换成整表比对 `[(event, reason, target_username)] == [两行]`，一记同时钉住行数、倒序时间线与两支的 reason。另外「`detail` 不可序列化 ⇒ 整行静默丢失」这条边界**只有** `test_fifth_failure_records_failure_then_lock` 判得到（全仓只有 `account_locked` 那支交过 datetime），原本两处说法写成「每条用例的行数断言」，`audit.py` 模块头与本文件模块头口径 3 都已收窄成点名那一条。
7. **复评审抓到的一处「列宽抄第二份」我判为不成立**：`test_audit_login_events.py` 里 `len(...) == 150` 与 `test_audit_writer.py` 的 `test_overlong_username_is_truncated_not_raised`、`test_unsaved_actor_falls_back_to_snapshot_only` 同口径，是**独立 oracle**（收窄模型列宽时它必须红），和 Task 5 第 5 条改掉的那个是两回事 —— 那条是**实现**里抄死 `USERNAME_MAX_LENGTH = 150`，本仓实现早已从 `AuditEvent._meta` 读。判据侧留字面值。
8. **变异表（本机复跑 `tasks/mut6.py`，字节快照回写、sha256 校验通过；每记跑 `test_audit_login_events` + `test_login_path_statements` = 12 例）**。对照两记：**M0 无变异** 12 例绿、**M5b 只改常量** 12 例绿。摘掉某一笔 `audit.record` 的 6 记（M1 成功 / M2 未知用户名 / M7 `account_locked` / M8 非第 5 次密码错误 / M9 停用 / M10 第 5 次那笔 `login_failure`）分别红 4 / 3 / 1 / 3 / 1 / 1 例，落点全在预期那条上。三记形状类：M3（照抄计划里重复的取 token）红 3 条成功形状；M4（退回「只在脏时才写」）红 3 例，其中 `test_login_success_reset_path_still_writes` **故意绿** —— 那个账号 attempts=2，条件成立照样写，它管的是「计数确实清零」而不是「写是无条件的」；M11（`last_login` 原地自赋值，UPDATE 仍在、形状不动）红 2 例，钉住的是值不是语句。M6（在锁定分支的 `login_failure` **之前**多插一笔）红 1 例，正是复评审指出「`_rows()[0]` 放过它」后换成整表比对的那条 —— 改回按位置取数则 M6 全绿。M5a 红 1 例（见第 4 条）。
9. **基线**：Step 4 的两个模块 + `test_audit_writer` = 30 例 OK；Step 5 的回归集（`test_login_throttle` / `test_accounts_write_paths` / `apps.accounts` / `test_account_password_change` / 本批两模块 / `test_audit_writer`）= 114 例 OK；系统 Python（Django 6.0.5）跑本批判据同样绿。
10. **Step 6 的 `git add` 清单不够**：本批还改了 `apps/accounts/audit.py`（模块头三处未来时态改现在时，「Task 6 接线后…」已经是事实）、`test/backend/test_audit_writer.py` 与 `test/backend/test_accounts_write_paths.py`（同理由的注释校正），以及本计划文件本身。

- [ ] **Step 6: 提交**

```bash
git add apps/accounts/views.py apps/accounts/audit.py test/backend/test_audit_login_events.py test/backend/test_login_path_statements.py test/backend/test_audit_writer.py test/backend/test_accounts_write_paths.py docs/superpowers/plans/2026-11-09-account-role-audit-implementation.md
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

- [ ] **Step 4.5: 实施期校正与两轮复审回写（2026-11-10 控制器，全部实测）**

1. **`unlock` 没有按计划正文包 `transaction.atomic()`。** 正文那段把「业务写 + 审计」罩进一层原子块，但审计是 best-effort：块内失败被 `record()` 咽掉，块并不会因此回滚业务写，代价只有 BEGIN/COMMIT。实跑（`TransactionTestCase` 真 autocommit）：不包 = 1 SELECT + 1 UPDATE + 1 INSERT，包 = 多一对 BEGIN/COMMIT。同理 `ChangePasswordView` 与 `reset_password` 的 `audit.record` 一律放在**既有** atomic 块**之外**：块内 7 条（SAVEPOINT/INSERT/RELEASE）vs 块外 5 条；`reset_password` 8 条 vs 6 条。`TestCase` 里量不出这个差别（`in_atomic_block` 恒真），必须用 `TransactionTestCase`。
2. **测试从正文的 5+1 条长到 14 条**，每条都有落点：整表 `_rows()`（正文的 `_row(event)` 用 `.order_by('-id').first()`，放过「同一次动作多写一笔」与「把别的事件码也写成这一次」）；`_ROW_FIELDS` 七列整值比对，含 `ip_address`（写入器侧只证「给了合法 IP 就存下来」，端点侧要证的是接线时真的把 `request` 传进了 `record()` —— 变异 Q5：把 `request` 换成 `None` ⇒ `ip_address` 落 None，红 1 条）；两条「被拒不留痕」用例（守卫那条 / 序列化器那条，失守位置不同）；`changed_fields` 排序那条（不排序 ⇒ 数组跟着 `Meta.fields` 的写法漂）；requested-not-diffed 那条（见第 6 条）；`unlock` 的 UPDATE 列集合那条（见第 8 条）；配置带第三个键那条（见第 7 条）。
3. **`_WritablePasswordSerializer` 是形状夹具，不是生产形状。** 白名单只作用于 update 这条路，而 `UserSerializer` 没有可写口令字段 ⇒ 白名单今天挡不到任何东西，所以用手造的 subclass（`Meta.fields + ['password']`）把差异顶出来。它会明文写进 `password` 列（生产序列化器不允许），用例只取审计那一行 —— 别把这条判据读成「视图里已经在记口令」。变异 A（`AUDITABLE_FIELDS` 加上 `password`）与 B（干脆去掉白名单过滤）各自红 1 条。
4. **控制器（我）写的两处注释被复审量出来是错的，都改了**：① 「眼前三条写路径的序列化器都没有可写口令字段」——假。`UserCreateSerializer.password`、`AdminResetPasswordSerializer.new_password`、`PasswordChangeSerializer` 那三个都是可写字段；那三条安全是因为 detail 手搓、不过白名单。② 「守卫那条 400 发生在视图写完业务之后」——假。`perform_update` 先 `_guard_lockout` 再 `serializer.save()`，两条路的 400 都在业务写之前。教训同 Task 5 那条：**注释里的位置/时序断言要照着代码跑一遍再抄**，散文看着顺不等于对得上号。
5. **`values` 是改完之后**（改之前 `is_active` 是 True，记旧值会把「停用了谁」写成「谁本来就是启用的」）；`user_deleted` 的 `role` 是删除前，靠 `perform_destroy` 里先取局部变量。Django 删完只把 pk 置 None、其余属性留着，但那是实现细节，不押它。
6. **`changed_fields` 记的是「请求带了哪些可记字段」，不是值差集**：重发当前值也算 changed。这是与 `_guard_lockout`、`serializer.save()` 对齐（两者都只看请求带了什么），审计自己比 before/after 就成了第二条时间线；代价是那行不能说「这个人被改动了」。判据 `test_user_updated_records_requested_fields_not_a_diff`；变异 Q2（把 detail 改成值差集）红 3 条。
7. **`system_paths_changed` 的 `restart_required` 按整份字典比，detail 只投影两个键 —— 这个不一致是**已知语义**并被钉住了**：`save_config` 整份重写且只写 `data_dir`/`temp_dir`，所以配置里手改出来的第三个键会被这次 PUT 抹掉 ⇒ 载荷说「要重启」是对的，而 detail 的 before/after 看着相等。变异 Q4（把比较也收窄成投影字典）红 1 条 —— 收窄会把「真的少了个键」报成「不用重启」。
8. **`unlock` 从整行 `save()` 换成 `update_fields` 窄写，唯一判据是 UPDATE 的 SET 列集合**：窄写与整行写在返回体、审计行、两列的最终值上都不可区分。列集合按整值判（`sorted(cols) == ['lockout_until', 'login_attempts']`），不逐列 `assertIn`/`assertNotIn` —— 后者漏掉的那几列恰好最贵（`password`/`last_login`/`is_superuser`/`first_name` 都会被整行 SET 一遍）。取列助手在本文件另写一份、锚 `"accounts_user"`：与 `test_accounts_write_paths.py` 里同名助手只差锚表，合并要把锚参数化、两边注释都会对不上号。变异 Q1（退回整行 save）红 1 条。
9. **响应文案从英文 `'Account unlocked successfully.'` 换成中文**：全仓与前端都没钉住旧串（`UserManagement.vue` 的 `unlockUser` 只 POST、不读响应体），钉新串在那条形状判据里。
10. **变异表（四轮，`tasks/mut7.py` / `mut7b.py` / `mut7c.py` / `mut7d.py`，字节快照 + sha256 校验回写）**。两组跑位要分清：**窄组** = 只跑本文件 14 例，**宽组** = `test_audit_account_events` + `test_admin_lockout` + `apps.accounts` + `test_account_password_change`（81 例）。摘掉七笔 `audit.record`（窄组，各红的条数）：`user_updated` 4、`system_paths_changed` 2、`user_created`/`user_deleted`/`account_unlocked`/`password_changed`/`password_reset` 各 1（`password_reset` 与 `user_created` 那两记是在宽组量的，同样 1）。其余：C（去掉 `sorted`）宽组红 1；A（白名单加上 `password`）宽组红 1；B（去掉白名单过滤）宽组红 1；E2（把 `user_updated` 的 record 挪到守卫之前）宽组红 1；Q2（detail 改成值差集）窄组红 3；Q3（create 的 detail 交空）窄组红 1；Q1（`unlock` 退回整行 save）窄组红 1；Q5（`record(None, ...)` 丢 request）窄组红 1；Q6（`password_changed` 记在校验之前）窄组红 2；Q4/D2（`restart_required` 收窄成投影比较 / 写死 True）窄组各红 1；H（`user_deleted` 交 `target=instance` 而不是 `target_username=`）**全绿** —— 删除后实例 pk 已被 Django 置 None，`audit._live()` 把两种写法折成同一行，这个调用点分辨不了，管住该形状的是写入器侧 `test_audit_writer.py::test_deleted_target_instance_still_records_the_snapshot`。对照（无变异）每轮绿。
11. **变异脚本自己的一个坑（记下来当规矩）**：`mut7.py` 只在 `finally` 里回写快照，于是一轮里换文件下手时，下一记（含对照）跑在上一记没被覆盖的那个文件上 —— 对照组实际带着 `I` 那记变异，是个假信号（当时看不出来纯属侥幸：`I` 恰好还没有判据）。改成**每记跑完立刻按快照全量回写所有被改文件**，`mut7b/c/d` 都这么写。
12. **本批没修、留给 Task 14 记台账的一条**：`perform_create` + `UserCreateSerializer.create`（`user.save()` 之后 `UserSetting.objects.create`）不在同一笔事务里，`UserSetting` 失败会留下「有用户、无 `user_created` 事件」的半截状态 —— 与审计无关的既有缺陷，接线只是把它暴露成「审计少一行」。要修就是给 create 那条路补一层 `atomic()`，属于行为变更，不放在接线批里顺手做。（另：`docs/tasks/todo.md` 里那句过宽的 `last_login` 说明也归 Task 14，出处见 Task 6 的 Step 5.5 第 5 条。）
13. **基线**：本文件 14 例；Step 4 那组（本文件 + `test_account_password_change` + `apps.accounts` + `test_profile_privilege` + `test.backend` 整目录）= **1714 例 OK（skipped=8）**；窄一组（再加 `test_admin_lockout` + `apps.common` + `test_accounts_write_paths`）= 172 例 OK。

- [ ] **Step 5: 提交**

```bash
git add apps/accounts/views.py apps/common/views.py test/backend/test_audit_account_events.py docs/superpowers/plans/2026-11-09-account-role-audit-implementation.md
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

- [ ] **Step 4.5: 实施期校正与两轮复审回写（2026-11-10 控制器，全部实测）**

1. **正文的 `AUDIT_USERNAME_MAX_LENGTH = 150` 删掉，改用 `audit.USERNAME_MAX_LENGTH`。** Task 5 已经量过「实现里抄第二份列宽」是缺陷（当时把模型列收窄到 60 全绿），这里同理：两份一旦漂移，坏的方向是「一个存得进快照列的用户名被查询侧拒掉」，于是审计页永远搜不到那笔事件，而那串字符看着完全合法。变异 M8real（视图中两处换成字面 150 **且**把 `actor_username` 收窄到 120）⇒ 红 4 条（API 1 + 写入器侧 3），两侧都有牙。**注意 M8 的第一版是假变异**：只把引用换成字面 150、列宽不动，本机行为一模一样 ⇒ 全绿，什么都没证。
2. **`max_page_size` 刻意不设**，DRF 3.18.3 `PageNumberPagination.get_page_size()` 现量：`0`/`-5`/`abc`/`2.5`/`''` 一律静默回落默认 50，`101` 只有在配了 `max_page_size` 时才静默截到 100，**一个 400 都不发**。所以显式校验是唯一那道闸，配了 clamp 反而误导（「超限是被 clamp 掉的」）。变异：删掉显式校验 ⇒ 红 1（`test_page_size_that_drf_would_silently_absorb`）；`page_size_query_param=None` ⇒ 红 2。
3. **排序补了 `-id`，正文对排序完全没提这件事**。只按 `-created_at` 排不是全序，翻页会重复/漏行；但**本机删掉 `-id` 在可观察层面什么都没错** —— `EXPLAIN QUERY PLAN` 现量这条 SELECT 走 `accounts_audit_event_created_at_763e7054`，平手次序恰好等于 `-id` 要的。所以「顺序/页边界」那条判据抓不住它，另加一条钉**发出的 ORDER BY 文本**的判据才抓得住（删 `-id` ⇒ 只红这条；翻成 `id` ⇒ 两条一起红）。另外量清了两件事：200 次「同一请求里连记两笔」实测 0 次相同时间戳（相差 134–149 µs，一次 INSERT 本身的代价），而 2000 次相邻 `timezone.now()` 有 1402 次撞成同一个值 —— 所以「平手不会出现」不能写进注释当理由，视图里那段注释按这个实测口径改过一遍（复审第一轮抓的就是我原来那句「第五次失败后那两笔会平手」，它在本机不成立）。
4. **测试从正文的 8 条长到 29 条**，分六个类：`AccessAndShapeTests`（权限三态 + 载荷形状 + 序列化器无可写字段 + 十个码逐个可查）、`FilterTests`（event / username 两侧 icontains / 两参数 AND / 空参数语义）、`LocalDayBoundaryTests`（今天两端含、相邻日各自、开区间、窗口整体落在数据外 ⇒ 空页而非 400、边界是本地不是 UTC）、`PaginationTests`（默认 50 而不是全局 20、界内界外、整页走查不重不漏、同瞬间全序 + 页边界、ORDER BY 文本、非法 `page` ⇒ 404）、`BadParamTests`（七种坏参数各自的 400 信封与 `code`）、`ReadOnlyTests`（四种写方法、无 detail 路由、读不写行）。
5. **`_parse_day_bound` 多一个 `name=` 形参**：400 的中文 `message` 要点名是 `date_from` 还是 `date_to`（spec §10），不然用户只看到「日期格式应为 YYYY-MM-DD」而不知道自己填的是哪一格。这些中文 message 从本批起是 Task 11 可见的契约。
6. **两处与正文预期不同、且是 DRF 决定的**：非法 `page` 走分页自己的 `NotFound` ⇒ **404 `not_found`**（正文没写，Task 11 要按 404 处理）；405 只有权限过了才拿得到（DRF `dispatch` 先 `initial()`），所以只读判据是以管理员身份发的，`/audit-events/<id>/` ⇒ 404（没有 detail 路由）。
7. **`username=''` 那一腿是不可判的**，注释里如实写明：`icontains ''` 匹配所有非 NULL，跳过筛选同样是全部，两种实现给同一个结果。有牙的是 `event=''`（少了 `if event` 就筛出零行；变异 ⇒ 红 14 条）与两条空日期腿（去掉 `_parse_day_bound` 的空串入口判断 ⇒ 红 18 条）。
8. **`__lte(当天 23:59:59)` 这个回归本批一度抓不住**：种子行都落在整数秒上，截断到秒与次日零点 `__lt` 给同一个结果。复审第二轮要求把 `late_today` 种成 `23:59:59.123456`（`created_at` 存微秒，现量写 123456 读回还是 123456），改完这一行后「上界截到秒」那记变异红 4 条。**同一条教训适用于第 1 条那个 M8**：变异必须改掉某个可观察的东西，否则它只是文本改动。
9. **成本事实（不设判据，只记录）**：每次请求两条查询（页 + `count`，`count` 是 spec §6 要的）；`username` 那对 `icontains` 是两次全表扫，`(actor_username, created_at)` / `(target_username, created_at)` 两根索引在 `LIKE '%x%'` 下用不上（`EXPLAIN` 现量）。Task 11 若把默认筛选做成「必须填用户名」，这条成本会变成常态，届时再判要不要加窗口约束。
10. **DST 在这里测不到**，如实记录：`TIME_ZONE='Asia/Shanghai'` 无夏令时，Django 6 的 `timezone.make_aware` 是 `replace(tzinfo=...)`（`fold=0`），没有任何用例假装覆盖它。边界用「本地今天 00:30 在 UTC 里是昨天 16:30」这个偏移事实钉（`test_bounds_are_local_not_utc` 钉前提，红在这里说明时区配置变了而不是筛选写错）。
11. **结构**：`views.py` 现在 579/600 行（`scripts/line-limit.mjs` exit 0），审计读端这一整块约 110 行是本文件最后一块还能整块搬走的；本批**不**切（Task 9–14 都不碰 `views.py`），切分理由与时机写在 `AuditEventListView` 的 docstring 末段，给下一个要往这里加东西的人。
12. **变异表（三轮，`tasks/mut8.py` / `mut8b.py` / `mut8c.py`，字节快照 + sha256 校验、每记跑完立刻全量回写）**：窄组 = `test_audit_api`（29 例）。删 `-id` 1 红；username 只搜 actor 2 红；上界截到秒 4 红；按 UTC 判边界 5 红；去掉 event 白名单 1 红；`required_feature` 换成别的键 1 红；`pagination_class=None` 28 红；去掉 `read_only_fields` 1 红；去掉倒置检查 1 红；去掉 page_size 校验 1 红；去掉空串判断 18 红；去掉日期筛选 4 红；event 无条件筛选 14 红；字面 150 + 列宽 120 红 4（含写入器侧 3）。对照（无变异）每轮绿。
13. **基线**：本模块 29 例；审计五兄弟（writer 18 + login 7 + account 14 + statements 5 + api 29）= 80 例 OK；`test.backend + apps.accounts + apps.common` = **1808 例 OK（skipped=8）**；`makemigrations --check --dry-run` = `No changes detected`。

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
git add apps/accounts/serializers.py apps/accounts/views.py apps/accounts/urls.py test/backend/test_audit_api.py docs/superpowers/plans/2026-11-09-account-role-audit-implementation.md
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

- [ ] **Step 4.5: 实施期校正与两轮复审回写（2026-11-10 控制器，全部实测）**

1. **测试从正文的 12 条长到 32 条，七个 `describe`**：审计事件标签 4（异源十对逐字、双向同集合、查表通路本身、未知码与三个原型名回退）、`defaultAuditFilters` 2、`buildAuditQuery` 8（只发非空条件、两侧 trim、日期补零与半截、形状不校验历法、页码、`page_size` 接受域、超长 username 不截）、`summarizeDetail` 10（占位符、六种真实形状逐句、「空」的两种写法、打码含误伤与递归、启发式抓不住值、循环引用、120 预算两端、最长真实一行）、与后端参数名同源 1、与后端数字同源 2、抽取器自证 5。正文 Step 3 那句 `Tests 12 passed` 以这条为准。
2. **第四份副本是查询参数名，正文完全没有它**（复审第一轮找出，是本轮唯一的 Critical）。`buildAuditQuery` 发出的 `event`/`username`/`date_from`/`date_to`/`page_size` 抄的是 `AuditEventListView.get_queryset` 里那五个 `params.get('…')`；实测把 `views.py` 的 `params.get('date_from', '')` 改成 `params.get('from_date', '')`，**改判据前 32 例全绿**——DRF 对不认识的参数静默忽略，审计页于是拿到一份看着像全量的时间线，一声不吭，正是本文件第 60–64 行自己排在最坏的那一类（合理但错的行集）。补了 `extractAuditParamNames`：只切 `class AuditEventListView` 到下一个顶格 `class` 那段类体（整份 `views.py` 一起刮会把接受域宽成一个谁都不看的集合），找不到类或一个名字都没刮到就抛。判据是「前端可能发出的键名全集 == 后端真读的名字 ∪ `page`」，全集从实现取（填满 / 半截日期 / 空白三种输入各发一次再收集），所以前端改名也一起红。`page` 只能点名：它是 `PageNumberPagination.page_query_param` 的默认名，源码里不出现 `params.get('page')`，它改名的判据在 T1 的整页走查。变异 N13（后端改名）红 2、N14（前端改名）红 4。
3. **`event` 与日期的不对称按「用户说完了没有」收口**（正文只写了日期那条线）：`event` 现在与 `username` 一样先 `trim()`，全空白 = 不发；日期先 `normalizeDay` —— 完整的补零（`2026-1-5` → `2026-01-05`），真半截的（`2026-11`、`2026/11/09`、`20261109`）交回空串不发。理由：后端 `strptime('%Y-%m-%d')` **实测**连 `2026-1-5` 都收，所以「只认两位」是前端自己画的线，不是后端的；画了这条线又不补零，就是把用户已经填完的条件静默丢掉。判据在 `test_audit_api.py::BadParamTests` 与这里的日期形状用例两头各钉一遍。
4. **`auditEventLabel` 查表改走 `Object.hasOwn`**，正文那句 `AUDIT_EVENT_LABELS[event] ?? event` 有原型泄漏：`'toString'` 会从原型上取到一个 Function，而 `??` 只挡 `null`/`undefined`，页面就把「function toString(){…}」显示成事件名。后端对未登记的码只留 warning、不拒写（`test_audit_writer.py::WriterTests::test_event_list_is_the_single_source`），所以这种字符串真会进表；用例把 `toString`/`constructor`/`__proto__` 三个原型名与三个真旧码一起钉住。
5. **正文里 `REAL_DETAILS` 那句「后端 detail 的六个真实形状，摘要判据全部建立在它们之上」是假说明，已按实测改写**。十个码逐个看过调用点：`login_success`、`password_changed`、`account_unlocked` **根本不写 `detail`**（`audit._insert` 那句 `detail or {}` 兜成空 dict，摘要给占位符），`system_paths_changed` 那份「前后两串 Windows 路径 + 布尔」最长、单独钉在 120 预算那条；`login_failure` 一个码有四种形状（`{reason}`、`{reason, remaining_attempts}`、`{reason, retry_after_minutes}`、加 `account_locked` 的 `{retry_after_minutes, locked_until}`），表里只取 `bad_password` 那一形。顺带把 `summarizeDetail` 注释里那句「`audit.record()` 里 `detail or {}`」改成 `_insert()`，那半句在 `apps/accounts/audit.py:102`，不在 `record` 里。
6. **后端那十个键名一个都不匹配 `/pass|token|secret/i`**（逐条数过：`reason`/`remaining_attempts`/`retry_after_minutes`/`locked_until`/`role`/`is_active`/`changed_fields`/`values`/`lockout_cleared`/`before`/`after`/`restart_required`），所以前端的按键名打码是**纵深防御**而不是现役堵漏；它只覆盖摘要这一行，正文 Task 11 的弹窗是裸 `JSON.stringify(row.detail, null, 2)`（本文件 2647 行）。这句话已写进 `DETAIL_SUMMARY_MAX` 的注释，弹窗要不要复用同一套键名规则归 Task 11 判。
7. **刮取一律在用例内部调用，不在模块顶层跑**：顶层抛错会被 vitest 报成一次收集失败（整文件 0 例），而 house style 是「读源码可以顶层、判定必须在 `it` 里」（`portWiring.spec.ts` 顶层只 read、`roleLabelHygiene.spec.ts` 连 parse 都在 `it` 内）。形状坏了要红的是**那一条命名用例**：变异 N11（块里挤进一行注释）与 N12（`AUDIT_EVENTS = (` 换成 `[`）各红 2 条，而不是整文件红。
8. **删掉两处不增加杀伤力的判据**（复审第二轮点的）：`extra`/`missing` 两条已经隐含「排序后逐字相等」，第三条纯重复；`toContain('login_success')` 被同一条同集合判据吞掉；「后端把上限挪小时夹出来的值仍在新接受域内」那条整块与 `page_size` 用例里的恒等式循环同输入同界——把它独有的性质（**夹的参照物来自实现而不是测试**）并进那段循环的注释，界仍取 `backendPageSizeMax()`。
9. **`USERNAME_QUERY_MAX` 与 `AUDIT_PAGE_SIZE_MAX` 目前是「无消费者的导出」**，Task 11 必须绑上去而不是重抄：正文 2608 行 `maxlength="150"` 要改成 `:maxlength="USERNAME_QUERY_MAX"`，2676 行 `:page-sizes="[20, 50, 100]"` 要由 `AUDIT_PAGE_SIZE_MAX`（加默认 50）推出来。按原文抄死就是把本模块刚消灭的第二副本又搬回组件里，而且那份抄本没有绊线。
10. **序列化器响应字段名是第五份副本，本批刻意不钉**：`AuditEventSerializer` 的七个 `fields` 现在前端还没有消费者，为假想读者写判据是空的。Task 11 落 `api/audit.ts` 时一起钉（同一套刮 `serializers.py` 的做法，找不到就抛）。
11. **`audit.py` 里 `AUDIT_EVENTS` 上方那段注释从将来时改成现在时**（正文写的「Task 9 会加一条绊线」已经落地）：现在点名绊线在 `frontend/test/unit/audit.spec.ts`、未登记码的回退是 warning 不拒写、以及块形要求（顶格 `AUDIT_EVENTS = (`、每项独占一行、只有单引号小写名 + 逗号）——最后这条是**给刮取器看的契约**，改形之前先想红的是哪几条。
12. **变异表（`tasks/mut9c.mjs`，15 记，字节快照 + sha256 校验，每记跑完立刻全量回写）**：Z 对照绿；N1 后端加码 2 红；N2 后端删码 2 红；N3 `AUDIT_PAGE_SIZE_MAX` 挪宽 1 红；N4 默认值改 30 1 红；N5 模型列收窄到 120 1 红；N6 前端不夹 `page_size` 1 红；N7 打码不递归 1 红；N8 刮取静默返回空集合 1 红；N9 摘要不截断 2 红；N10 标签表多贴一码 2 红；N11 块里挤注释 2 红；N12 块括号换方括号 2 红；N13 后端改参数名 2 红；N14 前端改参数名 4 红。
13. **基线**：本模块 32 例；全量 `npx vitest run` = 56 文件 / 773 例；`npm run build`（含 `vue-tsc -b`）干净；`node scripts/line-limit.mjs` exit 0；后端 `test_audit_api` 29 例 OK（本批只改了 `audit.py` 的注释，没动任何后端判据）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/utils/audit.ts frontend/test/unit/audit.spec.ts apps/accounts/audit.py docs/superpowers/plans/2026-11-09-account-role-audit-implementation.md
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

