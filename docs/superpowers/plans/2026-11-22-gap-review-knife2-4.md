# 审查刀二/三/四实施计划

**Spec:** `docs/superpowers/specs/2026-11-22-gap-review-knife2-4-design.md`
**依据:** `docs/reference/feature-gap-review-2026-11-16.md` §1、§2、§4.4
**分支:** `feature/gap-review-knife2-4`（从 master `89990cd` 开，不 push）

## Global Constraints

- **600 行硬约束**：`git ls-files '*.py' '*.ts' '*.vue'` 全仓生效。以下文件已接近/顶格，**只许净减或原地改，不许新增行**：
  - `apps/datafiles/services.py` 599 行（**本批不动**）
  - `apps/accounts/views.py` 594 行（**本批不动**；新端点放新文件）
  - `apps/datafiles/views/file_views.py` 590 行（只允许 +2 行：import + 调用）
  - `frontend/src/pages/data/DataBrowserAgGrid.vue` 600 行（只许改现有行，不许加行）
  - `frontend/src/pages/analysis/components/SingleParamTab.vue` 589 行（**本批不动**）
  - `test/backend/test_storage_usage_scan.py` 562 行（新 jobs 用例放新文件）
- **双主题**：新增 UI 只认 CSS token（`--text-2`、`--bg-2`、`--border`、`--brand` 等），不写裸色。
- **测试分层**：先选层再写断言。纯函数 → T2；响应体/权限 → T1；真实渲染/路由守卫 → T3。
- **e2e 纪律**：一条 bash 命令只跑一个 playwright 档位；跑前确认端口空闲，跑后释放；判绿取日志末尾汇总行，不取 `$?`。
- **提交**：每笔 commit 前 `cd frontend && npm run test:e2e:affected`；docs-only commit 记录 `RESULT: NO AFFECTED TESTS` 并注明「docs-only，无测试承重」。
- **不 push**；不合并 master；不删分支。
- **不新增设计文档以外的功能**；不做 SFTP 保留期、worker 硬上限、孤儿目录盘扫。
- **口径唯一**：`--days=7` 只在 `deploy/lqdp-prune-jobs.service` 与命令默认值两处，且两处一致。

---

## Task 1: jobs/ 纳入后端占用统计

**Files:**
- Modify: `apps/datafiles/storage_usage.py`
- New: `test/backend/test_storage_usage_jobs.py`
- Modify: `test/backend/test_files_usage_api.py`

**Interfaces:**
- `_compute_usage(user)` 返回体新增 `jobs_bytes: int`、`jobs_file_count: int`、`total_bytes: int`。
- `_scan_tree(root)` 原样复用，不传 `registered`。
- `get_user_usage(user, fresh=False)` 签名不变。

**Steps:**

1. 先写 `test/backend/test_storage_usage_jobs.py`：
   - 临时 `MEDIA_ROOT`，用户 A 的 `data/<username>/single/a.csv` 与 `jobs/<A.id>/<job_id>/out.xlsx`；
   - 断言 `jobs_bytes` 等于 jobs 目录文件 `st_size` 之和、`jobs_file_count` 等于文件数；
   - 断言 `total_bytes == bytes + jobs_bytes`；
   - 断言 jobs 根不存在时三项为 0；
   - 断言用户 B 的 `jobs/<B.id>` 不计入 A。
   - 用 `override_settings(MEDIA_ROOT=...)` + `clear_usage_cache()` 隔离；参考 `test/backend/test_storage_usage_scan.py::ComputeUsageTests` 的夹具风格。
2. 实现 `_user_jobs_root(user)`：
   ```python
   def _user_jobs_root(user):
       return os.path.normpath(
           os.path.join(str(settings.MEDIA_ROOT), 'jobs', str(int(user.id)))
       )
   ```
   `user.id` 是 Django PK，整数；不拼接用户名。
3. `_compute_usage` 中：
   ```python
   jobs_root = _user_jobs_root(user)
   jobs_scan = _scan_tree(jobs_root)
   ...
   'jobs_bytes': jobs_scan['bytes'],
   'jobs_file_count': jobs_scan['file_count'],
   'total_bytes': scan['bytes'] + jobs_scan['bytes'],
   ```
4. 更新 `test_files_usage_api.py` 的 `FIELDS` 集合，加入三个新字段；断言类型为 int。
5. 跑：
   ```bash
   python manage.py test test.backend.test_storage_usage_jobs test.backend.test_files_usage_api test.backend.test_storage_usage_scan test.backend.test_storage_usage_cache
   ```
   期望 `OK`。
