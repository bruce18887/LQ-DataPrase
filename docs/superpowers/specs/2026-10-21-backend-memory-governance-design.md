# 后端内存治理设计（2026-10-21）

状态：设计已确认，待拆实现计划
适用形态：服务器单进程（约 20 人）+ Electron 桌面打包版

## 1. 触发事件与基线

2026-10-20 22:33:23，`POST /api/v1/analysis/histogram/` 在
`GaussianKDE.__call__` 分配 `(200, 1766)` float64（2.69 MiB）时抛
`_ArrayMemoryError`。同一时刻的系统证据：

| 证据 | 读数 | 出处 |
|---|---|---|
| Windows 低虚拟内存事件 | 22:32:58，事件 2004 | Windows 系统日志 |
| 占用大户 | python.exe ×3 各 1.0–1.1 GB；NVIDIA Overlay 1.1 GB | 同上 |
| 页面文件 | 22:33:28 Volsnap 报无法扩展 | Windows 系统日志 |
| 干净进程 KDE 峰值 | 1766 样本 8.09 MiB / 4.0 ms；16384 样本 75.0 MiB / 34.3 ms | 2026-10-21 项目 venv 实测（Python 3.13.12 / numpy 2.4.6） |
| 事后机器状态 | RAM 31.8 GB，commit 30.9/39.4 GB（空闲 8.4 GB），页面文件分配 4.97 GB | 2026-10-21 本机实测 |

结论：这不是算法在 1766 个样本上的缺陷，而是**机器级提交内存（commit）耗尽**；
KDE 只是在最后一次小分配上撞墙。现有后端没有预算、压力响应或隔离机制，同类问题
会以任意端点、任意 500 的形式再次出现。

### 1.1 现有相关事实

- 服务器档：单进程 Django + SQLite，无 nginx，约 20 人（`config/settings/server.py`）。
- 解析缓存：进程内字节预算 LRU，默认 1536 MB（`apps/datafiles/services.py:29`）。
- 作业：`ProcessPoolExecutor`，`MAX_POOL_WORKERS = min(4, max(2, cpu//2))`
  （`apps/jobs/executor.py:37`），CPU worker 禁 Django。
- 指标：`GET /api/v1/metrics/` 已有 RSS / 缓存 / 作业 / 延迟环形采样
  （`apps/common/metrics.py`），仅管理员可读。
- 异常：未捕获异常统一 500 JSON（`apps/common/exceptions.py:96`），没有
  `MemoryError` 专门分支。
- 前端：axios 拦截器优先展示后端 `message`（`frontend/src/utils/error.ts`），
  503 不需要新的提示管线。
- 依赖：`psutil 7.2.2` 目前只是 py7zr 的传递依赖，未显式声明。

## 2. 目标与非目标

### 2.1 目标

1. 把内存变成**有预算、有水位、可观测**的资源，而不是出事后再猜。
2. 压力下按「自愈 → 限流 → 失败」处理，内存不足不再以未处理 500 的形式出现。
3. 失控导出只死作业，不拖死 Web 进程；Web 进程靠准入控制而非进程隔离。
4. 可选图层降级必须对用户可见，不静默改变图表语义。
5. 留下可复现的峰值清单、压测脚本和运维手册。

### 2.2 非目标

- 不改多进程 Web 服务形态（SQLite + 单进程是既定决策）。
- 不为交互式分析端点做进程隔离（DataFrame IPC 成本高于收益）。
- 不改导出作业的产物语义；导出失败仍是失败，不静默降级。
- Electron 后端 watchdog / 自动重启列为可选后续项，不进这三批。
- 不按实时可用内存做准入（避免阈值抖动），只把它作为系统级诊断指标。

## 3. 总体结构

