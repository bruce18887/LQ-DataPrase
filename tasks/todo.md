# quest.txt 修复计划（2026-06-08）

> 调查方法：代码定位 + 后端数据实证。结论均有 file:line 依据。

## 背景与根因分析

### 课题1：单文件分析 ECharts 空白 + "Can't get DOM width or height"
**根因**：以下仪表盘组件未使用带「零尺寸容器保护」的 `initEchartsWhenReady`，
而是直接 `echarts.init()` 一次性初始化。数据到达后的 `nextTick` 时刻容器高度尚未确定
（`flex:1` / `height:calc(100%-42px)`），`clientHeight=0` → ECharts 报警并渲染空白，
后续布局撑开后也不会自动重绘。

受影响文件（直接 `echarts.init`）：
- `SiteYieldAnalysis.vue:80,129`（柱状图 + 仪表盘 2 图）
- `BinDistribution.vue:60`（饼图）
- `BinSiteCrossTable.vue:82`（柱状图）
- `CpkAnalysisSection.vue:76`
- `FailTestItemsSection.vue:47`

对照基准（已正确，可参照写法）：`batch/AggregatedBinChart.vue`、`batch/YieldTrendChart.vue`
用 `initEchartsWhenReady`；`YieldTrendChart.vue` 用 `useChart`。

### 课题2：SFTP 下载新批次后旧批次从「已导入批次」消失（数据管理 + 仪表盘批次良率）
**根因（前端表现层 bug，非数据丢失）**：
- 后端完全保留旧批次：`_register_file`(datafiles/views.py:108) 只新增；SFTP 各下载分支
  建独立目录与 `batch_name`，不删旧批次；`list_batches`(batch_report/views.py:64) `distinct()` 返回全部。
- 数据管理「已导入批次」：`FileListTab.vue:342` / `FileManager.vue:161` 的 `batchGroups`
  从**分页 20 条**(`/files/?ordering=-created_at` 第 1 页) 分组而来。新文件按时间挤满第 1 页，
  把旧批次挤到第 2 页之后 → 列表里看不到旧批次。
- DRF 全局 `PAGE_SIZE=20`（base.py:134）且未开放 `page_size` 参数，前端无法一次取全。
- 仪表盘批次良率：`BatchYieldTab.vue:293 loadBatches` 调 `list_batches`（全量 distinct），
  代码层面**不应**丢批次 → 以 e2e 验证；若确有问题再单独排查。

### 课题3：查看数据 / 导出工具 Tab 的「当前文件」横幅 → 改为下拉框
- `DataManagement.vue:53-78`：view / export 两 Tab 顶部是只读「当前文件」banner，
  改为 `el-select`，选择即切 `activeFileId`，与 `DataBrowserAgGrid`/`ExportToolsTab` 联动。

### 课题4：SFTP 浏览器每次点击卡顿（非重点 — 原因分析 + 轻微修复）
**根因**：`apps/sftp/views.py:34 _get_connection` 每个请求都新建 `paramiko.Transport`
完成完整 SSH 握手，用完即 `close()`。每次进目录(`navigateTo→listFiles`)都重连一次 →
网络再快也有握手延迟。socket 无法跨请求持久化（密码存于 cache，但连接不能）。

---

## 修复方案

### 课题1（核心）
5 个组件 `echarts.init(...)` → `initEchartsWhenReady(...)`：
- 每 chart 持 `handle: EchartsHandle | null`；render 内已就绪则 `handle.chart.setOption`，
  否则 `handle = initEchartsWhenReady(el, { option, reuse:true })`。
- `handleResize` → `handle?.chart?.resize()`；`onBeforeUnmount` → `handle?.dispose()`。
- 主题切换 watch 保留（重绘文字颜色）。

### 课题2（采用：复用 batch-dirs API，不动分页）
**要点**：`/batch-dirs/`(BatchDirListView, datafiles/views.py:433) 已磁盘走查返回**全部**批次目录，
不受分页影响。把数据管理「已导入批次」的数据源从「分页 files 分组」切到 batch-dirs。
1. 后端：扩展 `BatchDirListView` —— 对 `registered` 批次，额外带回该批次的文件清单
   `files:[{id, filename, tags}]`（来自 `DataFile.objects.filter(file_type='batch', batch_name=dir_name)`），
   供前端展开显示与点击选择。`registered`/`unregistered` 判定逻辑保持不变。