6. Commit：`feat(datafiles): 占用统计纳入作业产物体积`

---

## Task 2: 前端占用 chip 改为总量 + 作业产物行

**Files:**
- Modify: `frontend/src/api/datafiles.ts`
- Modify: `frontend/src/utils/diskUsage.ts`
- Modify: `frontend/src/pages/data/components/FileListToolbar.vue`
- Modify: `frontend/test/unit/diskUsage.spec.ts`
- Modify: `frontend/e2e/data/disk-usage-chip.spec.ts`

**Interfaces:**
- `FileUsage` 增加 `jobs_bytes`、`jobs_file_count`、`total_bytes`。
- `usageChipText(usage)` 使用 `total_bytes`。
- 新 `usageJobsLine(usage): string | null` → `作业产物 <size> · <count> 个文件`；`jobs_bytes === 0` 时返回 null。

**Steps:**

1. 更新 `diskUsage.spec.ts`：
   - `usageChipText` 用 `total_bytes`（含 jobs 的夹具）；
   - `usageJobsLine` 非零/零两态；
   - 既有 `usageBreakdownRows` 仍按 `by_type`。
2. 更新 `datafiles.ts` 的 `FileUsage` 类型。
3. 更新 `diskUsage.ts`：`usageChipText` 改 `usage.total_bytes`；新增 `usageJobsLine`。
4. `FileListToolbar.vue`：
   - 浮层在分桶行之后增加一行 `v-if="usageJobs"` 显示 `{{ usageJobs }}`；
   - computed `usageJobs = computed(() => usageJobsLine(props.usage))`；
   - 样式沿用浮层现有类，不新增颜色。
5. 更新 `disk-usage-chip.spec.ts`：
   - chip 期望文本改为「磁盘占用 <data+jobs 总量>」；
   - 浮层断言出现「作业产物」行；
   - 端点坏掉/204 的既有用例保持。
6. 跑：
   ```bash
   cd frontend && npx vitest run test/unit/diskUsage.spec.ts
   ```
   期望全绿。
7. 跑该文件 e2e（一条命令只跑这一档，先确认端口空闲）：
   ```bash
   cd frontend && E2E_SKIP_BUILD=1 npx playwright test e2e/data/disk-usage-chip.spec.ts --project=P2 --workers=1
   ```
   期望末尾 `passed` 数与用例数一致。
8. Commit：`feat(data): 占用 chip 展示作业产物总量`

---

## Task 3: prune 保留期 7 天收口（docs/运维）

**Files:**
- Modify: `deploy/lqdp-prune-jobs.service`
- Modify: `deploy/README.md`
- Modify: `docs/reference/server-deployment.md`
- Modify: `docs/tasks/todo.md`

**Steps:**

1. `deploy/lqdp-prune-jobs.service` 注释改为：
   `# 保留期已定 7 天（2026-11-22 拍板）；改口径只改这里，不要改命令本体。`
2. `deploy/README.md` 与 `docs/reference/server-deployment.md` 把「保留期拍板后只改」改为「保留期已定 7 天」。
3. `docs/tasks/todo.md` 的「运维 prune_jobs timer」条目勾掉「保留期拍板」，补一行决策记录。
4. 跑 `node scripts/prepush-history-check.mjs` 前不需要；本任务只跑：
   ```bash
   cd frontend && npm run test:e2e:affected
   ```
   期望 `RESULT: NO AFFECTED TESTS`（docs/deploy 映射空集）并记录。
5. Commit：`docs(deploy): 定稿 prune_jobs 保留期 7 天`

---

## Task 4: 管理员跨用户只读后端

**Files:**
- Modify: `apps/accounts/permissions.py`
- New: `apps/datafiles/views/admin_scope.py`
- Modify: `apps/datafiles/views/file_views.py`（只 +2 行）
- New: `apps/datafiles/views/admin_usage_views.py`
- Modify: `apps/datafiles/views/__init__.py`
- Modify: `apps/datafiles/urls.py`
- Modify: `test/backend/test_role_can.py`
- New: `test/backend/test_admin_files_api.py`

**Interfaces:**
- `FEATURE_PERMISSIONS['data_view_all'] = ['administrator']`。
- `scoped_files(request, action, default_qs) -> QuerySet`：
  - 无 `owner_id` 或 `action != 'list'` → `default_qs`；
  - 有 `owner_id` 但无 `data_view_all` → 抛 `PermissionDenied`；
  - `owner_id` 非整数 → 抛 `ValidationError({'owner_id': '必须是整数'})`；
  - 否则 `default_qs.model.objects.filter(owner_id=int(owner_id))`。
