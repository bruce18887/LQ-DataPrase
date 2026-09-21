"""BFS 目录遍历与元数据过滤（spec §3.4）。

三处刻意与参考工具 ``file_retriever.py`` 相反的设计：

1. **BFS 工作队列，不是深度优先递归**：DFS 会一头扎进第一个子树直到叶才吐第一个文件；
   BFS 让候选从第一次列目录起就在往 UI 流，取消也只是「不再消费队列」（§3.9）。
2. **深度默认不限**：``max_depth`` 只在 ``depth='custom'`` 时有值（映射在
   ``contracts.DEPTH_TO_MAX``）。防失控的闸是 ``max_entries`` 预算与 deadline，它们与
   目录形状无关；用深度兜会在目标树恰好深一层时**静默少结果**（§3.2）。
3. **剪枝在进入前判定**：被 ``prune_dirs`` 命中的子树既不进入、也不计条目预算，否则
   「剪掉最外层」等于白剪。这是 ``max_entries`` 的**唯一**豁免（§3.2「遍历到的目录条目
   总数」）：被 ``name_pattern``/大小/时间窗拒掉的文件照吃预算，它们只是不成为候选，
   列目录的代价一点没省——把预算只记在候选上等于给它换个名字叫「候选上限」。

``depth`` 的口径：根目录是 0 层，根的直属子目录是 1 层，一个目录被列出的条件是其层数
``<= max_depth``。所以 ``self``=0 只列根、``children``=1 多列一层，与前端档位文案
「仅当前层 / 含下一层」逐字对应。

单目录 ``listdir_attr`` 失败只降级成一个 ``error{scope:"dir"}`` 事件并**继续**：一次搜索
要跨几百个目录，任何一个不可读都不该让整次搜索作废（§3.4）。
"""

import fnmatch
import logging
import posixpath
import stat
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from apps.datafiles.views import _is_summary_csv

from apps.sftp.search.contracts import SearchSpec

logger = logging.getLogger(__name__)

# 连接级故障的字符串标记：``list_one`` 把异常压成了消息文本（它不能抛，抛了就终止搜索），
# 所以这里只能嗅探文本。命中即把这条连接标成 broken 交还给 session 回收重开。
_CONNECTION_MARKERS = ('Garbage packet', 'SSH session not active',
                       'No existing session', 'Connection reset')


class Candidate:
    """一个通过元数据过滤的待扫文件。``__slots__``：十万候选时省内存。"""

    __slots__ = ('path', 'name', 'size', 'mtime')

    def __init__(self, path: str, name: str, size: int, mtime: int):
        self.path = path
        self.name = name
        self.size = size
        self.mtime = mtime

    def as_dict(self) -> Dict[str, object]:
        """SSE ``candidates`` 事件的 item 形状（spec §3.8）。"""
        return {'path': self.path, 'name': self.name,
                'size': self.size, 'mtime': self.mtime}

    def __repr__(self):
        return f'Candidate({self.path!r}, size={self.size})'


class WalkResult:
    """一次遍历的产物。``truncated`` 是 limits_hit 码列表，engine 逐个转 notice。"""

    def __init__(self) -> None:
        self.candidates: List[Candidate] = []
        self.events: List[dict] = []
        self.entries_seen: int = 0     # 实际所见的非剪枝条目（含被元数据过滤掉的）
        self.truncated: List[str] = []
        self.cancelled: bool = False


# ------------------------------------------------------------------ 过滤谓词


def is_pruned(dirname: str, patterns: Sequence[str]) -> bool:
    """``prune_dirs`` 只匹 basename（与前端「目录名标签」输入一致）。

    用 :func:`fnmatch.fnmatchcase` 而不是 :func:`fnmatch.fnmatch`：后者在 Windows 上会
    经 ``os.path.normcase`` 变成大小写不敏感，而服务器是大小写敏感的 POSIX —— 同一份
    条件在开发机和生产机会给出不同结果。``shell_grep`` 的 ``--include=`` 同样大小写敏感，
    两边一致才能保证换引擎不改结果。
    """
    for pattern in patterns:
        if fnmatch.fnmatchcase(dirname, pattern):
            return True
    return False


