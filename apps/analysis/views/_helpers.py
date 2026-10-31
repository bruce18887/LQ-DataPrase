"""Shared helper functions for analysis views."""

import math
import os
from typing import Set

import pandas as pd

from apps.common.keyed_lru import KeyedLRU
from apps.common.params import get_param
from apps.datafiles.lookup import owned_files_by_pk, valid_file_ids
from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.datafiles.utils import resolve_file_path

# Low-CPK set cache for the fast path: evaluating every column (IQR + CPK)
# is the dominant cost of the filter chain (~100-200 ms on a 10k-row file),
# and the fast path runs on every config toggle / file switch.  The key is
# the content coordinates (resolved path + mtime + size), so the same
# physical file's rows share one entry and a re-parsed file invalidates it.
#
# 形状复用 `apps/common/keyed_lru.py`（与仪表板汇总缓存同一份实现）：按条数封顶的 LRU +
# 每 key 单飞。旧写法是 plain dict + 「超 500 条 wholesale clear」——一次清空会把所有
# 还活着的文件一起打回冷启动，而且并发 miss 各算一遍。
_LOW_CPK_CACHE_MAX_ENTRIES = 500
_low_cpk_cache = KeyedLRU(_LOW_CPK_CACHE_MAX_ENTRIES)


def _low_cpk_cache_key(datafile, threshold, iqr_multiplier, data_only_bin1):
    """低 CPK 集合的内容坐标键：``(路径或行号, mtime_ns, size, format_type, threshold, iqr, bin1)``。

    路径族的第一元是 ``resolve_file_path(datafile.file_path)`` —— 盘上同一只文件的两行、
    两个 owner 解析出同一个字符串，因此共享一条；``datafile.id`` 不在键里，按行号做键
    会把同一只物理文件拆成两条（与解析/检测缓存同一条论证）。
    ``format_type`` 必须在键里，理由与解析缓存逐字相同：``df``/``metadata`` 是
    ``get_parser(datafile.format_type)`` 的产物，而 ``DataFile.file_path`` 没有唯一约束
    ⇒ 同一路径的两行可以标成不同格式、走不同 parser、bin 列也不同，漏掉它会让一行
    命中另一行那套列的集合（判据：本文件的同路径双格式用例）。
    路径读不出来时（测试替身没有 ``file_path``、文件已被删、路径为空）退回
    ``(datafile.id, 0, 0, format_type, ...)``：真实族第一元是 ``str``、退回族是 ``int``
    行号，两只键族不可能相等 ⇒ 退回不会与真实路径串味。
    """
    format_type = datafile.format_type
    try:
        path = resolve_file_path(datafile.file_path)
        if path:
            st = os.stat(path)
            return (path, st.st_mtime_ns, st.st_size, format_type,
                    threshold, iqr_multiplier, data_only_bin1)
    except (OSError, AttributeError):
        pass
    return (datafile.id, 0, 0, format_type, threshold, iqr_multiplier, data_only_bin1)


def cached_low_cpk_items(datafile, df, metadata,
                         threshold: float, iqr_multiplier: float,
                         data_only_bin1: bool) -> Set[str]:
    """低 CPK 参数集合（跨 histogram/multi_lot/correlation 端点共享缓存）。

    key 是**内容坐标** ``(解析后的绝对路径, mtime_ns, size, format_type, threshold,
    iqr_multiplier, data_only_bin1)``（形状见 ``_low_cpk_cache_key``）：集合是
    ``(df, metadata, threshold, iqr_multiplier, data_only_bin1)`` 的纯函数。df/metadata
    不是「只随盘上文件变」：它们由 ``get_parser(datafile.format_type)`` 产出，同一路径
    的两行可以标成不同格式（``DataFile.file_path`` 无唯一约束）⇒ ``format_type`` 与
    内容坐标一起进键，同一坐标才必然同一份结果。``datafile.id`` 与请求用户都**不进键**：
    行号会把同一只物理文件的两行（两个 owner）拆成两条；``threshold`` 已经把「用户设置」
    这唯一一条用户输入折成了实参，两用户同阈值共享同一只 set 是正确行为（判据见
    ``apps/analysis/tests_low_cpk_cache.py``）。

    函数内 import 是承重的（不是防环）：``_helpers`` 经 ``apps.datafiles.services`` 本来
    就在导入期加载了 statistics 包，所以搬到模块级不会成环；但搬上去会把名字**冻在导入期**，
    ``mock.patch('apps.analysis.services.statistics.compute_low_cpk_test_items')``
    （R6③ patch 消费方绑定）就静默失效了。每调用一次的 dict 查找成本可忽略。
    """
    key = _low_cpk_cache_key(
        datafile, threshold, iqr_multiplier, data_only_bin1)

    def compute():
        from apps.analysis.services.statistics import (
            filter_bin1_rows, compute_low_cpk_test_items)
        work_df = filter_bin1_rows(df, metadata) if data_only_bin1 else df
        return set(compute_low_cpk_test_items(
            work_df, metadata, threshold, iqr_multiplier=iqr_multiplier))

    return _low_cpk_cache.get_or_compute(key, compute)


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
