# C3 退出关池取证：三档孤儿测量与可重建配方（2026-10-29，WSL2/CPython 3.12.3）

这是 `apps/common/shutdown.py` 退出路径「关池 + 提前捕获管理线程 + 有界 join」那一步的
**取证记录**。模块头只留结论、残留、join 依据与本文件指针；量数、逐档结果、逐版本源码
引文与重建配方在本文件。判据（能在任何机器上跑红/绿的仓内断言）在
`test/backend/test_shutdown_closes_pools.py` 与 `test/backend/test_exit_pool_shutdown.py` ——
本文件的测量本身**不是判据**：它是 Linux 侧的形状证据，仓内功能测试测不出「子进程数」
（假池没有真子进程）。

## 为什么要有这次测量

`_exit_now` 用 `os._exit(0)`：绕过 atexit，也就绕过 `concurrent.futures` 的
`_python_exit`。`apps/jobs/executor.py` 的进程池（spawn，4 worker）如果不在退出前
关闭并由其管理线程推哨兵，POSIX 侧留下孤儿 `spawn_main` 子进程。「Windows 有 job
object 兜底」的说法仓内无依据（复核命令与口径只写在 `shutdown.py` 模块头一处），
两档都得修。修形有三个候选：(a) 不加关池步、(b) 只 `shutdown(wait=False,
cancel_futures=True)`、(c) 先捕获管理线程 → shutdown → 有界 join。测的就是这三档。

## 测量环境与样本量

- 2026-10-29，WSL2 Ubuntu，`/usr/bin/python3` 自报 CPython 3.12.3（取法 `python3 -V`）。
  产品进程跑的是 Windows 本机 CPython 3.13.12（`python -V`，`D:\Program Files\Python\Python313`）——
  两版**形状一致、行号不同**，下文引文一律带版本。
- 4-worker spawn 池（与 executor 相同的 context），idle 档用 4 条并发 no-op 预热
  （必须**同时**提交再等：逐条等只会起活 1 个孩子），busy 档用 4 条 60 s sleep。
- 驱动跑了两遍（drive），每遍每档 5 次 ⇒ **每档 n=10**。

## 三档结果

| 档 | 形状 | idle 结果 | busy 结果 |
|---|---|---|---|
| (a) | 无关池步（C3 之前的对照） | 4 个孩子全留，10/10 | 4 全留，10/10 |
| (b) | `shutdown(wait=False, cancel_futures=True)` 后**立刻** `os._exit(0)`（C3 修复前 shipped 的形状） | 4 全留 **8/10**；2 次被收回 | 4 全留，10/10 |
| (c) | 捕获 → 同样的 shutdown → `join(0.5)` → `os._exit(0)`（现形） | **0 幸存，10/10**，首个探针即已消失，线程自报 `qsize=0 pending=0`（哨兵已推且被取走） | 4 全留，10/10；线程自报 `qsize=0 pending=4` |

读法：

* (b) 不是「从不工作」，是「调度器碰巧在 `os._exit` 前跑了管理线程才工作」——
  退出路径不许依赖这个，所以 join 不是装饰。
* busy 档的残留位置在源码里可对账：`pending_work_items` 非空时管理线程的循环**推迟**
  `shutdown_workers()`（3.13.12 `process.py:378`），哨兵一个都没推；就算推了，worker
  也只在**条目之间**回读 call queue（3.12.3 `:251`，3.13.12 `:242`），正在跑的活照旧
  不受退出控制。第三种丢失模式（`shutdown_workers` 用 `put_nowait`，队列满即 `break`，
  3.13.12 `:540-547`）在这两遍里**没有复现**（arms 队列是空的），堵它需要显式
  `terminate()` 遍历捕获的 `_processes` —— 独立决策，本批未做。
* 收尸（`_reap_discarded`）对 busy 作业的保证比「行是终态」窄，且缺口是一个**事务**
  问题不是竞态：收尸的 UPDATE 跑在 autocommit，而这些 handler 只装在
  `standalone.py:194`——一个从不把它们包进 `transaction.atomic()` 的进程（任何 profile
  都没开 `ATOMIC_REQUESTS`）。哪天把 handler 挪进一个开着的原子块，它的回滚会把这条
  写回滚掉，行永远停在 `running`。半截产物文件留给 `prune_jobs`，它的 docstring 自己
  说清了对那个窗口也不是全覆盖。

## 源码形状：捕获为什么必须早于 shutdown（逐版本引文）

3.12.3 与 3.13.12 的 `concurrent/futures/process.py` 行号**不同**，此前一版把
「哨兵推送」段写成「both versions `:535-547`, reached via `:556`」—— 对 3.12.3 是错的
（那里 `:535-547` 是 `flag_executor_shutting_down`）。2026-10-30 按本机/评审机实测拆开：

