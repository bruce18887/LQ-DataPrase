"""作业执行器：常驻进程池 + 状态回填 + 超时看门狗 + 降级判定。

跑在**主进程**里（可以 import Django）。它负责两件事，边界很清楚：

* 主进程侧：读 settings / DataFile / 用户设置，把任务拼成**纯数据 dict**（`build_*_task`）；
* 子进程侧：只调 `apps.jobs.runner` 里的顶层函数（那里禁止 Django）。

为什么是进程池而不是线程池：导出是 CPU-bound，`futures.result()` 在主线程里等
和直接在主线程里算，对其它用户没有区别 —— 只有把活交给另一个进程，
请求线程才能立刻回去接下一个用户。
"""

import logging
import os
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor

from django.conf import settings
from django.db import connections
from django.utils import timezone

from apps.export.filters import grid_filters_from
from apps.jobs.models import Job
from apps.jobs.runner import run_export_excel, warmup_imports

logger = logging.getLogger(__name__)

# CPU 核数少时别把机器占满：这是给 20 人档留余量的旋钮，不是越大多好。
MAX_POOL_WORKERS = min(4, max(2, (os.cpu_count() or 4) // 2))
EXPORT_TIMEOUT_SECONDS = 30 * 60          # 单作业超时（spec §4.3）
MONITOR_INTERVAL = 5.0
# 作业类型 → (worker 入口, 超时秒)。加一类作业就是加一行 + 一个 runner 函数。
KIND_RUNNERS = {
    'export_excel': (run_export_excel, EXPORT_TIMEOUT_SECONDS),
}

_pool = None
_pool_lock = threading.Lock()
_pool_failed = False
_in_flight: dict[int, 'tuple[Future, float, int]'] = {}
_monitor_thread = None
_monitor_lock = threading.Lock()


def executor_available() -> bool:
    """进程池能不能建起来。建不起来时视图必须走同步降级（spec §7）。"""
    global _pool_failed
    if _pool_failed:
        return False
    try:
        _get_pool()
        return True
    except Exception as exc:  # PyInstaller 下 spawn 可能直接失败
        _pool_failed = True
        logger.warning('jobs pool unavailable, falling back to sync: %s', exc)
        return False


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=MAX_POOL_WORKERS)
            # 预热：把 pandas/matplotlib 的 import 成本从「第一个用户的导出」
            # 挪到进程启动期。实测收益只有亚秒级（见 perf-baseline §4），
            # 留着是因为它免费，别把它当 P3 的主要收益。
            _pool.submit(warmup_imports)
    return _pool


def result_dirs(owner_id: int, job_id: int) -> 'tuple[str, str]':
    """返回 (相对 MEDIA_ROOT 的目录, 绝对目录)。作业产物只落在 jobs/ 下。"""
    rel = os.path.join('jobs', str(owner_id), str(job_id))
    return rel, os.path.join(str(settings.MEDIA_ROOT), rel)


def build_export_excel_task(*, params, abs_path, fmt, hidden_columns,
                            job_id, owner_id) -> dict:
    """把一次导出需要的一切拼成纯数据 —— 子进程拿不到 ORM 对象。"""
    _rel, abs_dir = result_dirs(owner_id, job_id)
    name = params.get('result_name') or 'export.xlsx'
    return {
        'abs_path': abs_path,
        'fmt': fmt,
        'filters': grid_filters_from(params),
        'hidden_columns': list(hidden_columns or []),
        'out_path': os.path.join(abs_dir, name),
        'result_name': name,
    }


def submit(job: Job, task: dict) -> None:
    """投入进程池并把状态推到 running。

    调用方（视图）已经存好 Job 行；这里失败就抛，由视图决定降级方式。
    """
    entry, timeout = KIND_RUNNERS[job.kind]
    future = _get_pool().submit(entry, task)
    _in_flight[job.id] = (future, time.monotonic(), timeout)
    Job.objects.filter(pk=job.id).update(status='running', started_at=timezone.now())
    future.add_done_callback(lambda f: _write_back(job.id, f))
    _ensure_monitor()


def _write_back(job_id: int, future: 'Future') -> None:
    """把结果写回 Job 行。跑在线程池的管理线程里 ⇒ 用完必须还连接。"""
    try:
        _in_flight.pop(job_id, None)
        try:
            result = future.result()
        except Exception as exc:
            logger.exception('job %s failed', job_id)
            Job.objects.filter(pk=job_id).update(
                status='error', error=f'{type(exc).__name__}: {exc}',
                finished_at=timezone.now())
            return
        Job.objects.filter(pk=job_id).update(
            status='done', progress=100,
            result_path=_relativize(result.get('out_path', '')),
            result_name=os.path.basename(result.get('out_path', '')),
            finished_at=timezone.now())
    except Exception:  # 回填本身炸了也不能带崩执行器线程
        logger.exception('jobs write-back failed for %s', job_id)
    finally:
        connections.close_all()


def _relativize(abs_path: str) -> str:
    media = str(settings.MEDIA_ROOT).rstrip('\\/')
    if abs_path and abs_path.startswith(media):
        return abs_path[len(media):].lstrip('\\/')
    return abs_path


def _ensure_monitor() -> None:
    """超时看门狗：只在有作业在飞时活着，空闲若干轮后自己退出。

    不留常驻线程 —— 桌面档里那是白占的一个线程和一条 DB 连接。
    """
    global _monitor_thread
    with _monitor_lock:
        if _monitor_thread and _monitor_thread.is_alive():
            return
        _monitor_thread = threading.Thread(target=_monitor, daemon=True,
                                           name='jobs-monitor')
        _monitor_thread.start()


def _monitor() -> None:
    idle = 0
    while True:
        if not _in_flight:
            idle += 1
            if idle > 2:
                return                      # 空闲就收工，下次 submit 再拉起
        else:
            idle = 0
            now = time.monotonic()
            for job_id, (future, started, timeout) in list(_in_flight.items()):
                if now - started <= timeout:
                    continue
                _in_flight.pop(job_id, None)
                future.cancel()
                Job.objects.filter(pk=job_id, status='running').update(
                    status='error', error=f'超时 {timeout // 60} 分钟，已中止',
                    finished_at=timezone.now())
        connections.close_all()
        time.sleep(MONITOR_INTERVAL)


def reset_for_tests() -> None:
    """关掉进程池与看门狗，让测试用例之间不共享子进程状态。"""
    global _pool, _pool_failed, _monitor_thread
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
        _pool_failed = False
    _in_flight.clear()
    with _monitor_lock:
        _monitor_thread = None
