# apps/datafiles/storage_usage.py
"""当前用户的磁盘占用统计（批2 · 第 5 项）。

口径（唯一事实来源：specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md §4.2；
教训原文：docs/tasks/lessons.md 2026-10-24）：

* ``bytes``        —— 逐文件 ``st_size`` 加总，**表观口径**，页面只显示这一个数。
* ``unique_bytes`` —— 按 ``(st_dev, st_ino)`` 去重后的加总，真占盘口径。产品树目前没有
  硬链接（Task 1 探针 P4 实测），所以两者相等；留着它是**绊线**：哪天有代码往用户
  目录里硬链文件，它会先于 chip 说谎，逼人重新说明口径。
* 取 inode **必须** ``os.lstat``：本机（Python 3.13.12 / Windows）实测
  ``os.DirEntry.stat()`` 的 ``st_dev``/``st_ino`` 恒为 0，用它去重会把整棵树压成
  「1 个 inode」，几 GB 直接报成几 MB。同一条教训的实现见
  ``scripts/test_data_gc.py:144 walk_inodes()``。这条不是只写在注释里：
  ``test_硬链接按inode只计一次`` 用「一颗硬链对 + 一颗不同体积的独立文件」把它的
  变异体（改成 ``entry.stat()``）钉成必红 —— 只有硬链对的话坏实现也会得出同一个数。

本模块只做磁盘侧口径。DB 侧的两本账与差值恒等式（``_db_map`` / ``_mismatch``）、
进程内 TTL 缓存（``get_user_usage``）由后续任务加在本文件里；HTTP 视图在
``views/usage_views.py``，这里不碰。
"""
import os
from collections import OrderedDict

from django.conf import settings


def _user_data_root(username):
    """当前用户的数据根目录 = ``MEDIA_ROOT/data/<username>``。

    用户名只来自 ``request.user``（视图里没有入参），所以这里不存在路径穿越面；
    与 ``_helpers.py:172 _user_upload_dir`` 同一种拼法，只是不到 file_type 那一层。
    """
    return os.path.normpath(
        os.path.join(str(settings.MEDIA_ROOT), 'data', str(username))
    )


def _iter_files(root):
    """产出 ``(abs_path, top, st_dev, st_ino, st_size)``；``top`` = 根下第一段目录名。

    直接躺在根下的散文件 ``top == ''``。符号链接与目录联接跳过（链接目标可能被算成
    第二份，而它并不占这个用户的空间）。单个条目或单个目录读不到就跳过：一次权限
    问题不该让整颗 chip 消失，也不该让整个请求 500。
    """
    if not os.path.isdir(root):
        return
    stack = [(root, '')]
    while stack:
        cur, top = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(
                                (entry.path, top or os.path.basename(entry.name))
                            )
                            continue
                        st = os.lstat(entry.path)
                        yield entry.path, top, st.st_dev, st.st_ino, st.st_size
                    except OSError:
                        continue
        except OSError:
            continue


def _scan_tree(root, registered=None):
    """扫描 ``root``。返回 ``{'bytes','unique_bytes','file_count','by_type'}``，
    传了 ``registered`` 再附 ``{'registered_count','registered_db_bytes','registered_disk_bytes'}``。

    ``by_type`` 的值是 ``{'bytes': int, 'count': int}``，键为根下第一段目录名
    （``single`` / ``batch``，散文件为空串）。各桶之和恒等于总量，这条自洽性由测试钉。

    ``registered`` 是 ``{normcase 后的绝对路径: 清单里记的 file_size}``（Task 3 的
    ``_db_map`` 造）。在同一次走树里顺手把「注册行 ∩ 文件确实在盘上」这个交集的两侧各自
    累计出来 —— 这是订正⑤ 的实现位置：差值只比交集，所以缺文件与磁盘孤儿都不会混进来，
    而且**不用第二次走树**。不传就是纯总量扫描（Task 2 的测试与将来的独立复用都走这条）。

    查表前必须 ``os.path.normcase(path)``（map 的键是 normcase 过的，``entry.path`` 不是）。
    搞反方向的提醒：匹配不上时 ``reg_db`` 与 ``reg_disk`` 是在同一个分支里**一起**少加的，
    所以差值会恒等于 0、该报的不报（假绿），而不是冒出一条虚高的差值。所以真正的护栏是
    Task 3 那批用例断言 ``registered_count`` 非 0，别指望差值行替这条路把关。
    """
    total = 0
    count = 0
    seen = {}                      # (dev, ino) -> size
    by_type = OrderedDict()
    reg_count = reg_db = reg_disk = 0
    for path, top, dev, ino, size in _iter_files(root):
        total += size
        count += 1
        seen[(dev, ino)] = size
        bucket = by_type.get(top)
        if bucket is None:
            bucket = {'bytes': 0, 'count': 0}
            by_type[top] = bucket
        bucket['bytes'] += size
        bucket['count'] += 1
        if registered is not None:
            db_size = registered.get(os.path.normcase(path))
            if db_size is not None:
                reg_count += 1
                reg_db += int(db_size or 0)
                reg_disk += size
    result = {
        'bytes': total,
        'unique_bytes': sum(seen.values()),
        'file_count': count,
        'by_type': dict(by_type),
    }
    if registered is not None:
        result['registered_count'] = reg_count
        result['registered_db_bytes'] = reg_db
        result['registered_disk_bytes'] = reg_disk
    return result
