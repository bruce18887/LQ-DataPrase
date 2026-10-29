"""作业执行器：常驻进程池 + 状态回填 + 超时看门狗 + 降级判定。

跑在**主进程**里（可以 import Django）。它负责两件事，边界很清楚：

* 主进程侧：读 settings / DataFile / 用户设置，把任务拼成**纯数据 dict**（`build_*_task`）；
* 子进程侧：只调 `apps.jobs.runner` 里的顶层函数（那里禁止 Django）。

为什么是进程池而不是线程池：导出是 CPU-bound，`futures.result()` 在主线程里等
和直接在主线程里算，对其它用户没有区别 —— 只有把活交给另一个进程，
请求线程才能立刻回去接下一个用户。
"""

import logging
import multiprocessing
import os
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import NamedTuple

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
# 显式钉 spawn，不靠平台默认：Windows 默认就是 spawn，Linux 默认是 fork。
# fork 会把主进程的 Django 状态和已打开的 DB 连接带进子进程，而 lane=process 的
# 全部契约是「子进程里没有 django.setup()」（见 apps/jobs/runner.py 模块头）；
# fork 自多线程进程还带来 BrokenProcessPool 家族。
# Linux 服务器形态（2026-10-23 拍板）上线后，这条契约就只剩这一行在守：
# 判据 `test_worker_modules_import_without_django_setup` 只保证「不 import Django」，
# 保证不了「子进程是干净的」。
_MP_CONTEXT = multiprocessing.get_context('spawn')
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


class _Flight(NamedTuple):
    """`_in_flight` 的值：一条在飞作业的 future、两套时钟、侧车与所属的池。

    * `started is None` ⇒ 「进度一眼还没见到」（有侧车可读的作业在首次见到进度前不烧
      **执行**预算）。但它不等于没有上限 ——
    * `deadline = 提交时刻 + timeout` 在 `submit()` 那刻就定死，进度始终见不到的作业
      到点一样判死 —— 为什么必须有这道闸（含「少了它就是永久 running + 永久在飞」）
      只在 `_monitor_pass` 讲一处，这里只给字段口径。
    * `pool` 是这条作业提交进去的那条池（进程 lane ⇒ `_pool`，thread lane ⇒
      `_download_pool`）。`_discard_pool()` 只按它认领「随这次丢弃一起没掉的作业」，
      不按 lane 猜：崩池与下载池互不相干，判错池就是把还在产出的作业标成失败。
    """
    future: 'Future'
    started: 'float | None'
    timeout: int
    progress_path: str
    deadline: float
    pool: object


_in_flight: 'dict[int, _Flight]' = {}
_monitor_thread = None
_monitor_lock = threading.Lock()


class PoolBroken(RuntimeError):
    """池里的子进程已经死了，这个池不再可用。

    刻意定义成**本模块的**异常而不是让 `BrokenProcessPool` 冒到视图层：
    视图只认得「该降级」这件事。原缺陷就是把标准库异常直接抛出去，
    `_dispatch` 不接 ⇒ 500，而 `executor_available()` 因为「池对象还在」照样
    返回 True ⇒ 此后的每一次提交都 500，直到有人重启进程。
    """


def _discard_pool() -> None:
    """丢掉坏池，让下一次 `_get_pool()` 重建；**并替它丢掉的那些作业落终态**。

    不置 `_pool_failed`：那是「这台机器建不起池」的永久判定，而崩池通常是
    一次性的（实测成因是 OpenBLAS 在 commit 逼近上限时分配失败并放弃），
    压力过去后重建就能恢复。代价可控：每次崩池只有**紧接着的那一条**请求走同步。
    """
    global _pool
    with _pool_lock:
        broken, _pool = _pool, None
    if broken is not None:
        dropped = _reap_discarded(broken)
        try:
            broken.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001 — 池已经坏了，关不掉不是新问题
            logger.debug('broken pool shutdown failed', exc_info=True)
        if dropped:
            logger.warning('the discarded pool took %s in-flight job(s) down with it;'
                           ' they landed as error, the user has to resubmit', dropped)
    logger.warning('jobs pool broke; discarding it so the next submit rebuilds')


