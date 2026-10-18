"""ag-grid IRM 的算子层：服务端列过滤与排序。

从 `apps/datafiles/views/browse_views.py` 搬过来，**刻意不 import Django**：
`/browse/` 视图与作业化后的导出 worker 要用同一套算子，而 worker 跑在
`ProcessPoolExecutor` 的 spawn 子进程里（没有 `django.setup()`）。
留在视图模块里就等于让 worker 去 import DRF —— 逻辑只有一份是这里存在的理由。
"""

import pandas as pd

_NUMBER_FILTER_OPS = {
    'equals': lambda s, v: s == v,
    'notEqual': lambda s, v: s != v,
    'lessThan': lambda s, v: s < v,
    'lessThanOrEqual': lambda s, v: s <= v,
    'greaterThan': lambda s, v: s > v,
    'greaterThanOrEqual': lambda s, v: s >= v,
}
_TEXT_FILTER_OPS = {
    'equals': lambda s, v: s.str.lower() == v.lower(),
    'notEqual': lambda s, v: s.str.lower() != v.lower(),
    'contains': lambda s, v: s.str.lower().str.contains(v.lower(), na=False, regex=False),
    'notContains': lambda s, v: ~s.str.lower().str.contains(v.lower(), na=False, regex=False),
    'startsWith': lambda s, v: s.str.lower().str.startswith(v.lower()),
    'endsWith': lambda s, v: s.str.lower().str.endswith(v.lower()),
}


def apply_filter_model(df: 'pd.DataFrame', filter_model) -> 'pd.DataFrame':
    """应用 ag-grid IRM filterModel（服务端列过滤，方案 A）。

    逐列 AND 组合；白名单算子，未知列/未知 type/非法值一律宽容跳过（不 400——
    前端只发合法列，防御未知字段）。语义对齐 ag-grid 默认行为：
    * 数值比较前 ``to_numeric(errors='coerce')``——非数值转 NaN，参与比较恒 False，
      即列过滤激活时空值/非数值行被排除（ag-grid blank 默认语义）；
    * 文本过滤大小写不敏感（lower 比较），contains 用 ``regex=False`` 防正则字符；
    * ``empty``/``notEmpty`` 匹配空值（NaN 或空串）。
    """
    for col, cond in filter_model.items():
        if col not in df.columns or not isinstance(cond, dict):
            continue
        ftype = cond.get('filterType')
        op = cond.get('type')
        if ftype == 'number':
            s = pd.to_numeric(df[col], errors='coerce')
            if op == 'inRange':
                lo, hi = cond.get('filter'), cond.get('filterTo')
                try:
                    df = df[(s >= float(lo)) & (s <= float(hi))]
                except (TypeError, ValueError):
                    continue
            elif op in _NUMBER_FILTER_OPS and cond.get('filter') is not None:
                try:
                    df = df[_NUMBER_FILTER_OPS[op](s, float(cond['filter']))]
                except (TypeError, ValueError):
                    continue
            elif op == 'empty':
                df = df[s.isna()]
            elif op == 'notEmpty':
                df = df[s.notna()]
        elif ftype == 'text':
            s = df[col].fillna('').astype(str)
            if op in _TEXT_FILTER_OPS and cond.get('filter'):
                df = df[_TEXT_FILTER_OPS[op](s, str(cond['filter']))]
            elif op == 'empty':
                df = df[df[col].isna() | (s == '')]
            elif op == 'notEmpty':
                df = df[~(df[col].isna() | (s == ''))]
        elif ftype == 'set':
            values = cond.get('values') or []
            if values:
                df = df[df[col].astype(str).isin([str(v) for v in values])]
    return df


def apply_sort(df: 'pd.DataFrame', sort_model) -> 'pd.DataFrame':
    """稳定排序（IRM 块间顺序一致性的硬要求）+ NaN 恒排最后。

    每次 getRows 都全量重算排序，若排序不稳定/不确定，不同块请求会对
    并列行产生不同顺序 → 页面行重复/跳行。``kind='mergesort'`` 保证
    同一输入下块间顺序确定。混合类型 object 列（QR_Code 的 "None"+数字）
    sort_values 抛 TypeError → 逐列丢弃重试，该列退化为不排序。
    """
    valid = [
        (m['colId'], m['sort'])
        for m in sort_model
        if isinstance(m, dict) and m.get('colId') in df.columns and m.get('sort') in ('asc', 'desc')
    ]
    while valid:
        cols = [c for c, _ in valid]
        ascending = [s == 'asc' for _, s in valid]
        try:
            return df.sort_values(by=cols, ascending=ascending, kind='mergesort', na_position='last')
        except TypeError:
            valid = valid[:-1]  # 混类型列无法排序 → 丢弃最后一列重试
    return df
