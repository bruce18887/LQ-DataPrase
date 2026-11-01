import json
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from apps.analysis.services.statistics import (
    build_col_meta,
    detect_fail_data_with_borderline,
)
from apps.common.memory import get_budget
from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parse_cache_sizing import (
    _PARSE_MOUNT_PARSE_SIDE,
    _PARSE_MOUNT_WRITE_THROUGH,
    _column_profile_for_storage,
    _parse_value_bytes,
)
from apps.datafiles.parsers import get_parser, BaseATEParser
from apps.datafiles.utils import resolve_file_path

logger = logging.getLogger(__name__)


def _resolve_cache_budget_bytes() -> int:
    """解析缓存预算 = 预算内核的 ``cache_budget_bytes``（导入期读一次）。

    单独成函数是为了让测试能 patch 本模块消费的 ``get_budget`` 绑定（R6③），
    证明预算确实来自内核，而不是本模块里另写死的 1536MB。
    """
    return get_budget().cache_budget_bytes


# 预算来源统一在 apps/common/memory.py：web 预算的 60%，上限 1536MB。
# LQDP_PARSE_CACHE_MB 的覆盖也在那边解析（0 = 关闭缓存）。
PARSE_CACHE_BUDGET_BYTES = _resolve_cache_budget_bytes()
logger.info('解析缓存预算 = %dMB', PARSE_CACHE_BUDGET_BYTES // (1024 * 1024))

# fail/临界格检测结果的缓存预算：解析预算的 1/8，上限 64MB。
# 检测值只装 fail 行（``fail_cells`` 是 ``{行号: [列名]}``），同一只文件通常远小于帧；
# 但「全 fail 的宽表」可以到几十 MB，所以仍按字节封顶，而不是旧实现的 ``maxsize=32``。
# 失败四元组也占位（固定成本见 ``_FAILED_VALUE_BYTES``），与成功值共用这一条预算。
# 跟着解析预算走：``LQDP_PARSE_CACHE_MB=0`` 关掉解析缓存时这里也一并关掉
# （同一条开关不该只关一半）。
FAIL_CACHE_BUDGET_BYTES = min(PARSE_CACHE_BUDGET_BYTES // 8, 64 * 1024 * 1024)


class _BytesLRUCache:
    """按字节预算的 LRU，带每 key 单飞（并发 miss 只计算一次）。

    与 ``functools.lru_cache`` 的关键差别：
    1. 淘汰依据是**累计字节**而非条目数；
    2. 同一 key 的并发 miss 中只有一个线程真正计算，其余等待其结果——
       首屏 ``/summary`` + histogram + wafer_map 同时打到未缓存的大文件时，
       历史上会各解析一遍（单次约 4s）。
    3. 单值就超预算的条目不缓存（否则放进去立刻自逐），但每次仍返回正确值。
    """

    def __init__(self, budget_bytes: int):
        self._budget = max(0, int(budget_bytes))
        self._data: 'OrderedDict[tuple, tuple]' = OrderedDict()
        self._pending: set = set()
        self._total = 0
        self._cv = threading.Condition()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._clears = 0

    def __len__(self) -> int:
        with self._cv:
            return len(self._data)

    def bytes_cached(self) -> int:
        with self._cv:
            return self._total

    def clear(self) -> None:
        with self._cv:
            self._data.clear()
            self._total = 0
            self._clears += 1

    def evict_to(self, target_bytes: int) -> None:
        """淘汰最旧条目直到总量 ≤ target；至少保留一条（与 _store_locked 一致）。"""
        with self._cv:
            target = max(0, int(target_bytes))
            while self._total > target and len(self._data) > 1:
                _, (_, freed) = self._data.popitem(last=False)
                self._total -= freed
                self._evictions += 1

    def evict_keys(self, pred) -> int:
        """逐出 ``pred(key)`` 为真的条目，返回逐出条数。

        与 ``evict_to``/``_store_locked`` 的三点区别都是刻意的：
        1. 那两条按**预算**淘汰、且「至少保留一条」（防热点文件刚存就自逐）；本方法按
           **内容坐标**点名淘汰，点到的全走 —— 没人再读它时留下的字节就是白占的预算
           （脏不脏由键管，两半论证见 ``evict_parse_cache_for_paths`` 的 docstring）。
        2. 谓词只在**扫描**阶段求值、弹出在扫描之后 ⇒ 谓词抛错时一条都没动过，
           不会出现「条目没了但计费没扣」的错开。
        3. 不碰 ``_pending``、也不 notify：唤醒等待者的只有三处 ``notify_all``（``get_or_compute``
           的发布段与异常释放段、``put`` 的写透；这三处的**位置与数目**由
           ``test_parse_cache_invariant_scan.py::NotifyAllSourceScanTests`` 守着），
           定点淘汰不在其列 ⇒ 它插在中间也不会把挂在同一 key 上等待的人丢下（不会丢唤醒）。
        整段一次持锁 ⇒ 与发布段互斥，看不到「条目写了一半」的中间态。
        入账进 ``_evictions``（``/metrics`` 里预算淘汰与定点淘汰同账），不进 ``_clears``。
        """
        with self._cv:
            doomed = [key for key in self._data if pred(key)]
            for key in doomed:
                _, freed = self._data.pop(key)
                self._total -= freed
            self._evictions += len(doomed)
            return len(doomed)

    def get_or_compute(self, key, compute, size_of=_parse_value_bytes, store_if=None):
        """返回 key 对应的值，必要时由当前线程计算并放入缓存。

        ``store_if`` 由调用方定义什么值值得占位；默认 None＝无条件存。

        **发布顺序是这条承诺的一部分**（2026-10-28 修，判据见
        ``test/backend/test_parse_cache_single_flight.py``）：``compute`` 结束后，
        被判据钉住的**只是**一条不变量：唤醒后重新拿锁时不得出现「条目还没进 ``_data``、
        key 已离开 ``_pending``」的空窗（步序不是判据——拆两次持锁、锁内先 notify 后 store 均仍绿）。
        旧写法把这两步留在锁外，等待者被唤醒后重新拿锁时条目还没进 ``_data``、
        key 已不在 ``_pending`` ⇒ 它判定「没人正在算」，自己再算一遍，
        「每文件只算一次」在并发下就不成立了（A4 让 ``_parse_value_bytes`` 变贵后，
        这段锁外窗口翻倍，既有并发例从 12 轮红 2 次升到红 10 次）。
        写条目与放开 pending 目前在同一次持锁内做完，但 ``size_of``/``store_if`` 的求值留在锁外——
        那条由 ``PublishLockWindowTests`` 的两条**次序**判据钉着（get 侧与写透侧各一条）。

        异常与 ``store_if`` 拒绝这两条路径**仍然必须**释放 pending 并 notify：
        前者由 ``test_failed_parse_is_not_stuck_as_pending`` 钉着，
        后者是「瞬时失败不永久化」（失败值不入缓存，等待者醒来后自己重算）；
        ``size_of``/``store_if`` 自身抛错也走同一条释放路径（判据
        ``test_publish_side_exception_still_releases_pending``）。
        """
        while True:
            with self._cv:
                entry = self._data.get(key)
                if entry is not None:
                    self._data.move_to_end(key)
                    self._hits += 1
                    return entry[0]
                if key in self._pending:
                    # 另一个线程正在算：等它发布结果或失败后重来一轮
                    self._cv.wait()
                    continue
                self._misses += 1
                self._pending.add(key)
            try:
                value = compute()
                # 纯计算在锁外：这把 Condition 是全站解析缓存的**读锁**，任何线程查任何 key
                # 的命中都要拿它，而 1702 列那档的 size_of 是几十毫秒量级，进锁就变成
                # 「一个文件解析完」阻塞「所有文件的首屏命中查询」。先 store_if 后 size_of 是
                # HEAD 的短路次序：被拒的失败值不该再付一遍体积的钱、也不该要求体积函数容它。
                keep = store_if is None or store_if(value)
                nbytes = size_of(value) if keep else 0
                # 只有变异与发布进锁，且在同一次持锁内完成（先条目、后放开 pending）。
                with self._cv:
                    if keep:
                        self._store_locked(key, value, nbytes)
                    self._pending.discard(key)
                    self._cv.notify_all()
            except BaseException:
                # 算不出来、或 ``size_of``/``store_if`` 自身抛错：只放开 pending，
                # 没有任何值已发布，等待者醒来自己重算（绝不把该 key 永久挂在 pending 上）。
                with self._cv:
                    self._pending.discard(key)
                    self._cv.notify_all()
                raise
            return value

    def put(self, key, value, size_of=_parse_value_bytes) -> None:
        """直接写入一条缓存（不做单飞，也不返回结果）。

        上传链路已经把文件解析成 DataFrame，这里把结果写透进缓存，
        省掉用户首次打开时的第二次解析。

        ``notify_all`` 是承重的、一次都不能丢：``get_or_compute`` 里那句 ``self._cv.wait()``
        没有超时——别的线程若正挂在同一 key 上等结果，这里只写不唤醒就是死等，写透白做。
        """
        nbytes = size_of(value)   # 与发布段同口径：体积在锁外量，锁内只剩「写条目 + notify」
        with self._cv:
            self._store_locked(key, value, nbytes)
            self._cv.notify_all()

    def _store_locked(self, key, value, nbytes) -> None:
        """写入条目并按累计字节淘汰。**调用方必须已持有 ``self._cv``**——
        本方法不再自己加锁，全仓只有这一个写入口径（``get_or_compute`` 的发布段与
        ``put`` 都在锁内调它），免得「锁内/锁外」两份实现各漂一次。
        """
        if nbytes > self._budget:
            return
        if key in self._data:          # 同键覆盖先退旧账：``_data[key] = ...`` 是原地替换，
            self._total -= self._data[key][1]   # 旧那份不会自己从 _total 里扣 ⇒ 一只条目占两笔预算
        self._data[key] = (value, nbytes)
        self._data.move_to_end(key)
        self._total += nbytes
        while self._total > self._budget and len(self._data) > 1:
            _, (_, freed) = self._data.popitem(last=False)
            self._total -= freed
            self._evictions += 1


_parse_cache = _BytesLRUCache(PARSE_CACHE_BUDGET_BYTES)


def _disk_mtime_ns(file_path: str) -> int:
    """Return the on-disk mtime in nanoseconds, or 0 if the file is gone.

    Used as a cache key suffix: entries are keyed by the content
    coordinates ``(resolved absolute path, this mtime, format_type)``.
    Keying on the **resolved** absolute path is what keeps relative and
    absolute ``file_path`` variants of the same physical file sharing
    one entry; mtime is what makes a **successful** entry self-
    invalidate when the underlying file is re-uploaded, overwritten or
    otherwise replaced (including the project being moved on disk and
    ``file_path`` re-pointed): the next read lands on a new key and
    re-parses, instead of serving the old content's frame forever.

    Old rationale retired: this docstring once justified the mtime with
    "a cached ``(None, None, fmt)`` from a broken path would be served
    even after the DB row was fixed" — since the 2026-10-25 payload
    dedup work failure values never enter the **parse** cache at all
    (``store_if=_parse_succeeded``), so that example can no longer
    occur there. The conclusion is unchanged — mtime stays in the key,
    now argued by the success-entry invalidation above (the fail/
    borderline cache also stores failures, and relies on the same mtime).
    """
    try:
        return os.stat(file_path).st_mtime_ns
    except OSError:
        return 0


def _cached_parse(file_id: int, owner_id: int, path_key: int,
                  file_path: str, format_type: str) -> Tuple[Optional[pd.DataFrame], Optional[dict], Optional[str]]:
    """Parse a DataFile and cache the result in memory (byte-budgeted LRU).

    Key = (绝对路径, 盘上 mtime_ns, format_type) —— 内容坐标。
    `file_id` / `owner_id` 不进键：`_parse_file_uncached` 只消费路径与格式，
    那两个参数在这条链上只用于鉴权与日志。把 owner 放进键会让 20 个用户各解析
    一遍同一只物理文件（夹具见 scripts/perf_load20.py:192-195），且每-key 单飞
    在跨 owner 场景完全失效。`format_type` 必须留在键里：同一路径被两行标成不同
    格式时用的是不同 parser，合并会返回错数据。

    ``path_key`` is the on-disk mtime in nanoseconds of the file at the
    time the caller resolved it. Including it in the cache key ensures
    the cache auto-invalidates whenever the file's path or content
    changes — the caller re-reads ``DataFile.file_path`` and computes
    ``_disk_mtime_ns(file_path)`` on every call, so a stale entry from
    a previous (broken) path is never served. Entries are evicted by
    accumulated size (``PARSE_CACHE_BUDGET_BYTES``), not by count, and
    concurrent misses for the same file share one parse.

    ``file_path`` / ``format_type`` 由调用方解析（避免缓存函数内部再查库）。
    调用方必须已通过 DataFile 查询验证归属。

    Callers must NOT mutate the returned DataFrame — treat it as
    read-only. If you need a mutable copy, call ``.copy()`` yourself.
    坐标化之后这只帧的消费者从「一个 owner 的几个请求」变成「同一路径的所有
    请求」，共享范围更大，只读约定见 SharedFrameSafetyTests 的静态扫描。

    Returns ``(df, metadata, format_type)``.  Any element may be
    ``None`` on failure (missing file, parse error, etc.).
    """
    key = (file_path, path_key, format_type)
    return _parse_cache.get_or_compute(
        key, lambda: _parse_file_uncached(file_id, owner_id, path_key,
                                         file_path, format_type),
        store_if=_parse_succeeded)


def _parse_file_uncached(file_id: int, owner_id: int, path_key: int,
                         file_path: str, format_type: str):
    try:
        if not os.path.exists(file_path):
            return None, None, format_type  # hint: file not on disk
        parser = get_parser(format_type)
        df, metadata = parser.parse(file_path)
        if df is None:
            return None, metadata, format_type
        metadata = dict(metadata)
        # 串供 browse 每页直接拼接；dict 仍留给 detect_fail 等按 dict 读的消费方
        metadata['col_meta'] = build_col_meta(df, metadata)
        metadata['col_meta_json'] = json.dumps(metadata['col_meta'], ensure_ascii=False)
        # 首屏列级元信息与 col_meta 同址：都是「每文件一次」的 O(列) 现算，
        # 挂在解析刚结束的**过滤前全量帧**上，之后每一次 page==1 首屏直接读。
        profile = _column_profile_for_storage(
            df, format_type,
            source=_PARSE_MOUNT_PARSE_SIDE, file_path=file_path)
        if profile is not None:
            metadata['column_profile'] = profile
        return df, metadata, format_type
    except Exception as exc:
        logger.warning("_parse_file_uncached(%s, %s, %s) failed: %s", file_id, owner_id, path_key, exc)
        return None, None, None


def _parse_succeeded(value) -> bool:
    """「这条值值得占缓存位」的唯一判据。

    三种失败形状（路径不存在 / parser 返回 df=None / 抛异常兜成 (None, None, None)）都不该存：
    `_parse_value_bytes` 给它们算 0 字节，而 `_store_locked` 的淘汰循环只在**总量超预算**时逐条，
    0 字节条目既不占预算也永远不会被逐出 ⇒ 一次瞬时失败会永久化到该文件 mtime 变化。
    与写透路径 `put_cached_parsed_file`（开头的守卫判 **df 与 metadata 双双非 None** 才写）
    **方向一致但不等价**：本谓词只判 `value[0]`（df）。
    这里只判 df 就够，因为 `(df, None, fmt)` 这个形状在本链上今天不可达——
    `_parse_file_uncached` 在 df 非 None 后立刻对 metadata 做 `dict(metadata)`
    （那句起至 `except` 兜底的 `(None, None, None)`，行号会漂、按语义找），metadata 为 None
    会在那里抛 TypeError、落进异常分支返回 `(None, None, None)`，
    所以走到这里时「df 非 None」已蕴含「metadata 非 None」。
    （写透侧不收 df 非 None 而 metadata 为 None 的入参，是它自己守卫更严一分；
    两边刻意不必写成同一句谓词——读侧的形状由 `_parse_file_uncached` 兜死。）
    """
    return bool(isinstance(value, tuple) and value[0] is not None)


def get_cached_parsed_file(file_id: int, owner_id: int, datafile=None) -> Tuple[Optional[pd.DataFrame], Optional[dict], Optional[str]]:
    """Public wrapper around ``_cached_parse``.

    Resolves the current ``DataFile.file_path`` and uses its on-disk
    mtime as part of the cache key, so updating ``file_path`` (e.g.
    after the project root moved) automatically invalidates the cache.

    ``datafile``：调用方已加载的 DataFile 对象（带 owner 归属校验）时传入，
    可省去一次 DB 查询——热路径（导出/浏览）一次请求只查一次库。

    Returns ``(df, metadata, format_type)`` — same semantics as
    ``parser.parse()`` but backed by a byte-budgeted LRU cache
    (``PARSE_CACHE_BUDGET_BYTES``).
    """
    if datafile is None:
        datafile = DataFile.objects.filter(pk=file_id, owner_id=owner_id).first()
    if datafile is None:
        return None, None, None
    # 缓存 key 是内容坐标（解析后的绝对路径 + 盘上 mtime_ns + format_type），
    # 相对/绝对混存天然兼容；file_id / owner_id 只用于鉴权查询与日志，不进键
    abs_path = resolve_file_path(datafile.file_path)
    path_key = _disk_mtime_ns(abs_path)
    return _cached_parse(file_id, owner_id, path_key, abs_path, datafile.format_type)


def put_cached_parsed_file(file_id: int, owner_id: int, datafile,
                           df, metadata, fmt) -> None:
    """把上传时已经解析出的结果写透进解析缓存。

    上传链路 ``_register_file`` 为了拿 row_count/col_count 已经调用过一次
    ``parser.parse``（实测单次 3.2s、df 常驻 460MB），随后把 df 丢掉；
    不写透的话用户首次打开该文件会再解析一遍，同一只 275MB 文件被解析两次。

    key 的算法与 ``get_cached_parsed_file`` 完全同源（同一个
    ``resolve_file_path`` + 同一个 ``_disk_mtime_ns`` + 同一个
    ``(绝对路径, mtime_ns, format_type)`` 三元组），否则写进去也命不中。
    因此 ``datafile`` 必须在 ``DataFile.objects.create`` 之后传入——那时
    ``file_path`` 已是入库后的相对路径，解析出的绝对路径与读侧逐字节一致。

    ``df`` / ``metadata`` 为 None 时不写：失败结果不缓存，下次访问仍会重试，
    与 ``_parse_file_uncached`` 的失败语义保持一致。这也是这里不需要给
    ``put`` 传 ``store_if`` 的原因——写透侧早就只写成功值，同一道闸已经写在
    那句守卫里；``put`` 也没有 ``store_if`` 形参，等出现第二个写透调用方再
    考虑加同名同默认值的形参，现在加就是给一条没人走的路预留参数。

    ``file_id`` / ``owner_id`` 坐标化之后不再进键，形参保留是为了与
    ``get_cached_parsed_file`` 对称、不动调用点（``_helpers._register_file``）。
    """
    if datafile is None or df is None or metadata is None:
        return
    abs_path = resolve_file_path(datafile.file_path)
    path_key = _disk_mtime_ns(abs_path)
    # 上传链路的 metadata 来自 ``_helpers.parse_file_meta`` 的直接 ``parser.parse``，
    # 不经过 ``_parse_file_uncached``，所以它**没有** ``col_meta``。不在这里补上，
    # 这条条目此后每一次读都要走消费侧的
    # ``metadata.get('col_meta') or build_col_meta(df, metadata)`` 回落，
    # 「每文件只算一次」（J4）就只在回放路径兑现，而上传/导入才是主入库路径。
    # 与 ``_parse_file_uncached`` 同形：先复制一份再挂键，且
    # ``build_col_meta`` 的入参是**尚未带 col_meta 的那份**。
    # ``column_profile`` 必须同址一起补：只补 col_meta 的话条目就永久停在
    # 「有 col_meta、无 profile」的半吊子形状，首屏每一次读都要走视图侧回落，
    # 这一刀在主入库路径上等于没做。格式取 ``datafile.format_type``——它与缓存键、
    # 与视图侧回落用的是同一个值，否则「命中缓存」与「回落现算」会给出不同的系统列集合。
    if not all(k in metadata for k in ('col_meta', 'col_meta_json', 'column_profile')):
        metadata = dict(metadata)
        if 'col_meta' not in metadata:
            metadata['col_meta'] = build_col_meta(df, metadata)
        if 'col_meta_json' not in metadata:
            metadata['col_meta_json'] = json.dumps(
                metadata['col_meta'], ensure_ascii=False)
        if 'column_profile' not in metadata:
            profile = _column_profile_for_storage(
                df, datafile.format_type,
                source=_PARSE_MOUNT_WRITE_THROUGH, file_path=abs_path)
            if profile is not None:
                metadata['column_profile'] = profile
    _parse_cache.put((abs_path, path_key, datafile.format_type), (df, metadata, fmt))


_fail_cache = _BytesLRUCache(FAIL_CACHE_BUDGET_BYTES)

# 每条结果先记一笔固定开销：空结果 ``([], [], {}, {})`` 在「没有 fail 行」的文件上是最常见
# 的形状，若按内容算成 0 字节，``_store_locked`` 的预算淘汰永远逐不到它（无界容器）。
_FAIL_ENTRY_OVERHEAD_BYTES = 256

# 失败四元组的占位成本。失败值**也要缓存**：解析缓存拒收失败帧，这里若也拒收，坏文件每刷新
# 一次都要重解析一遍（HEAD 的 ``@lru_cache(maxsize=32)`` 正是把失败值 memo 住的）。固定成本
# 把「能缓存多少条失败」折成条数上界：预算 B、每条 ceil(B/64) ⇒ 第 65 条时 65·ceil(B/64) > B，
# ``_store_locked`` 必逐最旧一条 ⇒ 至多 64 条（与 HEAD 的 32 条同量级）。取 ceil 而非 B//64：
# 后者在 B 非 64 倍数时可能放过 65 条以上（B=127 ⇒ 127 条）；B=0（关缓存）时取 1 ⇒ 超预算不存。
_FAILED_VALUE_BYTES = max(1, (FAIL_CACHE_BUDGET_BYTES + 63) // 64)


def _fail_value_bytes(value) -> int:
    """``(fail_indices, fail_columns, fail_cells, borderline_cells)`` 的缓存占用估算。

    失败四元组（``value[0] is None``，``_detect_fail_data_uncached`` 的两条失败出口都返回
    这个形状）按 ``_FAILED_VALUE_BYTES`` 固定计费，分支必须**非 0**：0 字节条目不占预算、
    也永远逐不到（``_store_locked`` 只在总量超预算时逐条）⇒ 失败值会永久占着这个 key ——
    与 ``_parse_succeeded`` 拒收失败帧同一条理由，只是这里选择「缓存但按条数上界封顶」。
    成功值沿用 ``_parse_value_bytes`` 的纪律：不许给真实结果算 0 字节。字符串按**出现次数**
    计 —— 列名对象被同一文件的所有行共享，所以这里是高估：宁可提前淘汰，也不低估到让
    ``{行号: [列名]}`` 的真实体量隐身穿透。
    """
    if not isinstance(value, tuple) or not value or value[0] is None:
        return _FAILED_VALUE_BYTES
    total = _FAIL_ENTRY_OVERHEAD_BYTES
    indices, columns, fail_cells, borderline_cells = value
    if isinstance(indices, (list, tuple)):
        total += 8 * len(indices)
    if isinstance(columns, (list, tuple)):
        total += sum(8 + len(str(col)) for col in columns)
    for cell_map in (fail_cells, borderline_cells):
        if not isinstance(cell_map, dict):
            continue
        for cols in cell_map.values():
            total += 32                    # dict 一项 + list 头
            if isinstance(cols, (list, tuple)):
                total += sum(8 + len(str(col)) for col in cols)
    return total


def _cached_fail_data(file_id: int, owner_id: int, path_key: int,
                      file_path: str, format_type: str) -> Tuple[Optional[list], Optional[list], Optional[dict], Optional[dict]]:
    """Cache the full-file fail + borderline detection on top of the parsed file.

    Key = **与 ``_cached_parse`` 逐字相同**的内容坐标
    ``(绝对路径, 盘上 mtime_ns, format_type)``。检测值是帧的纯函数
    （``detect_fail_data`` 只读 ``(df, metadata)``），所以「跟着帧一起失效」只需
    一条论证：同一坐标 ⇒ 同一份内容 ⇒ 同一份检测结果。
    `file_id` / `owner_id` **不进键**：它们在这条链上只用于日志，把 owner 放进键会让
    同一只物理文件的第二个 owner 再检测一遍（夹具见 scripts/perf_load20.py:192-195）。
    ``format_type`` 必须留在键里：同一路径被两行标成不同格式时 parser 不同、检测面也不同。

    ``path_key`` 由调用方现读（``get_cached_fail_data`` 每次都重算 ``_disk_mtime_ns``）：
    盘上文件被替换 ⇒ 换键重新检测；文件被删 ⇒ ``_disk_mtime_ns`` 读回 0 ⇒ 也换键。

    淘汰与并发口径与解析缓存同源（``_BytesLRUCache``）：按**累计字节**（``FAIL_CACHE_BUDGET_BYTES``）
    而不是旧实现的 ``maxsize=32`` 条数，同一 key 的并发 miss 只检测一次。

    失败四元组 ``(None, None, None, None)`` **也缓存**（固定按 ``_FAILED_VALUE_BYTES``
    计费，见 ``_fail_value_bytes``）：解析缓存拒收失败帧，这里若也拒收，坏文件每刷新一次
    就重解析一遍。代价与 HEAD 的 ``@lru_cache(maxsize=32)`` 相同 —— 盘上 mtime 不变的
    失败值会一直命中（瞬时失败会被记住），直到预算淘汰或 ``clear_parse_cache()``；
    HEAD 的上界是 32 条（按键），这里是预算 B 下至多 64 条（算术见 ``_FAILED_VALUE_BYTES``）。
    文件被替换 ⇒ mtime 换键、重新解析；``clear_parse_cache()`` 全清。

    Callers must treat ``fail_cells`` / ``borderline_cells`` as read-only —
    they are shared across requests **and across owners**. Never mutate them
    (e.g. no in-place column removal). 静态扫描见
    ``apps/datafiles/tests_parse_cache_scan.py::SharedFailCellsSafetyTests``。

    Returns ``(fail_indices, fail_columns, fail_cells, borderline_cells)`` —
    any element may be ``None`` when the underlying file failed to parse.

    ``file_id`` / ``owner_id`` 形参保留是为了与 ``_cached_parse`` 对称、给 WARNING 留可归因
    上下文；它们不参与任何缓存判定。
    """
    key = (file_path, path_key, format_type)
    return _fail_cache.get_or_compute(
        key,
        lambda: _detect_fail_data_uncached(file_id, owner_id, path_key,
                                           file_path, format_type),
        size_of=_fail_value_bytes,
    )


def _detect_fail_data_uncached(file_id: int, owner_id: int, path_key: int,
                               file_path: str, format_type: str):
    """``_cached_fail_data`` 的未缓存实现（与 ``_parse_file_uncached`` 同形）。"""
    df, metadata, _fmt = _cached_parse(file_id, owner_id, path_key, file_path, format_type)
    if df is None:
        return None, None, None, None
    try:
        return detect_fail_data_with_borderline(df, metadata)
    except Exception as exc:
        logger.warning("_detect_fail_data_uncached(%s, %s, %s) failed: %s", file_id, owner_id, path_key, exc)
        return None, None, None, None


def get_cached_fail_data(file_id: int, owner_id: int, datafile=None) -> Tuple[Optional[list], Optional[list], Optional[dict], Optional[dict]]:
    """Public wrapper around ``_cached_fail_data`` — same resolution
    pattern as ``get_cached_parsed_file`` (mtime-based auto invalidation,
    ``datafile`` param skips one DB query on hot paths).

    Returns ``(fail_indices, fail_columns, fail_cells, borderline_cells)``;
    elements may be ``None`` on failure (missing file, parse error, etc.).
    """
    if datafile is None:
        datafile = DataFile.objects.filter(pk=file_id, owner_id=owner_id).first()
    if datafile is None:
        return None, None, None, None
    abs_path = resolve_file_path(datafile.file_path)
    path_key = _disk_mtime_ns(abs_path)
    return _cached_fail_data(file_id, owner_id, path_key, abs_path, datafile.format_type)


def get_parse_cache_stats() -> dict:
    """给 `/api/v1/metrics/` 读的解析缓存读数（apps/common/metrics.py）。

    `in_flight` 是这一眼里最值钱的部分：它 >0 且持续不掉，就说明「同一只文件正在被重复解析」
    （P1-1 之前是常态）。八个键都是整数，没有「取不到就当 0」的模糊空间 ——
    空缓存的真 0 和读失败的可不是一回事，所以这里不返回 None。

    `hits` / `misses` 算命中率；`evictions` 是预算/水位淘汰**加**按路径定点淘汰的，
    `clears` 是显式全清（MemoryError 兜底与整体改路径的管理命令；G1（2026-10-28 波次）
    之后删文件/合并只走定点淘汰，不再进 `clears`）——两者混在一起会把「内存吃紧自愈」
    读成「用户删了文件」。
    """
    with _parse_cache._cv:
        return {
            'entries': len(_parse_cache._data),
            'bytes': _parse_cache._total,
            'budget_bytes': _parse_cache._budget,
            'in_flight': len(_parse_cache._pending),
            'hits': _parse_cache._hits,
            'misses': _parse_cache._misses,
            'evictions': _parse_cache._evictions,
            'clears': _parse_cache._clears,
        }


def evict_parse_cache_to(fraction: float) -> None:
    """把缓存淘汰到预算的 fraction；best effort，至少保留 MRU 一条。"""
    ratio = max(0.0, min(1.0, float(fraction)))
    _parse_cache.evict_to(int(_parse_cache._budget * ratio))


def evict_parse_cache_for_paths(paths) -> int:
    """只淘汰「本次操作真的动过的那些路径」的条目，返回逐出条数（低频操作专用）。

    ``paths`` 是调用点交出来的磁盘路径：``resolve_file_path(row.file_path)`` 的结果，
    或 ``_plan_file_moves`` 的 ``src``/``target``（移动的两端都算「动过」）。
    键的第一元同样出自 ``resolve_file_path``，但那个函数对**绝对**入库值是原样透传、
    只对相对值做 ``normpath`` ⇒ 比对前两边各过一次 ``normcase(normpath(...))``，否则
    ``media\\data\\x`` 与 ``media/data/./x`` 这种同文件不同写法会各留一条（不脏，同 ①）。
    Windows 上 ``normcase`` 还折大小写：盘上大小写不敏感、两条写法本就是同一只文件，
    多逐一条只多付一次重解析 —— 归一化只会**多**逐，**少**逐才可能留脏，方向是安全的。

    为什么定点淘汰足够、不必全清（判据见 ``test/backend/test_parse_cache_eviction.py``、
    ``test/backend/test_parse_cache_scoped_invalidation.py``，而「哪些调用点在交路径」这个
    集合本身由 ``test/backend/test_parse_cache_invariant_scan.py`` 钉住）：键是内容坐标
    ``(绝对路径, 盘上 mtime_ns, format_type)``，「行没了」有两种形状、两种都不脏 ——
    ① 另有行指向同一坐标（``file_path`` 无唯一约束，``consolidate_uploads`` 的 db_only
    分支就把行改写到已存在的同名目标上）：留下的条目是**同一份正确内容**，逐它只为回收预算；
    ② 文件真被删时 ``_disk_mtime_ns`` 走 OSError 分支读回 **0** ⇒ 下一次读换了键、必然 miss
    后自行重解析。两半各一条判据：``SharedPhysicalPathTests``、``RemovedFileRereadsUnderANewKeyTests``。
    全清对②**没有**额外保护：在途那条发布它同样收不回 —— 挡脏的是键，不是清的半径。

    ``_cached_fail_data`` 不随本函数清理 —— 设计决定，不是遗漏（G2 之后理由换了，判据
    仍是 ``FailDataCacheIsNotPathScopedTests``）：那只缓存现在是 ``_BytesLRUCache``，完全
    有能力按同一个谓词逐（它的键与本函数比对的键**逐字相同**），但**不该**逐 ——
    键去 owner 之后一条检测值可能被多行、多个 owner 共享，「某一行被删」不等于
    「这条检测值不再被读」。留下的代价与帧缓存那两半逐字同源：① 另有行指向同一坐标时
    它仍是**同一份正确内容**；② 文件真被删时下一次读换了键（mtime 读回 0）必然 miss；
    而它自己有 ``FAIL_CACHE_BUDGET_BYTES`` 封顶，路径数不是它的上界。
    """
    wanted = {os.path.normcase(os.path.normpath(p)) for p in paths if p}
    return _parse_cache.evict_keys(
        lambda key: os.path.normcase(os.path.normpath(key[0])) in wanted)


def clear_parse_cache() -> None:
    """Drop **everything** from both in-memory caches（帧缓存 + fail/临界格检测缓存）。

    全站清空只留给「此刻没有『哪些路径安全』这回事」的场合：MemoryError 兜底
    （``apps/common/exceptions.py``）与整体重写路径的管理命令
    （``consolidate_uploads`` / ``fix_moved_project_paths``，理由见各自的调用点）。
    删文件/移动文件那类只动几条的操作改用 ``evict_parse_cache_for_paths(...)``：
    这里一把清掉的是**全站**的帧，别的用户下一次请求就得从盘上重解析。
    检测缓存必须一起清：它是同一个内容坐标上的派生结果，帧清了它却留着会让
    「MemoryError 之后自愈」只自愈一半（判据 ``GlobalClearStillClearsEverythingTests``）。
    """
    _parse_cache.clear()
    _fail_cache.clear()
