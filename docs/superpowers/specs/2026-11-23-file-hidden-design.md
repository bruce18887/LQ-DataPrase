# 文件「隐藏」功能设计（2026-11-23）

## 1. 背景与需求

数据文件积累后，用户希望把一批「当前用不到」的文件从各类选文件下拉里降噪，但仍保留在文件管理列表里可查、可恢复。

需求原文两条：

1. 有时想把某些文件隐藏起来——**只能在文件列表看到，其它选择数据的地方看不到**。
2. 未来数据文件高达几百个时，文件列表下拉框会不会很难查找？

**需求 2 结论：现状已解决，不开发。** 所有文件下拉走统一组件
`frontend/src/components/common/FileSelect.vue`（`el-select-v2` + `filterable` 本地过滤
+ 命中高亮 + 固定行高虚拟滚动），后端候选端 `/files/options/` 默认上限 5000 条、
仅标量列；几百个文件在容量和可查性上都在现设计内。已有
`frontend/e2e/analysis/file-select.spec.ts` 钉住搜索/高亮/虚拟窗口行为。
本 spec 只覆盖需求 1。

## 2. 已拍板的产品口径

| 决策点 | 结论 |
|---|---|
| 隐藏语义 | **软隐藏**：只影响「选择文件的候选列表」；已选中/在途使用的文件不拦截，直接 API 访问不拦。 |
| 生效范围 | **选择面排除**：`/files/` 与 `/files/options/` 默认排除隐藏；文件管理页显式看全部。批次数据页、修复中心、批次报表、存储统计等数据管理面**不受影响**（隐藏 ≠ 数据消失，空间照算）。 |
| 列表页 UI | 操作列单项「隐藏 / 取消隐藏」+ 文件名旁「已隐藏」徽标 + 行置灰；工具栏加「隐藏状态」筛选（**全部（默认）/ 未隐藏 / 已隐藏**）。不做多选批量隐藏（YAGNI，后续需要再加）。 |
| 存储方案 | `DataFile.is_hidden` 布尔字段 + 一笔迁移。不用保留字标签（与用户标签体系打架），不用枚举（当前仅二值）。 |

## 3. 后端设计

### 3.1 模型与迁移

- `apps/datafiles/models.py` 新增：
  `is_hidden = models.BooleanField(default=False, db_index=True)`。
- 新迁移 `apps/datafiles/migrations/0007_datafile_is_hidden.py`（AddField，样板参照
  `0005_datafile_tags.py`）。
- 上传/解析流水线**不写这个字段**（默认 False）。隐藏与 `status` 正交：解析失败的文件同样可隐藏/恢复。

### 3.2 序列化器

- `DataFileSerializer`（写口/详情）：`fields` 增加 `'is_hidden'`（不加进 `read_only_fields`，
  使 `PATCH /files/{id}/ {"is_hidden": true}` 可用）。
- `DataFileListSerializer`：`fields` 增加 `'is_hidden'`（列表要渲染徽标）。

### 3.3 列表与候选接口行为

| 端点 | 行为 |
|---|---|
| `GET /files/`（`action == 'list'`） | 默认 `filter(is_hidden=False)`；`?include_hidden=1` 不滤；`?hidden_only=1` 只返回隐藏（隐含包含）。参数组合：`hidden_only` 优先于 `include_hidden`。仅作用于 `list`——`retrieve/update/partial_update/destroy` 与按 id 取数一律不受限（软隐藏根基；否则对隐藏行 PATCH 取消隐藏会 404）。 |
| `GET /files/options/` | 恒定 `filter(is_hidden=False)`（含 `?include_error=1` 分支）。**values() 键集不变**，`test/backend/test_files_options_api.py` 的键集契约断言保持绿。 |
| `product_codes` / `format_types` / `list_tags` | 排除隐藏文件贡献的取值，避免分面出现「只有隐藏文件才有」的选项导致筛出空列表。 |
| 仪表板默认文件回退 | `apps/dashboard/views.py` 未传 `file_id` 时改取 `filter(owner, status='ready', is_hidden=False)`；显式 `file_id` 不拦。 |
| `PATCH /api/v1/files/{id}/` | 切换隐藏的唯一入口；权限沿用既有 owner 校验（他人文件 404）。 |

