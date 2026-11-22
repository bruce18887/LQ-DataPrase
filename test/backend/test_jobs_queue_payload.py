"""Task 10：作业 payload 下发 `queue_position` 与 `timeout_seconds`。

三条口径（归属点在 `apps/jobs/views.py::_job_payload` 的 docstring，这里只钉判据）：

1. **排队数**：同 owner、`status in ('pending', 'running')`、比我更早
   （`created_at` 更早；同刻按 `id` 更小）的条数。terminal 行恒 0 —— 跑完的作业没有队列。
2. **超时**：四类 kind 取 `executor.KIND_RUNNERS[kind]['timeout']`；遗留的未知 kind
   返回 None 而不是 500（轮询页不该因为一条考古行崩掉）。
3. **下发面**：提交 202 与详情带 `queue_position`；列表**不带**（每条一次 count() 就是 N+1）。

期望的超时秒数在本文件里写死（1800/3600/1800/7200）：从 `executor` 常量抄一遍
等于让判据跟着实现一起漂。

跑法：`python -X utf8 manage.py test test.backend.test_jobs_queue_payload`
"""

import os
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.jobs import executor
from apps.jobs.models import Job

PASSWORD = 'x-jobspayload-12345678'

# kind → executor 里登记的超时（秒）。写死是**刻意**的：判据独立于实现常量。
KIND_TIMEOUT_SECONDS = {
    'export_excel': 1800,
    'export_batch_charts': 3600,
    'export_html_report': 1800,
    'sftp_download': 7200,
}


class JobPayloadCase(APITestCase):
    """共享底座：两个 owner、可钉 `created_at` 的建行器、按身份取详情。"""

    def setUp(self):
        self.user = User.objects.create_user('payload_owner', 'po@localhost', PASSWORD)
        self.other = User.objects.create_user('payload_other', 'pt@localhost', PASSWORD)
        self.client.force_authenticate(user=self.user)
        # 钉在「过去」：走真实提交路径造出来的新行（auto_now_add）一定排在它们后面
        self.base = timezone.now() - timedelta(minutes=30)

    def _job(self, *, owner=None, status='pending', kind='export_excel',
             created_at=None):
        job = Job.objects.create(owner=owner or self.user, kind=kind,
                                 status=status, params={})
        if created_at is not None:
            # `created_at` 是 auto_now_add：先后与同刻都只能靠 update 造
            Job.objects.filter(pk=job.id).update(created_at=created_at)
            job.refresh_from_db()
        return job

    def _detail(self, job, *, as_user=None):
        self.client.force_authenticate(user=as_user or self.user)
        return self.client.get(f'/api/v1/jobs/{job.id}/')

    def _queue_position(self, job, *, as_user=None):
        resp = self._detail(job, as_user=as_user)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('queue_position', resp.json(),
                      '详情响应必须带 queue_position')
        return resp.json()['queue_position']


class QueuePositionTests(JobPayloadCase):
    """判据 1：队前条数的边界（同 owner / 非终态 / 更早 / 同刻按 id）。"""

    def test_counts_only_earlier_same_owner_non_terminal_rows(self):
        self._job(status='running', created_at=self.base)
        self._job(status='running', created_at=self.base + timedelta(seconds=1))
        self._job(status='pending', created_at=self.base + timedelta(seconds=2))
        # 不计：别的 owner、三种终态、以及排在后面的
        self._job(owner=self.other, status='running', created_at=self.base)
        self._job(status='done', created_at=self.base + timedelta(seconds=3))
        self._job(status='error', created_at=self.base + timedelta(seconds=3))
        self._job(status='cancelled', created_at=self.base + timedelta(seconds=3))
        target = self._job(status='pending',
                           created_at=self.base + timedelta(seconds=4))
        self._job(status='pending', created_at=self.base + timedelta(seconds=5))

        self.assertEqual(self._queue_position(target), 3)

    def test_same_created_at_is_ordered_by_id(self):
        """同刻是常态（auto_now_add 只到微秒）：那一刻按 id 先后定队。"""
        stamp = self.base
        first = self._job(created_at=stamp)
        second = self._job(created_at=stamp)
        target = self._job(created_at=stamp)
        later = self._job(created_at=stamp)
        self.assertLess(first.id, second.id)
        self.assertLess(second.id, target.id)
        self.assertLess(target.id, later.id, '同刻 id 更大的那条不许算在队前')

        self.assertEqual(self._queue_position(target), 2)

    def test_terminal_rows_report_zero(self):
        self._job(status='running', created_at=self.base)
        self._job(status='pending', created_at=self.base + timedelta(seconds=1))
        for status in ('done', 'error', 'cancelled'):
            with self.subTest(status=status):
                target = self._job(status=status,
                                   created_at=self.base + timedelta(seconds=2))
                self.assertEqual(self._queue_position(target), 0,
                                 f'{status} 行不该有排队数')


