"""Excel 工作表命名的共享规则（批量参数分布图 / 权重导出共用）。

Excel 的硬约束：

* 表名 ≤ 31 字符；
* 不能含 ``[ ] : * ? / \\``，也不能以 ``'`` 开头/结尾（这里连同 ``'`` 一起
  换掉，内部超链接引用就不用转义）；
* 表名大小写不敏感，``Abc`` 与 ``abc`` 视为同名；
* ``总览`` 是本项目总览页保留名，``History`` 是 Excel 保留名，都不分配给明细表。

单份实现：两个导出此前各自维护一份（批量导出那份还漏了非法字符清洗），
2026-11-15 实测导致参数名含 ``[V]`` 时总览超链接断链、长名撞名时互指。
"""

import re
from typing import Sequence

ILLEGAL_SHEET_CHARS = re.compile(r"[\[\]:*?/\\']")
RESERVED_SHEET_NAMES = ('总览', 'history')
SHEET_NAME_MAX_LEN = 31


def clean_sheet_name(name: str, fallback: str = '测试项') -> str:
    """测试项名 → 合法 sheet 名：非法字符换 `_`、31 字符上限；空名给 fallback。"""
    cleaned = ILLEGAL_SHEET_CHARS.sub('_', (name or '').strip())[:SHEET_NAME_MAX_LEN]
    return cleaned or fallback


def unique_sheet_names(names: Sequence[str], fallback: str = '测试项') -> list[str]:
    """按输入顺序分配唯一 sheet 名：重名/截断冲突加 `_2`、`_3`（保留名不占用）。"""
    used = {name.lower() for name in RESERVED_SHEET_NAMES}
    out: list[str] = []
    for name in names:
        base = clean_sheet_name(name, fallback)
        candidate = base
        n = 2
        while candidate.lower() in used:
            suffix = f'_{n}'
            candidate = base[:SHEET_NAME_MAX_LEN - len(suffix)] + suffix
            n += 1
        used.add(candidate.lower())
        out.append(candidate)
    return out
