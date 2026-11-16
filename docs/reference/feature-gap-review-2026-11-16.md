# 五项问答核查报告（2026-11-16）

**范围**：用户提出的 5 个问题 —— ① 管理员跨用户文件管理 ② 服务器过载时的前端提示
③ 参数分布图导出进度百分比 ④ 服务器生成物的清理 ⑤ 序列分布圈选后联动直方子图。

**方法**：纯静态代码核查（主代理 + 5 路定向检索），**未做运行时验证**，未启动任何服务。
基线 = 分支 `feature/batch4a-e2e-dup-split`，HEAD `6e70a33`。文中行号以该提交为准。
负命题（「没有 X」）按多种拼写各自复核过，复核命令见 §7。

**为什么落在 `docs/reference/`**：这份报告里的判断（哪些是既有能力、哪个洞是 knowingly 留着）
以后会有人照着做，按项目约定这类内容要住在被跟踪文件里。

---

## 0. 结论一览

| # | 问题 | 定性 | 现状一句话 | 档位 |
|---|------|------|-----------|------|
| 1 | 管理员看不到/管不了每个用户的文件 | **净缺口**（设计如此，非 bug） | 全仓读路径无条件 `owner=request.user`，管理员无例外 | 一批（新功能） |
| 2 | 服务器处理不过来的前端提示 | **半有**：只有内存打爆那一句 | 503 `out_of_memory` 有话术；CPU/排队过载**完全无提示**，准入层从未落地 | 一批（设计文档批 2） |
| 3 | 参数分布图导出加进度条百分比 | **已存在**，但 PPT 那一支没有 | xlsx 已有 `JobProgressChip` 百分比条；pptx 只 33%→100% 跳两下 | 一处小改 |
| 4 | 服务器生成物有没有清理 | **前提要纠正 + 半个缺口** | gage/标红不落盘；作业产物有 `prune_jobs` 但**无调度器调用** | 运维配置 + 待拍板 |
| 5 | serial 圈选高亮后再开直方子图 | **后半句已实现**，只差一个菜单项 | 子集面板整套管线可复用，serial 图右键缺「打开子集直方图」 | 一处小改 |

**两条被本次核查否证的前提**（下次别再当事实引用）：

- ~~「服务器生成了 gage report 文件、标红文件，需要清理」~~ → 二者都不落盘，见 §4.1。
- ~~「参数分布图导出没有进度提示」~~ → xlsx 分支早有百分比条，缺的是 pptx 分支，见 §3.2。

---

## 1. 管理员看不到每个用户下的文件

### 1.1 现状：文件域按 owner 硬隔离，无角色分支

| 证据位置 | 行为 |
|---|---|
| `apps/datafiles/views/file_views.py:114` | `DataFileViewSet.get_queryset()` = `filter(owner=self.request.user)` |
| `apps/datafiles/views/file_views.py:223` | `bulk_delete` 同口径，注释写明「Owner-scoped: only the requesting user's files are ever touched」 |
| `apps/datafiles/views/file_views.py:246,258,277` | `product_codes` / `format_types` / `options` 三个下拉数据源全部 owner 过滤 |
| `apps/datafiles/lookup.py:64` | `owned_files_by_pk()` —— 各域批量取文件的统一 owner 口径 |
| `apps/datafiles/views/browse_views.py:58,138` | 激活、查看数据均 `get_object_or_404(..., owner=request.user)` |
| `apps/datafiles/views/batch_views.py:38,150,210,250` | 批次目录列表/导入/删除/子批删除，路径与行都按当前用户算 |
| `apps/jobs/views.py:125` | 提交导出作业也是 `get_object_or_404(DataFile, pk=..., owner=request.user)` |

`apps/datafiles/views/_duplicate_files.py` 的注释直接点明这条 owner 过滤就是越权防线。
全仓文件域**唯一**的角色分支是一致性检查的写动作（`browse_views.py:339-361`）：
删除类动作要求 `data_delete`（仅管理员），修复类要求 `data_repair_mutate`（管理员 + 普通用户）——
但它检查的范围仍然只有 `owner=user` 那些行，即「管理员可以删自己的孤儿数据」，不是「管理员可以看别人的」。

### 1.2 管理员现在有什么 / 没有什么