- 新 `AdminFileUserUsageView(APIView)`：
  - `required_feature = 'data_view_all'`；
  - `GET` 返回 `{'results': [{id, username, display_name, role, is_active, usage}]}`；
  - `usage = get_user_usage(user)`；`ValueError` 时 `usage=None`；
  - 只列 `is_active=True`，按 `id` 升序。
- 路由：`/api/v1/admin/files/users/`（在 `apps/datafiles/urls.py` 注册）。

**Steps:**

1. 先写 `test/backend/test_role_can.py` 的新增真值：`data_view_all` 仅 administrator。
2. 先写 `test/backend/test_admin_files_api.py`：
   - 管理员带 `owner_id` 能列出目标用户文件；
   - 普通用户带 `owner_id` → 403；
   - `owner_id=abc` → 400；
   - 管理员不带 `owner_id` 仍只看自己；
   - 管理员 `GET /files/<他人文件id>/` → 404（详情不放开）；
   - `GET /admin/files/users/`：管理员 200、普通用户 403、匿名 401；
   - 返回的 `usage` 含 `bytes/jobs_bytes/total_bytes`；不安全用户名账号 `usage=None`。
3. 实现 `admin_scope.py`（新文件，约 35 行）。
4. `file_views.py`：
   - import `scoped_files`；
   - `get_queryset` 首行改为 `queryset = scoped_files(self.request, self.action, DataFile.objects.filter(owner=self.request.user))`。
   - 只加这两行，跑 `wc -l` 确认 ≤ 592。
5. 实现 `admin_usage_views.py`（新文件，约 45 行）。
6. `views/__init__.py` 导出 `AdminFileUserUsageView`；`urls.py` 加 `path('admin/files/users/', AdminFileUserUsageView.as_view(), name='admin-file-users')`。
7. 跑：
   ```bash
   python manage.py test test.backend.test_role_can test.backend.test_admin_files_api test.backend.test_files_usage_api
   ```
   期望 `OK`。
8. Commit：`feat(datafiles): 管理员跨用户只读文件清单与占用`

---

## Task 5: 管理员跨用户只读前端页

**Files:**
- New: `frontend/src/api/adminFiles.ts`
- New: `frontend/src/pages/admin/AdminFiles.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/layout/Sidebar.vue`
- Modify: `frontend/src/api/datafiles.ts`（`ListFilesParams` 加 `owner_id?`）
- Modify: `config/urls.py`（SPA 白名单加 `files`）
- New: `frontend/e2e/admin/files.spec.ts`

**Interfaces:**
- `adminFilesApi.listUsers()` → `{ results: AdminUserUsage[] }`。
- `AdminUserUsage = { id, username, display_name, role, is_active, usage: FileUsage | null }`。
- 文件列表走 `datafilesApi.listFiles({ owner_id, page, page_size: 20, search, product_code, format_type, ordering: '-created_at' })`。

**Steps:**

1. 新建 `adminFiles.ts`，类型与请求封装；错误交给全局拦截器。
2. 新建 `AdminFiles.vue`：
   - `AdminPageToolbar` 左侧用户 `el-select`（filterable），右侧刷新按钮；
   - 三个 KPI chip 用 `usageBytesText`；
   - `el-table` 只读列：文件名 / 产品 / 格式 / 大小（`formatSize`）/ 上传时间（`formatTime`）；
   - `el-pagination` 仿 `AuditLogPage.vue`；
   - 未选用户时显示空态；加载失败显示错误空态；
   - **不得出现查看/下载/删除/编辑按钮**。
3. `router/index.ts` 在 `/admin/audit` 之后新增 `/admin/files`，`requiresAdmin: true`，`meta.parent = { label: '系统管理' }`。
4. `config/urls.py` 把 SPA 白名单从 `r'^admin/(?:users|audit)/?$'` 改为 `r'^admin/(?:users|audit|files)/?$'`。
   这是单端口形态的整页刷新通路；Vite/e2e 覆盖不到，必须在代码里改对。
5. `Sidebar.vue` 的「系统管理」组新增 `{ path: '/admin/files', label: '全部文件', requiresAdmin: true }`。
5. 新建 `e2e/admin/files.spec.ts`：
   - 管理员经侧栏进入 `/admin/files`，选一个用户后表格出现行；
   - 断言页面上没有「下载」「删除」「查看」按钮（用 `getByRole('button', { name: ... })` 计数 0 或表格行内无 action 列）；
   - 普通用户：侧栏无「全部文件」，直达 `/admin/files` 被守卫送回 `/dashboard`。
