"""批量参数分布图的测试项分组契约（纯函数，不依赖 Django）。

规则匹配只在**前端**执行；本模块只校验前端发来的「已解析分组」并收敛每页上限。
"""

OTHER_GROUP_NAME = '其他'
DEFAULT_MAX_ITEMS_PER_SHEET = 50
ALLOWED_MAX_ITEMS_PER_SHEET = (30, 50, 100)


class GroupingError(ValueError):
    """带机器码与字段名的校验错误（视图转成 400 + extra.field）。"""

    def __init__(self, code: str, field: str):
        super().__init__(code)
        self.code = code
        self.field = field


def normalize_batch_grouping(raw_groups, raw_max, params, fmt='xlsx'):
    """校验并收敛分组请求；无分组返回 ``(None, DEFAULT_MAX_ITEMS_PER_SHEET)``。

    只做结构校验：参数是否真的存在于文件列由装配层按现有语义过滤
    （当前 ``params`` 同样只跳过不存在的列）。
    """
    if raw_groups in (None, [], ()):
        return None, DEFAULT_MAX_ITEMS_PER_SHEET
    if fmt == 'pptx':
        raise GroupingError('groups_not_supported', 'groups')
    if not isinstance(raw_groups, list):
        raise GroupingError('invalid_groups', 'groups')

    max_items = DEFAULT_MAX_ITEMS_PER_SHEET if raw_max is None else raw_max
    if isinstance(max_items, bool) or not isinstance(max_items, int) \
            or max_items not in ALLOWED_MAX_ITEMS_PER_SHEET:
        raise GroupingError('invalid_page_size', 'max_items_per_sheet')

    selected = set(params or [])
    normalized = []
    union = set()
    for group in raw_groups:
        if not isinstance(group, dict):
            raise GroupingError('invalid_groups', 'groups')
        name = group.get('name')
        members = group.get('params')
        if not isinstance(name, str) or not name.strip():
            raise GroupingError('invalid_groups', 'groups')
        if not isinstance(members, list) or not members \
                or not all(isinstance(m, str) for m in members):
            raise GroupingError('invalid_groups', 'groups')
        if len(set(members)) != len(members) or not set(members) <= selected:
            raise GroupingError('invalid_groups', 'groups')
        union |= set(members)
        normalized.append({'name': name.strip(), 'params': list(members)})
    if union != selected:
        raise GroupingError('invalid_groups', 'groups')
    return normalized, max_items
