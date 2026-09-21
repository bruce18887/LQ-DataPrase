"""服务端 grep 加速档：命令构造、两级能力探测与输出解析（spec §3.6）。

**全项目唯一允许拼 shell 命令字符串的模块。** 这个「唯一」不是靠自觉，由
``test/backend/test_sftp_search_grep.py::ShellSurfaceTests`` 在源码层面钉住：
``apps/`` 下除本文件外不得再出现 ``exec_command(``。相应地有两条硬规则：

1. 任何要进命令串的字符串**只能**经 :func:`_q`（= ``shlex.quote``）出去，
   包括路径、``term``、``name_pattern`` 与日期；``!`` 也要引（bash 里它是历史展开）。
2. ``term`` 永远配 ``-F``（固定串）+ ``-e <quoted>``。少了 ``-F``，``.*`` 这类
   查询串就会被当正则解释，「用户输入」当场变成「查询语言」。选项与值分两个
   token（``-e`` 与引好的串），``--`` 收尾挡住以 ``-`` 开头的路径。

``LC_ALL=C`` 前缀**故意不引**：它让 ``-w``/``-i`` 的字节语义在远端可预期（否则
``grep -w`` 的 word 判定随远端 locale 变，两档引擎就给不出同一结果集了）。它是常量
字符串，不是插值点。

**非 ASCII 查询进不了这一档**（``select_engine`` 已整体排除：这类查询的本域 CSV 常是
GBK 编码，grep 只按 UTF-8 字节匹配会静默漏结果），所以这里没有、也不许补「再追加一条
另一编码的 needle」那类写法：参考工具用的是 bash 专有的 ANSI-C 引用语法，在 dash/sh 下
语义不同 —— 那等于把结果是否完整押在远端 shell 是哪个上。

探测分两级（spec §3.6）：``grep`` 级 = ``grep --version`` + **我们拼的那几个选项它认不认**
+ SFTP/shell 路径映射一致；``find_xargs`` 级 = 额外的 GNU ``find -newermt`` 与 ``xargs -0 -r``。
任何一级不过都交回 :class:`ProbeResult`，由上层回落 client 并出 ``notice``。

**为什么选项存在性也是探测的一部分**：``--include`` / ``--exclude`` / ``--exclude-dir``
的语义（大小写敏感、按命令行顺序求值且**最后命中的规则决定去留**、``--exclude`` 不管
目录而 ``--exclude-dir`` 不管文件、多条 ``--include`` 之间是并集）是 **GNU grep 的实现
细节，不是 POSIX**。本模块的结果集平价正是钉在这几条语义上的，所以「``grep --version``
过了」并不够——探测必须真的拿这三个选项跑一次：探测通过而选项不存在 == 命令以退出码 2
结束 == 一次白跑（虽然会被 :func:`grep_stream` 抛回落，但要慢一整趟）。

**与 walker 的结果集平价（spec §3.3）**：dot 条目、``prune_dirs``、``data_files_only``
（汇总 CSV 与非 ``.csv``）三条规则在 walker 里是 Python 判定，这里必须翻成语义逐字相同
的 glob —— 判据与 glob 写法全部取自 :mod:`apps.sftp.search.filters`（唯一共享定义，
含「grep 侧大小写敏感所以要写成 ``[sS][uU][mM]_*``」这类细节）。翻不出来的就回落：
``depth`` 限制（GNU grep 没有 ``--max-depth``）、``name_pattern`` 与 ``*.csv`` 求交
（``--include`` 是并集 → 改走 find 分支）、以及根目录名撞上目录排除模式（grep/find 会
连根一起跳过，walker 却总会进根目录），判据都在 ``select_engine``/``filters``。

**已知残留（未闭合，故显式记录）**：软链接的取舍两档不同 —— walker 把 listing 里
非 ``S_IFDIR`` 的条目一律当文件打开（跟随软链接），而 ``grep -r`` 与 ``find -type f``
都**跳过**软链接。换 ``-R`` / ``find -L`` 只是把分歧挪到「服务器把软链接目录报成
``S_IFDIR`` 还是 ``S_IFLNK``」那一侧（``walker._is_dir`` 的 docstring 记的就是这个不确定），
两个方向都不平价。本地无法取证（Git Bash 造不出真软链接），处置留 Task 11 真机验证；
在此之前不要把 ``-r`` 改成 ``-R``，那属于换了个分歧而不是消除分歧。
"""

import logging
import shlex
import socket
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from apps.sftp.search import filters
from apps.sftp.search.contracts import SearchSpec
from apps.sftp.search.engine import (GREP_SELECT_INTERSECTION_MSG, PATH_MAPPING_MSG,
                                     ProbeResult, ROOT_EXCLUSION_MSG)