```
                 ┌─────────────────────────────┐
                 │ apps/common/memory.py       │
                 │ 预算 / 水位 / 系统内存快照   │
                 └───────┬─────────┬───────────┘
                         │         │
         ┌───────────────┘         └────────────────┐
         ▼                                          ▼
┌──────────────────┐                     ┌────────────────────┐
│ 解析缓存预算       │                     │ apps/common/metrics│
│ datafiles/services│                     │ /metrics 新字段     │
└──────────────────┘                     └────────────────────┘
         │
         ▼
┌──────────────────┐    soft 淘汰 / hard 拒绝 / MemoryError 503
│ 准入控制           │◄──────────────────────────────────────────
│ admission.py      │
└────────┬─────────┘
         ▼
┌──────────────────┐    KDE MemoryError → degraded（仅直方图）
│ 分析端点           │
└──────────────────┘
         │
         ▼
┌──────────────────┐    worker 硬上限：Linux rlimit / Windows Job Object
│ 作业进程池         │
└──────────────────┘
```

## 4. 预算模型

### 4.1 总预算

```
total_ram = psutil.virtual_memory().total
            ↳ 取不到时用 LQDP_TOTAL_RAM_MB，再退回 4 GB
budget    = LQDP_MEMORY_BUDGET_MB
            ↳ 未配时 clamp(total_ram × 0.5, 1.5 GB, 8 GB)
```

- 50% 是默认留白：服务器上的 OS 文件缓存、SQLite、桌面端 Electron 与其它应用
  都要留空间。服务器实测后可经 env 上调。
- 8 GB 上限是默认值，不是硬限制；需要更大预算时显式配置，并重跑峰值清单与压测。
- 显式 `LQDP_MEMORY_BUDGET_MB` 低于 1.5 GB 时按 1.5 GB 地板起用
  （`max(MIN_BUDGET_BYTES, ...)`）；当前**不为此打 warning**，配置者需自行确认。
- 取不到 psutil 时 budget 仍需可用：用 env 兜底并 **warning 一次**，不静默按
  4 GB 假装准确。

### 4.2 分配

```
jobs_budget   = min(2 GB, budget × 40%)
web_budget    = budget - jobs_budget
cache_budget  = LQDP_PARSE_CACHE_MB
                ↳ 未配时 min(1536 MB, web_budget × 60%)
working_budget = web_budget - cache_budget   # 只用于读数/阈值，不是硬上限
```

| 机器 RAM | budget | jobs | web | cache | working | soft 75% | hard 90% |
|---|---|---|---|---|---|---|---|
| 8 GB | 4.0 GB | 1.6 GB | 2.4 GB | 1.44 GB | 0.96 GB | 1.80 GB | 2.16 GB |
| 16 GB | 8.0 GB | 2.0 GB | 6.0 GB | 1.50 GB | 4.50 GB | 4.50 GB | 5.40 GB |
| 32 GB+ | 8.0 GB（默认上限） | 2.0 GB | 6.0 GB | 1.50 GB | 4.50 GB | 4.50 GB | 5.40 GB |

- 8 GB 机器是「能跑但紧」的下限；大文件场景建议 16 GB 起。
- 32 GB 以上默认仍取 8 GB；服务器要更大预算必须显式 `LQDP_MEMORY_BUDGET_MB`，
  并接受对应压测。
- 作业预留（40% / 2 GB 封顶）是给并发导出留的余量：导出与交互请求同时跑时，
  不能让 worker 把 Web 预算也吃掉。
- 显式 `LQDP_PARSE_CACHE_MB` 超过 `web_budget` 时夹到 `web_budget`；当前**不为此
  打 warning**。`0` 仍表示关闭解析缓存。

### 4.3 水位

```
used_ratio = process_rss / web_budget
level = normal   < 75%
        soft     75%–90%
        hard     ≥ 90%
```