def _reap_discarded(pool) -> int:
    """给「随这条池一起被丢掉」的作业落终态，返回落行的条数（丢弃者就是发起方）。

    为什么必须有这一步（provenance，本机 CPython 3.13.12，取法 `python -V`）：
    `ProcessPoolExecutor.shutdown(wait=False, cancel_futures=True)` 只置
    `_cancel_pending_futures` 并唤醒管理线程，真正逐条取消排在 call queue 之外的
    工作项在 `_ManagerBase.flag_executor_shutting_down`（该版本 :519-523
    `if not work_item.future.cancel()`），而 `Future.cancel()` 会照常触发 done-callback。
    本机实测见
    `test/backend/test_job_terminal_ownership.py::RealPoolDiscardTests`：
    max_workers=1 + 一条占住 child + 5 条排队 ⇒ 队尾 4 条全变 `cancelled()`，回调一个
    不落，且**全部跑在管理线程里**（`shutdown(wait=False)` 返回时一个都还没跑 ⇒ 这道
    收手**不能**建立在「此刻已经 cancelled」上，只能按 `_Flight.pool` 认领）。
    回调进 `_write_back` 后见 `future.cancelled()` 就收手（那句是对的：取消的发起方
    才知道该怎么说），于是条目被摘出 `_in_flight` 而行永远停在 running ——
    看门狗再也看不见它，前端永远轮询一个死作业。改动前它至少落在
    `error='CancelledError: '`（丑，但是终态）。所以丢弃者自己认领终态。

    先写行、后 `shutdown()`：这样不必和稍后在管理线程里跑的那次回调抢次序。被这一轮
    认领的条目只有两种时刻 —— 登记它的线程已把行写成 running（守卫命中，终态落得下去），
    或还没走到那一句（守卫命中 0 行，但它登记之后的 `_pool` 身份复核会摘掉这条并抛
    `PoolBroken`，行由视图的同步回落落终态）。**没有第三种**「条目被摘走而行永远停在
    running」，这句是 2026-10-29 补上那次复核之后才成立的（判据
    `test_job_terminal_ownership.py::PoolDiscardedBeforeRegistrationTests`），别当显然。
    已由别的发起方先落终态的行（`cancel_queued` / `_timed_out` / worker 自己写的 done）
    守卫命中 0 行 ⇒ 不覆。
    变异自证（2026-10-29 本机）：把 `_discard_pool` 里这一次调用删掉 ⇒
    `test_job_terminal_ownership.py::PoolDiscardTerminalTests` 红（行留在 `running`、
    `error=''`，正是评审复现出来的那个形状）。
    """
    dropped = [job_id for job_id, flight in list(_in_flight.items())
               if flight.pool is pool]
    for job_id in dropped:
        _in_flight.pop(job_id, None)
        Job.objects.filter(pk=job_id, status='running').update(
            status='error', error='进程池已重建，作业被丢弃，请重试',
            finished_at=timezone.now())
    return len(dropped)


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
            _pool = ProcessPoolExecutor(max_workers=MAX_POOL_WORKERS,
                                        mp_context=_MP_CONTEXT)
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

    调用方（视图）已经存好 Job 行；这里失败就抛，由视图决定降级方式 ——
    池已断的情况抛 `PoolBroken`（视图据此走同步回落），别让它以标准库异常的形状
    漏到 DRF 变成 500。
    """
    spec = KIND_RUNNERS[job.kind]
    entry, timeout = spec['entry'], spec['timeout']
    pool = _get_pool() if spec['lane'] == 'process' else _get_download_pool()
    try:
        future = pool.submit(entry, task)
    except BrokenProcessPool as exc:
        _discard_pool()
        raise PoolBroken(str(exc)) from exc
    # `progress_path` 是进度侧车路径：进程 lane 的 worker 没有 Django 写不了 DB，
    # 由轮询器代读；thread lane 自己写 DB，这里就是空串。
    # `started` 由 `_start_clock()` 决定（有侧车 ⇒ 先不烧执行预算）；`deadline` 是
    # **绝对上限**（提交时刻 + timeout），进度一眼没见过的作业靠它判死。
    progress_path = task.get('progress_path') or ''
    submitted_at = time.monotonic()
    _in_flight[job.id] = _Flight(future, _start_clock(progress_path, submitted_at),
                                 timeout, progress_path,
                                 submitted_at + timeout, pool)
    Job.objects.filter(pk=job.id).update(status='running', started_at=timezone.now())
    # 登记之后复核身份：`_discard_pool()` 在别的线程里**先**换 `_pool`、**后**由
    # `_reap_discarded` 收取尸快照，所以「登记夹在两者之间」那条交错会漏出认领名单；
    # 而 swap 一定早于快照 ⇒ 这一比恰好逮住它（判据
    # `test_job_terminal_ownership.py::PoolDiscardedBeforeRegistrationTests`）。
    # 复核必须在那句 running update **之后**：丢弃若落在「已登记、行还没写成 running」
    # 那一格，快照带上这条但守卫命中 0 行 —— 先写 running 再复核才两格都盖得住。
    # 抛出去时行是 running 而不是 pending：`_dispatch` 接 `PoolBroken` 必走同步回落
    # （done/error 两分支都终态），而开机自愈 `mark_interrupted_jobs` 的名单里只有 running。
    # thread lane 不比：它没有丢弃通路（`_download_pool` 只被 `reset_for_tests()` 换过，
    # 没有任何 `_discard_*`），而对它 `_pool is not pool` 恒真 —— 不加 lane 条件
    # 就是把每条下载都判成池坏（本族第三条判据钉着，别给它补死分支）。
    if spec['lane'] == 'process' and _pool is not pool:
        _in_flight.pop(job.id, None)
        raise PoolBroken('jobs pool was discarded while this job was being registered')
    future.add_done_callback(lambda f: _write_back(job.id, f))
    _ensure_monitor()


def _start_clock(progress_path: str, submitted_at: float):
    """`_in_flight` 执行预算起点的初值：有侧车 ⇒ `None`（等首次进度），没侧车 ⇒ 提交时刻。

    「排队时间不该烧执行预算」要能判定，前提是看得出**作业开跑了没有**。只有
    `run_export_excel` 一进来就写侧车（`apps/jobs/runner.py:119` 的
    `write_progress(...,1,3)`，在 `_parse_and_filter` 之前）；另外两个入口
    `run_export_batch_charts`（`:139` 解析 → `:151` 才第一次写）与
    `run_export_html_report`（`:181` 解析 → `:182`）都是**先解析后写侧车** ⇒
    「侧车出现第一个 >0 的值」才是开跑证据，起点由看门狗在那一刻按下。
    别概括成「worker 一进来就写侧车」，那句只对 `:119` 成立；解析阶段卡死会怎样、
    为什么绝对上限一步都不能少，只在 `_monitor_pass` 讲一处。

    thread lane（SFTP 批量下载）拿不到这个证据：`sftp_job.build_sftp_task()` 不往 task
    里放 `progress_path`（`apps/jobs/sftp_job.py::build_sftp_task`），它的进度是 worker
    自己写 DB 的 `Job.progress`，看门狗在循环里读不到侧车（`percent` 恒 0）。计划稿那句
    「thread lane 用首次 DB 进度写」在这里没有可操作的落点：改成让看门狗去读 DB 的
    progress 列，就得给**每条在飞作业每 5 秒加一条 SELECT**，而 `_monitor()` 的
    docstring 立的正是「别把每作业轮询放大」这条反例 —— 为一个本来就自限时长的
    lane 付这个代价不值。
    下载 lane 的时长由它自己的 `timeout_sec` 管：提交时钳在 [30, 3600]
    （`views.py::_submit_sftp` + `apps/sftp/downloads.py::clamp_timeout`），且**逐只文件**
    生效，卡死那一只会自己断。所以这里保持旧口径（submit 即起表），
    `SFTP_DOWNLOAD_TIMEOUT_SECONDS` 的 2 小时绝对上限照旧兜底，没被这次改动削掉。
    """
    return None if progress_path else submitted_at


def cancel_queued(job_id: int) -> bool:
    """取消**还没挤进 call queue** 的作业（真池里就是第 `capacity+1` 条起，见下）：
    成功 ⇒ 行已写成 `cancelled` 并返回 True。

    判据是 future 的可取消性，不是行上的状态字 —— `submit()` 在同一次请求里就把行
    推成 running，「排队中」在库里从来就是 running，只认 pending 的旧口径等于
    「凡走 API 提交的作业全都取消不了」。别说成「躺在池里没开跑的都能取消」：
    缓冲在 call queue 里的那些也没开跑，但父 future 已是 RUNNING ⇒ 一律 409。

    **窗口有多窄，说清楚（本机 CPython 3.13.12，取法 `python -V`；依据
    `concurrent/futures/process.py:395`/`:727` 两处源码 +
    `test/backend/test_job_cancel.py::RealPoolQueueWindowTests` 用真 spawn 池实测，
    本机 MAX_POOL_WORKERS=4）**：父 future 的 PENDING→RUNNING 是在
    `add_call_item_to_queue` 把工作项**推进 bounded call queue** 的那一刻翻的，不是
    worker 出队那一刻；队列容量 = `max_workers + EXTRA_QUEUED_CALLS` = 5。
    于是 `future.cancel()` 的真实判据是「有没有挤进那 5 格」：
    * 第 1–5 条（正在执行的 4 条 + 缓冲在 call queue 里的第 5 条）都已是 RUNNING
      ⇒ `cancel()` False ⇒ 409。**并发 ≤5 条时这个端点等于恒 409**，与改动前无异；
    * 从第 `max_workers + EXTRA_QUEUED_CALLS + 1` 条起（父 future 仍 PENDING）⇒
      `cancel()` True ⇒ 200，且它从未进过任何 worker ⇒ 不会有孤儿产物。
    好消息那一半是真的：`cancel()` 对**已开跑**的作业永远返回 False（RUNNING 不可取消），
    所以「取消成功 ⇒ 磁盘上不会多出半个文件」这条成立；坏消息那一半是窗口确实窄。

    返回 False 的两种场合调用方都要维持 409：
    * `future.cancel()` 返回 False ⇒ 工作项已进 call queue（缓冲中）**或**已被 worker
      领走 —— 父 future 这两态都是 RUNNING，从主进程侧分不出来。杀它要么留下半个
      文件，要么把还在产出的作业标成失败。
    * `_in_flight` 里没有这条 ⇒ 本进程的池看不见它（同步降级 `_sync_fallback` 在同一
      请求线程里跑完，压根不登记在飞表；别的进程/机器在跑同理）。提前判死等于把
      还在产出的作业标成失败，而它随后照样会写盘。

    写行带 `status='running'` 守卫：`cancel()` 成功后 `Future._invoke_callbacks()` 在
    **本线程内联**跑 `_write_back`，而回填见到 `future.cancelled()` 就收手（不再抢写
    那句用户读不懂的 `CancelledError: `），所以行此刻仍是 running，这一句才落得下去。
    守卫挡掉的是同一窗口里**别的通路先写的终态**：看门狗刚好判了「超时 N 分钟」，
    或 worker 自己落了 done/error —— 那些行不许被「已取消」覆掉（future 确实被取消了，
    所以这里仍返回 True，视图据库里那行真相回 payload，不假装 cancelled）。
    """
    entry = _in_flight.get(job_id)
    if entry is None or not entry.future.cancel():
        return False
    Job.objects.filter(pk=job_id, status='running').update(
        status='cancelled', error='', finished_at=timezone.now())
    return True


def _write_back(job_id: int, future: 'Future') -> None:
    """把结果写回 Job 行。跑在线程池的管理线程里 ⇒ 用完必须还连接。

    只回填**还没进终态**的行：thread lane 的下载作业会自己边跑边写
    （partial failure 时它把「哪几只失败」写进 error），这里无脑覆盖会把那句人话抹掉。

    被取消的作业**一律不在这里落终态**：取消的发起方才知道该说什么 ——
    `cancel_queued` 说「已取消」、看门狗的 `_timed_out` 说「超时 N 分钟，已中止」、
    崩池的 `_reap_discarded` 说「进程池已重建，作业被丢弃」。这里要是抢先写
    `error='CancelledError: '`，用户看到的就是一段内部异常文本。
    这道收手由 `test/backend/test_job_cancel.py::WriteBackGuardTests` 钉着；
    也正因为有它，**每个**发起方都必须自己落终态 —— 崩池那条路过去没有发起方，
    作业就再也没人写（见 `_reap_discarded`）。
    """
    try:
        _in_flight.pop(job_id, None)
        if future.cancelled():
            return          # 终态由取消的发起方写，这里连 error 都不该碰
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


def _timed_out(job_id: int, future: 'Future', timeout: int) -> None:
    """到点判死的唯一动作：摘出在飞表 → 出声 → 写终态 error → 试取消。

    承重的只有一件事：**这里必须摘条目**，别指望 `future.cancel()` 那次回调替它摘 ——
    RUNNING（已进 call queue）的 future `cancel()` 返回 False ⇒ 不会触发 `_write_back`
    ⇒ 条目留下就每轮重判一次，而看门狗收不了工的后果见 `_monitor_pass` 末段。
    变异自证（2026-10-29 本机）：删掉这一行 ⇒
    `test_job_cancel.py::TimeoutClockOriginTests` 的四条判据与本文件的
    `test_expired_deadline_reaps_a_leaked_entry_without_touching_a_done_row` 同时红。

    三句之间的**先后不承重**（同一变异批实测：把 `future.cancel()` 挪到写行之前、或把
    摘条目挪到最后一句，两个文件 23 条判据全绿）—— 因为回填见 `future.cancelled()` 就
    收手（`_write_back`），且下面这句 UPDATE 带 `status='running'` 守卫。仍保持现在这个
    顺序只是取向：让「超时 N 分钟，已中止」先落库，不把正确性押在那道收手上。
    **别把它写成守卫** —— 上一版注释那句「两处顺序都是承重的…别调换」是过度声称，
    2026-10-29 评审抓的正是它。
    """
    _in_flight.pop(job_id, None)
    logger.warning('job %s timed out after %s s, killed as error', job_id, timeout)
    Job.objects.filter(pk=job_id, status='running').update(
        status='error', error=f'超时 {timeout // 60} 分钟，已中止',
        finished_at=timezone.now())
    future.cancel()


def _monitor_pass(now: float) -> None:
    """看门狗的一轮：判超时（两套时钟）→ 读侧车 → 首次见到进度时按下执行起点。

    从 `_monitor()` 的循环体里抽出来是**为了可测**：C1 的判据要能造出
    「在队列里等过一整段预算、之后又被推进了一次」这种时钟，真线程里既等不起
    也不该等。循环本身只管节奏与收工，语义全在这一函数里。

    两套时钟的分工：`started`（执行预算，首次进度才按下）与 `deadline`（绝对上限，
    submit 那刻定死，两者都是 `_Flight` 的字段）。**每一次 `_monitor_pass` 至少有
    一个时钟在管**，不存在「永远不超时」的分支（判据 `test_job_cancel.py::TimeoutClockOriginTests`）。

    这条不变量同时是看门狗**收得了工**的凭据，也是「永久 running」那个形状的唯一解，
    所以下面这段只在这里讲一遍（`_Flight`、`_start_clock`、`_timed_out` 与判据文件
    都只留指针）：`run_export_batch_charts`、`run_export_html_report` 把解析放在第一次
    `write_progress` **之前** ⇒ 解析卡死的作业侧车永远是 0 ⇒ `started` 永远是 None；
    少了 `deadline` 就是永久 running + 永久在飞，而条目躺在 `_in_flight` 里判不死，
    `_monitor()` 的空闲退出（`idle > 2`）就永远走不掉，那条 5s 轮询线程连着它每轮的
    DB 连接一起永生 —— 只能等下次进程启动的 `mark_interrupted_jobs`
    （`apps/jobs/apps.py::mark_interrupted_jobs`）擦屁股。旧实现的 30/60 分钟超时
    拦住的正是它，所以绝对上限一步都不能少。
    """
    for job_id, flight in list(_in_flight.items()):
        if flight.started is None:
            # 执行预算还没按下 ⇒ 由绝对上限兜底。**这一支不许省**，为什么只能在
            # 本函数 docstring 里读。口径与旧实现一致：判死看的是「看门狗有没有见过
            # 进度」，同一轮里即便侧车已经有值也先判死（旧那版从 submit 起算，
            # 本就没有「晚到进度」这回事）。
            if now > flight.deadline:
                _timed_out(job_id, flight.future, flight.timeout)
                continue
            # 没越线就继续往下读侧车：这一轮可能就是「首次见到进度」，执行预算要在
            # 这里按下 —— 早退（`continue`）等于把所有作业退回旧口径（submit+timeout）。
        elif now - flight.started > flight.timeout:
            _timed_out(job_id, flight.future, flight.timeout)
            continue
        percent = read_progress(flight.progress_path) if flight.progress_path else 0
        if percent > 0 and flight.started is None:
            # 首次读到进度 > 0 ⇒ 作业真的开跑了，执行预算从这一刻起算，**每作业只钉一次**
            # （每见到新进度都重置起点，等于让长作业永远超不了时）。
            # `is flight` 不是「防不可能发生的事」—— 这条竞态真的走得到（回填线程与本
            # 线程之间没有任何同步），诚实的口径是：后果只到「把已结束的条目塞回在飞表
            # ⇒ 一条泄漏条目 + 看门狗多活几轮」，写不出错行（下面的 UPDATE 都带
            # `status='running'` 守卫，终态行不匹配）；且泄漏条目最迟在绝对上限那轮被
            # `_timed_out` 摘掉，走不到上面那段永生。两件事都由
            # `test_job_terminal_ownership.py::TimedOutOwnershipTests` 的
            # `test_expired_deadline_reaps_a_leaked_entry_without_touching_a_done_row`
            # 钉着（条目摘掉 + 终态行原样不动），别再把它当成散文。
            if _in_flight.get(job_id) is flight:
                _in_flight[job_id] = flight._replace(started=now)
        if 0 < percent < 100:
            # 只推进、不回退：worker 崩在半路时这里读到的是最后已知值，
            # 而 done 由 _write_back 统一置 100，轮询器不许抢跑。
            Job.objects.filter(pk=job_id, status='running').exclude(
                progress__gte=percent).update(progress=percent)


def _monitor() -> None:
    """在飞作业的看门狗：读进度侧车 + 判超时（每一轮见 `_monitor_pass`）。

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
            _monitor_pass(time.monotonic())
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
