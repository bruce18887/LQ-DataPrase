"""C1 判据：排队不烧执行预算、但**绝对上限仍在**，且取消窗口按真池的真实形状钉死。

上游：`docs/superpowers/plans/2026-10-28-backend-perf-remediation.md` Task C1。
共享道具（`FakePool`、`ExecutorSeamMixin`、两句人话口径）在
`test/backend/job_cancel_fixtures.py`；**终态归属**那一族另在
`test/backend/test_job_terminal_ownership.py` —— 分文件的唯一理由是 600 行绊线
（`scripts/line-limit.mjs`），不是两族判据互不相干。本文件钉三条行为，都不动契约
（不加列、不加新状态字符串）：

1. **两套时钟，每一轮至少有一套在管**（`executor._monitor_pass`）。
   * `started` = 执行预算起点，由「首次读到 progress > 0」按下 ⇒ 排队时间不烧预算；
   * `deadline` = `submit + timeout`，**submit 那一刻定死** ⇒ 进度一眼没见过的作业
     到点照样判死（为什么非有不可 —— 解析先于第一次 `write_progress`、少了这道闸
     会怎样 —— 只在 `_monitor_pass` 的 docstring 讲一处，本文件只留这个指针）。
   旧实现只有 `deadline` 那一个时钟；把它一起删掉是越权 —— 计划稿授权的只是
   「排队时间不烧**执行**预算」。

2. **`cancel` 放宽到 `running`，但窗口很窄**（本机 CPython 3.13.12，取法 `python -V`；
   依据是 `concurrent/futures/process.py:395`/`:727` 两处源码 + 本文件
   `RealPoolQueueWindowTests` 用真 spawn 池实测）：父 future 的 PENDING→RUNNING 是在
   工作项被**推进 bounded call queue**（容量 `max_workers + EXTRA_QUEUED_CALLS`，本机
   `MAX_POOL_WORKERS`=4 ⇒ 5）那一刻翻的，不是 worker 出队那一刻；RUNNING 的
   `Future.cancel()` 恒 False（`concurrent/futures/_base.py::Future.cancel`）。
   ⇒ 可取消的只有排在**第 6 条以后**的那一段；并发 ≤5 条时端点仍等于恒 409
   （与改动前无异）。真的一半：`cancel()` 对已开跑的作业永不为 True ⇒ 「取消成功
   不留孤儿产物」成立。

3. **取消/判死的终态各归其主**：`_write_back` 见 `future.cancelled()` 就收手，
   「已取消」由 `cancel_queued` 写、`超时 N 分钟` 由看门狗写，且两处都带
   `status='running'` 守卫 —— 同一窗口里先落的那句终态不许被后落的覆掉
   （第三个发起方「崩池丢弃」在 `test_job_terminal_ownership.py`）。

大多用例绕开真进程池：换成假池才能确定性地地理出「一直排在队列里没人领」，而这些
判据全跑在主进程侧。但假池**必须照真池的状态机走**（见 fixtures 里的 `FakePool`，
那里把它与真池**刻意**不同的两处也写清了），否则它会替生产撒谎；边界本身另由
`RealPoolQueueWindowTests` 对真池核一遍（先例：`apps/jobs/tests_jobs.py:603` 的
`RealPoolEndToEndTests`）。一律 `TransactionTestCase`（`APITestCase` 就是它的子类）：
`cancel_queued` 成功时 `Future.cancel()` 会**在调用线程里内联**触发 `_write_back`，
它用完把 DB 连接还掉，而 `TestCase` 那层未提交的事务会随那次关闭一起丢掉
（逐字解释见 `apps/jobs/tests_jobs.py:610-613`）。

跑法：`python -X utf8 manage.py test test.backend.test_job_cancel`
"""

import multiprocessing
import os
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import EXTRA_QUEUED_CALLS

from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.jobs import executor
from apps.jobs.models import Job
from apps.jobs.runner import write_progress
from test.backend.job_cancel_fixtures import (
    PASSWORD, PAYLOAD_FIELDS, ExecutorSeamMixin, FakePool, timeout_text)


