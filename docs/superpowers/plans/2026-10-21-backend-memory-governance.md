# 后端内存治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把后端内存做成有预算、有水位、可观测、可降级的资源，并给作业 worker 加硬上限，避免再次出现「2.69 MiB 分配失败 → 整张直方图 500」。

**Architecture:** 批 1 建预算内核与指标，解析缓存预算从内核派生，KDE 改分块原地运算，`MemoryError` 统一 503；批 2 用信号量限制重活并发，直方图 KDE 可降级且提示可见；批 3 给 `ProcessPoolExecutor` worker 加 Linux rlimit / Windows Job Object 硬上限，补峰值清单、20 并发压测与运维手册。服务器与桌面共用同一套内核。

**Tech Stack:** Django 6 + DRF、numpy / pandas、Vue 3 + Element Plus + ECharts、vitest、Playwright、psutil。

**Spec:** `docs/superpowers/specs/2026-10-21-backend-memory-governance-design.md`

## Global Constraints

- **单进程形态**：服务器档是单进程 Django + SQLite；预算、缓存、信号量都按单进程假设。不要引入多 worker。
- **不静默降级**：任何 `degraded` 响应必须有可见 UI 提示；导出与 multi-lot 不降级，失败要报错。
- **异常口径**：`MemoryError` → 503 `out_of_memory`；`ServerBusy` → 503 `server_busy`；其它未捕获异常仍 500。不吞其它异常。
- **双主题**：新增前端样式只用既有 token（`var(--warn)` 等），dark / light 都要可见。
- **文件规模**：单个 Vue / Django 源文件不超过 600 行。
- **测试分层**：按 `docs/reference/testing-gates.md`；批内 affected，收口全量池 + 后端全套；判绿取日志末尾 `RESULT:`，不取 `$?`。
- **不 push**：每个任务只 commit；push 需单独点名。
- **依赖**：`psutil==7.2.2` 提升为显式依赖；`requirements/base.txt` 的每条都必须钉版本。
- **测量优先**：75/90、60%、2 并发、384 MB 都是初始值；批 1/3 的峰值清单跑出来后，按数据调整并同步测试。

---

## File Structure

**新增**

| 文件 | 责任 |
|---|---|
| `apps/common/memory.py` | 预算公式、水位、系统 commit 快照、OOM 计数、启动日志 |
| `apps/common/admission.py` | 重活信号量、`ServerBusy`、准入计数、`HeavyActionMixin` |
| `apps/jobs/worker_limits.py` | worker 内存上限（Django-free、spawn-safe） |
| `scripts/memory_profile.py` | 峰值清单（人工运行，不进 CI） |
| `scripts/memory_load20.py` | 20 并发内存压测（人工运行） |
| `docs/reference/memory-runbook.md` | 运维手册 |
| `frontend/src/pages/analysis/histogramDegraded.ts` | degraded 原因 → 提示文案（纯函数） |
| `test/backend/test_memory_budget.py` | 预算 / 503 契约 |
| `test/backend/test_admission.py` | 准入 / 覆盖测试 |
| `test/backend/test_worker_limits.py` | worker 上限纯函数与子进程测试 |
| `frontend/test/unit/histogramDegraded.spec.ts` | T2 提示文案 |
| `frontend/e2e/analysis/histogram-degraded.spec.ts` | T3 降级提示接线 |

**修改**

| 文件 | 改动 |
|---|---|
| `apps/common/metrics.py` | `memory`、`admission`（批 2）、`worker_limits`（批 3）对象；`parse_cache` 计数器 |
| `apps/common/exceptions.py` | `MemoryError` / `ServerBusy` 分支 |
| `apps/datafiles/services.py` | 缓存预算从 memory 派生；hits/misses/evictions/clears；`evict_to` / `evict_parse_cache_to` |
| `apps/analysis/services/statistics/kde.py` | 分块 + 原地运算 |
| `apps/analysis/services/data_services/histogram.py` | `degraded` 参数与原因码 |
| `apps/analysis/views/analysis_views.py` | `HeavyActionMixin`、`heavy_actions`、degraded 记录 |
| `apps/analysis/views/statistics_views.py` | `HeavyActionMixin`、`heavy_actions` |
| `apps/gage/views.py` / `apps/buyoff/views.py` / `apps/batch_report/views.py` | 同上 |
| `apps/jobs/executor.py` | 进程池 initializer 接 worker cap |
| `apps/jobs/views.py` | 同步导出降级路径取重活槽 |
| `apps/jobs/tests_jobs.py` | 池 initializer 接线测试 |
| `frontend/src/pages/analysis/components/HistogramChart.vue` | 降级提示条 |
| `frontend/src/utils/error.ts` | `server_busy` / `out_of_memory` 兜底文案 |
| `requirements/base.txt` | `psutil==7.2.2` |
| `apps/common/tests_metrics.py` | 逐键契约更新 |
| `apps/datafiles/tests_parse_cache.py` | 预算派生与计数器测试 |
| `test/backend/test_kde_numpy.py` | 峰值上限用例 |
| `frontend/test/unit/error.spec.ts` | 两个新错误码 |

---

## 批 1：预算 + 指标 + 自愈 + KDE

> **批 1 已实施（2026-10-21）**：`apps/common/memory.py`、`apps/datafiles/services.py`、
> `apps/common/metrics.py`、`apps/analysis/services/statistics/kde.py`、
> `apps/common/exceptions.py`、`scripts/memory_profile.py` 是唯一事实来源。下面代码块
> 已与入库版本对齐；两者若再不一致，以入库文件为准，并回来更新本计划。

### Task 1: 内存预算内核

**Files:**
- Create: `apps/common/memory.py`
- Test: `test/backend/test_memory_budget.py`

**Interfaces:**
- Consumes: `psutil`（缺失时 env 兜底）
- Produces:
  - `env_int(name: str, default: int, *, minimum=None, maximum=None) -> int`
  - `env_mb(name: str) -> int | None`
  - `total_ram_bytes() -> int`
  - `compute_budget(total_ram: int, *, budget_mb=None, cache_mb=None) -> MemoryBudget`
  - `MemoryBudget.budget_bytes / jobs_budget_bytes / web_budget_bytes / cache_budget_bytes / working_budget_bytes`
  - `MemoryBudget.level(rss_bytes: int | None) -> str | None`
  - `get_budget() -> MemoryBudget`（进程内缓存）
  - `reset_budget_for_tests() -> None`
  - `system_memory_snapshot() -> dict`
  - `process_private_bytes() -> int | None`
  - `memory_snapshot(rss_bytes=_UNSET) -> dict`（`_UNSET` = 自己读 RSS；显式 `None` = 上游拿不到）
  - `record_oom() / oom_events() -> int`

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_memory_budget.py`：

```python
"""T1：内存预算公式、env 覆盖、水位与系统快照。"""
import os
import sys
from unittest import mock

from django.test import SimpleTestCase

from apps.common import memory

GB = 1024 ** 3
MB = 1024 ** 2


class BudgetMathTests(SimpleTestCase):
    def test_default_budget_is_half_ram_capped(self):
        plan = memory.compute_budget(16 * GB)
        self.assertEqual(plan.budget_bytes, 8 * GB)
        self.assertEqual(plan.jobs_budget_bytes, 2 * GB)
        self.assertEqual(plan.web_budget_bytes, 6 * GB)
        self.assertEqual(plan.cache_budget_bytes, 1536 * MB)

    def test_8gb_machine_cache_scales_with_web_budget(self):
        plan = memory.compute_budget(8 * GB)
        self.assertEqual(plan.budget_bytes, 4 * GB)
        self.assertEqual(plan.jobs_budget_bytes, int(4 * GB * 0.4))
        self.assertEqual(plan.web_budget_bytes, 4 * GB - int(4 * GB * 0.4))
        self.assertEqual(plan.cache_budget_bytes, int(plan.web_budget_bytes * 0.6))

    def test_small_ram_hits_floor(self):
        self.assertEqual(memory.compute_budget(2 * GB).budget_bytes, 1536 * MB)

    def test_large_ram_uses_default_cap(self):
        self.assertEqual(memory.compute_budget(64 * GB).budget_bytes, 8 * GB)

    def test_explicit_budget_can_exceed_default_cap(self):
        plan = memory.compute_budget(32 * GB, budget_mb=16384)
        self.assertEqual(plan.budget_bytes, 16 * GB)
        self.assertEqual(plan.jobs_budget_bytes, 2 * GB)
        self.assertEqual(plan.web_budget_bytes, 14 * GB)
        self.assertEqual(plan.cache_budget_bytes, 1536 * MB)

    def test_cache_env_zero_disables_cache(self):
        self.assertEqual(memory.compute_budget(16 * GB, cache_mb=0).cache_budget_bytes, 0)

    def test_cache_env_cannot_exceed_web_budget(self):
        plan = memory.compute_budget(16 * GB, cache_mb=99999)
        self.assertEqual(plan.cache_budget_bytes, plan.web_budget_bytes)

    def test_level_thresholds_and_unavailable(self):
        plan = memory.compute_budget(16 * GB)
        web = plan.web_budget_bytes
        self.assertEqual(plan.level(int(web * 0.74)), 'normal')
        self.assertEqual(plan.level(int(web * 0.75)), 'soft')
        self.assertEqual(plan.level(int(web * 0.90)), 'hard')
        self.assertIsNone(plan.level(None))


class EnvTests(SimpleTestCase):
    def tearDown(self):
        memory.reset_budget_for_tests()

    def test_invalid_budget_env_falls_back_with_warning(self):
        with mock.patch.object(memory, 'total_ram_bytes', return_value=16 * GB), \
             mock.patch.dict(os.environ, {'LQDP_MEMORY_BUDGET_MB': 'big'}):
            memory.reset_budget_for_tests()
            with self.assertLogs('apps.common.memory', level='WARNING'):
                plan = memory.get_budget()
        self.assertEqual(plan.budget_bytes, 8 * GB)

    def test_env_override_and_cache_override(self):
        with mock.patch.object(memory, 'total_ram_bytes', return_value=16 * GB), \
             mock.patch.dict(os.environ, {
                 'LQDP_MEMORY_BUDGET_MB': '4096',
                 'LQDP_PARSE_CACHE_MB': '512',
             }):
            memory.reset_budget_for_tests()
            plan = memory.get_budget()
        self.assertEqual(plan.budget_bytes, 4 * GB)
        self.assertEqual(plan.cache_budget_bytes, 512 * MB)

    def test_missing_psutil_falls_back_to_env_total(self):
        with mock.patch.dict(sys.modules, {'psutil': None}), \
             mock.patch.dict(os.environ, {'LQDP_TOTAL_RAM_MB': '2048'}):
            with self.assertLogs('apps.common.memory', level='WARNING'):
                self.assertEqual(memory.total_ram_bytes(), 2 * GB)


