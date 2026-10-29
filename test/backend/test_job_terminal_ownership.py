"""C1 判据第二族：**谁**给一条作业落终态（terminal-state ownership）。

上游：`docs/superpowers/plans/2026-10-28-backend-perf-remediation.md` Task C1
（评审 2026-10-29 的 Critical 就在这一族）。共享道具在
`test/backend/job_cancel_fixtures.py`，时钟与取消窗口在 `test/backend/test_job_cancel.py`。

终态的发起方有三个，且必须**只有一个**落得下去（都带 `status='running'` 守卫）：

* `cancel_queued` ⇒ `cancelled` / 空 error
  —— 由 `test_job_cancel.py::CancelRunningJobTests` 钉；
* 看门狗 `_timed_out` ⇒ 「超时 N 分钟，已中止」
  —— 由 `test_job_cancel.py::TimeoutClockOriginTests` 与本文件的日志那条钉；
* 崩池丢弃 `_reap_discarded` ⇒ 「进程池已重建，作业被丢弃，请重试」—— 本文件钉。

评审抓到的洞是第三个：`_write_back` 见 `future.cancelled()` 就收手（前两个发起方各自
有话说，这句是对的），而**崩池这条路没有发起方** —— `ProcessPoolExecutor.shutdown(
wait=False, cancel_futures=True)` 把还排在 call queue 之外的 PENDING 工作项全部取消
并照常触发 done-callback（前提由本文件 `RealPoolDiscardTests` 用真 spawn 池核过），
于是条目被回调摘出 `_in_flight`、行却永远停在 running，看门狗再也看不见它。
改动前它至少落在 `error='CancelledError: '`（丑，但是终态）—— 这道收手本身是必要的，
缺的是「丢弃者自己认领终态」。同一族的 `PoolDiscardedBeforeRegistrationTests` 钉它
剩下的那条**时间缝**：收尸快照早于登记 ⇒ 这条没人认领 ⇒ 行永远 running；修法是登记后
复核 `_pool` 身份，把它变成 `PoolBroken` 交回视图的同步回落。

跑法：`python -X utf8 manage.py test test.backend.test_job_terminal_ownership`
"""

import multiprocessing
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from unittest import mock

from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.jobs import executor
from apps.jobs.models import Job
from apps.jobs.runner import write_progress
from test.backend.job_cancel_fixtures import (
    PASSWORD, ExecutorSeamMixin, FakePool, dropped_text)


class PoolDiscardTerminalTests(ExecutorSeamMixin, TransactionTestCase):
    """Critical：`_discard_pool()` 丢弃的作业必须由丢弃者落成终态，不许留在 running。"""

    def setUp(self):
        self.user = User.objects.create_user('c1_owner', 'co@localhost', PASSWORD)
        self._tmp_source()
        # capacity=0 ⇒ 父 future 全部 PENDING，正是真池里「排在 call queue 之外」
        # 那一档（第 capacity+1 条起）——也只有这一档会被 shutdown 取消掉。
        self._patch_seams(capacity=0)

    def test_discarding_the_broken_pool_lands_a_terminal_state(self):
        executor._pool = self.pool          # 「当下活着的池就是这条」⇒ _discard_pool 认领它
        dropped = [self._make_running_export() for _ in range(2)]
        # 同一窗口里已有发起方落了终态（`cancel_queued` 先写成 cancelled）⇒ 守卫不许覆
        claimed = self._make_running_export()
        self.mark_cancelled(claimed)
        # 对照组：thread lane 挂在**另一条**池上，崩池轮不到它，更不许被顺手判死
        download = FakePool(capacity=0)
        with mock.patch.object(executor, '_get_download_pool', lambda: download):
            sftp, task = self._download_job()
            executor.submit(sftp, task)
        self.assertEqual(len(self.pool.futures), 3)

        executor._discard_pool()

        for job in dropped:
            row = Job.objects.get(pk=job.id)
            self.assertEqual(
                row.status, 'error',
                f'崩池丢弃的作业留在 {row.status}：它已被回调摘出 `_in_flight`，'
                f'看门狗再也看不见 ⇒ 前端永远轮询一个死作业（error={row.error!r}）')
            self.assertEqual(row.error, dropped_text())
            self.assertTrue(row.finished_at, '终态行没有 finished_at 就是半截状态')
            self.assertNotIn(job.id, executor._in_flight)
        self.assertEqual(Job.objects.get(pk=claimed.id).status, 'cancelled',
                         '别的发起方先落的终态不许被「丢弃」覆掉')
        self.assertEqual(Job.objects.get(pk=claimed.id).error, '')
        ctl = Job.objects.get(pk=sftp.id)
        self.assertEqual(ctl.status, 'running', '下载池上的作业不许被崩池判死')
        self.assertIn(sftp.id, executor._in_flight)
        self.assertIsNone(download.shut_down, '崩池通路不许顺手关掉另一条池')
        self.assertTrue(all(f.cancelled() for f in self.pool.futures),
                        '前提走形：shutdown(cancel_futures=True) 没取消这些 future')