- 比例是**初始值**；批 1 的峰值清单会给出 baseline 与各端点峰值，再决定是否调整。
- soft：重活请求入口把解析缓存淘汰到 `cache_budget / 2`。
- hard：批 1 先淘汰；批 2 起拒绝新重活。
- 系统级提交内存只进指标与启动 warning，不作为准入判据：本次事故是别的进程吃满
  commit，单看本进程 RSS 无法提前发现。

### 4.4 配置项

| 变量 | 默认 | 批次 | 说明 |
|---|---|---|---|
| `LQDP_MEMORY_BUDGET_MB` | RAM × 50%，夹取 1.5–8 GB | 1 | 总预算覆盖 |
| `LQDP_TOTAL_RAM_MB` | 4 GB | 1 | 仅在 psutil 取不到总 RAM 时兜底 |
| `LQDP_PARSE_CACHE_MB` | `min(1536, web × 60%)` | 1（既有） | 解析缓存预算；`0` 仍表示关闭缓存 |
| `LQDP_HEAVY_CONCURRENCY` | 2 | 2 | 重活并发上限，夹取 1–8 |
| `LQDP_HEAVY_WAIT_S` | 10 | 2 | 重活等待上限，夹取 0–60 |
| `LQDP_JOB_MEMORY_MB` | `max(384, jobs_budget_MB ÷ workers)` | 3 | 单个作业 worker 硬上限 |

## 5. 可观测

### 5.1 `/api/v1/metrics/` 新增

`memory`：

```
budget_bytes, jobs_budget_bytes, web_budget_bytes, cache_budget_bytes,
private_bytes, used_ratio, level,
system: { total_bytes, available_bytes, commit_used_bytes, commit_limit_bytes }
```

- `private_bytes`：Windows 取进程提交量；其它平台取 RSS 或 null。
- `system.*`：psutil + 平台实现；取不到为 null，不写 0。
- Windows commit：`GetPerformanceInfo`（ctypes）；Linux：`/proc/meminfo` 的
  `CommitLimit` / `Committed_AS`。
- `level` 是字符串 `normal|soft|hard`，不是布尔，便于日志与前端后续消费。

`admission`（批 2）：

```
inflight, waiting, rejected_busy, rejected_oom, degraded
```

`worker_limits` 新增（批 3）：

```
supported, cap_bytes, reason
```

`parse_cache` 增补：

```
hits, misses, evictions, clears
```

现有 `entries / bytes / budget_bytes / in_flight` 保留。

### 5.2 启动日志

```
内存预算: total_ram=31.8GB budget=8.0GB jobs=2.0GB web=6.0GB
          cache=1.5GB system_available=15.6GB commit=30.9/39.4GB
```

- 空闲 commit < budget：warning 一行，直接暴露「机器已被别的进程压住」的形态。
- 日志只打一次，不随请求刷。
- `config/settings/base.py` 为 `apps.common.memory` 配 INFO 级控制台 handler
  （`propagate=False`、`disable_existing_loggers=False`）：Django 默认只给
  `django.*` 挂 handler，不显式配置的话这行会被直接丢掉（批 1 已修，并有
  「logger 有效级别 = INFO + `_log_plan` 产出记录」的测试钉住）。

### 5.3 依赖

- `psutil==7.2.2` 写入 `requirements/base.txt`，从传递依赖提升为显式依赖。
- PyInstaller 打包验证见 §9；若钩子不可用，`memory.py` 退回 ctypes / `/proc`，
  指标字段为 null，不阻塞启动。

## 6. 准入控制（批 2）

### 6.1 登记