权限表 `apps/accounts/permissions.py:7-13` 全文只有 5 个 feature：

```
user_management / system_config / audit_log_view → administrator
data_delete                → administrator
data_repair_mutate         → administrator, user
```

**没有「跨用户读取数据」这个 feature**，所以这不是漏接，是模型里就没这个概念。

- **有**：账号管理页 `/admin/users`（增删改用户、角色、锁定，`apps/accounts/views.py` 的 `UserManagementViewSet`
  确实对管理员返回全部用户）；审计页 `/admin/audit`；`GET /api/v1/metrics/`（仅管理员）；
  `GET /api/v1/files/usage/`（**只统计当前用户自己**的占用，`apps/datafiles/storage_usage.py:64-78`）。
- **没有**：任何「选一个用户 → 看他的文件列表 → 代他删除/下载/重命名」的产品入口。
  前端路由里 `requiresAdmin` 只有那两条（`frontend/src/router/index.ts:89,102`，守卫在 `:197`）。
- **半个**：Django 后台 `/admin/` 注册了 `DataFile`（`apps/datafiles/admin.py:6-14`，可按 `owner__username` 搜索）。
  但 `config/urls.py:18-19` 只把 `/admin/users`、`/admin/audit` 让给 SPA，其余 `/admin/**` 归 Django admin。
  那是运维界面：非产品外观、无主题、无审计留痕、能做的操作与业务语义脱节，**不能当作本需求的答复**。

### 1.3 如果要做，落点在哪

这不是「加个筛选参数」的量级，因为 owner 过滤散在 7 个视图 + 1 个 lookup 门面里，
而且路径隔离按 `_user_upload_dir(request.user, ...)` 走。要动的面：

1. **权限模型**：`FEATURE_PERMISSIONS` 加一个 feature（如 `data_view_all`），别用 `role == 'administrator'`
   硬编码 —— 该文件头注已立此规矩（「视图里不许再硬编码角色字符串做门禁」）。
2. **读侧**：`get_queryset` 引入「以谁的身份看」的显式参数并过闸；`lookup.owned_files_by_pk` 的调用方
   （analysis / batch_report / buyoff / gage / dashboard）要决定是逐个放开还是维持隔离。**默认建议维持隔离**，
   只放开文件管理页，否则一个管理员点开别人的文件就把跨域读写面全开了。
3. **写侧**：`_user_upload_dir` 拼的是用户名，管理员代删需要显式指定目标用户目录，
   而 `storage_usage.py:64-74` 的注释已经点名老入口 `_helpers.py:172` **没挡用户名里的 `..`**
   （Django 默认 `UnicodeUsernameValidator` 接受点号）。这条在放开跨用户操作之前必须先补，
   否则「管理员以任意用户名拼路径」= 任意目录读写。
4. **审计**：代删他人数据属高危动作，应写 `AuditEvent`（`apps/accounts/models.py:122-142` 已有该表与
   actor/target 双快照设计，正是为此准备的）。
5. **UI**：新增 `/admin/files`（复用 `requiresAdmin` 守卫 + 侧栏菜单项），双主题。

**待拍板**：管理员要的是「只读可见（知道谁占了多少空间/有什么文件）」，
还是「可代为管理（删/改/下载）」？两者工作量差一个量级，风险也差一个量级。

---

## 2. 服务器处理不过来时前端的提示

### 2.1 三层分开看

**A. 内存打爆 —— 有专门话术，唯一一条**

`apps/common/exceptions.py:118-152`：任何视图抛 `MemoryError` → 503，
信封 `code='out_of_memory'`、`message='服务器内存不足，请关闭其他任务后重试'`、`Retry-After: 5`，
副作用是尽力清解析缓存 + `record_oom`。前端 `frontend/src/utils/error.ts:67-72` 的优先级是
`message → detail → code 查表`，所以用户看到的红条就是后端那句原文。
注意 `out_of_memory` **不在** `error.ts:15-52` 的 `ERROR_CODE_MAP` 里 —— 全靠后端带 message，
哪天后端改成只回 code，前端会退化成显示裸串 `out_of_memory`。

**B. CPU / 排队过载 —— 完全无提示，这一层从未实现**