class DiscardingPool(FakePool):
    """假池在 `submit()` 返回前把这次丢弃做掉 —— 注入 `_get_pool()` 与登记之间那一格。

    丢弃全在同一线程里同步跑完（swap `_pool` → 收尸快照 → `shutdown(cancel_futures)`），
    时刻就是「`_in_flight` 还看不见这条作业」，所以判据不靠调度也不靠睡：
    这一格在 `executor.py` 里只有 `pool.submit(entry, task)` 一条语句，注入它 = 注入那格。
    """

    def submit(self, entry, task):
        future = super().submit(entry, task)
        executor._discard_pool()
        return future


def _sync_fallback_entry(box):
    """`_sync_fallback` 要跑的 entry：写一个真文件并登记自己跑过几次（判「落得下去」用）。"""
    def entry(task):
        os.makedirs(os.path.dirname(task['out_path']), exist_ok=True)
        with open(task['out_path'], 'wb') as fh:
            fh.write(b'c1 race sync fallback')
        box.append(task['out_path'])
        return {'out_path': task['out_path'], 'downloadable': True}
    return entry


class PoolDiscardedBeforeRegistrationTests(ExecutorSeamMixin, APITestCase):
    """评审 2026-10-29 的 Important：收尸快照**越过**了这次登记，于是没人认领这条。

    交错（`apps/jobs/executor.py`，两处都不持锁）：请求线程在 `submit()` 里读到池 P ⇒
    另一条线程 `_discard_pool()` 先换 `_pool`、`_reap_discarded` 才取快照 ⇒ 请求线程
    在快照**之后**才登记 `_in_flight`。这条漏出认领名单，而 P 的 shutdown 已经把它的
    future 取消了（本机 CPython 3.13.12：`Future.add_done_callback` 见 state 是
    `CANCELLED`/`CANCELLED_AND_NOTIFIED` 就**就地内联**调用回调 —— 取法
    `python -c "import inspect,concurrent.futures._base as b;
    print(inspect.getsource(b.Future.add_done_callback))"`），于是登记回调那一句跑进
    `_write_back`、见 `future.cancelled()` 收手：**条目被摘走、行永远停在 running**，
    看门狗再也看不见它 —— 正是 `_reap_discarded` 这一族要关掉的那个失败形状，
    只是换了一条没被认领的时间缝。（评审描述的是「条目留在在飞表」，实测落到的是
    「条目也被摘走」：损坏的那半在行上，判据按实测的形状断。）

    注入点只有上面那个缝是**可注入**的（`_get_pool()` 与登记之间就 `pool.submit()`
    一条语句）。评审另建议的两处：`_ensure_monitor()` 在复核之后，那里的丢弃快照与
    守卫都命中 ⇒ 改动前后都落得了终态，钉不到这个交错；「登记与那句 running update
    之间」这一格没有可注入的接缝（要换掉 `executor.Job` 这个 ORM 把手才能踩到），
    所以它不单独成判据，改由**复核的位置**保证 —— 位置由第一条判据末尾那句
    `status == 'running'` 钉住（把复核挪到 update 之前就红）。
    """

    def setUp(self):
        self.user = User.objects.create_user('c1_race', 'cr@localhost', PASSWORD)
        self._tmp_source()
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='tiny.csv', file_path=self.path,
            file_size=os.path.getsize(self.path), format_type='CTA8280F',
            status='ready', program_name='PROG')
        self.client.force_authenticate(user=self.user)
        self._patch_seams(capacity=0)

    def test_a_discard_that_missed_the_registration_raises_pool_broken(self):
        self.pool = DiscardingPool(capacity=0)
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='pending', params={})
        raised = None
        try:
            executor.submit(job, self._export_task(job))
        except executor.PoolBroken as exc:
            raised = exc

        row = Job.objects.get(pk=job.id)
        self.assertIsNotNone(
            raised,
            f'漏认领的交错没被逮住：行落在 status={row.status}、在飞表里有它='
            f'{job.id in executor._in_flight}、那条 future 已 cancelled='
            f'{self.pool.futures[-1].cancelled()} ⇒ 回填收了手、条目被摘走、'
            f'看门狗再也看不见 ⇒ 行永远 running（评审那条形状）')
        self.assertNotIn(job.id, executor._in_flight,
                         '抛了 PoolBroken 却不摘条目 ⇒ 条目躺在作废的池上，每轮重判一次')
        self.assertIsNone(executor._pool, '前提走形：这次丢弃没把 `_pool` 换成 None')
        # 复核的**位置**也承重：必须在那句 running update 之后（见类 docstring 那一格），
        # 挪到之前 ⇒ 这里读到的是 pending，「丢弃夹在登记与 update 之间」那格就没人收尾。
        self.assertEqual(row.status, 'running',
                         '复核跑在了 running update 之前 ⇒ 那一格的行没人认领')

    def test_the_view_lands_the_missed_job_terminal_through_the_fallback(self):
        """复核那句 `PoolBroken` 经**真实视图路径**落到终态：`_dispatch` 接它 ⇒
        `_sync_fallback` 两个分支（成功写 done、异常写 error）都是终态，不是 500、
        也不是留下一个「running 但没人管」的行让前端永远轮询。
        """
        box = []
        self.pool = DiscardingPool(capacity=0)
        with mock.patch.dict(executor.KIND_RUNNERS['export_excel'],
                             {'entry': _sync_fallback_entry(box)}):
            resp = self.client.post('/api/v1/jobs/export_excel/',
                                    {'file_id': self.datafile.id}, format='json')

        self.assertEqual(resp.status_code, 200,
                         f'降级必须是文件流而不是 {resp.status_code}：'
                         f'{getattr(resp, "data", None)}')
        self.assertEqual(resp.get('X-Job-Fallback'), '1')
        self.assertEqual(len(box), 1, '同步回落没真的跑过一次 entry')
        job = Job.objects.filter(owner=self.user).order_by('-id').first()
        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'done', f'降级后行不是终态：{row.status}')
        self.assertEqual(row.error, '')
        self.assertTrue(row.finished_at)
        self.assertNotIn(job.id, executor._in_flight)

    def test_the_download_lane_is_not_tricked_by_the_same_check(self):
        """thread lane 今天**没有**丢弃通路（只有 `reset_for_tests()` 换过 `_download_pool`），
        而 `_pool is not pool` 对它恒真 —— 复核必须带 lane 条件，否则每条下载都被判成池坏。
        """
        executor._pool = None
        self.pool = FakePool(capacity=0)
        sftp, task = self._download_job()

        executor.submit(sftp, task)       # 不许抛

        self.assertIn(sftp.id, executor._in_flight)
        self.assertEqual(Job.objects.get(pk=sftp.id).status, 'running')