- `HeavyActionMixin`：ViewSet 类顶声明 `heavy_actions = frozenset({...})`；
  在 `initial()` 里按 `self.action` 取槽，在 `finalize_response()` 的 `finally`
  释放；`initial()` 自身抛异常（含 `ServerBusy`）时先退出上下文再上抛。
  **不要覆写 `dispatch()`**：DRF 在 `ViewSetMixin.initialize_request()` 里才设置
  `self.action`，而它在 `APIView.dispatch()` 内部执行 —— mixin 的 `dispatch()`
  覆写体运行时 `self.action` 仍是 `None`，名单里的动作永远不会取槽；且在那里
  抛出的 `ServerBusy` 位于 `APIView.dispatch()` 的 try/except 之外，会变成 500
  而不是 503 信封。（`apps/common/admission.py` 需 `import sys`。）

  ```python
  class HeavyActionMixin:
      heavy_actions = frozenset()
      _heavy_ctx = None

      def initial(self, request, *args, **kwargs):
          # ViewSetMixin.initialize_request has already set self.action here.
          action = getattr(self, 'action', None)
          self._heavy_ctx = None
          if action in self.heavy_actions:
              self._heavy_ctx = heavy_slot(action)
              self._heavy_ctx.__enter__()      # ServerBusy is now inside APIView.dispatch's try
          try:
              return super().initial(request, *args, **kwargs)
          except Exception:
              if self._heavy_ctx is not None:
                  self._heavy_ctx.__exit__(*sys.exc_info())
                  self._heavy_ctx = None
              raise

      def finalize_response(self, request, response, *args, **kwargs):
          try:
              return super().finalize_response(request, response, *args, **kwargs)
          finally:
              if self._heavy_ctx is not None:
                  self._heavy_ctx.__exit__(None, None, None)
                  self._heavy_ctx = None
  ```

- 加 mixin 的类：`AnalysisViewSet`、`StatisticsViewSet`、`GageViewSet`、
  `BuyoffViewSet`、`BatchReportViewSet`。
- 初版登记（峰值清单后增删，覆盖测试跟着改）：
  - 分析：`histogram`、`wafer_map`、`multi_lot`、`correlation`、
    `correlation_matrix`、`boxplot`、`qqplot`、`cpk`、`bin_stats`、`bin_trend`、
    `param_trend`、`zonal_yield`、`serial_distribution`、`uph`、`detect_fail`、
    `file_correlation_serials`、`file_correlation`、`file_correlation_export`；
  - Gage：`generate_summary`；
  - Buyoff：`identify_common_items`、`generate_form`；
  - Batch report：`batch_html_report`、`generate_report`。
- 轻端点（`list_batches`、`site_stats` 等）默认不进名单；峰值清单证明其重后再加。
- 同步导出的降级路径（`apps/jobs/views.py` 的 `_sync_fallback`，由
  `executor_available() == False` 触发）也取同一信号量，避免作业池不可用时绕开准入。
- T1 覆盖测试：`heavy_actions` 必须是该 ViewSet 真实 action 的子集，且 §6.1 的
  端点清单在测试里逐项钉住；新增重活端点忘登记会被测出来。视图级再钉两条：
  持槽时重活 action 返回 503 `server_busy` + `Retry-After: 5`；未登记动作不得
  进入 `heavy_slot`（证明 mixin 不是静默失效）。

### 6.2 时序

```
relief_if_soft()
  ↓
acquire(semaphore, timeout=WAIT_SECONDS)
  ↓ timeout → 503 server_busy + Retry-After: 5
check hard → 先淘汰缓存 → 仍超 → release + 503 server_busy(detail.reason='memory')
  ↓
execute
  ↓ MemoryError → clear cache + count → 503 out_of_memory
```

- 默认容量 2（`LQDP_HEAVY_CONCURRENCY`，夹取 1–8），等待 10s
  （`LQDP_HEAVY_WAIT_S`，夹取 0–60）。
- mixin 生命周期：槽在 `initial()` 取得 —— `ServerBusy` 因此位于
  `APIView.dispatch()` 的 try 内，走 §6.3 的 503 信封；成功或失败都由
  `finalize_response()` 的 `finally` 释放，异常路径不会泄漏信号量。
- 时序图里的「清缓存 + count」是 **best-effort**：动作自身失败不改变 503 结果
  （详见 §6.3）。