logger = logging.getLogger(__name__)

# 探测命令自带 2>&1：探测只借一条通道，不另开 stderr 流——命令没跑起来时
# 那份 stderr 正是 reason 的全部内容，分两条流读就要多一次阻塞。
_GREP_VERSION_CMD = 'grep --version 2>&1'
_FIND_XARGS_CMD = 'find --version 2>&1; xargs --version 2>&1'
_MAPPING_TOKEN = 'MAPPING_OK'

# 选项存在性探测：喂空输入，让「选项被接受」表现为退出码 1（没有一行匹配），
# 「不认这个选项」表现为 2 + 一句 unrecognized option。``-q`` 只是不想让远端把
# 探测当成真查询往外吐数据；选项解析在 ``-q`` 生效之前，报错照样进 2>&1。
_SELECTION_OPTS_CMD = ("printf '' | LC_ALL=C grep -q -F -e zz --exclude=zz "
                       '--exclude-dir=zz --include=zz 2>&1')

_GREP_MISSING_MSG = '服务端没有可用的 grep（grep --version 未通过）'
_SELECTION_OPTS_MSG = ('服务端 grep 不认 --include/--exclude/--exclude-dir'
                       '（文件选择平价靠的就是这三条）')
_PROBE_FAILED_MSG = '探测服务端 grep 失败'
_PROBE_TIMEOUT_SEC = 5      # 探测卡住 == 探测不过，宁可快速回落
_READ_TICK_SEC = 2.0        # grep 流的读超时：把取消延迟压到秒级

_DATE_ARG_FORMAT = '%Y-%m-%d %H:%M:%S'


def _q(value: Any) -> str:
    """唯一的插值出口：任何进命令串的东西都过这里。"""
    return shlex.quote(str(value))


# ------------------------------------------------------------------ 命令构造


def _grep_options(spec: SearchSpec) -> List[str]:
    """选项区。两档共用同一份，免得无 find 与有 find 两条路径的语义漂移。

    ``-r`` 在 find 分支里是冗余的（文件由 xargs 逐个喂进来），但留着无害，
    换来的是「两档的选项区逐字相同」这条可断言的性质。
    """
    options = ['-a', '-H', '-F', '-n', '-r']
    if not spec.case_sensitive:
        options.append('-i')
    if spec.matching == 'whole_word':
        options.append('-w')
    options += ['-m', '1' if spec.first_hit_per_file else str(spec.max_matches)]
    return options


def build_command(spec: SearchSpec, *, use_find: bool) -> str:
    """拼出这次要发给远端的命令。``use_find`` = 文件选择不能只靠 grep 的选项完成。

    走哪条分支由 :func:`apps.sftp.search.filters.needs_find` 判（``grep_stream`` 就是
    这么调的）。因此 ``use_find=False`` 却带上 grep 表达不出的选择条件，等于设计被绕过
    —— 下面两道 ``ValueError`` 与「``term`` 非空」那道是同一类第二道闸：宁可拒绝发命令，
    也不发一条会**静默少结果**的命令。
    """
    if not spec.term:
        raise ValueError('grep requires a non-empty term')
    if filters.root_collides_with_dir_excludes(spec):
        raise ValueError(ROOT_EXCLUSION_MSG)
    if not use_find and filters.grep_cannot_select(spec):
        raise ValueError(GREP_SELECT_INTERSECTION_MSG)
    needle = ['-e', _q(spec.term)]
    if use_find:
        return _find_then_grep(spec, _grep_options(spec) + needle)
    parts = ['LC_ALL=C', 'grep', *_grep_options(spec), *needle]
    # **顺序就是语义**（实测 GNU grep 3.0）：``--include``/``--exclude`` 是一个按命令行
    # 顺序求值的规则表，**最后命中的那条决定**去留（不是「exclude 恒压 include」）。
    # 所以 include 必须全部先发、exclude 全部后发 —— 这样在「exclude 恒压 include」
    # 那一类实现里也得到同一个结果，两种语义同解，才谈得上跨服务器平价。反过来排会
    # 静默把 dot 文件与汇总 CSV 放进来（本次实测过：include 后发时 16 个文件全回来）。
    # 目录侧独立命名空间：``--exclude-dir`` 只判目录，与文件规则无交叉（实测）。
    if spec.data_files_only:
        # 汇总 CSV 与 .csv 后缀：grep 这两条 glob 都是大小写敏感的，折叠写法在 filters。
        parts.append(f'--include={_q(filters.CSV_GREP_GLOB)}')
    if spec.name_pattern:
        parts.append(f'--include={_q(spec.name_pattern)}')
    parts.append(f'--exclude={_q(filters.DOT_GLOB)}')
    if spec.data_files_only:
        parts.append(f'--exclude={_q(filters.SUMMARY_GREP_GLOB)}')
    parts += _dir_exclusion_args(spec)
    parts.append('--')
    parts += [_q(root) for root in spec.roots]
    return ' '.join(parts)


