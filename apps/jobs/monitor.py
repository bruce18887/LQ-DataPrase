"""在飞作业的超时看门狗 —— 从 `apps/jobs/executor.py` 拆出的循环侧（2026-10-30）。

跑在**主进程**里（可以 import Django：models / timezone / connections），与 executor 同侧。
依赖方向是单向的：`executor` import 本模块，本模块**不** import `executor`。
为什么这个方向而不是反的：反方向（本模块从 executor 拿 `_in_flight`）会造出循环导入，
而「`submit()` 之后才拉起看门狗」意味着 executor 必须调用 monitor —— 边只能留在
executor→monitor 这一侧。在飞表 `_in_flight` 的所有权**仍在 executor**（`submit` 写它、
`_write_back` 摘它、`cancel_queued` 读它）；本模块的入口一律**显式接收这条 dict 作参数**
（接缝是调用时的参数，不是导入时的全局引用 ⇒ 测试把 `executor._in_flight` 整个换掉也照样
吃到当前绑定，判据可直接 `monitor._monitor_pass(now, fake_dict)` 喂表）。
这条方向同时保住 CPU worker 链路（`apps/jobs/runner.py`）的 Django-free：spawn 子进程
按 entry 的可 pickle 模块名 import 的只有 runner 那一串，永远不会走到本模块
（运行时判据：`test/backend/test_exit_pool_shutdown.py::RunnerChainProbeTests`）。

本模块的内容：`_ensure_monitor`（拉起）、`_monitor`（节奏与收工）、`_monitor_pass`
（一轮的语义，「两套时钟 + 永久 running 的后果」那段的**唯一**叙述处）、`_timed_out`
（到点判死的唯一动作）与 `MONITOR_INTERVAL`。executor 侧保留两个同名接缝函数
`_ensure_monitor` / `_monitor_pass`（薄壳，只做传参）：`submit()` 按模块全局查找它们，
测试接缝按名字 patch 它们（`test/backend/job_cancel_fixtures.py::_patch_seams`）。
"""

import logging
import threading
import time

from django.db import connections
from django.utils import timezone

from apps.jobs.models import Job
from apps.jobs.runner import read_progress

logger = logging.getLogger('apps.jobs.executor')
# ↑ 刻意用 executor 的名字，不是 __name__：判死那句 WARNING 的**日志通道**是判据
# 契约（`test/backend/test_job_terminal_ownership.py::TimedOutOwnershipTests::
# test_the_watchdog_says_in_the_log_why_it_killed_a_job` 按 `apps.jobs.executor`
# 捕获，运维在 userData/logs 里也按这个通道归因）。拆分搬的是实现，不许把归属一起搬走。

MONITOR_INTERVAL = 5.0

_monitor_thread = None
_monitor_lock = threading.Lock()


def _ensure_monitor(in_flight) -> None:
    """超时看门狗：只在有作业在飞时活着，空闲若干轮后自己退出。

    不留常驻线程 —— 桌面档里那是白占的一个线程和一条 DB 连接。
    """
    global _monitor_thread
    with _monitor_lock:
        if _monitor_thread and _monitor_thread.is_alive():
            return
        _monitor_thread = threading.Thread(target=_monitor, args=(in_flight,),
                                           daemon=True, name='jobs-monitor')
        _monitor_thread.start()


def _timed_out(job_id: int, future, timeout: int, in_flight) -> None:
    """到点判死的唯一动作：摘出在飞表 → 出声 → 写终态 error → 试取消。

    承重的只有一件事：**这里必须摘条目**，别指望 `future.cancel()` 那次回调替它摘 ——
    RUNNING（已进 call queue）的 future `cancel()` 返回 False ⇒ 不会触发 `_write_back`
    ⇒ 条目留下就每轮重判一次，而看门狗收不了工的后果见 `_monitor_pass` 末段。
    变异自证（2026-10-29 本机）：删掉这一行 ⇒
    `test_job_cancel.py::TimeoutClockOriginTests` 的四条判据与 `test_job_terminal_ownership.py` 的
    `test_expired_deadline_reaps_a_leaked_entry_without_touching_a_done_row` 同时红。

    三句之间的**先后不承重**（同一变异批实测：把 `future.cancel()` 挪到写行之前、或把
    摘条目挪到最后一句，两个文件 23 条判据全绿）—— 因为回填见 `future.cancelled()` 就
    收手（`executor._write_back`），且下面这句 UPDATE 带 `status='running'` 守卫。仍保持
    现在这个顺序只是取向：让「超时 N 分钟，已中止」先落库，不把正确性押在那道收手上。
    **别把它写成守卫** —— 上一版注释那句「两处顺序都是承重的…别调换」是过度声称，
    2026-10-29 评审抓的正是它。
    """
    in_flight.pop(job_id, None)
    logger.warning('job %s timed out after %s s, killed as error', job_id, timeout)
    Job.objects.filter(pk=job_id, status='running').update(
        status='error', error=f'超时 {timeout // 60} 分钟，已中止',
        finished_at=timezone.now())
    future.cancel()