6. 跑：
   ```bash
   cd frontend && npx vitest run
   cd frontend && npm run lint:e2e
   cd frontend && npm run build
   cd frontend && E2E_SKIP_BUILD=1 npx playwright test e2e/admin/files.spec.ts --project=P1 --workers=1
   ```
   逐条执行，确认端口与汇总行。
7. Commit：`feat(admin): 新增跨用户只读文件页`

---

## Task 6: 准入内核与 503 信封

**Files:**
- New: `apps/common/admission.py`
- Modify: `apps/common/exceptions.py`
- Modify: `apps/common/metrics.py`
- New: `test/backend/test_admission.py`

**Interfaces:**
- `ServerBusy(APIException)`：`status_code=503`、`default_code='server_busy'`、`default_detail='服务器繁忙，请稍后重试'`；实例带 `reason`，`detail={'reason': reason}`。
- `heavy_slot(action)` 上下文管理器。
- `admission_snapshot() -> dict`。
- `/metrics/` 的 `snapshot()` 增加 `admission` 键。

**Steps:**

1. 先写 `test/backend/test_admission.py`：
   - 容量 1 时，第二个线程等待超时 → `ServerBusy(reason='queue')`；
   - 槽释放后第二个线程可进入；
   - 嵌套调用只占一个槽；
   - hard 水位（mock `get_budget().level` 返回 `'hard'`）→ 先调 `evict_parse_cache_to(0.0)`，仍 hard → `ServerBusy(reason='memory')`；
   - soft 水位先调 `evict_parse_cache_to(0.5)`；
   - `admission_snapshot()` 的计数变化；
   - `ServerBusy` 经 `custom_exception_handler` 返回 503、`code='server_busy'`、`Retry-After: 5`、`detail.reason`。
   - 用 `unittest.mock.patch` 控制水位与 `evict_parse_cache_to`，用 `threading.Event` 控制并发，不 sleep 定长。
2. 实现 `apps/common/admission.py`：
   - 模块级 `_semaphore`、`_lock`、`_state`、`threading.local()`；
   - `_capacity()` / `_wait_seconds()` 用 `memory.env_int`；
   - `relief_if_soft()`、`_level()`、`_release()`、`_snapshot()`；
   - 拒绝日志 10s 限频（`logger.warning` + 单调时钟）。
3. `exceptions.py`：
   - 定义 `ServerBusy`；
   - 加入 `_KNOWN_EXCEPTIONS`；
   - `_code_for_status` 加 `503: 'server_busy'`；
   - `custom_exception_handler` 在 `exception_handler` 返回后给 `ServerBusy` 加 `Retry-After: 5`。
4. `metrics.py`：`snapshot()` 增加 `'admission': admission_snapshot()`（懒 import 避免循环）。
5. 跑：
   ```bash
   python manage.py test test.backend.test_admission apps.common.tests_metrics
   ```
   期望 `OK`。
6. Commit：`feat(common): 重活准入内核与 server_busy 信封`

---

## Task 7: 重活动作接线与同步降级准入

**Files:**
- Modify: `apps/analysis/views/analysis_views.py`
- Modify: `apps/analysis/views/statistics_views.py`
- Modify: `apps/gage/views.py`
- Modify: `apps/buyoff/views.py`
- Modify: `apps/batch_report/views.py`
- Modify: `apps/jobs/views.py`
- New: `test/backend/test_admission_wiring.py`

**Interfaces:**
- `HeavyActionMixin` 从 `apps.common.admission` 导入。
- 各 ViewSet 的 `heavy_actions` 按 Spec §5.3 表。
- `_sync_fallback` 在 `entry(task)` 外层包 `with heavy_slot('sync_fallback'):`；`ServerBusy` 时先把 job 标 `error` 再抛。

**Steps:**

1. 先写 `test/backend/test_admission_wiring.py`：
   - 五个 ViewSet 的 `heavy_actions` 是真实 action 的子集；
   - 逐项钉住 Spec §5.3 的名单（与 `set(viewset.get_extra_actions())` 或 `router` 的 action 对照）；
   - `site_stats`、`list_batches`、`batch_yield_data` 不在名单；
   - 持槽时重活 action 返回 503 `server_busy`，未登记 action 不取槽（mock `heavy_slot` 断言未被调用）；
   - `_sync_fallback` 被拒时 job.status 变 `error` 且返回 503。
