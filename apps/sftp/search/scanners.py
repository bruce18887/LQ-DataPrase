"""字节级内容扫描内核（spec §3.5，移植参考工具 ``csv_content_searcher.py:407`` 全套）。

四条不能写的性质（前两条是「两档引擎给出同一结果集」的前提）：

1. **整词判定在原始字节上做**：命中位置的前一字节与后一字节都不属于 ``[A-Za-z0-9_]``
   才算整词 —— 与 ``LC_ALL=C`` 的 ``grep -w`` 在 ASCII 上的判定字面一致。**绝不用
   ``re`` 的 ``\\b``、也绝不用 ``str.isalnum()``**：那是 Unicode 语义（把 CJK 当 word
   字符），会让「客户端档」与「服务端 grep 档」对同一个查询给出不同结果集。
2. **needle 多编码**：``term`` 非 ASCII 时追加 utf-8 / gbk / utf-16-le / utf-16-be
   四种字节形态。本域中文 CSV 常是 GBK，只探 utf-8 会**静默漏掉**所有 GBK 文件。
3. **不逐行 decode**：1 MiB 大块读 + prefetch 流水线，滚动窗口维持行号计数；字节永远
   不被切开成半个 needle（``LINE_CONTEXT`` 远大于 needle 长度）。
4. **异常分层**：连接级异常上抛，由 ``connect.SearchSession`` 决定回收重连；文件级异常
   就地记 WARNING 并继续。判据见 :func:`_is_file_scoped`。
"""

from __future__ import annotations

import errno
import logging
from typing import Dict, List, Optional, Tuple

from apps.sftp.search.connect import CONNECTION_ERRORS
from apps.sftp.search.contracts import SearchSpec
from apps.sftp.search.walker import Candidate

logger = logging.getLogger(__name__)

# —— 流水线与窗口（spec §3.5 的数字，勿各处另写）——
CHUNK_SIZE = 1 << 20      # 1 MiB 大块读：一次往返换一趟匹配
HEAD_SIZE = 64 << 10      # 只为抽 TestFile/StartTime/PtsModifyTime 保留的文件头
MAX_INFLIGHT = 64         # prefetch 在途请求数 —— 约 2 MB 在途，读不再等 round-trip
LINE_CONTEXT = 4096       # 滚动窗口：够装下最长 needle 跨边界的残段 + 行号计数余量
SNIPPET_MAX = 200         # 送前端的命中片段长度上限

