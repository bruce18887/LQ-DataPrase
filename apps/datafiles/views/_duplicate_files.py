"""重复文件的分组、保留选择与删除（批3a · 第 3 项）。

从 ``_helpers.py`` 搬出来的理由是**行数闸**，不是口味：那份 552/600（判据
``scripts/line-limit.mjs``，无豁免），而本模块要加的「keep_ids 白名单校验」带注释放不下。
搬动本身不改一行语义；``test_parse_cache_invariant_scan.py`` 按文件钉
``evict_parse_cache_for_paths`` 的调用点归属，所以那份登记表跟着搬。

三条口径只在这里写一次，视图与前端都只引用它：

1. **分组** = ``(filename, file_size)`` 精确相等 + ``owner=user``。后者是越权防线，
   不是冗余条件（``_delete_duplicate_files`` 里那句原注释同义）。
2. **展示切片 == 处理切片**：GET 与 POST 都取 ``_group_duplicates(user)[:50]``。
   ``groups.sort`` 的键就是分组键本身 ⇒ 全序，两边切到的必然是同一批 50 组。
   这是「只删已展示的组」的**实现**，不靠两个 limit 常数互相对齐 —— 对齐写法总有一天会漂。
3. **每组恰一枚保留 id**；未指定 = 该组 id 最小（``files`` 按 id 升序，见下面
   ``_group_duplicates`` 里的 ``order_by('id')``），即历史行为。
   Task 2/3 在这里加 ``_resolve_keep_selection`` 与 ``InvalidKeepSelection``。
"""

from django.db import transaction

from apps.datafiles.models import DataFile
from apps.datafiles.services import evict_parse_cache_for_paths

from ._helpers import _delete_datafile_file_only

# GET 的展示切片与 POST 的处理切片共用这一个常数（口径 2）。
DUPLICATE_DISPLAY_LIMIT = 50


def _group_duplicates(user):
    """Group the user's files by exact (filename, file_size) match.

    Returns a list of groups, each ``{'filename', 'file_size', 'files': [...]}``
    where ``files`` is ordered by id ascending (the first entry is the
    canonical file kept when duplicates are cleaned). Groups with fewer than
    two files are dropped. Works across single and batch files.
    """
    grouped = {}
    rows = DataFile.objects.filter(owner=user).order_by('id').values(
        'id', 'filename', 'file_size', 'file_type', 'batch_name', 'sub_batch',
        'created_at',
    )
    for r in rows:
        key = (r['filename'], r['file_size'])
        group = grouped.setdefault(key, {
            'filename': r['filename'],
            'file_size': r['file_size'],
            'files': [],
        })
        group['files'].append({
            'id': r['id'],
            'filename': r['filename'],
            'file_size': r['file_size'],
            'file_type': r['file_type'],
            'batch_name': r['batch_name'] or '',
            'sub_batch': r['sub_batch'] or '',
            'created_at': r['created_at'].isoformat() if r['created_at'] else '',
        })
    groups = [g for g in grouped.values() if len(g['files']) >= 2]
    groups.sort(key=lambda g: (g['filename'].lower(), g['file_size']))
    return groups


def _find_duplicate_groups(user, limit=DUPLICATE_DISPLAY_LIMIT):
    """Duplicate groups for the repair center: ``(groups, total_group_count)``.

    ``groups`` is capped at ``limit`` for display; the count reflects all.
    """
    groups = _group_duplicates(user)
    return groups[:limit], len(groups)


def _delete_duplicate_files(user):
    """Delete duplicate files (same filename+size), keeping the lowest id per
    group (the earliest registered). Returns the number of deleted rows.

    Per-file transaction so a mid-way failure never rolls back completed
    deletions; the action is idempotent. Only the duplicate file is removed —
    an existing batch directory and its remaining files are untouched.
    """
    deleted_count = 0
    deleted_paths = []
    groups = _group_duplicates(user)
    # 一次取回全部待删行：曾是「每个重复文件一次 SELECT」，几十组重复时就是几十次
    # 往返。owner=user 与 _group_duplicates 同源，是越权防线，不是冗余条件。
    pending = [item['id'] for group in groups for item in group['files'][1:]]
    rows = DataFile.objects.filter(owner=user, pk__in=pending).in_bulk()
    for group in groups:
        for item in group['files'][1:]:
            df = rows.get(item['id'])
            if df is None:
                continue
            with transaction.atomic():
                unlinked = _delete_datafile_file_only(df)
                df.delete()
            deleted_paths.append(unlinked)
            deleted_count += 1
    evict_parse_cache_for_paths(deleted_paths)
    return deleted_count