- 只拦重活，登录 / 列表 / 浏览不受影响。
- 线程内嵌套用 depth 计数器；跨进程不共享（当前单进程形态成立；若未来多 worker，
  预算与信号量都要按进程拆分，见 §11）。
- 拒绝日志 10s 限频。
- 状态码 503；不引入 507。

### 6.3 错误信封

```
{"code":"server_busy","message":"服务器繁忙，请稍后重试","detail":{"reason":"memory"}}
{"code":"out_of_memory","message":"服务器内存不足，请关闭其他任务后重试","detail":{"path":"/api/v1/analysis/histogram/"}}
```

- 两个码都加入 `frontend/src/utils/error.ts` 的 `ERROR_CODE_MAP` 兜底；后端
  `message` 优先，现有 toast 管线不改。
- `MemoryError` 分支的清缓存与 OOM 计数都是 **best-effort**（`_run_best_effort`）：
  清缓存自身再抛 `MemoryError` 时只留 ERROR 日志，`record_oom` 仍入账；懒导入
  失败时两项副作用都跳过。任何情况下 503 `out_of_memory` 信封都优先返回。
- 不吞其它异常：非 `MemoryError` 的未捕获异常仍按现状 500。

## 7. 降级契约（批 2）

- `compute_kde_curve(..., degraded=None)`：
  - `degraded` 为 list：捕获 `MemoryError`，追加原因码，返回 `None`；
  - `degraded` 为 None：继续抛出（multi-lot、导出保持失败可见）。
- `compute_histogram_stats(..., degraded=None)`：透传给两次 KDE 调用；响应每个
  参数固定带 `degraded: []`（空数组也带，契约稳定）。默认 `None` 不改变现有
  调用方行为：没传列表的路径仍让 `MemoryError` 上抛。
- 原因码：`kde_curve`、`filtered_kde_curve`。
- `HistogramChart.vue`：`degraded.length > 0` 时在图表上方显示紧凑提示
  「内存紧张，已省略 KDE 曲线」；复用 `OutlierHintBar` 的形态与既有 token，
  dark/light 都可见，不引发布局跳动；加 `data-degraded-hint` 供 e2e 定位。
- 提示文案由纯函数 `histogramDegradedHint(reasons)` 产出（新模块
  `frontend/src/pages/analysis/histogramDegraded.ts`），T2 钉住。
- 导出：不降级。KDE 失败让作业失败并给出可读原因；导出文件不能悄悄缺曲线。
- 多文件（multi_lot）：本批不降级，保持抛出；如后续要降级，必须同时设计该卡片
  的可见提示。

## 8. 作业 worker 硬上限（批 3）

### 8.1 模块与算法

- `apps/jobs/worker_limits.py`：Django-free、spawn-safe。
- `resolve_worker_cap(jobs_budget_mb, workers, env)`：默认
  `max(384 MB, jobs_budget_mb ÷ workers)`，`LQDP_JOB_MEMORY_MB` 覆盖。
- Linux：`resource.setrlimit(RLIMIT_AS, (cap, cap))`。
- Windows：Job Object + `JOB_OBJECT_LIMIT_PROCESS_MEMORY`，worker 自 assign，
  句柄常驻。
- 设置失败：启动 warning + `worker_limits.supported=false`；不假装有上限。

### 8.2 接线

- `ProcessPoolExecutor(max_workers=..., initializer=apply_worker_cap,
  initargs=(cap_bytes,))`。
- `warmup_imports` 与所有导出任务都在受限 worker 内。
- worker 越界 → 该 future 抛 `MemoryError` → 作业标失败、原因可读；Web 进程与
  其它 worker 继续服务。

### 8.3 风险与验证

- `RLIMIT_AS` 约束虚拟地址空间，OpenBLAS / 线程栈可能预留很大；先用峰值清单
  量最大导出的峰值，再定 384 MB 是否够。不够就抬上限或降 `MAX_POOL_WORKERS`，
  不放任误杀。