class TimeoutClockOriginTests(ExecutorSeamMixin, TransactionTestCase):
    """判据 1：执行预算由「首次见到进度」钉下；绝对上限由 submit 那一刻钉下。"""

    def setUp(self):
        self.user = User.objects.create_user('c1_clock', 'cc@localhost', PASSWORD)
        self._tmp_source()
        self._patch_seams()

    def _export_job(self):
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='pending', params={})
        return job, self._export_task(job)

    def test_submit_defers_the_clock_for_jobs_with_a_sidecar(self):
        before = time.monotonic()
        job, task = self._export_job()
        executor.submit(job, task)
        after = time.monotonic()

        entry = executor._in_flight[job.id]
        budget = executor.EXPORT_TIMEOUT_SECONDS
        self.assertEqual(entry.progress_path, task['progress_path'])
        self.assertIsNone(
            entry.started, '有侧车的作业：submit 时不许起执行预算（排队时间不是执行预算）')
        # 但绝对上限必须在 submit 那一刻定死 = submit + timeout（不是 None、不是 infinity）
        self.assertLessEqual(before + budget, entry.deadline)
        self.assertGreaterEqual(after + budget, entry.deadline)
        self.assertEqual(Job.objects.get(pk=job.id).status, 'running')

    def test_submit_keeps_the_clock_for_jobs_without_a_sidecar(self):
        """thread lane 保持 submit 即起表 —— 它没有侧车可读，见 `_start_clock` 的注释。"""
        job, task = self._download_job()
        self.assertNotIn('progress_path', task)

        executor.submit(job, task)

        entry = executor._in_flight[job.id]
        self.assertEqual(entry.progress_path, '')
        self.assertAlmostEqual(entry.deadline - entry.started,
                               executor.SFTP_DOWNLOAD_TIMEOUT_SECONDS,
                               places=6, msg='没侧车 ⇒ 两条时钟同一原点，只差一个 timeout')

    def test_queued_job_inside_the_absolute_deadline_is_not_error(self):
        """C1 授权的那半：排队 29 分钟（30 分钟绝对上限之内）不许被判死。"""
        job, task = self._export_job()
        self._clear_sidecar(task)                   # 「还没开跑」= 侧车不存在
        executor.submit(job, task)
        budget = executor.EXPORT_TIMEOUT_SECONDS
        executor._monitor_pass(time.monotonic() + budget - 60)

        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'running',
                         f'上限内的排队作业被判死了：error={row.error!r}')
        self.assertEqual(row.error, '')
        self.assertIn(job.id, executor._in_flight, '不许被看门狗踢出在飞表')

    def test_a_job_that_never_shows_progress_is_killed_at_the_deadline(self):
        """主案（删掉绝对上限就是这条红）：进度一眼没见过 ⇒ 到 `submit + timeout` 判死。
        `assertNotIn` 那半同样承重：条目留在 `_in_flight` 里看门狗就收不了工
        （后果那一段只在 `executor._monitor_pass` 叙述）。
        """
        job, task = self._export_job()
        self._clear_sidecar(task)
        executor.submit(job, task)
        budget = executor.EXPORT_TIMEOUT_SECONDS

        executor._monitor_pass(time.monotonic() + budget - 60)
        self.assertEqual(Job.objects.get(pk=job.id).status, 'running')

        executor._monitor_pass(time.monotonic() + budget + 1)
        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'error',
                         f'绝对上限没兜住无进度作业：status={row.status} '
                         f'error={row.error!r}')
        self.assertEqual(row.error, timeout_text(budget))
        self.assertTrue(row.finished_at)
        self.assertNotIn(job.id, executor._in_flight)
        self.assertEqual(executor._in_flight, {}, '在飞表必须被清空，看门狗才收得了工')

    def test_the_absolute_deadline_is_a_separate_clock_from_the_execution_budget(self):
        """`_monitor_pass` 在 `started is None` 时读的是 `deadline`，不是 `timeout`。
        生产里 `deadline = submit + timeout`，两个窗口重合，所以「等过执行预算但仍在
        绝对上限内」这段只能注入一条把两者拉开的条目来钉（预算 60s、上限 1h）；它同时
        反证判死那句文案用的仍是作业自己的 `timeout`，没被上限值污染。
        """
        job, task = self._export_job()
        self._clear_sidecar(task)
        executor.submit(job, task)
        entry = executor._in_flight[job.id]
        self.assertIsNone(entry.started)
        pinned = time.monotonic()
        executor._in_flight[job.id] = entry._replace(timeout=60,
                                                     deadline=pinned + 3600)

        executor._monitor_pass(pinned + 1800)       # 过 60s 执行预算、仍在 1h 上限内
        self.assertEqual(Job.objects.get(pk=job.id).status, 'running',
                         '绝对上限内就被判死 ⇒ 看门狗把 timeout 当成从 submit 起算了')
        self.assertIn(job.id, executor._in_flight)

        executor._monitor_pass(pinned + 3601)       # 越上限 ⇒ 判死
        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'error')
        self.assertEqual(row.error, timeout_text(60), '文案要跟作业的 timeout 走')
        self.assertNotIn(job.id, executor._in_flight)

    def test_deadline_kill_of_a_still_pending_future_keeps_the_timeout_text(self):
        """判死那句人话不会被「取消内联触发的那次回填写入」顶掉。
        `capacity=0` 的假池造「父 future 仍 PENDING」那一档（真池里就是第 capacity+1
        条）—— 只有它 `cancel()` 会成功并**在本线程内联**跑 `_write_back`。
        这里钉的是回填那道 `future.cancelled()` 收手 + 带守卫的 UPDATE 这两件事叠出来的
        结果；`_timed_out` 里三句的**先后**不承重（2026-10-29 变异自证：调换写行与
        `cancel()`，本文件 + `test_job_terminal_ownership.py` 23 条全绿），别把这条
        当成次序的判据 —— 次序是取向，见 `_timed_out` 的说明。
        """
        self.pool = FakePool(capacity=0)
        job, task = self._export_job()
        self._clear_sidecar(task)
        executor.submit(job, task)
        budget = executor.EXPORT_TIMEOUT_SECONDS

        executor._monitor_pass(time.monotonic() + budget + 1)

        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'error')
        self.assertEqual(row.error, timeout_text(budget),
                         '取消回调抢写了终态，判死那句人话丢了')
        self.assertTrue(self.pool.futures[-1].cancelled())

    def test_first_progress_starts_the_clock_and_only_once(self):
        job, task = self._export_job()
        executor.submit(job, task)
        first_percent = self._seed_sidecar(task, 1, 4)   # worker 的第一步

        first = time.monotonic()
        executor._monitor_pass(first)

        self.assertEqual(executor._in_flight[job.id].started, first,
                         '首次读到进度 > 0 时必须把执行预算起点钉下来')
        self.assertEqual(Job.objects.get(pk=job.id).progress, first_percent)

        next_percent = self._seed_sidecar(task, 2, 4)
        self.assertGreater(next_percent, first_percent)
        executor._monitor_pass(first + 100)
        # 只钉一次：每见到新进度就重置起点，等于让长作业永远超不了时
        self.assertEqual(executor._in_flight[job.id].started, first)
        self.assertEqual(Job.objects.get(pk=job.id).progress, next_percent)

    def test_timeout_counts_from_the_first_progress_not_from_submit(self):
        """见过进度之后由**执行时钟**管：排队 20 分钟才开跑 ⇒ 能活到 submit+50 分钟。
        这段额度是 C1 给的（旧口径 submit+30 就判死），也是唯一一段「比绝对上限更晚」
        的合法存活时间 —— 前提是看门狗在越线前见过进度。
        """
        job, task = self._export_job()
        self._seed_sidecar(task, 1, 3)                  # worker 已经开跑
        executor.submit(job, task)
        budget = executor.EXPORT_TIMEOUT_SECONDS

        started = time.monotonic() + 20 * 60            # 20 分钟后才被看见（仍在上限内）
        executor._monitor_pass(started)
        self.assertEqual(executor._in_flight[job.id].started, started)
        self.assertEqual(Job.objects.get(pk=job.id).status, 'running',
                         '开跑那一刻就被判超时，说明起点没被重置')

        # 距 submit 已 49 分钟：旧口径（submit + 30）早判死了，这里仍不许动
        executor._monitor_pass(started + budget - 1)
        self.assertEqual(Job.objects.get(pk=job.id).status, 'running')

        executor._monitor_pass(started + budget + 1)
        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'error', f'到了预算却没超时：{row.error!r}')
        self.assertIn('超时 30 分钟', row.error)
        self.assertNotIn(job.id, executor._in_flight)

    def test_sidecar_less_lane_still_times_out_from_submit(self):
        """下载 lane 的绝对上限不许被这次改动削掉：它没侧车，就按 submit 起表。"""
        job, task = self._download_job()
        executor.submit(job, task)
        budget = executor.SFTP_DOWNLOAD_TIMEOUT_SECONDS

        executor._monitor_pass(time.monotonic() + budget - 60)
        self.assertEqual(Job.objects.get(pk=job.id).status, 'running')

        executor._monitor_pass(time.monotonic() + budget + 1)
        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'error')
        self.assertIn('超时 120 分钟', row.error)
        self.assertNotIn(job.id, executor._in_flight)


