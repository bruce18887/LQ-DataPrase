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