class SnapshotTests(SimpleTestCase):
    def setUp(self):
        memory.reset_budget_for_tests()

    def tearDown(self):
        memory.reset_budget_for_tests()

    def test_snapshot_marks_unavailable_level_as_none(self):
        with mock.patch.object(memory, '_process_rss_bytes', return_value=None), \
             mock.patch.object(memory, 'system_memory_snapshot', return_value={
                 'total_bytes': None, 'available_bytes': None,
                 'commit_used_bytes': None, 'commit_limit_bytes': None,
             }):
            snap = memory.memory_snapshot(None)
        self.assertIsNone(snap['used_ratio'])
        self.assertIsNone(snap['level'])
        self.assertEqual(set(snap['system']), {
            'total_bytes', 'available_bytes',
            'commit_used_bytes', 'commit_limit_bytes',
        })

    def test_oom_counter_increments(self):
        before = memory.oom_events()
        memory.record_oom()
        self.assertEqual(memory.oom_events(), before + 1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_memory_budget -v 2`
Expected: FAIL / ImportError，`apps.common.memory` 不存在。

- [ ] **Step 3: 写最小实现**

创建 `apps/common/memory.py`：

```python
"""后端内存预算与水位（单进程形态）。

预算 = RAM × 50%，夹取 1.5–8 GB；LQDP_MEMORY_BUDGET_MB 显式覆盖可突破 8 GB。
分配 = 作业预留 min(2 GB, 40%) + Web 预算；Web 预算里解析缓存
min(1536 MB, 60%)，其余留给请求计算。水位按进程 RSS / web_budget 判。
"""
import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

MB = 1024 * 1024
GB = 1024 * MB

MIN_BUDGET_BYTES = 1536 * MB
MAX_BUDGET_BYTES = 8192 * MB
DEFAULT_TOTAL_RAM_BYTES = 4 * GB
JOBS_RATIO = 0.4
JOBS_CAP_BYTES = 2048 * MB
CACHE_RATIO = 0.6
CACHE_CAP_BYTES = 1536 * MB
SOFT_RATIO = 0.75
HARD_RATIO = 0.90

_lock = threading.Lock()
_budget = None
_logged = False
_oom_count = 0
_oom_lock = threading.Lock()


def env_int(name, default, *, minimum=None, maximum=None):
    raw = os.environ.get(name)
    if raw is None or raw == '':
        value = int(default)
    else:
        try:
            value = int(raw)
        except ValueError:
            logger.warning('%s=%r 不是整数，按默认 %s 起用', name, raw, default)
            value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_mb(name):
    """返回 MB 整数；未设置/非法返回 None（非法时 warning）。"""
    raw = os.environ.get(name)
    if raw is None or raw == '':
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning('%s=%r 不是整数，忽略该覆盖', name, raw)
        return None


def total_ram_bytes():
    try:
        import psutil
        return int(psutil.virtual_memory().total)
    except Exception:
        fallback_mb = env_int('LQDP_TOTAL_RAM_MB',
                              DEFAULT_TOTAL_RAM_BYTES // MB, minimum=512)
        logger.warning('psutil 取不到总内存，LQDP_TOTAL_RAM_MB 兜底为 %dMB',
                       fallback_mb)
        return fallback_mb * MB


class MemoryBudget:
    __slots__ = ('total_ram_bytes', 'budget_bytes', 'jobs_budget_bytes',
                 'web_budget_bytes', 'cache_budget_bytes')

    def __init__(self, total_ram_bytes, budget_bytes, jobs_budget_bytes,
                 web_budget_bytes, cache_budget_bytes):
        self.total_ram_bytes = int(total_ram_bytes)
        self.budget_bytes = int(budget_bytes)
        self.jobs_budget_bytes = int(jobs_budget_bytes)
        self.web_budget_bytes = int(web_budget_bytes)
        self.cache_budget_bytes = int(cache_budget_bytes)

    @property
    def working_budget_bytes(self):
        return self.web_budget_bytes - self.cache_budget_bytes

    def level(self, rss_bytes):
        if rss_bytes is None or self.web_budget_bytes <= 0:
            return None
        # 阈值先取整到字节：0.90 不是二进制小数，int(web * 0.90) 实际是
        # 0.8999999999 × web，直接比原始比值会把「90% 水位」误判成 soft。
        # 用与调用方相同的算式取整，边界值与 spec 的「≥ 90%」对齐。
        if rss_bytes >= int(self.web_budget_bytes * HARD_RATIO):
            return 'hard'
        if rss_bytes >= int(self.web_budget_bytes * SOFT_RATIO):
            return 'soft'
        return 'normal'


def compute_budget(total_ram, *, budget_mb=None, cache_mb=None):
    if budget_mb is None:
        budget_bytes = max(MIN_BUDGET_BYTES,
                           min(int(total_ram * 0.5), MAX_BUDGET_BYTES))
    else:
        budget_bytes = max(MIN_BUDGET_BYTES, int(budget_mb) * MB)
    jobs = min(JOBS_CAP_BYTES, int(budget_bytes * JOBS_RATIO))
    web = budget_bytes - jobs
    if cache_mb is None:
        cache = min(CACHE_CAP_BYTES, int(web * CACHE_RATIO))
    else:
        cache = min(max(0, int(cache_mb)) * MB, web)
    return MemoryBudget(total_ram, budget_bytes, jobs, web, cache)


def get_budget():
    global _budget, _logged
    if _budget is None:
        with _lock:
            if _budget is None:
                _budget = compute_budget(
                    total_ram_bytes(),
                    budget_mb=env_mb('LQDP_MEMORY_BUDGET_MB'),
                    cache_mb=env_mb('LQDP_PARSE_CACHE_MB'),
                )
                if not _logged:
                    _logged = True
                    _log_plan(_budget)
    return _budget


def reset_budget_for_tests():
    global _budget, _logged
    with _lock:
        _budget = None
        _logged = False


def record_oom():
    global _oom_count
    with _oom_lock:
        _oom_count += 1


def oom_events():
    with _oom_lock:
        return _oom_count


def _process_rss_bytes():
    from apps.common.metrics import process_rss_bytes
    return process_rss_bytes()


def process_private_bytes():
    """Windows 进程提交量；其它平台返回 None（RSS 已由 metrics 提供）。"""
    if not sys.platform.startswith('win'):
        return None
    try:
        import psutil
        info = psutil.Process(os.getpid()).memory_info()
        value = int(getattr(info, 'private', 0))
        return value or None
    except Exception:
        return None


def system_memory_snapshot():
    result = {
        'total_bytes': None,
        'available_bytes': None,
        'commit_used_bytes': None,
        'commit_limit_bytes': None,
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        result['total_bytes'] = int(vm.total)
        result['available_bytes'] = int(vm.available)
    except Exception:
        pass
    if sys.platform.startswith('win'):
        _windows_commit(result)
    elif sys.platform.startswith('linux'):
        _linux_commit(result)
    return result


def _windows_commit(result):
    try:
        import ctypes
        from ctypes import wintypes

        class _PerformanceInformation(ctypes.Structure):
            _fields_ = [
                ('cb', ctypes.c_ulong),
                ('CommitTotal', ctypes.c_size_t),
                ('CommitLimit', ctypes.c_size_t),
                ('CommitPeak', ctypes.c_size_t),
                ('PhysicalTotal', ctypes.c_size_t),
                ('PhysicalAvailable', ctypes.c_size_t),
                ('SystemCache', ctypes.c_size_t),
                ('KernelTotal', ctypes.c_size_t),
                ('KernelPaged', ctypes.c_size_t),
                ('KernelNonpaged', ctypes.c_size_t),
                ('PageSize', ctypes.c_size_t),
                ('HandleCount', ctypes.c_ulong),
                ('ProcessCount', ctypes.c_ulong),
                ('ThreadCount', ctypes.c_ulong),
            ]

        info = _PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        psapi = ctypes.WinDLL('psapi')
        psapi.GetPerformanceInfo.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        psapi.GetPerformanceInfo.restype = wintypes.BOOL
        if psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
            page = int(info.PageSize)
            result['commit_used_bytes'] = int(info.CommitTotal) * page
            result['commit_limit_bytes'] = int(info.CommitLimit) * page
    except Exception:
        return


def _linux_commit(result):
    try:
        values = {}
        with open('/proc/meminfo', encoding='ascii') as fh:
            for line in fh:
                key, _, rest = line.partition(':')
                if key in ('CommitLimit', 'Committed_AS') and rest.strip():
                    values[key] = int(rest.split()[0]) * 1024
        result['commit_used_bytes'] = values.get('Committed_AS')
        result['commit_limit_bytes'] = values.get('CommitLimit')
    except Exception:
        return


_UNSET = object()


def memory_snapshot(rss_bytes=_UNSET):
    plan = get_budget()
    rss = _process_rss_bytes() if rss_bytes is _UNSET else rss_bytes
    return {
        'budget_bytes': plan.budget_bytes,
        'jobs_budget_bytes': plan.jobs_budget_bytes,
        'web_budget_bytes': plan.web_budget_bytes,
        'cache_budget_bytes': plan.cache_budget_bytes,
        'private_bytes': process_private_bytes(),
        'used_ratio': (round(rss / plan.web_budget_bytes, 4)
                       if rss is not None and plan.web_budget_bytes else None),
        'level': plan.level(rss),
        'system': system_memory_snapshot(),
    }


def _fmt_gb(value):
    return f'{value / GB:.1f}GB' if value is not None else 'null'


def _log_plan(plan):
    system = system_memory_snapshot()
    logger.info(
        '内存预算: total_ram=%s budget=%s jobs=%s web=%s cache=%s '
        'system_available=%s commit=%s/%s',
        _fmt_gb(plan.total_ram_bytes), _fmt_gb(plan.budget_bytes),
        _fmt_gb(plan.jobs_budget_bytes), _fmt_gb(plan.web_budget_bytes),
        _fmt_gb(plan.cache_budget_bytes),
        _fmt_gb(system.get('available_bytes')),
        _fmt_gb(system.get('commit_used_bytes')),
        _fmt_gb(system.get('commit_limit_bytes')),
    )
    used = system.get('commit_used_bytes')
    limit = system.get('commit_limit_bytes')
    if used is not None and limit:
        free = limit - used
        if free < plan.budget_bytes:
            logger.warning(
                '系统空闲提交内存 %.1fGB 低于预算 %.1fGB，可能与其他进程冲突',
                free / GB, plan.budget_bytes / GB)
```

`memory_snapshot` 用 `_UNSET` 哨兵区分「没传、自己读」与「上游拿不到、保持 None」；
`metrics` 传 `None` 时不会重读真实 RSS。

同一个 Step 里把 `psutil` 提升为显式依赖：`requirements/base.txt` 在
`--- Remote access / crypto ---` 之前加：

```text
# psutil：内存 / commit 指标与预算兜底。py7zr 虽已传递依赖，仍显式声明，
# 避免干净检出或将来 py7zr 换依赖时指标静默变 null。
psutil==7.2.2
```

Run: `.venv/Scripts/python.exe -m pip show psutil | grep Version`
Expected: `Version: 7.2.2`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_memory_budget -v 2`
Expected: `OK`。

- [ ] **Step 5: 提交**

```bash
git add apps/common/memory.py test/backend/test_memory_budget.py requirements/base.txt
git commit -m "feat(memory): 新增预算内核与水位/commit 快照"
```

---

### Task 2: 解析缓存预算派生、计数器与淘汰

**Files:**
- Modify: `apps/datafiles/services.py:18-158`、`:312-338`
- Test: `apps/datafiles/tests_parse_cache.py:254-311`

**Interfaces:**
- Consumes: `apps.common.memory.get_budget()`（Task 1）
- Produces:
  - `_resolve_cache_budget_bytes() -> int`（`get_budget().cache_budget_bytes`）
  - `PARSE_CACHE_BUDGET_BYTES = _resolve_cache_budget_bytes()`
  - `_BytesLRUCache.evict_to(target_bytes: int) -> None`
  - `evict_parse_cache_to(fraction: float) -> None`
  - `get_parse_cache_stats()` 新增 `hits / misses / evictions / clears`

- [ ] **Step 1: 写失败测试**

把 `apps/datafiles/tests_parse_cache.py` 的 `CacheBudgetPolicyTests` 替换为（文件顶补
`from unittest import mock`）：

```python
class CacheBudgetWiringTests(SimpleTestCase):
    def setUp(self):
        from apps.common import memory
        memory.reset_budget_for_tests()

    def tearDown(self):
        from apps.common import memory
        memory.reset_budget_for_tests()

    def test_module_budget_matches_memory_plan(self):
        from apps.common import memory
        self.assertEqual(services.PARSE_CACHE_BUDGET_BYTES,
                         memory.get_budget().cache_budget_bytes)

    def test_resolver_reads_cache_budget_from_consuming_binding(self):
        """预算必须来自 get_budget()，而不是本模块里另写死的 1536MB。

        patch 的是 ``apps.datafiles.services.get_budget``（消费方绑定，R6③），
        不是 ``apps.common.memory.get_budget`` —— 后者证明不了本模块用的是它。
        """
        from apps.common.memory import MemoryBudget
        plan = MemoryBudget(
            total_ram_bytes=16 * 1024 ** 3,
            budget_bytes=8 * 1024 ** 3,
            jobs_budget_bytes=2 * 1024 ** 3,
            web_budget_bytes=6 * 1024 ** 3,
            cache_budget_bytes=123456,
        )
        with mock.patch('apps.datafiles.services.get_budget',
                        return_value=plan) as get_budget:
            self.assertEqual(services._resolve_cache_budget_bytes(), 123456)
        get_budget.assert_called_once_with()

    def test_stats_expose_counters(self):
        stats = services.get_parse_cache_stats()
        self.assertEqual(set(stats), {
            'entries', 'bytes', 'budget_bytes', 'in_flight',
            'hits', 'misses', 'evictions', 'clears',
        })
```

在 `BytesLRUCacheTests` 追加：

```python
    def test_hits_misses_and_clears_are_counted(self):
        self.patch_parser(_frame())
        self.cached_parse()
        self.cached_parse()
        stats = services.get_parse_cache_stats()
        self.assertEqual((stats['misses'], stats['hits'], stats['clears']),
                         (1, 1, 0))
        services.clear_parse_cache()
        self.assertEqual(services.get_parse_cache_stats()['clears'], 1)

    def test_evict_to_zero_keeps_last_entry_and_counts(self):
        frame = _frame()
        self.use_budget(services._frame_bytes(frame) * 10)
        self.patch_parser(frame)
        self.cached_parse(file_id=1)
        self.cached_parse(file_id=2)
        self.assertEqual(len(services._parse_cache), 2)
        services._parse_cache.evict_to(0)
        self.assertEqual(len(services._parse_cache), 1,
                         'evict_to 保留最后一条，与 _store 的 len>1 语义一致')
        self.assertGreaterEqual(
            services.get_parse_cache_stats()['evictions'], 1)

    def test_evict_parse_cache_to_fraction(self):
        frame = _frame()
        one = services._frame_bytes(frame)
        # 3 条 ≈ 3×one，预算必须 < 6×one 才会让「淘汰到预算一半」真的发生
        # （10×one 时 3 条连一半预算都不到，evict_to 无事可做）。
        self.use_budget(one * 4)
        self.patch_parser(frame)
        for file_id in (1, 2, 3):
            self.cached_parse(file_id=file_id)
        before = services._parse_cache.bytes_cached()
        services.evict_parse_cache_to(0.5)
        self.assertLessEqual(services._parse_cache.bytes_cached(), before / 2)
```

同时删除 `PARSE_CACHE_DEFAULT_MB` 的旧断言；预算派生保留为
`_resolve_cache_budget_bytes()` 并由上面的 resolver 测试钉住（patch 消费方绑定
`apps.datafiles.services.get_budget`）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test apps.datafiles.tests_parse_cache -v 2`
Expected: FAIL，`_BytesLRUCache` 无 `evict_to` / stats 缺计数器。

- [ ] **Step 3: 实现**

`apps/datafiles/services.py` 顶部：

```python
from apps.common.memory import get_budget


def _resolve_cache_budget_bytes() -> int:
    """解析缓存预算 = 预算内核的 cache_budget_bytes（导入期读一次）。"""
    return get_budget().cache_budget_bytes


# 预算来源统一在 apps/common/memory.py：web 预算的 60%，上限 1536MB。
# LQDP_PARSE_CACHE_MB 的覆盖也在那边解析（0 = 关闭缓存）。
PARSE_CACHE_BUDGET_BYTES = _resolve_cache_budget_bytes()
logger.info('解析缓存预算 = %dMB', PARSE_CACHE_BUDGET_BYTES // (1024 * 1024))
```

`PARSE_CACHE_DEFAULT_MB` 的旧常量/断言删除（预算公式已搬到 `memory.py`，Task 1 已钉住）。

`_BytesLRUCache.__init__` 增加：

```python
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._clears = 0
```

`get_or_compute` 的命中/未命中分支：

```python
                entry = self._data.get(key)
                if entry is not None:
                    self._data.move_to_end(key)
                    self._hits += 1
                    return entry[0]
                if key in self._pending:
                    self._cv.wait()
                    continue
                self._misses += 1
                self._pending.add(key)
```

`clear` 与新增 `evict_to`：

```python
    def clear(self) -> None:
        with self._cv:
            self._data.clear()
            self._total = 0
            self._clears += 1

    def evict_to(self, target_bytes: int) -> None:
        """淘汰最旧条目直到总量 ≤ target；至少保留一条（与 _store 一致）。"""
        with self._cv:
            target = max(0, int(target_bytes))
            while self._total > target and len(self._data) > 1:
                _, (_, freed) = self._data.popitem(last=False)
                self._total -= freed
                self._evictions += 1
```

`_store` 的 pop 分支加 `self._evictions += 1`。

`get_parse_cache_stats` 返回值加：

```python
            'hits': _parse_cache._hits,
            'misses': _parse_cache._misses,
            'evictions': _parse_cache._evictions,
            'clears': _parse_cache._clears,
```

新增：

```python
def evict_parse_cache_to(fraction: float) -> None:
    """内存水位到 soft/hard 时把缓存淘汰到预算的 fraction。"""
    ratio = max(0.0, min(1.0, float(fraction)))
    _parse_cache.evict_to(int(_parse_cache._budget * ratio))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test apps.datafiles.tests_parse_cache -v 2`
Expected: `OK`。

- [ ] **Step 5: 提交**

```bash
git add apps/datafiles/services.py apps/datafiles/tests_parse_cache.py
git commit -m "feat(memory): 解析缓存预算改由预算内核派生，补命中/淘汰计数"
```

---

### Task 3: `/metrics/` 增加 memory 对象与解析缓存计数器

**Files:**
- Modify: `apps/common/metrics.py:163-175`
- Test: `apps/common/tests_metrics.py:139-158`

**Interfaces:**
- Consumes: `memory.get_budget()`、`memory.memory_snapshot()`（Task 1/2）
- Produces: `snapshot()['memory']`，键：
  `budget_bytes / jobs_budget_bytes / web_budget_bytes / cache_budget_bytes / private_bytes / used_ratio / level / system{...}`

- [ ] **Step 1: 写失败测试**

`apps/common/tests_metrics.py` 的 `test_admin_gets_the_whole_payload` 顶层键集改为：

```python
        self.assertEqual(
            set(body), {'uptime_seconds', 'pid', 'rss_bytes', 'rss_available',
                        'memory', 'parse_cache', 'summary_cache', 'jobs',
                        'requests'})
        self.assertEqual(set(body['memory']), {
            'budget_bytes', 'jobs_budget_bytes', 'web_budget_bytes',
            'cache_budget_bytes', 'private_bytes', 'used_ratio', 'level',
            'system',
        })
        self.assertEqual(set(body['memory']['system']), {
            'total_bytes', 'available_bytes',
            'commit_used_bytes', 'commit_limit_bytes',
        })
```

`test_parse_cache_reports_budget_and_usage` 改为：

```python
        self.assertEqual(set(cache), {
            'entries', 'bytes', 'budget_bytes', 'in_flight',
            'hits', 'misses', 'evictions', 'clears',
        })
```

新增：

```python
    def test_memory_unavailable_is_null_not_zero(self):
        with mock.patch.object(metrics, 'process_rss_bytes', return_value=None):
            snap = metrics.snapshot()
        self.assertIsNone(snap['memory']['used_ratio'])
        self.assertIsNone(snap['memory']['level'])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test apps.common.tests_metrics -v 2`
Expected: FAIL，`memory` 键不存在 / `parse_cache` 键集不符。

- [ ] **Step 3: 实现**

`apps/common/metrics.py` 的 `snapshot()`：

```python
def snapshot():
    rss = process_rss_bytes()
    from apps.common import memory as memory_mod
    return {
        'uptime_seconds': round(time.time() - _started_at),
        'pid': os.getpid(),
        'rss_bytes': rss,
        'rss_available': rss is not None,
        'memory': memory_mod.memory_snapshot(rss),
        'parse_cache': _parse_cache_stats(),
        'summary_cache': _summary_cache_stats(),
        'jobs': _job_counts(),
        'requests': latency_summary(),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test apps.common.tests_metrics apps.datafiles.tests_parse_cache test.backend.test_memory_budget -v 2`
Expected: `OK`。

- [ ] **Step 5: 提交**

```bash
git add apps/common/metrics.py apps/common/tests_metrics.py
git commit -m "feat(metrics): 增加预算水位与解析缓存命中/淘汰读数"
```

---

### Task 4: KDE 分块 + 原地运算

**Files:**
- Modify: `apps/analysis/services/statistics/kde.py:72-80`
- Test: `test/backend/test_kde_numpy.py`（追加）

**Interfaces:**
- Produces: `GaussianKDE.__call__` 输出与旧实现逐点一致，峰值分配显著下降
- Constant: `_CHUNK_ROWS = 32`

- [ ] **Step 1: 写失败测试**

在 `test/backend/test_kde_numpy.py` 追加（并 `import tracemalloc`）：

```python
def test_kde_call_peak_memory_is_bounded():
    """16384 样本 × 200 网格：分块后峰值应远低于未分块的 75 MiB。"""
    vals = np.random.default_rng(5).normal(0.0, 1.0, MAX_KDE_SAMPLES)
    grid = np.linspace(-5.0, 5.0, 200)
    kde = GaussianKDE(vals, bw_method='silverman')
    tracemalloc.start()
    pdf = kde(grid)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert pdf.shape == (200,)
    assert peak < 30 * 1024 * 1024, f'peak {peak / 1048576:.1f}MiB'
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe test/backend/test_kde_numpy.py`
Expected: FAIL，`peak 75.0MiB >= 30MiB`。

- [ ] **Step 3: 实现**

`apps/analysis/services/statistics/kde.py`：

```python
# 网格分块：每个临时矩阵最多 _CHUNK_ROWS × n 个 float64。
# 200×16384 未分块时同时存在 diff/diff²/exp 三个 ~26MB 临时矩阵；
# 分 32 行后单块 ~4MiB，形状与逐点结果不变（逐行 reduction 顺序不变）。
_CHUNK_ROWS = 32
```

`__call__`：

```python
    def __call__(self, points):
        pts = np.asarray(points, dtype=float).reshape(-1)
        if pts.size == 0:
            return np.empty((0,), dtype=float)
        stdev = np.sqrt(self.covariance)
        data = self.dataset[0]
        pdf = np.empty(pts.size, dtype=float)
        step = max(1, min(pts.size, _CHUNK_ROWS))
        for start in range(0, pts.size, step):
            block = pts[start:start + step]
            diff = block[:, None] - data[None, :]
            diff /= stdev
            np.square(diff, out=diff)
            diff *= -0.5
            np.exp(diff, out=diff)
            pdf[start:start + step] = diff.mean(axis=1)
        return pdf / (stdev * _SQRT_2PI)
```

- [ ] **Step 4: 跑全部 KDE 测试**

Run: `.venv/Scripts/python.exe test/backend/test_kde_numpy.py`
Expected: 全部 PASS（含 golden 1e-9、阈值等价、scipy live 对照、峰值上限）。

- [ ] **Step 5: 提交**

```bash
git add apps/analysis/services/statistics/kde.py test/backend/test_kde_numpy.py
git commit -m "perf(kde): 网格分块 + 原地运算，峰值 75MiB 降至 30MiB 以下"
```

---

### Task 5: `MemoryError` 统一 503 + 清缓存

**Files:**
- Modify: `apps/common/exceptions.py:96-114`
- Test: `test/backend/test_memory_budget.py`（追加）

**Interfaces:**
- Consumes: `memory.record_oom()`、`datafiles.services.clear_parse_cache()`
- Produces: 503 信封 `{code:'out_of_memory', message, detail:{path}}`，`Retry-After: 5`

- [ ] **Step 1: 写失败测试**

追加到 `test/backend/test_memory_budget.py`：

```python
class MemoryErrorHandlerTests(SimpleTestCase):
    def _payload(self, exc, path='/api/v1/analysis/histogram/'):
        from types import SimpleNamespace
        from apps.common.exceptions import custom_exception_handler
        return custom_exception_handler(exc, {
            'request': SimpleNamespace(path=path),
        })

    def test_memory_error_maps_to_503_and_clears_cache(self):
        from unittest import mock
        before = memory.oom_events()
        with mock.patch(
            'apps.datafiles.services.clear_parse_cache') as clear:
            response = self._payload(MemoryError('boom'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'out_of_memory')
        self.assertIn('内存不足', response.data['message'])
        self.assertEqual(response['Retry-After'], '5')
        self.assertEqual(response.data['detail']['path'],
                         '/api/v1/analysis/histogram/')
        clear.assert_called_once()
        self.assertEqual(memory.oom_events(), before + 1)

    def test_clear_cache_failure_still_returns_503_and_counts_oom(self):
        """清缓存自身再抛 MemoryError 时，503 信封与 OOM 记账都必须保住。"""
        before = memory.oom_events()
        with mock.patch(
                'apps.datafiles.services.clear_parse_cache',
                side_effect=MemoryError('again')) as clear, \
                self.assertLogs('apps.common.exceptions', level='ERROR') as logs:
            response = self._payload(MemoryError('boom'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {
            'code': 'out_of_memory',
            'message': '服务器内存不足，请关闭其他任务后重试',
            'detail': {'path': '/api/v1/analysis/histogram/'},
        })
        self.assertEqual(response['Retry-After'], '5')
        clear.assert_called_once()
        self.assertEqual(memory.oom_events(), before + 1)
        self.assertTrue(any('clear_parse_cache' in line for line in logs.output))

    def test_memory_error_survives_side_effect_import_failure(self):
        """懒导入自身失败时跳过副作用，503 信封仍必须返回。"""
        import builtins
        real_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == 'apps.datafiles.services':
                raise ImportError('simulated import failure')
            return real_import(name, *args, **kwargs)

        before = memory.oom_events()
        with mock.patch('builtins.__import__', side_effect=failing_import), \
                self.assertLogs('apps.common.exceptions', level='ERROR') as logs:
            response = self._payload(MemoryError('boom'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'out_of_memory')
        self.assertEqual(response['Retry-After'], '5')
        self.assertEqual(memory.oom_events(), before)
        self.assertTrue(any('imports failed' in line for line in logs.output),
                        logs.output)

    def test_other_exceptions_still_500(self):
        response = self._payload(ValueError('boom'))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data['code'], 'internal_error')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_memory_budget.MemoryErrorHandlerTests -v 2`
Expected: FAIL，`MemoryError` 当前返回 500 `internal_error`。

- [ ] **Step 3: 实现**

`apps/common/exceptions.py` 顶部 `custom_exception_handler` 开头加（与入库版本一致）：

```python
def _safe_error_log(message, *args, **kwargs):
    """写 ERROR 日志；日志设施自身失效时保持静默——此刻已无处可写。"""
    try:
        logger.error(message, *args, **kwargs)
    except Exception:
        pass


def _run_best_effort(name, action):
    """执行 MemoryError 分支的兜底动作（清缓存 / 记 OOM）。

    极端内存压力下动作自身也可能失败（例如清缓存时再次抛 MemoryError），
    因此逐个包裹：失败只留日志证据，绝不逸出 handler，且不影响后续动作
    （清缓存失败时 record_oom 仍必须入账）。
    """
    try:
        action()
    except Exception:
        _safe_error_log(
            'MemoryError handler side effect failed: %s', name, exc_info=True)


def custom_exception_handler(exc, context):
    if isinstance(exc, MemoryError):
        memory_mod = None
        clear_cache = None
        # 懒导入是为了避开配置加载期的循环；极端内存压力下导入自身也可能失败
        # （例如再次触发 MemoryError）。此时跳过副作用，503 信封仍必须返回。
        try:
            from apps.common import memory as memory_mod
            from apps.datafiles.services import clear_parse_cache as clear_cache
        except Exception:
            memory_mod = None
            clear_cache = None
            _safe_error_log(
                'MemoryError handler imports failed; '
                'returning 503 without side effects', exc_info=True)

        if clear_cache is not None:
            _run_best_effort('clear_parse_cache', clear_cache)
        if memory_mod is not None:
            _run_best_effort('record_oom', memory_mod.record_oom)
        request = (context or {}).get('request')
        path = getattr(request, 'path', '') or ''
        _safe_error_log(
            'MemoryError in %s', path or 'unknown',
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return Response(
            {
                'code': 'out_of_memory',
                'message': '服务器内存不足，请关闭其他任务后重试',
                'detail': {'path': path},
            },
            status=503,
            headers={'Retry-After': '5'},
        )

    response = exception_handler(exc, context)
    ...
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_memory_budget -v 2`
Expected: `OK`。

- [ ] **Step 5: 提交**

```bash
git add apps/common/exceptions.py test/backend/test_memory_budget.py
git commit -m "fix(memory): MemoryError 统一 503 out_of_memory 并清解析缓存"
```

---

### Task 6: 峰值清单脚本（baseline + KDE + 直方图）

**Files:**
- Create: `scripts/memory_profile.py`

**Interfaces:**
- Produces: 可重复运行的 RSS 峰值表；输出到 stdout，不写库、不落盘

- [ ] **Step 1: 写脚本**

```python
#!/usr/bin/env python
"""内存峰值清单（人工工具，不进 CI）。

跑法：
    .venv/Scripts/python.exe scripts/memory_profile.py --rows 20000 --params 100

只读测量：本脚本只量 RSS，不写库、不落盘。为了让「不写库」成为结构性保证而不是
自觉，`django.setup()` 前面上了两道闸：

1. 设置档固定用 `config.settings.unit`（测试档），不用 `development`。unit 档把库 /
   MEDIA_ROOT / 临时区都指到 `test/unit-data`（`LQDP_UNIT_DATA_DIR`），与真实数据根
   无关。**刻意不用 `setdefault`**：外部环境里预置的 `DJANGO_SETTINGS_MODULE`
   若是 development，`setdefault` 会原样保留，闸门就形同虚设。
2. `django.setup()` 前后把 `sys.argv` 临时换成离线命令 `check`。`JobsConfig.ready()`
   在服务启动路径上会调 `mark_interrupted_jobs()`，把库里 `running` 的作业 UPDATE 成
   `error`（见 `apps/jobs/apps.py`）；一个量内存的脚本跑一次就把用户的作业判死，代价
   远大于这次测量。`check` 在 `OFFLINE_COMMANDS` 里，`ready()` 会走「无僵尸可收」分支。

两道闸任一单独都够拦，叠起来是纵深防御。跑完 `git status` 只应看到本脚本，
输出日志按约定放 `tasks/`（gitignored）。
"""
import argparse
import gc
import os
import sys
import threading
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.unit'

import django  # noqa: E402

_argv = sys.argv
sys.argv = ['memory_profile.py', 'check']   # OFFLINE_COMMANDS includes 'check'
try:
    django.setup()
finally:
    sys.argv = _argv

import psutil  # noqa: E402

from apps.analysis.services.data_services.histogram import compute_histogram_stats  # noqa: E402
from apps.analysis.services.statistics.kde import GaussianKDE, MAX_KDE_SAMPLES  # noqa: E402

MB = 1024 * 1024


def _rss():
    return psutil.Process(os.getpid()).memory_info().rss


class _Sampler:
    # 1ms 而非 20ms：KDE 一次调用只有 ~17ms，20ms 采样几乎必然整段错过（实测同一
    # 操作在 20ms 下读 0.0MiB、5ms 读 4–5MiB、1ms 读 5–7MiB），那样的峰值表会把
    # 「有峰值」写成「没峰值」。psutil.memory_info 本身 ~0.1ms，1ms 采样不吃掉测量对象。
    def __init__(self, interval=0.001):
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, _rss())
            time.sleep(self.interval)

    def __enter__(self):
        self.peak = _rss()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)
        return False


def _measure(name, fn):
    gc.collect()
    base = _rss()
    with _Sampler() as sampler:
        t0 = time.perf_counter()
        fn()
        ms = (time.perf_counter() - t0) * 1000
    print(f'{name:<32} base={base/MB:8.1f}MiB '
          f'peak={sampler.peak/MB:8.1f}MiB delta={(sampler.peak-base)/MB:8.1f}MiB '
          f'{ms:8.1f}ms')


def _frame(rows, params):
    rng = np.random.default_rng(20261021)
    return pd.DataFrame({
        f'P{i}': rng.normal(10.0, 0.5, rows) for i in range(params)
    })


def _metadata(params):
    return {
        'format': 'CTA8280F',
        'mins': {f'P{i}': '8.0' for i in range(params)},
        'maxs': {f'P{i}': '12.0' for i in range(params)},
        'units': {f'P{i}': 'uA' for i in range(params)},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=20000)
    parser.add_argument('--params', type=int, default=100)
    args = parser.parse_args()

    print(f'python={sys.version.split()[0]} numpy={np.__version__} '
          f'pandas={pd.__version__} rows={args.rows} params={args.params}')
    _measure('import baseline', lambda: None)

    df = _frame(args.rows, args.params)
    meta = _metadata(args.params)
    _measure('frame resident', lambda: df.memory_usage(deep=True).sum())
    _measure('histogram no KDE',
             lambda: compute_histogram_stats(df, meta, 'P0', None,
                                             include_kde=False))
    _measure('histogram with KDE',
             lambda: compute_histogram_stats(df, meta, 'P0', None,
                                             include_kde=True, kde_variant='all'))

    vals = np.random.default_rng(7).normal(0, 1, MAX_KDE_SAMPLES)
    grid = np.linspace(-5, 5, 200)
    _measure('GaussianKDE call (16384)',
             lambda: GaussianKDE(vals, bw_method='silverman')(grid))


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 跑脚本**

Run: `.venv/Scripts/python.exe scripts/memory_profile.py --rows 20000 --params 100`
Expected: 打印 5 行表；`GaussianKDE call` 的 delta 明显小于 75 MiB（2026-10-21 实测
4.9–7.4 MiB / 17.4 ms）。把输出留在 `tasks/memory-profile-2026-10-21.log`（不入库），
并把 baseline 与 KDE 峰值写进 spec 的 §9（若与初始值偏差大，在同一提交里调整并跑
Task 1 测试）。

- [ ] **Step 3: 提交**

```bash
git add scripts/memory_profile.py
git commit -m "chore(memory): 新增峰值清单脚本（baseline/KDE/直方图）"
```

**批 1 收口检查**

```bash
# 定向
.venv/Scripts/python.exe manage.py test test.backend.test_memory_budget apps.common.tests_metrics apps.datafiles.tests_parse_cache -v 2
.venv/Scripts/python.exe test/backend/test_kde_numpy.py
# 后端全套（判日志末尾 Ran N tests + OK/FAILED）
.venv/Scripts/python.exe manage.py test
# affected e2e 门禁（判末尾 RESULT: 行，不取 $?）
(cd frontend && npm run test:e2e:affected)
# 前端静态三件套
(cd frontend && npx vitest run && npm run lint:e2e && npm run build)
```

Expected: 后端日志末尾 `Ran N tests` + `OK`；affected 门禁日志末尾 `RESULT:` 为通过；
vitest / lint:e2e / build 通过；`git status` 只剩预期改动。

---

## 批 2：准入 + 降级

### Task 7: 准入内核 + `admission` 指标

**Files:**
- Create: `apps/common/admission.py`
- Modify: `apps/common/metrics.py`（加 `admission` 对象）、`apps/common/exceptions.py`（`ServerBusy` → 503）
- Test: `test/backend/test_admission.py`、`apps/common/tests_metrics.py`

**Interfaces:**
- Consumes: `memory.get_budget()`、`memory.env_int()`、`datafiles.services.evict_parse_cache_to()`
- Produces:
  - `ServerBusy(reason)`，`code='server_busy'`、`message`、`retry_after=5`
  - `heavy_slot(action='')` context manager
  - `HeavyActionMixin`（`heavy_actions: frozenset[str]`）
  - `snapshot() -> {inflight, waiting, rejected_busy, rejected_oom, degraded}`
  - `record_degraded()`
  - `reset_for_tests()`

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_admission.py`：

```python
"""T1：重活信号量、超时 503、hard 拒绝、嵌套与计数。"""
import os
import threading
import time
from unittest import mock

from django.test import SimpleTestCase

from apps.common import admission, memory


def _plan(web_mb=1024):
    MB = 1024 * 1024
    return memory.MemoryBudget(
        total_ram_bytes=4 * 1024 * MB,
        budget_bytes=web_mb * MB,
        jobs_budget_bytes=0,
        web_budget_bytes=web_mb * MB,
        cache_budget_bytes=0,
    )


class HeavySlotTests(SimpleTestCase):
    def setUp(self):
        admission.reset_for_tests()

    def tearDown(self):
        admission.reset_for_tests()

    def test_timeout_raises_server_busy_and_counts(self):
        with mock.patch.dict(os.environ, {
            'LQDP_HEAVY_CONCURRENCY': '1',
            'LQDP_HEAVY_WAIT_S': '0',
        }):
            # 必须先把 env 与 semaphore 钉好，holder 和主线程用的是同一个实例；
            # 在 holder 持锁后 reset 会换出一只新 semaphore，测试就永远不超时。
            admission.reset_for_tests()
            holder_ready = threading.Event()
            release = threading.Event()

            def hold():
                with admission.heavy_slot('hold'):
                    holder_ready.set()
                    release.wait(timeout=3)

            thread = threading.Thread(target=hold)
            thread.start()
            self.assertTrue(holder_ready.wait(timeout=2))
            try:
                with self.assertRaises(admission.ServerBusy) as ctx:
                    with admission.heavy_slot('second'):
                        pass
                self.assertEqual(ctx.exception.reason, 'wait_timeout')
                self.assertEqual(admission.snapshot()['rejected_busy'], 1)
            finally:
                release.set()
                thread.join(timeout=3)

    def test_hard_pressure_rejects_after_acquire(self):
        plan = _plan(web_mb=100)
        with mock.patch.object(memory, 'get_budget', return_value=plan), \
             mock.patch.object(admission, '_rss', return_value=95 * 1024 * 1024), \
             mock.patch.object(admission, '_relief_if_needed'):
            with self.assertRaises(admission.ServerBusy) as ctx:
                with admission.heavy_slot('pressure'):
                    pass
        self.assertEqual(ctx.exception.reason, 'memory')
        self.assertEqual(admission.snapshot()['inflight'], 0)

    def test_release_after_exception(self):
        with self.assertRaises(RuntimeError):
            with admission.heavy_slot('boom'):
                raise RuntimeError('x')
        self.assertEqual(admission.snapshot()['inflight'], 0)
        with admission.heavy_slot('again'):
            self.assertEqual(admission.snapshot()['inflight'], 1)

    def test_nested_slot_acquires_once(self):
        with admission.heavy_slot('outer'):
            with admission.heavy_slot('inner'):
                self.assertEqual(admission.snapshot()['inflight'], 1)

    def test_soft_pressure_evicts_cache(self):
        plan = _plan(web_mb=100)
        with mock.patch.object(memory, 'get_budget', return_value=plan), \
             mock.patch.object(admission, '_rss', return_value=80 * 1024 * 1024), \
             mock.patch('apps.datafiles.services.evict_parse_cache_to') as evict:
            with admission.heavy_slot('soft'):
                pass
        evict.assert_called()


class ServerBusyEnvelopeTests(SimpleTestCase):
    def test_server_busy_maps_to_503(self):
        from apps.common.exceptions import custom_exception_handler
        response = custom_exception_handler(admission.ServerBusy('memory'), {})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'server_busy')
        self.assertEqual(response['Retry-After'], '5')
        self.assertEqual(response.data['detail'], {'reason': 'memory'})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_admission -v 2`
Expected: FAIL / ImportError，`admission` 不存在。

- [ ] **Step 3: 实现**

创建 `apps/common/admission.py`：

```python
"""重活端点准入：soft 淘汰缓存、有界等待、hard 拒绝、MemoryError 由异常处理器兜底。"""
import logging
import sys
import threading
from contextlib import contextmanager

from apps.common import memory

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 2
DEFAULT_WAIT_SECONDS = 10
REJECT_LOG_INTERVAL = 10.0

_semaphore = None
_semaphore_lock = threading.Lock()
_stats_lock = threading.Lock()
_stats = {'inflight': 0, 'waiting': 0, 'rejected_busy': 0, 'degraded': 0}
_local = threading.local()
_last_log = 0.0


class ServerBusy(Exception):
    code = 'server_busy'
    message = '服务器繁忙，请稍后重试'
    retry_after = 5

    def __init__(self, reason='wait_timeout'):
        super().__init__(reason)
        self.reason = reason
        self.detail = {'reason': reason}


def _get_semaphore():
    global _semaphore
    if _semaphore is None:
        with _semaphore_lock:
            if _semaphore is None:
                capacity = memory.env_int(
                    'LQDP_HEAVY_CONCURRENCY', DEFAULT_CONCURRENCY,
                    minimum=1, maximum=8)
                _semaphore = threading.BoundedSemaphore(capacity)
    return _semaphore


def _rss():
    from apps.common.metrics import process_rss_bytes
    return process_rss_bytes()


def _relief_if_needed():
    level = memory.get_budget().level(_rss())
    if level in ('soft', 'hard'):
        from apps.datafiles.services import evict_parse_cache_to
        evict_parse_cache_to(0.5)


def _log_rejection(action, reason):
    global _last_log
    import time
    now = time.monotonic()
    if now - _last_log < REJECT_LOG_INTERVAL:
        return
    _last_log = now
    logger.warning('重活请求被拒 action=%s reason=%s stats=%s',
                   action or '?', reason, snapshot())


@contextmanager
def heavy_slot(action=''):
    depth = getattr(_local, 'depth', 0)
    if depth:
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth = depth
        return

    _relief_if_needed()
    with _stats_lock:
        _stats['waiting'] += 1
    wait_s = memory.env_int('LQDP_HEAVY_WAIT_S', DEFAULT_WAIT_SECONDS,
                            minimum=0, maximum=60)
    acquired = _get_semaphore().acquire(timeout=wait_s)
    with _stats_lock:
        _stats['waiting'] -= 1
        if acquired:
            _stats['inflight'] += 1
        else:
            _stats['rejected_busy'] += 1
    if not acquired:
        _log_rejection(action, 'wait_timeout')
        raise ServerBusy('wait_timeout')

    try:
        _relief_if_needed()
        if memory.get_budget().level(_rss()) == 'hard':
            with _stats_lock:
                _stats['rejected_busy'] += 1
            _log_rejection(action, 'memory')
            raise ServerBusy('memory')
        _local.depth = 1
        yield
    finally:
        _local.depth = 0
        with _stats_lock:
            _stats['inflight'] -= 1
        _get_semaphore().release()


def record_degraded():
    with _stats_lock:
        _stats['degraded'] += 1


def snapshot():
    with _stats_lock:
        return {
            'inflight': _stats['inflight'],
            'waiting': _stats['waiting'],
            'rejected_busy': _stats['rejected_busy'],
            'rejected_oom': memory.oom_events(),
            'degraded': _stats['degraded'],
        }


def reset_for_tests():
    global _semaphore, _last_log, _stats
    with _semaphore_lock:
        _semaphore = None
    with _stats_lock:
        _stats = {'inflight': 0, 'waiting': 0, 'rejected_busy': 0, 'degraded': 0}
    _last_log = 0.0
    _local.depth = 0


class HeavyActionMixin:
    """ViewSet 在类顶声明 heavy_actions，在 initial() 取槽、finalize_response() 释放。

    不能覆写 ``dispatch()``：

    1. DRF 在 ``ViewSetMixin.initialize_request()`` 里才设置 ``self.action``，而它在
       ``APIView.dispatch()`` 内部执行；mixin 的 ``dispatch()`` 覆写体运行时
       ``self.action`` 还是 ``None``，任何重活都不会真正取槽（静默失效）。
    2. ``ServerBusy`` 若在 ``dispatch()`` 覆写里、``APIView.dispatch()`` 的
       try/except 之外抛出，就不会进 ``handle_exception``，最终变成 500 而不是
       503 ``server_busy`` 信封。

    ``initial()`` 在 ``initialize_request()`` 之后执行，``self.action`` 已就绪；
    它本身位于 ``APIView.dispatch()`` 的 try 内，``ServerBusy`` 能走统一异常处理。
    """

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

`apps/common/metrics.py` 的 `snapshot()` 加：

```python
        'admission': _admission_stats(),
```

并在文件内加：

```python
def _admission_stats():
    from apps.common import admission
    return admission.snapshot()
```

`apps/common/exceptions.py` 的 `custom_exception_handler` 在 `MemoryError` 分支之后加
（懒导入，避免配置加载期循环）：

```python
    from apps.common.admission import ServerBusy
    if isinstance(exc, ServerBusy):
        return Response(
            {'code': exc.code, 'message': exc.message, 'detail': exc.detail},
            status=503,
            headers={'Retry-After': str(exc.retry_after)},
        )
```

`apps/common/tests_metrics.py` 顶层键集加 `'admission'`，并加：

```python
        self.assertEqual(set(body['admission']), {
            'inflight', 'waiting', 'rejected_busy', 'rejected_oom', 'degraded',
        })
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_admission apps.common.tests_metrics -v 2`
Expected: `OK`。

- [ ] **Step 5: 提交**

```bash
git add apps/common/admission.py apps/common/metrics.py apps/common/exceptions.py apps/common/tests_metrics.py test/backend/test_admission.py
git commit -m "feat(admission): 重活信号量、soft 淘汰与 hard 拒绝"
```

---

### Task 8: 登记重活端点 + 同步导出兜底 + 覆盖测试

**Files:**
- Modify: `apps/analysis/views/analysis_views.py:60`、`apps/analysis/views/statistics_views.py:55`、`apps/gage/views.py:30`、`apps/buyoff/views.py:20`、`apps/batch_report/views.py:29`、`apps/jobs/views.py:177-179`
- Test: `test/backend/test_admission.py`（追加）

**Interfaces:**
- Consumes: `HeavyActionMixin`、`heavy_slot`（Task 7）
- Produces: 每个 ViewSet 的 `heavy_actions` 与 spec §6.1 清单一致

- [ ] **Step 1: 写失败测试**

追加到 `test/backend/test_admission.py`：

```python
HEAVY_EXPECTED = {
    'histogram', 'wafer_map', 'multi_lot', 'correlation',
    'correlation_matrix', 'boxplot', 'qqplot', 'cpk', 'bin_stats',
    'bin_trend', 'param_trend', 'zonal_yield', 'serial_distribution',
    'uph', 'detect_fail', 'file_correlation_serials',
    'file_correlation', 'file_correlation_export',
    'generate_summary', 'identify_common_items', 'generate_form',
    'batch_html_report', 'generate_report',
}


class HeavyActionCoverageTests(SimpleTestCase):
    def _viewsets(self):
        from apps.analysis.views import AnalysisViewSet, StatisticsViewSet
        from apps.gage.views import GageViewSet
        from apps.buyoff.views import BuyoffViewSet
        from apps.batch_report.views import BatchReportViewSet
        return (AnalysisViewSet, StatisticsViewSet, GageViewSet,
                BuyoffViewSet, BatchReportViewSet)

    def test_registry_matches_design_list(self):
        actual = set()
        for cls in self._viewsets():
            real = {a.__name__ for a in cls.get_extra_actions()}
            self.assertTrue(cls.heavy_actions <= real,
                            f'{cls.__name__} 登记了不存在的 action: '
                            f'{cls.heavy_actions - real}')
            self.assertTrue(cls.heavy_actions,
                            f'{cls.__name__} 未登记任何重活 action')
            actual |= set(cls.heavy_actions)
        self.assertEqual(actual, HEAVY_EXPECTED)


class HeavyMixinViewLevelTests(SimpleTestCase):
    """视图级证明：mixin 真在 DRF 生命周期里取槽，且 ServerBusy 走 503 信封。"""

    def setUp(self):
        admission.reset_for_tests()
        self.addCleanup(admission.reset_for_tests)

    def test_registered_action_returns_503_when_slot_is_held(self):
        import pandas as pd
        from apps.analysis.tests_param_guards import (
            StaleParamAcrossFileSwitchTests,
        )
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0]})
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(df)
        self.addCleanup(restore)
        request = StaleParamAcrossFileSwitchTests._authed_post(
            factory, force_authenticate, '/api/v1/analysis/histogram/',
            {'file_id': 1, 'params': ['Param0']})

        with mock.patch.dict(os.environ, {
                'LQDP_HEAVY_CONCURRENCY': '1',
                'LQDP_HEAVY_WAIT_S': '0'}):
            admission.reset_for_tests()
            ready = threading.Event()
            release = threading.Event()

            def hold():
                with admission.heavy_slot('holder'):
                    ready.set()
                    release.wait(timeout=3)

            thread = threading.Thread(target=hold)
            thread.start()
            self.assertTrue(ready.wait(timeout=2))
            try:
                response = AnalysisViewSet.as_view(
                    {'post': 'histogram'})(request)
                response.render()
            finally:
                release.set()
                thread.join(timeout=3)

        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(response.data['code'], 'server_busy')
        self.assertEqual(response['Retry-After'], '5')


class HeavyMixinWiringTests(SimpleTestCase):
    """重活名单之外的动作不得取槽——证明 mixin 不是静默失效的摆设。"""

    def test_slot_entered_only_for_registered_action(self):
        from rest_framework import viewsets
        from rest_framework.decorators import action
        from rest_framework.permissions import AllowAny
        from rest_framework.response import Response
        from rest_framework.test import APIRequestFactory
        from apps.common.admission import HeavyActionMixin

        entered = []

        class SpySlot:
            def __init__(self, name):
                self.name = name

            def __enter__(self):
                entered.append(self.name)
                return self

            def __exit__(self, *exc):
                return False

        class DummyViewSet(HeavyActionMixin, viewsets.GenericViewSet):
            permission_classes = [AllowAny]
            heavy_actions = frozenset({'heavy'})

            @action(detail=False, methods=['post'])
            def heavy(self, request):
                return Response({'ok': True})

            @action(detail=False, methods=['post'])
            def light(self, request):
                return Response({'ok': True})

        factory = APIRequestFactory()
        with mock.patch('apps.common.admission.heavy_slot',
                        side_effect=lambda name='': SpySlot(name)):
            for name in ('heavy', 'light'):
                response = DummyViewSet.as_view({'post': name})(
                    factory.post(f'/dummy/{name}/'))
                response.render()
                self.assertEqual(response.status_code, 200)

        self.assertEqual(entered, ['heavy'])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_admission.HeavyActionCoverageTests test.backend.test_admission.HeavyMixinViewLevelTests test.backend.test_admission.HeavyMixinWiringTests -v 2`
Expected: FAIL，`heavy_actions` 为空 / mixin 不取槽（若用旧 `dispatch()` 实现，
`HeavyMixinWiringTests` 会因 `self.action` 仍为 `None` 而记录为空）。

- [ ] **Step 3: 实现**

各 ViewSet 加 mixin 与登记：

```python
# analysis_views.py
from apps.common.admission import HeavyActionMixin

class AnalysisViewSet(HeavyActionMixin, FileCorrelationActions,
                      ParamStatActions, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    heavy_actions = frozenset({
        'histogram', 'wafer_map', 'multi_lot', 'correlation',
        'serial_distribution', 'cpk', 'qqplot', 'uph',
        'file_correlation_serials', 'file_correlation',
        'file_correlation_export',
    })
```

```python
# statistics_views.py
from apps.common.admission import HeavyActionMixin

class StatisticsViewSet(HeavyActionMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    heavy_actions = frozenset({
        'detect_fail', 'bin_stats', 'zonal_yield', 'correlation_matrix',
        'bin_trend', 'boxplot', 'param_trend',
    })
```

```python
# gage/views.py
from apps.common.admission import HeavyActionMixin

class GageViewSet(HeavyActionMixin, viewsets.GenericViewSet):
    heavy_actions = frozenset({'generate_summary'})
```

```python
# buyoff/views.py
from apps.common.admission import HeavyActionMixin

class BuyoffViewSet(HeavyActionMixin, viewsets.GenericViewSet):
    heavy_actions = frozenset({'identify_common_items', 'generate_form'})
```

```python
# batch_report/views.py
from apps.common.admission import HeavyActionMixin

class BatchReportViewSet(HeavyActionMixin, viewsets.GenericViewSet):
    heavy_actions = frozenset({'batch_html_report', 'generate_report'})
```

同步导出兜底：`apps/jobs/views.py` 顶部加：

```python
from apps.common.admission import heavy_slot
```

`_dispatch` 改为：

```python
    def _dispatch(self, job: Job, task: dict):
        if not executor.executor_available():
            with heavy_slot('jobs_sync_fallback'):
                return self._sync_fallback(job, task)
        executor.submit(job, task)
        ...
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_admission -v 2`
Expected: `OK`（覆盖测试 + 信号量测试全绿）。

- [ ] **Step 5: 提交**

```bash
git add apps/analysis/views/analysis_views.py apps/analysis/views/statistics_views.py apps/gage/views.py apps/buyoff/views.py apps/batch_report/views.py apps/jobs/views.py test/backend/test_admission.py
git commit -m "feat(admission): 重活端点登记与同步导出兜底取槽"
```

---

### Task 9: KDE 降级契约（后端）

**Files:**
- Modify: `apps/analysis/services/data_services/histogram.py:24-46`、`:82-117`、`:301-355`
- Modify: `apps/analysis/views/analysis_views.py:207-216`
- Test: `apps/analysis/tests_histogram_kde.py`（追加）

**Interfaces:**
- `compute_kde_curve(data_series, bin_min, bin_max, n_points=200, degraded=None, degraded_reason='kde_curve')`
- `compute_histogram_stats(..., degraded=None)`
- 响应字段 `degraded: []`（每个参数结果固定带）
- 原因码 `kde_curve` / `filtered_kde_curve`

- [ ] **Step 1: 写失败测试**

追加到 `apps/analysis/tests_histogram_kde.py`：

```python
class DegradedKdeTests(SimpleTestCase):
    def _post(self, df, metadata, payload):
        from apps.analysis.views import AnalysisViewSet
        factory, force_authenticate, restore = StaleParamAcrossFileSwitchTests._patched_view(
            df, metadata=metadata)
        self.addCleanup(restore)
        request = StaleParamAcrossFileSwitchTests._authed_post(
            factory, force_authenticate,
            '/api/v1/analysis/histogram/', payload)
        response = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        response.render()
        return response

    def test_histogram_degrades_kde_on_memory_error(self):
        from unittest import mock
        from apps.analysis.services.statistics import kde as kde_mod

        # 均匀线性数据没有 IQR 异常值 ⇒ 只走全量 KDE，原因码确定是 kde_curve。
        df = pd.DataFrame({'Param0': np.linspace(10.5, 11.5, 200)})
        metadata = {'format': 'CTA8280F', 'mins': {'Param0': '8.0'},
                    'maxs': {'Param0': '14.3'}, 'units': {'Param0': 'uA'}}
        with mock.patch.object(kde_mod.GaussianKDE, '__call__',
                               side_effect=MemoryError()):
            response = self._post(df, metadata, {
                'file_id': 1, 'params': ['Param0'], 'range_type': 'RDL',
            })
        self.assertEqual(response.status_code, 200, response.content)
        result = response.data['results']['Param0']
        self.assertEqual(result['degraded'], ['kde_curve'])
        self.assertIsNone(result['kde_curve'])

    def test_normal_histogram_has_empty_degraded(self):
        df = pd.DataFrame({'Param0': np.linspace(10.5, 11.5, 200)})
        metadata = {'format': 'CTA8280F', 'mins': {'Param0': '8.0'},
                    'maxs': {'Param0': '14.3'}, 'units': {'Param0': 'uA'}}
        response = self._post(df, metadata, {
            'file_id': 1, 'params': ['Param0'], 'range_type': 'RDL',
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['results']['Param0']['degraded'], [])

    def test_service_without_degraded_list_reraises_memory_error(self):
        from unittest import mock
        from apps.analysis.services.data_services.histogram import (
            compute_histogram_stats,
        )
        from apps.analysis.services.statistics import kde as kde_mod

        df = pd.DataFrame({'Param0': np.linspace(10.5, 11.5, 200)})
        metadata = {'format': 'CTA8280F', 'mins': {'Param0': '8.0'},
                    'maxs': {'Param0': '14.3'}, 'units': {'Param0': 'uA'}}
        with mock.patch.object(kde_mod.GaussianKDE, '__call__',
                               side_effect=MemoryError()):
            with self.assertRaises(MemoryError):
                compute_histogram_stats(df, metadata, 'Param0', None,
                                        include_kde=True)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test apps.analysis.tests_histogram_kde.DegradedKdeTests -v 2`
Expected: FAIL，响应没有 `degraded` 键，`MemoryError` 直接 500。

- [ ] **Step 3: 实现**

`histogram.py`：

```python
def compute_kde_curve(data_series, bin_min, bin_max, n_points=200,
                      degraded=None, degraded_reason='kde_curve'):
    ...
    try:
        kde = GaussianKDE(vals, bw_method='silverman')
    except MemoryError:
        if degraded is None:
            raise
        degraded.append(degraded_reason)
        return None
    except Exception:
        return None
    x = _dense_x_grid(...)
    try:
        y = kde(x)
    except MemoryError:
        if degraded is None:
            raise
        degraded.append(degraded_reason)
        return None
    ...
```

`compute_histogram_stats` 签名末尾加 `degraded=None`，两次调用改成：

```python
        if want_raw:
            kde_curve = compute_kde_curve(
                data_series, x_lo, x_hi, degraded=degraded,
                degraded_reason='kde_curve')
        if want_filtered:
            filtered_kde_curve = compute_kde_curve(
                normal_data, x_lo, x_hi, degraded=degraded,
                degraded_reason='filtered_kde_curve')
```

返回字典加：

```python
        'degraded': list(degraded) if degraded is not None else [],
```

`analysis_views.py` 的 histogram 循环：

```python
        from apps.common import admission
        ...
        for param in params:
            degraded = []
            result = compute_histogram_stats(
                ..., include_kde=include_kde, kde_variant=kde_variant,
                degraded=degraded)
            if result is not None:
                results[param] = result
                if result['degraded']:
                    admission.record_degraded()
            else:
                skipped_params.append(param)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test apps.analysis.tests_histogram_kde -v 2`
Expected: `OK`（含原有 KDE / sigma 用例）。

- [ ] **Step 5: 提交**

```bash
git add apps/analysis/services/data_services/histogram.py apps/analysis/views/analysis_views.py apps/analysis/tests_histogram_kde.py
git commit -m "feat(histogram): KDE 内存不足时降级并回传 degraded 原因"
```

---

### Task 10: 前端降级提示 + 错误码 + T2/T3

**Files:**
- Create: `frontend/src/pages/analysis/histogramDegraded.ts`
- Modify: `frontend/src/pages/analysis/components/HistogramChart.vue:1-31,307-316`
- Modify: `frontend/src/utils/error.ts:22-57`
- Test: `frontend/test/unit/histogramDegraded.spec.ts`、`frontend/test/unit/error.spec.ts`
- Test: `frontend/e2e/analysis/histogram-degraded.spec.ts`

**Interfaces:**
- `histogramDegradedHint(reasons: string[] | null | undefined) -> string`
- `data-degraded-hint` DOM 锚点

- [ ] **Step 1: 写失败测试**

`frontend/test/unit/histogramDegraded.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import {
  HISTOGRAM_DEGRADED_TEXT,
  histogramDegradedHint,
} from '../../src/pages/analysis/histogramDegraded'

describe('histogramDegradedHint', () => {
  it('空/缺省不显示', () => {
    expect(histogramDegradedHint([])).toBe('')
    expect(histogramDegradedHint(null)).toBe('')
    expect(histogramDegradedHint(undefined)).toBe('')
  })

  it('任一 KDE 原因都给出同一句可见提示', () => {
    expect(histogramDegradedHint(['kde_curve'])).toBe(HISTOGRAM_DEGRADED_TEXT)
    expect(histogramDegradedHint(['filtered_kde_curve'])).toBe(HISTOGRAM_DEGRADED_TEXT)
  })
})
```

`error.spec.ts` 追加：

```ts
  it('内存/过载码有中文兜底', () => {
    expect(ERROR_CODE_MAP.server_busy).toContain('稍后')
    expect(ERROR_CODE_MAP.out_of_memory).toContain('内存')
  })
```

`frontend/e2e/analysis/histogram-degraded.spec.ts`：

```ts
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, listParams, selectParam } from '../helpers/params'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { SEEDED_FILES } from '../fixtures/test-data'

const SINGLE = '.single-param-tab'
const HINT = `${SINGLE} [data-degraded-hint]`
const HISTOGRAM_ROUTE = '**/api/v1/analysis/histogram/**'

test.describe('@p1 分析页内存降级提示', () => {
  test('degraded 响应显示提示，双主题可见', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.GAGE_S4)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    await page.route(HISTOGRAM_ROUTE, async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      const response = await route.fetch()
      const body = await response.json()
      for (const result of Object.values(body.results ?? {}) as Record<string, any>[]) {
        result.degraded = ['kde_curve']
      }
      await route.fulfill({ response, json: body })
    })

    const params = await listParams(page)
    expect(params.length).toBeGreaterThan(1)
    const pending = page.waitForResponse(
      (r) => r.url().includes('/api/v1/analysis/histogram/')
        && r.request().method() === 'POST' && r.status() === 200,
    )
    await selectParam(page, params[1])
    await pending

    await expect(page.locator(HINT)).toBeVisible({ timeout: 10_000 })
    await expect(page.locator(HINT)).toContainText('内存紧张')

    const themeNow = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    const t0 = await themeNow()
    await page.locator('button.theme-toggle').click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', t0 === 'light' ? 'night' : 'light')
    await expect(page.locator(HINT)).toBeVisible()

    await page.unroute(HISTOGRAM_ROUTE)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run test/unit/histogramDegraded.spec.ts test/unit/error.spec.ts`
Expected: FAIL，模块不存在 / 键缺失。

- [ ] **Step 3: 实现**

`frontend/src/pages/analysis/histogramDegraded.ts`：

```ts
export const HISTOGRAM_DEGRADED_TEXT = '内存紧张，已省略 KDE 曲线'

export function histogramDegradedHint(
  reasons: string[] | null | undefined,
): string {
  return reasons && reasons.length > 0 ? HISTOGRAM_DEGRADED_TEXT : ''
}
```

`HistogramChart.vue` 模板在 `<OutlierHintBar>` 前加：

```html
    <div v-if="degradedHint" class="degraded-hint-bar" data-degraded-hint>
      <el-icon class="degraded-hint-bar__icon"><Warning /></el-icon>
      {{ degradedHint }}
    </div>
```

脚本加：

```ts
import { computed } from 'vue'
import { Warning } from '@element-plus/icons-vue'
import { histogramDegradedHint } from '../histogramDegraded'

const degradedHint = computed(() => histogramDegradedHint(props.result?.degraded))
```

样式加：

```css
.degraded-hint-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 6px 12px;
  margin-top: 4px;
  border-radius: 4px;
  font-size: var(--p-fs-dense);
  color: var(--warn);
  background-color: color-mix(in srgb, var(--warn) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
}

.degraded-hint-bar__icon {
  font-size: var(--p-fs-base);
  flex-shrink: 0;
}
```

`error.ts` 的 `ERROR_CODE_MAP` 加：

```ts
  server_busy: '服务器繁忙，请稍后重试',
  out_of_memory: '服务器内存不足，请关闭其他任务后重试',
```

- [ ] **Step 4: 跑 T2 与 T3**

Run:
```bash
cd frontend
npx vitest run test/unit/histogramDegraded.spec.ts test/unit/error.spec.ts
npm run lint:e2e
npm run build
npx playwright test e2e/analysis/histogram-degraded.spec.ts --project=P1 --workers=1
```
Expected: vitest 全绿；lint / build 通过；Playwright 1 例通过。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/analysis/histogramDegraded.ts frontend/src/pages/analysis/components/HistogramChart.vue frontend/src/utils/error.ts frontend/test/unit/histogramDegraded.spec.ts frontend/test/unit/error.spec.ts frontend/e2e/analysis/histogram-degraded.spec.ts
git commit -m "feat(analysis): 直方图内存降级提示与 503 文案兜底"
```

**批 2 收口检查**

```bash
.venv/Scripts/python.exe manage.py test test.backend.test_admission apps.analysis.tests_histogram_kde apps.common.tests_metrics -v 2
(cd frontend && npx vitest run && npm run lint:e2e && npm run build)
(cd frontend && npm run test:e2e:affected)
```

Expected: 全绿；日志末尾 `RESULT:` 为通过。

---

## 批 3：隔离 + 运维

### Task 11: worker 内存硬上限 + 接线 + 指标

**Files:**
- Create: `apps/jobs/worker_limits.py`
- Modify: `apps/jobs/executor.py:83-94`
- Modify: `apps/common/metrics.py`（`worker_limits` 对象）
- Test: `test/backend/test_worker_limits.py`、`apps/jobs/tests_jobs.py`、`apps/common/tests_metrics.py`

**Interfaces:**
- `resolve_worker_cap(jobs_budget_mb: int, workers: int, env_mb: int | None = None) -> int`
- `apply_worker_cap(cap_bytes: int) -> bool`
- `platform_support() -> tuple[str, bool]`
- metrics `worker_limits: {supported, cap_bytes, reason}`

- [ ] **Step 1: 写失败测试**

创建 `test/backend/test_worker_limits.py`：

```python
"""T1：worker 上限公式 + 平台子进程越界测试。"""
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

from apps.jobs import worker_limits

MB = 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


class CapMathTests(SimpleTestCase):
    def test_default_divides_jobs_budget(self):
        self.assertEqual(worker_limits.resolve_worker_cap(2048, 4), 512 * MB)

    def test_floor_is_384mb(self):
        self.assertEqual(worker_limits.resolve_worker_cap(1024, 4), 384 * MB)

    def test_env_override_wins(self):
        self.assertEqual(worker_limits.resolve_worker_cap(2048, 4, env_mb=256),
                         256 * MB)

    def test_platform_support_is_explicit(self):
        reason, supported = worker_limits.platform_support()
        if sys.platform == 'win32':
            self.assertEqual((reason, supported), ('job_object', True))
        elif sys.platform.startswith('linux'):
            self.assertEqual((reason, supported), ('rlimit', True))
        else:
            self.assertEqual(supported, False)


class CapEnforcementTests(SimpleTestCase):
    CHILD = r'''
import sys
sys.path.insert(0, r"%s")
from apps.jobs.worker_limits import apply_worker_cap
if not apply_worker_cap(256 * 1024 * 1024):
    print("UNSUPPORTED")
    sys.exit(2)
try:
    bytearray(512 * 1024 * 1024)
except MemoryError:
    print("MEMORY_ERROR")
    sys.exit(0)
print("ALLOCATED")
sys.exit(1)
''' % str(ROOT)

    def test_worker_cap_makes_oversized_allocation_fail(self):
        reason, supported = worker_limits.platform_support()
        if not supported:
            self.skipTest(f'当前平台不支持: {reason}')
        proc = subprocess.run(
            [sys.executable, '-c', self.CHILD],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0,
                         f'stdout={proc.stdout!r} stderr={proc.stderr!r}')
        self.assertIn('MEMORY_ERROR', proc.stdout)
```

`apps/jobs/tests_jobs.py` 追加（放在现有池测试旁）：

```python
class WorkerCapWiringTests(TestCase):
    def test_pool_is_created_with_worker_cap(self):
        from apps.jobs import executor, worker_limits
        seen = {}

        class Spy:
            def __init__(self, **kwargs):
                seen.update(kwargs)

            def submit(self, *args, **kwargs):
                return None

        original_pool = executor.ProcessPoolExecutor
        original_pool_obj = executor._pool
        executor.ProcessPoolExecutor = Spy
        executor._pool = None
        self.addCleanup(setattr, executor, 'ProcessPoolExecutor', original_pool)
        self.addCleanup(setattr, executor, '_pool', original_pool_obj)
        executor._get_pool()
        self.assertIs(seen['initializer'], worker_limits.apply_worker_cap)
        self.assertGreater(seen['initargs'][0], 0)
```

`apps/common/tests_metrics.py` 顶层键集加 `'worker_limits'`，并加：

```python
        self.assertEqual(set(body['worker_limits']), {
            'supported', 'cap_bytes', 'reason',
        })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_worker_limits apps.jobs.tests_jobs.WorkerCapWiringTests -v 2`
Expected: FAIL，模块/参数不存在。

- [ ] **Step 3: 实现**

`apps/jobs/worker_limits.py`：

```python
"""作业 worker 内存上限。被 ProcessPoolExecutor（Windows spawn）导入，禁 Django。"""
import logging
import sys

logger = logging.getLogger(__name__)

MIN_WORKER_CAP_MB = 384
_job_handle = None


def resolve_worker_cap(jobs_budget_mb, workers, env_mb=None):
    if env_mb is not None:
        return max(64, int(env_mb)) * 1024 * 1024
    workers = max(1, int(workers))
    return max(MIN_WORKER_CAP_MB, int(jobs_budget_mb) // workers) * 1024 * 1024


def platform_support():
    if sys.platform == 'win32':
        return 'job_object', True
    if sys.platform.startswith('linux'):
        return 'rlimit', True
    return 'unsupported', False


def apply_worker_cap(cap_bytes):
    if cap_bytes <= 0:
        return False
    reason, supported = platform_support()
    if not supported:
        logger.warning('worker 内存上限不支持平台 %s', sys.platform)
        return False
    try:
        if reason == 'rlimit':
            return _apply_rlimit(cap_bytes)
        return _apply_job_object(cap_bytes)
    except Exception as exc:
        logger.warning('worker 内存上限设置失败: %s', exc)
        return False


def _apply_rlimit(cap_bytes):
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (cap_bytes, cap_bytes))
    return True


def _apply_job_object(cap_bytes):
    global _job_handle
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [
            ('PerProcessUserTimeLimit', wintypes.LARGE_INTEGER),
            ('PerJobUserTimeLimit', wintypes.LARGE_INTEGER),
            ('LimitFlags', wintypes.DWORD),
            ('MinimumWorkingSetSize', ctypes.c_size_t),
            ('MaximumWorkingSetSize', ctypes.c_size_t),
            ('ActiveProcessLimit', wintypes.DWORD),
            ('Affinity', ctypes.c_size_t),
            ('PriorityClass', wintypes.DWORD),
            ('SchedulingClass', wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ('ReadOperationCount', ctypes.c_ulonglong),
            ('WriteOperationCount', ctypes.c_ulonglong),
            ('OtherOperationCount', ctypes.c_ulonglong),
            ('ReadTransferCount', ctypes.c_ulonglong),
            ('WriteTransferCount', ctypes.c_ulonglong),
            ('OtherTransferCount', ctypes.c_ulonglong),
        ]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ('BasicLimitInformation', BasicLimit),
            ('IoInfo', IoCounters),
            ('ProcessMemoryLimit', ctypes.c_size_t),
            ('JobMemoryLimit', ctypes.c_size_t),
            ('PeakProcessMemoryUsed', ctypes.c_size_t),
            ('PeakJobMemoryUsed', ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JobObjectExtendedLimitInformation = 9
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    # 不设 restype 时 GetCurrentProcess 的伪句柄会被截成 c_int，
    # AssignProcessToJobObject 直接报错 6（ERROR_INVALID_HANDLE）。
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = ctypes.c_size_t(cap_bytes)
    ok = kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info),
        ctypes.sizeof(info))
    if not ok:
        kernel32.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        kernel32.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    _job_handle = job
    return True
```

`apps/jobs/executor.py` 的 `_get_pool`：

```python
def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            from apps.common import memory
            from apps.jobs import worker_limits
            cap = worker_limits.resolve_worker_cap(
                memory.get_budget().jobs_budget_bytes // (1024 * 1024),
                MAX_POOL_WORKERS,
                env_mb=memory.env_mb('LQDP_JOB_MEMORY_MB'),
            )
            _pool = ProcessPoolExecutor(
                max_workers=MAX_POOL_WORKERS,
                initializer=worker_limits.apply_worker_cap,
                initargs=(cap,),
            )
            _pool.submit(warmup_imports)
    return _pool
```

`apps/common/metrics.py` 加：

```python
def _worker_limits_status():
    try:
        from apps.common import memory
        from apps.jobs import executor, worker_limits
        cap = worker_limits.resolve_worker_cap(
            memory.get_budget().jobs_budget_bytes // (1024 * 1024),
            executor.MAX_POOL_WORKERS,
            env_mb=memory.env_mb('LQDP_JOB_MEMORY_MB'),
        )
        reason, supported = worker_limits.platform_support()
        return {'supported': supported,
                'cap_bytes': cap if supported else None,
                'reason': reason}
    except Exception:
        return {'supported': False, 'cap_bytes': None,
                'reason': 'unavailable'}
```

`snapshot()` 加 `'worker_limits': _worker_limits_status(),`。

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
.venv/Scripts/python.exe manage.py test test.backend.test_worker_limits apps.jobs.tests_jobs.WorkerCapWiringTests apps.common.tests_metrics -v 2
```
Expected: `OK`。

- [ ] **Step 5: 提交**

```bash
git add apps/jobs/worker_limits.py apps/jobs/executor.py apps/jobs/tests_jobs.py apps/common/metrics.py apps/common/tests_metrics.py test/backend/test_worker_limits.py
git commit -m "feat(jobs): worker 内存硬上限（rlimit/Job Object）与指标"
```

---

### Task 12: 峰值扩展 + 20 并发压测 + 运维手册 + 打包验证

**Files:**
- Modify: `scripts/memory_profile.py`（增加 endpoint 模式）
- Create: `scripts/memory_load20.py`
- Create: `docs/reference/memory-runbook.md`

**Interfaces:**
- 脚本输出可复现的峰值/503/延迟读数；手册给出处置步骤

- [ ] **Step 1: 扩展峰值脚本**

在 `scripts/memory_profile.py` 增加：

```python
def _endpoint_cases(df, meta):
    """单文件、可合成数据的重活服务；多文件/坐标类由 20 并发端点压测覆盖。"""
    return [
        ('endpoint histogram', lambda: compute_histogram_stats(
            df, meta, 'P0', None, include_kde=True, kde_variant='all')),
        ('endpoint boxplot', lambda: _boxplot(df)),
        ('endpoint correlation_matrix', lambda: _correlation(df)),
        ('endpoint qqplot', lambda: _qqplot(df, meta)),
    ]


def _boxplot(df):
    from apps.analysis.services.statistics import compute_boxplot_stats
    return compute_boxplot_stats(df['P0'])


def _correlation(df):
    from apps.analysis.services.statistics import compute_correlation_matrix
    return compute_correlation_matrix(df, ['P0', 'P1'])


def _qqplot(df, meta):
    from apps.analysis.services.statistics import compute_qqplot
    return compute_qqplot(df['P0'], meta, 'P0')
```

在 `main()` 的 `GaussianKDE` 测量之后加：

```python
    for name, fn in _endpoint_cases(df, meta):
        _measure(name, fn)
```

以上签名已按当前树核对：`compute_boxplot_stats(Series)`、
`compute_correlation_matrix(df, params)`、`compute_qqplot(Series, metadata, param)`。
多文件 / 坐标类端点（file_correlation、wafer_map、导出）由 Task 12 的 20 并发端点压测覆盖，
不在本脚本里伪造。

- [ ] **Step 2: 写压测脚本**

`scripts/memory_load20.py`：

```python
#!/usr/bin/env python
"""20 并发直方图内存压测（人工运行）。

先用 seed_users 建号、准备一只 GAGE_S4 文件，启动 dev server，然后：
    .venv/Scripts/python.exe scripts/memory_load20.py --base http://127.0.0.1:8000 \
        --user admin --password admin123 --file-id 1 --param Param0 --rounds 3
"""
import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def _request(method, url, token=None, payload=None, timeout=120):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, (json.loads(body.decode('utf-8')) if body else {})


def _login(base, user, password):
    _status, body = _request(
        'POST', f'{base}/api/v1/auth/login/',
        payload={'username': user, 'password': password}, timeout=10)
    return body['access']


def _metrics(base, token):
    _status, body = _request('GET', f'{base}/api/v1/metrics/',
                             token=token, timeout=10)
    return body


def _one(base, token, file_id, param):
    t0 = time.perf_counter()
    try:
        status, _body = _request(
            'POST', f'{base}/api/v1/analysis/histogram/',
            token=token,
            payload={'file_id': file_id, 'params': [param],
                     'range_type': 'RDL'},
            timeout=120)
    except urllib.error.HTTPError as exc:
        status = exc.code
    return status, (time.perf_counter() - t0) * 1000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8000')
    parser.add_argument('--user', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--file-id', type=int, required=True)
    parser.add_argument('--param', required=True)
    parser.add_argument('--workers', type=int, default=20)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()

    token = _login(args.base, args.user, args.password)
    baseline = _metrics(args.base, token)
    stats = []
    for round_no in range(args.rounds):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            stats.extend(pool.map(
                lambda _: _one(args.base, token, args.file_id, args.param),
                range(args.workers)))
        print(f'round {round_no + 1}:',
              json.dumps(_metrics(args.base, token)['memory'], ensure_ascii=False))
    codes = [code for code, _ in stats]
    times = [ms for _, ms in stats]
    print('status:', {code: codes.count(code) for code in sorted(set(codes))})
    print('p95_ms:', round(statistics.quantiles(times, n=20)[18], 1)
          if len(times) >= 20 else round(max(times), 1))
    print('baseline_rss:', baseline['rss_bytes'])
    print('final_rss:', _metrics(args.base, token)['rss_bytes'])


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: 跑峰值与压测**

```bash
.venv/Scripts/python.exe scripts/memory_profile.py --rows 20000 --params 100
# 另开终端启动 runserver 并按 README 准备账号/文件后：
.venv/Scripts/python.exe scripts/memory_load20.py --user admin --password admin123 --file-id 1 --param Param0 --rounds 3
```

判据：
- 峰值脚本输出 baseline / KDE / histogram 峰值，写入下方手册的「实测」段；
- 压测无未处理 500；503 只可能是 `server_busy`/`out_of_memory`；`memory.level` 不长期停在 `hard`；
- 若压测出现 500，按 `docs/tasks/lessons.md` 的「崩池/提交内存」条目先查环境，再查代码。

- [ ] **Step 4: 写运维手册**

创建 `docs/reference/memory-runbook.md`：

````markdown
# 后端内存运维手册（2026-10-21）

## 1. 先看哪几个数

`GET /api/v1/metrics/`（管理员）：

| 字段 | 正常 | 动作 |
|---|---|---|
| `memory.used_ratio` | < 0.75 | normal |
| `memory.level` | `normal` | `soft` 会淘汰缓存；`hard` 会拒绝重活 |
| `memory.system.commit_used_bytes / commit_limit_bytes` | 空闲 > 预算 | 空闲不足先查别的进程/页面文件 |
| `parse_cache.bytes / budget_bytes` | < 1 | 接近 100% 说明缓存在工作 |
| `parse_cache.evictions` | 偶发 | 持续增长说明预算偏紧或文件过大 |
| `admission.rejected_busy / rejected_oom` | 0 | 持续增长按下面处置 |
| `worker_limits.supported` | true | false = 平台不支持，只有软监控 |
| `rss_bytes` | < `memory.web_budget_bytes` | 越界先降缓存/并发 |

## 2. 事故处置

1. **物理内存空、commit 打满**（2026-10-20 的形态）：
   Windows `Get-Counter '\Memory\Committed Bytes','\Memory\Commit Limit'`；
   查 `Get-Process | Sort-Object PrivateMemorySize64 -Descending`；
   结束孤儿 `manage.py runserver 21xxx` / `vite preview`，再重试。
2. **本进程 RSS 高**：把 `LQDP_PARSE_CACHE_MB` 降到 512、`LQDP_HEAVY_CONCURRENCY` 降到 1，
   重启后端；用 `scripts/memory_profile.py` 找最大单请求峰值。
3. **导出 worker OOM**：作业会标失败；降低 `LQDP_JOB_MEMORY_MB`，或调低
   `MAX_POOL_WORKERS`（代码改动），再跑一次同一导出确认可复现。
4. **503 持续**：确认不是 `hard` 水位误判；`memory.system.commit_*` 正常时再看
   `admission.inflight` 是否长期占满。

## 3. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `LQDP_MEMORY_BUDGET_MB` | RAM×50%，1.5–8 GB | 总预算 |
| `LQDP_TOTAL_RAM_MB` | 4 GB | psutil 取不到时的兜底 |
| `LQDP_PARSE_CACHE_MB` | web×60%，上限 1536 | 0 = 关闭缓存 |
| `LQDP_HEAVY_CONCURRENCY` | 2 | 重活并发，1–8 |
| `LQDP_HEAVY_WAIT_S` | 10 | 重活等待，0–60 |
| `LQDP_JOB_MEMORY_MB` | jobs_budget/workers，≥384 | 单 worker 硬上限 |

## 4. 开发机卫生

- **不要**同时跑 e2e 池与 dev server：每个 slot 的 Django 常驻约 1 GB。
- 池结束（正常或被杀）后回查 `manage.py runserver 210xx`、`vite preview` 与
  21001–22020 监听，清完再起下一轮。
- Windows 只看「可用内存」会误判；必须看 commit。页面文件建议显式设上限，
  不要完全依赖系统管理。

## 5. 实测

本节只写命令产出的数字：执行本任务时把 `scripts/memory_profile.py` 与
`scripts/memory_load20.py` 的**实际输出原文**追加在下面，禁止保留占位符。
换机器 / 改阈值后重跑并更新。

（执行时在此粘贴两段输出，并标注日期与机器规格。）
````

- [ ] **Step 5: 打包验证**

Run: `(cd frontend && npm run dist:win)`
Expected: 构建成功；安装包启动后管理员 `/api/v1/metrics/` 能读到 `memory` 与
`worker_limits` 字段，后端日志无 worker 初始化报错。若 psutil 未被 PyInstaller 收集，
按 spec §5.3 退回 ctypes / `/proc` 实现并补一条打包版冒烟说明。

- [ ] **Step 6: 提交**

```bash
git add scripts/memory_profile.py scripts/memory_load20.py docs/reference/memory-runbook.md
git commit -m "chore(memory): 补峰值清单、20 并发压测与运维手册"
```

**批 3 收口检查**

```bash
.venv/Scripts/python.exe manage.py test test.backend.test_worker_limits apps.jobs.tests_jobs apps.common.tests_metrics -v 2
.venv/Scripts/python.exe test/backend/test_kde_numpy.py
(cd frontend && npx vitest run && npm run lint:e2e && npm run build)
# 收口全量（按 testing-gates）：先确认 free commit ≥ 8GB、无 21xxx 孤儿
.venv/Scripts/python.exe manage.py test
node scripts/e2e_pool.mjs --slots=4
```

Expected: 后端全绿、前端构建通过、池日志末尾 `RESULT:` 为通过；`npm run dist:win` 已单独验过。
池轮若 `verdict=VOID (infra)`，按 testing-gates §4 重跑，不把该轮读数当结论。

---

## Self-Review

- **Spec coverage**：§4 预算 → Task 1；§5 指标 → Task 3/7/11；§6 准入 → Task 7/8；§7 降级 → Task 9/10；§8 worker → Task 11；§9 测试 → 各任务；§10 分批 → 批 1/2/3；§3 运维 → Task 12。
- **Placeholder scan**：计划中没有 TBD/TODO；Task 12 手册 §5 的实测输出必须由脚本产出后追加，属于执行步骤，不是留空。
- **Type consistency**：`degraded` 统一为 `list[str]`；`heavy_actions` 统一为 `frozenset[str]`；`ServerBusy.reason` 为 `wait_timeout|memory`；`worker_limits` 指标键统一为 `supported/cap_bytes/reason`。
- **已知依赖顺序**：Task 2 依赖 Task 1；Task 7 依赖 Task 2/1；Task 8 依赖 Task 7；Task 9 依赖 Task 7（`record_degraded`）；Task 10 依赖 Task 9；Task 11 依赖 Task 1；Task 12 依赖 Task 6/11。
