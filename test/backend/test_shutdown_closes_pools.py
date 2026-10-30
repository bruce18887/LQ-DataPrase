"""Task C3 判据（shutdown 侧）：优雅退出关掉两条池，且**先替被取消的作业落终态**再关。

上游：`docs/superpowers/plans/2026-10-28-backend-perf-remediation.md` Task C3。
道具在 `test/backend/shutdown_pool_fixtures.py`（两份判据共用，拆文件的原因是 600 行绊线）；
`executor.shutdown_pools_for_exit()` 自己的判据与两条运行时 import 探针在同族文件
`test/backend/test_exit_pool_shutdown.py`。

`shutdown._cleanup()` 原本只做两件事（关 DB 连接、刷日志），而 `_exit_now` 紧接着
`os._exit(0)` —— 绕过 atexit，也绕过 `concurrent.futures` 自己那个「解释器退出时收
子进程」的 `_python_exit`。于是 `apps/jobs/executor.py` 的两条池（进程池 + 下载线程池）
在退出路径上**从来没有关闭调用点**，POSIX 侧留下孤儿子进程。

计划稿那句「Windows 有 job object 兜底」**仓内无依据**（2026-10-30 复核
`grep -rn --include=*.py --include=*.ts "Job[O]bject" apps config standalone.py test electron`
⇒ 零命中；上一版记录的那条缺 `electron/`，而那正是主张唯一可能的栖身处，`--include=*.ts`
在没有 electron 的范围里是惰性的 —— 补范围重跑后才与结论相称。方括号让这行文本不被自己
命中，`--include` 让陈旧 `.pyc` 不替它作证，口径与出处只写在
`apps/common/shutdown.py` 模块头一处）。所以两档都得修。本文件断的是**调用序列与终态
归属**，与平台无关 —— 子进程数那一侧由 Linux 侧取证测过（三档 arms、n=10、幸存者用
`kill -0` 探；量数、结论与重建配方在
`docs/reference/c3-exit-pool-orphan-forensics-2026-10-29.md`，这里不重复，
也不充当判据：判据必须能在任何机器上跑出红或绿）。

七组承重，**每条测试的 docstring 里写明它抓哪一个变异**（跑批记录与还原核对见提交说明，
不在这里当判据）：

1. `_cleanup` 里确有关池那一步，参数 `wait=False, cancel_futures=True`，且**恰好一次**
   （连着调两次也一样；「一次」由 `Shutting down (…)` INFO 行恰好一条钉住 `_shutdown_started`，
   「绕过标志也不重复」由摘空的全局钉住 —— 2026-10-30 评审前这两层混在一个说法里）。
2. 那一步在 `_close_database_connections()` **之前**（里面的收尸要写库），也在
   `_flush_output()` 之前 —— 顺序由**记录的调用序列**证明。为什么不能用「功能测试」证明
   这个顺序：Django 在连接关掉后会透明重连，功能上换了顺序一样落得了终态，所以承重的
   是序列本身。
3. best-effort：池抛错 / 收尸抛错 / `shutdown_pools_for_exit` 整体炸 / `apps.jobs.executor`
   根本 import 不来 / 管理线程 `join()` 自己炸 —— 都不许改变退出通路或退出码
   （`_exit_now` 仍 `os._exit(0)`），join 炸还不许把后面的线程跳过去。
4. 关池前先 `_reap_discarded`（C1 立的终态归属不变量；判据在兄弟模块）。
5. 管理线程（真池 `ProcessPoolExecutor._executor_manager_thread`，推哨兵的那个）必须在
   `shutdown()` **之前**捕获、之后**有界** join —— 哨兵是那个线程推的，而 `shutdown()`
   自己把引用置成 None（本机 CPython 3.13.12 `concurrent/futures/process.py:854`），
   「事后再抓」根本抓不到。这一组的对照面是「只调 shutdown 不 join」：仓内功能测试**测不出**
   它（假池没有真子进程），能测出它的只有上面那次 Linux 取证，所以这里钉的是**形状与上界**，
   不钉「子进程数」。
6. 那个**私有属性依赖**本身要有 pin（Fix 3）：真池里它就是 `threading.Thread`、
   `ThreadPoolExecutor` 压根没有它 —— 前者红了说明 CPython 改了名，后者的缺席是
   「捕获只可能捕到进程池线程」的依据。改名的场合要**出声**（loud WARNING），
   静默退化等于「4 个孤儿、零告警」。
7. 双保险：`_pool_manager_threads` 的捕获失败不许带走关池（capture 的 try/except）。

跑法：`python -X utf8 manage.py test test.backend.test_shutdown_closes_pools`
"""

