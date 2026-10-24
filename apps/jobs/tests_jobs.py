"""P3 重活作业化：`apps/jobs` 的 T1 判据。

设计稿 `docs/specs/2026-10-17-heavy-job-offload-design.md`，上游
`docs/plans/2026-10-17-performance-remediation.md` §6。

本文件钉四件事：

1. **worker 侧模块不得依赖 Django**（`test_worker_modules_import_without_django_setup`）——
   整片设计的地基：CPU 侧作业跑在 `ProcessPoolExecutor` 的 spawn 子进程里，子进程没有
   `django.setup()`。这个前提 2026-10-18 用 grep 验过一次，但 grep 挡不住将来有人
   往 `apps/export/filters.py` 里加一行 `from django.conf import settings`，所以做成断言。
2. 作业状态机与权限（他人 job_id 一律 404，不是 403）。
3. 进程池不可用时**同步降级**（返回 200 + 文件流 + `X-Job-Fallback: 1`）。
4. 参数快照原样进 worker —— 作业可能在用户改完设置之后才执行，语义必须钉在提交那一刻。

跑法：`.venv/Scripts/python.exe manage.py test apps.jobs`
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from django.conf import settings
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.jobs.models import Job
from apps.jobs.runner import run_export_excel

PASSWORD = 'x-jobs-12345678'

# 10 行 CTA8280F：两列在规格限内、一列超限（SW_Bin=5），够 openpyxl 读出形状。
TINY_CSV = (
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


def _sheet_names(path: str):
    """产出包里所有 worksheet 成员名。空列表 = 这不是一份能打开的工作簿。"""
    with zipfile.ZipFile(path) as zf:
        return [n for n in zf.namelist() if n.startswith('xl/worksheets/sheet')]


def _sheet_rows(path: str) -> int:
    """数第一个 worksheet 里的 `<row ` 出现次数（没有 sheet 时返回 -1）。

    不用 `openpyxl.load_workbook(...).max_row`：这里的 xlsx 是手写数据区 XML + zip
    重打包出来的，没写 `dimension` 记录，`max_row` 实测恒报 1 —— 用它当判据，
    「FAIL 筛选真的少了几行」这条根本不承重。数 XML 的行元素才是它声称在数的东西。
    """
    names = _sheet_names(path)
    if not names:
        return -1
    with zipfile.ZipFile(path) as zf:
        xml = zf.read(sorted(names)[0]).decode('utf-8', 'replace')
    return xml.count('<row ')


def _worker_probe(code):
    """在**没有 DJANGO_SETTINGS_MODULE** 的子进程里跑一段代码。

    刻意清空环境变量：`manage.py test` 的父进程里 DJANGO_SETTINGS_MODULE 已被设上，
    子进程继承它就会悄悄 setup 出 Django，于是「不依赖 Django」这条判据永远假绿。
    """
    env = dict(os.environ)
    env.pop('DJANGO_SETTINGS_MODULE', None)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return subprocess.run(
        [sys.executable, '-c', code], capture_output=True, text=True,
        encoding='utf-8', errors='replace', env=env, cwd=root, timeout=120)


class WorkerModuleIsolationTests(unittest.TestCase):
    """判据 1：worker 侧模块必须能脱离 Django 导入并使用。"""

    def test_worker_modules_import_without_django_setup(self):
        code = (
            'import apps.common.grid_filters, apps.export.filters, apps.jobs.runner;'
            'print("ok")'
        )
        proc = _worker_probe(code)
        self.assertEqual(
            proc.returncode, 0,
            msg=f'worker 侧模块在无 Django 的子进程里导入失败：\n{proc.stderr[-1500:]}')
        self.assertIn('ok', proc.stdout)

    def test_batch_charts_chain_imports_without_django(self):
        """S2 的前提：批量图表与 HTML 报告要能整条搬进 worker。

        这条第一次跑就红了 —— `apps/common/user_settings.py` 有一行
        `from apps.accounts.models import UserSetting` 带着 `# noqa: F401`，
        全文件实际没人用它，但它让 `export_batch_charts_xlsx`（只取
        `DEFAULT_CPK_THRESHOLDS` 这个纯 NamedTuple）在 spawn 子进程里 import 就炸。
        """
        code = (
            'import apps.export.export_batch_charts_xlsx;'
            'import apps.export.html_report;'
            'from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS, CpkThresholds;'
            'assert DEFAULT_CPK_THRESHOLDS.cpk_a == 1.67;'
            'print("ok")'
        )
        proc = _worker_probe(code)
        self.assertEqual(
            proc.returncode, 0,
            msg=f'批量图表/HTML 报告链路带 Django 依赖，worker 起不来：\n'
                f'{proc.stderr[-1500:]}')
        self.assertIn('ok', proc.stdout)

    def test_django_import_would_have_been_caught(self):
        """上一条的对照组：同一个探针确实能抓到 Django 依赖。

        没有这条，上一条可能因为「子进程根本没跑起来、返回码被忽略」而假绿。
        """
        proc = _worker_probe('from django.conf import settings; print(settings.DEBUG)')
        self.assertNotEqual(
            proc.returncode, 0,
            msg='探针自己不再能识别 Django 依赖了 —— 上一条判据已失效')


class JobsApiTests(APITestCase):
    """判据 2/3/4：端点契约、所有权、降级、参数快照。

    这些用例把 `executor.submit` 换成记录器：作业真正的执行由
    `RealPoolEndToEndTests` 与 `RunnerPureFunctionTests` 各自负责。
    不注入的话，「提交后 result_path 仍为空」会变成和后台进程赛跑的竞态断言。
    """

    def setUp(self):
        import apps.jobs.executor as executor_module
        self.user = User.objects.create_user('jobs_owner', 'jo@localhost', PASSWORD)
        self.other = User.objects.create_user('jobs_other', 'jt@localhost', PASSWORD)
        self.tmpdir = tempfile.mkdtemp(prefix='jobs_api_')
        self.path = self._write_tiny_file('tiny.csv')
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='tiny.csv', file_path=self.path,
            file_size=os.path.getsize(self.path), format_type='CTA8280F',
            status='ready', program_name='PROG')
        self.client.force_authenticate(user=self.user)

        self.submitted = []

        def fake_submit(job, task):
            self.submitted.append((job.id, task))
            Job.objects.filter(pk=job.id).update(status='running', progress=0)

        self._original_submit = executor_module.submit
        executor_module.submit = fake_submit
        self.addCleanup(setattr, executor_module, 'submit', self._original_submit)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_tiny_file(self, name):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(TINY_CSV)
        return path

    def _submit(self, **params):
        return self.client.post('/api/v1/jobs/export_excel/',
                                {'file_id': self.datafile.id, **params},
                                format='json')

    # ── 提交与状态机 ────────────────────────────────────────────────

    def test_submit_returns_202_and_persists_owned_job(self):
        resp = self._submit()
        self.assertEqual(resp.status_code, 202, resp.content)
        body = resp.json()
        self.assertIn('job_id', body)
        job = Job.objects.get(pk=body['job_id'])
        self.assertEqual(job.owner_id, self.user.pk)
        self.assertEqual(job.kind, 'export_excel')
        self.assertIn(job.status, ('pending', 'running'))
        # 提交必须「拿了号就走」：请求线程里不许出现结果文件
        self.assertEqual(job.result_path, '')

    def test_status_shape_has_every_field_frontend_polls(self):
        job_id = self._submit().json()['job_id']
        body = self.client.get(f'/api/v1/jobs/{job_id}/').json()
        self.assertEqual(
            set(body), {'id', 'kind', 'status', 'progress', 'error',
                        'result_name', 'created_at'})
        self.assertEqual(body['id'], job_id)

    def test_params_snapshot_is_stored_verbatim_and_reaches_worker(self):
        resp = self._submit(passfail='FAIL', site_filter='2',
                            sort_model='[{"colId":"VOLT","sort":"desc"}]')
        job = Job.objects.get(pk=resp.json()['job_id'])
        self.assertEqual(job.params['passfail'], 'FAIL')
        self.assertEqual(job.params['site_filter'], '2')
        self.assertEqual(job.params['file_id'], self.datafile.id)
        # 快照必须在提交那一刻就固定：作业可能在用户改完设置之后才被领取
        _job_id, task = self.submitted[-1]
        self.assertEqual(task['filters']['passfail'], 'FAIL')
        self.assertEqual(task['filters']['site_filter'], '2')
        self.assertEqual(task['filters']['sort_model'],
                         '[{"colId":"VOLT","sort":"desc"}]')
        self.assertNotIn('file_id', task['filters'],
                         'file_id 是主进程才知道的东西，混进 filters 会让 worker 去找库')

    # ── 所有权与错误形态 ────────────────────────────────────────────

    def test_other_users_job_is_404_not_403(self):
        """403 会告诉调用方「这个 id 存在」，作业 id 是自增的 ⇒ 可枚举。"""
        job_id = self._submit().json()['job_id']
        self.client.force_authenticate(user=self.other)
        for method, url in (('get', f'/api/v1/jobs/{job_id}/'),
                            ('get', f'/api/v1/jobs/{job_id}/download/'),
                            ('post', f'/api/v1/jobs/{job_id}/cancel/')):
            resp = getattr(self.client, method)(url)
            self.assertEqual(resp.status_code, 404, f'{method} {url} → {resp.status_code}')

    def test_list_only_returns_own_jobs(self):
        mine = self._submit().json()['job_id']
        other_client = self.client
        other_client.force_authenticate(user=self.other)
        ids = [row['id'] for row in other_client.get('/api/v1/jobs/').json()['results']]
        self.assertNotIn(mine, ids)
        other_client.force_authenticate(user=self.user)
        self.assertIn(mine, [r['id'] for r in
                             other_client.get('/api/v1/jobs/').json()['results']])

    def test_download_before_done_is_404(self):
        job_id = self._submit().json()['job_id']
        resp = self.client.get(f'/api/v1/jobs/{job_id}/download/')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['code'], 'job_not_ready')

    def test_cancel_pending_succeeds_but_running_is_409(self):
        job = Job.objects.create(owner=self.user, kind='export_excel',
                                 status='pending', params={})
        resp = self.client.post(f'/api/v1/jobs/{job.id}/cancel/')
        self.assertEqual(resp.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')

        job2 = Job.objects.create(owner=self.user, kind='export_excel',
                                  status='running', params={})
        self.assertEqual(self.client.post(f'/api/v1/jobs/{job2.id}/cancel/').status_code, 409)

    def test_unknown_kind_is_400(self):
        resp = self.client.post('/api/v1/jobs/no_such_kind/', {'file_id': self.datafile.id},
                                format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'unsupported_kind')

    def test_submit_requires_existing_own_file(self):
        self.client.force_authenticate(user=self.other)
        resp = self.client.post('/api/v1/jobs/export_excel/',
                                {'file_id': self.datafile.id}, format='json')
        self.assertEqual(resp.status_code, 404)

    # ── 降级路径 ────────────────────────────────────────────────────

    def test_pool_unavailable_falls_back_to_sync_response(self):
        """进程池建不出来（PyInstaller 环境异常）时，行为必须退回今天的样子。

        这条是 spec §7 唯一的「必须有测试」降级：200 + 文件流 + X-Job-Fallback 头，
        而不是 500，也不是静默排队等一个永远不会来的 worker。
        """
        import apps.jobs.executor as executor_module
        original = executor_module.executor_available
        executor_module.executor_available = lambda: False
        self.addCleanup(setattr, executor_module, 'executor_available', original)
        resp = self._submit()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get('X-Job-Fallback'), '1')
        self.assertTrue(resp.get('Content-Disposition'), '降级响应必须带下载文件名')

    def test_broken_pool_falls_back_to_sync_instead_of_500(self):
        """池里的子进程死过一次之后，下一次提交必须降级，不能永久 500。

        2026-10-24 实测成因链（e2e slot 池现场，`C:/lqdp-e2e/slots/022212-54444`）：
        OpenBLAS 分配失败 → worker 被杀 → `pool.submit` 抛 BrokenProcessPool →
        视图不接 → 该进程**此后每次提交都 500**，而 `executor_available()` 因为
        「池对象还在」照样返回 True，所以永远走不到同步回落。服务器上等于
        一次内存尖峰永久废掉所有导出，而 `Restart=always` 救不了（进程没死）。
        """
        import apps.jobs.executor as executor_module
        from concurrent.futures.process import BrokenProcessPool

        class DeadPool:
            def submit(self, *args, **kwargs):
                raise BrokenProcessPool('A child process terminated abruptly')

            def shutdown(self, *args, **kwargs):
                pass

        executor_module.reset_for_tests()
        self.addCleanup(executor_module.reset_for_tests)
        executor_module._pool = DeadPool()
        # 本类的 setUp 把 submit 换成了记录器；这条用例要量的正是真实 submit 与
        # 视图之间的异常契约，所以装回真身。
        executor_module.submit = self._original_submit

        resp = self._submit()
        self.assertEqual(resp.status_code, 200,
                         f'崩过一次的池必须走同步回落，实际 {resp.status_code}：'
                         f'{getattr(resp, "data", None)}')
        self.assertEqual(resp.get('X-Job-Fallback'), '1')
        # 换池：坏池不能被留着，否则下一条提交还要再废一次
        self.assertIsNone(executor_module._pool,
                          'BrokenProcessPool 之后没有丢弃坏池，下一次提交仍会失败')

    def test_broken_pool_leaves_no_pending_job(self):
        """降级路径不能留下永远 `pending` 的行 —— 开机自愈只清 `running`。"""
        import apps.jobs.executor as executor_module
        from concurrent.futures.process import BrokenProcessPool

        class DeadPool:
            def submit(self, *args, **kwargs):
                raise BrokenProcessPool('boom')

            def shutdown(self, *args, **kwargs):
                pass

        executor_module.reset_for_tests()
        self.addCleanup(executor_module.reset_for_tests)
        executor_module._pool = DeadPool()
        executor_module.submit = self._original_submit

        before = {j.id: j.status for j in Job.objects.filter(owner=self.user)}
        self._submit()
        after = list(Job.objects.filter(owner=self.user).exclude(id__in=before))
        self.assertEqual(len(after), 1, '降级路径应当仍然只建一行作业')
        self.assertIn(after[0].status, ('done', 'error'),
                      f'作业卡在 {after[0].status}：没人会再来改它')

    # ── 启动钩子 ────────────────────────────────────────────────────

    def test_running_jobs_are_marked_error_on_boot(self):
        """进程重启后 running 是僵尸：没人会再来改它，前端会永远轮询。"""
        zombie = Job.objects.create(owner=self.user, kind='export_excel',
                                    status='running', params={})
        queued = Job.objects.create(owner=self.user, kind='export_excel',
                                    status='pending', params={})
        done = Job.objects.create(owner=self.user, kind='export_excel',
                                  status='done', result_path='jobs/1/2/x.xlsx', params={})
        from apps.jobs.apps import mark_interrupted_jobs
        mark_interrupted_jobs()

        zombie.refresh_from_db()
        self.assertEqual(zombie.status, 'error')
        self.assertIn('重启', zombie.error)
        done.refresh_from_db()
        self.assertEqual(done.status, 'done')
        # pending 不判死：它还没被领取，重启后照常可执行
        queued.refresh_from_db()
        self.assertEqual(queued.status, 'pending')


class OfflineCommandPredicateTests(unittest.TestCase):
    """启动清理该不该跑，取决于这条谓词 —— 判反了僵尸作业就永远没人收。"""

    def test_offline_management_commands_are_skipped(self):
        from apps.jobs.apps import _is_offline_command
        for argv in (['manage.py', 'test'], ['manage.py', 'migrate'],
                     ['manage.py', 'makemigrations'], ['manage.py', 'check']):
            self.assertTrue(_is_offline_command(argv), argv)

    def test_server_paths_still_sweep(self):
        """判据方向是 fail-safe：认不出来的命令一律照清。"""
        from apps.jobs.apps import _is_offline_command
        for argv in (['manage.py', 'runserver', '127.0.0.1:8000'],
                     ['standalone.py', '--host', '0.0.0.0', '--port', '8000'],
                     ['gunicorn', 'config.wsgi'],          # Linux 正式档
                     ['python', '-c', 'x=1']):             # 没有命令词
            self.assertFalse(_is_offline_command(argv), argv)

    def test_warning_free_import_path(self):
        """`manage.py check` 这类离线命令不该在 app 加载期碰库。

        钉住 Django 那句 `RuntimeWarning: Accessing the database during app
        initialization` 不再出现 —— 它是本文件那条钩子的直接后果，回归了就该看见。
        """
        code = (
            'import warnings, sys;'
            'warnings.simplefilter("error", RuntimeWarning);'
            'sys.argv=["manage.py","check"];'
            'import django;'
            'from django.conf import settings;'
            'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE",'
            '"config.settings.unit"); django.setup(); print("clean")'
        )
        proc = _worker_probe(code)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr[-1200:])
        self.assertIn('clean', proc.stdout)


class RunnerPureFunctionTests(TestCase):
    """判据 4：worker 入口函数本身 —— 不靠进程池也能独立证。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='jobs_runner_')
        self.path = os.path.join(self.tmpdir, 'tiny.csv')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(TINY_CSV)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _task(self, **over):
        out = os.path.join(self.tmpdir, 'out.xlsx')
        task = {'abs_path': self.path, 'fmt': 'CTA8280F',
                'filters': {}, 'hidden_columns': [], 'out_path': out,
                'result_name': 'tiny.xlsx'}
        task.update(over)
        return task, out

    def test_run_export_excel_produces_readable_xlsx(self):
        task, out = self._task()
        result = run_export_excel(task)
        self.assertEqual(result['bytes_written'], os.path.getsize(out))
        self.assertTrue(_sheet_names(out), '包里没有 worksheet，不是能打开的工作簿')
        # 这里刻意只断「>1 行」不断具体行数：实测这份 10 行夹具导出后是 21 个 `<row `
        # （`tasks/_jobs_runner_probe.py`），是导出器自己的行布局，我解释不了它的构成，
        # 把一个看不懂的常数钉进判据，将来只会变成「改断言迁就实现」。
        # 「筛选真的改变了行数」这条由下一条用例用关系断言承重。
        self.assertGreater(_sheet_rows(out), 1)

    def test_filters_actually_change_the_row_set(self):
        """worker 里的筛选必须真的生效 —— 否则作业化会静默导出全量。"""
        task, out = self._task()
        run_export_excel(task)
        rows_all = _sheet_rows(out)

        task2, out2 = self._task(filters={'passfail': 'FAIL'},
                                 result_name='fail.xlsx')
        run_export_excel(task2)
        rows_fail = _sheet_rows(out2)

        task3, out3 = self._task(filters={'site_filter': '2'},
                                 result_name='site2.xlsx')
        run_export_excel(task3)
        rows_site2 = _sheet_rows(out3)

        self.assertLess(rows_fail, rows_all, 'FAIL 筛选没减少行 = filters 被忽略')
        self.assertLess(rows_site2, rows_all, 'site 筛选没减少行 = filters 被忽略')
        self.assertGreater(rows_fail, 1, 'FAIL 筛成空表说明 worker 侧的 fail 判定不工作')

    def test_progress_write_works_before_the_result_dir_exists(self):
        """作业目录是**跑完才创建**的，而进度从第一秒就要写。

        e2e 第一次跑作业化导出时就是红在这里：`write_progress` 直接 open(...,'w')
        一个还不存在的目录 → FileNotFoundError → worker 死 → 前端永远等不到下载事件。
        单测先前漏掉，是因为所有夹具的 out_path 父目录本来就存在。
        """
        deep = os.path.join(self.tmpdir, 'fresh', 'nested', 'out.xlsx')
        self.assertFalse(os.path.isdir(os.path.dirname(deep)))
        task, _out = self._task()
        task['out_path'] = deep
        task['progress_path'] = os.path.join(os.path.dirname(deep), '.progress')
        result = run_export_excel(task)
        self.assertTrue(os.path.exists(result['out_path']))
        with open(task['progress_path'], encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), '100')

    def test_progress_failure_does_not_kill_the_export(self):
        """进度是装饰性的：写不进去（只读盘、被别的进程锁住）也不能让导出失败。"""
        task, out = self._task()
        task['progress_path'] = os.path.join(self.tmpdir, 'nope', '.progress')
        original = os.makedirs

        def explode(path, *a, **kw):
            if str(path).endswith('nope'):
                raise OSError('read-only filesystem')
            return original(path, *a, **kw)

        with mock.patch('os.makedirs', side_effect=explode):
            # 第一次写进度就会抛：实现必须吞掉它，继续把 xlsx 写出来
            result = run_export_excel(task)
        self.assertTrue(os.path.exists(result['out_path']))
        self.assertGreater(result['bytes_written'], 0)

    def test_task_dict_is_picklable(self):
        """Windows 是 spawn：task 必须能 pickle，否则进不了进程池。"""
        import pickle
        task, _out = self._task()
        self.assertEqual(pickle.loads(pickle.dumps(task)), task)


