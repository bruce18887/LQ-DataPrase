import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import get_parser, BaseATEParser

logger = logging.getLogger(__name__)


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


@lru_cache(maxsize=64)
def _cached_parse(file_id: int, owner_id: int, path_key: int,
                  file_path: str, format_type: str) -> Tuple[Optional[pd.DataFrame], Optional[dict], Optional[str]]:
    """Parse a DataFile and cache the result in memory.

    ``path_key`` is the on-disk mtime in nanoseconds of the file at the
    time the caller resolved it. Including it in the cache key ensures
    the cache auto-invalidates whenever the file's path or content
    changes — the caller re-reads ``DataFile.file_path`` and computes
    ``_disk_mtime_ns(file_path)`` on every call, so a stale entry from
    a previous (broken) path is never served. Caches up to 64 parsed
    DataFrames keyed on the triple ``(file_id, owner_id, path_key)``.

    ``file_path`` / ``format_type`` 由调用方解析（避免缓存函数内部再查库）。
    调用方必须已通过 DataFile 查询验证归属。

    Callers must NOT mutate the returned DataFrame — treat it as
    read-only. If you need a mutable copy, call ``.copy()`` yourself.

    Returns ``(df, metadata, format_type)``.  Any element may be
    ``None`` on failure (missing file, parse error, etc.).
    """
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
    path_key = _disk_mtime_ns(datafile.file_path)
    return _cached_parse(file_id, owner_id, path_key, datafile.file_path, datafile.format_type)


def clear_parse_cache() -> None:
    """Drop the in-memory parsed-file cache.

    ``functools.lru_cache`` has no per-key eviction, so we clear the whole
    cache. Call this after deleting DataFile rows so a deleted (or replaced)
    file can never be served from a stale cache entry. Entries re-populate
    lazily on the next access, so the only cost is a re-parse on demand.
    """
    _cached_parse.cache_clear()