def passes_metadata(name: str, size: Optional[int], mtime: Optional[int],
                    spec: SearchSpec) -> bool:
    """元数据过滤。判定顺序见下，缺一即与 spec §3.4 不等价。"""
    if name.startswith('.'):
        return False                       # 与 views.py:537 _collect_files 现状一致
    if spec.name_pattern and not fnmatch.fnmatchcase(name, spec.name_pattern):
        return False
    if spec.data_files_only:
        ext = posixpath.splitext(name)[1].lower()
        if ext != '.csv' or _is_summary_csv(name):
            return False
    size = size or 0
    if spec.min_size is not None and size < spec.min_size:
        return False
    if spec.max_size is not None and size > spec.max_size:
        return False
    if spec.modified_after is not None or spec.modified_before is not None:
        # mtime 拿不到时取**排除**：把不确定的文件混进结果，用户无从分辨。
        if not mtime:
            return False
        stamp = _as_datetime(mtime)
        if spec.modified_after is not None and stamp < spec.modified_after:
            return False
        if spec.modified_before is not None and stamp > spec.modified_before:
            return False
    return True


def _as_datetime(mtime: int) -> datetime:
    """epoch 秒 → 本地 naive datetime，与 ``contracts`` 解析出的窗口同一时区口径。"""
    return datetime.fromtimestamp(mtime)


# ------------------------------------------------------------------ 单层列举


def list_one(sftp, path: str,
             spec: SearchSpec) -> Tuple[List[str], List[Candidate], Optional[str],
                                        int]:
    """列一个目录：返回 ``(可进入的子目录, 通过过滤的候选, 错误消息或 None, 所见条目数)``。

    **本函数不抛异常**（除了 KeyboardInterrupt 这类 BaseException）：调用方在 worker
    线程里，抛出等于把整次搜索炸掉。子目录已经过 ``realpath`` 归一，供上层做环保护。

    ``seen`` 的口径（spec §3.2 钳位表「遍历到的目录条目总数」+ §3.4 唯一豁免）：数的是
    这一层**实际看到**的条目，含 dot 条目、含被 ``name_pattern``/大小/时间窗拒掉的文件
    —— 被拒条目只是「不成为候选」，它们照样消耗了一次列目录。唯一的豁免是 ``prune_dirs``
    命中的目录：剪枝的全部意义就是连进都不进，若剪掉的子树还吃预算，「剪掉最外层」等于
    白剪。空名条目不是真实条目，不计。
    """
    try:
        attrs = sftp.listdir_attr(path)
    except Exception as exc:  # noqa: BLE001 —— 降级为 dir 事件，绝不终止遍历
        logger.warning('SFTP listdir failed for %s: %s', path, exc)
        return [], [], str(exc) or type(exc).__name__, 0

    base = path.rstrip('/') or '/'
    dirs: List[str] = []
    found: List[Candidate] = []
    seen = 0
    for attr in attrs:
        name = getattr(attr, 'filename', '')
        if not name:
            continue
        if _is_dir(attr) and is_pruned(name, spec.prune_dirs):
            continue                       # 唯一豁免预算的一条：见 docstring
        seen += 1
        if name.startswith('.'):
            continue                       # 与 views.py:537 _collect_files 现状一致
        full = posixpath.join(base, name)
        if _is_dir(attr):
            dirs.append(_resolve_dir(sftp, full))
        elif passes_metadata(name, getattr(attr, 'st_size', None),
                             getattr(attr, 'st_mtime', None), spec):
            found.append(Candidate(full, name,
                                   getattr(attr, 'st_size', None) or 0,
                                   getattr(attr, 'st_mtime', None) or 0))
    return dirs, found, None, seen


def _is_dir(attr) -> bool:
    """只有 ``S_ISDIR`` 算目录，其余（含 symlink、``st_mode`` 缺失）一律按文件走。

    判成目录才有环风险，而环保护的开销是给真目录的；判成文件最坏是扫描阶段报一个
    ``error{scope:"file"}``，比静默丢条目好（§3.2「静默少结果比慢十倍恶劣」）。
    服务器多数会把 symlink 指向的目录 stat 成 ``S_IFDIR``，那种照常递归。
    """
    mode = getattr(attr, 'st_mode', None)
    return bool(mode is not None and stat.S_ISDIR(mode))


def _resolve_dir(sftp, path: str) -> str:
    """``realpath`` 归一：SFTP 协议判 symlink 不可靠（§3.4），靠解析后的真身去重。"""
    try:
        return posixpath.normpath(sftp.realpath(path))
    except Exception as exc:  # noqa: BLE001 —— 归一失败退回字面路径，目录照列
        logger.warning('SFTP realpath failed for %s: %s, falling back to normpath',
                       path, exc)
        return posixpath.normpath(path)


def _looks_connection_level(message: str) -> bool:
    return any(marker in message for marker in _CONNECTION_MARKERS)


