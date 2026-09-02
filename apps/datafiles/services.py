import logging
import os
import threading
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from apps.analysis.services.statistics import detect_fail_data
from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import get_parser, BaseATEParser
from apps.datafiles.utils import resolve_file_path

logger = logging.getLogger(__name__)

# 解析缓存按**字节预算**限流，不是按条数：单只大文件（10 万行 × 800 列）
# 解析后约 667MB，历史上 ``maxsize=64`` 的 64 只就足以吃掉数 GB 常驻内存。
# 可用 LQDP_PARSE_CACHE_MB 覆盖（Electron 内嵌后端与 32 位受限环境需要更小值）。
PARSE_CACHE_BUDGET_BYTES = int(os.environ.get('LQDP_PARSE_CACHE_MB', '1536')) * 1024 * 1024


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


def _parse_value_bytes(value) -> int:
    """``(df, metadata, format_type)`` 三元组的缓存占用（metadata 只算量级）。"""
    df = value[0] if isinstance(value, tuple) else None
    total = _frame_bytes(df)
    if isinstance(value, tuple) and isinstance(value[1], dict):
        total += 64 * len(value[1])
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

    def get_or_compute(self, key, compute, size_of=_parse_value_bytes):
        """返回 key 对应的值，必要时由当前线程计算并放入缓存。"""
        while True:
            with self._cv:
                entry = self._data.get(key)
                if entry is not None:
                    self._data.move_to_end(key)
                    return entry[0]
                if key in self._pending:
                    # 另一个线程正在算：等它发布结果或失败后重来一轮
                    self._cv.wait()
                    continue
                self._pending.add(key)
            try:
                value = compute()
            finally:
                with self._cv:
                    self._pending.discard(key)
                    self._cv.notify_all()
            self._store(key, value, size_of(value))
            return value

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


_parse_cache = _BytesLRUCache(PARSE_CACHE_BUDGET_BYTES)


def _disk_mtime_ns(file_path: str) -> int:
    """Return the on-disk mtime in nanoseconds, or 0 if the file is gone.

    Used as a cache key suffix so that re-pointing a DataFile's
    ``file_path`` (e.g. after the project is moved on disk) or replacing
    the underlying file automatically invalidates the in-memory cache.
    Without this, ``_cached_parse`` would happily hand back a cached
    ``(None, None, fmt)`` from the previous (broken) path and the
    analysis endpoints would 400 with
    ``file_not_found_or_parse_failed`` even after the DB row was fixed.
    """
    try:
        return os.stat(file_path).st_mtime_ns
    except OSError:
        return 0


def _cached_parse(file_id: int, owner_id: int, path_key: int,
                  file_path: str, format_type: str) -> Tuple[Optional[pd.DataFrame], Optional[dict], Optional[str]]:
    """Parse a DataFile and cache the result in memory (byte-budgeted LRU).

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

    Returns ``(df, metadata, format_type)``.  Any element may be
    ``None`` on failure (missing file, parse error, etc.).
    """
    key = (file_id, owner_id, path_key, file_path)
    return _parse_cache.get_or_compute(
        key, lambda: _parse_file_uncached(file_id, owner_id, path_key,
                                         file_path, format_type))


def _parse_file_uncached(file_id: int, owner_id: int, path_key: int,
                         file_path: str, format_type: str):
    try:
        if not os.path.exists(file_path):
            return None, None, format_type  # hint: file not on disk
        parser = get_parser(format_type)
        df, metadata = parser.parse(file_path)
        if df is None:
            return None, metadata, format_type
        return df, metadata, format_type
    except Exception as exc:
        logger.warning("_cached_parse(%s, %s, %s) failed: %s", file_id, owner_id, path_key, exc)
        return None, None, None


def get_cached_parsed_file(file_id: int, owner_id: int, datafile=None) -> Tuple[Optional[pd.DataFrame], Optional[dict], Optional[str]]:
    """Public wrapper around ``_cached_parse``.

    Resolves the current ``DataFile.file_path`` and uses its on-disk
    mtime as part of the cache key, so updating ``file_path`` (e.g.
    after the project root moved) automatically invalidates the cache.

    ``datafile``：调用方已加载的 DataFile 对象（带 owner 归属校验）时传入，
    可省去一次 DB 查询——热路径（导出/浏览）一次请求只查一次库。

    Returns ``(df, metadata, format_type)`` — same semantics as
    ``parser.parse()`` but backed by a 64-entry LRU cache.
    """
    if datafile is None:
        datafile = DataFile.objects.filter(pk=file_id, owner_id=owner_id).first()
    if datafile is None:
        return None, None, None
    # 缓存 key 基于解析后的绝对路径 mtime，相对/绝对混存天然兼容
    abs_path = resolve_file_path(datafile.file_path)
    path_key = _disk_mtime_ns(abs_path)
    return _cached_parse(file_id, owner_id, path_key, abs_path, datafile.format_type)


@lru_cache(maxsize=32)
def _cached_fail_data(file_id: int, owner_id: int, path_key: int,
                      file_path: str, format_type: str) -> Tuple[Optional[list], Optional[list], Optional[dict]]:
    """Cache the full-file fail detection on top of the parsed file.

    Mirrors ``_cached_parse``: the key includes the on-disk mtime, so
    replacing the underlying file auto-invalidates. ``detect_fail_data``
    is a pure function of ``(df, metadata)`` — which themselves only
    change when the file changes — so caching the whole-file default
    result (no per-column narrowing) is safe for hot browse requests.

    Callers must treat ``fail_cells`` as read-only — it is shared across
    requests. Never mutate it (e.g. no in-place column removal).

    Returns ``(fail_indices, fail_columns, fail_cells)`` — any element
    may be ``None`` when the underlying file failed to parse.
    """
    df, metadata, fmt = _cached_parse(file_id, owner_id, path_key, file_path, format_type)
    if df is None:
        return None, None, None
    try:
        return detect_fail_data(df, metadata)
    except Exception as exc:
        logger.warning("_cached_fail_data(%s, %s, %s) failed: %s", file_id, owner_id, path_key, exc)
        return None, None, None


def get_cached_fail_data(file_id: int, owner_id: int, datafile=None) -> Tuple[Optional[list], Optional[list], Optional[dict]]:
    """Public wrapper around ``_cached_fail_data`` — same resolution
    pattern as ``get_cached_parsed_file`` (mtime-based auto invalidation,
    ``datafile`` param skips one DB query on hot paths).

    Returns ``(fail_indices, fail_columns, fail_cells)``; elements may be
    ``None`` on failure (missing file, parse error, etc.).
    """
    if datafile is None:
        datafile = DataFile.objects.filter(pk=file_id, owner_id=owner_id).first()
    if datafile is None:
        return None, None, None
    abs_path = resolve_file_path(datafile.file_path)
    path_key = _disk_mtime_ns(abs_path)
    return _cached_fail_data(file_id, owner_id, path_key, abs_path, datafile.format_type)


def clear_parse_cache() -> None:
    """Drop the in-memory parsed-file caches.

    Neither cache evicts by key, so we clear them wholesale. Call this after
    deleting DataFile rows so a deleted (or replaced) file can never be
    served from a stale cache entry. Entries re-populate lazily on the next
    access, so the only cost is a re-parse on demand.
    """
    _parse_cache.clear()
    _cached_fail_data.cache_clear()