def _dir_exclusion_args(spec: SearchSpec) -> List[str]:
    """``prune_dirs`` + dot 目录 → 每个模式一条 ``--exclude-dir``（照旧逐条过 :func:`_q`）。

    grep 只拿目录的 basename 去匹这些 glob，命中即不进入 —— 与 walker
    :func:`~apps.sftp.search.walker.is_pruned`（basename + ``fnmatchcase``）同口径，
    所以被剪掉的整棵子树在两档里以同样的方式消失。
    """
    return [f'--exclude-dir={_q(glob)}' for glob in filters.dir_exclude_globs(spec)]


def _find_then_grep(spec: SearchSpec, grep_args: Sequence[str]) -> str:
    """``find ... -print0 | xargs -0 -r env LC_ALL=C grep ...``。

    ``-print0``/``-0`` 是一对：文件名带空格换行也不分裂；``-r`` 让空结果集
    根本不启动 grep（否则 xargs 会带空参数列表跑一次，读 stdin 卡住）。

    文件选择整个交给 find 的谓词（grep 那边一个 ``--include``/``--exclude`` 都不发）：
    只有 find 能把多个 glob 以**与**的方式串起来。三段与 walker 一一对应：

    * ``find <roots> ( -type d ( -name '.*' -o -name <prune> ... ) -prune )``
      —— 不进入 dot 目录与被 ``prune_dirs`` 命中的目录。``-type d`` 是必需的：walker
      只对目录判 prune，一个恰好叫 ``cache`` 的**文件**照样是候选。
    * ``-o ( -type f`` + ``! -name '.*'`` —— dot 文件不进结果（dot 目录已被上面剪掉，
      这条补的是文件侧，与 grep 分支那两条 ``--exclude``/``--exclude-dir`` 等价）。
    * ``[ -name <name_pattern> ] [ -iname '*.csv' ! -iname 'sum_*' ]`` —— 文件名模式与
      「仅数据文件」的求交在这里才表达得出来；``-iname`` 自带大小写不敏感，正好对上
      walker 的 ``.lower()`` 判据。

    圆括号必须引：它们在 shell 里是分组语法，不过 :func:`_q` 就是一次命令注入面。
    """
    parts = ['find']
    parts += [_q(root) for root in spec.roots]
    parts += [_q('('), '-type', 'd', _q('(')]
    for index, glob in enumerate(filters.dir_exclude_globs(spec)):
        if index:
            parts.append('-o')
        parts += ['-name', _q(glob)]
    parts += [_q(')'), '-prune', _q(')'), '-o', _q('('),
              '-type', 'f', _q('!'), '-name', _q(filters.DOT_GLOB)]
    if spec.name_pattern:
        parts += ['-name', _q(spec.name_pattern)]
    if spec.data_files_only:
        parts += ['-iname', _q(filters.CSV_FIND_GLOB),
                  _q('!'), '-iname', _q(filters.SUMMARY_FIND_GLOB)]
    if spec.min_size is not None:
        parts += ['-size', _q(f'+{int(spec.min_size)}c')]
    if spec.max_size is not None:
        parts += ['-size', _q(f'-{int(spec.max_size)}c')]
    if spec.modified_after:
        parts += ['-newermt', _q(spec.modified_after.strftime(_DATE_ARG_FORMAT))]
    if spec.modified_before:
        # 「早于」= 非（新于或等于）：`!` 在 bash 里是历史展开，必须引。
        parts += [_q('!'), '-newermt',
                  _q(spec.modified_before.strftime(_DATE_ARG_FORMAT))]
    parts += ['-print0', _q(')'), '2>/dev/null']
    tail = ' '.join(['xargs', '-0', '-r', 'env', 'LC_ALL=C', 'grep', *grep_args, '--'])
    return ' '.join(parts) + ' | ' + tail


# ------------------------------------------------------------------ 输出解析


def _looks_like_lineno(token: bytes) -> bool:
    """行号判定：纯数字**且没有前导零**。

    没有后半条，内容里的时间戳（``StartTime,2026:09:01``）会被当成第二个候选
    分隔点，真实数据几乎每行都触发歧义告警，WARNING 就废了。
    """
    if not token.isdigit():
        return False
    return not (len(token) > 1 and token.startswith(b'0'))