### 3.4 代码落点（含 600 行红线）

`apps/datafiles/views/file_views.py` 当前 **591 行**（上限 600，机械判据
`frontend/test/unit/lineLimit.spec.ts`）。可见性参数解析抽到**新模块**
`apps/datafiles/visibility.py`（纯函数，如
`apply_visibility(queryset, query_params, action) -> queryset`），ViewSet 内只加
import + 单行调用（+2 行，预计 593–595 行）。`options` / 分面端点各加一行过滤。
**任何后续追加都要先回到本红线复核，不得突破 600。**

### 3.5 明确不改的后端

- `apps/datafiles/lookup.py`、analysis/jobs 按 id 取数与提交：不检查隐藏（软隐藏）。
- 批次聚合（`apps/batch_report/*`）、`batch-dirs`、重复组（`_duplicate_files.py`）、
  存储统计（`storage_usage.py`）：全部照旧包含隐藏文件。

## 4. 前端设计

### 4.1 类型与 API

- `frontend/src/types/index.ts`：`DataFile` 增加 `is_hidden: boolean`。
- `frontend/src/api/datafiles.ts`：
  - `listFiles` 参数增加 `include_hidden?: boolean` / `hidden_only?: boolean`（序列化为 `'1'`）。
  - 新增 `setFileHidden(id: number, hidden: boolean)` → `PATCH /files/{id}/ {is_hidden: hidden}`，
    返回更新后的文件。

### 4.2 文件管理页

- `FileListTab.vue`：新增 `hiddenFilter: 'all' | 'visible' | 'hidden'`（默认 `'all'`）；
  映射：`all → include_hidden=1`，`visible → 默认`，`hidden → hidden_only=1`；
  切换时重置到第 1 页并复用现有加载函数（与表头筛选、排序、搜索正交）。
- `FileListToolbar.vue`：工具栏加「隐藏状态」`el-select`（全部/未隐藏/已隐藏），
  透出 change 事件；双主题样式用 token。
- `FileListTable.vue`：
  - 文件名单元格：`row.is_hidden` 时加 `el-tag`（文案「已隐藏」，`type="info"` `effect="plain"`）。
  - 行置灰：复用 `tableRowClassName`，新增 `row-hidden` 类（opacity/文字色用
    `var(--text-2)` 一类 token，light/dark 两套都验）。
  - 操作列：新增「隐藏 / 取消隐藏」`el-button`（文案随 `row.is_hidden` 切换），
    emit `toggle-hidden`；列宽 140 → 210。
- 成功后 `ElMessage.success` 并就地刷新当前页（保持筛选/页码）。
- `DataManagement.vue`：`/files/?page_size=9999` 全量拉取**不加参数**（默认排除隐藏），
  导出/对比/Gage/Buyoff 下拉自动干净，无需逐处改。文件列表 tab 数据来自
  `FileListTab` 自己的分页请求（`FileListTab.vue:198`），二者互相独立。
- `AdminFiles.vue`：请求带 `include_hidden=1`，隐藏文件加徽标；**只读**，无切换按钮。

### 4.3 明确不改的前端

- 分析页 4 个 tab、仪表板、`ActiveFileBanner`、`FileCorrelationControls`、
  `GageSummary`、`BuyoffForm`：零改动，靠 options/全量列表默认排除。
- 已选中/记忆中的文件被隐藏：不拦截在途使用；刷新后该文件不在候选中，
  由现有「记忆文件不在列表」逻辑回落到空态，不新增特殊提示。