2. 实现 `HeavyActionMixin`（放 `admission.py`，与内核同文件；本任务只加类）。
3. 五个 ViewSet 加 mixin 与 `heavy_actions`；只改类定义与 import，不重排现有代码。
4. `jobs/views.py`：import `heavy_slot`/`ServerBusy`；`_sync_fallback` 包裹。
5. 跑：
   ```bash
   python manage.py test test.backend.test_admission test.backend.test_admission_wiring apps.jobs.tests_jobs
   ```
   期望 `OK`。
6. Commit：`feat(analysis): 重活端点接入准入信号量`

---

## Task 8: KDE 可见降级（后端）

**Files:**
- Modify: `apps/analysis/services/data_services/histogram.py`
- Modify: `apps/analysis/views/analysis_views.py`
- New: `test/backend/test_histogram_degraded.py`

**Interfaces:**
- `compute_kde_curve(..., *, degraded=None, reason='kde_curve')`。
- `compute_histogram_stats(..., degraded=None)`；返回体恒带 `degraded: list`。
- `AnalysisViewSet.histogram` 建 `degraded=[]` 并透传。

**Steps:**

1. 先写 `test/backend/test_histogram_degraded.py`：
   - mock `compute_kde_curve` 抛 `MemoryError` → `compute_histogram_stats(degraded=[])` 返回 `degraded=['kde_curve']` 且 `kde_curve=None`；
   - `filtered_kde_curve` 分支的 reason；
   - `degraded=None` 时 `MemoryError` 继续抛出（multi_lot/导出行为不变）；
   - 正常路径 `degraded=[]`；
   - 视图层：mock service 返回 `degraded=['kde_curve']`，响应 JSON 含该字段。
2. 实现 `compute_kde_curve` 的 `degraded`/`reason` 参数；仅捕获 `MemoryError`，其它异常行为不变。
3. `compute_histogram_stats` 两次 KDE 调用传 `degraded` 与 reason；返回 dict 加 `'degraded': list(degraded or [])`。
4. `analysis_views.histogram` 建 `degraded=[]`，传给 `compute_histogram_stats`。
5. 跑：
   ```bash
   python manage.py test test.backend.test_histogram_degraded test.backend.test_analysis_api
   ```
   （若 `test_analysis_api` 名称不存在，用 `ls test/backend | grep analysis` 找到直方图测试文件。）
6. Commit：`feat(analysis): 直方图 KDE 内存降级可上报`

---

## Task 9: 前端降级提示与错误码

**Files:**
- New: `frontend/src/pages/analysis/histogramDegraded.ts`
- Modify: `frontend/src/pages/analysis/components/HistogramChart.vue`
- Modify: `frontend/src/utils/error.ts`
- Modify: `frontend/test/unit/error.spec.ts`
- New: `frontend/test/unit/histogramDegraded.spec.ts`
- Modify: `frontend/e2e/analysis/histogram.spec.ts`（或现有直方图 e2e）

**Steps:**

1. T2：`histogramDegradedHint([])` → null；`['kde_curve']` → 「内存紧张，已省略 KDE 曲线」；未知 reason 也返回同一句；`undefined/null` 不抛。
2. T2：`error.spec.ts` 增加 `server_busy`、`throttled` 码表断言。
3. 实现 `histogramDegraded.ts`；`error.ts` 两张码表补两行。
4. `HistogramChart.vue`：
   - template 在 `OutlierHintBar` 旁增加 `v-if="degradedText"` 的紧凑提示，`data-degraded-hint`；
   - `degradedText = computed(() => histogramDegradedHint(props.result?.degraded ?? []))`；
   - 样式只认 token，dark/light 都可读；不引发布局跳动（与 `OutlierHintBar` 同形态）。
5. T3：用 `page.route` 拦截 `/analysis/histogram/` 返回 `degraded: ['kde_curve']`，进分析页断言 `[data-degraded-hint]` 可见；再返回空数组断言不可见。放进现有直方图 spec，避免新文件过大。
6. 跑：
   ```bash
   cd frontend && npx vitest run test/unit/error.spec.ts test/unit/histogramDegraded.spec.ts
   cd frontend && E2E_SKIP_BUILD=1 npx playwright test e2e/analysis/histogram.spec.ts --project=P1 --workers=1
   ```
7. Commit：`feat(analysis): 展示 KDE 内存降级提示`

