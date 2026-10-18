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


if __name__ == '__main__':
    unittest.main()