- 内存水位算得出、没人据此拒绝请求：`apps/common/memory.py:91-101` 的 `level()` 返回 normal/soft/hard，
  唯一消费者是 `apps/common/metrics.py:173` → `GET /api/v1/metrics/`（运维只读接口）。**没有任何视图看它**。
- 设计文档里的准入层（`apps/common/admission.py`、`HeavyActionMixin`、`ServerBusy`、`server_busy`、
  前端 `degraded`/`繁忙`）**全仓零命中**，只活在
  `docs/superpowers/specs|plans/2026-10-21-backend-memory-governance*`。
- 速率限制形同虚设：`exceptions.py:42` 有 `Throttled` → 429「请求过于频繁，请稍后再试」，
  但 `config/settings/base.py:224-239` 明确「只配速率表、刻意不装 `DEFAULT_THROTTLE_CLASSES`」，
  理由是轮询路径多 + e2e 单 IP 打 376 例。所以 429 在现网不可达。
- 作业池没有排队上限：`apps/jobs/executor.py:46` `MAX_POOL_WORKERS = min(4, max(2, cpu//2))`，
  超出并发的工作项只是排在 `ProcessPoolExecutor` 的 call queue 里等（容量 4+1=5，
  见 `apps/jobs/views.py:283-291` 注释）。第 6 条作业的状态是 `running`（库里「排队中」就是 running），
  前端进度条显示 0%，**没有任何一句「前面还有 N 个作业」**。

**C. 超时 —— 有话术，但前后端口径错位**

| 侧 | 事实 | 证据 |
|---|---|---|
| 后端 | 按 kind 给超时：excel / html_report 30 分、batch_charts 60 分、sftp_download 2 小时 | `apps/jobs/executor.py:57-59` |
| 后端 | 看门狗每 5s 一轮，判死写库「超时 N 分钟，已中止」 | `apps/jobs/monitor.py:38,77-79` |
| 前端 | 轮询 1s 起、连续 3 次无变化降 2s、**上限 5 分钟** | `frontend/src/composables/jobPolling.ts:10-16` |
| 前端 | 到上限 → info 蓝条「导出仍在进行，本页已停止等待；作业没有被取消，可稍后重新导出」 | `jobPolling.ts:103,116-121` |
| 前端 | 普通请求 30s 超时 → 「无法连接服务器，请检查网络」，与断网同一句话 | `api/index.ts:52-58`、`utils/error.ts:79` |

**错位点**：后端图表作业允许跑 60 分钟，前端 5 分钟就停止等待。批量分布图一旦跑过 5 分钟，
用户看到的就是那句 info，之后作业真的跑完了他也不知道。

### 2.2 两条静默路径（用户全程无感）

1. **崩池/池建不起来 → 同步降级**：`apps/jobs/views.py:201-248`。`executor_available()` 只判
   「池建不建得起来」；`PoolBroken` 时视图丢掉作业号直接同步跑完，回 `200 + 文件流 + X-Job-Fallback: 1`。
   这条路对用户完全无提示（这是刻意的：行为退回作业化之前）。**但它绕过了进度上报**
   ——`useJobExport.ts:83-92` 收到 sync-fallback 直接把进度从 0 拉到 100 然后下载。
2. **轮询本身取不到状态**：`jobPolling.ts:72-74` 判 failed，文案「取不到作业状态」，
   再经 `jobFailureView` 弹红条。后端此刻可能还在正常跑。

### 2.3 如果要做

按既有设计文档的批 2 走（准入 + 可见降级 + 前端 503/繁忙文案），但要先解决两个前置：

- **`evict_parse_cache_to` 是死代码**（产品侧零调用），而批 2 的 hard 分支依赖这个 relief 入口。
- **前端 5 分钟上限必须与后端 kind 超时对齐**，否则加了「排队中」提示也还是会在排队中途停止等待。

最小可用的一刀，其实不是准入而是**把已有事实说出来**：作业 payload 里带上「前面还有几个在排队」+
把 `POLL_MAX_MS` 提到与 kind 超时同档（或到点后不报 info 而改成「继续等待 / 停止等待」的显式选择）。

---

## 3. 参数分布图导出的进度条百分比

### 3.1 已经有百分比了

「批量导出参数分布图」这个入口只有一个，在数据管理页（`frontend/src/pages/data/ExportToolsTab.vue:7` 卡片标题）。
它已经把进度条接上了：