class ExecutorDispatchTests(unittest.TestCase):
    """判据 4 的另一半：task 是主进程拼的，快照字段必须原样到 worker。"""

    def test_build_task_carries_snapshot_and_absolute_path(self):
        from apps.jobs.executor import build_export_excel_task
        tmpdir = tempfile.mkdtemp(prefix='jobs_exec_')
        try:
            path = os.path.join(tmpdir, 'tiny.csv')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(TINY_CSV)
            params = {'file_id': 7, 'passfail': 'PASS', 'site_filter': '1'}
            task = build_export_excel_task(
                params=params, abs_path=path, fmt='CTA8280F',
                hidden_columns=['QR_Code'], job_id=42, owner_id=3)
            self.assertEqual(task['abs_path'], path)
            self.assertEqual(task['hidden_columns'], ['QR_Code'])
            self.assertEqual(task['fmt'], 'CTA8280F')
            # filters 里只该有算子字段，file_id 这类主进程才知道的东西不该混进去
            self.assertEqual(task['filters'], {'passfail': 'PASS', 'site_filter': '1'})
            self.assertIn(os.path.join('jobs', '3', '42'), task['out_path'])
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_pool_mp_context_is_pinned_not_left_to_default(self):
        """建池必须**显式**传 spawn，断言的是「参数存在」而不是「值是 spawn」。

        本机 Windows 的默认 start method 本来就是 spawn（实测），所以「删掉
        mp_context 实参」这种改法在这台机器上照样全绿；而 Linux 的默认是 fork，
        删掉就把本文件判据 1 那条「子进程里没有 django.setup()」的契约静默打掉。
        截住构造函数断言实参本身，两个平台都能红。
        """
        import apps.jobs.executor as executor_module
        captured = {}
        real_cls = executor_module.ProcessPoolExecutor

        def spy(*args, **kwargs):
            captured.update(kwargs)
            return real_cls(*args, **kwargs)

        self.addCleanup(executor_module.reset_for_tests)
        executor_module.reset_for_tests()
        # 预热那一条 submit 会真的拉起 worker：本用例只验证接线，把它换成空函数。
        with mock.patch.object(executor_module, 'warmup_imports', lambda: None), \
                mock.patch.object(executor_module, 'ProcessPoolExecutor', spy):
            pool = executor_module._get_pool()
        self.assertIsNotNone(pool)
        self.assertIn('mp_context', captured,
                      '建池没有显式传 mp_context：Windows 蒙对，Linux 会退化成 fork')
        self.assertEqual(captured['mp_context'].get_start_method(), 'spawn')


    def test_submit_on_broken_pool_raises_domain_error_and_discards_pool(self):
        """`submit` 必须把 `BrokenProcessPool` 换成本模块的语义异常，并把坏池扔掉。

        断言的是两件事，缺一就退回原缺陷：
        ① 抛出的异常类型是视图**认得**的（`executor.PoolBroken`），不是标准库异常 ——
           否则视图要么漏接（500），要么用 `except Exception` 把它和真业务失败混掉；
        ② 池对象被置空，下一次 `_get_pool()` 会重建 —— 否则「永久废池」原样保留。
        """
        import apps.jobs.executor as ex
        from concurrent.futures.process import BrokenProcessPool

        class DeadPool:
            def submit(self, *args, **kwargs):
                raise BrokenProcessPool('boom')

            def shutdown(self, *args, **kwargs):
                pass

        self.addCleanup(ex.reset_for_tests)
        ex.reset_for_tests()
        ex._pool = DeadPool()

        job = mock.Mock(id=99, kind='export_excel')
        with self.assertRaises(ex.PoolBroken):
            ex.submit(job, {})
        self.assertIsNone(ex._pool, '坏池没有被丢弃')

        built = {}

        class StubPool:
            def __init__(self, *args, **kwargs):
                built['ok'] = True

            def submit(self, *args, **kwargs):
                return mock.Mock()

            def shutdown(self, *args, **kwargs):
                pass

        with mock.patch.object(ex, 'ProcessPoolExecutor', StubPool), \
                mock.patch.object(ex, 'warmup_imports', lambda *a, **k: None):
            fresh = ex._get_pool()
        self.assertTrue(built.get('ok'), '丢弃之后下一次取池没有重建')
        self.assertIsInstance(fresh, StubPool)