class CancelRunningJobTests(ExecutorSeamMixin, APITestCase):
    """判据 2：走**真实提交路径**（同一次请求里 pending→running）的取消，按真池窗口钉。
    旧用例 `apps/jobs/tests_jobs.py:251` 用 `Job.objects.create(status='pending')` 造行，
    绕过了 `submit()`，所以生产里「cancel 恒 409」从没被覆盖过。
    """

    def setUp(self):
        self.user = User.objects.create_user('c1_api', 'ca@localhost', PASSWORD)
        self._tmp_source()
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='tiny.csv', file_path=self.path,
            file_size=os.path.getsize(self.path), format_type='CTA8280F',
            status='ready', program_name='PROG')
        self.client.force_authenticate(user=self.user)
        self._patch_seams()

    def _submit_export(self):
        resp = self.client.post('/api/v1/jobs/export_excel/',
                                {'file_id': self.datafile.id}, format='json')
        self.assertEqual(resp.status_code, 202, resp.content)
        return resp.json()['job_id']

    def _assert_uncancellable(self, job_id):
        resp = self.client.post(f'/api/v1/jobs/{job_id}/cancel/')
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.json()['code'], 'not_cancellable')
        job = Job.objects.get(pk=job_id)
        self.assertEqual(job.status, 'running', '取消失败的作业不能被提前判死')
        self.assertEqual(job.error, '')
        self.assertIsNone(job.finished_at)
        self.assertIn(job_id, executor._in_flight,
                      '仍在飞的作业仍要被看门狗盯着，不许踢出在飞表')

    def test_cancel_a_queued_job_through_the_real_submit_path(self):
        """可取消那一档（父 future 仍 PENDING ⇒ 工作项从未进过 call queue）走满 200 形状。
        `capacity=0` 的假池 = 「队列一格都没挤进去」，对应真池第 capacity+1 条起；
        窗口边界不在这里断，由 `test_only_the_over_capacity_tail_...` 与真池用例断。
        """
        self.pool = FakePool(capacity=0)
        job_id = self._submit_export()
        # 生产形状：提交后行里是 running，而 future 还躺在池队列（call queue 之外）里
        self.assertEqual(Job.objects.get(pk=job_id).status, 'running')
        self.assertIn(job_id, executor._in_flight)
        # 取消前先把作业目录拍一张快照。不直接断「目录不存在」：这个目录名可能被
        # **别的用例的同 id 产物**占着（TransactionTestCase 不重置自增序列），
        # 而本片要钉的是「这次取消没往磁盘上新写任何东西」。
        _rel, abs_dir = executor.result_dirs(self.user.pk, job_id)
        before = sorted(os.listdir(abs_dir)) if os.path.isdir(abs_dir) else None

        # 取消的回调不该再打那段 `logger.exception('job %s failed')` 栈（那是把用户
        # 的取消当作业失败记账）—— 这里**断日志**而不是像旧版那样把 logger 整个 patch 掉：
        # 静音会把「回填又抢写了终态」这类真信号一起抹掉。
        with self.assertNoLogs('apps.jobs.executor', level='ERROR'):
            resp = self.client.post(f'/api/v1/jobs/{job_id}/cancel/')

        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(set(body), PAYLOAD_FIELDS, '取消的响应体必须是轮询契约的形状')
        self.assertEqual(body['status'], 'cancelled')

        job = Job.objects.get(pk=job_id)
        self.assertEqual(job.status, 'cancelled')
        self.assertEqual(job.error, '',
                         '不许把 CancelledError 的文本留在「已取消」的行上')
        self.assertEqual(job.progress, 0)
        self.assertTrue(job.finished_at)
        self.assertNotIn(job_id, executor._in_flight)
        self.assertEqual(job.result_path, '', '取消掉的作业不许挂上产物')
        # 没有孤儿产物：future 从未被 worker 领走 ⇒ 取消（连同它内联触发的回填）
        # 都不该在磁盘上留下新东西。
        after = sorted(os.listdir(abs_dir)) if os.path.isdir(abs_dir) else None
        self.assertEqual(after, before,
                         f'取消留下了孤儿产物：{abs_dir} {before} → {after}')

    def test_only_the_over_capacity_tail_is_cancellable_at_the_boundary(self):
        """真窗口的形状：前 `MAX_POOL_WORKERS + EXTRA_QUEUED_CALLS` 条全 409，第 6 条才 200。
        这条是本片最不好听的结论——**并发 ≤5 条时端点等于没改**；任何「排队中就能
        取消」的说法都比这宽，所以一切注释与文案以这条为准。
        """
        capacity = executor.MAX_POOL_WORKERS + EXTRA_QUEUED_CALLS
        ids = [self._submit_export() for _ in range(capacity + 1)]
        self.assertEqual(len(self.pool.futures), capacity + 1)
        # 假池照真池翻态：挤进 call queue 的（含正在执行的 + 缓冲的）都是 RUNNING
        self.assertTrue(all(f.running() for f in self.pool.futures[:capacity]))
        self.assertFalse(self.pool.futures[capacity].running())

        for job_id in ids[:capacity]:
            self._assert_uncancellable(job_id)

        with self.assertNoLogs('apps.jobs.executor', level='ERROR'):
            resp = self.client.post(f'/api/v1/jobs/{ids[capacity]}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Job.objects.get(pk=ids[capacity]).status, 'cancelled')
        # 只取消那一条：别把同批的其它作业一起带走
        for job_id in ids[:capacity]:
            self.assertEqual(Job.objects.get(pk=job_id).status, 'running')
            self.assertIn(job_id, executor._in_flight)

    def test_cancel_refuses_a_future_the_call_queue_already_made_running(self):
        """RUNNING 就 409 —— 而「在 worker 里跑」与「缓冲在 call queue」都是 RUNNING。
        主进程侧**分不出**这两态（`process.py:395` 在 push 时就翻了状态），所以这条
        钉的是「不许提前判死」，不是「这条真的开跑了」。
        """
        job_id = self._submit_export()               # 第 1 条 ⇒ 挤得进 call queue
        self.assertTrue(executor._in_flight[job_id].future.running())
        self._assert_uncancellable(job_id)

    def test_cancel_refuses_running_row_that_is_not_in_flight(self):
        """同步降级（`_sync_fallback`）跑的、或别的进程里的作业：`_in_flight` 里没有 ⇒ 409。"""
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='running', params={})
        self.assertNotIn(job.id, executor._in_flight)

        resp = self.client.post(f'/api/v1/jobs/{job.id}/cancel/')

        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(Job.objects.get(pk=job.id).status, 'running')

    def test_cancel_still_rejects_every_terminal_row(self):
        """放宽只放宽 `running`：终态行不许被「取消」改写。"""
        for terminal in ('done', 'error', 'cancelled'):
            job = Job.objects.create(owner=self.user, kind='export_excel',
                                     status=terminal, params={})
            resp = self.client.post(f'/api/v1/jobs/{job.id}/cancel/')
            self.assertEqual(resp.status_code, 409, f'{terminal} 不该可取消')
            self.assertEqual(Job.objects.get(pk=job.id).status, terminal)

    def test_cancel_still_accepts_a_pending_row(self):
        """没进过池的行（pending）保持既有语义：直接终态，不看 `_in_flight`。"""
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='pending', params={})

        resp = self.client.post(f'/api/v1/jobs/{job.id}/cancel/')

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['status'], 'cancelled')
        self.assertEqual(Job.objects.get(pk=job.id).status, 'cancelled')

    def test_cancel_queued_keeps_an_error_written_in_the_same_window(self):
        """`cancel_queued` 的 `status='running'` 守卫：别覆掉同一窗口里先看门狗写的那句。
        时序（无同步，真的走得到）：请求线程 `_in_flight.get()` + `cancel()` 成功 ⇒
        看门狗那一轮先落「超时 30 分钟」⇒ 请求线程那句 `cancelled` 的 UPDATE 命中 0 行。
        """
        self.pool = FakePool(capacity=0)             # 让这条落在可取消那一档
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='pending', params={})
        executor.submit(job, self._export_task(job))
        future = executor._in_flight[job.id].future
        text = timeout_text(executor.EXPORT_TIMEOUT_SECONDS)
        Job.objects.filter(pk=job.id).update(status='error', error=text,
                                             finished_at=timezone.now())

        self.assertTrue(executor.cancel_queued(job.id),
                        'future 确实被取消了，返回值不许虚报成「没取消」')
        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'error', '取消把看门狗的判死覆成了「已取消」')
        self.assertEqual(row.error, text)
        self.assertTrue(future.cancelled())
        self.assertNotIn(job.id, executor._in_flight)


