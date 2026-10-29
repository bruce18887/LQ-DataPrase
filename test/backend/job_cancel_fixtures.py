"""C1 判据的**共享道具**：假池、执行器接缝、两句口径。

消费者有两个文件，拆开的唯一原因是 600 行绊线（`scripts/line-limit.mjs:185`：
被跟踪的 `*.py` 到 601 行即红）：

* `test/backend/test_job_cancel.py` —— 两套时钟（排队不烧执行预算、绝对上限仍在）
  与取消窗口的真实形状；
* `test/backend/test_job_terminal_ownership.py` —— 终态归属：谁给一条作业落终态
  （`cancel_queued` / 看门狗 `_timed_out` / 崩池丢弃 `_reap_discarded`）。

夹具只有这一份：**不许**复制假池。理由不挂任何教训条目，就是它自己 —— 两份会各自漂，
而漂出来的那份会替 `cancel_queued` 的可取消性撒谎，那正是本批判据的判据本身。
真池那一侧由上面两个文件各自的 `RealPool*` 用例用 spawn 池核。
"""

import os
import shutil
import tempfile
from concurrent.futures import Future
from concurrent.futures.process import EXTRA_QUEUED_CALLS
from unittest import mock

from django.conf import settings
from django.utils import timezone

from apps.jobs import executor
from apps.jobs import sftp_job
from apps.jobs.models import Job
from apps.jobs.runner import read_progress, write_progress

PASSWORD = 'x-c1-jobs-12345678'
# 内容不重要：假池从不执行 worker，视图侧只 `os.path.exists(abs_path)`
# （`apps/jobs/views.py::_submit_export`）。
DUMMY_CSV = 'Index_No,Dut_No,VOLT\n1,1,1.5\n'
# 轮询契约（`_job_payload` 的键集合），取消的响应体必须是同一个形状。
PAYLOAD_FIELDS = {'id', 'kind', 'status', 'progress', 'error',
                  'result_name', 'created_at'}


def timeout_text(seconds):
    """看门狗判死那句人话的口径（与 `_timed_out`/旧实现同形状，别在这里改写它）。"""
    return f'超时 {seconds // 60} 分钟，已中止'


def dropped_text():
    """崩池丢弃那句人话的口径（与 `executor._reap_discarded` 同形状）。"""
    return '进程池已重建，作业被丢弃，请重试'


class FakePool:
    """照 **父 future 的状态机**模仿 `ProcessPoolExecutor`，而不是发裸 PENDING Future。

    真池的翻转点（本机 CPython 3.13.12 `concurrent/futures/process.py:395`）：
    `add_call_item_to_queue` 把工作项推进 bounded call queue 的**同一刻**调
    `set_running_or_notify_cancel()` —— 于是「缓冲在队列里、还没被任何 child 拿过」
    和「正在 worker 里跑」这两态在父 future 上都是 RUNNING，`cancel()` 一样 False；
    主进程侧**分不出**这两态。队列灌满（`max_workers + EXTRA_QUEUED_CALLS` 格）之后
    提交的工作项才留在 PENDING ⇒ 可取消。

    两处**刻意**与真池不同，都用得着就说清：
    * 翻转的**线程**：真池的 `submit()` 只把工作项 id 塞进 `_work_ids` 并唤醒管理线程
      （`process.py:788-810` 里没有 `add_call_item_to_queue`），翻 RUNNING 发生在
      **管理线程**里 —— 本机实测：刚 submit 完立刻读，队首那条还是 PENDING，20ms 后
      才变 RUNNING。假池在 `submit()` 里同步翻，为的是判据能确定性地摆出前沿；
      真池那侧的节奏由 `test_job_cancel.py::RealPoolQueueWindowTests` 的有界轮询钉。
    * `capacity=0` 是**故意**留的旋钮：它模拟「排在 call queue 之外」那一档（真池里
      就是第 capacity+1 条），不是伪造可取消性。旧版本每个 `submit()` 返回 PENDING
      Future，于是「第 1 条就可取消」这种生产里不存在的 200 窗口被断成了绿。
    """

    def __init__(self, capacity=None):
        self.futures = []
        self._capacity = capacity
        self.shut_down = None

    @property
    def capacity(self):
        return (executor.MAX_POOL_WORKERS + EXTRA_QUEUED_CALLS
                if self._capacity is None else self._capacity)

    def submit(self, entry, task):        # executor.submit 按位置传 (entry, task)
        future = Future()
        if len(self.futures) + 1 <= self.capacity:
            future.set_running_or_notify_cancel()   # 真池：进 call queue 即 RUNNING
        self.futures.append(future)
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        """照真池 `shutdown` 的形状：`cancel_futures=True` ⇒ 还 PENDING 的全被取消，
        且**照常触发它们的 done-callback**（真池由管理线程做，见 `_reap_discarded`
        的 provenance；RUNNING 的 `cancel()` False ⇒ 留着不管，与本实现同一结果）。
        """
        self.shut_down = (wait, cancel_futures)
        if cancel_futures:
            for future in self.futures:
                future.cancel()