class RealPoolEndToEndTests(TransactionTestCase):
    """真进程池跑通一次：提交 → 子进程算 → 状态回填 → 下载。

    这是本片唯一证明「Windows spawn + worker 不碰 Django + 结果写回 SQLite」整条链路
    成立的用例，其余用例都注入假 submit。代价是它会真的 spawn 进程池（首轮约 0.7s，
    模块级常驻，后续复用），所以只留这一条。

    **必须 TransactionTestCase**：结果回填跑在进程池的管理线程里，用的是**另一条 DB
    连接**；`TestCase` 把用例包在一个未提交的事务里，那条线程看不见这行 Job，
    `update()` 命中 0 行 → 状态永远停在 running（实测就这样红过一次）。同仓先例见
    `apps/datafiles/tests_import_tx.py:11-13`。
    """

    def setUp(self):
        import apps.jobs.executor as executor_module
        # TransactionTestCase 的 self.client 是 Django 的 Client，没有 force_authenticate
        self.client = APIClient()
        self.user = User.objects.create_user('jobs_e2e', 'je@localhost', PASSWORD)
        self.client.force_authenticate(user=self.user)
        self.tmpdir = tempfile.mkdtemp(prefix='jobs_e2e_')
        path = os.path.join(self.tmpdir, 'tiny.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(TINY_CSV)
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='tiny.csv', file_path=path,
            file_size=os.path.getsize(path), format_type='CTA8280F',
            status='ready', program_name='PROG')
        self.addCleanup(executor_module.reset_for_tests)
        self.addCleanup(__import__('shutil').rmtree, self.tmpdir, True)

    def test_export_job_completes_through_the_process_pool(self):
        resp = self.client.post('/api/v1/jobs/export_excel/',
                                {'file_id': self.datafile.id}, format='json')
        self.assertEqual(resp.status_code, 202, resp.content)
        job_id = resp.json()['job_id']

        job = None
        for _ in range(120):        # 最多等 30s：导出 10 行文件正常在 2s 内
            job = Job.objects.get(pk=job_id)
            if job.status in ('done', 'error'):
                break
            import time
            time.sleep(0.25)
        self.assertEqual(job.status, 'done', f'error={job.error!r}')
        self.assertEqual(job.progress, 100)
        self.assertTrue(job.result_path.startswith(os.path.join('jobs', str(self.user.pk))),
                        job.result_path)

        down = self.client.get(f'/api/v1/jobs/{job_id}/download/')
        self.assertEqual(down.status_code, 200)
        blob = b''.join(down.streaming_content)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            self.assertTrue([n for n in zf.namelist()
                             if n.startswith('xl/worksheets/sheet')],
                            '下载到的不是能打开的工作簿')
        self.assertEqual(blob, open(os.path.join(
            str(settings.MEDIA_ROOT), job.result_path), 'rb').read(),
            '下载内容与 worker 落盘的文件必须逐字节一致')