- UI：`frontend/src/pages/data/components/export/ExportActions.vue:33` → `<JobProgressChip :percent="batchProgress" :active="batchActive" />`
- 组件：`frontend/src/components/common/JobProgressChip.vue:27-42` —— 一条 `el-progress` + 右侧 `{{ clamped }}%` 数字，
  `role="status"` + `aria-label`，样式只认 token，双主题由 design-tokens 切换。
- 数据流：`useExport.ts:18,69-70` 把 `job.progress` / `job.exporting` 透出 → `ExportToolsTab.vue:92` 接住。
- 全链路：提交 → 轮询 `GET /jobs/<id>/` → `pollDecision` 读 `job.progress` → `useJobExport.ts:126-129` 写回 `progress`。
- 同源上报：`export_batch_charts` 的 xlsx 分支每装配完一个参数回调一次，
  `apps/jobs/runner.py:159-169` 把 `done/total` 折成 1–100 写进 `.progress` 侧车；
  `apps/export/export_batch_charts_xlsx.py:544-549` 是回调点，且**多属参数只报一次**（否则进度会超过总数）。

同类对照：`export_excel`（`DataBrowserAgGrid.vue:17`）与 `export_html_report`（`ExportFooter.vue:6`）
也用同一个 `JobProgressChip`，但它们只有 `1/3 → 2/3 → 3/3` 三段（`runner.py:120-127,185-195`），
粒度比分布图导出更粗。

### 3.2 真实短板是这两条

**① pptx 分支没有逐参数进度** —— `apps/jobs/runner.py:154-157` 调
`build_batch_charts_pptx(...)` 时**不传 `progress_cb`**，而该函数签名里也确实没有这个参数
（`apps/export/export_ppt.py:26-31`）。所以选 PPT 导出时，进度条只会：
`write_progress(1,3)=33%` → 中间**完全静止** → `write_progress(3,3)=100%`。
要补就是在 pptx 的逐参数循环里加同款回调（`_cb` 已在 runner 侧备好，传进去即可）。

**② 条最多 5 秒才动一次** —— 侧车文件由看门狗线程每 `MONITOR_INTERVAL = 5.0` 秒读一次才回写
`Job.progress`（`apps/jobs/monitor.py:38`、`:118-136`），前端 1–2s 轮询只是反复拿同一个值。
参数少但单图很慢（大 dpi / 多工位）的导出，会看到长时间停在同一个数字。
另注：`0 < percent < 100` 且 `exclude(progress__gte=percent)` —— **只推进不回退**，这是刻意的
（worker 崩在半路时读到的是最后已知值）。

还有一条不改代码就会误判的：**渲染阶段本身不上报进度**。xlsx 的回调点在「装配完一个参数」，
而耗时大头在 matplotlib 渲染。`workers=1` 是硬要求（作业已在常驻池子进程里，
再开 8 渲染池 = 4×8=32 个 Python 进程，`export_batch_charts_xlsx.py:280-287`），
串行渲染下「装配完第 k 个」与「渲染完第 k 个」是同一时刻，所以百分比在 xlsx 上是准的；
但若哪天改回并行渲染，进度就会退化成批次结束才跳。

**结论**：这条需求 ≈「给 pptx 补 `progress_cb`」。5s 一跳是否要改成 worker 直写 DB 之外的通道，
属性能取向，先不动。

---

## 4. 服务器生成物的清理

### 4.1 先纠正前提：gage report 与标红文件不落盘

