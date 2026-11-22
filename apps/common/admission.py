"""重活准入内核：一个进程内信号量 + 内存水位驱动的淘汰 + 503 信封。

面板上的重活动作（直方图、wafer map、关联合计、出表…）是「一个人点击、整机变慢」的那类请求：
它们的峰值内存是解析缓存的好几倍。20 人档同时点两下就足以把 RSS 顶到水面以上，
而那时**所有**请求都开始慢，包括还没开始干活的人。所以这里做的是**准入**而不是排队执行：
同时跑的重活有上限（默认 2），拿不到槽的请求等一小会儿（默认 10s），再拿不到就明确回 503 ——
拒绝一个重活、保住其余几十个轻请求，比让所有人都陪着慢更划算。

三件事按顺序做，顺序本身是设计：

1. **soft 水位先救自己** —— RSS 已过 75% 时先把解析缓存淘汰到一半。缓存是可重建的，
   先扔它比先拒人便宜；把它扔了水位可能就回去了，于是这一请求根本不需要被拒。
2. **拿槽（带等待上限）** —— 超时即 `ServerBusy(reason='queue')`：此刻的瓶颈是并发数，
   不是内存，所以理由与内存那条区分开，运维看一眼就知道该调哪个旋钮。
3. **hard 水位再救一次** —— 拿到槽后若 RSS 已过 90%，把解析缓存清零再**复判**；
   仍 hard 才 `ServerBusy(reason='memory')`。复判这一步不能省：淘汰就是为复判服务的，
   不复判等于「hard 一律拒绝」，淘汰白做。

线程内嵌套用 `threading.local()` 的 depth 计数，只有最外层取/放槽：一个重活动作内部
再调用另一个带准入的函数（作业同步兜底就是这种形状）不该把容量吃两次。
跨进程不共享 —— 打包版是单机单进程，跨进程语义会引入 IPC 依赖却没有对应收益；
真到了多 worker 形态，这一层要换成共享状态，届时 `admission_snapshot()` 的键不用改。

淘汰调用是 best-effort：它自己失败（缓存实现出问题）只留日志，不改变 503 的判定 ——
判据是「水位复判结果」，不是「淘汰有没有成功」，否则缓存故障会变成全站停摆。
"""

import contextlib
import logging
import threading
import time

from apps.common.exceptions import ServerBusy
from apps.common.memory import env_int

__all__ = ['HeavyActionMixin', 'admission_snapshot', 'heavy_slot',
           'relief_if_soft', 'reset_for_tests']

logger = logging.getLogger(__name__)

# 容量：同时跑的重活数。默认 2 是 spec 的取值 —— 20 人档里两个重活已经把 Web 预算吃掉大半，
# 再放宽只是把「谁来慢」的问题推给所有人；不够用先调环境变量，不改代码。
DEFAULT_CAPACITY = 2
MIN_CAPACITY = 1
MAX_CAPACITY = 8

# 等待：拿不到槽时最多等多久。0 合法（立刻拒绝），用来在压测/测试里关掉等待。
DEFAULT_WAIT_SECONDS = 10
MIN_WAIT_SECONDS = 0
MAX_WAIT_SECONDS = 60

# 淘汰水位线：soft 扔一半，hard 清零。两个数写在这里而不是散在调用点，
# 因为「soft 扔一半」这个口径会被测试与文档同时引用。
SOFT_EVICT_FRACTION = 0.5
HARD_EVICT_FRACTION = 0.0

# 拒绝日志限频：拒绝是成批发生的（同一时刻多个请求一起撞墙），
# 每条一行会把日志刷成噪音，反而看不出「哪一分钟开始拒人」。
REJECT_LOG_INTERVAL_S = 10.0

_lock = threading.Lock()
_local = threading.local()

# _semaphore 与它的容量绑定在一起重建：环境变量变了要换一个大小不同的信号量，
# 但已经持槽的线程释放的是它当初拿到的那个对象（下面用局部引用），不会打到新槽上。
_semaphore = None
_semaphore_capacity = None

_state = {
    'active': 0,        # 当前持槽数
    'waiting': 0,       # 正在等着拿槽的线程数
    'rejected': 0,      # 累计拒绝数（进程生命周期内）
    'relief': 0,        # 累计成功执行的淘汰次数（soft 与 hard 都算）
    'last_reason': None,  # 最近一次拒绝的理由：'queue' / 'memory'
}

_last_reject_log_at = 0.0


def _capacity():
    return env_int('LQDP_HEAVY_CONCURRENCY', DEFAULT_CAPACITY,
                   minimum=MIN_CAPACITY, maximum=MAX_CAPACITY)


def _wait_seconds():
    return env_int('LQDP_HEAVY_WAIT_S', DEFAULT_WAIT_SECONDS,
                   minimum=MIN_WAIT_SECONDS, maximum=MAX_WAIT_SECONDS)


def _semaphore_for(capacity):
    """按容量取（必要时重建）模块级信号量。只在容量变化时重建。"""
    global _semaphore, _semaphore_capacity
    with _lock:
        if _semaphore is None or _semaphore_capacity != capacity:
            _semaphore = threading.BoundedSemaphore(capacity)
            _semaphore_capacity = capacity
        return _semaphore


def _level():
    """当前内存水位：'normal' / 'soft' / 'hard'，取不到时返回 None。

    懒导入两处都是为了避开配置加载期的循环（`metrics` 与 `memory` 都会回头穿过这里）。
    取不到水位不阻断准入：`None` 不等于 hard，准入照样按并发数工作 ——
    观测失败不该变成拒绝服务。
    """
    try:
        from apps.common.memory import get_budget
        from apps.common.metrics import process_rss_bytes
        return get_budget().level(process_rss_bytes())
    except Exception:
        logger.warning('读取内存水位失败，按未过水位处理', exc_info=True)
        return None


