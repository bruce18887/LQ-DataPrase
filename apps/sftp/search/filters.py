"""条目过滤规则的**单一事实源**：walker 的 Python 判定 ↔ shell_grep 的 glob 翻译。

spec §3.3 的不变量是「同一个 SearchSpec 必须得到同一个结果集，与目标服务器恰好有没有
grep 无关」。参照档是 walker，而 grep 档只能表达 glob，不能表达 Python 代码 —— 于是
「哪些条目算隐藏 / 算汇总 / 算数据文件」这套判定必须只有一份定义：walker 直接调用这里的
谓词，shell_grep 调用这里的 glob 常量把它们翻译成 ``--include`` / ``--exclude`` /
``--exclude-dir`` 或 find 谓词。谁都不许在本地另写一份字面量。

三条规则的原始出处（改任何一条都要同时回到这里）：

- 隐藏条目：``apps/sftp/views.py:537`` ``_collect_files`` 的 ``name.startswith('.')``
  （dot 目录与 dot 文件都不进、不列）。
- 汇总 CSV：``apps/datafiles/views/_helpers.py:71`` 的
  ``os.path.basename(filename).lower().startswith('sum_')`` —— 直接复用那个函数，不重写。
- 数据 CSV：``posixpath.splitext(name)[1].lower() == '.csv'`` 且非汇总，与
  ``_collect_files`` 的 ``only_data`` 分支逐字同判据。

**glob 的大小写写法是实测出来的，不要"顺手简化"**（GNU grep 3.0）：

- grep 的 ``--include``/``--exclude``/``--exclude-dir`` 一律**大小写敏感**，而 walker 判
  扩展名与汇总前缀时先 ``.lower()``。所以 grep 档必须用 bracket 形式逐字母折叠
  （``*.[cC][sS][vV]``、``[sS][uU][mM]_*``），否则 ``DATA.CSV`` 这类文件名在两档间漂移。
- find 的 ``-iname`` 本身大小写不敏感 → 用裸 glob；``-name`` 大小写敏感 → 与
  :func:`is_pruned` 的 :func:`fnmatch.fnmatchcase` 同口径。
- grep 的 ``--include``/``--exclude`` 是**一张按命令行顺序求值的规则表，最后命中的
  那条决定去留**（实测 GNU grep 3.0；并不是「exclude 恒压 include」），且 ``--exclude``
  只作用于文件、``--exclude-dir`` 只作用于目录 —— 所以 dot 规则要同时出这两条。
  结论对命令构造是硬性的：**include 必须全部先发、exclude 全部后发**，那样在
  「exclude 恒压 include」那一类实现里也同解；反序则 dot 文件与汇总 CSV 会漏进来。
  walker 的判定顺序（dot/汇总/非 csv 一律否决，``name_pattern`` 只否决不匹配者）与
  这个排法等价，故三条规则可译。
"""

import fnmatch
import posixpath
from typing import List

from apps.datafiles.views import _is_summary_csv

from apps.sftp.search.contracts import SearchSpec

# —— 隐藏条目：dotfile 与 dot 目录共用一条 glob（grep/find/fnmatch 三种实现同形）——
DOT_GLOB = '.*'

# —— 汇总 / 数据文件，grep 档的 bracket 形式（grep 侧 glob 大小写敏感）——
SUMMARY_GREP_GLOB = '[sS][uU][mM]_*'
CSV_GREP_GLOB = '*.[cC][sS][vV]'

# —— 同样两条规则在 find 档的写法（配 ``-iname``，故无需折叠）——
SUMMARY_FIND_GLOB = 'sum_*'
CSV_FIND_GLOB = '*.csv'


def is_hidden(name: str) -> bool:
    """以 ``.`` 开头的条目不进结果、目录也不进入（``views.py:537`` 的既有约定）。"""
    return name.startswith('.')


def is_summary_entry(name: str) -> bool:
    """汇总 CSV。直接委托给 ``_is_summary_csv``，本模块不重新定义什么叫汇总。"""
    return _is_summary_csv(name)


def is_data_csv(name: str) -> bool:
    """``data_files_only`` 的判定：``.csv`` 后缀（大小写不敏感）且非汇总。"""
    if posixpath.splitext(name)[1].lower() != '.csv':
        return False
    return not is_summary_entry(name)


def dir_exclude_globs(spec: SearchSpec) -> List[str]:
    """grep ``--exclude-dir`` / find ``-prune`` 要用的目录 glob：dot 规则 + 每条 prune。

    顺序固定（dot 在前、prune 按用户输入顺序），两档、两条分支都从这里取，保证
    命令构造端与 :func:`apps.sftp.search.walker.is_pruned` 端是同一批模式。
    """
    return [DOT_GLOB, *spec.prune_dirs]


def root_collides_with_dir_excludes(spec: SearchSpec) -> bool:
    """某个根目录**自己的名字**撞上了要发给 grep/find 的目录排除模式。

    walker 永远会进入根目录（``prune_dirs`` 与 dot 规则只判 listing 里看到的条目），
    而实测 grep 3.0 与 find 都会把命令行上那个起始目录一并排除掉——根目录名被
    ``--exclude-dir`` / ``-prune`` 命中时整棵子树安静消失，那是最恶劣的假阴性。
    只有根路径的**最后一段**参与判定（实测 ``--exclude-dir=tmp /tmp/ggrep/e`` 不受影响），
    所以深层目录名撞模式是平价的，不需要为此回落。
    """
    globs = dir_exclude_globs(spec)
    for root in spec.roots:
        base = posixpath.basename(root.rstrip('/')) or '/'
        if any(fnmatch.fnmatchcase(base, glob) for glob in globs):
            return True
    return False


def grep_cannot_select(spec: SearchSpec) -> bool:
    """grep 分支表达不出这条查询的文件选择：``--include`` 是**并集**，无法求交。

    ``name_pattern`` 与「仅数据文件」的 ``*.csv`` 要同时成立时，一条 ``--include`` 装不下
    两个 glob、两条又变成并集（实测 GNU grep 3.0），只有 find 的 ``-name A -iname B``
    是与。这类查询改走 find 分支，见 :func:`needs_find`。
    """
    return bool(spec.name_pattern) and bool(spec.data_files_only)


def needs_find(spec: SearchSpec) -> bool:
    """这次查询必须由 ``find ... | xargs grep`` 来完成（grep 没有对应原语）。

    两类原因：按 mtime/size 选文件（grep 没有），以及 :func:`grep_cannot_select`
    （glob 求交）。调用方两侧必须都读这里 —— ``shell_grep`` 据此选命令形状，
    ``select_engine`` 据此决定是否要求 ``has_find_xargs``。留在 shell_grep 里会让
    engine 与它互相 import（循环），各写一份则迟早漂移。
    """
    if grep_cannot_select(spec):
        return True
    return bool(spec.modified_after or spec.modified_before
                or spec.min_size is not None or spec.max_size is not None)