| 类别 | 落盘？ | 证据 |
|---|---|---|
| gage 汇总报告 | **否** | `apps/gage/views.py:106-115`：builder 返回 bytes，直接 `FileResponse(io.BytesIO(...))`。`gage_legacy_builder.py:104-118` 用 `NamedTemporaryFile(delete=False)` 写，`finally` 里释放删除 |
| buyoff 报告 | **否** | `apps/buyoff/views.py:134-139`：`save_excelize(f)` 回内存 buffer 后返回 |
| 「标红文件」 | **否** | 标红是 xlsx 里的**单元格填充色**，不是独立文件：`apps/export/excelize_helpers.py:16-25`（红/橙调色板）、`:134,165`（红样式函数）、`apps/export/excel_builders.py:191-222`（按 diff 规则逐格上色）。`excelize_helpers.py:21` 的 `os.unlink(tmp_path)` 就是它唯一的落盘痕迹 |
| 内嵌直方图 PNG | **否** | `charts.py:382`、`export_ppt.py:144`、`report_charts.py:28` 全部 savefig 进 `io.BytesIO` |
| matplotlib 配置目录 | 临时，`atexit` 清 | `apps/export/chart_workers.py:23-25` |
| 解析缓存 | **内存 LRU**，非盘上文件 | `apps/datafiles/services.py:38-49,211,404`（按字节预算，解析预算的 60%/上限 1536MB） |
| 后端日志 | **Django 侧不落盘，但桌面形态会** | `config/settings/base.py:59-81` 的 `LOGGING` 以 `DEFAULT_LOGGING` 为底，两个 handler 都显式指向 stdout（`:61-65` 解释：打包版 Electron 对子进程 stderr 一律记 ERROR，会把级别整体弄失真）。但 `electron/backend.ts:49-63` 把后端日志 `appendFileSync` 进 `userData/logs/backend.log`，`electron/main.ts:87` 同目录另有 `main.log` —— **无轮转、无清理**，见 §4.4-6 |
| **作业产物** | **是，永久留盘** | `apps/jobs/executor.py:243-246` → `MEDIA_ROOT/jobs/<owner_id>/<job_id>/` |
| **SFTP 取回的数据文件** | **是，永久留盘**（算用户数据） | `apps/sftp/downloads.py:159-161,282-283,320`，成功后当场注册进 `DataFile` |

所以「gage report、标红文件的清理」这个需求本身不成立。**真正在涨的是 `jobs/` 产物与 SFTP 取回文件两项。**

### 4.2 作业产物：清理器写得很好，但没有任何人按时跑它

`apps/jobs/management/commands/prune_jobs.py`（`--days` 默认 7，`:218`）：

- 选行：`status ∈ TERMINAL_STATUSES` 且 `finished_at < now - days`（`:226-229`、`_prunable :187-189`）。
- 定位目录按 **`owner_id + pk`**，不按 `result_path` —— 因为 `error` 行的 `result_path` 恒为空，
  按它推目录会「行删了、目录留下」永久泄漏（模块 docstring `:10-19` 把这段教训写清了）。
- 两道删除围栏：形状闸 `_guard_target`（必须正好是 `<jobs_root>/<十进制>/<十进制>`，
  用 `relpath` 而非「前缀 + 长度切片」，因为切片会被与 `jobs` 同长的兄弟目录 `jobz/7/3` 撞穿）
  + 归属闸 `_indexed_by_another_row`。`:92-99` 点名真实会踩的那条：
  `sftp_download` 且 `done` 的行的 `result_path` 指向用户批次目录，dirname 一层就是**该用户全部批次的父目录**。
- 三态结局 `REMOVED/ABSENT/KEPT`：**目录没清掉就不删行**，留着重试，汇总报「留盘 N」（`:249-269`）。
- 已知不解决：`_timed_out` 之后 worker 还在写的窗口；本次修复前已泄漏的孤儿目录（要按盘扫，另开工单）；
  POSIX 上 unlink 被占文件会**静默删掉写到一半的产物**再被 `makedirs` 建回成孤儿（`:40-45`）。

**调度缺口（本条的实际风险）**：

- 项目 2026-10-15 已整体移除 Celery（`config/settings/base.py:275`、`config/__init__.py:4-7`），
  无 `beat_schedule`、无 cron 入口。
- `apps/jobs/apps.py:60-62` 的 `ready()` 只在**非**离线命令时调 `mark_interrupted_jobs()`，
  `prune_jobs` 正在那份 `OFFLINE_COMMANDS` 名单里（`:24`）。名单的原文含义是
  「这些命令跑在开发/CI/运维的批处理里，没有『进程重启留下的僵尸』这回事」（`:18`）——
  **它是「跑这些命令时别去改库里的作业状态」，不是「跑到 prune 时顺手清一次产物」，两者毫无关系。
  这条是本轮核查里最容易读反的一句。**
