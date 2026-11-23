# 文件隐藏（软隐藏）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给数据文件加「隐藏」标记：隐藏只影响选文件的候选列表（`/files/` 默认排除、`/files/options/` 恒排除），文件管理列表仍可查看、筛选与恢复；不动批次聚合/修复中心/存储统计。

**Architecture:** 后端在 `DataFile` 上加 `is_hidden` 布尔字段，可见性参数解析抽成 `apps/datafiles/visibility.py` 纯函数（`file_views.py` 已 591 行，不允许再加逻辑）；前端文件管理页加「隐藏状态」筛选 + 行徽标 + 单项切换按钮，其余 8 个选择面靠 options 默认排除零改动生效。

**Tech Stack:** Django 5 + DRF（APITestCase）、Vue 3 + Element Plus（el-table / el-select）、Vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-11-23-file-hidden-design.md`

## Global Constraints

- **600 行红线**（机械判据 `frontend/test/unit/lineLimit.spec.ts`）：`apps/datafiles/views/file_views.py` 现 **591 行**，本批只允许通过 `visibility.py` 接线，收口前 `wc -l` 必须 ≤ 600；`FileListTab.vue` 520、`FileListTable.vue` 460、`FileListToolbar.vue` 199，改动后均不得超 600。
- **冻结测试文件不许加行**：`apps/datafiles/tests.py`（EXEMPT 精确 1968 行）、`frontend/e2e/data/data.spec.ts`（EXEMPT 精确 1042 行）——后端新用例一律写 `apps/datafiles/tests_hidden.py`，e2e 一律新文件 `frontend/e2e/data/file-hidden.spec.ts`。
- **软隐藏边界**：隐藏只过滤 `action == 'list'` 与 `options`；详情/更新/删除/`apps/datafiles/lookup.py` 按 id 取数一律不拦。`get_queryset` 的隐藏过滤必须放在**最后**（标签搜索用 OR 拼查询集，提前过滤会被 OR 带回来）。
- **默认排除、显式包含**：`GET /files/` 缺省只返回未隐藏；`?include_hidden=1` 全部；`?hidden_only=1` 仅隐藏（优先于 include_hidden）。`/files/options/` 无开关，恒排除。
- **双主题**：新增样式只用 CSS 变量（`var(--text-2)` 等），light/night 都要目检。
- **迁移即全量门禁**：命中 `*/*/migrations/*.py` ⇒ affected 判据升全量档；收口跑 `node scripts/e2e_pool.mjs --slots=4` + 后端全套。
- **一条 bash 只跑一个 playwright 档位**；跑前确认端口空闲，判绿取日志末尾汇总行/`RESULT:`，不取 `$?`。
- **共享工作树**：不 `git add -A`；只 stage 本计划列出的文件；提交前 `git status --short` 核对。
- **不 push、不合并**：FF 并入本地 master 需用户点头（本计划止于分支收口）。

## File Structure

- `apps/datafiles/models.py`（改）：`is_hidden` 字段。
- `apps/datafiles/migrations/0007_datafile_is_hidden.py`（新建，makemigrations 生成）。
- `apps/datafiles/visibility.py`（新建）：`visibility_mode` / `apply_visibility` 纯函数。
- `apps/datafiles/serializers.py`（改）：两个序列化器 `fields` 加 `'is_hidden'`。
- `apps/datafiles/views/file_views.py`（改）：list 末端收口、options/三分面排除；只接线不加逻辑。
- `apps/dashboard/views.py`（改）：默认选文件 `is_hidden=False`。
- `apps/datafiles/tests_hidden.py`（新建）：T1 全量组合。
- `frontend/src/types/index.ts`（改）：`DataFile.is_hidden`。
- `frontend/src/api/datafiles.ts`（改）：`ListFilesParams` 两参数 + `setHidden`。
- `frontend/src/pages/data/components/FileListToolbar.vue`（改）：隐藏状态下拉。
- `frontend/src/pages/data/components/FileListTab.vue`（改）：筛选状态 + 切换处理 + 接线。
- `frontend/src/pages/data/components/FileListTable.vue`（改）：徽标、置灰、操作列按钮。
- `frontend/src/pages/admin/AdminFiles.vue`（改）：`include_hidden: 1` + 徽标（只读）。
- `frontend/e2e/data/file-hidden.spec.ts`（新建）：T3 一条接线证明。
- `docs/intro/guide/04-data.md`（改）：文件列表章节补隐藏说明。
- `docs/tasks/todo.md`（改）：台账（已在计划落盘时追加，执行中勾选）。

---

### Task 0: 开分支与基线核盘

**Files:**
- 无代码改动

**Interfaces:**
- Consumes: master 当前 HEAD（计划与 spec 已入库）
- Produces: 分支 `feature/file-hidden`

- [ ] **Step 1: 核盘**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
git status --short
git log --oneline -3
wc -l apps/datafiles/views/file_views.py apps/datafiles/tests.py frontend/src/pages/data/components/FileListTab.vue frontend/src/pages/data/components/FileListTable.vue frontend/src/pages/data/components/FileListToolbar.vue frontend/e2e/data/data.spec.ts
```

Expected: `git status --short` 为空；行数依次约 `591 / 1968 / 520 / 460 / 199 / 1042`。若工作区脏：**停止**并报告，不 stash、不 checkout。

- [ ] **Step 2: 开分支**

```bash
git switch -c feature/file-hidden master
```

Expected: `Switched to a new branch 'feature/file-hidden'`

---

### Task 1: 模型字段 + 迁移 + 序列化器（T1：默认值 / PATCH 切换 / 他人 404）

**Files:**
- Create: `apps/datafiles/tests_hidden.py`
- Modify: `apps/datafiles/models.py`（`status` 字段之后）
- Create: `apps/datafiles/migrations/0007_datafile_is_hidden.py`（makemigrations 生成）
- Modify: `apps/datafiles/serializers.py`（两处 `fields`）

**Interfaces:**
- Produces: `DataFile.is_hidden`（bool，默认 False）；`PATCH /api/v1/files/{id}/ {"is_hidden": bool}` 返回 detail 序列化器（含 `is_hidden`）。

- [ ] **Step 1: 写失败测试**

新建 `apps/datafiles/tests_hidden.py`：

```python
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile

User = get_user_model()


def _make(owner, filename, **kwargs):
    defaults = dict(
        file_path=f'/tmp/{filename}',
        file_size=100,
        format_type='CTA8290D',
        status='ready',
    )
    defaults.update(kwargs)
    return DataFile.objects.create(owner=owner, filename=filename, **defaults)


class HiddenToggleTests(APITestCase):
    """is_hidden 字段契约：默认 False、PATCH 单字段切换、他人文件 404。"""

    def setUp(self):
        self.user = User.objects.create_user(username='hidden_owner', password='x')
        self.other = User.objects.create_user(username='hidden_other', password='x')
        self.client.force_authenticate(self.user)
        self.file = _make(self.user, 'toggle.csv')

    def test_new_file_defaults_to_visible(self):
        resp = self.client.get(f'/api/v1/files/{self.file.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['is_hidden'])

    def test_patch_toggles_hidden(self):
        resp = self.client.patch(
            f'/api/v1/files/{self.file.id}/', {'is_hidden': True}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['is_hidden'])
        self.file.refresh_from_db()
        self.assertTrue(self.file.is_hidden)

        resp = self.client.patch(
            f'/api/v1/files/{self.file.id}/', {'is_hidden': False}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.file.refresh_from_db()
        self.assertFalse(self.file.is_hidden)

    def test_patch_other_users_file_is_404(self):
        foreign = _make(self.other, 'foreign.csv')
        resp = self.client.patch(
            f'/api/v1/files/{foreign.id}/', {'is_hidden': True}, format='json')
        self.assertEqual(resp.status_code, 404)
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_hidden)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python manage.py test apps.datafiles.tests_hidden -v 1
```

Expected: FAIL（`TypeError: 'is_hidden' is an invalid keyword argument` 或 `KeyError: 'is_hidden'`）。

- [ ] **Step 3: 加模型字段**

`apps/datafiles/models.py` 在 `status = models.CharField(...)` 之后加：

```python
    # 软隐藏：只影响选文件的候选列表（/files/ 默认排除、/files/options/ 恒排除），
    # 详情/更新/删除/按 id 取数一律不拦。过滤内核见 apps/datafiles/visibility.py。
    is_hidden = models.BooleanField(default=False, db_index=True)
```

- [ ] **Step 4: 生成迁移并核对**

```bash
python manage.py makemigrations datafiles
```

Expected: `Create model ...` 不出现，只生成 `apps/datafiles/migrations/0007_datafile_is_hidden.py`，内容为：

```python
class Migration(migrations.Migration):

    dependencies = [
        ('datafiles', '0006_add_sub_batch_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='datafile',
            name='is_hidden',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
```

- [ ] **Step 5: 序列化器暴露字段**

`apps/datafiles/serializers.py`：`DataFileSerializer.Meta.fields` 与 `DataFileListSerializer.Meta.fields` 各加 `'is_hidden'`（放在 `'status'` 之前；**不要**加进 `read_only_fields`，PATCH 要用）。

- [ ] **Step 6: 跑测试确认通过**

```bash
python manage.py test apps.datafiles.tests_hidden -v 1
```

Expected: `Ran 3 tests` / `OK`

- [ ] **Step 7: 提交**

```bash
git add apps/datafiles/tests_hidden.py apps/datafiles/models.py apps/datafiles/migrations/0007_datafile_is_hidden.py apps/datafiles/serializers.py
git commit -m "feat(datafiles): DataFile.is_hidden 字段与 PATCH 切换（T1）"
```

---

### Task 2: 可见性过滤（列表 / options / 分面 / 仪表板 + 软隐藏边界）

**Files:**
- Create: `apps/datafiles/visibility.py`
- Modify: `apps/datafiles/views/file_views.py`（get_queryset 末端、options、product_codes、format_types、list_tags）
- Modify: `apps/dashboard/views.py`（默认回退）
- Modify: `apps/datafiles/tests_hidden.py`（追加用例）

**Interfaces:**
- Produces: `visibility_mode(query_params) -> 'visible'|'all'|'hidden'`；`apply_visibility(queryset, query_params, action) -> queryset`。

- [ ] **Step 1: 追加失败测试**

在 `apps/datafiles/tests_hidden.py` **追加**：

```python
class VisibilityModeTests(APITestCase):
    """visibility_mode 纯解析：真值判定与 hidden_only 优先级。"""

    def test_modes(self):
        from apps.datafiles.visibility import visibility_mode
        self.assertEqual(visibility_mode({}), 'visible')
        self.assertEqual(visibility_mode({'include_hidden': '1'}), 'all')
        self.assertEqual(visibility_mode({'hidden_only': '1'}), 'hidden')
        self.assertEqual(
            visibility_mode({'hidden_only': '1', 'include_hidden': '1'}), 'hidden')
        self.assertEqual(visibility_mode({'include_hidden': '0'}), 'visible')


class HiddenListApiTests(APITestCase):
    """列表默认排除隐藏；include_hidden / hidden_only；分面与 options 排除。"""

    def setUp(self):
        self.user = User.objects.create_user(username='list_u', password='x')
        self.client.force_authenticate(self.user)
        self.visible = _make(
            self.user, 'visible.csv',
            product_code='PROD_A', format_type='CTA8290D', tags=['open'],
        )
        self.hidden = _make(
            self.user, 'hidden.csv',
            product_code='PROD_H', format_type='ETS88', tags=['secret'],
            is_hidden=True,
        )

    def _list_ids(self, params=None):
        resp = self.client.get('/api/v1/files/', params or {})
        self.assertEqual(resp.status_code, 200)
        return [row['id'] for row in resp.data['results']]

    def test_list_excludes_hidden_by_default(self):
        ids = self._list_ids()
        self.assertIn(self.visible.id, ids)
        self.assertNotIn(self.hidden.id, ids)

    def test_include_hidden_returns_all(self):
        ids = self._list_ids({'include_hidden': 1})
        self.assertIn(self.visible.id, ids)
        self.assertIn(self.hidden.id, ids)

    def test_hidden_only_returns_hidden(self):
        self.assertEqual(self._list_ids({'hidden_only': 1}), [self.hidden.id])

    def test_hidden_only_wins_over_include_hidden(self):
        self.assertEqual(
            self._list_ids({'hidden_only': 1, 'include_hidden': 1}),
            [self.hidden.id],
        )

    def test_list_rows_expose_is_hidden(self):
        resp = self.client.get('/api/v1/files/', {'include_hidden': 1})
        rows = {row['id']: row for row in resp.data['results']}
        self.assertFalse(rows[self.visible.id]['is_hidden'])
        self.assertTrue(rows[self.hidden.id]['is_hidden'])

    def test_search_tag_or_does_not_leak_hidden(self):
        """标签搜索用 OR 拼查询集：隐藏过滤必须在最后收口，不能被 OR 带回来。"""
        resp = self.client.get('/api/v1/files/', {'search': 'secret'})
        self.assertNotIn(self.hidden.id, [row['id'] for row in resp.data['results']])

    def test_options_excludes_hidden(self):
        self.hidden.status = 'error'
        self.hidden.save(update_fields=['status', 'updated_at'])
        err_visible = _make(self.user, 'err_ok.csv', status='error')
        for params in ({}, {'include_error': 1}):
            resp = self.client.get('/api/v1/files/options/', params)
            ids = [row['id'] for row in resp.data['results']]
            self.assertNotIn(self.hidden.id, ids, params)
            if params:
                self.assertIn(err_visible.id, ids)
            else:
                self.assertNotIn(err_visible.id, ids)

    def test_facets_exclude_hidden_only_values(self):
        codes = self.client.get('/api/v1/files/product_codes/').data['product_codes']
        self.assertIn('PROD_A', codes)
        self.assertNotIn('PROD_H', codes)
        formats = self.client.get('/api/v1/files/format_types/').data['format_types']
        self.assertIn('CTA8290D', formats)
        self.assertNotIn('ETS88', formats)
        tags = self.client.post('/api/v1/files/list_tags/', {}, format='json').data['tags']
        self.assertIn('open', tags)
        self.assertNotIn('secret', tags)

    def test_detail_update_delete_of_hidden_are_allowed(self):
        """软隐藏边界：详情/改/删不因隐藏而受限。"""
        self.assertEqual(
            self.client.get(f'/api/v1/files/{self.hidden.id}/').status_code, 200)
        self.assertEqual(
            self.client.patch(f'/api/v1/files/{self.hidden.id}/',
                              {'is_hidden': False}, format='json').status_code, 200)
        self.hidden.refresh_from_db()
        self.assertFalse(self.hidden.is_hidden)
        self.hidden.is_hidden = True
        self.hidden.save(update_fields=['is_hidden', 'updated_at'])
        self.assertEqual(
            self.client.delete(f'/api/v1/files/{self.hidden.id}/').status_code, 204)

    def test_lookup_returns_hidden_file(self):
        """按 id 批量取数（analysis/导出共用口径）不拦隐藏。"""
        from apps.datafiles.lookup import owned_files_by_pk
        found = owned_files_by_pk(self.user, [self.hidden.id])
        self.assertIn(self.hidden.id, found)


class DashboardHiddenFallbackTests(APITestCase):
    """未传 file_id 的默认取文件要跳过隐藏行。"""

    def setUp(self):
        self.user = User.objects.create_user(username='hidden_dash', password='x')
        self.client.force_authenticate(self.user)

    def test_only_hidden_ready_file_yields_no_data(self):
        _make(self.user, 'only_hidden.csv', is_hidden=True)
        resp = self.client.get('/api/v1/summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['code'], 'no_data')

    def test_visible_file_is_picked_even_if_older(self):
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        try:
            _make(self.user, 'older_visible.csv', file_path=path)
            _make(self.user, 'newer_hidden.csv', is_hidden=True)
            resp = self.client.get('/api/v1/summary/')
            self.assertEqual(resp.status_code, 200)
            # 选中可见行（空文件解析失败 ⇒ parse_failed），不是 hidden 行（路径不存在 ⇒ file_not_found）
            self.assertEqual(resp.data['code'], 'parse_failed')
        finally:
            os.unlink(path)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python manage.py test apps.datafiles.tests_hidden -v 1
```

Expected: 新增用例 FAIL（默认列表含隐藏、options 含隐藏、分面含隐藏值、dashboard 选中隐藏行、`ModuleNotFoundError: apps.datafiles.visibility`）。

- [ ] **Step 3: 新建可见性内核**

新建 `apps/datafiles/visibility.py`：

```python
"""文件隐藏（软隐藏）的过滤内核。

隐藏只影响「选择文件的候选列表」：列表端点只在 ``action == 'list'`` 时排除隐藏，
``options`` 端点恒定排除；详情/更新/删除/按 id 取数一律不受限（软隐藏）。
参数约定（仅 list 端点）：

- 缺省                 → 只返回未隐藏
- ``?include_hidden=1`` → 返回全部（含隐藏）
- ``?hidden_only=1``    → 只返回已隐藏（优先于 include_hidden）
"""

VISIBLE = 'visible'
ALL = 'all'
HIDDEN = 'hidden'

_TRUE_VALUES = {'1', 'true', 'yes', 'on'}


def visibility_mode(query_params) -> str:
    """把查询参数解析成三种可见性模式：visible / all / hidden。"""
    if str(query_params.get('hidden_only', '')).strip().lower() in _TRUE_VALUES:
        return HIDDEN
    if str(query_params.get('include_hidden', '')).strip().lower() in _TRUE_VALUES:
        return ALL
    return VISIBLE


def apply_visibility(queryset, query_params, action: str):
    """仅在 list 动作上应用隐藏过滤；其它动作原样返回（软隐藏边界）。"""
    if action != 'list':
        return queryset
    mode = visibility_mode(query_params)
    if mode == HIDDEN:
        return queryset.filter(is_hidden=True)
    if mode == ALL:
        return queryset
    return queryset.filter(is_hidden=False)
```

- [ ] **Step 4: 接线 `file_views.py`**

在该文件 import 区加：

```python
from apps.datafiles.visibility import apply_visibility
```

`get_queryset` 最后一行 `return queryset` 替换为（**必须在最后**，标签搜索的 OR 在它之上）：

```python
        # 隐藏过滤放最后：上方标签搜索用 OR 拼回的 queryset 会绕过先前条件，
        # 只有在这里收口才能保证隐藏行不被 OR 带回来（软隐藏，仅 list 生效）。
        return apply_visibility(queryset, self.request.query_params, self.action)
```

`options` 动作里 status 过滤之后加一行：

```python
        queryset = queryset.filter(is_hidden=False)
```

`product_codes` / `format_types` 两处 `DataFile.objects.filter(owner=request.user)` 各追加 `.filter(is_hidden=False)`；`list_tags` 里 `DataFile.objects.filter(owner=request.user)` 同样追加 `.filter(is_hidden=False)`。

- [ ] **Step 5: 仪表板默认回退**

`apps/dashboard/views.py` 未传 `file_id` 的分支改成：

```python
                datafile = DataFile.objects.filter(
                    owner=request.user, status='ready', is_hidden=False
                ).order_by('-created_at').first()
```

- [ ] **Step 6: 跑测试确认通过**

```bash
python manage.py test apps.datafiles.tests_hidden -v 1
```

Expected: `Ran 16 tests` / `OK`

- [ ] **Step 7: 行数红线检查**

```bash
wc -l apps/datafiles/views/file_views.py
cd frontend && npx vitest run test/unit/lineLimit.spec.ts
```

Expected: `file_views.py` ≤ 600（预计 593–595）；vitest `lineLimit` 全绿（0.6s 级）。

- [ ] **Step 8: 提交**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
git add apps/datafiles/visibility.py apps/datafiles/views/file_views.py apps/datafiles/tests_hidden.py apps/dashboard/views.py
git commit -m "feat(datafiles): 软隐藏过滤——列表默认排除、options/分面恒排除、仪表板默认跳过（T1）"
```

---

### Task 3: 前端类型/API + 隐藏状态筛选（工具栏 + FileListTab）

**Files:**
- Modify: `frontend/src/types/index.ts`（`DataFile` 接口）
- Modify: `frontend/src/api/datafiles.ts`（`ListFilesParams`、`datafilesApi.setHidden`）
- Modify: `frontend/src/pages/data/components/FileListToolbar.vue`
- Modify: `frontend/src/pages/data/components/FileListTab.vue`

**Interfaces:**
- Produces: `HiddenFilter = 'all' | 'visible' | 'hidden'`（从 `FileListToolbar.vue` 导出）；`datafilesApi.setHidden(id: number, hidden: boolean)`；`listFiles` 接受 `include_hidden` / `hidden_only`。

- [ ] **Step 1: 类型与 API**

`frontend/src/types/index.ts` 的 `DataFile` 接口在 `status: string` 后加：

```ts
  /** 软隐藏：只影响选文件候选（/files/options 恒排除）；文件管理列表仍可见 */
  is_hidden?: boolean