class RealPoolQueueWindowTests(TransactionTestCase):
    """把 `FakePool` 那条边界对**真池**再核一遍 —— 假池可以骗人，std 库不能。
    形状照 `apps/jobs/tests_jobs.py:603` 的 `RealPoolEndToEndTests`：真 spawn 池 +
    TransactionTestCase。这条不碰 `executor`，钉的就是 `cancel_queued` 唯一的判据
    `future.cancel()` 在 stdlib 里的真实翻转点。
    """

    def test_cancellability_flips_at_workers_plus_extra_queued_calls(self):
        workers, hold = 2, 2.0
        capacity = workers + EXTRA_QUEUED_CALLS
        tmpdir = tempfile.mkdtemp(prefix='c1_realpool_')
        self.addCleanup(shutil.rmtree, tmpdir, True)
        pool = ProcessPoolExecutor(max_workers=workers,
                                   mp_context=multiprocessing.get_context('spawn'))
        # `cancel_futures` 是关键字限定参数（本机 3.13.12），addCleanup 传不了位置参 ⇒ 用闭包
        self.addCleanup(lambda: pool.shutdown(wait=False, cancel_futures=True))

        # 1) 把 worker 全占住（`time.sleep` 在子进程里跑，父 future 立刻 RUNNING）
        busy = [pool.submit(time.sleep, hold) for _ in range(workers)]
        # 2) 再提交超出 call queue 容量的两条：第一条挤进队列（RUNNING 但没 child 拿过），
        #    第二条排在队列外（PENDING ⇒ 可取消）。管理线程只在 submit/结果时醒，
        #     child 腾出的空格不会立刻被补 ⇒ 这个前沿是稳的。
        markers = [os.path.join(tmpdir, f'{i}.progress') for i in range(2)]
        queued = [pool.submit(write_progress, p, 1, 3) for p in markers]
        buffered, outside = queued[:EXTRA_QUEUED_CALLS], queued[EXTRA_QUEUED_CALLS:]

        # **这道轮询不是死代码**（评审建议按「`set_running_or_notify_cancel()` 在
        # `submit()` 里同步发生」去掉，本机源码 + 实测都否证了那句）：CPython 3.13.12
        # 的 `ProcessPoolExecutor.submit()`（`concurrent/futures/process.py:788-810`）
        # 只把工作项 id 放进 `_work_ids` 并唤醒管理线程，函数体里没有
        # `add_call_item_to_queue`；翻 RUNNING 发生在**管理线程**里的那次
        # `add_call_item_to_queue`（`:337` → `:395`）。实测：submit 返回后立刻读，队首
        # 那条仍是 PENDING，约 20ms 后才 RUNNING ⇒ 去掉轮询等于把判据交给线程调度。
        # 有界（2s）且以「前沿形状出现」为退出条件：等得到，等不到就当场红（不是空转）。
        stop = time.monotonic() + 2.0
        while time.monotonic() < stop:
            if all(f.running() for f in busy + buffered) and \
                    all(not f.running() for f in outside):
                break
            time.sleep(0.02)
        self.assertTrue(all(f.running() for f in busy), 'worker 里的那几条必须是 RUNNING')
        self.assertTrue(all(f.running() for f in buffered),
                        '缓冲在 call queue 里、没被任何 child 拿过的一条也已是 RUNNING')
        self.assertFalse(any(f.done() for f in outside), '队尾那几条不该已经收场')

        # 判据本身：前沿以内 cancel() 恒 False，队尾恒 True
        self.assertEqual([f.cancel() for f in busy + buffered], [False] * capacity,
                         f'前 {capacity} 条（=max_workers+EXTRA_QUEUED_CALLS）里冒出了可取消的')
        self.assertEqual([f.cancel() for f in outside], [True] * len(outside),
                         '排在队列容量之外的那几条本该可取消')
        self.assertTrue(all(f.cancelled() for f in outside))
        # 取消掉的作业从未进过 worker ⇒ 侧车（产物前身）不该出现。**等收工，不等常数**：
        # `shutdown(wait=True)` 之后管理线程与 child 都结束了，此刻的「不存在」才是
        # 「从来没跑过」的证据；旧写法 `time.sleep(0.5)` 在慢机器上只是碰巧没跑完（假绿）。
        # 队尾已被上面的 `cancel()` 翻成 CANCELLED，这里只会等真在跑的那几条收工。
        pool.shutdown(wait=True)
        self.assertEqual([os.path.exists(p) for p in markers[EXTRA_QUEUED_CALLS:]],
                         [False] * len(outside), '取消成功的作业写出了产物')


