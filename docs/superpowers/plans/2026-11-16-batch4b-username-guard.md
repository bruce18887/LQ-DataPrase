# 批4 刀二：`..` 用户名上传逃逸双层防御 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `..` / `.` / 空串 / 含分隔符的用户名不能把上传目录拼到 `MEDIA_ROOT`，并且失败形态是 400 `unsafe_username` 而不是 500；新账号在创建时就被拒绝，旁路（admin/命令/bootstrap）由上传目录的第二层兜住。

**Architecture:** 判据从 `apps/datafiles/storage_usage.py` 抽到 `apps/common/usernames.py`（`UNSAFE_USERNAMES` + `is_safe_username`），上传目录与占用扫描共用同一份。第一层在 `UserCreateSerializer.validate_username`（挡 API 建号）；第二层在 `_user_upload_dir` 的 `makedirs` 之前抛 `UnsafeUsernameError(APIException, 400, unsafe_username)`，经既有异常处理器出稳定机器码。24 个调用点一处都不加 try。

**Tech Stack:** Django + DRF + unittest；不涉及前端。

**Spec:** `docs/superpowers/specs/2026-11-15-batch4a-e2e-split-and-username-guard-design.md` §3、§4、§6；门禁节奏见 `docs/reference/testing-gates.md`。

## Global Constraints

- **600 行硬约束**：`apps/datafiles/tests.py` 冻在 **1959 行**，**一行都不能加**；新判据放 `test/backend/`（`test_usernames.py` / `test_batch_dir_traversal.py`）。`apps/accounts/tests.py` 现有 498 行，本次增量必须远小于 102 行余量。
- **不改 24 个调用点**：`_user_upload_dir` 的失败靠统一异常处理器出信封，不给任何调用点加 try。
- **不缩窄** `apps/sftp/views.py` 那三处 `except Exception`（会改变既有失败信封，属独立小批）。
- **不做** `User.username` 字段级 validators + `AlterField` 迁移；**不做** 存量改名工具；**不加** 前端 `ERROR_CODE_MAP` 的 `unsafe_username`（处理器已把中文句子放进 `message`）。
- **版本控制**：从 master（当前 `24fa25c`）另开 `feature/batch4b-username-guard`；master 上不提交产品代码；不 push。
- **门禁**：`apps/accounts/**` 与 `apps/common/**` 命中 `[GLOBAL]`，收口必须跑 `node scripts/e2e_pool.mjs --slots=4` + 后端全套 + `npx vitest run` + `npm run lint:e2e`；判绿取日志末尾判据行，不取退出码。
- **语义**：400 不是 403（与角色无关）；`a.b` 这类带点号的正常账号必须照旧 201/200。

## File Structure

- `apps/common/usernames.py`（新建）：`UNSAFE_USERNAMES` + `is_safe_username`，唯一判据。
- `apps/common/exceptions.py`：`UnsafeUsernameError(APIException)` + `_KNOWN_EXCEPTIONS` 注册。
- `apps/datafiles/storage_usage.py`：删除本地判据，改 import；订正“老入口没挡”的注释。
- `apps/datafiles/views/usage_views.py`：改 import 到 `apps.common.usernames`。
- `apps/datafiles/views/_helpers.py`：`_user_upload_dir` 在 `makedirs` 前抛 `UnsafeUsernameError`；订正假 docstring。
- `apps/accounts/serializers.py`：`UserCreateSerializer.validate_username`。
- `apps/accounts/tests.py`：3 条建号判据（拒绝 `..` / 允许 `a.b` / 拒绝 `.` 与空串）。
- `test/backend/test_usernames.py`（新建）：判据纯函数 + `_user_upload_dir` 第二层 + HTTP 400。
- `docs/tasks/todo.md`：本刀台账与门禁记录。

---

### Task 1: 抽出判据 + 第二层上传防护

**Files:**
- Create: `apps/common/usernames.py`
- Modify: `apps/common/exceptions.py`
- Modify: `apps/datafiles/storage_usage.py`
- Modify: `apps/datafiles/views/usage_views.py`
- Modify: `apps/datafiles/views/_helpers.py`
- Test: `test/backend/test_usernames.py`（新建，判据纯函数）
- Test: `test/backend/test_batch_dir_traversal.py`（追加第二层与 HTTP 400）