```

`frontend/src/api/datafiles.ts` 的 `ListFilesParams` 追加：

```ts
  /** 列表包含已隐藏（文件管理页「全部」档）；缺省只返回未隐藏 */
  include_hidden?: number
  /** 只返回已隐藏（优先于 include_hidden） */
  hidden_only?: number
```

`datafilesApi` 里 `setTags` 之前加：

```ts
  /** 切换隐藏（软隐藏：只影响选文件候选；PATCH 单字段） */
  setHidden(id: number, hidden: boolean) {
    return api.patch<DataFile>(`/files/${id}/`, { is_hidden: hidden })
  },
```

- [ ] **Step 2: 工具栏加筛选**

`frontend/src/pages/data/components/FileListToolbar.vue`：模板 `.toolbar-right` 内搜索框之前插入：

```vue
      <el-select
        class="hidden-filter"
        data-testid="hidden-filter"
        :model-value="hiddenFilter"
        @change="onHiddenFilterChange"
      >
        <el-option label="全部（含隐藏）" value="all" />
        <el-option label="未隐藏" value="visible" />
        <el-option label="已隐藏" value="hidden" />
      </el-select>
```

script：props 增 `hiddenFilter: HiddenFilter`、emits 增 `'hidden-filter-change': [value: HiddenFilter]`，并加：

```ts
export type HiddenFilter = 'all' | 'visible' | 'hidden'