| 形状 | 3.12.3（WSL2 `/usr/bin/python3`） | 3.13.12（本机，`D:\Program Files\Python\Python313`） |
|---|---|---|
| `shutdown()` 只置标志、唤醒管理线程 | `:864-870` | `:842-848` |
| 推 `None` 哨兵的 `shutdown_workers()` | `:560-572`，由 `:581` 到达 | `:535-547`，由 `:556` 到达 |
| `shutdown()` 置空线程引用（事后 getattr 恒 None） | `:876` | `:854` |
| 循环在有在飞项时推迟 `shutdown_workers()` | ——（形状相同） | `:378` |
| worker 只在条目之间回读 call queue | `:251` | `:242` |
| `put_nowait` 哨兵、`queue.Full` 即 break | ——（未复现） | `:540-547` |
| join 上界的依据：线程推完哨兵后逐个 `p.join()` 等 child | —— | `:556` 然后 `:565-568` |

3.13.12 那一列 2026-10-29/30 在本机源码树逐条对过；3.12.3 那一列在 WSL2 实测。
换版本先重查，别复用行号。

## 重建配方（不依赖任何日志文件）

测量脚本 `tasks/c3_orphan_probe.py`（186 行）是**一次性临时件**且 `tasks/` 整目录被
`.gitignore:160` 排除 —— 它不在任何 clone 里存在，**本文件才是记录**。下面是把它
重建出来所需的全部坑（第一轮实测每个都踩过或防过）：

1. **PID 交接走文件，不走 stdout**：spawn 孩子继承父进程的 stdout 管道；孤儿孩子
   永远握着写端，驱动那句「读到 EOF」永远不返回 —— 第一轮就挂在这上面。arm 进程在
   `os._exit(0)` 前把 `pool._processes` 的 PID 写进约定文件（`PIDS p1 p2 p3 p4`）。
2. **每档一个 fresh 进程**，`subprocess.Popen([sys.executable, '-u', script, 'child',
   arm, pidfile], stdout=log, stderr=log, start_new_session=True)`：`start_new_session`
   让 arm 与驱动分属不同会话/进程组，超时 `proc.kill()` 杀掉的是 arm 自己，终端信号
   也不会串进测量。每档限时 150 s，超时按 TIMEOUT 记账。
3. **幸存判据是 `kill(pid, 0)`**，每 0.25 s 探一次、探到 arm 进程消失后 10 s 为止。
   分类：`ProcessLookupError` = 死了；**`PermissionError` = 活着**（进程存在、只是不
   归你信号 —— Windows 语义，POSIX 上 EPERM 同样按活算）。把它错判成死 = 测量
   自证清白，是这套配方最阴的一个坑。
4. **档间/轮间对幸存者补 `kill -9`**（「never leave sleepers behind」）：busy 档的
   60 s sleep 孩子如果跨档活着，下一档的探针读到的就是上一档的孤儿。
5. arm 内的退出形状与生产对齐：`getattr(pool, '_executor_manager_thread', None)`
   **先**捕获，`pool.shutdown(wait=False, cancel_futures=True)`，然后
   `thread.join(JOIN_TIMEOUT)`，`os._exit(0)`；`JOIN_TIMEOUT` 必须等于
   `apps/common/shutdown.py::_POOL_MANAGER_JOIN_SECONDS`（写死 0.5 会量到另一个形状）。
6. 第二遍 drive 额外读管理线程自己的账：`manager.call_queue.qsize()` 与
   `len(manager.pending_work_items)`，在退出前写进交接文件（`QSIZE qsize=… pending=…`）。
   管理线程握着 call queue 的引用不随 `shutdown()` 置空而消失，这两个数把
   「哨兵在队列里没人读」与「哨兵根本没入队」分开 —— busy 档的 `qsize=0 pending=4`
   就是这么来的。尽力而为：`_join_executor_internals` 可能已把队列关掉，读不到记
   `unreadable(ExcName)`。
7. 驱动输出：每次运行一行（rc / 孩子数 / 探针时幸存数 / 首个全零时刻 / 队列读数），
   末尾 SUMMARY（每档 n、逐轮幸存、all_zero、max time-to-zero、队列注记）。
   `idle-join` 档的合格复现是 all_zero=True 且 10/10。

## 这组数字进了代码哪里

- 「先捕获后有界 join」进了 `_close_job_pools`/`_pool_manager_threads`/
  `_close_pools_and_join_managers`；join 上界的运维依据（Electron 5 s 强杀 vs
  busy_timeout 30 s）写在 `shutdown.py` 模块头与 `_POOL_MANAGER_JOIN_SECONDS` 注释。
- 形状与上界的仓内判据（可红可绿、任何机器）：`test_the_manager_thread_is_captured_
  before_shutdown_and_joined_once`、`test_the_manager_join_timeout_is_bounded_inside_
  the_force_kill_window`、`test_a_manager_thread_that_outstays_the_join_says_so_in_the_log`。
- 私有属性依赖的改名哨兵：`ManagerThreadAttributePinTests`（真池里必须是
  `threading.Thread`；`ThreadPoolExecutor` 压根没有它）+ `PoolRenameAlarmTests`
  （捕不到必须出声，下载 lane 不许误响）。
