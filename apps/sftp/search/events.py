"""SSE 事件的协议字面量：kind / 码表 / 文案 / 批合成器（spec §3.8）。

这里是「响应侧的契约」，与 :mod:`apps.sftp.search.contracts`（请求侧）对称：
 walker / scanners / shell_grep 都不引用它，只有 :mod:`apps.sftp.search.runner` 与
端点层用它拼事件。把码表单独放一处有两个理由：

1. 「上限一律显式告知」要求**每个码都有文案**，缺一个就是运行期 ``KeyError``；
   码表集中一处才谈得上被测试逐码钉住（``test_every_limit_code_has_a_message``）。
2. 前端要渲染降级/截断提示，但它**只抄事件里带来的 ``message``**（连同 ``incomplete``
   这个分类结果）—— 在 TS 里再维护一份码表，迟早与这张表分叉。
"""

from typing import Any, Callable, Dict, List, Optional

# —— 事件流节流常量（计划 Global Constraints：engine 侧只有这三个数字）——
EVENT_POLL_SEC = 0.2          # 生成器排空队列的轮询上限 = 取消延迟的上限（spec §3.9）
FLUSH_MAX_ITEMS = 200         # 批合成：攒够 200 项
FLUSH_MAX_AGE_SEC = 0.2       # 批合成：或攒够 200ms，先到者算数

# 扫描线程池的线程名前缀：测试靠它确认「取消之后线程池真的退干净了」。
SCAN_THREAD_PREFIX = 'sftp-scan'

# 给用户看的钳位文案，逐码定义：``contracts`` 的钳位码与这里必须一一对应，缺一个就是
# KeyError（测试 test_every_clamp_code_has_a_message 钉着这条）。
CLAMPED_TEXT = {
    'clamped_workers': '并行数已调整到服务器可接受范围',
    'clamped_timeout': '超时已钳位到 30–3600 秒',
    'clamped_max_entries': '遍历条目上限已钳位',
    'clamped_max_candidates': '候选数上限已钳位',
    'clamped_max_matches': '命中数上限已钳位',
    'clamped_matches_per_file': '每文件命中数上限已钳位到 20',
    'clamped_column_rows': '每文件取值数已钳位到 50',
    'clamped_max_scan_bytes': '单文件扫描预算已钳位到 1 GiB',
    'clamped_max_depth': '递归深度已钳位到 64 层',
}

# spec §3.8 的截断/降级码表。钳位码只告知、不进 done.limits_hit（用户的输入被完整执行
# 了，只是落在了一个可接受的档位上）；下面这些**都**进 done.limits_hit，但里面混着两类
# 语义完全不同的码：「结果集确实不完整」与「只是换了引擎/少了两条并发」。两者的分界
# 就在下面那两个 frozenset，别在本表里加注释列（注释会过期，代码不会）。
TRUNCATION_TEXT = {
    'truncated_depth': '已达递归深度上限，更深的目录没有遍历',
    'truncated_entries': '已达遍历条目上限，剩余目录没有列完',
    'truncated_candidates': '候选数已达上限，结果集不完整',
    'truncated_matches': '命中数已达上限，搜索提前停止',
    'scan_budget_exceeded': '有文件超出单文件扫描预算，只扫到了预算为止',
    'grep_fallback': '服务端 grep 运行失败，本次已改用客户端引擎',
    'grep_unavailable': '服务器不支持服务端 grep，本次使用客户端引擎',
    'workers_reduced': '服务器接受的并发连接少于请求数',
    'dir_unreadable': '有目录读不了，其内容未纳入结果',
    # spec §3.8 的码表里没有超时这一条，但静默到点返回正是「少结果不吭声」，
    # 所以补一个码；它同样进 done.limits_hit，且确实代表结果不完整（见 INCOMPLETE_CODES）。
    'timeout': '已达搜索超时，结果集不完整',
}

# —— 「这条告知代不代表结果集不完整」的分类，**只住在这里这一处** ——
# 为什么要后端算好再随事件送出去：前端要么抄一份码名表（第二份抄件就是下一个 ``only_data``
# 式的漂移源），要么每次改分类都来动 TS。现在前端只读 ``notice.incomplete`` 这一个布尔值，
# 黄条与中性提示的判据与 ``done.truncated`` 同源（runner 用同一个集合算）。
# 分类判据：**用户的输入被完整执行了吗**。换引擎、少两条并发 = 只是慢；
# 少扫了目录/文件/命中 = 结果集不完整（spec §3.13 那条「不可关闭的黄条」只属于后者）。
INCOMPLETE_CODES = frozenset({
    'truncated_depth', 'truncated_entries', 'truncated_candidates', 'truncated_matches',
    'scan_budget_exceeded', 'dir_unreadable', 'timeout',
})
# 只影响快慢、结果仍是完整的那几个（同样进 done.limits_hit —— 上限从不静默，但它是中性提示）。
SPEED_ONLY_CODES = frozenset({'grep_fallback', 'grep_unavailable', 'workers_reduced'})

NOTICE_TEXT = {**CLAMPED_TEXT, **TRUNCATION_TEXT}


def notice(code: str, message: Optional[str] = None) -> Dict[str, Any]:
    """一条 ``notice`` 事件。不带 message 时取码表文案（缺码就地 KeyError）。

    ``incomplete`` 由 :data:`INCOMPLETE_CODES` 算出，是前端「黄色提示条 vs 中性一行」的唯一
    判据（分类的落点只有那个集合，理由见那里）。钳位码不在 TRUNCATION_TEXT 里，天然为 False。
    """
    return {'kind': 'notice', 'code': code,
            'message': message if message is not None else NOTICE_TEXT[code],
            'incomplete': code in INCOMPLETE_CODES}


def brief(exc: BaseException) -> str:
    """异常摘要：进 notice 文案用，压成一行并截断，别把整叠 traceback 甩给用户。"""
    return (str(exc) or type(exc).__name__).strip().splitlines()[0][:200]


class Flusher:
    """事件批合成器：``FLUSH_MAX_ITEMS`` 项或 ``FLUSH_MAX_AGE_SEC`` 秒，先到者出帧。

    十万条目逐条发事件会把 SSE 的开销盖过扫描本身（spec §3.8），所以候选与命中都攒帧。
    """

    __slots__ = ('now', 'items', 'started_at')

    def __init__(self, now: Callable[[], float]):
        self.now = now
        self.items: List[Any] = []
        self.started_at = now()

    def add(self, item: Any) -> None:
        self.items.append(item)

    @property
    def full(self) -> bool:
        return len(self.items) >= FLUSH_MAX_ITEMS

    @property
    def aged(self) -> bool:
        return bool(self.items) and (self.now() - self.started_at) >= FLUSH_MAX_AGE_SEC

    def take(self) -> List[Any]:
        """取走攒着的一批（顺带把计时起点拨到此刻）。"""
        items, self.started_at = self.items, self.now()
        self.items = []
        return items