function onHiddenFilterChange(value: HiddenFilter) {
  emit('hidden-filter-change', value)
}
```

样式加：

```css
.hidden-filter {
  width: 130px;
}
```

- [ ] **Step 3: FileListTab 接筛选状态**

`FileListTab.vue`：

1. 模板 `<FileListToolbar ...>` 增 `:hidden-filter="hiddenFilter"` 与 `@hidden-filter-change="onHiddenFilterChange"`。
2. import 改为 `import FileListToolbar, { type HiddenFilter } from './FileListToolbar.vue'`。
3. `currentSearch` 附近加状态与处理：

```ts
const hiddenFilter = ref<HiddenFilter>('all')

function onHiddenFilterChange(value: HiddenFilter) {
  hiddenFilter.value = value
  currentPage.value = 1
  tableRef.value?.clearSelection()
  loadFiles()
}
```

4. `loadFiles()` 的 `listFiles({...})` 参数对象里加：

```ts
      include_hidden: hiddenFilter.value === 'all' ? 1 : undefined,
      hidden_only: hiddenFilter.value === 'hidden' ? 1 : undefined,
```

- [ ] **Step 4: 构建验证**

```bash
cd frontend && npm run build
```

Expected: `vue-tsc -b` 无错误，`build complete in ...s`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/api/datafiles.ts frontend/src/pages/data/components/FileListToolbar.vue frontend/src/pages/data/components/FileListTab.vue
git commit -m "feat(data): 文件列表隐藏状态筛选与 setHidden API"
```