2. 前端：`FileListTab.vue` / `FileManager.vue` 的 `batchGroups` 改为来自 `batchDirs`
   （`registered===true` 的项），不再依赖分页 `files`。单文件表格分页逻辑保持不变。
   - 保留：批次内文件 el-tag 点击 → `file-selected`；删除批次按钮；activeFileId 高亮。
3. 仪表盘批次良率：`BatchYieldTab.vue` 已用全量 `list_batches`，仅 e2e 验证多批次完整列出。

### 课题3
- `DataManagement.vue`：view/export 两 banner → `el-select`(filterable, 空态提示)，
  `v-model`→`activeFileId`；维护 dark/light 两套主题。

### 课题4（轻微）
- 前端：`SftpBrowser.listFiles` 期间 loading + 防重复点击（体感优化），根因记入 review。
- 不引入后端连接池（socket 不可跨请求复用，改动过大，超范围）。

---

## 约束（CLAUDE.md）
- 单文件 ≤ 600 行：`FileListTab.vue`(979 行) 已超标，本次仅小幅加逻辑不再扩大。
- 测试放 `test/`；新增/改动功能补 e2e。
- 前端改动维护 dark + light 两套主题。

## TODO
- [x] 课题1：5 个图表组件迁移 initEchartsWhenReady（vue-tsc 0 error）
- [x] 课题2：batch-dirs API 扩展返回 files + 前端 batchGroups 改用 batch-dirs（后端实测两批次完整返回）
- [x] 课题3：view/export Tab「当前文件」改下拉框（el-select，dark/light 通用变量）
- [x] 课题4：SFTP listFiles loading 防抖（轻微）+ 根因记录（代码注释 + todo）
- [x] e2e：单文件图表渲染（dashboard 课题1 ✅）、批次保留（batch-dirs files ✅ 测试环境无注册批次故 skip）、当前文件下拉（data 课题3 ✅ 全 6 用例通过）
- [x] 验证 dark/light 主题（沿用既有 CSS 变量 + :root[data-theme="night"]，未引入硬编码色）
- [x] review 小结

## Review

### 改动文件
- 课题1（图表）：`SiteYieldAnalysis / BinDistribution / BinSiteCrossTable / CpkAnalysisSection / FailTestItemsSection`.vue
  —— 生 `echarts.init` → `initEchartsWhenReady`（buildXxxOption + handle 模式，onMounted 主动渲染 + resize 监听 + dispose）。
- 课题2（批次保留）：`apps/datafiles/views.py BatchDirListView` 扩展返回每批 `files[]`（含 id/filename/tags/format_type/row_count/col_count/program_name/status/created_at）；
  `FileListTab.vue` / `FileManager.vue` 的 `batchGroups` 改为来自 `batchDirs.filter(registered)`，与分页 files 解耦；`datafiles.ts` 类型 `BatchDirInfo.files: DataFile[]`。
- 课题3（当前文件下拉）：`DataManagement.vue` view/export 两 banner → `el-select`（filterable/clearable），删除只读 `activeFileName`/`selectedFileName`。
- 课题4（SFTP 卡顿，轻微）：`SftpBrowser.vue` listFiles 加 `listLoading` 防重复点击 + `SftpFileTable.vue` v-loading；根因（每请求重建 SSH 握手）记入代码注释。

### 验证
- vue-tsc --noEmit：0 error（我改动范围）。注：`vue-tsc -b` 全量 build 有大量**既有**报错（BoxPlotChart/HistogramTab/MultiLot 等前序会话未提交改动），与本次无关；我引入的 FileManager 型错误已修复。
- 后端：`manage.py test apps.datafiles apps.batch_report` → 50 passed。
- e2e：dashboard 9 passed/2 skip（课题1 图表 0 尺寸警告专项通过）；data 课题3 全 6 用例通过。
- 已知无关 flaky：data #4「删除后无残留」在测试 DB（86 文件 + 多个未导入 SFTP 目录）下于上传行检索处偶发超时——stash 还原原代码后同样失败，确认与本次改动无关。

### 后续可选
- `FileListTab.vue` 979 行已超 600 行约束（本次仅小改未扩大），建议后续拆分。
- SFTP 卡顿根因（每请求 SSH 握手）需后端连接保活/池化方可根治，超本次范围。
