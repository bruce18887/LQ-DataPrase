"""引擎选择谓词（spec §3.3）。本文件后续由「engine 阶段机」任务续写，目前只有谓词。

搜索引擎有两档：客户端字节扫描（永远正确）与服务端 ``grep`` 加速。本模块的唯一职责是
回答「这次能不能用 grep」，而它存在的全部理由是：

    **同一个查询在有无 grep 的两台服务器上必须给出同一个结果集。**

因此回落条件里没有一条是性能取舍——每一条都是「grep 档在这一查询上给不出与 client 档
相同的结果集」。宁可慢，不可静默少结果。任何一条不满足即回落 client，且**必须带一句
可显示的原因**（engine 转成 ``notice`` 事件，前端展示），不能让用户猜这次是哪档跑的。
"""

from dataclasses import dataclass
from typing import Tuple

from apps.sftp.search import filters
from apps.sftp.search.contracts import SearchSpec

# —— 几条「理由不显然」的回落文案（spec §3.3 逐条给了论证，这里只放给用户看的那一句）——
# 非 ASCII 是最容易被误当成性能取舍的一条，所以文案里必须写清后果是「漏结果」。
NON_ASCII_GREP_MSG = (
    '查询串含非 ASCII 字符：服务端 grep 只会按 UTF-8 字节匹配，'
    '会静默漏掉 GBK 编码的文件，故本次改用客户端引擎')
FUZZY_UNSUPPORTED_MSG = (
    '模糊匹配（子序列）在 grep 没有对应原语，只有客户端引擎支持')
PATH_MAPPING_MSG = (
    'SFTP 路径与 shell 路径不一致（常见于 chroot）：'
    '服务端 grep 会搜一个不存在的路径并安静返回 0 命中，故不使用加速')
# —— 下面几条同样不是性能取舍，而是「grep 拼不出同一个结果集」（Task 8 交付时补齐的四条）——
DEPTH_LIMIT_MSG = (
    '递归深度限制（depth 不是「不限」）在 grep 没有对应原语：GNU grep 没有 --max-depth，'
    '只有客户端引擎能既限深度又给出同一结果集')
ROOT_EXCLUSION_MSG = (
    '根目录自身的名字撞上了目录排除条件（剪枝目录名或以 . 开头）：grep/find 会连根目录'
    '一起跳过，而客户端引擎总会进入根目录，两者结果集不同，故改用客户端引擎')
GREP_SELECT_INTERSECTION_MSG = (
    '文件名模式与「仅数据文件」两个条件要同时成立：grep 的 --include 之间是并集、'
    '求不出交集，这类查询得走 find 管道')
NEEDS_FIND_XARGS_MSG = (
    '按大小/时间筛文件、或文件名模式需与「仅数据文件」求交集，这些只有 GNU find/xargs '
    '能表达，服务器不具备，故改用客户端引擎')


@dataclass(frozen=True)
class ProbeResult:
    """服务端能力探测结果（由 ``shell_grep.probe`` 填，见 spec §3.6 的两级探测）。

    两级是**不等价**的：``grep`` 级（``has_grep`` + ``path_mapping_ok``）只保证能跑无时间
    过滤的查询；带时间过滤还额外要求 GNU ``find -newermt`` 与 ``xargs -0``
    （``has_find_xargs``）。缺任何一级都必须回落，且都是正确性而非速度问题——
    chroot 下 grep 一个错路径不是「慢」，是「假阴性」。

    ``has_grep`` 自 Task 8 起含义变严：它不仅要求 ``grep`` 这个二进制在，还要求它认
    ``--include``/``--exclude``/``--exclude-dir`` —— 那三条是文件选择平价的唯一表达手段，
    探测过了而选项不存在会直接让命令以退出码 2 结束（白跑一趟整棵树）。
    """

    has_grep: bool
    has_find_xargs: bool
    path_mapping_ok: bool
    reason: str = ''

    @property
    def usable(self) -> bool:
        """grep 档是否可用（不含时间过滤这一级，那一级的判据在 :func:`select_engine`）。"""
        return bool(self.has_grep and self.path_mapping_ok)


def select_engine(spec: SearchSpec, probe: ProbeResult) -> Tuple[str, str]:
    """返回 ``("grep"|"client", 原因)``。原因恒非空，前端直接显示。

    **判断顺序是刻意的**：先判 spec 侧的那几条（这些与服务器无关，无论探测结果如何都必须
    回落），再判 probe 侧。``probe.reason`` 只允许覆盖「probe 引起的那一条回落」——
    要是让它抢先返回，非 ASCII 查询就会拿到一句「服务器上没有 grep」，把真正的原因
    （会静默漏 GBK 文件）藏掉，用户下一次换台服务器就又被坑一遍。

    spec 侧的这几条彼此同构：**grep 档在这一查询上给不出与 walker 相同的结果集**。
    前四条来自 spec §3.3（模式 / 子序列匹配 / 非 ASCII / 每目录一个），深度与根目录名
    这两条是 Task 8 实施时补的（GNU grep 没有 ``--max-depth``；``--exclude-dir`` 与
    ``-prune`` 会命中命令行上那个根目录本身，而 walker 总会进入根目录）。其余三条
    （``prune_dirs``、``data_files_only``、dot 条目）能逐字翻译成 grep 选项，所以
    **不在此处回落**，翻译见 :mod:`apps.sftp.search.filters` 与 ``shell_grep.build_command``。
    """
    if spec.mode != 'content':
        return 'client', f'命中模式 {spec.mode} 需要客户端引擎'
    if not spec.allow_server_grep:
        return 'client', '用户已关闭服务端加速'
    if spec.matching == 'fuzzy':
        return 'client', FUZZY_UNSUPPORTED_MSG
    if not spec.term.isascii():
        return 'client', NON_ASCII_GREP_MSG
    if spec.one_per_folder:
        return 'client', '每目录只取一个文件 grep 无对应原语'
    if spec.stop_after_listing:
        return 'client', '仅列出候选不需要执行 grep'
    if spec.depth != 'all':
        return 'client', DEPTH_LIMIT_MSG
    if filters.root_collides_with_dir_excludes(spec):
        return 'client', ROOT_EXCLUSION_MSG
    if not probe.usable:
        return 'client', probe.reason or '服务器不支持服务端 grep'
    if filters.needs_find(spec) and not probe.has_find_xargs:
        # find 管道是这条查询唯一的平价表达（时间/大小过滤，或两个 glob 求交），
        # 缺 GNU find/xargs 就只能回落。判据与 shell_grep 选分支用的是同一个函数。
        return 'client', NEEDS_FIND_XARGS_MSG
    return 'grep', '服务端 grep 可用'