---

### Task 4: 表格徽标 + 隐藏/取消隐藏按钮 + 管理员页只读徽标

**Files:**
- Modify: `frontend/src/pages/data/components/FileListTable.vue`
- Modify: `frontend/src/pages/data/components/FileListTab.vue`（`onToggleHidden` 处理）
- Modify: `frontend/src/pages/admin/AdminFiles.vue`

**Interfaces:**
- Consumes: `datafilesApi.setHidden`（Task 3）
- Produces: `FileListTable` 新 emit `'toggle-hidden': [row: any]`

- [ ] **Step 1: 表格徽标与置灰**

`FileListTable.vue` 文件名单元格：`file-name` span 之后加：

```vue
            <el-tag
              v-if="row.is_hidden"
              size="small"
              type="info"
              effect="plain"
              class="hidden-badge"
            >已隐藏</el-tag>
```

`tableRowClassName` 改为：

```ts
function tableRowClassName({ row, rowIndex }: { row: any; rowIndex: number }) {
  const parity = rowIndex % 2 === 0 ? 'row-even' : 'row-odd'
  return row.is_hidden ? `${parity} row-hidden` : parity
}
```

样式追加：

```css
.hidden-badge {
  flex-shrink: 0;
}

/* 隐藏行置灰：只用 token，light/night 一致 */
:deep(.row-hidden) .file-name,
:deep(.row-hidden) .program-name-cell,
:deep(.row-hidden) .time-text,
:deep(.row-hidden) .size-badge {
  color: var(--text-2);
}
```

