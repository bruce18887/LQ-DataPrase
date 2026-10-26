import logging
import os
import threading
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from apps.analysis.services.statistics import (
    build_col_meta,
    detect_fail_data_with_borderline,
)
from apps.common.memory import get_budget
from apps.datafiles.models import DataFile, ParseHistory
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


def _frame_bytes(df) -> int:
    """估算一只 DataFrame 的常驻字节数。

    ``deep=True`` 才会把 object 列的真实字符串大小算进来——ATE 数据里
    这类列很多，浅估算会让预算形同虚设。
    """
    if df is None:
        return 0
    try:
        return int(df.memory_usage(deep=True).sum())
    except Exception:
        return 0


def _col_meta_bytes(metadata) -> int:
    """`col_meta` 的真实量级：列名 + 每列三个字符串。

    1702 列那档是几十 KB 量级。`_parse_value_bytes` 若继续按 `64 × len(metadata)` 算，
    它会被估成 64 字节，1536MB 那条预算就成了自欺的数字（判据 J7）。
    """
    col_meta = metadata.get('col_meta') if isinstance(metadata, dict) else None
    if not isinstance(col_meta, dict):
        return 0
    total = 0
    for name, entry in col_meta.items():
        total += len(str(name))
        if isinstance(entry, dict):
            total += sum(len(str(v)) for v in entry.values())
    return total


def _parse_value_bytes(value) -> int:
    """``(df, metadata, format_type)`` 三元组的缓存占用（metadata 按真实量级）。"""
    df = value[0] if isinstance(value, tuple) else None
    total = _frame_bytes(df)
    if isinstance(value, tuple) and isinstance(value[1], dict):
        meta = value[1]
        total += 64 * (len(meta) - (1 if 'col_meta' in meta else 0))
        total += _col_meta_bytes(meta)
    return total


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
        """淘汰最旧条目直到总量 ≤ target；至少保留一条（与 _store 一致）。"""
        with self._cv:
            target = max(0, int(target_bytes))
            while self._total > target and len(self._data) > 1:
                _, (_, freed) = self._data.popitem(last=False)
                self._total -= freed
                self._evictions += 1

    def get_or_compute(self, key, compute, size_of=_parse_value_bytes, store_if=None):
        """返回 key 对应的值，必要时由当前线程计算并放入缓存。

        ``store_if`` 由调用方定义什么值值得占位；默认 None＝无条件存。
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
            finally:
                with self._cv:
                    self._pending.discard(key)
                    self._cv.notify_all()
            if store_if is None or store_if(value):
                self._store(key, value, size_of(value))
            return value

    def put(self, key, value, size_of=_parse_value_bytes) -> None:
        """直接写入一条缓存（不做单飞，也不返回结果）。

        上传链路已经把文件解析成 DataFrame，这里把结果写透进缓存，
        省掉用户首次打开时的第二次解析。

        ``notify_all`` 是必须的：同一 key 可能已有别的线程正在
        ``get_or_compute`` 里 ``self._cv.wait()`` 等这个 key 的结果，
        只写不唤醒的话它们会一直等到超时后重算，写透就白做了。
        """
        with self._cv:
            self._store(key, value, size_of(value))
            self._cv.notify_all()

    def _store(self, key, value, nbytes) -> None:
        with self._cv:
            if nbytes > self._budget:
                return
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
    dedup work failure values never enter the cache at all
    (``store_if=_parse_succeeded``), so that example can no longer
    occur. The conclusion is unchanged — mtime stays in the key, now
    argued by the success-entry invalidation above.
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
        metadata['col_meta'] = build_col_meta(df, metadata)
        return df, metadata, format_type
    except Exception as exc:
        logger.warning("_cached_parse(%s, %s, %s) failed: %s", file_id, owner_id, path_key, exc)
        return None, None, None


def _parse_succeeded(value) -> bool:
    """「这条值值得占缓存位」的唯一判据。

    三种失败形状（路径不存在 / parser 返回 df=None / 抛异常兜成 (None, None, None)）都不该存：
    `_parse_value_bytes` 给它们算 0 字节，而 `_store` 的淘汰循环只在**总量超预算**时逐条，
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
    if 'col_meta' not in metadata:
        metadata = dict(metadata)
        metadata['col_meta'] = build_col_meta(df, metadata)
    _parse_cache.put((abs_path, path_key, datafile.format_type), (df, metadata, fmt))


@lru_cache(maxsize=32)
def _cached_fail_data(file_id: int, owner_id: int, path_key: int,
                      file_path: str, format_type: str) -> Tuple[Optional[list], Optional[list], Optional[dict], Optional[dict]]:
    """Cache the full-file fail + borderline detection on top of the parsed file.

    Mirrors ``_cached_parse``: the key includes the on-disk mtime, so
    replacing the underlying file auto-invalidates. ``detect_fail_data``
    is a pure function of ``(df, metadata)`` — which themselves only
    change when the file changes — so caching the whole-file default
    result (no per-column narrowing) is safe for hot browse requests.

    Callers must treat ``fail_cells`` / ``borderline_cells`` as read-only —
    they are shared across requests. Never mutate them (e.g. no in-place
    column removal).

    Returns ``(fail_indices, fail_columns, fail_cells, borderline_cells)`` —
    any element may be ``None`` when the underlying file failed to parse.
    """
    df, metadata, fmt = _cached_parse(file_id, owner_id, path_key, file_path, format_type)
    if df is None:
        return None, None, None, None
    try:
        return detect_fail_data_with_borderline(df, metadata)
    except Exception as exc:
        logger.warning("_cached_fail_data(%s, %s, %s) failed: %s", file_id, owner_id, path_key, exc)
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

    `hits` / `misses` 算命中率；`evictions` 是预算或水位淘汰掉的，`clears` 是显式
    清空（删文件/上传覆盖）——两者混在一起会把「内存吃紧自愈」读成「用户删了文件」。
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


def clear_parse_cache() -> None:
    """Drop the in-memory parsed-file caches.

    Neither cache evicts by key, so we clear them wholesale. Call this after
    deleting DataFile rows so a deleted (or replaced) file can never be
    served from a stale cache entry. Entries re-populate lazily on the next
    access, so the only cost is a re-parse on demand.
    """
    _parse_cache.clear()
    _cached_fail_data.cache_clear()