**Interfaces:**
- Produces: `is_safe_username(username) -> bool`、`UNSAFE_USERNAMES`、`UnsafeUsernameError`（`status_code=400`、`default_code='unsafe_username'`）。
- Consumes: 既有统一异常处理器 `custom_exception_handler`。

- [ ] **Step 0: 从 master 开分支**

```bash
git switch -c feature/batch4b-username-guard master
```

Expected: `Switched to a new branch 'feature/batch4b-username-guard'`

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_usernames.py`（判据本体）：

```python
"""`is_safe_username` 的判据本体（批4 刀二）。

第二层与 HTTP 400 的判据按设计稿 §3.6 落在
`test/backend/test_batch_dir_traversal.py`；这里只钉纯函数。
"""
import os

from django.test import SimpleTestCase

from apps.common.usernames import is_safe_username


class SafeUsernameTests(SimpleTestCase):
    def test_rejects_names_that_change_the_directory(self):
        for bad in ('', '.', '..', 'a' + os.sep + 'b'):
            self.assertFalse(is_safe_username(bad), repr(bad))

    def test_allows_dotted_and_normal_names(self):
        for good in ('user', 'a.b', 'a-b', 'a_b', 'a@b', 'a+b'):
            self.assertTrue(is_safe_username(good), repr(good))
