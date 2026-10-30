"""Shared helper functions for analysis views."""

import math
import os
from typing import Dict, Set

import pandas as pd

from apps.datafiles.lookup import owned_files_by_pk, valid_file_ids
from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.datafiles.utils import resolve_file_path
from apps.common.params import get_param

# Low-CPK set cache for the fast path: evaluating every column (IQR + CPK)
# is the dominant cost of the filter chain (~100-200 ms on a 10k-row file),
# and the fast path runs on every config toggle / file switch.  The key
# carries the file's mtime+size so a re-parsed file invalidates the entry.
_low_cpk_cache: Dict[tuple, Set[str]] = {}


def cached_low_cpk_items(datafile, user_id: int, df, metadata,
                         threshold: float, iqr_multiplier: float,
                         data_only_bin1: bool) -> Set[str]:
    """低 CPK 参数集合（跨 histogram/multi_lot/correlation 端点共享缓存）。

    key 含 (user, file, threshold, iqr, bin1) + mtime+size，文件重解析自动失效。
    """
    key = (user_id, datafile.id, threshold, iqr_multiplier, data_only_bin1)
    try:
        st = os.stat(resolve_file_path(datafile.file_path))
        key += (st.st_mtime_ns, st.st_size)
    except (OSError, AttributeError):
        # file missing / test fakes without file_path → no mtime guard
        key += (0, 0)
    cached = _low_cpk_cache.get(key)
    if cached is not None:
        return cached
    from apps.analysis.services.statistics import filter_bin1_rows, compute_low_cpk_test_items
    work_df = filter_bin1_rows(df, metadata) if data_only_bin1 else df
    result = set(compute_low_cpk_test_items(
        work_df, metadata, threshold, iqr_multiplier=iqr_multiplier))
    if len(_low_cpk_cache) > 500:
        # 简单上限：key 含 mtime+size 天然随文件重解析失效，全清成本低
        _low_cpk_cache.clear()
    _low_cpk_cache[key] = result
    return result


def get_bool_param(request, key, default=False):
    """Parse a boolean request param (JSON body or query string) with the
    same 'true'/'1'/'yes' tolerance used across the analysis views."""
    return str(get_param(request, key, '')).lower() in ('true', '1', 'yes')


def parse_filter_flags(request):
    """解析单文件数据筛选的 5 个开关（忽略无Limit/忽略无测试值/仅用Pass(Bin1)/
    仅显示Fail测试项/仅低CPK项）+ iqr_multiplier。

    多文件分析与相关性端点与 histogram 共用同一口径（2026-08-20）：
    消费方须保证 fail 集合基于全量 df 预计算（bin1 过滤前）。
    """
    from apps.common.params import get_param_float
    return {
        'ignore_no_limit': get_bool_param(request, 'ignore_no_limit'),
        'ignore_no_test_value': get_bool_param(request, 'ignore_no_test_value'),
        'data_only_bin1': get_bool_param(request, 'data_only_bin1'),
        'only_fail_test_item': get_bool_param(request, 'only_fail_test_item'),
        'only_low_cpk': get_bool_param(request, 'only_low_cpk'),
        'iqr_multiplier': get_param_float(request, 'iqr_multiplier', 1.5),
    }


def get_cpk_b_threshold(user):
    """用户的 B 级 CPK 阈值 = 「仅低 CPK 项」筛选的判定线。

    单一事实来源已上移到 apps.common.user_settings.get_cpk_thresholds（A/B/C 三值
    一起读，供分级/警报/导出共用），这里保留原签名与「缺失回退 1.33」语义，
    避免既有调用点与替身型测试同时改两处。
    """
    from apps.common.user_settings import get_cpk_thresholds
    return get_cpk_thresholds(user).cpk_b


