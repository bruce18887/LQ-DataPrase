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

本模块只有口径，不碰 HTTP（视图在 ``views/usage_views.py``）。磁盘侧走树是上面的
``_iter_files`` / ``_scan_tree``；DB 侧的两本账与交集差值恒等式是下面的 ``_db_map`` /
``_mismatch`` / ``_compute_usage``；对外入口是 ``get_user_usage``（进程内分桶 TTL 缓存）。
分桶实现没有 per-key 过期，靠「换桶即换 key」过期 ⇒ 一条结果的寿命最多到它所属桶的末尾，
即 **≤ TTL（30s）**，不是 ``[TTL, 2*TTL)``（2026-11-14 复审纠正：初稿把窗口写宽了一倍，
而 Task 7 的界面文案会照抄这个数）。返回体仍带 ``scanned_at``，让陈旧对用户可见。
"""
import os
import time

from django.conf import settings
from django.utils import timezone           # 本任务的 _compute_usage 用

from apps.common.keyed_lru import KeyedLRU   # 本任务的 get_user_usage 用
from apps.datafiles.models import DataFile   # 本任务的 _db_map 用
from apps.datafiles.utils import resolve_file_path  # 本任务的 _db_map 用

# 规格 §4.4：进程内 TTL 缓存。没有 per-key 过期，靠换桶换 key ⇒ 一条结果寿命 ≤ TTL；
# 所以浮层必须显示 scanned_at，让陈旧对用户可见。
USAGE_CACHE_TTL_SECONDS = 30
_USAGE_CACHE_MAX_ENTRIES = 64

_usage_cache = KeyedLRU(_USAGE_CACHE_MAX_ENTRIES)

# 规格 §4.6 的阈值：只在超阈时提示，不做常驻的第二指标。
# 「常态下差值为零」这句在旧口径（全量比全量）下实测不成立（本机 dev ratio=0.1775，
# 全部来自 73 条已删文件），换成订正⑤ 的交集口径后才成立 —— 改回全量比全量
# 就会让这条阈值在每台有遗留数据的装机上永远红。
MISMATCH_RATIO_THRESHOLD = 0.05

# 用户名直接当目录名用（与 _helpers.py:183 同一种拼法），所以要挡住能改变指向的那几种写法。
_UNSAFE_USERNAMES = ('', '.', '..')


def is_safe_username(username):
    """用户名能不能安全当数据目录名用。**视图也用它**：早退成 204 比让异常冒成 500 诚实
    （500 会让前端每次进门弹一条错误 toast，而这件事本来就不是「服务器坏了」）。
    把判据放这儿而不是各写一份，是为了它和 ``_user_data_root`` 永远同进同退。"""
    name = str(username)
    return not (
        name in _UNSAFE_USERNAMES
        or os.sep in name
        or (os.altsep and os.altsep in name)
    )


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
    if not is_safe_username(username):
        raise ValueError('用户名不能安全地用作数据目录名：%r' % str(username))
    return os.path.normpath(
        os.path.join(str(settings.MEDIA_ROOT), 'data', str(username))
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
                reg_db += int(db_size)
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


def _db_map(user, root):
    """该用户的注册行，分成「根目录内（做成 map）」与「根目录外（只记账）」。

    ``file_size`` 是注册那一刻的 ``os.path.getsize``（``_helpers.py:123``），此后永不刷新
    ⇒ 只能当参考值。更要紧的是 ``store_file_path``（``utils.py:97``）对 MEDIA_ROOT 之外/
    跨盘的路径**保持绝对路径**、``resolve_file_path`` 又原样透传 2026-08-21 前的遗留绝对
    路径 ⇒ 那部分记录指向的文件根本不在本模块要扫的树里，混进合计就会常年报一条假的不一致
    （计划订正②）。

    键统一 ``os.path.normcase(os.path.normpath(...))``：Windows 路径大小写不敏感，DB 里写
    ``data/INROOT/...`` 而磁盘上是 ``data/inroot/`` 时不做 normcase 会让那条在交集里**凭空
    消失**。注意消失的方向：``reg_db`` 与 ``reg_disk`` 是一起少的，所以差值会变成 0、
    该报的不报（假绿），不是冒出一条虚高差值 —— 护栏是 Task 3 断言
    ``registered_count == 1``，不是差值行。

    遍历形状照抄生产写法 ``views/browse_views.py:272-277``（同一份 values_list），但**加
    ``order_by('id')``**：同一个路径上有重复注册行是已知状态（批3 整批就在处理它），
    map 按路径去重 ⇒ 不加排序的话胜者取决于数据库返回顺序，差值会在两次请求之间翻脸，
    还在 30s TTL 里冻住一个。``order_by('id')`` 把胜者定死成 id 最大的那条。

    返回的口径分两套：``in_rows``/``in_bytes`` 是**行**口径（返回体里的 db_* 用它），
    ``in_files`` = ``len(map)`` 与 map 本身是**文件**口径（交集差值用它）。
    """
    prefix = os.path.normcase(os.path.normpath(root)) + os.sep
    registered = {}
    in_rows = in_bytes = out_count = out_bytes = 0
    for file_path, file_size in DataFile.objects.filter(owner=user).order_by('id').values_list(
        'file_path', 'file_size'
    ):
        abs_path = os.path.normcase(os.path.normpath(resolve_file_path(file_path)))
        # 没有 `or 0` 兜 None：file_size 是 BigIntegerField(null=False)，
        # 实测 update(file_size=None) 直接 sqlite3.IntegrityError（0001_initial.py:23）
        # ⇒ 那层兜底永远进不去，留着只会让下一个人以为这种数据存在过。
        size = int(file_size)
        if abs_path.startswith(prefix):
            in_rows += 1
            in_bytes += size
            registered[abs_path] = size
        else:
            out_count += 1
            out_bytes += size
    return {
        'map': registered,
        'in_rows': in_rows,
        'in_files': len(registered),
        'in_bytes': in_bytes,
        'out_count': out_count,
        'out_bytes': out_bytes,
    }


def _mismatch(bytes_total, registered_disk_bytes, registered_db_bytes):
    """规格 §4.6 的恒等式，但两侧都只取交集（订正⑤）。

    ``registered_disk_bytes`` = 交集里每条的**实际** st_size 之和；
    ``registered_db_bytes``   = 同一条条的**清单** file_size 之和。
    于是这一行只说一件事：**清单里的大小数字过期了**。
    文件已删（=孤立数据库记录）与磁盘孤儿（=孤立磁盘文件）各归修复中心自己的卡，
    不再在这里用 MB 重复说一遍 —— 实测本机 dev 库旧口径 ratio=0.1775、新口径 0.0000。
    分母用 ``bytes_total``（用户看得见的那个数），``max(..., 1)`` 只防空目录除零；
    ``>`` 是严格大于，恰好等于阈值不算不一致。
    """
    diff = abs(registered_disk_bytes - registered_db_bytes)
    ratio = diff / max(bytes_total, 1)
    return ratio > MISMATCH_RATIO_THRESHOLD, diff


def _compute_usage(user):
    """扫盘 + 查库，组出端点返回体（口径见模块 docstring）。

    交集的三个内部量（``registered_count`` / ``registered_disk_bytes`` /
    ``registered_db_bytes``）**不进返回体**：界面只需要「超没超阈值 + 差多少」，
    多摆三个数就是规格 §4.6 明确否掉的「没人看得懂的二阶数字」。它们的正确性由
    Task 3 的 JoinedScanTests 直接打在 `_scan_tree` 上钉住。
    """
    root = _user_data_root(user.username)
    db = _db_map(user, root)
    scan = _scan_tree(root, registered=db['map'])
    mismatch, diff = _mismatch(
        scan['bytes'], scan['registered_disk_bytes'], scan['registered_db_bytes']
    )
    return {
        'data_dir': root,
        'bytes': scan['bytes'],
        'unique_bytes': scan['unique_bytes'],
        'file_count': scan['file_count'],
        'by_type': scan['by_type'],
        # db_count / db_bytes 是「全量参考」，走的是**行**口径（in_rows + out_count）；
        # 差值恒等式走的是交集（文件口径），那三个内部量不进返回体。
        'db_count': db['in_rows'] + db['out_count'],
        'db_bytes': db['in_bytes'] + db['out_bytes'],
        'db_bytes_in_root': db['in_bytes'],
        'db_outside_root_count': db['out_count'],
        'db_outside_root_bytes': db['out_bytes'],
        'mismatch_over_threshold': mismatch,
        'mismatch_diff_bytes': diff,
        'scanned_at': timezone.now().isoformat(),
    }


def get_user_usage(user, fresh=False):
    """按用户取占用统计，带进程内分桶 TTL 缓存。

    key = ``(username, bucket)``，``bucket = int(monotonic // TTL)``。为什么不用
    ``functools.lru_cache`` 也不用精确过期：仓内已有 ``KeyedLRU``（唯一一份，按条数
    封顶 + 每 key 单飞），而它只有 ``get_or_compute``/``clear`` 两个动作、没有 per-key
    过期与 per-key 删除 ⇒ 用分桶把「过期」变成「换 key」。代价是真实窗口在
    ≤ 30s，所以返回体带 ``scanned_at`` 让陈旧可见。
    ``fresh=True`` 清整表：会顺带让别的用户重扫一次，但触发它的只是某个用户自己的
    一次写操作，代价是一次扫描（实测 11.4ms / 112 文件），换来的是「漏挂失效钩子最多
    陈旧 30s」而不是永久。

    **尽力而为，不是事务级的**：``KeyedLRU.clear()`` 明确不 fence 在途的 ``compute``
    （``keyed_lru.py:53-59``），所以「写之前就开始扫、写完之后才发布」的那一次可能让
    紧随其后的 fresh 调用拿到写前的结果。窗口等于一次扫描（十毫秒级），下一个桶自愈。
    要真消除得给条目加 epoch —— 那是给一个只读 chip 加机制，不做。
    """
    if fresh:
        _usage_cache.clear()
    bucket = int(time.monotonic() // USAGE_CACHE_TTL_SECONDS)
    return _usage_cache.get_or_compute(
        (str(user.username), bucket), lambda: _compute_usage(user)
    )


def clear_usage_cache():
    """测试隔离入口（与 ``dashboard.services.clear_dashboard_summary_cache`` 同形）。"""
    _usage_cache.clear()
