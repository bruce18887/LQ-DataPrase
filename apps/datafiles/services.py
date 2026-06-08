import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import get_parser, BaseATEParser

logger = logging.getLogger(__name__)


@lru_cache(maxsize=64)
def _cached_parse(file_id: int, owner_id: int) -> Tuple[Optional[pd.DataFrame], Optional[dict], Optional[str]]:
    """Parse a DataFile and cache the result in memory.

    Caches up to 64 parsed DataFrames keyed by ``(file_id, owner_id)``.
    Callers must NOT mutate the returned DataFrame — treat it as read-only.
    If you need a mutable copy, call ``.copy()`` yourself.

    Returns ``(df, metadata, format_type)``.  Any element may be ``None``
    on failure (missing file, parse error, etc.).
    """
    try:
        qs = DataFile.objects.filter(pk=file_id, owner_id=owner_id)
        datafile = qs.first()
        if datafile is None:
            return None, None, None
        if not os.path.exists(datafile.file_path):
            return None, None, datafile.format_type  # hint: file not on disk
        parser = get_parser(datafile.format_type)
        df, metadata = parser.parse(datafile.file_path)
        if df is None:
            return None, metadata, datafile.format_type
        return df, metadata, datafile.format_type
    except Exception as exc:
        logger.warning("_cached_parse(%s, %s) failed: %s", file_id, owner_id, exc)
        return None, None, None


def get_cached_parsed_file(file_id: int, owner_id: int) -> Tuple[Optional[pd.DataFrame], Optional[dict], Optional[str]]:
    """Public wrapper around ``_cached_parse``.

    Returns ``(df, metadata, format_type)`` — same semantics as
    ``parser.parse()`` but backed by a 64-entry LRU cache.
    """
    return _cached_parse(file_id, owner_id)


def clear_parse_cache() -> None:
    """Drop the in-memory parsed-file cache.

    ``functools.lru_cache`` has no per-key eviction, so we clear the whole
    cache. Call this after deleting DataFile rows so a deleted (or replaced)
    file can never be served from a stale cache entry. Entries re-populate
    lazily on the next access, so the only cost is a re-parse on demand.
    """
    _cached_parse.cache_clear()


def parse_and_save_datafile(file_path: str, user, filename: str, file_size: int) -> DataFile:
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        file_head = f.read(4096)
    
    format_type = BaseATEParser.identify_format(file_head)
    if format_type == 'Unknown':
        raise ValueError("无法识别的数据格式")
    
    parser = get_parser(format_type)
    df, metadata = parser.parse(file_path)
    
    if df is None:
        raise ValueError("数据解析失败")
    
    datafile = DataFile.objects.create(
        owner=user,
        filename=filename,
        file_path=file_path,
        file_size=file_size,
        format_type=format_type,
        row_count=df.shape[0],
        col_count=df.shape[1],
        program_name=metadata.get('program_name', ''),
        metadata=metadata,
        status='ready',
    )
    
    ParseHistory.objects.create(
        user=user,
        datafile=datafile,
        filename=filename,
        filepath=file_path,
        format_type=format_type,
        rows=df.shape[0],
        cols=df.shape[1],
    )
    
    return datafile