- 子进程测试：小上限（64–128 MB）故意越界，断言 `MemoryError`；Linux 走 CI，
  Windows 走本机。
- 不做运行中杀 worker / 定向替换；碎片问题出现再评估 `max_tasks_per_child`。

## 9. 测试与验收

| 层 | 覆盖 |
|---|---|
| T1 | 预算公式/夹取/env/psutil 缺失；缓存预算派生与计数器；水位判定；准入容量/超时/释放/嵌套/hard 拒绝；`MemoryError` → 503 + 清缓存；degraded 契约；worker cap 子进程测试；`heavy_actions` 覆盖 |
| T2 | 错误码 → 文案；degraded 原因 → 提示文案 |
| T3 | 一条直方图 route 拦截用例（不依赖真实 OOM），断言降级提示在 dark/light 都可见 |

- 峰值清单：`scripts/memory_profile.py`，人工运行，不进 CI。批 1 先做
  baseline + KDE + 直方图，批 3 扩展到全部重活端点与导出。
- 批 1 实测（2026-10-21，`config.settings.unit`，`scripts/memory_profile.py`）：
  baseline ≈ 96 MiB；`GaussianKDE.__call__`（16384 样本 × 200 网格）
  4.9–7.4 MiB / 17.4 ms；直方图含 KDE 6.7–8.7 MiB / 22 ms。
  **75/90（水位）、60%（缓存占比）与批 2 的 2 并发 / 批 3 的 384 MB 初始值
  均保持不变** —— 实测没有给出需要调整它们的证据。
- 压测：`scripts/memory_load20.py`（或给 `perf_load20.py` 加 `--memory`），
  20 并发直方图，记录峰值 RSS、503 数、P95。
- 验收：
  1. 压测无未处理 500；503 只出现在 hard / 超时，且信封完整；
  2. 峰值 RSS 不越 `web_budget`；缓存淘汰后能恢复；
  3. 导出 worker 越界时服务仍活，作业失败原因可读；
  4. `npm run dist:win` 成功，打包版 `/metrics/` 能取到预算字段，worker 初始化
     不报错；
  5. 现有 KDE golden / scipy 对照用例全绿，新增峰值上限用例通过。
- 门禁按 `docs/reference/testing-gates.md`：批内 affected，收口全量池 + 后端全套。
  新增的 dev-only 脚本/文档若被 affected 判为未知路径，按该文档的放行类目处理；
  确需加规则时同步补 `frontend/test/unit/e2eAffectedDecide.spec.ts`，不为这类
  改动跑全量。

## 10. 分批实施

### 批 1：预算 + 指标 + 自愈 + KDE

- 新增 `apps/common/memory.py`；扩展 `metrics.py`；`datafiles/services.py`
  预算派生；`kde.py` 分块 + 原地运算；`exceptions.py` 的 `MemoryError`
  分支；`requirements/base.txt` 的 psutil；`scripts/memory_profile.py` 的
  baseline + KDE/直方图测量；测试。
- 先跑 baseline 测量（现有最大样例；缺样例时用合成数据并标注），再定 75/90 与
  60% 是否保留。
- 验收：新指标可见、KDE 峰值下降且输出不变、`MemoryError` 503 契约。

### 批 2：准入 + 降级

- `apps/common/admission.py`；各 ViewSet `heavy_actions`；
  `compute_histogram_stats` / `compute_kde_curve` 的 degraded；
  `HistogramChart.vue` 提示；`histogramDegraded.ts`；`error.ts` 两个码；
  `apps/jobs/views.py` 的同步降级路径接信号量；指标 `admission`；T1 / T2 / T3。
- 验收：20 并发下 503 行为正确；降级提示双主题可见；未登记重活端点被覆盖测试抓出。

### 批 3：隔离 + 运维

