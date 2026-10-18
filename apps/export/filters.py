"""导出请求里的网格筛选（passfail / site / filter_model / sort）。

从 `apps/export/views.py` 搬过来，**刻意不 import Django**：作业化的导出跑在
`ProcessPoolExecutor` 的 spawn 子进程里（见 `apps/jobs/runner.py`），那边只能
吃纯 pandas。视图与 worker 共用这一份，导出结果才可能和表格里看到的一致。
"""

import json

from apps.analysis.services.statistics import detect_fail_data, get_site_column
from apps.common.grid_filters import apply_filter_model, apply_sort

# 与 /browse/ 的 IRM 参数同名；这四个键就是「网格当前显示的是什么」的全部语义。
GRID_FILTER_KEYS = ('site_filter', 'filter_model', 'passfail', 'sort_model')


def grid_filters_from(payload) -> dict:
    """从请求/params 快照里只摘出算子字段，其余（file_id 等）留在主进程。"""
    return {k: payload[k] for k in GRID_FILTER_KEYS if payload.get(k)}


def parse_grid_model(raw, expect):
    """Parse ag-grid sort/filter model from an export request.

    Frontend sends JSON-encoded ``sort_model`` (array) / ``filter_model``
    (object) identical to /browse/ IRM params. Malformed or mistyped values
    degrade to empty (no sorting/filtering) instead of 400 — export must not
    fail because a filter widget sent something odd.
    """
    if not raw:
        return [] if expect == list else {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return [] if expect == list else {}
    return parsed if isinstance(parsed, expect) else ([] if expect == list else {})


def apply_export_filters(df, metadata, request_data):
    """Apply passfail/site/sort/filter_model to ``df`` like /browse/ does.

    Shared by to_excel/to_csv so both exports match what the grid shows.
    Filter order mirrors DataBrowserView: site → filter_model → passfail → sort.
    """
    # 惰性复制：df 是解析缓存里的共享只读对象，但下面每个分支都会产出新对象
    # （df[mask] / sort_values / reset_index），有过滤时先整表 copy 纯属浪费
    # （275MB 文件实测 328ms）。无过滤时由返回前的兜底补上复制，下游永远
    # 拿到自有对象，语义与「进门就 copy」完全等价。
    export_df = df

    site_filter = request_data.get('site_filter') or ''
    if site_filter and site_filter != '全部':
        site_col = get_site_column(export_df)
        if site_col:
            export_df = export_df[export_df[site_col].astype(str) == str(site_filter)]

    filter_model = parse_grid_model(request_data.get('filter_model'), dict)
    if filter_model:
        export_df = apply_filter_model(export_df, filter_model)

    passfail = request_data.get('passfail') or ''
    if passfail and passfail != '全部':
        fail_indices, _, _ = detect_fail_data(export_df, metadata)
        fail_set = set(fail_indices)
        if str(passfail).lower() == 'fail':
            export_df = export_df.loc[export_df.index.isin(fail_set)]
        elif str(passfail).lower() == 'pass':
            export_df = export_df.loc[~export_df.index.isin(fail_set)]
        export_df = export_df.reset_index(drop=True)

    sort_model = parse_grid_model(request_data.get('sort_model'), list)
    if sort_model:
        export_df = apply_sort(export_df, sort_model)

    # 兜底：所有分支都因参数缺失/不生效而没产出新对象时，这里才真正复制。
    # 绝不能把共享缓存的引用交给下游（下游一旦原地改列会污染缓存）。
    if export_df is df:
        export_df = df.copy()

    return export_df