- [ ] **Step 2: 操作列按钮**

操作列 `width="140"` 改 `width="220"`，在「查看」与「删除」之间插入：

```vue
          <el-button size="small" type="warning" plain @click.stop="emit('toggle-hidden', row)">
            {{ row.is_hidden ? '取消隐藏' : '隐藏' }}
          </el-button>
```

emits 增：

```ts
  'toggle-hidden': [row: any]
```

- [ ] **Step 3: FileListTab 切换处理**

模板 `<FileListTable ...>` 增 `@toggle-hidden="onToggleHidden"`；script 加：

```ts
async function onToggleHidden(row: any) {
  const next = !row.is_hidden
  try {
    await datafilesApi.setHidden(row.id, next)
    ElMessage.success(next ? '文件已隐藏' : '已取消隐藏')
    await loadFiles()
  } catch {
    // 出声交给 axios 拦截器（页面不自造错误 toast 的既有约定）；失败不做乐观更新。
  }
}
```

- [ ] **Step 4: 管理员页只读可见**

`AdminFiles.vue`：

1. `loadFiles()` 的 `listFiles({...})` 增 `include_hidden: 1,`。
2. 文件名列改为模板 + 徽标（保持只读，无操作列）：

```vue
        <el-table-column prop="filename" label="文件名" min-width="280" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.filename }}
            <el-tag v-if="row.is_hidden" size="small" type="info" effect="plain">已隐藏</el-tag>
          </template>
        </el-table-column>
```

