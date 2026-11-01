"""SFTP 目录列表的排序与分页（B1 载荷封顶）。

从 ``views.py`` 拆出来：那个文件在本次改动前正好 600/600（600 行硬约束、无新增豁免），
而列表这一刀要加「先排序再切片 + 总数/截断标记」。按 ``scripts/line-limit.mjs`` 的
拆分建议把纯逻辑搬到本模块，视图只剩握手、记账与响应组装。

判据在 ``test/backend/test_sftp_list_pagination.py``（走真实端点）：分页必须是**同一
有序序列的连续片段** —— 先切片再各自排序会让两页拼起来重/漏，这条由用例直接钉住。
"""
import os
from stat import S_ISDIR

#: B1 载荷封顶（用户 2026-11-01 拍板：默认 500，上限 1000）。目录上千文件时
#: 一次全量物化 + 整体序列化会把响应推到几十 KB 以上；显式 limit 不许把这一刀绕回去。
LIST_LIMIT_DEFAULT = 500
LIST_LIMIT_MAX = 1000

SORT_KEYS = {
    'name': lambda x: x['name'].lower(),
    'mtime': lambda x: x.get('mtime', 0) or 0,
    'size': lambda x: x.get('size', 0) or 0,
    'type': lambda x: os.path.splitext(x['name'])[1].lower(),
}


def parse_pagination(query_params):
    """``(limit, offset)`` 或 ``(None, 错误说明)``。缺省 500/0，范围见上面两个常数。"""
    try:
        limit = int(query_params.get('limit', LIST_LIMIT_DEFAULT))
        offset = int(query_params.get('offset', 0))
    except (TypeError, ValueError):
        return None, 'limit 需为整数，offset 需为非负整数'
    if not 1 <= limit <= LIST_LIMIT_MAX or offset < 0:
        return None, f'limit 需在 1..{LIST_LIMIT_MAX}，offset 需不为负'
    return (limit, offset), None


def page_entries(attrs, *, sort_by='name', sort_order='asc', limit=LIST_LIMIT_DEFAULT,
                 offset=0):
    """把 ``listdir_attr`` 结果排好序再切页，返回 ``(本页 items, 总数, 是否被截断)``。"""
    items = []
    for entry in attrs:
        is_dir = S_ISDIR(entry.st_mode)
        items.append({
            'name': entry.filename,
            'is_dir': is_dir,
            'size': entry.st_size if not is_dir else 0,
            'mtime': entry.st_mtime,
        })

    # Sort: directories first (except when sorting by time, which is pure chronological)
    key_fn = SORT_KEYS.get(sort_by, SORT_KEYS['name'])
    reverse = sort_order == 'desc'
    if sort_by == 'mtime':
        items.sort(key=key_fn, reverse=reverse)
    else:
        items.sort(key=lambda x: (not x['is_dir'], key_fn(x)), reverse=reverse)

    total = len(items)
    page = items[offset:offset + limit]
    return page, total, offset + len(page) < total