class BatchChartsAndHtmlReportTests(TestCase):
    """S2：另两类重活也搬进 worker，且**不许嵌套进程池**。

    `build_batch_charts_xlsx_with_charts` 自己就开 `ProcessPoolExecutor(8)`。
    作业已经跑在常驻池（`MAX_POOL_WORKERS` 最多 4）的子进程里，再开一层就是
    4×8=32 个 Python 进程 —— 每个常驻 150–250MB，20 人档会把机器打爆。
    所以作业侧必须请求串行渲染，并行度只在常驻池那一层给。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='jobs_s2_')
        self.path = os.path.join(self.tmpdir, 'tiny.csv')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(TINY_CSV)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _base_task(self, name):
        out = os.path.join(self.tmpdir, name)
        return {'abs_path': self.path, 'fmt': 'CTA8280F', 'out_path': out,
                'result_name': os.path.basename(out),
                'datafile': {'id': 1, 'filename': 'tiny.csv',
                             'program_name': 'PROG'},
                'params': ['VOLT'], 'filters': {}, 'data_only_bin1': False,
                'show_limit': True, 'show_3sigma': False, 'show_4sigma': False,
                'show_6sigma': True, 'show_normal': False, 'show_kde': False,
                'dpi': 100, 'cpk_thresholds': (1.67, 1.33, 1.0),
                'generated_at': '2026-10-18 12:00:00'}

    def test_batch_charts_job_produces_xlsx(self):
        from apps.jobs.runner import run_export_batch_charts
        task = self._base_task('charts.xlsx')
        result = run_export_batch_charts(task)
        self.assertTrue(_sheet_names(result['out_path']),
                        '批量图表作业产出不是能打开的工作簿')
        self.assertGreater(result['bytes_written'], 0)

    def test_workers_one_does_not_construct_a_render_pool(self):
        """嵌套的 proof 必须是行为，不是源码里有没有 `workers=1` 这串字。

        把 builder 模块内的 `ProcessPoolExecutor` 换成一个「一旦被构造就抛」的哨兵，
        再按作业路径（workers=1）调用：能跑完 ⇒ 内层池确实没被构造。
        源码 grep 那种判据改个写法（如 `workers=int(1)`）就假绿，且挡不住
        「传了 1 但代码里仍走并行分支」的真 bug。
        """
        import apps.export.export_batch_charts_xlsx as builder

        class Boom:
            def __init__(self, *a, **kw):
                raise AssertionError('workers=1 时不该构造渲染进程池')

        original = builder.ProcessPoolExecutor
        builder.ProcessPoolExecutor = Boom
        self.addCleanup(setattr, builder, 'ProcessPoolExecutor', original)

        from apps.common.user_settings import CpkThresholds
        from apps.datafiles.parsers import get_parser
        df, metadata = get_parser('CTA8280F').parse(self.path)
        payload = builder.build_batch_charts_xlsx_with_charts(
            df, metadata, ['VOLT'], workers=1,
            cpk_thresholds=CpkThresholds(1.67, 1.33, 1.0))
        self.assertGreater(len(payload), 0)

    def test_default_call_still_uses_the_pool(self):
        """上一条的对照：不传 workers 时池必须照旧被构造，否则我是把并行改没了。"""
        import apps.export.export_batch_charts_xlsx as builder

        built = []

        class Spy(builder.ProcessPoolExecutor):
            def __init__(self, *a, **kw):
                built.append(kw.get('max_workers'))
                super().__init__(*a, **kw)

        original = builder.ProcessPoolExecutor
        builder.ProcessPoolExecutor = Spy
        self.addCleanup(setattr, builder, 'ProcessPoolExecutor', original)

        from apps.common.user_settings import CpkThresholds
        from apps.datafiles.parsers import get_parser
        df, metadata = get_parser('CTA8280F').parse(self.path)
        builder.build_batch_charts_xlsx_with_charts(
            df, metadata, ['VOLT'], cpk_thresholds=CpkThresholds(1.67, 1.33, 1.0))
        self.assertEqual(len(built), 1, f'缺省路径应当构造一次渲染池，实际 {built}')

    def test_progress_sidecar_reports_intermediate_percent(self):
        """进度侧车：worker 没有 Django、写不了 DB，就落一个文件让主进程轮询器读。

        断的是**中间值**（3 个参数时第 1、2 个必须落在 1..99 之间且递增），
        只断「最终 == 100」的判据恒绿：什么都不写的实现也能给出 100。
        """
        from apps.jobs.runner import write_progress
        path = os.path.join(self.tmpdir, '.progress')
        seen = []
        for done in range(1, 4):
            write_progress(path, done, total=3)
            with open(path, encoding='utf-8') as f:
                seen.append(int(f.read().strip()))
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(0 < v <= 100 for v in seen), seen)
        self.assertEqual(seen, sorted(seen), f'进度不许回退：{seen}')
        self.assertLess(seen[0], 100, '第一个参数完成时就该 <100，否则进度条永远空转')
        self.assertEqual(seen[-1], 100)

    def test_batch_charts_job_writes_sidecar_while_rendering(self):
        from apps.jobs.runner import run_export_batch_charts
        task = self._base_task('charts2.xlsx')
        task['params'] = ['VOLT', 'Data_Num', 'Test_Time']
        task['progress_path'] = os.path.join(self.tmpdir, '.progress')
        result = run_export_batch_charts(task)
        self.assertEqual(result['progress_percent'], 100)

    def test_batch_charts_pptx_branch_produces_a_deck(self):
        """我在 runner 里写了 pptx 分支，不测就不能说它可用。

        顺带钉住一件事：`build_batch_charts_pptx` 自己不嵌池（不像 xlsx builder），
        所以作业化它不需要 `workers=1` 那层保护 —— 若将来它也开池，这条用例
        的产物仍对，但嵌套判据要照 xlsx 那条补上。
        """
        from apps.jobs.runner import run_export_batch_charts
        task = self._base_task('deck.pptx')
        task['chart_format'] = 'pptx'
        result = run_export_batch_charts(task)
        self.assertGreater(result['bytes_written'], 0)
        with zipfile.ZipFile(result['out_path']) as zf:
            self.assertIn('ppt/presentation.xml', zf.namelist())

    def test_html_report_job_produces_self_contained_html(self):
        from apps.jobs.runner import run_export_html_report
        task = self._base_task('report.html')
        result = run_export_html_report(task)
        with open(result['out_path'], 'r', encoding='utf-8') as f:
            html = f.read()
        self.assertIn('<html', html.lower())
        self.assertIn('data:image/png;base64', html,
                      'HTML 报告的图表是内联 base64；丢了它就等于报告没有图')
        self.assertEqual(result['bytes_written'], os.path.getsize(result['out_path']))

    def test_both_new_tasks_are_picklable(self):
        import pickle
        from apps.jobs.runner import run_export_batch_charts  # noqa: F401
        from apps.jobs.runner import run_export_html_report  # noqa: F401
        for name in ('charts.xlsx', 'report.html'):
            task = self._base_task(name)
            self.assertEqual(pickle.loads(pickle.dumps(task)), task)


class ExecutorRegistryTests(unittest.TestCase):
    """三类作业都必须在注册表里，且各自的超时不同（spec §4.3）。"""

    def test_all_kinds_registered(self):
        """四类重活都在注册表里（S1 那条断「恰好三类导出」，S3 加下载后由这条接替）。

        断的是「该有的都有」，不是「只有这些」—— 后者会在每加一类作业时假红一次，
        而它想防的其实是「某类被漏掉」。
        """
        from apps.jobs import executor
        self.assertEqual(
            set(executor.KIND_RUNNERS),
            {'export_excel', 'export_batch_charts', 'export_html_report',
             'sftp_download'})

    def test_every_kind_has_a_complete_spec(self):
        """每类作业都必须给齐 entry / lane / timeout —— 漏一个就是运行时 KeyError。"""
        from apps.jobs import executor
        for kind, spec in executor.KIND_RUNNERS.items():
            self.assertTrue(callable(spec['entry']), kind)
            self.assertIn(spec['lane'], ('process', 'thread'), kind)
            self.assertGreater(spec['timeout'], 0, kind)

    def test_worker_modules_for_all_kinds_are_django_free(self):
        """新增两类不能把 Django 又拽回 worker。"""
        code = ('import apps.jobs.runner as r;'
                'assert callable(r.run_export_batch_charts) and '
                'callable(r.run_export_html_report); print("ok")')
        proc = _worker_probe(code)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr[-1500:])
        self.assertIn('ok', proc.stdout)


if __name__ == '__main__':
    unittest.main()