# C locale 的 word 字符集。**故意不用 str.isalnum()、也不用 re 的 \b** ——
# 那是 Unicode 语义，与 LC_ALL=C 的 grep -w 不等价，两档引擎就会给出不同结果集。
_WORD_BYTES = frozenset(
    b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')

# 非 ASCII term 的字节形态（GBK 优先于 gb2312：后者表达不了部分本域用字）
_NEEDLE_ENCODINGS = ('utf-8', 'gbk', 'utf-16-le', 'utf-16-be')
# 解码四探；utf-16 放最后是给「有 BOM 的 utf-16」留的路
_PROBE_ENCODINGS = ('utf-8', 'gbk', 'gb2312', 'utf-16')

# paramiko 把服务端回给**单个文件**的状态码转成 ``IOError(errno=...)``
# （见 ``sftp_client._convert_status``），而 socket 层故障也是 OSError —— 类型分不开。
_FILE_SCOPE_ERRNOS = frozenset({
    errno.ENOENT, errno.EACCES, errno.EPERM, errno.ENOTDIR, errno.EISDIR})


# ------------------------------------------------------------------ needle 与匹配


def build_needles(term: str, case_sensitive: bool) -> Tuple[List[bytes], bool]:
    """``term`` → 要在原始字节里找的 needle 列表 + 是否折叠大小写。

    ASCII 走单 needle：多 needle（比如再探 utf-16）会把编码巧合算成命中，而 grep 档
    只能发一个 ``-F`` 串 —— 两档可比的前提是这里也只能有一个。非 ASCII 不折叠：
    多字节编码下改单个字节就散架，大小写本来就只对 ASCII 有意义。
    """
    if not term:
        return [], False
    if term.isascii():
        needle = term if case_sensitive else term.lower()
        return [needle.encode('utf-8')], not case_sensitive

    needles: List[bytes] = []
    for encoding in _NEEDLE_ENCODINGS:
        try:
            encoded = term.encode(encoding)
        except (UnicodeEncodeError, LookupError):
            continue          # 该编码表达不了这个 term（如 emoji 之于 gbk），换下一个
        if encoded not in needles:
            needles.append(encoded)
    return needles, False


def word_ok(buf: bytes, idx: int, needle_len: int) -> bool:
    """``buf[idx:idx+needle_len]`` 是否是一个整词（两侧都不是 word 字节；文件边界算侧翼）。"""
    if idx > 0 and buf[idx - 1] in _WORD_BYTES:
        return False
    end = idx + needle_len
    if end < len(buf) and buf[end] in _WORD_BYTES:
        return False
    return True


def find_first(buf: bytes, needles: List[bytes], fold: bool, *,
               word: bool = False, start: int = 0) -> int:
    """``buf[start:]`` 里最左的命中位置（绝对偏移），没有则 -1。

    折叠安全性：**``bytes.lower()`` 只改 ASCII 字节**，``region`` 与 ``buf`` 逐字节
    等长同位，所以在 ``region`` 上取到的索引可以直接交给 :func:`word_ok` 用 ``buf``
    判定 —— 这也是不做 ``casefold()``（那会改长度）的原因。
    """
    region = buf.lower() if fold else buf
    best = -1
    for needle in needles:
        pos = start
        # 已经有更左的命中时，只需在 [start, best) 里找能否击败它
        stop_at = best if best >= 0 else None
        while True:
            pos = region.find(needle, pos, stop_at)
            if pos < 0:
                break
            if not word or word_ok(buf, pos, len(needle)):
                best = pos
                stop_at = best
                break
            pos += 1          # 整词不合格：从下一个字节继续，而非跳过整个 needle
    return best


def fuzzy_match(needle: bytes, buf: bytes) -> bool:
    """``buf`` 是否以**子序列**方式含 ``needle``（顺序要、连续不要）。grep 档无此原语。"""
    return _fuzzy_index(needle, buf) >= 0


def _fuzzy_index(needle: bytes, buf: bytes, start: int = 0) -> int:
    """单向前进的贪心子序列扫描：线性时间、无回溯。返回首个字符位置，不命中 -1。

    从**最早**的首字符出现处起手就够：起点越晚可用尾巴越短，最早处匹不出来意味着
    任何更晚的起点也匹不出来，所以不需要回头重试。
    """
    if not needle:
        return -1
    pos = buf.find(needle[:1], start)
    if pos < 0:
        return -1
    cursor = pos
    for byte in needle[1:]:
        cursor = buf.find(bytes((byte,)), cursor + 1)
        if cursor < 0:
            return -1
    return pos


def _locate(buf: bytes, needles: List[bytes], fold: bool, *, word: bool,
            fuzzy: bool, start: int, at_eof: bool) -> int:
    """下一个命中的绝对偏移，没有则 -1。substring/whole_word 与 fuzzy 两条路都走这里。"""
    if not fuzzy:
        return find_first(buf, needles, fold, word=word, start=start)
    return _fuzzy_locate(buf, needles, fold, start, at_eof)


def _fuzzy_locate(buf: bytes, needles: List[bytes], fold: bool, start: int,
                  at_eof: bool) -> int:
    """子序列是**行级**谓词（参考工具 ``content_searcher.py:100``），所以逐行判。

    只判完整行：半行的尾巴可能就在下一次读里，判早了 snippet 会缺尾。``at_eof``
    时才判最后一段没有行尾的内容（文件末行常不带 ``\\n``）。
    """
    cursor = start
    while True:
        nl = buf.find(b'\n', cursor)
        if nl < 0 and not at_eof:
            return -1
        line = buf[cursor:] if nl < 0 else buf[cursor:nl]
        probe = line.lower() if fold else line
        if line and any(fuzzy_match(needle, probe) for needle in needles):
            return cursor
        if nl < 0:
            return -1        # 最后半行也判过了
        cursor = nl + 1


def extract_line(buf: bytes, idx: int) -> bytes:
    """``idx`` 所在那一行的原始字节（不含 ``\\n``，末尾 ``\\r`` 也去掉）。"""
    start = buf.rfind(b'\n', 0, idx) + 1
    end = buf.find(b'\n', idx)
    return buf[start:len(buf) if end < 0 else end].rstrip(b'\r')


# ------------------------------------------------------------------ 编码与文件头


def detect_encoding(first_line: bytes) -> str:
    """四探取第一个能整行解开的编码；全失败退回 utf-8（由 :func:`decode_line` 兜底）。"""
    for encoding in _PROBE_ENCODINGS:
        try:
            first_line.decode(encoding)
            return encoding
        except (UnicodeError, LookupError):
            continue          # 探不出来就换下一个，最后有 utf-8 兜底
    return 'utf-8'


def decode_line(raw: bytes, encoding: Optional[str]) -> str:
    """解一行。``encoding`` 是按**第一行**探测出来的，本行未必同族，所以留退路；
    全都解不开时忽略非法字节而不是抛 —— 一个坏字节不该让整个搜索炸。"""
    candidates = ((encoding,) if encoding else ()) + _PROBE_ENCODINGS
    for candidate in candidates:
        try:
            return raw.decode(candidate)
        except (UnicodeError, LookupError):
            continue          # 换下一个候选编码
    return raw.decode('utf-8', errors='ignore')


_HEAD_FIELDS = {'TestFile': 'test_file', 'StartTime': 'start_time',
                'PtsModifyTime': 'pts_modify_time'}


def parse_head(head: bytes) -> Tuple[str, str, str]:
    """从文件头抽 ``(TestFile, StartTime, PtsModifyTime)``，遇 ``[DATA]`` 即停。

    head 是按字节切的，**最后一段很可能是半行**：留着它会把残缺值当真值
    （``StartTime,2026-09-01 0`` 会被当成一个时间），所以不以 ``\\n`` 结尾就丢掉。
    ``[DATA]`` 之后停是防「数据区里某行首列撞 TestFile」覆盖头部真值。
    """
    found = {'test_file': '', 'start_time': '', 'pts_modify_time': ''}
    if not head:
        return '', '', ''
    lines = head.split(b'\n')
    if not head.endswith(b'\n'):
        lines = lines[:-1]
    encoding = None
    for raw in lines:
        if encoding is None:
            encoding = detect_encoding(raw)
        text = decode_line(raw, encoding).rstrip('\r')
        if text.startswith('['):
            if text[1:].partition(']')[0].strip().upper() == 'DATA':
                break
            continue          # 别的 section 标记行照常跳过
        key, _, value = text.partition(',')
        field = _HEAD_FIELDS.get(key.strip())
        value = value.strip().rstrip(',')
        if field and value and not found[field]:
            found[field] = value.split('\\')[-1] if field == 'test_file' else value
    return found['test_file'], found['start_time'], found['pts_modify_time']


def truncate_head_for_test(head: bytes) -> bytes:
    """造出「最后一个字段被切成半行」的 head —— 只给测试用（见 :func:`parse_head`）。"""
    return head[:head.rfind(b'\r\n', 0, len(head) - 2) + 1]


# ------------------------------------------------------------------ 异常分层


def _is_file_scoped(exc: BaseException) -> bool:
    """这次异常是「这个文件读不了」还是「这条连接坏了」。

    判错的代价不对称：把坏死连接当文件级就地吞掉，后续每个文件都在同一条脏连接上
    白跑；把一次「文件被并发改掉」（搜索期间是常态）上抛，整次搜索陪葬。所以
    非 OSError（``SSHException`` / ``SFTPError`` / ``EOFError``，含
    ``HostKeyMismatchError`` ⊂ ``SSHException``）一律上抛，OSError 里只认服务端
    回给单个文件的状态码：``errno`` 在 :data:`_FILE_SCOPE_ERRNOS` 里，或是 paramiko
    用 ``IOError(text)`` 表达的无 errno 状态。
    **超时先否掉**：``channel_timeout`` 到点是 ``socket.timeout``（TimeoutError ⊂
    OSError，常无 errno），它在途请求的响应会被下一个读走去，等于连接脏了。
    """
    if not isinstance(exc, OSError):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return False
    return exc.errno is None or exc.errno in _FILE_SCOPE_ERRNOS


def _start_prefetch(remote, size: int) -> None:
    """让服务端并发预取整个文件，把 1 MiB 大块读的往返藏掉（不预取就是逐 chunk 一个来回）。

    三种「没有」都只让扫描变慢、不影响正确性，所以都不算错：没有 ``prefetch`` 属性
    （老 paramiko 或测试替身）、``size`` 未知、服务端拒绝预取。
    """
    prefetch = getattr(remote, 'prefetch', None)
    if prefetch is None or size <= 0:
        return
    try:
        try:
            prefetch(size, MAX_INFLIGHT)
        except TypeError:
            prefetch(size)     # 老 paramiko 没有 max_concurrent_requests 形参
    except Exception as exc:  # noqa: BLE001 —— 预取失败退回慢路径，继续扫
        logger.warning('SFTP search prefetch failed for %s bytes: %s',
                       size, exc, exc_info=True)


# ------------------------------------------------------------------ 扫描主体


def scan_file(sftp, cand: Candidate, spec: SearchSpec) -> Optional[Dict[str, object]]:
    """扫一个文件。命中返回结果 dict，不命中（含读不了）返回 ``None``。

    ``hits`` 是 ``[{line, snippet}]``；顶层 ``line``/``snippet`` 是 ``hits[0]`` 的别名，
    因为 SSE 事件与结果表两个形状都要它，别在下游各写一遍 ``or``。
    """
    needles, fold = build_needles(spec.term, spec.case_sensitive)
    if not needles:
        return None
    word = spec.matching == 'whole_word'
    fuzzy = spec.matching == 'fuzzy'
    want = 1 if spec.first_hit_per_file else max(1, spec.matches_per_file)
    # 收缩后必须留在窗口里的字节数。needle 可以恰好被 chunk 切成两半，所以窗口要能
    # 装下「残段」；LINE_CONTEXT 远大于 MAX_TERM_LEN 编出来的任何 needle，
    # 于是命中位置的左邻字节必在窗口内 —— 整词判定不会因收缩而看到假的文件开头。
    keep = max(max(len(needle) for needle in needles) - 1, LINE_CONTEXT)

    hits: List[Dict[str, object]] = []
    head = b''
    buf = b''
    newlines_before = 0        # 已被窗口挤掉的字节里数到的换行数
    search_from = 0            # buf 内偏移（不是绝对 idx，别混用）
    encoding: Optional[str] = None
    scanned = 0
    eof = False

    try:
        with sftp.open(cand.path, 'rb') as remote:
            _start_prefetch(remote, cand.size)
            while len(hits) < want:
                chunk = remote.read(CHUNK_SIZE)
                if chunk:
                    if len(head) < HEAD_SIZE:
                        head += chunk[:HEAD_SIZE - len(head)]
                    buf += chunk
                    scanned += len(chunk)
                else:
                    eof = True

                while len(hits) < want:
                    idx = _locate(buf, needles, fold, word=word, fuzzy=fuzzy,
                                  start=search_from, at_eof=eof)
                    if idx < 0:
                        break
                    if not fuzzy and not eof and buf.find(b'\n', idx) < 0:
                        # 命中行的行尾还没进窗口，snippet 会缺尾巴。补读一次就够
                        # （CHUNK_SIZE ≫ 参考工具那个 400 字节下限）。
                        more = remote.read(CHUNK_SIZE)
                        if more:
                            buf += more
                            scanned += len(more)
                        else:
                            eof = True
                    if encoding is None:
                        # 首次定位时才探测：不命中就一个字节都不该 decode
                        encoding = detect_encoding(head.split(b'\n', 1)[0])
                    hits.append({
                        'line': newlines_before + buf.count(b'\n', 0, idx) + 1,
                        'snippet': decode_line(extract_line(buf, idx),
                                               encoding).strip()[:SNIPPET_MAX],
                    })
                    if fuzzy:
                        end_of_line = buf.find(b'\n', idx)
                        search_from = len(buf) if end_of_line < 0 else end_of_line + 1
                    else:
                        search_from = idx + 1

                if eof:
                    break      # 上面那一轮已经按 at_eof 判过尾行了
                if len(buf) > keep:
                    consumed = len(buf) - keep
                    newlines_before += buf.count(b'\n', 0, consumed)
                    buf = buf[consumed:]
                    search_from = max(0, search_from - consumed)
                # 预算判定放在收缩之后：放前面会被 keep 改变语义
                if spec.max_scan_bytes and scanned >= spec.max_scan_bytes:
                    break
    except CONNECTION_ERRORS as exc:
        if not _is_file_scoped(exc):
            raise              # 让 SearchSession 把这条脏连接换掉再派下一个文件
        logger.warning('SFTP search could not read %s: %s', cand.path, exc)
        return None
    except Exception as exc:  # noqa: BLE001 —— 单文件的意外只丢这个文件，不丢搜索
        logger.warning('Search could not scan %s: %s', cand.path, exc)
        return None

    if not hits:
        return None
    test_file, start_time, pts_modify_time = parse_head(head)
    result: Dict[str, object] = {
        'path': cand.path, 'name': cand.name, 'size': cand.size,
        'mtime': cand.mtime, 'line': hits[0]['line'],
        'snippet': hits[0]['snippet'], 'hits': hits,
        'test_file': test_file, 'start_time': start_time,
        'pts_modify_time': pts_modify_time,
    }
    return result
