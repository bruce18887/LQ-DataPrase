"""测试项归类接进作业提交链路的 T1 判据（BatchGroups Task 5）。

钉两件事：

1. `build_batch_charts_task` 的可选键 —— **有分组才出现** `groups` /
   `max_items_per_sheet`，缺省时 task 保持旧 payload 形状（多出来的键会让
   「没有分组」这条路径也走新装配，属于无声的行为切换）；
2. 视图守卫生效在**建作业之前** —— 非法分组返回 400 + 机器码 + `field`，
   不留下一条永远跑不出产物的 pending 行。

分层：纯 task dict 与响应体就够表达，归 T1；不渲染图表、不开浏览器
（`docs/reference/testing-gates.md` §2 的冲突裁决）。
"""

import os
import tempfile

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.jobs.executor import build_batch_charts_task
from apps.jobs.models import Job

PASSWORD = 'x-batch-groups-12345678'
TINY_CSV = 'Param,Data\nA,1\n'


class BatchChartsTaskGroupingTests(SimpleTestCase):
    """task dict 的可选键（worker 只收纯数据，键的有无就是版本开关）。"""

    def _task(self, params):
        return build_batch_charts_task(
            params=params, abs_path='C:/none/x.csv', fmt='CTA8290D',
            job_id=1, owner_id=1, dpi=100, cpk_thresholds=(1.67, 1.33, 1.0),
            groups=params.get('groups'),
            max_items_per_sheet=params.get('max_items_per_sheet'))

    def test_task_carries_groups_and_cap(self):
        groups = [{'name': 'A', 'params': ['P1']}]
        task = self._task({'params': ['P1'], 'groups': groups, 'max_items_per_sheet': 50})
        self.assertEqual(task['groups'], groups)
        self.assertEqual(task['max_items_per_sheet'], 50)

    def test_task_omits_grouping_keys_when_absent(self):
        task = self._task({'params': ['P1']})
        self.assertNotIn('groups', task)
        self.assertNotIn('max_items_per_sheet', task)

    def test_task_defaults_cap_when_groups_given_without_cap(self):
        """视图总会带 cap；直调 builder 时缺省值必须与分组契约同一个常量。"""
        groups = [{'name': 'A', 'params': ['P1']}]
        task = self._task({'params': ['P1'], 'groups': groups})
        self.assertEqual(task['max_items_per_sheet'], 50)


class BatchGroupsSubmitTests(APITestCase):
    """视图层：非法请求 400（机器码 + 字段名），合法请求进 task 与参数快照。"""

    def setUp(self):
        import apps.jobs.executor as executor_module

        self.user = User.objects.create_user(
            'groups_owner', 'groups_owner@localhost', PASSWORD)
        self.tmpdir = tempfile.mkdtemp(prefix='jobs_groups_')
        self.path = os.path.join(self.tmpdir, 'tiny.csv')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(TINY_CSV)
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='tiny.csv', file_path=self.path,
            file_size=os.path.getsize(self.path), format_type='CTA8280F',
            status='ready', program_name='PROG')
        self.client.force_authenticate(user=self.user)

        self.submitted = []

        def fake_submit(job, task):
            self.submitted.append((job.id, task))
            Job.objects.filter(pk=job.id).update(status='running', progress=0)

        # 视图在 `_dispatch` 里先问池、再 submit：两条都替换掉，
        # 本文件判的是校验与 task 形状，不是进程池（那份归 tests_jobs.py）。
        orig_submit = executor_module.submit
        orig_available = executor_module.executor_available
        executor_module.submit = fake_submit
        executor_module.executor_available = lambda: True
        self.addCleanup(setattr, executor_module, 'submit', orig_submit)
        self.addCleanup(setattr, executor_module, 'executor_available', orig_available)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _post(self, **params):
        return self.client.post('/api/v1/jobs/export_batch_charts/',
                                {'file_id': self.datafile.id, **params},
                                format='json')

    def test_legacy_payload_keeps_no_grouping_keys(self):
        resp = self._post(params=['A'])
        self.assertEqual(resp.status_code, 202, resp.content)
        _job_id, task = self.submitted[-1]
        self.assertNotIn('groups', task)
        self.assertNotIn('max_items_per_sheet', task)
        job = Job.objects.get(pk=resp.json()['job_id'])
        self.assertNotIn('groups', job.params)
        self.assertNotIn('max_items_per_sheet', job.params)

    def test_valid_groups_reach_task_normalized(self):
        resp = self._post(params=['A'], max_items_per_sheet=50,
                          groups=[{'name': ' LKG ', 'params': ['A']}])
        self.assertEqual(resp.status_code, 202, resp.content)
        _job_id, task = self.submitted[-1]
        self.assertEqual(task['groups'], [{'name': 'LKG', 'params': ['A']}])
        self.assertEqual(task['max_items_per_sheet'], 50)

    def test_invalid_groups_is_400_and_leaves_no_job(self):
        resp = self._post(params=['A'], groups=[{'name': 'A', 'params': ['A', 'B']}])
        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.json()
        self.assertEqual(body['code'], 'invalid_groups')
        self.assertEqual(body['field'], 'groups')
        self.assertFalse(Job.objects.exists(), '校验失败不许留下 pending 作业行')

    def test_bad_page_size_is_400_and_names_the_field(self):
        resp = self._post(params=['A'], max_items_per_sheet=20,
                          groups=[{'name': 'A', 'params': ['A']}])
        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.json()
        self.assertEqual(body['code'], 'invalid_page_size')
        self.assertEqual(body['field'], 'max_items_per_sheet')
        self.assertFalse(Job.objects.exists())

    def test_pptx_rejects_groups(self):
        resp = self._post(params=['A'], format='pptx',
                          groups=[{'name': 'A', 'params': ['A']}])
        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.json()
        self.assertEqual(body['code'], 'groups_not_supported')
        self.assertEqual(body['field'], 'groups')
        self.assertFalse(Job.objects.exists())
