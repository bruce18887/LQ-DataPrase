# SFTP 传输互斥/取消 + 文件相关性对比六项改进（2026-09-09）

> 来源：用户 6 项需求（SFTP 浏览器 ×2 + 数据管理文件相关性对比 ×4）。
> 4 项决策已逐项拍板（见 §1.2）。实现计划另出（writing-plans）。

## 1. 需求与决策

### 1.1 用户原文

1. SFTP 浏览器：短时间间隔连续点击两个文件的下载，直接报错甚至卡住。
2. SFTP 浏览器：下载时增加取消按钮。
3. 数据管理·文件相关性对比：超大文件直接卡死，疑似卡在自动加载对比序列的过程。
4. 同上：Limit Diff 规则加入另一种——B 的 limit 更紧但 diff 百分比不超过 x%（可设置）时不报错，否则报错。
5. 同上：Ignore No Limit 与 Ignore No Data 取消默认勾选。
6. 同上：limit 判定列加排序（点击把 fail 排前面）；导出 Excel 的 limit sheet 加筛选。

### 1.2 已拍板决策（2026-09-09，AskUserQuestion）

| 决策点 | 结论 |
|---|---|
| SFTP 并发策略 | **同时只允许一个下载**（有传输进行中时其它下载入口禁用；不做排队、不做后端锁） |
| 新规则语义 | **wider + 收紧容差**：B 不比 A 紧 → pass；B 收紧且每侧 diff% ≤ x% → pass；任一侧收紧超 x% → fail；任一侧缺 limit 或 A 侧限值为 0 → fail |
| x% 默认值 | **30%**（界面可改） |
| 大文件卡死现场 | **选完文件立刻卡**（渲染卡死为主因，后端瘦身一并做） |

## 2. 现状与根因（file:line 为 2026-09-09 HEAD 快照）

### 2.1 SFTP

- 前端无互斥：`singleFileDownload`（`frontend/src/pages/sftp/SftpBrowser.vue:313-349`）不检查
  `fileDownloading/dirDownloading` 即发起 SSE；第二次调用覆盖 `fileAbortCtrl`（:317）、
  `fileProgress`、`fileDoneTimer`。批量下载/批量解析（:405-436，非 SSE 的 axios POST）
  也无互斥。
- 后端按用户复用同一 paramiko 连接：`apps/sftp/pool.py:98-125`（per-process `_pool`，
  `get_connection(user_id)` 同 user 返回同一 `SFTPClient`；文件头注释自述 lock-free 前提
  是 sync worker 且 paramiko 非线程安全）。两个并发下载生成器共用同一 channel，
  `channel_timeout`（`apps/sftp/downloads.py:53-78`）互相 settimeout 抢 socket → 报错/卡死；
  任一方异常/GeneratorExit 都 `pool.invalidate`（:166-178）→ 另一个下载立刻死。
- 取消基础设施已备：`postSse` 支持 AbortSignal（`frontend/src/api/sftp.ts:210-249`，
  fetch + ReadableStream）；`downloadFileStream/downloadDirStream` 把 AbortError 静默吞掉
  （:163-167 / :194-198）；后端断开走 GeneratorExit → `remove_partial` 清半截文件 +
  invalidate（`apps/sftp/downloads.py:166-178`、目录版 :301-317；`apps/sftp/local_paths.py:37-50`），
  `test/backend/test_sftp_guards.py:132-196` 已覆盖。
- **取消路径缺陷**：AbortError 被 api 层吞掉后 `downloadFileStream` 正常 return →
  `singleFileDownload` 的 `catch` 不触发 → `fileDownloading` 永不复位（进度卡残留）。
  当前 abort 只在 `onBeforeUnmount` 触发所以从未暴露。
- 目录下载按钮不写 `downloadingRows`（目录行无进行中反馈），`SftpFileTable.vue:48-81`
  的 `:loading` 只挡同一行重复点击。

### 2.2 文件相关性对比

- 渲染卡死根因：`SerialSelector.vue:21` 用普通 `el-select` + `el-option v-for` 渲染
  **全量**公共序列（无关键字时 `filteredItems = options`，:77）；el-option 是完整 Vue
  组件，序列数上万时组件挂载即冻结主线程——序列响应一返回（`FileCorrelationSection.vue:126-134`
  watch 自动触发）就卡，与「选完文件立刻卡」吻合。
