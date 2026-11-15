"""测试项归类接进作业提交链路的 T1 判据（BatchGroups Task 5）。

钉三件事：

1. `build_batch_charts_task` 的可选键 —— **有分组才出现** `groups` /
   `max_items_per_sheet`，缺省时 task 保持旧 payload 形状（多出来的键会让
   「没有分组」这条路径也走新装配，属于无声的行为切换）；
2. 视图守卫生效在**建作业之前** —— 非法分组返回 400 + 机器码 + `field`，
   不留下一条永远跑不出产物的 pending 行；
3. worker 把 task 里那两个键**真的递给了 builder** —— task 形状对、视图对，
   唯独 runner 接线漏掉时特性会静默退回旧版式，所以这条判据盯的是
   `run_export_batch_charts` 的调用参数，而不是 task dict 里有没有键。

分层：纯 task dict、调用参数与响应体就够表达，归 T1；不渲染图表、不开浏览器
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

# runner 那条用例必须让 `_parse_and_filter` 真的解析成功（它才走得到 builder），
# 所以这里要一份 CTA8280F 能认的极小船形，形状抄 tests_jobs.TINY_CSV，
# 只留一个可作图的数值列 VOLT。
RUNNER_TINY_CSV = (
    'CTA8280F\n'
    'Device Name,TINY_DEVICE\n'
    'TestFileName,C:\\x\\prog.dll\n'
    '[Data]\n'
    'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,'
    'Test_Time,Data_Num,VOLT,\n'
    'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,V,\n'
    'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,1.0,\n'
    'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2.0,\n'
    + ''.join(
        f'{i},{i},{i},{(i % 2) + 1},TRUE,{5 if i == 3 else 1},0,0,None,4.1,10,'
        f'{1.5 if i != 3 else 9.9},\n'
        for i in range(1, 11))
)


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


class BatchChartsRunnerGroupingTests(SimpleTestCase):
    """worker 接线：`run_export_batch_charts` 把两个分组键递给 builder。

    为什么要 spy 而不是跑真渲染：本判据要证明的是**调用参数**，真渲染一次
    只证明「产物不炸」，把 `groups=` 整行删掉照样绿 —— 特性会静默退回旧版式。
    所以把 builder 换成固定 bytes 的接缝，断关键字参数与落盘内容。
    """

    def setUp(self):
        import apps.jobs.runner as runner_module

        self.tmpdir = tempfile.mkdtemp(prefix='jobs_runner_groups_')
        self.path = os.path.join(self.tmpdir, 'tiny.csv')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(RUNNER_TINY_CSV)

        self.payload = b'fake-xlsx-from-spy'
        self.calls = []

        def spy_builder(*args, **kwargs):
            self.calls.append({'args': args, 'kwargs': kwargs})
            return self.payload

        self.runner = runner_module
        self.addCleanup(setattr, runner_module,
                        'build_batch_charts_xlsx_with_charts',
                        runner_module.build_batch_charts_xlsx_with_charts)
        runner_module.build_batch_charts_xlsx_with_charts = spy_builder

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _task(self, out_name):
        return {
            'abs_path': self.path, 'fmt': 'CTA8280F',
            'out_path': os.path.join(self.tmpdir, out_name),
            'progress_path': os.path.join(self.tmpdir, '.progress'),
            'params': ['VOLT'], 'data_only_bin1': False,
            'show_limit': True, 'show_3sigma': False, 'show_4sigma': False,
            'show_6sigma': True, 'show_normal': False, 'show_kde': False,
            'dpi': 100, 'cpk_thresholds': (1.67, 1.33, 1.0),
        }

    def test_runner_forwards_groups_and_cap_to_builder(self):
        groups = [{'name': 'LKG', 'params': ['VOLT']}]
        task = self._task('grouped.xlsx')
        task['groups'] = groups
        # 用 30 而不是 50：50 恰好等于契约缺省，runner 若把 `task.get(key, 50)` 写成
        # 字面量回退，这里照样绿 —— 换一个非缺省值才能区分「原样透传」与「回退到 50」。
        task['max_items_per_sheet'] = 30

        result = self.runner.run_export_batch_charts(task)

        self.assertEqual(len(self.calls), 1, 'xlsx 分支必须调用一次 builder')
        kwargs = self.calls[0]['kwargs']
        self.assertEqual(kwargs.get('groups'), groups,
                         'task 里的 groups 必须原样递到 builder，否则退回旧版式')
        self.assertEqual(kwargs.get('max_items_per_sheet'), 30,
                         'task 里的页上限必须原样递到 builder')
        self.assertEqual(result['bytes_written'], len(self.payload))
        with open(task['out_path'], 'rb') as fh:
            self.assertEqual(fh.read(), self.payload, 'builder 的 bytes 要落盘')

    def test_runner_defaults_cap_when_task_has_no_page_size(self):
        """旧任务/直调 worker 没有 cap 时，递给 builder 的必须是契约缺省 50。"""
        task = self._task('legacy.xlsx')
        task['groups'] = [{'name': 'LKG', 'params': ['VOLT']}]

        self.runner.run_export_batch_charts(task)

        kwargs = self.calls[0]['kwargs']
        self.assertEqual(kwargs.get('groups'), task['groups'])
        self.assertEqual(kwargs.get('max_items_per_sheet'), 50)


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
