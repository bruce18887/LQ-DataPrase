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
3. **每组恰一枚保留 id，且校验是双向的**（正向白名单 + 反向覆盖，两道都在
   ``_resolve_keep_selection`` 里、都抛在任何删除之前）：
   - 正向：每一枚 ``keep_id`` 必须是**已展示切片**里某组的成员；
   - 反向：**非空**载荷必须逐组覆盖整个已展示切片。漏一组 = GET 与 POST 之间列表变了
     （多导入一条把某组挤进来、或某组塌成一行让第 51 组滑进来），那组用户没见过，
     按默认替他把 ``files[0]`` 之外的都删掉正是本项要修的缺陷本身 ⇒ 一律拒；
   - **空/未提供**载荷不参与反向校验，走「每组留 id 最小」的历史分支（§5.3 第 2 条，
     服务老客户端与脚本；未指定 = 该组 id 最小，``files`` 按 id 升序，见下面
     ``_group_duplicates`` 里的 ``order_by('id')``）。
   越界与漏组都由 ``_resolve_keep_selection`` 拒成 ``InvalidKeepSelection``，
   视图把它翻成 400（各态形状在 ``test/backend/test_duplicate_keep_selection.py``）。
"""

import os

from django.db import transaction

from apps.datafiles.models import DataFile
from apps.datafiles.services import evict_parse_cache_for_paths
from apps.datafiles.utils import resolve_file_path

from ._helpers import _delete_datafile_file_only

# GET 的展示切片与 POST 的处理切片共用这一个常数（口径 2）。
DUPLICATE_DISPLAY_LIMIT = 50


class InvalidKeepSelection(ValueError):
    """`keep_ids` 与本次可处理的重复组对不上（正向越界或反向漏组，见 `_resolve_keep_selection`）。

    继承 `ValueError` 只为让视图一句 `except` 就能翻成 400，不必再往 `browse_views`
    引一个新异常名。
    """


def _group_key(group):
    """分组键本身（`(filename, file_size)`，全库唯一 ⇒ 可当 dict 键）。"""
    return (group['filename'], group['file_size'])


def _resolve_keep_selection(groups, keep_ids, limit=DUPLICATE_DISPLAY_LIMIT):
    """把 `keep_ids` 落成「每组一枚保留 id」，返回 ``(displayed, keep_by_key)``。

    两道方向相反的闸门，都在**任何删除动作之前**抛 —— 顺序就是「一行都不许删」那句的实现：

    **正向（白名单）**：每一枚 id 必须出现在已展示切片（前 ``limit`` 组）的成员里。
    四态越界即拒：

    * 不存在的 id / 他人的文件 / 非重复文件：压根进不了 ``allowed``；
    * **切片之外的组**：用户以为改了它，服务端根本不碰。静默接受等于按默认
      删掉用户以为改选过的那份，正是本项要修的缺陷的变体；
    * 同一组两枚：radio 的不变量是「一组恰一枚」，出现两枚说明载荷与界面状态不一致，
      此时删谁都是替用户决定。

    非整数（含 `bool`：`isinstance(True, int)` 在 Python 里是真的，不挡就会拿 `True`
    当 id 1 去查表）同样拒 —— 这是 HTTP 入口，不是内部调用。

    **反向（覆盖）**：非空载荷必须逐组覆盖整个 ``displayed``。只有正向闸门时，「漏掉的组」
    会在 ``_delete_duplicate_files`` 里回落到默认「留 ``files[0]``」，于是列表在 GET 与 POST
    之间变过（多导入一条、或某组塌成一行让第 51 组滑进来）时，一组**用户从来没看见**的文件
    被静默删掉且不可撤销 —— 而本批的全部意义就是不再由服务端替用户决定。
    **空/未提供载荷不走这道闸门**（口径 3 第三条：那是老客户端与脚本的 legacy 分支）。
    判据用 ``keep_by_key`` 而非 ``keep_ids`` 的假值：载荷里每一枚要么抛错要么落进映射，
    所以「映射为空」恒等于「没送任何 id」，生成器之类的一次性可迭代对象也不会被误判。
    """
    displayed = groups[:limit]
    allowed = {}
    for group in displayed:
        for item in group['files']:
            allowed[item['id']] = _group_key(group)
    keep_by_key = {}
    for raw in keep_ids:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise InvalidKeepSelection('keep_ids 必须是整数数组')
        key = allowed.get(raw)
        if key is None:
            raise InvalidKeepSelection('保留项不属于本次可处理的重复组（已失效或不在本批 50 组内）')
        if key in keep_by_key:
            raise InvalidKeepSelection('同一组只能有一枚保留项')
        keep_by_key[key] = raw
    if keep_by_key and len(keep_by_key) < len(displayed):
        missed = [g['filename'] for g in displayed if _group_key(g) not in keep_by_key]
        raise InvalidKeepSelection(
            '保留项没有覆盖本批全部已展示的组（缺 %d 组，如：%s）'
            '——列表可能已经变了，请重新检查后再删'
            % (len(missed), '、'.join(missed[:3])))
    return displayed, keep_by_key


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


def _delete_duplicate_files(user, keep_ids=()):
    """按保留选择删除重复文件，返回 ``(deleted_count, remaining_groups)``。

    * ``keep_ids`` 为空 ⇒ 每组留 id 最小（== 搬迁前的历史行为，向后兼容由
      ``apps/datafiles/tests.py:1255`` 与本文件的默认例共同钉住）；
    * ``keep_ids`` 非空 ⇒ 校验先于删除，**两个方向都要过**（口径 3）：既有越界的 id 会被拒，
      少覆盖一个已展示组的载荷同样被拒 —— ``_resolve_keep_selection`` 抛出来时一行都没动，
      所以这里那句 `keep_by_key.get(..., files[0])` 的默认回落**只在 legacy 分支可达**；
    * 逐文件 ``transaction.atomic()`` 照旧：中途失败不回滚已删的，动作幂等；
    * **只处理已展示切片**（口径 2）—— 第 51 组之后的东西用户根本没看见，
      不该替他删（设计 §5.4 的语义反转，2026-11-14 用户拍板）。

    ``deleted_count`` 只统计**字节真的不在盘上了**的那些（设计 §5.2：用户已否掉 `.trash`，
    这条计数与按钮上那句「（X MB）」是这次不可撤销操作上唯一的闸，它不许说谎）。
    ``_delete_datafile_file_only`` 只在真的 `os.remove` 成功时返回路径，被占用而抛
    ``OSError`` 时返回 ``None`` —— 但那只对「已经不在盘上」与「删不掉」两种情况给同一个值，
    所以这里额外按本调用点解析出的路径复查一次 ``os.path.exists``：
    还在盘上 ⇒ **不计数**（DB 行照旧删掉，行为与改前一致）。遗留的那只文件因此
    变成**孤立磁盘文件**，下一次一致性检查会把它报出来，由「清理孤立磁盘文件」
    （``delete_orphaned_disk``）处理；不计数就是这句话的兑现，不是补救手段。

    ``remaining_groups`` 是删完再跑一遍 `_group_duplicates` 的**实测**长度，不是
    ``总数 - len(displayed)`` 的算术。两句在当下所有可达形状里**恒等**（M5 实测：算术版跑全绿，
    因为每个已展示组跑完必塌成 1 行），所以这条**不是**判据能钉住的分歧 —— 选实测的理由是
    它不依赖「每组都恰好删到只剩 1 行」这个前提，而那个前提由上面的循环写法维持，不由数据库约束维持。
    """
    groups = _group_duplicates(user)
    displayed, keep_by_key = _resolve_keep_selection(groups, keep_ids)
    pending = []
    for group in displayed:
        keep = keep_by_key.get(_group_key(group), group['files'][0]['id'])
        pending.extend(item['id'] for item in group['files'] if item['id'] != keep)
    deleted_count = 0
    deleted_paths = []
    # 一次取回全部待删行（批2 之前的写法是每个重复文件一次 SELECT）。
    # owner=user 与 _group_duplicates 同源，是越权防线，不是冗余条件。
    rows = DataFile.objects.filter(owner=user, pk__in=pending).in_bulk()
    for group in displayed:
        keep = keep_by_key.get(_group_key(group), group['files'][0]['id'])
        for item in group['files']:
            if item['id'] == keep:
                continue
            df = rows.get(item['id'])
            if df is None:
                continue
            # 路径在这里自己解析一次：`unlinked` 为 None 时分不出「本来就没有」与
            # 「remove() 失败」，而 DF 行已经 delete()，之后再也拿不到这个信息。
            path = resolve_file_path(df.file_path)
            with transaction.atomic():
                unlinked = _delete_datafile_file_only(df)
                df.delete()
            deleted_paths.append(unlinked)
            if os.path.exists(path):
                continue
            deleted_count += 1
    evict_parse_cache_for_paths(deleted_paths)
    return deleted_count, len(_group_duplicates(user))