- 后端 serials 端点：`apps/analysis/views/file_correlation_views.py:141-188`
  `_load_file_correlation_pair` 每文件 `get_cached_parsed_file` 全量解析 + **整表
  `df.copy()`**（为保护 LRU 缓存不被 `__serial__` 注入污染，:167-168）。serials 端点
  只需要序列列，整表拷贝是纯浪费（大文件数百 MB 内存 + 秒级耗时）。
- Limit Diff 规则单一来源：`apps/analysis/services/file_correlation.py:121-134`
  `_evaluate_diff_rule`，现仅 `'zero'`/`'wider'`；白名单在
  `file_correlation_views.py:202-204`；规则文案 3 处
  （`FileCorrelationTable.vue:12`、`FileCorrelationLimitTable.vue:9`、
  `FileCorrelationSummary.vue:66`）；类型 `frontend/src/types/index.ts:162`。
- 默认值三处：前端 `FileCorrelationSection.vue:115-121`（`ignoreNoLimit/ignoreNoData: true`）、
  后端 `_bool_param(..., True)`（`file_correlation_views.py:234-235`）、
  `FileCorrelationConfig`（`file_correlation.py:47-48`）。
- 判定列无排序：`FileCorrelationLimitTable.vue:58-64`（el-table，判定 = `rowVerdict`
  = `lsl_fail||usl_fail`）；数据视图 ag-grid `defaultColDef sortable:false`
  （`FileCorrelationTable.vue:60-65`，**本次不动**）。
- Excel limit sheet 无筛选：`apps/export/excel_builders.py:154-245`（表头行 2、
  数据行 3+、冻结窗格、无 auto_filter）。`excelize.File.auto_filter(sheet, range_ref, [])`
  可用，先例 `apps/export/export_xlsx_optimized.py:329`。
- e2e：`frontend/e2e/data/file-correlation.spec.ts:66-67` 断言两个 Ignore 复选框
  **默认 is-checked**（需求 5 必须反转）。

## 3. 方案

### 3.1 SFTP 传输互斥（需求 1）

- `SftpBrowser.vue` 新增 `transferActive = computed(() => fileDownloading.value ||
  dirDownloading.value || batchDownloading.value || batchParsing.value)`。
- `SftpFileTable` 新增 prop `transferActive`：下载 / 下载并解析 / 目录下载三类按钮
  `:disabled="transferActive"`（保留现有 per-row `:loading` 作为活跃行反馈）。
- `SftpBatchActions` 新增 prop `transferActive`：批量下载 / 批量下载并解析按钮
  disabled（自身 loading 态保留）。
- 把批量入口纳入互斥的原因：批量端点与 SSE 下载共用同一条按用户复用的 paramiko
  连接，任意两类并发都会触发 2.1 的竞态。

### 3.2 SFTP 下载取消按钮（需求 2）

- `SftpDownloadProgress.vue`：`progress-info` 行右侧加**原位图标按钮**（`Close` 图标，
  tooltip「取消下载」，`aria-label`，样式全语义 token；不加文字按钮——用户 UI 偏好），
  emit `cancel`。两种 mode（file/dir）都渲染。
- `SftpBrowser.vue`：
  - `cancelFileDownload()`：`fileAbortCtrl?.abort()` + `fileDownloading.value = false`；
  - `cancelDirDownload()`：`dirAbortCtrl?.abort()` + `dirDownloading.value = false`；
  - 显式复位是必须的：AbortError 被 api 层吞掉后 catch 不触发（见 2.1 取消路径缺陷）；
  - 模板给两个进度卡分别接 `@cancel`。
- 后端零改动：abort → fetch 中断 → Django 生成器 GeneratorExit → 既有半截文件清理 +
  连接失效。
- e2e 契约：取消按钮 class `.dl-cancel-btn`（进度卡 `.download-progress-card` 内）。

### 3.3 序列选择器渲染截断 + serials 端点瘦身（需求 3）

前端（`SerialSelector.vue`）：

- 新增常量 `SERIAL_RENDER_CAP = 300`；`filteredItems` 改为
  `(kw ? matches : options).slice(0, SERIAL_RENDER_CAP)`（两个分支都截断）。
- footer 提示扩展：被截断时显示「仅显示前 300 项，可搜索或直接全选」（与现有
  「匹配 N 项，按 Enter 全选」并存，关键字分支优先）。