- 全仓 `prune_jobs` 的调用方只有测试（`test/backend/test_prune_jobs_dir.py:175`、
  `prune_jobs_fixtures.py:121`）。**生产路径零调用。**
- 下载端点也不回收：`JobDownloadView`（`apps/jobs/views.py:259-275`）只 `open()` + `FileResponse`，
  成功后不 unlink、不清 `result_path`。

部署文档自己已经把这条挂成上线前待办 —— `docs/reference/server-deployment.md:249-256`：
「`media/` 没有自动回收通路……磁盘按**取回量 × 保留期**线性增长（按每天几十 GB 估，30 天就是 TB 级）……
作业产物那一半可以先自动化：`prune_jobs --days=N` 挂进 §4 的 timer（在 `lqdp-backup.service` 之外
另开一个 oneshot 即可），但取回的数据文件不在它范围内。」

### 4.3 其它清理事实

- **全仓无磁盘水位淘汰**：`disk_usage` / `free_space` 零命中（§7 复核）。缓存只有内存字节 LRU 预算，没有盘容量概念。
- **删 DataFile 不级联清产物**：`file_views.py:202-214`（单删）与 `:216-242`（批删）只 unlink 该文件本体 +
  失效解析缓存；报告/产物与 `DataFile` 之间没有外键，删源文件后那些以它算出来的 xlsx 仍躺在 `jobs/` 下。
- **其它 management commands 清单**（`ls apps/*/management/commands/`）：
  `prune_jobs`、`backup_db`、`consolidate_uploads`（迁移旧 `media/uploads/`，空目录 `rmdir`，
  **孤儿只报告不删** `:144-163`）、`migrate_user_paths`、`migrate_project_paths`、
  `backfill_product_code`、`seed_test_data`、`seed_users`、`jobs/maintenance`。
  除 `prune_jobs` 外都不是回收器。
- **占用可见性有一半**：`apps/datafiles/storage_usage.py` 按 `MEDIA_ROOT/data/<username>` 统计，
  30s 分桶 TTL。**`jobs/` 目录完全不进这份统计**，所以「谁占了多少」看不到产物那一半。

### 4.4 如果要做

按性价比排序：

1. **把 `prune_jobs` 挂上 systemd timer**（已定 Linux + systemd 形态）——纯运维配置，零代码。
   这是唯一「已经在库里、只是没人按按钮」的一条。
2. **`jobs/` 纳入占用统计**，让管理员看得见产物体积（否则保留期拍了也没法验证）。
3. **定「取回文件何时可删」的策略** → 才能做成第二个管理命令。这条是业务口径，等拍板。
4. 孤儿目录盘扫（`prune_jobs` 模块 docstring `:35-38` 已把它列为独立工单）。
5. 可选：同步降级路径（`_sync_fallback`）产出的文件现在也留盘，且没有对应可读的作业号可查——
   它写的 `result_path` 有行索引，prune 收得到，但值得确认一下取向日志是否够用。
6. **桌面形态的日志无轮转**：`userData/logs/backend.log` 与 `main.log` 是
   `appendFileSync` 一路追加（`electron/backend.ts:56-63`），全仓没有按大小/天数切档或删旧档的代码。
   后端每收一个数据块都在热路径上打日志（`backend.ts:68-72` 的注释自己点名了这条热路径），
   所以这台机器用得越久文件越大。服务器形态（stdout 交给 systemd journal）不受这条影响，
   是否处理取决于桌面版要发多少台。

---

## 5. 序列分布圈选高亮后，再开一个直方子图

### 5.1 现状：serial 图圈选只做高亮

`frontend/src/pages/analysis/components/SerialChart.vue:370-381`：

```
useChartBrushSelect({ mode: 'rect', immediate: true,
  canMenu: () => highlight.serials.value.length > 0,
  onCreate: (sel) => { if (sel.kind === 'serials') highlight.set(sel) } })
```

`immediate: true` 的含义写在 `useChartBrushSelect.ts:33-35` 与 `:222-228`：
mouseup 算出选区后**立刻** `onCreate` + `clearSelection`，浮层只在拖拽期间闪一次，不等右键菜单。
所以 serial 图的框选是「一次性消费为高亮」，右键菜单（`mode="highlight"`）里只有「清除高亮」一项
（`ChartContextMenu.vue:11-17`）。