import multiprocessing
import os
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.common import shutdown
from apps.jobs import executor
from test.backend.job_cancel_fixtures import FakePool
from test.backend.shutdown_pool_fixtures import CountingPool, RecordingManagerThread

# Electron 的强杀窗口：`electron/backend.ts:486` 那个 `}, 5000)`（POST shutdown →
# SIGTERM → 5s 后 `taskkill /F`）。关池步自己花掉的时间必须明显小于它，否则「优雅退出」
# 每次都断在强杀上，清理等于没做。
_FORCE_KILL_WINDOW_SECONDS = 5.0
# 单个管理线程 join 的上界口径（和 `shutdown._POOL_MANAGER_JOIN_SECONDS` 一起钉住）。
_JOIN_BOUND_SECONDS = 0.5


class CleanupPoolStepTests(TestCase):
    """`_cleanup` 侧：关池这一步存在、参数对、位置对、坏了也不改退出通路。"""

    def setUp(self):
        # 模块级单次标志：上一个用例置过就得复位，否则本用例的清理整段被跳过。
        shutdown._shutdown_started = False
        self.addCleanup(setattr, shutdown, '_shutdown_started', False)
        # Fix 1 后 `_cleanup` 会经 `shutdown_pools_for_exit` 置 `_pool_failed`，
        # 用例离场必须归还（reset_for_tests 正是这条既有通路），否则污染后续模块的
        # `executor_available()`。
        self.addCleanup(executor.reset_for_tests)
        self.sequence = []

    def _pool(self, label, **kwargs):
        return CountingPool(capacity=0, label=label, box=self.sequence, **kwargs)

    def _bind(self, proc, down):
        """换掉两条池并清空在飞表 ⇒ 本类不写库（`_reap_discarded` 按 `_Flight.pool`
        认领，名单为空就是纯 no-op）。"""
        for target, value in (('_pool', proc), ('_download_pool', down)):
            patcher = mock.patch.object(executor, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        emptier = mock.patch.dict(executor._in_flight, {}, clear=True)
        emptier.start()
        self.addCleanup(emptier.stop)
        return proc, down

    def _record_later_steps(self):
        """把后两步换成记账（不真关连接、不真刷日志 —— 那两步不是本任务的判据）。"""
        return (mock.patch.object(shutdown, '_close_database_connections',
                                  lambda: self.sequence.append('db-close')),
                mock.patch.object(shutdown, '_flush_output',
                                  lambda: self.sequence.append('flush')))

    # ------------------------------------------------------------------
    # 1. 存在 + 参数 + 恰好一次
    # ------------------------------------------------------------------
    def test_cleanup_shuts_down_both_pools_once_with_cancel_futures(self):
        """两条池各被 `shutdown(wait=False, cancel_futures=True)` 打到**恰好一次**。

        `wait=False` 是硬要求：Windows 上 `wait=True` 会让退出等一条还在跑的导出
        （用户看到的就是「点了退出，窗口十几分钟不走」）。
        变异：删掉 `_cleanup` 里的这一步 ⇒ 这里两个 `calls` 都是 `[]`。
        """
        proc, down = self._bind(self._pool('pool:process'), self._pool('pool:download'))

        shutdown._cleanup('unit')

        self.assertEqual(proc.calls, [(False, True)],
                         f'进程池没被按口径关掉：{proc.calls}')
        self.assertEqual(down.calls, [(False, True)],
                         f'下载线程池没被按口径关掉：{down.calls}')

    # ------------------------------------------------------------------
    # 2. 位置：在关连接之前（收尸要写库）
    # ------------------------------------------------------------------
    def test_the_pool_step_runs_before_the_database_close(self):
        """变异：把这一步挪到 `_close_database_connections()` 之后 ⇒ 序列变
        `['db-close', 'pool:process', ...]`，这里红。"""
        proc, down = self._bind(self._pool('pool:process'), self._pool('pool:download'))
        close_db, flush = self._record_later_steps()

        with close_db, flush:
            shutdown._cleanup('unit')

        self.assertEqual(self.sequence,
                         ['pool:process', 'pool:download', 'db-close', 'flush'],
                         f'退出步骤顺序变了：{self.sequence}')
        self.assertEqual(proc.calls, [(False, True)])
        self.assertEqual(down.calls, [(False, True)])

    # ------------------------------------------------------------------
    # 3. 位置：在刷日志之前，且后一步炸了也不拖累它
    # ------------------------------------------------------------------
    def test_pools_still_close_when_flush_output_raises(self):
        """`_flush_output` 自己把异常吞了（那是它的既有设计，本任务不改），所以要整体
        换掉它才能造出「后面的步骤炸了」。承重的是：**池已经关完了**，异常从 `_cleanup`
        冒出去也不影响这一事实（`_cleanup` 从来没给 `_flush_output` 加守卫，这里记录
        现状而不是新要求）。
        变异：把关池挪到 `_flush_output()` 之后 ⇒ 两个 `calls` 都还是 `[]`。
        """
        proc, down = self._bind(self._pool('pool:process'), self._pool('pool:download'))

        def boom():
            raise RuntimeError('flush blew up')

        with mock.patch.object(shutdown, '_flush_output', boom), \
                mock.patch.object(shutdown, '_close_database_connections', lambda: None):
            with self.assertRaises(RuntimeError):
                shutdown._cleanup('unit')

        self.assertEqual(proc.calls, [(False, True)], '后一步抛错就不关池了')
        self.assertEqual(down.calls, [(False, True)], '后一步抛错就不关池了')

    # ------------------------------------------------------------------
    # 4. best-effort：不许改变退出通路 / 退出码
    # ------------------------------------------------------------------
    def test_a_raising_pool_changes_neither_the_exit_path_nor_the_code(self):
        """走**真退出通路** `_exit_now`（`_cleanup` + `os._exit(0)`），进程池故意抛。

        变异：拆掉关池外层的 try/except ⇒ `RuntimeError` 从 `_exit_now` 冒出来，
        `os._exit` 一次都没被调用（= 退出码/通路被改掉），这里红。
        """
        proc, down = self._bind(self._pool('pool:process', raise_on_shutdown=True),
                                self._pool('pool:download'))
        close_db, flush = self._record_later_steps()

        with close_db, flush, mock.patch.object(shutdown.os, '_exit') as exit_call:
            shutdown._exit_now('unit')

        self.assertEqual(exit_call.call_args_list, [mock.call(0)],
                         '关池失败改掉了退出通路（`os._exit(0)` 没被执行）')
        self.assertEqual(down.calls, [(False, True)],
                         '一条池抛错就把另一条池扔下了')
        self.assertEqual(self.sequence[-2:], ['db-close', 'flush'],
                         f'清理被一条坏池截断：{self.sequence}')

    def test_an_exploding_exit_step_stays_inside_the_cleanup(self):
        """上那条只覆盖「某条池的 `shutdown()` 抛」；这一条覆盖**整个** exit step 抛出来
        的场合（收尸撞上没迁移的库、`_get_pool` 之外的代码坏了……）。外层那道
        try/except 就是为这一格存在的：它一不许把 `_close_database_connections()` 与
        `_flush_output()` 带走，二不许改变退出码。
        变异：拆掉 `_close_job_pools` 里包住 `shutdown_pools_for_exit()` 的那道 try ⇒
        `RuntimeError` 从 `_cleanup` 冒出来，这里红。
        """
        self._bind(self._pool('pool:process'), self._pool('pool:download'))
        close_db, flush = self._record_later_steps()
        bomb = mock.patch.object(executor, 'shutdown_pools_for_exit',
                                 side_effect=RuntimeError('the exit step exploded'))

        with bomb, close_db, flush:
            shutdown._cleanup('unit')          # 不许抛

        self.assertEqual(self.sequence, ['db-close', 'flush'],
                         f'退出步骤被一个炸掉的关池截断：{self.sequence}')

    def test_a_missing_executor_module_is_skipped_not_fatal(self):
        """`apps.jobs.executor` 进不来（打包裁剪 / PyInstaller 缺件 / 装不进 app 的阶段）
        不是「退出失败」：静默跳过，后两步照跑。`sys.modules` 里放 `None` 就是标准库
        认的「这个模块不可导入」形状。实现用的是 `import apps.jobs.executor as m`，
        **不是** `from apps.jobs import m` —— 后者在包属性上直接命中已缓存的模块、不抛
        ImportError，这条判据就会变成假绿（2026-10-29 本机实测两种写法：前者
        `ModuleNotFoundError: ... halted; None in sys.modules`，后者照常返回模块对象）。
        变异：拆掉 import 外层的 try/except ⇒ `_cleanup` 抛 ImportError，这里红。
        """
        close_db, flush = self._record_later_steps()

        with mock.patch.dict(sys.modules, {'apps.jobs.executor': None}), close_db, flush:
            shutdown._cleanup('unit')

        self.assertEqual(self.sequence, ['db-close', 'flush'],
                         f'executor 缺席时退出被带偏：{self.sequence}')

    def test_a_join_that_raises_neither_escapes_nor_skips_the_remaining_threads(self):
        """Fix 5(b)：`thread.join()` 外面那道 try/except 与那句 load-bearing 的 `continue`
        此前**没有任何用例钉过**（评审 2026-10-29 变异：整段删掉 ⇒ 全部用例照绿，而同族
        「清理不许抛」的另外两支都有判据）。这一条直接喂 `_close_pools_and_join_managers`
        一个两条线程的名单：第一条炸，不许把异常扔出去、不许跳过后一条、也不许炸完了
        还去问它的 `is_alive()`（`continue` 的作用 —— 炸过的线程状态不可信）。
        变异 A：删掉 try/except ⇒ RuntimeError 从这里冒出，这里红。
        变异 B：留着 except 删掉 `continue` ⇒ 「still running」告警被记进日志（替身
        故意 `alive_after_join=True`），下面那条 assertFalse 红。
        """
        box = []
        bad = RecordingManagerThread('join:bad', box, raise_on_join=True,
                                     alive_after_join=True)
        good = RecordingManagerThread('join:good', box)
        jobs_executor = mock.Mock()

        with self.assertLogs('apps.common.shutdown', level='WARNING') as captured:
            shutdown._close_pools_and_join_managers(jobs_executor, [bad, good])  # 不许抛

        self.assertEqual(bad.joins, [shutdown._POOL_MANAGER_JOIN_SECONDS],
                         'join 压根没被尝试')
        self.assertEqual(good.joins, [shutdown._POOL_MANAGER_JOIN_SECONDS],
                         '第一条炸就跳过了后面的线程')
        self.assertEqual(box, ['join:good'], f'时刻记号不对：{box}')
        self.assertTrue(any('manager thread' in line for line in captured.output),
                        f'join 炸了却没留痕：{captured.output}')
        self.assertFalse(any('still running' in line for line in captured.output),
                         'join 炸完还去轮询 is_alive ⇒ `continue` 被删了')
        jobs_executor.shutdown_pools_for_exit.assert_called_once_with()

    def test_a_raising_join_still_reaches_the_hard_exit(self):
        """完整退出通路：`_exit_now` 经过一条 join 就炸的管理线程 ⇒ `os._exit(0)` 照到。
        与 `test_a_raising_pool…`（池关不掉）、`test_an_exploding_exit_step…`（exit step
        整体炸）凑齐「清理三处失效都不许改掉退出码」。
        变异：删掉 join 的 try/except ⇒ RuntimeError 穿 `_cleanup`，`os._exit` 没被调，红。
        """
        thread = RecordingManagerThread('join:process', self.sequence,
                                        raise_on_join=True)
        proc = self._pool('pool:process', manager_thread=thread)
        self._bind(proc, self._pool('pool:download'))
        close_db, flush = self._record_later_steps()

        with close_db, flush, mock.patch.object(shutdown.os, '_exit') as exit_call:
            shutdown._exit_now('unit')

        self.assertEqual(exit_call.call_args_list, [mock.call(0)],
                         'join 炸掉改掉了退出通路（`os._exit(0)` 没被执行）')
        self.assertEqual(thread.joins, [shutdown._POOL_MANAGER_JOIN_SECONDS])
        self.assertEqual(self.sequence[-2:], ['db-close', 'flush'],
                         f'清理被一次 join 失败截断：{self.sequence}')

    def test_a_failing_capture_still_closes_the_pools(self):
        """承重之 7：`_pool_manager_threads` 自己抛（替身对象换了形状、CPython 半成品
        升级……）时捕获被 try/except 兜成空名单，**关池照做** —— 一次捕获失败不许把
        关池一起带走（关池才是防孤儿的正题，捕获只是它的加强件）。
        变异：删掉捕获外层的 try/except ⇒ RuntimeError 从 `_cleanup` 穿出，两个
        `calls` 都是 `[]`，这里红。
        """
        proc, down = self._bind(self._pool('pool:process'), self._pool('pool:download'))
        close_db, flush = self._record_later_steps()
        bomb = mock.patch.object(shutdown, '_pool_manager_threads',
                                 side_effect=RuntimeError('capture broke'))

        with bomb, close_db, flush:
            shutdown._cleanup('unit')          # 不许抛

        self.assertEqual(proc.calls, [(False, True)], '捕获失败把关池一起跳过了')
        self.assertEqual(down.calls, [(False, True)], '捕获失败把关池一起跳过了')

    # ------------------------------------------------------------------
    # 5. 管理线程：提前捕获、有界 join
    # ------------------------------------------------------------------
    def test_the_manager_thread_is_captured_before_shutdown_and_joined_once(self):
        """管理线程：`shutdown()` **之前**捕获，**之后**有界 join 一次，且排在关连接之前。

        为什么必须是「之前」：哨兵（让 child 自己退出的那个 `None`）是**那个管理线程**推的，
        而 `shutdown()` 在返回前把 `self._executor_manager_thread` 置成 None —— 「事后
        getattr」拿到的是 None，于是一次 join 都不会发生，孤儿子进程照旧留下，而功能测试
        一点也看不出来（假池没有真子进程）。所以替身照抄 CPython 那一手（见 `CountingPool`）。
        下载 lane **不挂**管理线程替身（2026-10-30 评审修正）：真 `ThreadPoolExecutor`
        没有那个属性（`ManagerThreadAttributePinTests` 钉），上一版喂它一条线程等于让
        判据去断言「把循环简化成只走 `_pool`」是错的 —— 那是生产造不出来的形状。
        变异 A：删掉 join 那几行 ⇒ `joins == []`，这里红（Linux 取证里同一形状
        「只 shutdown 不 join」10 次里 8 次把 4 个 child 全留下、2 次靠调度器碰巧收回，
        加上 join 后 10/10 次一个不剩 —— 见取证文档）。
        变异 B：把捕获挪到 `shutdown_pools_for_exit()` 之后 ⇒ 拿到 None，同样 `joins == []`。
        """
        proc_thread = RecordingManagerThread('join:process', self.sequence)
        proc = self._pool('pool:process', manager_thread=proc_thread)
        down = self._pool('pool:download')
        self._bind(proc, down)
        close_db, flush = self._record_later_steps()

        with close_db, flush:
            shutdown._cleanup('unit')

        self.assertIsNone(proc._executor_manager_thread,
                         '替身没照真池那样在 shutdown 后把管理线程引用置 None ⇒ '
                         '下面那条 join 就不再证明「只能提前捕获」')
        self.assertEqual(proc_thread.joins, [shutdown._POOL_MANAGER_JOIN_SECONDS],
                         f'进程池的管理线程没被 join（或 join 口径不对）：{proc_thread.joins}')
        self.assertEqual(self.sequence,
                         ['pool:process', 'pool:download',
                          'join:process', 'db-close', 'flush'],
                         f'关池这五件事的相对顺序变了：{self.sequence}')

    def test_the_manager_join_timeout_is_bounded_inside_the_force_kill_window(self):
        """join 必须**带超时**，且整个关池步的最坏耗时落在 Electron 强杀窗口之内。

        `Thread.join()` 不带参数就是「等到线程结束为止」，而真池的管理线程在推完哨兵后会
        逐个 `p.join()` 等 child 退出（3.13.12 `process.py:565-568`）—— 一条还在跑导出的
        child 能把退出堵在原地几十分钟，运维看到的正是「点了退出，窗口不走」，然后被
        `taskkill /F` 断在半路（连 WAL checkpoint 都省了）。
        最坏情况按**测到的 join 超时**算（两条池各等满 + HTTP 通路的 flush 延迟），且排在
        上界那条之前 —— 用常量算它被 `≤0.5` 数学吞掉（0.15+1.0=1.15 < 5，永远不先红，
        2026-10-30 评审指出），按实测值算才可达。
        变异：把 `join(_POOL_MANAGER_JOIN_SECONDS)` 写成裸 `join()` ⇒ `joins[0]` 是 None，
        这里红；把常量抬到 30 ⇒ 最坏情况这条先红（60.15s ≥ 5s，运维口径的报错），
        上界那条是第二道 pin。
        """
        thread = RecordingManagerThread('join:process', self.sequence)
        proc = self._pool('pool:process', manager_thread=thread)
        self._bind(proc, self._pool('pool:download'))
        close_db, flush = self._record_later_steps()

        with close_db, flush:
            shutdown._cleanup('unit')

        self.assertEqual(len(thread.joins), 1, f'join 次数不对：{thread.joins}')
        bounded = thread.joins[0]
        self.assertIsNotNone(bounded,
                             'join 没带超时 ⇒ 退出可能堵在一条还在跑活的 child 上')
        worst_case = shutdown._EXIT_DELAY_SECONDS + 2 * bounded
        self.assertLess(worst_case, _FORCE_KILL_WINDOW_SECONDS,
                        f'关池步最坏 {worst_case}s，已经吃掉强杀窗口 {_FORCE_KILL_WINDOW_SECONDS}s')
        self.assertLessEqual(bounded, _JOIN_BOUND_SECONDS,
                             f'join 上界 {bounded}s 超过 {_JOIN_BOUND_SECONDS}s')

    def test_a_manager_thread_that_outstays_the_join_says_so_in_the_log(self):
        """join 到点而线程还活着（child 还在跑活）时**必须留一句日志** —— 那是运维唯一
        看得到的表面（Electron 把 stdout/日志管道到 `userData/logs`），也是「这次退出为什么
        还留着 N 个子进程」唯一的可归因线索。
        变异：去掉 `is_alive()` 那条告警 ⇒ 这里红（`assertLogs` 什么都没捕到）。
        """
        thread = RecordingManagerThread('join:process', self.sequence, alive_after_join=True)
        self._bind(self._pool('pool:process', manager_thread=thread),
                   self._pool('pool:download'))

        with self.assertLogs('apps.common.shutdown', level='WARNING') as captured:
            shutdown._close_job_pools()

        self.assertTrue(any('manager thread' in line for line in captured.output),
                        f'有界 join 超时却没有告警：{captured.output}')

    def test_a_second_call_closes_and_joins_each_pool_exactly_once(self):
        """双调安全，**两层分开各钉各的**（2026-10-30 评审修正：上一版把整条行为都记在
        `_shutdown_started` 名下，而评审实际删掉那个标志后全部用例照绿 —— 当时 no-op 的
        唯一凭据是摘空的全局，标志本身零判据）：

        * 连着两次 `_cleanup` 只清理一遍 ⇒ 凭据是 `Shutting down (…)` INFO 行**恰好一条**
          （变异：删 `_shutdown_started` 短路 ⇒ 两条 ⇒ 这里红）。
        * **绕过**标志直接连调 `_close_job_pools` 也是 no-op ⇒ 凭据是第一次已把
          `executor._pool`/`_download_pool` 摘成 None（变异：`shutdown_pools_for_exit`
          不再置 None ⇒ `calls`/`joins` 变两条）。
        """
        thread = RecordingManagerThread('join:process', self.sequence)
        proc = self._pool('pool:process', manager_thread=thread)
        down = self._pool('pool:download')
        self._bind(proc, down)
        close_db, flush = self._record_later_steps()

        with close_db, flush, \
                self.assertLogs('apps.common.shutdown', level='INFO') as infos:
            shutdown._cleanup('unit')
            shutdown._cleanup('unit')          # 被单次标志挡住

        starts = [line for line in infos.output if 'Shutting down' in line]
        self.assertEqual(len(starts), 1,
                         f'两次 _cleanup 让清理启动行出现了 {len(starts)} 次 ⇒ '
                         f'`_shutdown_started` 短路失效（这条曾经无人钉）：{starts}')
        self.assertEqual(proc.calls, [(False, True)], f'两次 _cleanup 关了不止一遍：{proc.calls}')
        self.assertEqual(down.calls, [(False, True)], f'两次 _cleanup 关了不止一遍：{down.calls}')
        self.assertEqual(thread.joins, [shutdown._POOL_MANAGER_JOIN_SECONDS],
                         f'两次 _cleanup join 了不止一遍：{thread.joins}')

        shutdown._close_job_pools()            # 绕过单次标志，直接再关两遍
        shutdown._close_job_pools()

        self.assertEqual(proc.calls, [(False, True)], '关池步不是幂等的')
        self.assertEqual(down.calls, [(False, True)], '关池步不是幂等的')
        self.assertEqual(thread.joins, [shutdown._POOL_MANAGER_JOIN_SECONDS],
                         '管理线程被重复 join')


class ManagerThreadAttributePinTests(SimpleTestCase):
    """Fix 3：`shutdown.py::_pool_manager_threads` 伸手进私有属性
    `_executor_manager_thread` 这件事，依赖本身要 pin（真池形状的判据先例：
    `test_job_cancel.py::RealPoolQueueWindowTests`、`test_job_terminal_ownership.py::
    RealPoolDiscardTests`、`apps/jobs/tests_jobs.py:603` 的 `RealPoolEndToEndTests`）。
    CPython 哪天改名：`threads` 恒空、join 循环跑零次、日志**一句都不留** ——
    「4 个孤儿、没有告警」，修复会静默停止作为修复。这两条就是让改名必须见红。
    """

    def test_real_process_pool_exposes_a_manager_thread_after_submit(self):
        """真 spawn 池（本机 CPython 3.13.12，取法 `python -V`；评审机 3.12.3 同形状）：
        首次 submit 后 `_executor_manager_thread` 必须存在且是 `threading.Thread`。
        注意它是**懒启动**的 —— 构造完属性值是 None（本机实测），所以先 submit 一条
        顶层可 pickle 的函数（`os.getpid`）把线程真正带起来，再读属性。
        变异（跨版本）：CPython 改名 ⇒ 属性缺席，这里红；哪天不再懒启动，红不了 ——
        本条只钉「存在 + 类型」这两个消费面。
        """
        pool = ProcessPoolExecutor(max_workers=1,
                                   mp_context=multiprocessing.get_context('spawn'))
        self.addCleanup(lambda: pool.shutdown(wait=True))
        future = pool.submit(os.getpid)
        self.assertIsInstance(future.result(timeout=120), int)

        thread = getattr(pool, '_executor_manager_thread', None)
        self.assertIsNotNone(thread,
                             '真池 submit 之后没有 `_executor_manager_thread` ⇒ '
                             'CPython 改了名或被改成懒对象，`_pool_manager_threads` 的'
                             '捕获会静默拿到空名单')
        self.assertIsInstance(thread, threading.Thread,
                              f'那个属性不再是线程对象而是 {type(thread)!r}')
        pool.shutdown(wait=True)      # 哨兵通路本身也要走得通：线程会自己收干净

    def test_thread_pool_executor_has_no_such_attribute(self):
        """下载 lane 的依据面：`ThreadPoolExecutor` **没有** `_executor_manager_thread`
        （本机 3.13.12 测；评审机 3.12.3 同）。这条是两处取向的凭据：捕获循环在生产里
        最多捕到进程池那一条；改名告警只许对进程 lane 响（`PoolRenameAlarmTests` 的
        对照组），否则每次正常退出都白响一声。
        """
        pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(lambda: pool.shutdown(wait=False))
        self.assertFalse(hasattr(pool, '_executor_manager_thread'),
                         '线程池哪天也有了那个私有属性 ⇒ `_pool_manager_threads` 的'
                         '「返回进程池线程或什么都没有」口径与告警豁免一起要重读')


class PoolRenameAlarmTests(TestCase):
    """Fix 3 的出声半边：池在而管理线程捕不到 ⇒ loud WARNING。

    只点进程 lane：`ThreadPoolExecutor` 压根没有那个属性（上面刚钉），下载池在场时
    每次都误报等于把信号稀释成噪音。
    """

    def setUp(self):
        self.addCleanup(executor.reset_for_tests)   # Fix 1 后置的 `_pool_failed` 要归还

    def _bind_quiet(self, proc, down):
        for target, value in (('_pool', proc), ('_download_pool', down)):
            patcher = mock.patch.object(executor, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        emptier = mock.patch.dict(executor._in_flight, {}, clear=True)
        emptier.start()
        self.addCleanup(emptier.stop)

    def test_a_process_pool_exposing_no_manager_thread_says_so(self):
        """属性被改名（对象上压根没有它）的场合：`_pool` 在场却捕不到线程 ⇒ 必须响。
        红证据（TDD）：2026-10-30 本条先写、实现未加告警时跑红（`assertLogs` 捕不到
        任何东西），加告警后转绿。
        变异：删掉 `_pool_manager_threads` 的告警分支 ⇒ `assertLogs` 什么都没捕到，这里红。
        """
        proc = FakePool()          # FakePool 压根没有该属性 —— 正是「被改名」的形状
        self._bind_quiet(proc, None)

        with self.assertLogs('apps.common.shutdown', level='WARNING') as captured:
            shutdown._close_job_pools()

        self.assertTrue(any('_executor_manager_thread' in line for line in captured.output),
                        f'捕不到管理线程却不吭声（静默退化就是 4 孤儿零告警）：'
                        f'{captured.output}')

    def test_the_download_lane_alone_never_triggers_the_rename_alarm(self):
        """对照组（哨兵判据必须带的「别把正常路径一起废掉」）：只有下载池在场
        （生产的 thread lane 真实形状：`ThreadPoolExecutor` 压根没有那个属性，用不带
        它的 `FakePool` 照形）⇒ 必须**静默**，关池照做。
        变异：把告警条件从「仅进程 lane」放宽到两条 lane ⇒ `assertNoLogs` 红。
        """
        down = FakePool()
        self._bind_quiet(None, down)

        with self.assertNoLogs('apps.common.shutdown', level='WARNING'):
            shutdown._close_job_pools()

        self.assertEqual(down.shut_down, (False, True), '对照组把关池本身也跳过了')
