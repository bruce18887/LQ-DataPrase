"""运维可见性：进程内指标采样 + `GET /api/v1/metrics/` 的数据源。

方案 `docs/plans/2026-10-17-performance-remediation.md` §9-4 的要求是「20 人的运维需要一双眼睛，
否则今天特别慢无法归因」。所以这里采的东西全部对着归因场景：

* 解析缓存占了多少预算、有多少条目还在单飞 —— 决定「是不是又在重复解析」；
* 看板汇总缓存条目数 —— P1-2 那条 614ms→0ms 的命中率；
* RSS —— 20 人档最大的 OOM 风险来自解析缓存，不是代码；
* 在飞作业数与终态计数 —— P3 作业化之后，「慢」多半表现为作业排队；
* 近 5 分钟请求延迟 P50/P95 与最慢路径 Top-N —— 方案 §3 的验收线就是按 P95 写的。

**没有的东西也同样是设计**：这里不写 DB、不留历史、不做聚合持久化。指标是进程内存里的
一个有界环形窗口，进程重启就清零 —— 打包版是单机常驻进程，加一层持久化只会带来新的
失败模式（写盘、权限、清理），而运维要回答的从来是「现在这一分钟谁在慢」。
"""

import os
import threading
import time
from collections import deque

__all__ = [
    'MetricsMiddleware', 'percentile', 'snapshot', 'normalize_path',
    'WINDOW_SECONDS',
]

# 采样窗口：与方案 §3 的「近 5 分钟请求 P50/P95」对齐。
WINDOW_SECONDS = 300
# 环形上限：20 人档按 30 req/s 的极端值算，5000 条约覆盖 3 分钟；
# 触顶时丢最旧的样本，宁可不精确也不无界吃内存（这个模块不能自己变成 OOM 原因）。
MAX_SAMPLES = 5000

_self_path = '/api/v1/metrics/'

_samples = deque(maxlen=MAX_SAMPLES)      # (monotonic_ts, label, ms)
_lock = threading.Lock()
_started_at = time.time()


def percentile(values, q):
    """排序取值法（不插值）：运维读数要的是「这条线之上有多少请求」，不是拟合值。

    空输入返回 None —— 调用方据此显示「无样本」，而不是拿 0 冒充「全都很快」。
    """
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return round(ordered[idx])


def normalize_path(path):
    """把路径里的数字段折成 `<id>`，否则作业/文件 id 会把统计基数撑到无界。

    这是这个模块唯一一处「加工」：不折的话 `GET /jobs/1/`、`/jobs/2/` … 各算一条路径，
    Top-N 就退化成「最近访问了哪些 id」而不是「哪类接口慢」。
    """
    parts = [seg if not seg.isdigit() else '<id>' for seg in path.split('/')]
    return '/'.join(parts)


def is_worth_recording(path):
    """自己的轮询不进自己的样本池。

    不排掉的话，运维页开在那儿每 2s 刷一次，`/api/v1/metrics/` 就会霸占
    「最慢路径 Top-1」，而它慢不慢跟用户没任何关系 —— 观测者改变了被观测值。
    """
    return not path.startswith(_self_path)


class MetricsMiddleware:
    """记录 (方法, 归一化路径, 耗时 ms)。纯内存、单锁、无 IO。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        record = is_worth_recording(path)
        label = f'{request.method} {normalize_path(path)}' if record else ''
        t0 = time.perf_counter()
        response = self.get_response(request)
        if record:
            ms = (time.perf_counter() - t0) * 1000
            now = time.monotonic()
            with _lock:
                _samples.append((now, label, ms))
        return response


def _recent(now=None):
    """返回窗口内样本的快照列表（调用方已持锁或不关心撕裂）。"""
    cutoff = (time.monotonic() if now is None else now) - WINDOW_SECONDS
    return [(ts, label, ms) for ts, label, ms in _samples if ts >= cutoff]


def latency_summary(now=None):
    """总体 P50/P95/max + 最慢路径 Top-5（按 P95 排）。"""
    rows = _recent(now)
    if not rows:
        return {'samples': 0, 'window_seconds': WINDOW_SECONDS, 'p50_ms': None,
                'p95_ms': None, 'max_ms': None, 'slowest': []}

    by_label = {}
    for _ts, label, ms in rows:
        by_label.setdefault(label, []).append(ms)
    all_ms = [ms for _ts, _l, ms in rows]
    slowest = sorted(
        ({'path': label, 'n': len(vals), 'p95_ms': percentile(vals, 0.95),
          'p50_ms': percentile(vals, 0.5)} for label, vals in by_label.items()),
        key=lambda row: row['p95_ms'] or 0, reverse=True)[:5]
    return {
        'samples': len(rows),
        'window_seconds': WINDOW_SECONDS,
        'p50_ms': percentile(all_ms, 0.5),
        'p95_ms': percentile(all_ms, 0.95),
        'max_ms': percentile(all_ms, 1.0),
        'slowest': slowest,
    }


def process_rss_bytes():
    """当前进程 RSS（字节）。没有 psutil 时返回 None，**不返回 0**。

    psutil 已在 `requirements/base.txt` 显式声明（内存水位与 commit 快照都靠它）；
    这里仍保留 ImportError 分支 —— 精简打包或环境损坏时「取不到」是合法状态。
    把「取不到」写成 0 会让运维页显示「RSS 0 MB」，那比没有这个数字更糟。
    """
    try:
        import psutil
    except ImportError:
        return None
    try:
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except Exception:
        return None


def _parse_cache_stats():
    from apps.datafiles.services import get_parse_cache_stats
    return get_parse_cache_stats()


def _summary_cache_stats():
    from apps.dashboard.services import summary_cache_stats
    return summary_cache_stats()


def _job_counts():
    from django.db import OperationalError, ProgrammingError

    from apps.jobs.models import Job
    try:
        rows = Job.objects.values_list('status', flat=True)
        counts = {}
        for status in rows.iterator():
            counts[status] = counts.get(status, 0) + 1
    except (OperationalError, ProgrammingError):
        # 表还没建（首次启动/未 migrate）：报「拿不到」而不是编一个全 0
        return {'available': False}
    return {'available': True, **counts}


def snapshot():
    """组装指标载荷。全部来自进程内状态，一次调用不写盘不打 DB 之外的网络。"""
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