- [ ] **Step 5: 构建 + 行数检查 + 双主题目检**

```bash
cd frontend && npm run build
wc -l src/pages/data/components/FileListTable.vue src/pages/data/components/FileListTab.vue src/pages/data/components/FileListToolbar.vue src/pages/admin/AdminFiles.vue
cd frontend && npx vitest run test/unit/lineLimit.spec.ts
```

Expected: build 通过；四个文件均 ≤ 600；lineLimit 全绿。

浏览器目检（`npm run dev` 或 e2e preview 环境）：切 light / night 两套主题，确认「已隐藏」徽标与置灰行在两套下都可读、颜色来自 token 无硬编码。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/data/components/FileListTable.vue frontend/src/pages/data/components/FileListTab.vue frontend/src/pages/admin/AdminFiles.vue
git commit -m "feat(data): 隐藏徽标、置灰与单项切换；管理员页只读可见"
```

---

### Task 5: e2e 接线证明（file-hidden.spec.ts）

**Files:**
- Create: `frontend/e2e/data/file-hidden.spec.ts`

**Interfaces:**
- Consumes: `data-testid="hidden-filter"`（Task 3）、操作列「隐藏/取消隐藏」（Task 4）、分析页 `[data-file-picker="single"]` 契约。

- [ ] **Step 1: 写用例**

新建 `frontend/e2e/data/file-hidden.spec.ts`：

```ts
import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadFile, expectUploadSuccess } from '../helpers/upload'
import { filePicker } from '../helpers/params'