---

## Task 10: 作业排队数与超时下发（后端）

**Files:**
- Modify: `apps/jobs/views.py`
- New: `test/backend/test_jobs_queue_payload.py`

**Interfaces:**
- `_job_payload(job, *, with_queue=False)`。
- `queue_position`：同 owner、`status in ('pending','running')`、`created_at < job.created_at`（同刻 `id <`）。
- `timeout_seconds`：`executor.KIND_RUNNERS[job.kind]['timeout']`。
- 提交（202）与详情返回 `queue_position`；列表可省略。

**Steps:**

1. 先写 `test/backend/test_jobs_queue_payload.py`：
   - 同 owner 两个 running 在前，新 job 的 `queue_position=2`；
   - 别的 owner 的 job 不计；
   - terminal job 的 `queue_position=0`；
   - `timeout_seconds` 对四类 kind 分别等于 1800/3600/1800/7200；
   - 列表响应不含 `queue_position`（或为 0，二者取实现并在测试里钉住）。
2. 实现 helper `_queue_position(job)`（一次 `count()`）。
3. `_job_payload` 增加 `with_queue`；提交与详情调用 `with_queue=True`。
4. 跑：
   ```bash
   python manage.py test test.backend.test_jobs_queue_payload apps.jobs.tests_jobs
   ```
   期望 `OK`。
5. Commit：`feat(jobs): 下发排队数与作业超时`

---

## Task 11: 前端排队展示与等待上限对齐

**Files:**
- Modify: `frontend/src/api/jobs.ts`
- Modify: `frontend/src/composables/jobPolling.ts`
- Modify: `frontend/src/composables/useJobExport.ts`
- Modify: `frontend/src/components/common/JobProgressChip.vue`
- Modify: `frontend/src/pages/dashboard/components/ExportFooter.vue`
- Modify: `frontend/src/pages/data/components/export/ExportActions.vue`
- Modify: `frontend/src/pages/data/DataBrowserAgGrid.vue`（只改现有行）
- Modify: `frontend/test/unit/jobExport.spec.ts`
- New: `frontend/test/unit/jobQueue.spec.ts`

**Interfaces:**
- `JobStatus` 增加可选 `queue_position?: number`、`timeout_seconds?: number`。
- `pollTimeoutMs(job): number`：`timeout_seconds*1000 + 60_000`，缺字段回退 `POLL_MAX_MS`。
- `pollDecision` state 增加 `maxMs`；超过 `maxMs` → `giveup`。
- `useJobExport` 返回 `queuePosition`（ref）。
- `JobProgressChip` 新可选 prop `queuePosition?: number`；`active && percent === 0 && queuePosition > 0` 时文本显示 `排队中 · 前面 N 个`，否则显示 `N%`。

**Steps:**

1. T2 `jobQueue.spec.ts`：
   - `pollTimeoutMs({timeout_seconds: 3600}) === 3660000`；
   - 缺字段回退 300000；
   - `pollDecision` 在 `maxMs` 内继续 wait，超过 giveup；
   - `queuePositionText(0)` / `(3)`（若抽纯函数）。
2. 更新 `jobExport.spec.ts` 的既有 `POLL_MAX_MS` 断言（如被替换）。
3. 实现 `pollTimeoutMs`、`pollDecision` 的 `maxMs`、`useJobExport` 的首响应定上限与 `queuePosition`。
4. `JobProgressChip` 增加 prop 与文本分支；callsites 传 `:queue-position="..."`，变量来自各自的 `useJobExport()` 返回值；`DataBrowserAgGrid.vue` 只改现有行（若需新增行，改为在已有模板行内传参）。
5. 跑：
   ```bash
   cd frontend && npx vitest run test/unit/jobQueue.spec.ts test/unit/jobExport.spec.ts
   cd frontend && npm run build
   ```
6. Commit：`feat(jobs): 前端展示排队数并对齐作业超时`

---

## 收口门禁（所有任务完成后）

1. `cd frontend && npx vitest run`
2. `cd frontend && npm run lint:e2e`
3. `cd frontend && npm run build`
4. `python manage.py test test.backend apps.<每个目录>`（按 `scripts/e2e_nightly.mjs:129-136` 枚举，不手打 `apps.*`）
5. `node scripts/e2e_pool.mjs --slots=4`
6. `node scripts/prepush-history-check.mjs`（不 push 也要过一遍历史守卫）
7. 更新 `docs/tasks/todo.md` 的台账与门禁表；整枝终审后再更新。
