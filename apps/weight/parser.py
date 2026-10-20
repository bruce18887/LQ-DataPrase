# apps/weight/parser.py
"""权重 CSV 解析：`double 名称[n] = {v,…};` → 分组 / 序号命名 / 逐点均值。

零 Django、零 Excel 依赖 —— parse 端点与 xlsx 构建共用这唯一一份（spec §2 第 4 条）。
错误只给机器码 + 结构化字段，中文文案在前端 ERROR_CODE_MAP（spec §3.3）。

命名与均值的口径（spec §3.2）：名称区分大小写；只出现 1 次的名称保持原名，出现 N 次的
**全部**成员加 `_1.._N`；组序 = 首次出现序，组内按出现序；`source_index` 是**全局**第几条
声明（从 1 起，均值行固定 0），所以组内成员在交错文件里不必连号；`first_row` = 组内第一条
的 `source_index`，它不是文件行号。均值在解析期算好（前端只切可见性），长度 = 组内最大声明
长度，某个 code 无成员有值时留 None；`decimals=MEAN_DECIMALS` 只是显示口径（spec §7.4），
数值本身不四舍五入。

同名撞名（已实测、刻意不去重）：后缀可以与文件里本来就在的字面量重名 —— `A` 出现两次得
`A_1`/`A_2`，若文件里另有一条只出现一次的 `A_1`，输出就是 `['A_1', 'A_2', 'A_1']`；字面量
`A_Avg` 同理与组 `A` 的均值名重复。本模块**既不去重也不报错**（要报错就得新增错误码，而每个
新码都必须同时进前端 `ERROR_CODE_MAP`，那是改 spec，不在本模块口径内）。**消费方不得拿
`series.name` 当键**：用 `(group.index, series 下标)` 或 `source_index`（前端 Task 6 的
`v-for :key`、Task 8 表格 `row-key` 都按此口径；ECharts 的 `series.name` 只用于显示）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

TEXT_LIMIT = 2_000_000
DECLARATION_LIMIT = 2000
LENGTH_LIMIT = 1024
MEAN_DECIMALS = 5

DECL_RE = re.compile(
    r'double\s+(?P<name>[A-Za-z_]\w*)\s*\[\s*(?P<length>\d+)\s*\]\s*=\s*\{(?P<body>[^}]*)\}\s*;'
)
NUMBER_RE = re.compile(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?')


class WeightError(Exception):
    """解析失败：`.code` 是稳定机器码（前端 ERROR_CODE_MAP 的键），`.fields` 是结构化上下文。"""

    def __init__(self, code: str, **fields):
        super().__init__(code)
        self.code = code
        self.fields = fields


@dataclass(frozen=True)
class WeightSeries:
    name: str
    source_index: int
    declared_length: int
    decimals: int
    values: tuple[float | None, ...]


@dataclass(frozen=True)
class WeightGroup:
    index: int
    name: str
    first_row: int
    series: tuple[WeightSeries, ...]
    mean: WeightSeries


@dataclass(frozen=True)
class WeightDoc:
    filename_hint: str
    groups: tuple[WeightGroup, ...]
    code_max: int
    series_count: int
    group_count: int


def _decimals_of(token: str) -> int:
    mantissa = token.lower().split('e')[0]
    return len(mantissa.split('.')[1]) if '.' in mantissa else 0


def _parse_values(body: str, *, line: int) -> tuple[list[float], int]:
    values: list[float] = []
    decimals = 0
    for raw in body.split(','):
        token = raw.strip()
        if not token:
            continue                      # 容忍尾随逗号
        # 拦 `1_000` 这类下划线分隔写法的是 NUMBER_RE 的形状（它没有 `_` 分支，`fullmatch` 必失败），
        # 不要再加 `'_' in token` 子句：变异反证证明它永不生效（存活变异），留着只会误导下一个读的人
        if not NUMBER_RE.fullmatch(token):
            raise WeightError('weight_bad_number', line=line, token=token)
        v = float(token)
        if not math.isfinite(v):          # float() 认 nan/inf，必须显式拒（lessons R4①）
            raise WeightError('weight_bad_number', line=line, token=token)
        values.append(v)
        decimals = max(decimals, _decimals_of(token))
    return values, decimals


def compute_mean(members: Sequence[WeightSeries], name: str) -> WeightSeries:
    """逐点算术平均：第 i 点只对「长度够且该点有值」的成员求平均，全空则 None。"""
    width = max((len(m.values) for m in members), default=0)
    means: list[float | None] = []
    for i in range(width):
        pool = [m.values[i] for m in members if i < len(m.values) and m.values[i] is not None]
        means.append(sum(pool) / len(pool) if pool else None)
    return WeightSeries(name=name, source_index=0, declared_length=width,
                        decimals=MEAN_DECIMALS, values=tuple(means))


def parse_weight_text(text: str, *, filename_hint: str = '') -> WeightDoc:
    """整文本扫描（声明可跨行，行号取声明起始行），非声明行与空行忽略。"""
    if len(text) > TEXT_LIMIT:
        raise WeightError('weight_too_large', which='text', limit=TEXT_LIMIT, actual=len(text))

    matches = list(DECL_RE.finditer(text))
    if not matches:
        raise WeightError('no_declaration')
    if len(matches) > DECLARATION_LIMIT:
        raise WeightError('weight_too_large', which='declarations', limit=DECLARATION_LIMIT,
                          actual=len(matches))

    order: list[str] = []
    buckets: dict[str, list[WeightSeries]] = {}
    for n, m in enumerate(matches, start=1):
        line = text.count('\n', 0, m.start()) + 1
        declared = int(m.group('length'))
        if declared > LENGTH_LIMIT:
            raise WeightError('weight_too_large', which='length', limit=LENGTH_LIMIT,
                              actual=declared, line=line)
        values, decimals = _parse_values(m.group('body'), line=line)
        if len(values) != declared:
            raise WeightError('weight_length_mismatch', line=line, name=m.group('name'),
                              declared=declared, actual=len(values))
        name = m.group('name')
        if name not in buckets:
            buckets[name] = []
            order.append(name)
        buckets[name].append(WeightSeries(name, n, declared, decimals, tuple(values)))

    groups = []
    for gi, name in enumerate(order):
        members = buckets[name]
        if len(members) > 1:
            members = [WeightSeries(f'{name}_{i + 1}', s.source_index, s.declared_length,
                                    s.decimals, s.values) for i, s in enumerate(members)]
        groups.append(WeightGroup(index=gi, name=name, first_row=members[0].source_index,
                                  series=tuple(members),
                                  mean=compute_mean(members, f'{name}_Avg')))

    # `double A[0] = {};` 是合法的（声明 0 == 实际 0，LENGTH_LIMIT 只卡上界），
    # 但轴上界不能是 -1 —— 钳到 0，Task 3/4/6 拿到的是非负上界，不加新错误码
    code_max = max(s.declared_length for g in groups for s in g.series)
    return WeightDoc(filename_hint=filename_hint, groups=tuple(groups),
                     code_max=max(code_max - 1, 0),
                     series_count=sum(len(g.series) for g in groups), group_count=len(groups))


def _series_to_dict(s: WeightSeries) -> dict:
    return {'name': s.name, 'source_index': s.source_index, 'declared_length': s.declared_length,
            'decimals': s.decimals, 'values': list(s.values)}


def doc_to_payload(doc: WeightDoc) -> dict:
    """JSON 可序列化的载荷：tuple → list，缺席点 → None（解析器不留 NaN 通路）。"""
    return {
        'code_max': doc.code_max,
        'group_count': doc.group_count,
        'series_count': doc.series_count,
        'groups': [{'index': g.index, 'name': g.name, 'first_row': g.first_row,
                    'series': [_series_to_dict(s) for s in g.series],
                    'mean': _series_to_dict(g.mean)} for g in doc.groups],
    }
