# 审查刀二/三/四设计：prune 保留期 + jobs 占用、管理员跨用户只读、过载准入

日期：2026-11-22
依据：`docs/reference/feature-gap-review-2026-11-16.md` §1、§2、§4.4、§6、§8
关联设计：`docs/superpowers/specs/2026-10-21-backend-memory-governance-design.md` 批 2

## 1. 已拍板口径

| 决策 | 结果 |
|---|---|
| `prune_jobs` 保留期 | **7 天**（命令默认值 = systemd 模板现值），不改命令本体 |
| 管理员跨用户权限 | **只读**：可按用户看文件清单与占用，不可下载/预览/删改 |
| 过载准入层 | **完整批 2**：准入信号量 + 503 信封 + 前端话术 + 等待上限对齐 + 排队数 + KDE 可见降级 |
| 分支 | `feature/gap-review-knife2-4`，从 master 开，不 push |

## 2. 目标与非目标

### 2.1 目标

1. 关闭 prune 保留期待拍板项，并把 `MEDIA_ROOT/jobs/` 纳入占用统计与前端展示。
2. 新增管理员 `/admin/files`：按用户只读查看文件清单、数据体积、作业产物体积。
3. 落地内存治理批 2：重活准入、`server_busy` 503、KDE 降级提示、作业排队数与前后端超时对齐。

### 2.2 非目标

- 不做管理员代删/代改/代下载/代预览；不放开 `files/<id>/` 详情、`browse/`、下载端点。
- 不做 SFTP 取回文件的保留期策略（业务口径未定）。
- 不做作业 worker 硬上限（批 3）。
- 不做孤儿作业目录盘扫（审查 §4.4-4）。
- 不把 `batch_yield_data` 纳入重活名单（等峰值清单）。

## 3. A. prune 保留期 + jobs/ 占用口径

### 3.1 保留期收口

- `deploy/lqdp-prune-jobs.service` 的 `ExecStart` 维持 `--days=7`；注释改为「保留期已定 7 天（2026-11-22）」。
- `deploy/README.md`、`docs/reference/server-deployment.md` 同步措辞，删除「拍板后只改」的待定语气。
- `docs/tasks/todo.md` 的「保留期拍板」勾选。

### 3.2 占用统计

`apps/datafiles/storage_usage.py`：

- 新增 `_user_jobs_root(user)`：`MEDIA_ROOT/jobs/<user.id>`，`user.id` 为整数（Django PK），`os.path.normpath`；不使用用户名。
- 复用 `_scan_tree(root)` 扫描 jobs 根（不带 `registered`），得到 `bytes/file_count`。
- `_compute_usage` 返回体新增：
  - `jobs_bytes`：作业产物表观体积；
  - `jobs_file_count`：作业产物文件数；
  - `total_bytes`：`bytes + jobs_bytes`。
- `bytes`、`by_type`、DB 清单与差值口径保持不变；30s 分桶缓存键不变（jobs 与 data 同一次计算）。
- jobs 根不存在时三个新字段为 0，不报错。

前端：

- `FileUsage` 类型加三个字段。
- `usageChipText` 改为用 `total_bytes`，文案 `磁盘占用 <总量>`；`usageBreakdownRows` 保持 data 分桶，另新增 `usageJobsLine(usage)` 返回「作业产物 X · N 个文件」；`FileListToolbar` 浮层增加该行。
- `diskUsage.spec.ts` 更新/新增判据；`disk-usage-chip.spec.ts` 的 chip 期望改为总量，并断浮层有作业产物行。

## 4. B. 管理员跨用户只读

### 4.1 权限

`apps/accounts/permissions.py` 新增：

```python
'data_view_all': ['administrator'],
```

`test/backend/test_role_can.py` 的 `EXPECTED_FEATURES` 与真值表同步。

### 4.2 文件清单（复用现有列表端点）

`GET /api/v1/files/?owner_id=<id>`：

- 仅当 `self.action == 'list'` 且 `role_can(request.user.role, 'data_view_all')` 时生效；
- 无权限却带 `owner_id` → 403；
- `owner_id` 非整数 → 400 `validation_error`；
- 其它动作（retrieve/下拉/批量删除）完全不受影响，仍按 `owner=request.user`；
- 列表序列化器仍是 `DataFileListSerializer`（不含 `file_path`/`metadata`）。

实现落点：新建 `apps/datafiles/views/admin_scope.py` 的 `scoped_files(request, action, default_qs)`，
`file_views.py::get_queryset` 只改一行调用 + 一行 import，避免顶到 600 行闸。

### 4.3 用户占用列表

新端点 `GET /api/v1/admin/files/users/`：

- `permission_classes = [IsAuthenticated, FeaturePermission]`，`required_feature='data_view_all'`；
- 返回 `{'results': [{id, username, display_name, role, is_active, usage}]}`，
  `usage` 为 `get_user_usage(user)` 原样（含新增 jobs 字段）；
- 用户名不能安全拼路径的旧账号：`usage: null`，不 500；
- 按 `id` 升序，只列启用账号。