def parse_line(raw: bytes) -> Optional[Tuple[str, int, bytes]]:
    """解析 ``path:line:content``。解析不出来的行**一律留 WARNING**（计划 §6 风险表）。

    ``-H`` 打印的路径里可能含冒号（``a:b.csv``），内容里也可能有冒号，所以「哪个
    冒号是分隔符」本质上是歧义的。取最左的合法行号候选：路径错了上层 stat 会失败
    并出 ``error{scope:"file"}``，比悄悄丢一行更可查。
    """
    line = raw.rstrip(b'\r\n')
    if not line:
        return None
    if line.startswith(b'Binary file '):
        return None
    parts = line.split(b':')
    if len(parts) < 3:
        logger.warning('grep output line is not path:line:content (no separators): %r',
                       line[:200])
        return None
    candidates = [i for i in range(1, len(parts) - 1) if _looks_like_lineno(parts[i])]
    if not candidates:
        logger.warning('grep output line has a non-numeric line number, skipped: %r',
                       line[:200])
        return None
    if len(candidates) > 1:
        logger.warning(
            'grep output line is ambiguous (colon inside path), taking the leftmost '
            'line number: %r', line[:200])
    at = candidates[0]
    path = b':'.join(parts[:at]).decode('utf-8', errors='ignore')
    return path, int(parts[at]), b':'.join(parts[at + 1:])


# ------------------------------------------------------------------ 通道工具


def _arm_read_timeout(chan: Any, seconds: float) -> None:
    """给 channel 设读超时。``readline`` 会一直阻塞到下一个字节，不设超时取消就得
    等远端吐下一行才生效（spec §3.9 要求取消延迟有界）。

    设不上（测试替身、或通道实现不同）就只可能是「取消慢一点」，就地 WARNING。
    """
    try:
        chan.settimeout(seconds)
    except Exception as exc:                            # noqa: BLE001
        logger.warning('grep: cannot arm the read timeout (%s); cancellation now has '
                       'to wait for the next line of grep output', exc)


def _readline(chan_file: Any) -> Optional[bytes]:
    """一行；``None`` = 读超时（不是 EOF），``b''`` = EOF。"""
    try:
        return chan_file.readline()
    except socket.timeout:
        return None


def _run(chan: Any, cmd: str) -> Tuple[int, bytes]:
    """跑一条探测命令并读到 EOF。探测命令输出都很短，不值得做流式。"""
    chan.exec_command(cmd)
    return chan.recv_exit_status(), chan.makefile('rb').read()


# ------------------------------------------------------------------ 能力探测


def probe(chan_factory: Callable[[], Any], roots: Sequence[str]) -> ProbeResult:
    """三级探测（grep 在 → grep 认我们的选项 → 路径映射一致，外加 find/xargs 一级）。

    任何异常都收成 ``ProbeResult(usable=False)``，绝不上抛。

    探测不过不是错误而是环境事实——上层据此回落 client，搜索照跑。让它抛就等于
    「服务器没有 grep」变成「搜索 500」。选项存在性排在映射之前：那三条 glob 选项是
    结果集平价的地基（见模块 docstring），不认就是整档不可用，不必再花时间试路径。
    """
    chan: Any = None
    try:
        chan = chan_factory()
        _arm_read_timeout(chan, _PROBE_TIMEOUT_SEC)

        exit_code, out = _run(chan, _GREP_VERSION_CMD)
        has_grep = exit_code <= 1 and b'grep' in out.lower()
        if not has_grep:
            hint = out[:200].decode('utf-8', errors='ignore').strip()
            return ProbeResult(False, False, False, f'{_GREP_MISSING_MSG}：{hint}')

        exit_code, out = _run(chan, _SELECTION_OPTS_CMD)
        if exit_code > 1:
            hint = out[:200].decode('utf-8', errors='ignore').strip()
            return ProbeResult(False, False, False,
                               f'{_SELECTION_OPTS_MSG}：{hint or f"退出码 {exit_code}"}')

        exit_code, out = _run(chan, _FIND_XARGS_CMD)
        low = out.lower()
        has_find_xargs = b'find' in low and b'xargs' in low

        mapping_ok = _probe_mapping(chan, roots)
        return ProbeResult(True, has_find_xargs, mapping_ok,
                           '' if mapping_ok else f'路径映射探测未通过：{PATH_MAPPING_MSG}')
    except Exception as exc:                            # noqa: BLE001
        logger.warning('SFTP search: grep capability probe failed: %s', exc, exc_info=True)
        return ProbeResult(False, False, False, f'{_PROBE_FAILED_MSG}：{exc}')
    finally:
        if chan is not None:
            try:
                chan.close()
            except Exception as exc:                    # noqa: BLE001
                logger.warning('SFTP search: failed to close the probe channel: %s', exc)