def clean_data(data):
    if isinstance(data, list):
        return [clean_data(item) for item in data]
    elif isinstance(data, dict):
        return {k: clean_data(v) for k, v in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    else:
        return data


def _filter_blank_params(params):
    """Drop fully-blank / empty / whitespace-only column names from a params list.

    Some parsers (CTA8280F trailing comma, etc.) yield an unnamed column
    whose empty-string name passes the dtype check (all-NaN is float64)
    but cannot be selected by users and would 400 the analysis endpoints
    with `param_not_found`. Stripping blanks here keeps the param
    selector honest and protects the QQ plot / histogram / wafer_map
    fast paths uniformly.
    """
    return [p for p in params if p and str(p).strip()]


def _sanitize_numeric_params(df, params):
    """Filter params to only those that are valid numeric columns with data.

    Removes: blank names, all-NaN columns, non-numeric columns, duplicate columns.
    """
    # Deduplicate columns first
    duplicated = df.columns.duplicated()
    if duplicated.any():
        df = df.loc[:, ~duplicated]
    present = [p for p in params if p and str(p).strip() and p in df.columns]
    candidates = df.iloc[:, df.columns.get_indexer(list(dict.fromkeys(present)))]
    has_data = candidates.notna().any()
    valid = set()
    for p, dtype in candidates.dtypes.items():
        # Skip all-NaN columns
        if not has_data[p]:
            continue
        # Skip non-numeric
        if not pd.api.types.is_numeric_dtype(dtype):
            continue
        # Skip bool columns (real data has ``Dut_Pass``): ``is_numeric_dtype``
        # returns True for bool, but a pass/fail flag is not a measurable
        # parameter — a boxplot / correlation row for it is meaningless, and
        # before ``ensure_numeric`` gained ``.astype(float)`` it also crashed
        # ``.quantile()`` with "numpy boolean subtract".
        # 常量列（nunique()==1）**不排除**：全一致的列（如整文件 pass 的
        # SW_Bin、数字 trim code）画箱线图是合法的，而相关矩阵的对角线/
        # NaN 已在 compute_correlation_matrix 里从根上修好（fill_diagonal(1.0)
        # + 非对角 NaN → None），不需要在这里靠剔列规避。
        if pd.api.types.is_bool_dtype(dtype):
            continue
        valid.add(p)
    return [p for p in present if p in valid]


def _load_df_from_request(request):
    file_id = request.data.get('file_id') or request.query_params.get('file_id')
    if not file_id:
        return None, None, None, 'file_id_required'
    try:
        file_id = int(file_id)
    except (TypeError, ValueError):
        # 直连 API / 被篡改的 URL 可绕过前端下拉，非数字 id 是客户端错误不是 500
        return None, None, None, 'file_id_invalid'
    datafile = DataFile.objects.filter(pk=file_id, owner=request.user).first()
    if datafile is None:
        return None, None, None, 'file_not_found'
    df, metadata, fmt = get_cached_parsed_file(file_id, request.user.pk, datafile)
    if df is None and fmt is not None:
        # file_id valid but file not on disk or parse failed
        return None, None, None, 'file_not_found_or_parse_failed'
    if df is None:
        return None, None, None, 'file_not_found'
    # Deduplicate columns to prevent DataFrame-vs-Series issues downstream.
    # Skip the full-table copy when there are no duplicates (the common
    # case): a .loc copy of a 10k×188 frame costs ~100ms per request, and
    # the analysis views never mutate the returned frame in place.
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    return df, datafile, metadata, None


def _load_files_from_request(request, file_ids):
    """Load multiple files from request for cross-file analysis.

    Returns list of dicts with df, metadata, file_id, filename, timestamp.

    取数（按 owner 批量、按 PK 分块、坏 id 拦在查询之外）的口径住在
    ``apps/datafiles/lookup.py`` —— 批次报表那边是同一条取数的**另一个**消费者。
    这里留的是 analysis 自己的语义：**坏 / 缺 / 解析失败的 id 静默跳过**
    （那边判 404），并按输入序回放 ⇒ 重复 id 出多条。
    """
    normalized_ids = valid_file_ids(file_ids)
    if not normalized_ids:
        return []
    datafiles = owned_files_by_pk(request.user, normalized_ids)
    file_data_list = []
    # Bulk lookup deduplicates rows; iterate the IDs to preserve order and repeats.
    for file_id in normalized_ids:
        try:
            datafile = datafiles.get(file_id)
            if datafile is None:
                continue

            df, metadata, fmt = get_cached_parsed_file(file_id, request.user.pk, datafile)
            if df is None:
                continue

            file_data_list.append({
                'df': df,
                'metadata': metadata,
                'file_id': datafile.id,
                'filename': datafile.filename,
                'timestamp': datafile.created_at.strftime('%Y-%m-%d %H:%M:%S') if datafile.created_at else ''
            })
        except Exception:
            continue
    return file_data_list