### 4.4 前端

- 新路由 `/admin/files`，`requiresAdmin`，`meta.parent = { label: '系统管理' }`。
- **`config/urls.py` 的 SPA 白名单正则必须加 `files`**：`r'^admin/(?:users|audit|files)/?$'`。
  否则单端口形态下整页刷新 `/admin/files` 会被 Django admin 接走并 302 到 `/admin/login/`；
  Vite/e2e 自带 history fallback，覆盖不到这条（2026-11-11 部署实测过的同形坑）。
- 侧栏「系统管理」组新增「全部文件」入口。
- 页面 `AdminFiles.vue`：
  - `AdminPageToolbar` 用户下拉（来自 `/admin/files/users/`）；
  - 三个 KPI：数据体积、作业产物体积、总占用；
  - 只读文件表：文件名 / 产品 / 格式 / 大小 / 上传时间；搜索 + 分页；
  - **无查看、下载、删除、编辑按钮**；
  - 空态：未选用户 / 该用户无文件 / 加载失败。
- 不写 `AuditEvent`（只读）；将来开放写操作时补。

## 5. C. 过载准入（完整批 2）

### 5.1 准入模块

新文件 `apps/common/admission.py`：

```python
heavy_slot(action) -> contextmanager
```

时序：

```
relief_if_soft()                 # level == soft → evict_parse_cache_to(0.5)
acquire(semaphore, timeout=WAIT) # 超时 → ServerBusy(reason='queue')
if level == hard:
    evict_parse_cache_to(0.0)    # 仍 hard → release + ServerBusy(reason='memory')
yield
release
```

- 容量：`LQDP_HEAVY_CONCURRENCY`，默认 2，夹取 1–8。
- 等待：`LQDP_HEAVY_WAIT_S`，默认 10，夹取 0–60。
- 线程内嵌套用 depth 计数，只有最外层取/放槽。
- 拒绝日志 10s 限频。
- `admission_snapshot()` 返回 `{capacity, active, waiting, rejected, relief, last_reason}`。

### 5.2 信封

`apps/common/exceptions.py` 新增 `ServerBusy(APIException)`：

```json
{"code":"server_busy","message":"服务器繁忙，请稍后重试","detail":{"reason":"queue"}}
```

- `status_code=503`；`Retry-After: 5`。
- 加入 `_KNOWN_EXCEPTIONS`；`_code_for_status(503) = 'server_busy'`。
- 前端 `ERROR_CODE_MAP` 增加 `server_busy`，顺带补 `throttled`。

### 5.3 接线

`HeavyActionMixin` 按内存治理设计 §6.1：

- `initial()` 中按 `self.action` 取槽；`ServerBusy` 位于 `APIView.dispatch()` 的 try 内；
- `finalize_response()` 的 `finally` 释放；
- 不覆写 `dispatch()`。

五个 ViewSet 与 `heavy_actions`：

| ViewSet | heavy_actions |
|---|---|
| `AnalysisViewSet` | `histogram, wafer_map, multi_lot, correlation, file_correlation_serials, file_correlation, file_correlation_export, serial_distribution, cpk, qqplot, uph` |
| `StatisticsViewSet` | `detect_fail, bin_stats, zonal_yield, correlation_matrix, bin_trend, boxplot, param_trend` |
| `GageViewSet` | `generate_summary` |
| `BuyoffViewSet` | `identify_common_items, generate_form` |
| `BatchReportViewSet` | `batch_html_report, generate_report` |

`site_stats`、`list_batches` 保持轻端点；`batch_yield_data` 暂不登记。

`apps/jobs/views.py::_sync_fallback` 也取同一信号量；被拒时先把作业标 `error`（`error='服务器繁忙，请稍后重试'`）再抛 503，避免永久 pending。

### 5.4 指标

`/api/v1/metrics/` 的 `snapshot()` 增加：

```json
"admission": {"capacity":2,"active":0,"waiting":0,"rejected":0,"relief":0,"last_reason":null}
```

### 5.5 KDE 可见降级

- `compute_kde_curve(data_series, bin_min, bin_max, n_points=200, *, degraded=None, reason='kde_curve')`：
  捕获 `MemoryError`；`degraded` 为 list 时 `append(reason)` 并返回 `None`，否则继续抛出。
- `compute_histogram_stats(..., degraded=None)`：两次 KDE 调用分别传 `'kde_curve'` / `'filtered_kde_curve'`；
  返回体恒带 `degraded: list(degraded or [])`。
- `AnalysisViewSet.histogram` 建 `degraded = []` 并透传；每个参数的结果自带 `degraded`。
- multi_lot / 导出不降级，保持抛出。
- 前端新增 `frontend/src/pages/analysis/histogramDegraded.ts`：
  `histogramDegradedHint(reasons: string[]): string | null`，非空返回「内存紧张，已省略 KDE 曲线」。
- `HistogramChart.vue` 在 `props.result?.degraded?.length` 时渲染紧凑提示，`data-degraded-hint`，样式全走 token。

### 5.6 作业排队数与等待上限