- 全选 / Enter 全选 / 清空语义**不变**：仍作用于完整 `matches/options` 集合，
  `MAX_SELECTED=200` 裁剪不变。
- 不换 `el-select-v2`：全库零使用先例，现有定制交互（filterMethod 接管、Enter 捕获
  全选、footer/empty 插槽、清过滤 poking 内部 input）迁移风险不成比例。

后端（`file_correlation_views.py` + `file_correlation.py`）：

- `file_correlation_serials` 端点不再走 `_load_file_correlation_pair` 的整表 copy：
  抽共享的文件解析循环为内部助手，serials 路径只对序列列做
  `pd.to_numeric(df[serial_col], errors='coerce')`（返回新 Series，**不污染 LRU 缓存
  原帧**），`list_common_serials` 签名改为接收两个 Series。
- `file_correlation` / `file_correlation_export` 两端点行为不变（仍需带 `__serial__`
  的整表 + copy）。
- 错误契约不变：`need_two_files` / `parse_failed` / `no_serial_column`。
- 首次解析大文件的耗时不可避免（parse cache 未命中时），期间前端已有 loading 态
  （`commonSerialsLoading` → el-select `:loading`）。

### 3.4 Limit Diff 新规则 `tight_pct`（需求 4）

- `FileCorrelationConfig` 加字段 `tight_pct: float = 30.0`（仅 `diff_rule='tight_pct'`
  时消费）。
- `_evaluate_diff_rule` 加分支（A=文件1/ATE，B=文件2/Bench）：
  - LSL 侧 pass ⟺ `lsl_a is not None and lsl_b is not None` 且
    (`lsl_b <= lsl_a` **或** `lsl_a != 0 且 (lsl_b − lsl_a)/|lsl_a|×100 ≤ tight_pct`)；
  - USL 侧 pass ⟺ 两侧非 None 且
    (`usl_b >= usl_a` **或** `usl_a != 0 且 (usl_a − usl_b)/|usl_a|×100 ≤ tight_pct`)；
  - 缺任一侧 limit 或 A 侧限值为 0（百分比无基准）→ fail；恰好 = x% 判过（≤）。
- `_parse_fc_config`：白名单 `('zero', 'wider', 'tight_pct')`；
  `tight_pct = get_param_float(request, 'tight_pct', 30.0)`，非法（None/<0）回退 30.0。
- 前端：
  - `types/index.ts`：`DiffRule = 'zero' | 'wider' | 'tight_pct'`；
    `FileCorrelationOptions` 加 `tightPct: number`。
  - `FileCorrelationControls.vue`：radio 加第三项「C：收紧 ≤ x%」（value=tight_pct）；
    `diffRule==='tight_pct'` 时旁边显示 `.fc-opt`「收紧容差 (%)」el-input-number
    （0–100、step 0.1、precision 1、宽 92px，同误差阈值控件形态），emit
    `update:tightPct`。
  - `FileCorrelationSection.vue`：options 加 `tightPct: 30`，透传 v-model。
  - `useFileCorrelation.buildPayload`：加 `tight_pct: opts.tightPct`。
  - 规则文案 3 处（Table/LimitTable/Summary 的内联 ternary）加第三分支
    「规则C：B 收紧 ≤ x% 允许」。
- rows 的 `lsl_fail/usl_fail` 与标红由后端统一判定，前端展示零改动。

### 3.5 Ignore No Limit / No Data 取消默认勾选（需求 5）

- 前端 `FileCorrelationSection.vue:119-120` → `false`。
- 后端 `_bool_param('ignore_no_limit'/'ignore_no_data', False)`（`file_correlation_views.py:234-235`）
  + `FileCorrelationConfig.ignore_no_limit/ignore_no_data = False`（`file_correlation.py:47-48`），
  保持前后端契约一致（直调 API 不传参的行为同步翻转）。
- 行为后果：无 limit / 所选序列上无数据的测试项默认**参与**对比（显示在结果中）。
- 文档同步：`file_correlation_views.py` 的请求体示例与 docstring（:61、:98、
  :194-197）及 `file_correlation.py` 模块 docstring/注释中「默认勾选 / checked /
  true」表述更新（实现时 grep `默认勾选|checked|ignore_no` 全量过一遍）。
- 存量后端测试审计：`apps/analysis/tests_file_correlation*.py` 中不传这两个参数
  直调 API 的用例，预期结果变化处显式传参或更新断言。

