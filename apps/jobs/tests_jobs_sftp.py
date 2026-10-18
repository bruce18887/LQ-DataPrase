"""S3：SFTP 批量下载作业化（D3 已拍板 = 作业化 + 轮询）。

设计稿 `docs/specs/2026-10-17-heavy-job-offload-design.md` §4.2 / §5，
上游 `docs/plans/2026-10-17-performance-remediation.md` §6 第 4 项。

为什么这块走**线程**而不是进程池：SFTP 传输是 IO-bound（不占 CPU），
而它要在主进程里注册 DataFile、写进度 —— 那些都要 Django。进程池那条 lane
只给 CPU-bound 的三个导出。

跑法：`.venv/Scripts/python.exe manage.py test apps.jobs`
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import UserSetting
from apps.datafiles.models import DataFile
from apps.jobs.models import Job
from apps.sftp.tests_download_dir import FakeSftp  # 复用同一个替身，别造第二个

PASSWORD = 'x-sftp-12345678'
User = get_user_model()


def _file_list(entries):
    """file_list 形态 = (remote_path, rel_path, size, mtime)，与 SSE 通路一致。"""
    return [(r, rel, size, 0) for r, rel, size in entries]


class JobFakeSftp(FakeSftp):
    """给复用的替身补上 `close()` 与 `listdir_attr()`。

    `tests_download_dir.FakeSftp` 只实现了 SSE 生成器用到的那两个方法，
    而作业这条链路还会 close()（真实 SFTPClient 一定有）与列目录。
    刻意在**本文件**里子类化补，不去改那个共享替身 —— 它服务的用例不该因为我扩面。
    """

    closed = 0

    def close(self):
        self.closed += 1

    def listdir_attr(self, path):
        return []


def advancing_clock(step=0.5):
    """每次调用递增 step 秒的假 monotonic 时钟（用来验进度限频）。"""
    state = {'t': 0.0}

    def tick():
        state['t'] += step
        return state['t']
    return tick


class SftpJobKindTests(unittest.TestCase):
    """lane 归属：sftp 下载必须走线程，不许被塞进进程池。"""

    def test_sftp_download_is_registered_on_the_thread_lane(self):
        from apps.jobs import executor
        spec = executor.KIND_RUNNERS['sftp_download']
        self.assertEqual(spec['lane'], 'thread')
        self.assertEqual(spec['timeout'], executor.SFTP_DOWNLOAD_TIMEOUT_SECONDS)

    def test_export_kinds_stay_on_the_process_lane(self):
        """对照组：三个导出仍然是进程 lane。只断 sftp 变线程，可能我把全池改成了线程。"""
        from apps.jobs import executor
        for kind in ('export_excel', 'export_batch_charts', 'export_html_report'):
            self.assertEqual(executor.KIND_RUNNERS[kind]['lane'], 'process', kind)

    def test_thread_pool_is_bounded_to_two(self):
        """spec §4.2：每作业一条临时 SSH 连接。20 人 × N 作业会撞 sshd MaxStartups，
        所以并发下载必须有硬上限 —— 这个数就是那条约束的落点。"""
        from apps.jobs import executor
        self.assertLessEqual(executor.MAX_DOWNLOAD_WORKERS, 2)


class SftpJobRunTests(TestCase):
    """作业本体：消费同一个事件生成器，结果与 SSE 通路一致。

    用 Django `TestCase` 而不是 `unittest.TestCase`：这些用例要建用户、写 Job 行，
    只有前者会准备测试库（后者直接 `no such table: accounts_user`，本文件第一版就栽在
    这里）。`run_sftp_download` 在这里是**直接调用**（不经池），与用例同线程同连接，
    所以事务包裹不影响可见性 —— 真正走池的那条链路仍由进程 lane 的端到端用例覆盖。
    """

    def setUp(self):
        self.user = User.objects.create_user('sftp_job', 'sj@localhost', PASSWORD)
        self.tmp = tempfile.mkdtemp(prefix='jobs_sftp_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._media = override_settings(MEDIA_ROOT=os.path.join(self.tmp, 'media'))
        self._media.enable()
        self.addCleanup(self._media.disable)

    def _make_job(self, dir_name='BAT01'):
        return Job.objects.create(
            owner=self.user, kind='sftp_download', status='pending',
            params={'path': f'/data/{dir_name}', 'dir_name': dir_name})

    def test_run_download_persists_progress_and_result(self):
        from apps.jobs.sftp_job import run_sftp_download

        sftp = JobFakeSftp({'/r/a.csv': b'0' * 10, '/r/b.csv': b'1' * 20,
                         '/r/c.csv': b'2' * 30})
        job = self._make_job()
        task = {'job_id': job.id, 'owner_id': self.user.pk,
                'file_list': _file_list([('/r/a.csv', 'a.csv', 10),
                                         ('/r/b.csv', 'b.csv', 20),
                                         ('/r/c.csv', 'c.csv', 30)]),
                'dir_name': 'BAT01', 'timeout_sec': 600}

        seen = []
        with mock.patch('apps.jobs.sftp_job._open_temp_sftp', return_value=sftp):
            result = run_sftp_download(task)
        job.refresh_from_db()
        seen.append(job.progress)

        self.assertEqual(job.status, 'done', job.error)
        self.assertEqual(job.progress, 100)
        # 结果不是「一个可下载文件」，而是落进用户库的一个批次目录
        self.assertTrue(job.result_path.endswith('BAT01'), job.result_path)
        self.assertEqual(job.result_name, 'BAT01')
        self.assertFalse(result['downloadable'])
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), 3,
                         '下载即注册 DataFile 是 SSE 通路既有语义，作业化不许丢')
        self.assertTrue(seen)

    def test_progress_write_gate(self):
        """进度写库的判据本身：限频 + 去重，两个条件都要满足。

        第一版这条是去 mock `Job.objects.filter` 数写入次数 —— 那个 spy 把 Manager
        当参数喂进了 Django 的 filter 解析，直接 `cannot unpack non-iterable Manager
        object`；而且就算它能跑，测的也是「我拦到调用没有」，不是「该不该写」。
        抽成纯函数后代边界值来验算。
        """
        from apps.jobs.sftp_job import progress_should_write

        # 到点且前进 → 写
        self.assertTrue(progress_should_write(2.0, 0.0, 40, 30))
        # 间隔未到 → 不写（限频本体，防 SQLite 写放大）
        self.assertFalse(progress_should_write(0.4, 0.0, 40, 30))
        # 到点但百分比没前进 → 不写（去重：同一秒内多个事件只留一个值）
        self.assertFalse(progress_should_write(9.0, 0.0, 30, 30))
        # 边界：正好等于间隔算到点（>=，别让差一微秒就永远写不出去）
        self.assertTrue(progress_should_write(1.0, 0.0, 50, 30))
        # 进度回退也不写
        self.assertFalse(progress_should_write(5.0, 0.0, 10, 30))

    def test_run_download_does_not_write_progress_without_intervals(self):
        """真下载一遍：三只在同一瞬间完成的文件不该刷出三次进度写库。

        上一条验算判据函数，这一条确认它在真实循环里被用上 ——
        只断最终 100（由 done 分支统一置），中间值是否被写由函数那条判据负责。
        """
        from apps.jobs import sftp_job
        from apps.jobs.sftp_job import run_sftp_download

        job = self._make_job('BATTH')
        task = {'job_id': job.id, 'owner_id': self.user.pk,
                'file_list': _file_list([('/r/a.csv', 'a.csv', 10),
                                         ('/r/b.csv', 'b.csv', 20),
                                         ('/r/c.csv', 'c.csv', 30)]),
                'dir_name': 'BATTH', 'timeout_sec': 600}
        sftp = JobFakeSftp({'/r/a.csv': b'0' * 10, '/r/b.csv': b'1' * 20,
                            '/r/c.csv': b'2' * 30})
        with mock.patch.object(sftp_job, '_open_temp_sftp', return_value=sftp):
            run_sftp_download(task)
        job.refresh_from_db()
        self.assertEqual(job.progress, 100)
        self.assertEqual(job.status, 'done', job.error)

    def test_partial_failure_ends_done_but_records_the_error_text(self):
        """一只文件传输炸掉：既有 SSE 语义是「清理半截 + error 事件 + 继续下一只」，
        作业化后必须仍是 done（其余只成功），并把失败信息留在 error 字段里给人看。"""
        from apps.jobs.sftp_job import run_sftp_download

        sftp = JobFakeSftp({'/r/a.csv': b'0' * 10, '/r/b.csv': b'1' * 20},
                        fail_after={'/r/b.csv': 1})
        job = self._make_job('BAT02')
        task = {'job_id': job.id, 'owner_id': self.user.pk,
                'file_list': _file_list([('/r/a.csv', 'a.csv', 10),
                                         ('/r/b.csv', 'b.csv', 20)]),
                'dir_name': 'BAT02', 'timeout_sec': 600}
        with mock.patch('apps.jobs.sftp_job._open_temp_sftp', return_value=sftp):
            run_sftp_download(task)
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        self.assertIn('b.csv', job.error)
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), 1)

    def test_all_failed_marks_job_error(self):
        from apps.jobs.sftp_job import run_sftp_download

        sftp = JobFakeSftp({'/r/a.csv': b'0' * 10},
                        broken={'/r/a.csv': OSError('connection reset by peer')})
        job = self._make_job('BAT03')
        task = {'job_id': job.id, 'owner_id': self.user.pk,
                'file_list': _file_list([('/r/a.csv', 'a.csv', 10)]),
                'dir_name': 'BAT03', 'timeout_sec': 600}
        with mock.patch('apps.jobs.sftp_job._open_temp_sftp', return_value=sftp):
            run_sftp_download(task)
        job.refresh_from_db()
        self.assertEqual(job.status, 'error')
        self.assertIn('全部失败', job.error)

    def test_temp_connection_is_used_and_closed_even_when_download_blows_up(self):
        """绝不碰 pool.py 的 per-user 常驻连接：paramiko 的 SFTPClient 不是线程安全的，
        作业与浏览共用一条会互踩。"""
        from apps.jobs import sftp_job, executor
        from apps.jobs.sftp_job import run_sftp_download

        opened = {'n': 0}
        sftp = JobFakeSftp({'/r/a.csv': b'0' * 10})

        class CountingSftp(JobFakeSftp):
            def open(self, *a, **kw):
                opened['n'] += 1
                return super().open(*a, **kw)

        job = self._make_job('BAT04')
        task = {'job_id': job.id, 'owner_id': self.user.pk,
                'file_list': _file_list([('/r/a.csv', 'a.csv', 10)]),
                'dir_name': 'BAT04', 'timeout_sec': 600}

        close_calls = []
        conn = CountingSftp({'/r/a.csv': b'0' * 10})
        conn.close = lambda: close_calls.append(True)

        with mock.patch.object(sftp_job, '_open_temp_sftp', return_value=conn), \
                mock.patch.object(executor.pool_module, 'get_connection',
                                  side_effect=AssertionError('不该用常驻连接')):
            run_sftp_download(task)
        self.assertEqual(close_calls, [True], '临时连接必须在 finally 里关掉')
        self.assertGreater(opened['n'], 0)

    def test_missing_cached_session_raises_not_connected_before_any_io(self):
        from apps.jobs.sftp_job import SftpJobError, _open_temp_sftp

        with mock.patch('apps.sftp.cache.get_session', return_value=None):
            with self.assertRaises(SftpJobError) as ctx:
                _open_temp_sftp(self.user.pk)
        self.assertIn('not_connected', str(ctx.exception))


class SftpSubmitApiTests(TestCase):
    """端点契约：提交时先验凭据，验不过就不该留一行 pending。"""

    def setUp(self):
        self.user = User.objects.create_user('sftp_api', 'sa@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _post(self, payload):
        return self.client.post('/api/v1/jobs/sftp_download/', payload, format='json')

    def test_missing_path_is_400_and_persists_nothing(self):
        resp = self._post({})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'param_required')
        self.assertEqual(Job.objects.filter(kind='sftp_download').count(), 0)

    def test_not_connected_is_answered_at_submit(self):
        """未连接要在提交那一刻就答，而不是建一行 pending 再让它慢慢 error。"""
        with mock.patch('apps.sftp.cache.get_session', return_value=None):
            resp = self._post({'path': '/data/BAT01'})
        self.assertIn(resp.status_code, (400, 412))
        self.assertEqual(resp.json()['code'], 'not_connected')
        self.assertEqual(Job.objects.filter(kind='sftp_download').count(), 0)

    def test_empty_directory_is_answered_at_submit(self):
        """远端目录里没有 CSV 也是「现在就能知道」的事：collect 完就要答复，
        否则用户拿到一个 job_id，轮询到超时才发现目录是空的。"""
        from apps.jobs import executor

        class EmptySftp(JobFakeSftp):
            def listdir_attr(self, path):
                return []

        with mock.patch('apps.jobs.sftp_job._open_temp_sftp', return_value=EmptySftp({})), \
                mock.patch.object(executor, 'executor_available', lambda: True), \
                mock.patch.object(executor, 'submit', lambda job, task: None):
            resp = self._post({'path': '/data/BAT01'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['code'], 'no_data')

    def test_download_on_a_directory_result_is_409(self):
        """批量下载的产物已经注册进用户库，不是一个可再下载的单文件。
        给 409 + 明确 code，比伪造一个 zip 诚实。"""
        job = Job.objects.create(owner=self.user, kind='sftp_download', status='done',
                                 result_path=os.path.join('data', 'sftp_api', 'batch', 'B1'),
                                 result_name='B1', params={})
        resp = self.client.get(f'/api/v1/jobs/{job.id}/download/')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['code'], 'not_a_file_result')