class TimeoutSecondsTests(JobPayloadCase):
    """判据 2：超时取自执行器那张表；未知 kind 不下发数字也不 500。"""

    def test_every_known_kind_publishes_its_executor_timeout(self):
        for kind, seconds in KIND_TIMEOUT_SECONDS.items():
            with self.subTest(kind=kind):
                job = self._job(kind=kind)
                body = self._detail(job).json()
                self.assertEqual(body['timeout_seconds'], seconds)

    def test_unknown_legacy_kind_is_none_and_does_not_500(self):
        job = self._job(kind='legacy_export_v0')     # 早已下线的 kind（遗留行）
        resp = self._detail(job)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.json()['timeout_seconds'])


class PayloadSurfaceTests(JobPayloadCase):
    """判据 3：202 / 详情 / 列表三个面的键集合。"""

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp(prefix='jobs_payload_')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.path = os.path.join(self.tmpdir, 'tiny.csv')
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write('Index_No,VOLT\n1,1.5\n')
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='tiny.csv', file_path=self.path,
            file_size=os.path.getsize(self.path), format_type='CTA8280F',
            status='ready', program_name='PROG')
        # 执行不是本片的被测对象：提交只走「拿号」那条路（接缝同 apps/jobs/tests_jobs.py）
        def fake_submit(job, task):
            Job.objects.filter(pk=job.id).update(status='running')

        for target, value in (('executor_available', lambda: True),
                              ('submit', fake_submit)):
            patcher = mock.patch.object(executor, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _submit(self):
        return self.client.post('/api/v1/jobs/export_excel/',
                                {'file_id': self.datafile.id}, format='json')

    def test_submit_202_carries_queue_position(self):
        self._job(status='running', created_at=self.base)
        self._job(status='running', created_at=self.base + timedelta(seconds=1))
        self._job(status='pending', created_at=self.base + timedelta(seconds=2))

        resp = self._submit()

        self.assertEqual(resp.status_code, 202, resp.content)
        body = resp.json()
        self.assertEqual(body['queue_position'], 3)
        self.assertEqual(Job.objects.get(pk=body['job_id']).status, 'running')

    def test_detail_carries_queue_position_and_timeout(self):
        job = self._job(created_at=self.base)
        body = self._detail(job).json()
        self.assertEqual(body['queue_position'], 0)
        self.assertEqual(body['timeout_seconds'], 1800)

    def test_list_omits_queue_position_but_keeps_timeout(self):
        self._job(created_at=self.base)
        self._job(created_at=self.base + timedelta(seconds=1))

        resp = self.client.get('/api/v1/jobs/')

        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()['results']
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertNotIn('queue_position', row,
                             '列表不许逐条 count()（N+1）')
            self.assertEqual(row['timeout_seconds'], 1800)

    def test_other_users_detail_is_still_404(self):
        job = self._job()
        resp = self._detail(job, as_user=self.other)
        self.assertEqual(resp.status_code, 404,
                         '越权仍是 404，不是 403（作业 id 自增，403 等于确认它存在）')