- `apps/jobs/worker_limits.py` + executor 接线；峰值脚本扩展到全部重活端点；
  `scripts/memory_load20.py`；`docs/reference/memory-runbook.md`；打包验证。
- 验收：worker 越界测试；压测报告；打包版验证；手册可照着处置一次演练。

## 11. 风险与开放问题

1. **服务器 OS 未定**：硬上限两套都实现并按平台选；不支持的平台显式
   `worker_limits.supported=false`。
2. **`RLIMIT_AS` 与 OpenBLAS**：可能过度约束虚拟地址空间；以峰值清单为准，
   必要时改用 `RLIMIT_DATA` 或软监控。
3. **阈值初值**：75/90、60%、2 并发、384 MB 都是初始值，必须由批 1/3 的实测
   确认或调整。
4. **psutil + PyInstaller**：需打包验证；失败则退回 ctypes / `/proc`，指标字段
   为 null。
5. **多进程未来**：若服务器改多 worker，预算是整机还是每进程、信号量是否跨进程，
   必须重新设计；当前不做。
6. **Electron watchdog**：可选后续；不在三批内。
7. **Linux commit 指标**：overcommit 下 `CommitLimit/Committed_AS` 只作诊断参考，
   不参与准入。

## 12. 文件清单

新增：

- `apps/common/memory.py`
- `apps/common/admission.py`
- `apps/jobs/worker_limits.py`
- `scripts/memory_profile.py`
- `scripts/memory_load20.py`
- `docs/reference/memory-runbook.md`
- `frontend/src/pages/analysis/histogramDegraded.ts`
- `test/backend/test_memory_budget.py`
- `test/backend/test_admission.py`
- `test/backend/test_worker_limits.py`
- `frontend/test/unit/histogramDegraded.spec.ts`
- `frontend/e2e/analysis/histogram-degraded.spec.ts`

修改：

- `apps/common/metrics.py`
- `apps/common/exceptions.py`
- `apps/datafiles/services.py`
- `apps/analysis/services/statistics/kde.py`
- `apps/analysis/services/data_services/histogram.py`
- `apps/analysis/views/analysis_views.py`
- `apps/analysis/views/statistics_views.py`
- `apps/gage/views.py`
- `apps/buyoff/views.py`
- `apps/batch_report/views.py`
- `apps/jobs/executor.py`
- `apps/jobs/tests_jobs.py`
- `apps/jobs/views.py`
- `frontend/src/pages/analysis/components/HistogramChart.vue`
- `frontend/src/utils/error.ts`
- `requirements/base.txt`
- `apps/common/tests_metrics.py`
- `apps/datafiles/tests_parse_cache.py`
- `test/backend/test_kde_numpy.py`
- `frontend/test/unit/error.spec.ts`

## 13. 关键取舍

- **503 而不是 507**：507 是 WebDAV 语义；503 + `Retry-After` 是过载/暂时不可用
  的标准表达，前端 axios 管线现成。
- **系统 commit 不参与准入**：本次事故是别的进程吃满 commit，本进程 RSS 正常；
  用它做准入会在机器被别的应用压住时误伤所有用户。它只进指标和启动 warning。
- **交互式分析不做进程隔离**：DataFrame 跨进程序列化 / 共享内存的复杂度高于收益；
  准入控制 + 算法峰值 + 缓存预算足够覆盖 20 人档。
- **导出不降级**：导出的产物是交付物，缺曲线比失败更糟；失败带原因，用户可重试。
- **降级必须可见**：任何 `degraded` 响应都有 UI 提示；不允许静默改变图表语义。

## 14. 参考

- `docs/reference/testing-gates.md`
- `docs/tasks/lessons.md` 2026-10-18 / 2026-10-21 提交内存条目
- `docs/reference/perf-baseline-2026-10-17.md`
- `docs/reference/server-deployment.md`
- 事故现场：2026-10-20 22:32:58 系统事件 2004；22:33:23 histogram 500。