class TimedOutOwnershipTests(ExecutorSeamMixin, TransactionTestCase):
    """看门狗那一路的两个补充：出声，且摘掉泄漏条目时不碰已经终态的行。"""

    def setUp(self):
        self.user = User.objects.create_user('c1_timedout', 'tt@localhost', PASSWORD)
        self._tmp_source()
        self._patch_seams()

    def test_the_watchdog_says_in_the_log_why_it_killed_a_job(self):
        """库里写着「超时 30 分钟」而日志里查不到是谁写的 ⇒ 事后无法归因。

        级别刻意用 WARNING：`test_job_cancel.py::CancelRunningJobTests` 里那两处
        `assertNoLogs('apps.jobs.executor', level='ERROR')` 钉的是「回填别把用户的取消
        记成失败」，与本条不同级别，互不干扰。
        """
        job = self._make_running_export()
        budget = executor.EXPORT_TIMEOUT_SECONDS

        with self.assertLogs('apps.jobs.executor', level='WARNING') as captured:
            executor._monitor_pass(time.monotonic() + budget + 1)

        self.assertEqual(Job.objects.get(pk=job.id).status, 'error')
        self.assertTrue(
            any('timed out' in line and str(job.id) in line for line in captured.output),
            f'判死没有出声：{captured.output}')

    def test_expired_deadline_reaps_a_leaked_entry_without_touching_a_done_row(self):
        """`_monitor_pass` 那句「泄漏条目最迟在绝对上限那轮被 `_timed_out` 摘掉」的落地判据。

        泄漏的形状（回填线程与本线程的竞态，无任何同步）：条目被塞回 `_in_flight`，
        而 DB 行已经是 done。要同时成立两件事 —— 条目**被摘掉**（否则看门狗收不了工，
        那段后果只在 `executor._monitor_pass` 叙述），行**原样不动**（用户已经
        拿到产物，不许改判死）。`timeout` 走 `KIND_RUNNERS` 现读，所以用 patch.dict
        把绝对上限缩到 1 秒，再拿 `_monitor_pass(now)` 的显式 `now` 越线，不睡真秒。
        """
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='pending', params={})
        task = self._export_task(job)
        self._clear_sidecar(task)           # 侧车不存在 ⇒ started 恒 None ⇒ 归绝对上限管
        with mock.patch.dict(executor.KIND_RUNNERS['export_excel'], {'timeout': 1}):
            executor.submit(job, task)
        Job.objects.filter(pk=job.id).update(status='done', progress=100,
                                            result_name='r.xlsx',
                                            finished_at=timezone.now())
        self.assertIn(job.id, executor._in_flight)

        executor._monitor_pass(time.monotonic() + 60)

        self.assertNotIn(job.id, executor._in_flight,
                         '过期条目没被摘掉 ⇒ 看门狗永不收工')
        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'done', '绝对上限把已经 done 的行改判死了')
        self.assertEqual(row.progress, 100)
        self.assertEqual(row.error, '')
        self.assertEqual(row.result_name, 'r.xlsx')


