"""C3 判据的**共享道具**：记账管理线程替身 + 带记录旋钮的假池。

消费者有两个文件，拆开的唯一原因与 `job_cancel_fixtures.py` 同族（600 行绊线，
`scripts/line-limit.mjs`）：

* `test/backend/test_shutdown_closes_pools.py` —— `shutdown._cleanup()` 侧的
  调用序列、best-effort、管理线程捕获与 join 的形状；
* `test/backend/test_exit_pool_shutdown.py` —— `executor.shutdown_pools_for_exit()`
  侧的终态归属、退出窗口封死重建，以及两条运行时 import 探针。

夹具只有这一份，理由同 `job_cancel_fixtures.py`：两份会各自漂。
"""

from test.backend.job_cancel_fixtures import FakePool

from apps.jobs.models import Job


class RecordingManagerThread:
    """真池那个管理线程的**记账替身**：只被 join，不干活。

    `join(timeout)` 把传进来的 timeout 原样记下来，并往共享的 `box` 里打一个时刻记号，
    于是「join 排在 shutdown 之后、排在关连接之前」这种位置关系可读、可红。
    `alive_after_join=True` 模仿「join 到点时线程还在等还在跑活的 child」⇒ 生产实现要
    往日志里留一句（那是运维唯一能看到的表面）。
    `raise_on_join=True` 模仿「解释器把 join 本身弄炸」：先记账**再**抛 —— 钉的是
    `shutdown._close_pools_and_join_managers` 里包住 `thread.join()` 的 try/except
    与那句 load-bearing 的 `continue`（cleanup 不许抛、不许把后面的线程跳过去）。
    """

    def __init__(self, label, box, alive_after_join=False, raise_on_join=False):
        self.label = label
        self.box = box
        self.joins = []
        self._alive_after_join = alive_after_join
        self._raise_on_join = raise_on_join

    def join(self, timeout=None):
        self.joins.append(timeout)
        if self._raise_on_join:
            raise RuntimeError(f'{self.label} refuses to be joined')
        self.box.append(self.label)

    def is_alive(self):
        return self._alive_after_join


class CountingPool(FakePool):
    """`FakePool` + 四个记录旋钮：`shutdown` 的**全部**调用参数、调用**顺序记号**、
        「`shutdown()` 那一刻库里的状态」，以及一条照真池形状挂在实例上的管理线程引用。

    `FakePool.shut_down` 只留最后一次调用，钉不住「恰好一次」；「此刻库状态」是
    `test_the_reap_happens_before_the_pool_is_shut_down` 唯一的眼睛 —— 收尸若排在关池
    之后，这一眼读到的就是 `running`（回调见 cancelled 就收手，之后再没人写）。
    `shutdown()` 末尾把 `_executor_manager_thread` 置 None，**这一条是照抄 CPython**
    （3.13.12 `process.py:854`，评审机 3.12.3 同行号段 `:876`）：不抄它就钉不住
    「必须在 shutdown 之前捕获」——事后 getattr 拿到 None，join 一次都不会发生。
    """

    def __init__(self, capacity=0, label=None, box=None, raise_on_shutdown=False,
                 manager_thread=None):
        super().__init__(capacity)
        self.calls = []
        self.label = label
        self.box = box
        self.raise_on_shutdown = raise_on_shutdown
        self.watch = []
        self.statuses_at_shutdown = []
        self._executor_manager_thread = manager_thread

    def shutdown(self, wait=True, *, cancel_futures=False):
        self.calls.append((wait, cancel_futures))
        if self.box is not None:
            self.box.append(self.label)
        self.statuses_at_shutdown = [Job.objects.get(pk=pk).status for pk in self.watch]
        if self.raise_on_shutdown:
            raise RuntimeError('this pool refuses to close')
        super().shutdown(wait, cancel_futures=cancel_futures)
        self._executor_manager_thread = None