```

在 `test/backend/test_batch_dir_traversal.py` 追加（文件已有 `os/shutil/tempfile`、`SimpleTestCase/TestCase/override_settings`、`APIClient`、`User`、`_user_upload_dir`；补下列 import）：

```python
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from apps.common.exceptions import UnsafeUsernameError
```

```python
class UserUploadDirGuardTests(SimpleTestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='lqdp-usernames-')
        self.addCleanup(shutil.rmtree, self.media, True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def test_unsafe_username_raises_and_creates_nothing(self):
        with self.assertRaises(UnsafeUsernameError):
            _user_upload_dir(SimpleNamespace(username='..'), 'single')
        self.assertFalse(os.path.isdir(os.path.join(self.media, 'single')))

    def test_dotted_username_is_allowed(self):
        path = _user_upload_dir(SimpleNamespace(username='a.b'), 'single')
        self.assertTrue(os.path.isdir(path))
        self.assertTrue(path.startswith(os.path.join(self.media, 'data')))


class UnsafeUsernameUploadTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='lqdp-usernames-http-')
        self.addCleanup(shutil.rmtree, self.media, True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(
            username='..', password='strong-pass-123', role='user')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_upload_returns_400_unsafe_username(self):
        upload = SimpleUploadedFile('x.csv', b'a,b\n1,2\n', content_type='text/csv')
        resp = self.client.post('/api/v1/upload/', {'file': upload}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get('code'), 'unsafe_username')
        self.assertFalse(os.path.isdir(os.path.join(self.media, 'single')))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_usernames
```

Expected: FAIL/ERROR（`ModuleNotFoundError: apps.common.usernames` 与 `ImportError: UnsafeUsernameError`）。

- [ ] **Step 3: 新建 `apps/common/usernames.py`**

```python
"""用户名能否安全地用作数据目录名（账号名会拼进 MEDIA_ROOT 路径）。"""
import os

UNSAFE_USERNAMES = ('', '.', '..')


def is_safe_username(username):
    """用户名能否作为单个路径段使用。

    Django 的 ``UnicodeUsernameValidator`` 接受 ``..`` / ``.`` 作为完整用户名；
    把它们拼进 ``MEDIA_ROOT/data/<username>`` 会归一化到 ``MEDIA_ROOT`` 或
    ``MEDIA_ROOT/data``。上传路径与占用扫描共用这一份判据。
    """
    name = str(username)
    return not (
        name in UNSAFE_USERNAMES
        or os.sep in name
        or (os.altsep and os.altsep in name)
    )
```

- [ ] **Step 4: `apps/common/exceptions.py` 加异常并注册**

在 `from rest_framework.exceptions import (...)` 里加入 `APIException`，并在 `_KNOWN_EXCEPTIONS` 之前定义：

```python
class UnsafeUsernameError(APIException):
    """账号名不能当数据目录名用；400 而不是 500（不是服务器坏了）。"""
    status_code = 400
    default_detail = '账号名无法用作数据目录名'
    default_code = 'unsafe_username'
```

在 `_KNOWN_EXCEPTIONS` 元组末尾加入：

```python
    (UnsafeUsernameError, 'unsafe_username', '账号名无法用作数据目录名'),
```

- [ ] **Step 5: `storage_usage.py` 改 import 并删本地判据**

删除 `_UNSAFE_USERNAMES` 与 `is_safe_username` 定义，加入：

```python
from apps.common.usernames import is_safe_username
```

把 `_user_data_root` docstring 中“已知同形状的老入口 `_helpers.py:172 _user_upload_dir` 没挡这一条……”整段替换为：

```text
    ``_helpers.py`` 的上传入口已经用同一个 ``is_safe_username`` 挡住同一条；
    两侧共用 ``apps.common.usernames``，判据不会再漂。
```

- [ ] **Step 6: `usage_views.py` 改 import**

```python
from apps.common.usernames import is_safe_username
from apps.datafiles.storage_usage import get_user_usage
```

- [ ] **Step 7: `_helpers.py` 加第二层 + 订正 docstring**

在文件顶部加入：

```python
from apps.common.exceptions import UnsafeUsernameError
from apps.common.usernames import is_safe_username
```

把 `_user_upload_dir` 的 docstring 中“Django's UnicodeUsernameValidator guarantees … so no further sanitization is performed.”整段替换为：

```text
    The directory is named after the user's login name (not the numeric id) so
    that paths are stable across id changes and human-readable in shell
    listings.  Usernames that cannot be a single directory name (``''`` /
    ``'.'`` / ``'..'`` / separators) are rejected by ``is_safe_username``;
    raising ``UnsafeUsernameError`` keeps that failure a 400, not a 500.
```

在 `if user is None:` 之后、拼路径之前加入：

```python
    if not is_safe_username(user.username):
        raise UnsafeUsernameError()
```

- [ ] **Step 8: 跑测试确认通过**

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_usernames test.backend.test_batch_dir_traversal test.backend.test_storage_usage_scan
```

Expected: `OK`；`test_usernames.py` 2 例 + `test_batch_dir_traversal.py` 既有用例 + 新增 3 例。

- [ ] **Step 9: 提交**

```bash
git add apps/common/usernames.py apps/common/exceptions.py apps/datafiles/storage_usage.py apps/datafiles/views/usage_views.py apps/datafiles/views/_helpers.py test/backend/test_usernames.py test/backend/test_batch_dir_traversal.py
git commit -m "feat(datafiles): 上传目录拒绝不安全的用户名"
```

---

### Task 2: 建号 serializer 第一层

**Files:**
- Modify: `apps/accounts/serializers.py`
- Test: `apps/accounts/tests.py`

**Interfaces:**
- Consumes: `is_safe_username`（Task 1）。
- Produces: `UserCreateSerializer.validate_username`；非法用户名 → 400 `validation_error`，`detail.username` 带错。

- [ ] **Step 1: 写失败测试**

在 `apps/accounts/tests.py` 的 `UserManagementViewSetTests` 末尾追加：

```python
    def test_create_rejects_unsafe_username(self):
        resp = self.client.post(
            '/api/v1/auth/users/',
            {'username': '..', 'password': 'strong-pass-123'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['code'], 'validation_error')
        self.assertIn('username', resp.data['detail'])
        self.assertFalse(User.objects.filter(username='..').exists())

    def test_create_allows_dotted_username(self):
        resp = self.client.post(
            '/api/v1/auth/users/',
            {'username': 'a.b', 'password': 'strong-pass-123',
             'email': 'ab@example.com', 'display_name': 'AB'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['username'], 'a.b')
        self.assertTrue(User.objects.filter(username='a.b').exists())

    def test_create_rejects_dot_and_empty_username(self):
        for bad in ('.', ''):
            resp = self.client.post(
                '/api/v1/auth/users/',
                {'username': bad, 'password': 'strong-pass-123'},
                format='json',
            )
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, repr(bad))
            self.assertIn('username', resp.data['detail'], repr(bad))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test apps.accounts
```

Expected: 前两条红（`..` 被创建 / `a.b` 也许已能建但 `..` 的断言红），至少 `test_create_rejects_unsafe_username` FAIL。

- [ ] **Step 3: 实现 serializer**

`apps/accounts/serializers.py` 加 import：

```python
from apps.common.usernames import is_safe_username
```

在 `UserCreateSerializer` 内、`validate` 之前加：

```python
    def validate_username(self, value):
        if not is_safe_username(value):
            raise serializers.ValidationError('账号名无法用作数据目录名')
        return value
```

- [ ] **Step 4: 跑测试确认通过**

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test apps.accounts test.backend.test_usernames
```

Expected: `OK`；`a.b` 201、`..`/`.`/空串 400。

- [ ] **Step 5: 提交**

```bash
git add apps/accounts/serializers.py apps/accounts/tests.py
git commit -m "feat(accounts): 建号时拒绝不能作为目录名的用户名"
```

---

### Task 3: 台账、分支与全量门禁

**Files:**
- Modify: `docs/tasks/todo.md`

**Interfaces:**
- Consumes: Task 1/2 的代码与测试。
- Produces: 可并入的验证树；并入仍需用户点头。

- [ ] **Step 1: 在 todo.md 追加本刀条目**

```markdown
# 任务：批4 刀二（用户名路径双层防御，2026-11-16）

设计：`docs/superpowers/specs/2026-11-15-batch4a-e2e-split-and-username-guard-design.md` §3
计划：`docs/superpowers/plans/2026-11-16-batch4b-username-guard.md`

## 勾选清单

- [ ] 判据抽到 `apps/common/usernames.py`，上传目录第二层抛 `UnsafeUsernameError`
- [ ] `UserCreateSerializer.validate_username` 第一层
- [ ] 全量门禁（全局档：池 + 后端全套 + vitest + lint）
- [ ] 并入 master（需用户点头；不 push）

## 门禁记录

| 档 | 命令 | 实测判据行 |
|---|---|---|
| T1 | `manage.py test apps.accounts test.backend.test_usernames test.backend.test_batch_dir_traversal test.backend.test_storage_usage_scan` | |
| 全量 vitest | `npx vitest run` | |
| e2e 类型 | `npm run lint:e2e` | |
| 全量池 | `node scripts/e2e_pool.mjs --slots=4` | |
| 后端全套 | `manage.py test` | |
```

- [ ] **Step 2: 提交台账与计划**

```bash
git add docs/tasks/todo.md docs/superpowers/plans/2026-11-16-batch4b-username-guard.md
git commit -m "docs(plan): 批4 刀二计划与台账"
```

（分支已在 Task 1 Step 0 创建。）

- [ ] **Step 3: T1 定向门禁**

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test apps.accounts test.backend.test_usernames test.backend.test_batch_dir_traversal test.backend.test_storage_usage_scan
```

Expected: `OK`；把 `Ran N tests` / `OK` 原文填进 todo 表。

- [ ] **Step 4: 全量档（GLOBAL）**

```bash
cd frontend && npx vitest run
cd frontend && npm run lint:e2e
node scripts/e2e_pool.mjs --slots=4
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test
```

每次一条命令；池与后端可并行（本项目并跑验收口径：红集合相等 + 例数相同）。取池的 `unexpected`/`结论` 行与后端的 `Ran … / OK` 行填表。

- [ ] **Step 5: 提交台账**

```bash
git add docs/tasks/todo.md
git commit -m "docs(todo): 批4 刀二收口门禁"
```

- [ ] **Step 6: 并入本地 master（需用户点头；不 push）**

```bash
git merge-base --is-ancestor master HEAD
git switch master
git merge --ff-only feature/batch4b-username-guard
git branch -d feature/batch4b-username-guard
git status --short
```

Expected: FF 成功、分支删除、工作树干净；`origin` 不推送。

---

## 自审

**Spec 覆盖：** §3.1 缺陷（Task 1）、§3.2 两层（Task 1 第二层 / Task 2 第一层）、§3.5 两处注释（Task 1 Step 5/7）、§3.6 判据（Task 1/2 的测试）、§3.7 全量门禁（Task 3）。

**占位符：** 无；代码与命令都是可执行原文。

**类型一致：** `is_safe_username` 单一实现；`UnsafeUsernameError` 在 `_KNOWN_EXCEPTIONS` 注册后由既有处理器映射为 `unsafe_username`；serializer 的 `ValidationError` 走 `validation_error`，与 `test_put_username_must_remain_unique` 的既有断言同形。