高亮本身：`useSerialHighlight.ts` 是会话级单例，渲染以 `props.enableSelection` 为闸
（`SerialChart.vue:174-176`，激活时底层 site 系列降透明到 ≤0.25）；
切参数**不清**（同一批芯片跨参数重画，`SerialChart.vue:382-383`），切文件清（R5）。

### 5.2 「直方子图」整套管线已经存在，只是入口只长在直方图上

现成通路（框选 → 子集面板 → 独立直方图 dock 单元）：

| 环节 | 位置 | 说明 |
|---|---|---|
| 选区形状 | `selectionGeometry.ts:10-12` | `value_range` **或** `serials`，两种都已定义 |
| 直方图框选 → 建面板 | `HistogramChart.vue:318-325` + `SingleParamTab.vue:89` | `mode: 'value-range'`，`onCreate` → `emit('create-subset')` → `subsetPanels.create` |
| 面板 store | `useSubsetPanels.ts:78-87` | `createPanel(selection)` 只吃一个 `ChartSelection`，不挑 kind |
| 请求体 | `selectionGeometry.ts:110-128` | `buildSubsetRequest` 把 `selection` 原样塞进 `/analysis/histogram/`，强制 DR 分箱 |
| 后端解析 | `apps/analysis/services/data_services/subset_selection.py:47-63` | **`serials` 分支完整实现**：1..100000 个、元素类型/NaN 校验、`serial_col` 可选 |
| 后端过滤 | `apps/analysis/views/analysis_views.py:200-217` | `filter_df_by_selection` 行级过滤；`value_range` 还会回传 `selection_serials` 做选区固化 |
| dock 呈现 | `useChartDock.ts:23-28,258-281` | guest key `subset:<id>`，追加一行、只改内存不落盘（会话级） |
| 面板体 | `SubsetPanelBody.vue:12-22` | 复用 `HistogramChart`，`range-type="DR"`、`outlier-handling="off"`、`enable-data-zoom` |
| 标题 | `selectionGeometry.ts:88-96` | serials 选区显示「`<参数> 子集 · n=<颗数>`」 |

**而且是白送的**：`useSerialHighlight.ts:8-11,24-41` 把对外高亮集合定义成
`brush ∪ 子集面板贡献`（去重保序，brush 在前）。所以「打开子图 → 芯片持续高亮 → 关掉子图才消失」
这条语义已经实现了，文件头注逐字写着「子图展示即高亮其芯片，关掉子图才取消」。

### 5.3 要做的只有三处

1. `ChartContextMenu.vue`：`mode="highlight"` 那一支加一项「打开子集直方图」，多 emit 一个事件。
2. `SerialChart.vue`：`@open-subset` → `subsetPanels.create({ kind: 'serials', serials: highlight.serials.value, serial_col: highlight.serialCol.value })`。
3. 双主题样式（该文件样式已全走 token，新增按钮沿用现有 `role="menuitem"` 类）。

**一个必须先定的语义取舍**：因为 `immediate: true` 在 mouseup 已清掉浮层选区，
菜单项此刻手上只有「当前高亮的那批序列」，**不是「刚刚框的那一下」**。
两者差别在于用户可以在同一张图上连框多次（`highlight.set` 是**替换**而不是并集，
`useSerialHighlight.ts:44-48`，所以其实只有最后一次；但**跨参数**连框时，切参数不清高亮，
累积下来的仍是最后一次 set 的那批）。可选取向：

- **A（最小）**：菜单项 = 对「当前高亮集合」开子图。改动只在 UI 层，语义与「高亮 = 我在关注这批序列」一致。
- **B**：serial 图也保留 last-brush 选区（不 `clearSelection`），菜单项只对那一次框选开子图；高亮仍走并集。
  代价是要改 `useChartBrushSelect` 的 `immediate` 分支，两条消费时机分叉，浮层与高亮的视觉关系要重新对齐。
- **C**：干脆去掉 `immediate`，serial 图回到直方图那套「框选 → 右键 → 选动作」的两段式。
  改动最统一，但会牺牲现在「框完立即看到高亮」的手感（`useChartBrushSelect.ts:33-35` 说明当初就是为手感才加的）。

**建议 A**，并在标题里已经把 n 显示出来，用户能自查是对哪批开的子图。