/**
 * 文件隐藏（软隐藏）接线证明：
 *  - 隐藏后文件列表仍可见（徽标 + 「已隐藏」筛选档）
 *  - 分析页下拉候选默认排除隐藏文件
 *  - 取消隐藏后候选恢复
 * 组合语义（include_hidden / hidden_only / 分面 / 仪表板回退）由 T1
 * `apps/datafiles/tests_hidden.py` 承载，这里只证明接线不证明组合。
 */
test.describe('文件隐藏（软隐藏）', { tag: ['@p1', '@data'] }, () => {
  test('隐藏：仅文件列表可见；分析页下拉排除；取消隐藏后恢复', async ({ page }) => {
    await gotoApp(page, '/data')

    const name = `e2e_hidden_${Date.now()}.csv`
    const tmpPath = path.join(os.tmpdir(), name)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)

      const row = page.locator('.content-section:visible .el-table .el-table__row')
        .filter({ hasText: name })
      await expect(row).toHaveCount(1, { timeout: 15_000 })

      // 隐藏：行保留 + 徽标
      await row.locator('button').filter({ hasText: '隐藏' }).click()
      await expect(row).toContainText('已隐藏', { timeout: 10_000 })

      // 隐藏状态筛选：未隐藏档看不到，已隐藏档能看到
      const filter = page.getByTestId('hidden-filter')
      await filter.click()
      await page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
        .filter({ hasText: '未隐藏' }).click()
      await expect(row).toHaveCount(0, { timeout: 10_000 })

      await filter.click()
      await page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
        .filter({ hasText: '已隐藏' }).click()
      await expect(row).toHaveCount(1, { timeout: 10_000 })

      // 分析页下拉：默认排除隐藏
      await gotoApp(page, '/analysis')
      const picker = filePicker(page, 'single')
      await expect(picker).toBeVisible({ timeout: 15_000 })
      await picker.click()
      await picker.locator('input').first().fill(name)
      await expect(
        page.locator('.el-select-dropdown:visible .el-select-dropdown__empty'),
      ).toHaveText('无匹配文件', { timeout: 10_000 })
      await page.keyboard.press('Escape')

      // 回文件列表取消隐藏
      await gotoApp(page, '/data')
      const row2 = page.locator('.content-section:visible .el-table .el-table__row')
        .filter({ hasText: name })
      await expect(row2).toContainText('已隐藏', { timeout: 15_000 })
      await row2.locator('button').filter({ hasText: '取消隐藏' }).click()
      await expect(row2).not.toContainText('已隐藏', { timeout: 10_000 })

      // 分析页下拉恢复
      await gotoApp(page, '/analysis')
      const picker2 = filePicker(page, 'single')
      await picker2.click()
      await picker2.locator('input').first().fill(name)
      await expect(
        page.locator('.el-select-dropdown:visible .el-select-dropdown__item:visible').first(),
      ).toContainText(name, { timeout: 10_000 })
      await page.keyboard.press('Escape')
    } finally {
      fs.rmSync(tmpPath, { force: true })
    }
  })
})
```

- [ ] **Step 2: 端口检查 + 单跑该 spec**

```bash
netstat -ano | grep LISTENING | grep -E ':(28100|23100)\b' || echo "ports free"
```

```bash
cd frontend && E2E_PORT=28100 E2E_FRONTEND_PORT=23100 E2E_SKIP_BUILD=1 npx playwright test e2e/data/file-hidden.spec.ts --project=P1 --workers=1
```

Expected: `1 passed`（含 setup 无失败；末尾汇总行 1/2 依 project setup 而定，判据是 `1 passed`）。

- [ ] **Step 3: lint:e2e**

```bash
cd frontend && npm run lint:e2e
```

Expected: `tsc -p tsconfig.e2e.json` 无输出。

- [ ] **Step 4: 提交**

```bash
git add frontend/e2e/data/file-hidden.spec.ts
git commit -m "test(e2e): 文件隐藏接线证明——列表可见、下拉排除、取消后恢复"
```

---

### Task 6: intro 书文件管理章节

**Files:**
- Modify: `docs/intro/guide/04-data.md`（`## 文件列表` 节）