# ------------------------------------------------------------------ BFS 主体


def _list_via_session(session, path: str,
                      spec: SearchSpec) -> Tuple[List[str], List[Candidate], str, int]:
    """借一条连接列一个目录。坏连接在这里标出来还给池（「脏了就换」这条）。

    条目预算 ``seen`` 由 :func:`list_one` 就地数：它是**实际所见**的条目数，被元数据
    过滤掉的文件照算，只有 ``prune_dirs`` 命中的子树在 ``list_one`` 里就豁免掉，所以
    「剪掉最外层」不会把 ``max_entries`` 吃光（§3.2 口径 + §3.4 唯一豁免）。
    """
    item = session.borrow()
    broken = False
    try:
        dirs, files, err, seen = list_one(item[1], path, spec)
        if err and _looks_connection_level(err):
            broken = True
        return dirs, files, err or '', seen
    finally:
        session.give_back(item, broken=broken)


def walk(spec: SearchSpec, session, *,
         on_candidate: Optional[Callable[[Candidate], None]] = None,
         cancel_event=None, deadline: Optional[float] = None) -> WalkResult:
    """广度优先列举 ``spec.roots`` 下的候选文件。

    显式**批**派发：一批最多 ``workers * 4`` 个目录，收完再派下一批。不在锁内一边派
    一边收，是因为那样 ``pending`` 与 ``result`` 会被 worker 线程并发写；现在所有累加
    都在本线程，无需锁。``on_candidate`` 在收的时候回调，所以候选边列边流。
    """
    result = WalkResult()
    max_depth = spec.effective_max_depth()
    workers = max(1, min(spec.workers, session.size))
    pending: List[Tuple[str, int]] = [(path, 0)
                                      for path in _resolve_roots(session, spec.roots)]
    visited = {path for path, _depth in pending}
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='sftp-walk')
    try:
        while pending:
            if _stopped(cancel_event) or _expired(deadline):
                result.cancelled = True
                break
            if result.entries_seen >= spec.max_entries:
                result.truncated.append('truncated_entries')
                break
            if len(result.candidates) >= spec.max_candidates:
                result.truncated.append('truncated_candidates')
                break

            batch, pending = pending[:workers * 4], pending[workers * 4:]
            futures = {executor.submit(_list_via_session, session, path, spec):
                       (path, depth) for path, depth in batch}
            for future in as_completed(futures):
                path, depth = futures[future]
                try:
                    dirs, files, err, seen = future.result()
                except Exception as exc:  # noqa: BLE001 —— 借还/线程层故障同样降级为 dir 事件
                    logger.warning('SFTP walk of %s failed: %s', path, exc,
                                   exc_info=True)
                    result.events.append({'kind': 'error', 'scope': 'dir',
                                          'path': path, 'message': str(exc)})
                    continue
                result.entries_seen += seen
                if err:
                    result.events.append({'kind': 'error', 'scope': 'dir',
                                          'path': path, 'message': err})
                for candidate in files:
                    if len(result.candidates) >= spec.max_candidates:
                        break
                    result.candidates.append(candidate)
                    if on_candidate is not None:
                        on_candidate(candidate)
                _enqueue_dirs(dirs, depth, max_depth, visited, pending, result)
    finally:
        # 不用 with：with 会 join 全部 worker，取消时请求会挂到整棵树列完才返回。
        executor.shutdown(wait=False, cancel_futures=True)
    return result


def _enqueue_dirs(dirs: Sequence[str], depth: int, max_depth: Optional[int],
                  visited: set, pending: List[Tuple[str, int]],
                  result: WalkResult) -> None:
    """把子目录排进队列；已到深度闸则记 ``truncated_depth``（显式告知，不静默少结果）。"""
    if not dirs:
        return
    child_depth = depth + 1
    if max_depth is not None and child_depth > max_depth:
        if 'truncated_depth' not in result.truncated:
            result.truncated.append('truncated_depth')
        return
    for path in dirs:
        if path in visited:
            continue          # 环保护 / 重叠根去重
        visited.add(path)
        pending.append((path, child_depth))


def _stopped(cancel_event) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _expired(deadline: Optional[float]) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _resolve_roots(session, roots: Sequence[str]) -> List[str]:
    """根路径也要归一：``/data`` 与 ``/data/`` 是同一条根，symlink 根要折到真身，
    否则环保护的 ``visited`` 集合认不出重复，重叠根会把同一棵树列两遍。"""
    item = session.borrow()
    try:
        return [_resolve_dir(item[1], root) for root in roots]
    finally:
        session.give_back(item)