- `_job_payload(job, *, with_queue=False)` 新增：
  - `queue_position`：同 owner、`status in ('pending','running')`、`created_at < job.created_at`（同刻按 `id <`）的条数；
  - `timeout_seconds`：`executor.KIND_RUNNERS[job.kind]['timeout']`。
- 提交与详情带 `queue_position`；列表可省略（前端不读）。
- 前端 `JobStatus` 增加可选 `queue_position` / `timeout_seconds`。
- `jobPolling.pollTimeoutMs(job)`：`timeout_seconds * 1000 + 60_000`，缺字段回退 `POLL_MAX_MS`（5 分钟）。
- `pollDecision` 的 state 增加 `maxMs`；`useJobExport` 在首个响应确定上限。
- `useJobExport` 暴露 `queuePosition`；`JobProgressChip` 增可选 `queuePosition`，进度 0 且 >0 时显示「排队中 · 前面 N 个」。

## 6. 测试策略

| 层 | 判据 |
|---|---|
| T1 | usage 新字段与 jobs 扫描；admin 权限/隔离/usage 列表；admission 槽/503/嵌套/指标；mixin 重活名单与真实 action 一致；degraded 直方图；queue_position/timeout_seconds |
| T2 | `diskUsage` 新口径；`server_busy`/`throttled` 文案；`pollTimeoutMs`/排队文案；`histogramDegradedHint` |
| T3 | `/admin/files` 管理员可见、普通用户被守卫且无菜单；直方图降级提示真实渲染（一条） |

## 7. 风险与回滚

- **准入可能误伤正常请求**：容量默认 2、等待 10s；若 20 人档出现大量 503，先调 `LQDP_HEAVY_CONCURRENCY` / `LQDP_HEAVY_WAIT_S`，不改代码。
- **jobs 扫描增加请求成本**：每用户一次树走 + 30s 缓存；本机 ~11ms/百文件，20 人档可接受。
- **owner_id 参数扩大读面**：严格限定 `list` + `data_view_all`；详情/下载/预览不放开。
- **前端 60 分钟轮询**：`POLL_SLOW_MS=2s` 封顶，请求量可接受；到 kind 超时后仍会放弃。
- 回滚：三块各自独立提交，可单独 revert；准入层可用环境变量把容量调大但不等同关闭（如需完全关闭，另加开关不在本批）。

## 8. 文件清单

**后端**

- `apps/datafiles/storage_usage.py`
- `apps/datafiles/views/usage_views.py`（如把 admin users 端点放这里；否则新文件）
- `apps/datafiles/views/admin_usage_views.py`（新）
- `apps/datafiles/views/admin_scope.py`（新）
- `apps/datafiles/views/file_views.py`（+2 行）
- `apps/datafiles/views/__init__.py`
- `apps/datafiles/urls.py`
- `apps/accounts/permissions.py`
- `apps/common/admission.py`（新）
- `apps/common/exceptions.py`
- `apps/common/metrics.py`
- `apps/analysis/views/analysis_views.py`
- `apps/analysis/views/statistics_views.py`
- `apps/gage/views.py`
- `apps/buyoff/views.py`
- `apps/batch_report/views.py`
- `apps/jobs/views.py`
- `apps/analysis/services/data_services/histogram.py`
- `test/backend/test_storage_usage_jobs.py`（新）
- `test/backend/test_files_usage_api.py`
- `test/backend/test_admin_files_api.py`（新）
- `test/backend/test_role_can.py`
- `test/backend/test_admission.py`（新）
- `test/backend/test_admission_wiring.py`（新）
- `test/backend/test_histogram_degraded.py`（新）
- `test/backend/test_jobs_queue_payload.py`（新）

**前端**

- `frontend/src/utils/diskUsage.ts`
- `frontend/src/pages/data/components/FileListToolbar.vue`
- `frontend/src/api/datafiles.ts`
- `frontend/src/api/jobs.ts`
- `frontend/src/api/adminFiles.ts`（新）
- `frontend/src/pages/admin/AdminFiles.vue`（新）
- `frontend/src/router/index.ts`
- `frontend/src/components/layout/Sidebar.vue`
- `config/urls.py`（SPA 白名单加 `files`）
- `frontend/src/utils/error.ts`
- `frontend/src/pages/analysis/histogramDegraded.ts`（新）
- `frontend/src/pages/analysis/components/HistogramChart.vue`
- `frontend/src/composables/jobPolling.ts`
- `frontend/src/composables/useJobExport.ts`
- `frontend/src/components/common/JobProgressChip.vue`
- `frontend/src/pages/dashboard/components/ExportFooter.vue`
- `frontend/src/pages/data/components/export/ExportActions.vue`
- `frontend/src/pages/data/DataBrowserAgGrid.vue`（仅调用点传参；已 600 行，**不得加行**，只改现有行）
- 对应 T2/T3 测试文件

**文档/运维**

- `deploy/lqdp-prune-jobs.service`
- `deploy/README.md`
- `docs/reference/server-deployment.md`
- `docs/tasks/todo.md`