class WriteBackGuardTests(ExecutorSeamMixin, TransactionTestCase):
    """回填的终态归属是这套取消/判死语义的承重点，单独钉两条。"""

    def setUp(self):
        self.user = User.objects.create_user('c1_guard', 'cg@localhost', PASSWORD)
        self._tmp_source()
        self._patch_seams()

    def test_write_back_does_not_resurrect_a_terminal_cancelled_row(self):
        """取消成功后 future 以 CancelledError 收场，回填只认非终态行 ⇒ 「已取消」不会被翻盘。"""
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='pending', params={})
        task = self._export_task(job)
        executor.submit(job, task)
        future = self.pool.futures[-1]

        Job.objects.filter(pk=job.id).update(status='cancelled',
                                             finished_at=timezone.now())
        future.set_result({'out_path': task['out_path'], 'bytes_written': 2048})

        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'cancelled')
        self.assertEqual(row.progress, 0, '回填不许把取消行推到 100')
        self.assertEqual(row.result_path, '')
        self.assertEqual(row.result_name, '')
        self.assertNotIn(job.id, executor._in_flight)

    def test_write_back_leaves_a_cancelled_future_to_its_canceller(self):
        """取消的那一侧才是终态的主人：回填见 `future.cancelled()` 就收手。

        少了这道收手，`cancel_queued` 的 `status='running'` 守卫就命中 0 行（行已被
        回填写成 error），用户那句「已取消」就变成 `error='CancelledError: '`。
        """
        self.pool = FakePool(capacity=0)
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='pending', params={})
        executor.submit(job, self._export_task(job))
        future = self.pool.futures[-1]

        future.cancel()                       # 内联触发 done-callback `_write_back`

        row = Job.objects.get(pk=job.id)
        self.assertEqual(row.status, 'running',
                         f'取消的回调抢写了终态：error={row.error!r}')
        self.assertEqual(row.error, '')
        self.assertIsNone(row.finished_at)
        self.assertNotIn(job.id, executor._in_flight)