### 3.6 判定列排序 + Excel limit sheet 筛选（需求 6）

- `FileCorrelationLimitTable.vue` 判定列（:58-64）加 `sortable` +
  `:sort-method`（FAIL rank 0 / PASS rank 1，同判定次序按原 rows 序稳定）：
  点一次升序 FAIL 在前，再点反向，再点恢复原序。
- `excel_builders.py` Limit对比 sheet：数据行写完后
  `f.auto_filter(sheet_limit, f'A2:I{row_idx - 1}', [])`（row_idx > 3 时，即至少
  一行数据；表头行 2 为筛选行）。仅 Limit对比 sheet，测试值对比 sheet 不加。
- 数据视图 ag-grid 不动（用户语义「limit 判定」= Limit 对比视图判定列；
  如需数据视图判定列排序另开任务）。

## 4. 测试计划

### 4.1 后端（TDD）

- `apps/analysis/tests_file_correlation_service.py` 新增 `tight_pct` 规则用例：
  ① B 收紧且 diff% ≤ x → pass；② 超 x → fail；③ B 更宽 → pass；④ 恰好 = x → pass；
  ⑤ A 侧限值 0 → fail；⑥ 缺任一侧 limit → fail；⑦ LSL/USL 两侧独立判定；
  ⑧ x 传参生效（非默认 30）。
- `apps/analysis/tests_file_correlation.py`：API 契约（`diff_rule='tight_pct'` +
  `tight_pct` 透传；非法值回退）；默认值翻转后不传 ignore 参数的存量用例审计修正；
  serials 端点契约回归（Series 重构等价）。
- `apps/export`：Limit对比 sheet auto_filter 断言（对齐 `tests.py:117` 先例读回
  autoFilter 范围）。
- 门禁：`manage.py test apps.analysis apps.export`（串行）。

### 4.2 前端

- `npm run build`（vue-tsc -b + vite）。
- e2e `file-correlation.spec.ts`：
  - 面板用例：两个 Ignore 复选框断言反转为**未勾选**；规则 C radio 可见，选中后
    「收紧容差」输入出现且默认 30.0；
  - Limit 视图排序用例：分析后切 Limit 对比，点判定表头断言首行判定为 FAIL
    （前提：种子对能产生 FAIL 行；实现时先验证种子数据，产不出 FAIL 则换规则参数
    构造，仍不行则记为 skip 并在 todo 说明）；
- e2e `sftp.spec.ts`：
  - 互斥用例：开始 big.csv 下载后，另一文件/目录下载按钮 disabled；完成/取消后
    恢复 enabled（需 fixture 里有第二个可下载对象，实现时确认现有 paramiko 服务
    器文件清单，不足则造一个小文件）；
  - 取消用例：下载进行中点击 `.dl-cancel-btn` → 进度卡消失 → 按钮恢复 → 再次
    下载可正常完成（证明连接/状态干净）；断言不出现「已导入」toast（半截文件
    未入库由后端测试覆盖）。
- e2e 跑完释放端口；新增 UI 全语义 token，双主题无新增字面色。

## 5. 范围外（本次不做）

- 后端 per-user 下载锁 / 排队（用户已选「同时只允许一个」）。
- 下载进行中禁用目录导航（list 与下载共用连接的竞态**保留现状**，仅文档记录；
  如实际遇到浏览期间下载报错再议）。
- 批量下载/解析的取消（非 SSE，无进度卡；互斥只做禁用）。
- `el-select-v2` 虚拟化迁移。
- 数据视图（ag-grid）判定列排序。
- `apps/export` 其它 sheet 的 auto_filter。

## 6. 已知边界与风险

- 渲染截断 300：下拉只能直接浏览前 300 颗序列，更深的靠搜索（Enter 全选）或全选；
  提示文案明示。典型真实序列数远小于 300 时无感知。
- 后端默认值翻转属契约变更：任何绕过 UI 直调 API 且不传 ignore 参数的调用方
  行为会变（前端始终显式传参，不受影响）。
- 取消依赖后端 GeneratorExit 及时触发：SSE 事件流在传输活跃期 ≥10 事件/秒，
  abort 后秒级生效；若后端恰好阻塞在无事件的长读取，取消延迟到下一个事件边界。
- `SftpBrowser.vue` 现 504 行，本批预计 +25 行内（<600 上限）；
  `file_correlation_views.py` 236 行、`SerialSelector.vue` 170 行均余量充足。
