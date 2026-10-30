"""Task C3 判据（executor 退出侧）：`shutdown_pools_for_exit` 的终态归属、退出窗口
**不许重新武装建池**，以及两条「谁 import 谁」的运行时探针。

与 `test/backend/test_shutdown_closes_pools.py` 同族（拆分的唯一原因是 600 行绊线，
道具共用 `test/backend/shutdown_pool_fixtures.py`）：那边的用例判 `apps/common/shutdown.py`
的调用序列，这边判 `apps/jobs/executor.py` 自己的函数与 import 形状。

`ExecutorNotImportedAtRuntimeTests` 两枚探针与 `ExitPoolShutdownTests` 六个用例
2026-10-30 从 `test_shutdown_closes_pools.py` 搬入（承重不变，见那边的模块头
七组承重之 3、4；唯一改动是 `test_cleanup_lands_both_lanes_terminal_through_the_real_path`
按 Fix 7 显式 patch 掉 `_flush_output`，不再让进程级 `logging.shutdown()` 跨用例泄漏）；
`ExitBlindsPoolRebuildTests` 与 `RunnerChainProbeTests` 是本轮修复新加
（Fix 1 的 bug 本体 / Fix 2 拆分的前提证明）。

跑法：`python -X utf8 manage.py test test.backend.test_exit_pool_shutdown`
"""

import os
import pathlib
import subprocess
import sys
from concurrent.futures import Future
from unittest import mock

from django.test import SimpleTestCase, TestCase, TransactionTestCase

from apps.accounts.models import User
from apps.common import shutdown
from apps.jobs import executor
from apps.jobs.models import Job
from test.backend.job_cancel_fixtures import (
    PASSWORD, ExecutorSeamMixin, dropped_text)
from test.backend.shutdown_pool_fixtures import CountingPool


