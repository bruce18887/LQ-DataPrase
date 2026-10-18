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
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor

from django.conf import settings
from django.db import connections
from django.utils import timezone

from apps.export.filters import grid_filters_from
from apps.jobs.models import Job
from apps.jobs.runner import (
    PROGRESS_FILENAME, progress_path_for, read_progress,
    run_export_batch_charts, run_export_excel,
    run_export_html_report, warmup_imports)
from apps.jobs.sftp_job import run_sftp_download
# 别名导出给判据用：测试要证明 SFTP 作业**没有**走 per-user 常驻连接
# （apps/jobs/tests_jobs_sftp.py 里 mock 的就是 executor.pool_module.get_connection）
from apps.sftp import pool as pool_module

logger = logging.getLogger(__name__)

# CPU 核数少时别把机器占满：这是给 20 人档留余量的旋钮，不是越大多好。
MAX_POOL_WORKERS = min(4, max(2, (os.cpu_count() or 4) // 2))
# 并发下载硬上限：每条作业连接都是一条独立 SSH 会话，不设限会撞 sshd MaxStartups。
MAX_DOWNLOAD_WORKERS = 2
EXPORT_TIMEOUT_SECONDS = 30 * 60          # 单作业超时（spec §4.3）
CHARTS_TIMEOUT_SECONDS = 60 * 60          # 批量图表串行渲染，比单表慢一个量级
SFTP_DOWNLOAD_TIMEOUT_SECONDS = 2 * 60 * 60   # 下载看链路，给到 2 小时
MONITOR_INTERVAL = 5.0

# 作业类型 → {entry, timeout, lane}。加一类作业 = 加一行 + 一个入口函数。
# lane=process ⇒ 跑在进程池子进程里，entry 必须 Django-free（apps/jobs/runner.py）；
# lane=thread  ⇒ 跑在主进程线程里，entry 可以用 Django（下载要注册 DataFile）。
KIND_RUNNERS = {
    'export_excel': {'entry': run_export_excel, 'lane': 'process',
                     'timeout': EXPORT_TIMEOUT_SECONDS},
    'export_batch_charts': {'entry': run_export_batch_charts, 'lane': 'process',
                            'timeout': CHARTS_TIMEOUT_SECONDS},
    'export_html_report': {'entry': run_export_html_report, 'lane': 'process',
                           'timeout': EXPORT_TIMEOUT_SECONDS},
    'sftp_download': {'entry': run_sftp_download, 'lane': 'thread',
                      'timeout': SFTP_DOWNLOAD_TIMEOUT_SECONDS},
}

_pool = None
_pool_lock = threading.Lock()
_pool_failed = False
_download_pool = None
_download_lock = threading.Lock()
_in_flight: dict[int, 'tuple[Future, float, int, str]'] = {}
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
    return _base_task(params=params, abs_path=abs_path, fmt=fmt,
                      job_id=job_id, owner_id=owner_id) | {
        'filters': grid_filters_from(params),
        'hidden_columns': list(hidden_columns or []),
    }


def build_batch_charts_task(*, params, abs_path, fmt, job_id, owner_id,
                            dpi, cpk_thresholds, chart_format='xlsx') -> dict:
    """批量图表：图形开关与 dpi/CPK 阈值都必须在主进程钳成纯标量再进 task。

    这里**没有** hidden_columns：隐藏列是表格/xlsx 数据区的概念，图表产物用不上。
    """
    show_keys = ('show_limit', 'show_3sigma', 'show_4sigma',
                 'show_6sigma', 'show_normal', 'show_kde')
    return _base_task(params=params, abs_path=abs_path, fmt=fmt,
                      job_id=job_id, owner_id=owner_id) | {
        'params': list(params.get('params') or []),
        'chart_format': chart_format,
        'dpi': int(dpi),
        'cpk_thresholds': tuple(cpk_thresholds),
        'data_only_bin1': bool(params.get('data_only_bin1')),
        **{k: params.get(k, True if k == 'show_limit' or k == 'show_6sigma' else False)
           for k in show_keys},
    }


def build_html_report_task(*, params, abs_path, fmt, job_id, owner_id,
                           dpi, cpk_thresholds, datafile, generated_at) -> dict:
    """HTML 报告：`datafile` 只带 id/filename/program_name 三个字段进 worker。"""
    return _base_task(params=params, abs_path=abs_path, fmt=fmt,
                      job_id=job_id, owner_id=owner_id) | {
        'dpi': int(dpi),
        'cpk_thresholds': tuple(cpk_thresholds),
        'data_only_bin1': bool(params.get('data_only_bin1')),
        'datafile': {'id': datafile.id, 'filename': datafile.filename,
                     'program_name': datafile.program_name},
        # 时间戳钉在提交那一刻：随队列长度漂移的「生成时间」是在骗用户
        'generated_at': generated_at,
    }


def _base_task(*, params, abs_path, fmt, job_id, owner_id) -> dict:
    """三类作业共用的部分：绝对路径、结果位置、进度侧车路径。"""
    _rel, abs_dir = result_dirs(owner_id, job_id)
    name = params.get('result_name') or 'export.xlsx'
    out_path = os.path.join(abs_dir, name)
    return {
        'abs_path': abs_path,
        'fmt': fmt,
        'out_path': out_path,
        'result_name': name,
        'progress_path': os.path.join(abs_dir, PROGRESS_FILENAME),
    }


def _get_download_pool():
    """IO-bound 作业用的线程池（懒建，上限 MAX_DOWNLOAD_WORKERS）。"""
    global _download_pool
    if _download_pool is None:
        with _download_lock:
            if _download_pool is None:
                _download_pool = ThreadPoolExecutor(
                    max_workers=MAX_DOWNLOAD_WORKERS, thread_name_prefix='jobs-dl')
    return _download_pool


def submit(job: Job, task: dict) -> None:
    """按 lane 投进对应的池，并把状态推到 running。

    调用方（视图）已经存好 Job 行；这里失败就抛，由视图决定降级方式。
    """
    spec = KIND_RUNNERS[job.kind]
    entry, timeout = spec['entry'], spec['timeout']
    pool = _get_pool() if spec['lane'] == 'process' else _get_download_pool()
    future = pool.submit(entry, task)
    # 第 4 个元素是进度侧车路径：进程 lane 的 worker 没有 Django 写不了 DB，
    # 由轮询器代读；thread lane 自己写 DB，这里就是空串。
    _in_flight[job.id] = (future, time.monotonic(), timeout,
                          task.get('progress_path') or '')
    Job.objects.filter(pk=job.id).update(status='running', started_at=timezone.now())
    future.add_done_callback(lambda f: _write_back(job.id, f))
    _ensure_monitor()


def _write_back(job_id: int, future: 'Future') -> None:
    """把结果写回 Job 行。跑在线程池的管理线程里 ⇒ 用完必须还连接。

    只回填**还没进终态**的行：thread lane 的下载作业会自己边跑边写
    （partial failure 时它把「哪几只失败」写进 error），这里无脑覆盖会把那句人话抹掉。
    """
    try:
        _in_flight.pop(job_id, None)
        pending = Job.objects.filter(pk=job_id).exclude(
            status__in=('done', 'error', 'cancelled'))
        try:
            result = future.result()
        except Exception as exc:
            logger.exception('job %s failed', job_id)
            pending.update(status='error', error=f'{type(exc).__name__}: {exc}',
                           finished_at=timezone.now())
            return
        if result.get('downloadable') is False:
            return          # entry 自己已经把 result_path/name 写好了
        pending.update(
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
    """在飞作业的看门狗：读进度侧车 + 判超时。

    周期是 `MONITOR_INTERVAL`=5s，比 spec §4.3 说的「1 次/秒/作业」更省 ——
    SQLite 每 5 秒一次单字段 UPDATE，20 人 × 3 类作业也不会写放大；
    进度条 5 秒一跳对人是可读的。改这个节奏只改常量，别改循环。
    """
    idle = 0
    while True:
        if not _in_flight:
            idle += 1
            if idle > 2:
                return                      # 空闲就收工，下次 submit 再拉起
        else:
            idle = 0
            now = time.monotonic()
            for job_id, (future, started, timeout, progress_path) in list(_in_flight.items()):
                if now - started > timeout:
                    _in_flight.pop(job_id, None)
                    future.cancel()
                    Job.objects.filter(pk=job_id, status='running').update(
                        status='error', error=f'超时 {timeout // 60} 分钟，已中止',
                        finished_at=timezone.now())
                    continue
                percent = read_progress(progress_path) if progress_path else 0
                if 0 < percent < 100:
                    # 只推进、不回退：worker 崩在半路时这里读到的是最后已知值，
                    # 而 done 由 _write_back 统一置 100，轮询器不许抢跑。
                    Job.objects.filter(pk=job_id, status='running').exclude(
                        progress__gte=percent).update(progress=percent)
        connections.close_all()
        time.sleep(MONITOR_INTERVAL)


def reset_for_tests() -> None:
    """关掉两条池与看门狗，让测试用例之间不共享子进程/线程状态。"""
    global _pool, _pool_failed, _monitor_thread, _download_pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
        _pool_failed = False
    with _download_lock:
        if _download_pool is not None:
            _download_pool.shutdown(wait=False, cancel_futures=True)
        _download_pool = None
    _in_flight.clear()
    with _monitor_lock:
        _monitor_thread = None