def _monitor_pass(now: float, in_flight) -> None:
    """看门狗的一轮：判超时（两套时钟）→ 读侧车 → 首次见到进度时按下执行起点。

    从 `_monitor()` 的循环体里抽出来是**为了可测**：C1 的判据要能造出
    「在队列里等过一整段预算、之后又被推进了一次」这种时钟，真线程里既等不起
    也不该等。循环本身只管节奏与收工，语义全在这一函数里。

    两套时钟的分工：`started`（执行预算，首次进度才按下）与 `deadline`（绝对上限，
    submit 那刻定死，两者都是 `executor._Flight` 的字段）。**每一次 `_monitor_pass` 至少有
    一个时钟在管**，不存在「永远不超时」的分支（判据 `test_job_cancel.py::TimeoutClockOriginTests`）。

    这条不变量同时是看门狗**收得了工**的凭据，也是「永久 running」那个形状的唯一解，
    所以下面这段只在这里讲一遍（`_Flight`、`executor._start_clock`、`_timed_out` 与判据文件
    都只留指针）：`run_export_batch_charts`、`run_export_html_report` 把解析放在第一次
    `write_progress` **之前** ⇒ 解析卡死的作业侧车永远是 0 ⇒ `started` 永远是 None；
    少了 `deadline` 就是永久 running + 永久在飞，而条目躺在 `_in_flight` 里判不死，
    `_monitor()` 的空闲退出（`idle > 2`）就永远走不掉，那条 5s 轮询线程连着它每轮的
    DB 连接一起永生 —— 只能等下次进程启动的 `mark_interrupted_jobs`
    （`apps/jobs/apps.py::mark_interrupted_jobs`）擦屁股。旧实现的 30/60 分钟超时
    拦住的正是它，所以绝对上限一步都不能少。
    """
    for job_id, flight in list(in_flight.items()):
        if flight.started is None:
            # 执行预算还没按下 ⇒ 由绝对上限兜底。**这一支不许省**，为什么只能在
            # 本函数 docstring 里读。口径与旧实现一致：判死看的是「看门狗有没有见过
            # 进度」，同一轮里即便侧车已经有值也先判死（旧那版从 submit 起算，
            # 本就没有「晚到进度」这回事）。
            if now > flight.deadline:
                _timed_out(job_id, flight.future, flight.timeout, in_flight)
                continue
            # 没越线就继续往下读侧车：这一轮可能就是「首次见到进度」，执行预算要在
            # 这里按下 —— 早退（`continue`）等于把所有作业退回旧口径（submit+timeout）。
        elif now - flight.started > flight.timeout:
            _timed_out(job_id, flight.future, flight.timeout, in_flight)
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
            if in_flight.get(job_id) is flight:
                in_flight[job_id] = flight._replace(started=now)
        if 0 < percent < 100:
            # 只推进、不回退：worker 崩在半路时这里读到的是最后已知值，
            # 而 done 由 _write_back 统一置 100，轮询器不许抢跑。
            Job.objects.filter(pk=job_id, status='running').exclude(
                progress__gte=percent).update(progress=percent)


def _monitor(in_flight) -> None:
    """在飞作业的看门狗：读进度侧车 + 判超时（每一轮见 `_monitor_pass`）。

    周期是 `MONITOR_INTERVAL`=5s，比 spec §4.3 说的「1 次/秒/作业」更省 ——
    SQLite 每 5 秒一次单字段 UPDATE，20 人 × 3 类作业也不会写放大；
    进度条 5 秒一跳对人是可读的。改这个节奏只改常量，别改循环。
    """
    idle = 0
    while True:
        if not in_flight:
            idle += 1
            if idle > 2:
                return                      # 空闲就收工，下次 submit 再拉起
        else:
            idle = 0
            _monitor_pass(time.monotonic(), in_flight)
        connections.close_all()
        time.sleep(MONITOR_INTERVAL)


def reset_for_tests() -> None:
    """摘掉看门狗线程引用，让用例之间不共享线程状态。

    不 join：语义与拆分前 `executor.reset_for_tests` 里那段内联代码逐字一致
    （线程靠空闲自退，判据从不等它）。
    """
    global _monitor_thread
    with _monitor_lock:
        _monitor_thread = None