class ExecutorNotImportedAtRuntimeTests(TestCase):
    """「`shutdown.py` 不许在模块顶层依赖 `apps.jobs`」这条约束的**运行时**判据。

    为什么不用 AST 扫源码文本：那是 `docs/tasks/lessons.md:270-284`（2026-10-18 那条）
    明确否掉的形状 —— 文本断言只证明代码长这样，把依赖藏在包 `__init__`、函数体或
    `importlib` 里它就恒绿，而这条约束真正要防的正是「谁在 app 就绪之前 import 了 models」。
    形状照仓内已接受的先例（`test/backend/test_norm_ppf_memo.py:471-488` 的子进程探针）。

    探针必须 `django.setup()` 之后再 import：先 import 的话 DRF 那一串顶层把手会抛
    `AppRegistryNotReady`（评审 2026-10-29 实测），崩在断言之前、区分不了任何东西。
    `sys.argv` 摆成离线命令（`manage.py check`）的形状，是为了让 `apps/jobs/apps.py::ready()`
    跳过「僵尸作业判死」那次真实 UPDATE —— 探针不许碰开发库里的数据。
    2026-10-30 看门狗拆分后 `apps.jobs.monitor` 与 executor 同乘降：它只被
    `executor` 的顶层 import 拽进来，所以「executor 缺席」必然连带「monitor 缺席」，
    本探针按 executor 缺席下断言仍然充分，不加新断言去数 monitor。
    """

    _ROOT = pathlib.Path(shutdown.__file__).resolve().parents[2]

    def _probe(self, extra_import):
        code = ('import sys; sys.argv = ["manage.py", "check"];'
                ' import django; django.setup();'
                ' import apps.common.shutdown;'
                + (' import apps.jobs.executor;' if extra_import else '') +
                ' print(",".join(sorted(m for m in sys.modules if m.startswith("apps.jobs"))))')
        proc = subprocess.run(
            [sys.executable, '-X', 'utf8', '-c', code], cwd=str(self._ROOT),
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=180, env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings.development'})
        self.assertEqual(proc.returncode, 0,
                         f'探针进程没跑起来（cwd={self._ROOT}）：{proc.stderr}')
        return set(proc.stdout.strip().split(','))

    def test_importing_shutdown_pulls_the_registry_but_not_the_executor(self):
        """干净树：`apps.jobs.models` 在（说明 app 注册表真的跑过了，不是探针空转到恒绿），
        `apps.jobs.executor` **不在**。
        变异：把 `_close_job_pools` 里那行 import 提到模块顶层 ⇒ 顶层 import 会把 executor
        一起拽进来，这里红。
        """
        modules = self._probe(extra_import=False)

        self.assertIn('apps.jobs.models', modules,
                      f'注册表没跑起来，缺席就不算证据：{sorted(modules)}')
        self.assertNotIn('apps.jobs.executor', modules,
                         f'shutdown.py 在模块顶层就把 apps.jobs.executor 拽进来了：{sorted(modules)}')

    def test_the_control_arm_does_see_the_executor_when_it_is_imported(self):
        """对照组（哨兵类判据必须带的那条「没把正常路径一起废掉」）：同一个探针只要显式
        import 一次 executor，它就必须**出现** —— 否则上面那条缺席可能只是探针压根没在看。
        """
        modules = self._probe(extra_import=True)

        self.assertIn('apps.jobs.executor', modules,
                      f'对照组失效：连显式 import 都不出现在 sys.modules：{sorted(modules)}')


class ExitPoolShutdownTests(ExecutorSeamMixin, TransactionTestCase):
    """`executor.shutdown_pools_for_exit()` 侧：终态归属（C1 不变量）与两条池互不拖累。

    这里用**真 submit 通路**造两条 lane 各一条作业（行写成 running、条目登记进
    `_in_flight`、`_Flight.pool` 指向各自那条池），所以关掉池之前不收尸，行就永久
    running —— 正是 C1 那一轮评审抓出来的形状换了个发起方重演。
    """

    def setUp(self):
        self.user = User.objects.create_user('c3_owner', 'c3@localhost', PASSWORD)
        self._tmp_source()
        self.addCleanup(executor.reset_for_tests)
        self.addCleanup(setattr, shutdown, '_shutdown_started', False)

    def _bind(self, proc, down):
        """两条 lane 各挂一条假池（`_patch_seams` 只有一条池，钉不住「两条都关」）。
        `_pool`/`_download_pool` 也要换：`shutdown_pools_for_exit` 读的就是这两个全局。"""
        for target, value in (('_get_pool', lambda: proc),
                              ('_get_download_pool', lambda: down),
                              ('_ensure_monitor', lambda: None),
                              ('_pool', proc), ('_download_pool', down)):
            patcher = mock.patch.object(executor, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _two_lanes(self, proc, down):
        """进程 lane + thread lane 各一条，都走生产 `submit()`。"""
        export = self._make_running_export()
        sftp, task = self._download_job()
        executor.submit(sftp, task)
        self.assertEqual(executor._pool, proc, '前提走形：进程 lane 没挂在这条池上')
        self.assertEqual(executor._download_pool, down, '前提走形：thread lane 没挂在这条池上')
        return export, sftp

    def _assert_terminal(self, job, expect_error=True):
        row = Job.objects.get(pk=job.id)
        self.assertNotEqual(row.status, 'running',
                            f'作业 {job.id} 留在 running：关池的发起方没落终态，'
                            f'而 `_write_back` 见 cancelled 就收手 ⇒ 前端永远轮询一个死作业')
        self.assertEqual(row.status, 'error')
        if expect_error:
            self.assertEqual(row.error, dropped_text())
            self.assertTrue(row.finished_at, '终态行没有 finished_at 就是半截状态')
        self.assertNotIn(job.id, executor._in_flight, '条目没被摘出在飞表')

    # ------------------------------------------------------------------
    def test_exit_step_lands_terminal_rows_for_both_lanes(self):
        """两条 lane 的作业都由这次退出落成终态。

        变异：`shutdown_pools_for_exit` 里不先 `_reap_discarded` ⇒ 两行都留在
        `running`、`error=''`（评审给崩池那条路复现过的同一个形状）。
        """
        proc, down = CountingPool(capacity=0), CountingPool(capacity=0)
        self._bind(proc, down)
        export, sftp = self._two_lanes(proc, down)
        self.assertEqual([Job.objects.get(pk=j.id).status for j in (export, sftp)],
                         ['running', 'running'], '前提走形：submit 之后两行都该是 running')

        executor.shutdown_pools_for_exit()

        for job in (export, sftp):
            self._assert_terminal(job)
        self.assertEqual(proc.calls, [(False, True)])
        self.assertEqual(down.calls, [(False, True)])

    def test_the_reap_happens_before_the_pool_is_shut_down(self):
        """`shutdown()` 那一刻读库：已经是终态 ⇒ 收尸排在关池**之前**。

        为什么这条位置承重：`FakePool`/真池的 `cancel_futures=True` 一旦跑起来，回调
        就把条目摘走且不再写行（`_write_back` 见 `future.cancelled()` 收手），届时按
        `_Flight.pool` 认领也认不到了 —— 所以只能先收尸。
        变异：把 `_reap_discarded` 与 `shutdown` 调换 ⇒ 这里读到 `running`。
        """
        proc, down = CountingPool(capacity=0), CountingPool(capacity=0)
        self._bind(proc, down)
        export, sftp = self._two_lanes(proc, down)
        proc.watch, down.watch = [export.id], [sftp.id]

        executor.shutdown_pools_for_exit()

        self.assertEqual(proc.statuses_at_shutdown, ['error'],
                         '关进程池的那一刻行还是 running ⇒ 收尸排在了关池之后')
        self.assertEqual(down.statuses_at_shutdown, ['error'],
                         '关下载池的那一刻行还是 running ⇒ 收尸排在了关池之后')

    def test_a_pool_that_raises_still_lets_the_other_pool_close(self):
        """一条池关不掉（真池里 `shutdown(wait=True)` 才会抛，这里注入抛错）不许把
        另一条池扔在原地 —— 那正是孤儿子进程的成因。
        变异：去掉 per-pool 的 try/except ⇒ 异常冒出 `shutdown_pools_for_exit`，
        `down.calls` 为空，这里红。
        """
        proc = CountingPool(capacity=0, raise_on_shutdown=True)
        down = CountingPool(capacity=0)
        self._bind(proc, down)
        export, sftp = self._two_lanes(proc, down)

        executor.shutdown_pools_for_exit()      # 不许抛

        self.assertEqual(down.calls, [(False, True)], '一条池抛错就扔下了另一条池')
        self._assert_terminal(sftp)

    def test_a_reap_that_raises_still_closes_the_pool(self):
        """收尸要写库，库没了（连接已关 / 锁死）也得把池关掉 —— 关池是正题。
        变异：把收尸与关池合进同一个 try/except ⇒ 收尸抛错后 `shutdown` 不被调用，
        两个 `calls` 都为空，这里红。
        """
        proc, down = CountingPool(capacity=0), CountingPool(capacity=0)
        self._bind(proc, down)
        self._two_lanes(proc, down)

        with mock.patch.object(executor, '_reap_discarded',
                               side_effect=RuntimeError('database is gone')):
            executor.shutdown_pools_for_exit()

        self.assertEqual(proc.calls, [(False, True)], '收尸失败就没关池')
        self.assertEqual(down.calls, [(False, True)], '收尸失败就没关池')

    def test_the_dead_pool_globals_are_dropped(self):
        """两条池从全局摘掉：留一个已 shutdown 的池在 `_pool` 上，之后的 `submit()`
        会把标准库 `RuntimeError` 抛进视图（500）；测试套件的用例之间也不该共享一条
        死池。口径与 `_discard_pool()`/`reset_for_tests()` 一致（换 None ⇒ 下一次重建）。
        变异：不再置 None ⇒ 这里红。
        """
        proc, down = CountingPool(capacity=0), CountingPool(capacity=0)
        self._bind(proc, down)
        self._two_lanes(proc, down)

        executor.shutdown_pools_for_exit()

        self.assertIsNone(executor._pool, '进程池全局没被摘掉')
        self.assertIsNone(executor._download_pool, '下载池全局没被摘掉')

    def test_cleanup_lands_both_lanes_terminal_through_the_real_path(self):
        """端到端接线：`shutdown._cleanup()` 这条真通路（不是直接调 executor 的函数）
        把两条 lane 落成终态，并把两条池都关掉。
        `_flush_output` 在这里**显式**换掉（Fix 7 minor）：本条是全族唯一走完整
        `_cleanup` 的用例，不拦它就会真执行进程级 `logging.shutdown()`（关掉所有
        handler；dev LOGGING 目前只有 StreamHandler 所以「 benign」，但那是跨用例
        泄漏的全局态，不是本条的判据）。DB 关闭留着真跑 —— 「Django 透明重连」正是
        `test_shutdown_closes_pools.py` 模块头第 2 组说过的事实，接线结论不依赖它。
        变异：`_cleanup` 里接错了函数（例如误调 `reset_for_tests`，它只关池不收尸）
        ⇒ 两行留在 running，这里红。
        """
        proc, down = CountingPool(capacity=0), CountingPool(capacity=0)
        self._bind(proc, down)
        export, sftp = self._two_lanes(proc, down)

        shutdown._shutdown_started = False
        with mock.patch.object(shutdown, '_flush_output') as flush:
            shutdown._cleanup('unit')

        flush.assert_called_once_with()
        # 钉「还原」：with 结束后 `shutdown._flush_output` 必须又是真函数（patch 泄漏
        # 到兄弟用例 = 后面的退出通路悄悄不刷日志）。
        self.assertIsNot(shutdown._flush_output, flush,
                         '_flush_output 的 patch 没被还原')
        for job in (export, sftp):
            self._assert_terminal(job)
        self.assertEqual(proc.calls, [(False, True)])
        self.assertEqual(down.calls, [(False, True)])


class ExitBlindsPoolRebuildTests(SimpleTestCase):
    """Fix 1（真 bug）：退出调用之后，**建池这件事必须对剩余进程永久关闭**。

    `shutdown_pools_for_exit()` 过去只把 `_pool` 摘成 None，不置 `_pool_failed` ⇒
    退出窗口里还在被服务的任何请求（`apps/jobs/views.py` 的 `_dispatch` 每条请求都调
    `executor_available()`）都会经 `_get_pool()` **重建**一条池，`os._exit(0)` 紧随其后
    把它孤儿掉 —— 退出通路重造它存在要防的那个泄漏。窗口按 `shutdown.py` 模块头的实测
    口径是 `_EXIT_DELAY_SECONDS` + 两次有界 join（~0.15s+1s），最坏由
    `PRAGMA busy_timeout=30000`（`apps/common/memory/db_pragmas.py:14`）撑到 30 s，
    而 Electron 5 s 就强杀。评审 2026-10-30 的证明形状：截住 `ProcessPoolExecutor`
    构造器，那次调用之后一条 `executor_available()` 就造出新池。本用例以记账替身
    重放这个形状。
    """

    def test_no_pool_is_rebuilt_after_the_exit_shutdown(self):
        """红证据（TDD）：2026-10-30 实现前先跑，`executor_available()` 返回 True 且
        替身被构造（前两条断言红，见 fixround 日志 `fix1_red.log`）。
        变异：`shutdown_pools_for_exit` 不置 `_pool_failed` ⇒ 这里红（就是未修形状本身）。
        """
        built = []

        class _RebuiltPool:
            """只够 `_get_pool()` 走通的最小替身：构造一次记一次。"""

            def __init__(self, *args, **kwargs):
                built.append(self)

            def submit(self, entry, *args, **kwargs):
                future = Future()
                future.set_running_or_notify_cancel()
                return future

            def shutdown(self, *args, **kwargs):
                pass

        with mock.patch.object(executor, 'ProcessPoolExecutor', _RebuiltPool), \
                mock.patch.object(executor, '_pool', None), \
                mock.patch.object(executor, '_download_pool', None), \
                mock.patch.object(executor, '_pool_failed', False), \
                mock.patch.dict(executor._in_flight, {}, clear=True):
            executor.shutdown_pools_for_exit()
            self.assertFalse(
                executor.executor_available(),
                '退出调用之后「能不能建池」又翻回 True ⇒ 还在被服务的请求会在退出'
                '窗口里重建池，`os._exit(0)` 把它孤儿掉（Fix 1 的 bug 本体）')
            self.assertEqual(built, [],
                             f'退出窗口里重建了 {len(built)} 条新池 ⇒ 孤儿又多了 {len(built)} 份')
            self.assertTrue(executor._pool_failed,
                            'Fix 1 口径：退出判定要走 `_pool_failed`（永久降级），不是只摘全局')


class RunnerChainProbeTests(SimpleTestCase):
    """Fix 2 前提的**运行时**证明：看门狗拆进 `apps/jobs/monitor.py` 之后，
    spawn 子进程 import 的 `apps/jobs/runner.py` 链路没有被拆分污染。

    两条断言各管一害：
    * 返回码 0 —— 链路在无 `django.setup()` 的子进程里照样 import 得起来。这条才是
      「monitor（它 import models，和 executor 一样）滑进 worker 闭包」的第一现场判据：
      模型类创建没配好的 Django 会当场炸（ImproperlyConfigured/AppRegistryNotReady），
      返回码非零即红。
    * `sys.modules` 里没有 `apps.jobs.executor`/`apps.jobs.monitor` —— 精确指名「这次
      拆分没给闭包添任何新东西」的双保险（按 norm_ppf 先例查 sys.modules）。
    注意 runner 链路**本来**就带 `django.conf` 这类 import-无害的模块（本机实测，
    2026-10-30：`django`, `django.conf`, `django.utils…` 在场而 `django.apps` 不在）——
    「django 模块数恒零」对 `distributions` 那条成立（`test_norm_ppf_memo.py:471-488`），
    对 runner 从来不成立，所以这里不把那条更强口径硬搬过来当判据。
    形状先例：`apps/jobs/tests_jobs.py::_worker_probe` —— 刻意清空
    `DJANGO_SETTINGS_MODULE`（继承过去子进程会悄悄 setup 出 Django，判据永远假绿）。
    """

    _ROOT = pathlib.Path(executor.__file__).resolve().parents[2]

    def test_runner_imports_without_django_after_the_monitor_split(self):
        env = dict(os.environ)
        env.pop('DJANGO_SETTINGS_MODULE', None)
        proc = subprocess.run(
            [sys.executable, '-X', 'utf8', '-c',
             'import sys; import apps.jobs.runner;'
             ' print("executor" if "apps.jobs.executor" in sys.modules else "-executor",'
             ' "monitor" if "apps.jobs.monitor" in sys.modules else "-monitor")'],
            cwd=str(self._ROOT), capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=180, env=env)
        self.assertEqual(proc.returncode, 0,
                         f'runner 链路在无 Django 的子进程里 import 失败（monitor 滑进闭包'
                         f'就是这一害的形状）：\n{proc.stderr[-1500:]}')
        self.assertEqual(proc.stdout.strip(), '-executor -monitor',
                         f'worker 闭包被拆分污染：{proc.stdout.strip()}')