def _bump(key, delta=1):
    with _lock:
        _state[key] += delta


def _evict(fraction):
    """把解析缓存淘汰到预算的 fraction；失败只记日志，返回是否成功。

    懒导入是硬要求：`apps.datafiles.services` 会拉起模型层，
    而本模块在 DRF 异常处理与配置加载期都可能被导入。
    """
    try:
        from apps.datafiles.services import evict_parse_cache_to
        evict_parse_cache_to(fraction)
    except Exception:
        logger.warning('淘汰解析缓存失败：fraction=%s（best-effort，忽略）',
                       fraction, exc_info=True)
        return False
    _bump('relief')
    return True


def relief_if_soft():
    """soft 水位下先淘汰解析缓存到一半；返回是否真的淘汰了。"""
    if _level() != 'soft':
        return False
    return _evict(SOFT_EVICT_FRACTION)


def _note_reject(reason, action):
    """记一次拒绝：计数与最近理由每次都记，日志按 10s 限频。"""
    global _last_reject_log_at
    now = time.monotonic()
    with _lock:
        _state['rejected'] += 1
        _state['last_reason'] = reason
        should_log = (now - _last_reject_log_at) >= REJECT_LOG_INTERVAL_S
        if should_log:
            _last_reject_log_at = now
    if should_log:
        logger.warning('重活准入拒绝：action=%s reason=%s', action, reason)


@contextlib.contextmanager
def heavy_slot(action):
    """为一次重活动作取一个槽；拿不到时抛 `ServerBusy`。

    `action` 只用于日志与归因（例如 `'histogram'`），不参与判定。
    """
    depth = getattr(_local, 'depth', 0)
    if depth > 0:
        # 线程内嵌套：已经持槽了，只加计数，不再取槽也不再判水位。
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth -= 1
        return

    semaphore = _semaphore_for(_capacity())
    relief_if_soft()

    _bump('waiting')
    try:
        acquired = semaphore.acquire(timeout=_wait_seconds())
    finally:
        _bump('waiting', -1)

    if not acquired:
        _note_reject('queue', action)
        raise ServerBusy(reason='queue')

    _bump('active')
    _local.depth = 1
    try:
        if _level() == 'hard':
            _evict(HARD_EVICT_FRACTION)
            if _level() == 'hard':
                _note_reject('memory', action)
                raise ServerBusy(reason='memory')
        yield
    finally:
        _local.depth = 0
        _bump('active', -1)
        semaphore.release()


def admission_snapshot():
    """准入读数：容量、在跑、在等、累计拒绝、累计淘汰、最近拒绝理由。"""
    capacity = _capacity()
    with _lock:
        return {
            'capacity': capacity,
            'active': _state['active'],
            'waiting': _state['waiting'],
            'rejected': _state['rejected'],
            'relief': _state['relief'],
            'last_reason': _state['last_reason'],
        }


def reset_for_tests():
    """清空信号量与计数器：测试隔离用，生产路径不调用。"""
    global _semaphore, _semaphore_capacity, _last_reject_log_at
    with _lock:
        _semaphore = None
        _semaphore_capacity = None
        _state.update({'active': 0, 'waiting': 0, 'rejected': 0,
                       'relief': 0, 'last_reason': None})
        _last_reject_log_at = 0.0
    _local.depth = 0


class HeavyActionMixin:
    """把 ViewSet 的重活动作接到准入信号量上（spec §6.1）。

    用法：`class XViewSet(HeavyActionMixin, ...)` 并在类顶声明
    `heavy_actions = frozenset({...})`。

    取槽点在 `initial()` 而不是 `dispatch()`：`ViewSetMixin.initialize_request()`
    才把 `self.action` 填好，而它跑在 `APIView.dispatch()` **内部** —— 覆写
    `dispatch()` 时名单永远匹配不上（`self.action` 还是 `None`），在那里抛出的
    `ServerBusy` 也落在 `APIView.dispatch()` 的 try 之外，会变成 500 而不是 503 信封。

    取槽在 `super().initial()` **之后**：认证 / 权限 / 节流先过，匿名或无权请求
    不占槽、也不进 10s 等待队列去撞 401（2026-11-22）。取槽之后 `initial()` 里
    不再有可抛点，所以不需要异常清场块；槽的释放只在 `finalize_response()` 的
    `finally`（成功与业务体异常都走这一处）。
    """

    heavy_actions = frozenset()
    _heavy_ctx = None

    def initial(self, request, *args, **kwargs):
        # 认证 / 权限 / 节流先行：匿名刷重活不该占着槽，让真实用户排队。
        super().initial(request, *args, **kwargs)
        # 到这里 `self.action` 已被 `ViewSetMixin.initialize_request()` 填好。
        action = getattr(self, 'action', None)
        self._heavy_ctx = None
        if action in self.heavy_actions:
            ctx = heavy_slot(action)
            ctx.__enter__()        # ServerBusy 因此位于 APIView.dispatch() 的 try 内
            self._heavy_ctx = ctx

    def finalize_response(self, request, response, *args, **kwargs):
        try:
            return super().finalize_response(request, response, *args, **kwargs)
        finally:
            if self._heavy_ctx is not None:
                self._heavy_ctx.__exit__(None, None, None)
                self._heavy_ctx = None