def _probe_mapping(chan: Any, roots: Sequence[str]) -> bool:
    """SFTP 侧看见的路径，shell 侧在同一位置吗（chroot 会不一致）。

    不一致还去 grep，就是搜一个不存在的路径、安静返回 0 命中——那是假阴性，
    比慢和报错都恶劣，所以这一条判不过就把整个 grep 档判死。

    **有意偏离参考工具**：``csv_content_searcher.py:213`` 是先 ``sftp.listdir(root)``
    取一个条目、再到 shell 侧 ``[ -e <root>/<条目> ]``。这里直接测 root 本身：
    chroot 下 shell 侧通常连 ``/data`` 都不可见，判别力相同，却省掉一次 SFTP 往返
    （probe 只有一个 transport 可用）。spec §3.6 只要求「映射一致」，未规定粒度。
    """
    for root in roots:
        _exit_code, out = _run(chan, f'[ -e {_q(root)} ] && echo {_MAPPING_TOKEN}')
        if _MAPPING_TOKEN.encode() in out:
            return True
    return False


# ------------------------------------------------------------------ 命中流


def grep_stream(chan: Any, spec: SearchSpec, *,
                cancel_event: Any = None,
                deadline: Optional[float] = None) -> Iterator[Dict[str, Any]]:
    """执行 grep 并逐命中 yield ``{path, line, snippet}``（元数据由 Task 9 补）。

    退出码语义分开对待：``0`` 有命中、``1`` 真的没命中（正常收尾）、
    ``>=2`` 是 grep 自己出错了 —— 必须抛出让上层回落 client，绝不能被当成
    「这个目录里没有」而静默少结果。
    """
    chan.exec_command(build_command(spec, use_find=filters.needs_find(spec)))
    _arm_read_timeout(chan, _READ_TICK_SEC)
    stream = chan.makefile('rb')
    unparsed: List[bytes] = []
    while True:
        raw = _readline(stream)
        if raw is None:                                 # 读超时：该看看要不要停了
            if _stopped(cancel_event, deadline):
                _abandon(chan)
                return
            continue
        if not raw:
            break                                       # EOF
        if _stopped(cancel_event, deadline):
            _abandon(chan)
            return
        parsed = parse_line(raw)
        if parsed is None:
            stripped = raw.rstrip(b'\r\n')
            if stripped and not stripped.startswith(b'Binary file '):
                unparsed.append(stripped)                # 出错原因很可能就混在这里头
            continue
        path, line_no, content = parsed
        yield {'path': path, 'line': line_no, 'snippet': _snippet(content)}

    exit_code = chan.recv_exit_status()
    if exit_code >= 2:
        detail = _stderr_text(chan) or b'\n'.join(unparsed[-5:])
        text = detail.decode('utf-8', errors='ignore').strip()
        raise RuntimeError(
            f'grep failed: {(text or f"服务端未给出原因（退出码 {exit_code}）")[:300]}')


def _stopped(cancel_event: Any, deadline: Optional[float]) -> bool:
    if cancel_event is not None and cancel_event.is_set():
        return True
    return deadline is not None and time.monotonic() >= deadline


def _abandon(chan: Any) -> None:
    """关掉通道即终止远端 grep；关闭失败不该盖掉「已取消」这个正常结局。"""
    try:
        chan.close()
    except Exception as exc:                            # noqa: BLE001
        logger.warning('grep: failed to close the channel while cancelling: %s', exc)


def _stderr_text(chan: Any) -> bytes:
    try:
        return chan.makefile_stderr('rb').read()
    except Exception as exc:                            # noqa: BLE001
        logger.warning('grep: cannot read stderr (%s); falling back to the unparsed '
                       'stdout lines for the reason', exc)
        return b''


def _snippet(content: bytes) -> str:
    """片段解码复用 scanners 的四探（utf-8/gbk/gb2312/utf-16），不在这里另写一份。

    延迟 import：本模块被 ``engine`` 导入，而 grep 档只在探测通过后才用得到解码；
    放在模块级会让「只用 client 档」的进程也背上整份扫描栈。
    """
    from apps.sftp.search import scanners

    encoding = scanners.detect_encoding(content)
    return scanners.decode_line(content, encoding).strip()[:scanners.SNIPPET_MAX]
