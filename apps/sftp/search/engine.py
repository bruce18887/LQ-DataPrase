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

from apps.sftp.search.contracts import SearchSpec

# —— 三条「理由不显然」的回落文案（spec §3.3 逐条给了论证，这里只放给用户看的那一句）——
# 非 ASCII 是最容易被误当成性能取舍的一条，所以文案里必须写清后果是「漏结果」。
NON_ASCII_GREP_MSG = (
    '查询串含非 ASCII 字符：服务端 grep 只会按 UTF-8 字节匹配，'
    '会静默漏掉 GBK 编码的文件，故本次改用客户端引擎')
FUZZY_UNSUPPORTED_MSG = (
    '模糊匹配（子序列）在 grep 没有对应原语，只有客户端引擎支持')
PATH_MAPPING_MSG = (
    'SFTP 路径与 shell 路径不一致（常见于 chroot）：'
    '服务端 grep 会搜一个不存在的路径并安静返回 0 命中，故不使用加速')


@dataclass(frozen=True)
class ProbeResult:
    """服务端能力探测结果（由 ``shell_grep.probe`` 填，见 spec §3.6 的两级探测）。

    两级是**不等价**的：``grep`` 级（``has_grep`` + ``path_mapping_ok``）只保证能跑无时间
    过滤的查询；带时间过滤还额外要求 GNU ``find -newermt`` 与 ``xargs -0``
    （``has_find_xargs``）。缺任何一级都必须回落，且都是正确性而非速度问题——
    chroot 下 grep 一个错路径不是「慢」，是「假阴性」。
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

    **判断顺序是刻意的**：先判 spec 侧的六条（这些与服务器无关，无论探测结果如何都必须
    回落），再判 probe 侧。``probe.reason`` 只允许覆盖「probe 引起的那一条回落」——
    要是让它抢先返回，非 ASCII 查询就会拿到一句「服务器上没有 grep」，把真正的原因
    （会静默漏 GBK 文件）藏掉，用户下一次换台服务器就又被坑一遍。
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
    if not probe.usable:
        return 'client', probe.reason or '服务器不支持服务端 grep'
    if ((spec.modified_after or spec.modified_before)
            and not probe.has_find_xargs):
        return 'client', '时间过滤需要 GNU find/xargs，服务器不具备'
    return 'grep', '服务端 grep 可用'