class RealPoolDiscardTests(SimpleTestCase):
    """上面那条 Critical 的**前提**，用真 spawn 池核一遍（假池的 `shutdown` 是自己写的）。

    本机 CPython 3.13.12（取法 `python -V`）。真池的取消发生在**管理线程**里：
    `ProcessPoolExecutor.shutdown` 只置 `_cancel_pending_futures` 并唤醒管理线程
    （`concurrent/futures/process.py:842-851`），逐条 `future.cancel()` 的是
    `_ManagerBase.flag_executor_shutting_down`（该版本 :519-523，`cancel()` 里
    `_invoke_callbacks()` 就地把 done-callback 打出去）。本机三轮预跑实测同一形状：
    `shutdown(wait=False)` 返回时**一个回调都还没跑**，几毫秒后 6 个回调全部在
    管理线程里跑完 ⇒ 「摘的时候再看 `future.cancelled()`」是错的口径，
    生产的 `_reap_discarded` 只能按 `_Flight.pool` 认领。本用例取 `wait=True`
    把管理线程等干净（判据要的是确定性的前提，不是节奏），并把「回调不在主线程」
    这件事一起断下来。
    """

    def test_shutdown_with_cancel_futures_cancels_pending_items_and_fires_callbacks(self):
        workers, hold, queued_n = 1, 1.0, 5
        tmpdir = tempfile.mkdtemp(prefix='c1_discard_')
        self.addCleanup(shutil.rmtree, tmpdir, True)
        pool = ProcessPoolExecutor(max_workers=workers,
                                   mp_context=multiprocessing.get_context('spawn'))
        # `cancel_futures` 是关键字限定参数（本机 3.13.12），addCleanup 传不了位置参 ⇒ 用闭包。
        # 本用例那次 shutdown(wait=True) 之后，这条只是幂等收尾（源码里 None 都判过了）。
        self.addCleanup(lambda: pool.shutdown(wait=False, cancel_futures=True))

        # hold 那条占住唯一的 child：没有它，child 会一路把队列里的活吃掉，
        # 还剩几条 PENDING 就纯看机器快慢（判据要的是「有 PENDING 被取消」这个形状）。
        busy = pool.submit(time.sleep, hold)
        markers = [os.path.join(tmpdir, f'{i}.progress') for i in range(queued_n)]
        queued = [pool.submit(write_progress, p, 1, 3) for p in markers]
        fired = []                       # (future, 跑回调的线程名)
        for future in [busy] + queued:   # 注册时六个都还没结束 ⇒ 回调一律由管理线程代跑
            future.add_done_callback(lambda f, box=fired: box.append(
                (f, threading.current_thread().name)))

        pool.shutdown(wait=True, cancel_futures=True)

        cancelled = [f for f in queued if f.cancelled()]
        # 算术在这里，不靠运气：call queue 容量 = max_workers + EXTRA_QUEUED_CALLS = 2，
        # busy 占一格、排队五条最多再占一格 ⇒ 至少 4 条留在 PENDING。
        self.assertGreaterEqual(len(cancelled), 4,
                                f'call queue 之外没剩下多少条：{len(cancelled)}')
        self.assertFalse(busy.cancelled(), '已经交给 child 的那条不该被取消掉')
        for future in cancelled:
            self.assertIn(future, [f for f, _ in fired],
                          '被取消的作业没触发 done-callback ⇒ `_write_back` 不会跑，'
                          'Critical 的成因就不成立')
        self.assertEqual([os.path.exists(p) for p, f in zip(markers, queued)
                          if f.cancelled()], [False] * len(cancelled),
                         '被取消的工作项还是进了 child（侧车被写出）')
        # 落点在这里：六个回调**全部**在别的线程跑完（本机实测 `shutdown(wait=False)`
        # 返回时一个都还没跑）。⇒「摘的时候看一眼 `future.cancelled()`」在主线程里
        # 根本不成立，生产的 `_reap_discarded` 只能按 `_Flight.pool` 认领。
        self.assertEqual(len(fired), 1 + queued_n, '六个 future 的回调都该触发过')
        self.assertTrue(all(name != threading.main_thread().name for _, name in fired),
                        f'有回调落在主线程：{fired}')
