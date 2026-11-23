"""文件隐藏（软隐藏）的过滤内核。

隐藏只影响「选择文件的候选列表」：列表端点只在 ``action == 'list'`` 时排除隐藏，
``options`` 端点恒定排除；详情/更新/删除/按 id 取数一律不受限（软隐藏）。
参数约定（仅 list 端点）：

- 缺省                 → 只返回未隐藏
- ``?include_hidden=1`` → 返回全部（含隐藏）
- ``?hidden_only=1``    → 只返回已隐藏（优先于 include_hidden）
"""

VISIBLE = 'visible'
ALL = 'all'
HIDDEN = 'hidden'

_TRUE_VALUES = {'1', 'true', 'yes', 'on'}


def visibility_mode(query_params) -> str:
    """把查询参数解析成三种可见性模式：visible / all / hidden。"""
    if str(query_params.get('hidden_only', '')).strip().lower() in _TRUE_VALUES:
        return HIDDEN
    if str(query_params.get('include_hidden', '')).strip().lower() in _TRUE_VALUES:
        return ALL
    return VISIBLE


def apply_visibility(queryset, query_params, action: str):
    """仅在 list 动作上应用隐藏过滤；其它动作原样返回（软隐藏边界）。"""
    if action != 'list':
        return queryset
    mode = visibility_mode(query_params)
    if mode == HIDDEN:
        return queryset.filter(is_hidden=True)
    if mode == ALL:
        return queryset
    return queryset.filter(is_hidden=False)