### 5.4 这条不需要动后端

`serials` 选区的解析、校验、行级过滤、空选区报错（`empty_selection`，`analysis_views.py:235-236`）全都有，
且已有 T1/T2 判据覆盖。纯前端一个菜单项。

---

## 6. 待拍板清单（不拍板就没法往下做的）

| # | 要定什么 | 为什么必须用户定 |
|---|---|---|
| 1 | 管理员要「只读可见」还是「可代为管理」他人文件（§1.3） | 工作量与风险差一个量级；后者必须先补用户名拼路径的 `..` 防护 |
| 2 | 过载提示做到哪一层：只补「排队中/前面还有 N 个」，还是上准入限流（§2.3） | 后者依赖设计文档批 2 的预算/降级取向，且 `evict_parse_cache_to` 死代码要先接 |
| 3 | 前端 5 分钟等待上限是否提到与后端 kind 超时同档（§2.1-C） | 纯取向：转更久的圈 vs 早点撒手 |
| 4 | `prune_jobs` 保留几天、是否上 timer；**SFTP 取回文件的保留策略**（§4.4） | 后者是业务口径，决定磁盘要配多大 |
| 5 | serial 开子图取 A/B/C 哪种语义（§5.3） | 涉及交互手感，不是技术约束 |
| 6 | pptx 进度是补 `progress_cb` 还是接受 33%→100%（§3.2-①） | 若接受，就把这条从待办里划掉，别留模糊 |

## 7. 复核口径（负命题怎么验的）

```bash
# 过载/准入层不存在（只在 docs/ 的设计文档里出现）
grep -rniE "admission|server_busy|ServerBusy|HeavyAction|繁忙|degraded" apps/ frontend/src/
# → apps/ 与 frontend/src/ 均无命中（只有 SQLite 的 busy_timeout，语义无关）

# out_of_memory 前端没有码表映射
grep -rn "out_of_memory" frontend/src/    # → 无命中

# 无磁盘水位淘汰
grep -rniE "disk_usage|free_space|shutil\.disk" apps/    # → 无命中

# prune_jobs 生产路径无调用方
grep -rn "prune_jobs" --include=*.py --include=*.sh --include=*.service --include=*.md .
# → 只有 apps/jobs/{apps,models}.py 的注释、命令本体、测试、docs/

# pptx 无 progress_cb
grep -n "def build_batch_charts_pptx" -A 8 apps/export/export_ppt.py
# 对照 apps/jobs/runner.py:154-157 的调用点
```

**未验证项（诚实标注）**：以上全部是静态阅读结论。没有实测过
「连框多次后开子图的序列集合到底是什么」（§5.3 那条取舍需要开浏览器才能定手感），
没有实测 20 人档过载时的真实表现（`scripts/perf_load20.py` 在，本轮没跑），
没有确认 `prune_jobs` 在目标服务器上的实际保留期容量账。

## 8. 建议的批次切法

按「先收已有、再开新面」排：

1. **刀一（小、独立、当天可收）**：§5 serial 圈选开子图（取 A 案）+ §3.2-① pptx 补 `progress_cb`。
   两处都不动后端契约、不动权限，符合 600 行约束（`SerialChart.vue` / `ChartContextMenu.vue` 现长远未触阈）。
   验证：T2 `vitest`（`selectionGeometry` 已有纯函数判据位）+ affected e2e 加一条 serial 框选开子图。
2. **刀二（运维，零功能代码）**：§4.4-1 `prune_jobs` 上 systemd timer + §4.4-2 `jobs/` 进占用统计。
   等第 4 项保留期拍板。
3. **刀三（过载可见性）**：§2.3 排队提示 + 前端等待上限对齐。这条先写 spec，
   因为它要回答「准入做不做」——那会牵动批 2 那份设计文档的存量取向。
4. **刀四（跨用户文件管理）**：§1，最大的一批，且必须**先单独补 `_user_upload_dir` 的用户名 `..` 防护**
   再开跨用户读写面（这条防护本身可以独立先做，属加固，不改变任何现有行为）。

**当前不动代码**：本会话只出报告。按项目规则（`.claude/CLAUDE.md` §1 计划模式默认），
刀一起手也要先进计划模式写规格。