- [ ] **Step 1: 补文案**

在 `docs/intro/guide/04-data.md` 的 `## 文件列表` 节末追加一段（保持该书既有语气）：

```markdown
文件的「隐藏」是**软隐藏**：隐藏后该文件不再出现在分析、仪表板、导出等选文件的下拉里，
但仍留在本页文件列表（带「已隐藏」徽标、置灰显示），可用工具栏「隐藏状态」筛选找回并
随时取消隐藏。批次数据、修复中心与存储统计不受影响——隐藏不会删除数据，磁盘占用照算。
```

- [ ] **Step 2: 构建与扫描**

```bash
npm run intro:build
node scripts/intro/check.mjs
```

Expected: 构建成功；`check.mjs` PASS（红线扫描无命中）。

- [ ] **Step 3: 提交**

```bash
git add docs/intro/guide/04-data.md
git commit -m "docs(intro): 文件列表补充隐藏（软隐藏）说明"
```

---

### Task 7: 收口门禁与台账

**Files:**
- Modify: `docs/tasks/todo.md`（勾选清单 + 门禁记录表）

- [ ] **Step 1: 前端单测 + 静态体检 + 构建**

```bash
cd frontend && npx vitest run
```

Expected: 全部 passed（含 `lineLimit.spec.ts`）。

```bash
cd frontend && npm run lint:e2e && npm run build
```

Expected: 均无错误。

- [ ] **Step 2: 后端全套**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
python manage.py test test.backend apps.accounts apps.analysis apps.batch_report apps.buyoff apps.common apps.dashboard apps.datafiles apps.export apps.gage apps.jobs apps.sftp apps.weight
```

Expected: `Ran N tests` / `OK (skipped=…)`；`grep -cE "^(FAIL|ERROR):"` = 0（判据取末尾行，不取 `$?`）。

- [ ] **Step 3: e2e 全量池（迁移命中 ⇒ 全量档）**

先核端口（池基址 21001/22001 各 60 个）：

```bash
netstat -ano | grep LISTENING | grep -E ':(210[0-9]{2}|220[0-9]{2})\b' || echo "pool ports free"
```

```bash
node scripts/e2e_pool.mjs --slots=4
```

Expected: 末尾汇总含 `结论` 行（MEASURED）；真红按 `RESULT:`/汇总判级，崩池轮 `VOID (infra)` 重跑才是结论。

- [ ] **Step 4: 更新台账**

`docs/tasks/todo.md` 的「文件隐藏」条目：勾选全部清单项，追加「门禁记录」表（命令 + 实测判据行，照批4/审查刀的表格形），以及已知非本批红（若出现）。

- [ ] **Step 5: push 前历史自检**

```bash
node scripts/prepush-history-check.mjs
```

Expected: 末行 `RESULT: PASS`。

- [ ] **Step 6: 提交收口**

```bash
git add docs/tasks/todo.md
git commit -m "docs(todo): 文件隐藏收口——门禁记录与勾选"
```

- [ ] **Step 7: 停下等用户点头**

报告分支状态、门禁结果与 diff stat；**不 push、不合并**。用户确认后再 FF 并入本地 master。