- 已知边角：文件列表行点击可打开隐藏文件进入「查看数据」（行点击链路
  `FileListTab.onRowClick` 不经过候选列表），此时导出工具顶部 `ActiveFileBanner`
  的 `FileSelect` 因候选已排除隐藏而无法解析标签（下拉显示空白，数据仍可查看）。
  属软隐藏的预期形态，不为 banner 单独开 `include_hidden` 口子；若用户反馈困扰，
  另立批次处理。

## 5. 边界与非目标

- 不做硬性禁用/归档/回收站；不做隐藏原因备注、隐藏时间审计。
- 不做多选批量隐藏（后续有需要再立批次）。
- 不做服务端远程搜索的下拉改造（几百文件在现上限内；5000 上限为已知边界，超限另立需求）。
- 隐藏对「查看数据」banner 行点击入口不拦（软隐藏）；导出等选择面已由候选排除。

## 6. 测试计划（按 `docs/reference/testing-gates.md` 先选层）

### T1 后端契约（主承载）

新文件 `apps/datafiles/tests_hidden.py`，**不改** `apps/datafiles/tests.py`
（后者按精确行数冻结在 600 行豁免里，多一行即红）。

覆盖用例：

1. 默认 `GET /files/` 不含隐藏行；`include_hidden=1` 含；`hidden_only=1` 只含隐藏。
2. `GET /files/options/` 默认与 `include_error=1` 分支都不含隐藏行。
3. `product_codes` / `format_types` / `list_tags` 不返回隐藏文件独有的取值。
4. `PATCH /files/{id}/ {"is_hidden": true|false}` 生效并可回读；他人文件 404。
5. 软隐藏边界：隐藏后 `GET /files/{id}/` 仍 200；`DELETE` 仍可用；按 id 的分析/导出取数不拦（至少一条分析端点冒烟）。
6. 仪表板未传 `file_id` 时默认回退不选隐藏文件；显式 `file_id` 指向隐藏文件仍可用。
7. 新上传文件 `is_hidden=False`。

### T2 前端纯函数

本设计无新增纯函数判据，不新增 vitest。若实现中抽出参数映射纯函数（如
`visibilityParams('hidden')`），补 `frontend/test/unit/` 对应用例（入参→出参）。

### T3 浏览器（一条接线证明，组合归 T1）

新 spec `frontend/e2e/data/file-hidden.spec.ts`，单条用例：

文件管理页隐藏文件 → 该行仍在列表且有「已隐藏」徽标 → 分析页下拉不含该文件 →
回文件管理页取消隐藏 → 分析页下拉恢复出现。

### 门禁

- 迁移文件命中 `*/*/migrations/*.py` → affected 判据按测试门禁 §3 规则 2 **升全量档**。
- 收口：`node scripts/e2e_pool.mjs --slots=4` + 后端全套；push 前
  `node scripts/prepush-history-check.mjs`。
- 每批 commit 前：`cd frontend && npm run test:e2e:affected`；「NO AFFECTED TESTS」不算绿灯。

## 7. 文档维护

- 文件管理页新增按钮/筛选与判定口径变化 → 按 `.claude/CLAUDE.md`
  「产品介绍书定期维护」触发条件 ②，批次收口时同步 `docs/intro/` 文件管理章节
  （隐藏/恢复操作与筛选说明），`npm run intro:build` + `node scripts/intro/check.mjs` 必须 PASS。
- 两条「行数冻结」事实（`file_views.py` 593–595、`tests.py` 不可新增）在实现中随时复核，
  突破即停并重新规划。

## 8. 交付顺序

1. 本 spec 入库 → 用户复核。
2. `writing-plans` 出实施计划（写入 `docs/tasks/todo.md` 勾选清单）→ 用户 check-in。
3. 后端模型/迁移/接口 → T1 测试 → 前端 UI → T3 用例 → intro 书 → 全量门禁 → 提交。