class ExecutorSeamMixin:
    """把两条池与看门狗线程换成可控道具，其余全是生产代码路径。"""

    def _patch_seams(self, capacity=None):
        self.pool = FakePool(capacity)

        def get_pool():
            # `submit()` 登记后要拿 `_pool` 比身份（漏认领那条交错，见 `executor.submit`）：
            # 接缝换掉的只是**建池**，「当下活着的池就是这条」这个前提得跟着换，
            # 否则每条假池作业都会被复核判成池坏。每次调用都同步一次，是因为
            # 用例常在本方法之后换 `self.pool`（`capacity=0` 那一档），换完仍要对得上。
            executor._pool = self.pool
            return self.pool

        for target, value in (('_get_pool', get_pool),
                              ('_get_download_pool', lambda: self.pool),
                              # 看门狗线程会和手动的 `_monitor_pass` 抢跑同一条作业，
                              # 判据要的是「我推进了一次」的确定性，不是线程竞态。
                              ('_ensure_monitor', lambda: None)):
            patcher = mock.patch.object(executor, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(executor.reset_for_tests)

    def _tmp_source(self):
        self.tmpdir = tempfile.mkdtemp(prefix='c1_jobs_')
        self.path = os.path.join(self.tmpdir, 'tiny.csv')
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write(DUMMY_CSV)
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        # 作业产物只落在 MEDIA_ROOT/jobs/<owner>/<id>/ 下（executor.result_dirs）
        self.addCleanup(shutil.rmtree, os.path.join(str(settings.MEDIA_ROOT), 'jobs',
                                                    str(self.user.pk)), True)

    def _export_task(self, job):
        return executor.build_export_excel_task(
            params={'result_name': 'r.xlsx'}, abs_path=self.path,
            fmt='CTA8280F', hidden_columns=[], job_id=job.id,
            owner_id=self.user.pk)

    def _download_job(self):
        """thread lane 的真实形状：`build_sftp_task()` 里**没有** progress_path。"""
        job = Job.objects.create(owner=self.user, kind='sftp_download',
                                 status='pending', params={'path': '/r'})
        task = sftp_job.build_sftp_task(
            job_id=job.id, owner_id=self.user.pk, remote_path='/r',
            dir_name='BATC1', file_list=[('/r/a.csv', 'a.csv', 10)],
            timeout_sec=600)
        return job, task

    def _make_running_export(self, status='pending'):
        """造一行并走**真实提交路径**（同一次调用里 pending→running + 登记 `_in_flight`）。"""
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status=status, params={})
        executor.submit(job, self._export_task(job))
        return job

    def _clear_sidecar(self, task):
        """造出「侧车还不存在 = 还没开跑」。作业目录可能被**别的用例的同 id 产物**占着
        （TransactionTestCase 不重置自增序列 ⇒ 同 (owner_id, job_id) 撞同一个目录名）。
        """
        if os.path.exists(task['progress_path']):
            os.remove(task['progress_path'])
        self.assertEqual(read_progress(task['progress_path']), 0)

    def _seed_sidecar(self, task, done, total):
        """用 worker 那份真写手（`runner.write_progress`）落侧车，别手搓格式；
        返回它算出的百分比当「DB 里该出现的进度」—— 口径只有一份。
        """
        self._clear_sidecar(task)
        percent = write_progress(task['progress_path'], done, total)
        self.assertEqual(read_progress(task['progress_path']), percent)
        return percent

    def mark_cancelled(self, job):
        """别处已抢先落终态的形状（`cancel_queued` 赢了同一窗口的竞态）。"""
        Job.objects.filter(pk=job.id).update(status='cancelled', error='',
                                             finished_at=timezone.now())
