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

from django.conf import settings

# 用户名直接当目录名用（与 _helpers.py:183 同一种拼法），所以要挡住能改变指向的那几种写法。
_UNSAFE_USERNAMES = ('', '.', '..')


def _user_data_root(username):
    """当前用户的数据根目录 = ``MEDIA_ROOT/data/<username>``。

    用户名只来自 ``request.user``（视图里没有入参），但**它仍然拼进路径**，所以这条
    拼接要挡住：Django 默认的 ``UnicodeUsernameValidator`` 实测**接受** ``..``
    （点号是合法字符），而 ``MEDIA_ROOT/data/..`` 归一化后就是 ``MEDIA_ROOT`` ——
    那个端点就会把**所有用户**的量报给这一个用户。``os.path.basename('..')`` 也是
    ``'..'``，所以别拿它当防护。

    已知同形状的老入口 ``_helpers.py:172 _user_upload_dir`` 没挡这一条（上传侧同样能
    被 ``..`` 顶到 MEDIA_ROOT），那是既有事实、不属本批，记进台账。
    """
    name = str(username)
    if name in _UNSAFE_USERNAMES or os.sep in name or (os.altsep and os.altsep in name):
        raise ValueError('用户名不能安全地用作数据目录名：%r' % name)
    return os.path.normpath(
        os.path.join(str(settings.MEDIA_ROOT), 'data', name)
    )


def _iter_files(root):
    """产出 ``(abs_path, top, st_dev, st_ino, st_size)``；``top`` = 根下第一段目录名。

    直接躺在根下的散文件 ``top == ''``。单个条目或单个目录读不到就跳过：一次权限
    问题不该让整颗 chip 消失，也不该让整个请求 500。

    **符号链接与目录联接（junction / 挂载点）都必须跳过**，而且要分开两个判断：
    本机实测（Python 3.13.12 / Windows）``mklink /J`` 造出来的 junction 是
    ``is_symlink() == False`` 而 ``is_dir(follow_symlinks=False) == True`` —— 只判
    ``is_symlink()`` 的话它会被当成普通子目录**走进去**，于是「别人的目录体积」被算进
    这个用户头上（指向一个自引用 junction 时还能一路递归到 MAX_PATH 才因 OSError 停下，
    而那声 OSError 正好被上面那条跳过规则咽掉，表现为一个偏大的数而不是一声报错）。
    跳过的代价是链接目标不计入本用户占用 —— 正确：它不占这个用户的盘块。
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
                        if entry.is_symlink() or entry.is_junction():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append((entry.path, top or entry.name))
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

    两条契约，Task 3 依赖它们：
    * ``registered_count`` 数的是**文件**，不是注册行数 —— map 按路径去重，同一个路径上
      有几条重复行只留一条。所以它不许被拿去和 ``db_count`` 对照；行数由 ``_db_map``
      自己数（``in_rows``），map 的胜者用 ``order_by('id')`` 定死，否则同一份数据两次
      请求可能挑到不同的 ``file_size``，差值会在 30s TTL 里翻脸。
    * 传了 ``registered`` 就必须是**绝对** root：``entry.path`` 的绝对性是从 root 继承的，
      相对 root ⇒ 相对 path ⇒ 与 map 的键永不相等，而两侧是一起不加的 ⇒ 交集恒空、
      差值恒 0（假绿）。这条用 raise 挡，不用 assert（``-O`` 会把 assert 剥掉）。

    查表前必须 ``os.path.normcase(path)``（map 的键是 normcase 过的，``entry.path`` 不是）。
    搞反方向的提醒：匹配不上时 ``reg_db`` 与 ``reg_disk`` 是在同一个分支里**一起**少加的，
    所以差值会恒等于 0、该报的不报（假绿），而不是冒出一条虚高的差值。所以真正的护栏是
    Task 3 那批用例断言 ``registered_count`` 非 0，别指望差值行替这条路把关。
    """
    if registered is not None and not os.path.isabs(root):
        raise ValueError('_scan_tree 带 registered 时 root 必须是绝对路径：%r' % root)
    total = 0
    count = 0
    seen = {}                      # 去重键 -> size
    by_type = {}                   # 插入序即输出序，不用再套 OrderedDict
    reg_count = reg_db = reg_disk = 0
    for path, top, dev, ino, size in _iter_files(root):
        total += size
        count += 1
        # 有些文件系统（网络盘、部分虚拟盘）把 st_ino 一律报 0。真按 (dev, ino) 去重
        # 就会把整棵树塌成「1 个 inode」—— 与 2026-10-24 那次「5.0GB 报成 0.07MB」同形，
        # 只是换了成因。ino 为 0 时退回按路径记（等于不去重）：宁可高估，不去猜。
        seen[(dev, ino) if ino else (dev, ino, path)] = size
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
        'by_type': by_type,
    }
    if registered is not None:
        result['registered_count'] = reg_count
        result['registered_db_bytes'] = reg_db
        result['registered_disk_bytes'] = reg_disk
    return result
