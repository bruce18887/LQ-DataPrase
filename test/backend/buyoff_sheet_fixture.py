"""buyoff 工作表「下发形状」回归的**输入帧 / 游程预言**（判据本体在
``test_buyoff_sheet_shape.py``，本模块只被它消费）。XML 读回已抽到 ``sheet_readback.py``
（与 gage 段共用一份），「为什么以 sheet XML 为准 / 为什么不信 ``<dimension>`` / 为什么
样式取内容不取 id / 为什么列宽自己展开 ``<col min max>``」四条口径都写在那份模块文档里。

分成几个文件只因为 `.claude/CLAUDE.md` 那条 600 行硬约束（机械 owner 是
``scripts/line-limit.mjs`` + ``frontend/test/unit/lineLimit.spec.ts``，被跟踪 ``.py`` 一律算，
测试文件也在内）；四条判据（①产物字节 ②逐格读回+预言 ③列字母上界 ④游程下发）
仍然全部集中在 ``test_buyoff_sheet_shape.py`` 的类里，本模块不含任何断言。
文件名不以 ``test`` 开头 ⇒ Django ``test*.py`` 的发现规则不会把它当用例收集（同
``test/backend/excel_cf.py``、``test/backend/sheet_readback.py`` 的先例）。

本模块的共享状态一律**只读或每次新副本**（``SHAPES`` 深层 ``MappingProxyType``、
``_readback`` 返回深副本）：它们被多个用例复用，返回共享可变对象等于让一个用例改写
另一个用例的判据取数 —— 复审当场注入成功过一次，钉它的判据是
``test_buyoff_sheet_shape.BuyoffReadbackEquivalenceTests`` 的
``test_shared_fixture_state_cannot_pollute_another_case``。
"""
import os
import tempfile
from copy import deepcopy
from types import MappingProxyType
from unittest import mock

import excelize

from apps.buyoff import excelize_layout as layout
from apps.buyoff.services import NA
from test.backend.sheet_readback import readback

SHEET = 'Buyoff data'
#: 统计带的数据列起点 = ``build_buyoff_form`` 的「── Layout setup ──」那一段里
#: ``test_col_start`` 赋的值（A=分区、B=行名、C+=测试项）。指符号不指行号：行号会漂。
TEST_COL_START = 3
#: 统计带的行域。首行 = 「── Section writing loop ──」那一段里 ``row_idx`` 的初值；
#: 每个角色写 ``STAT_ROWS`` 那 14 行（循环体末尾 ``row_idx += 1``），角色之间再空一行
#: （「# Blank row between sections」那一句的 ``row_idx += 1``）⇒ 每角色 14 + 1。
FIRST_BAND_ROW = 6
BAND_ROW_COUNT = len(layout.STAT_ROWS)
ROWS_PER_ROLE = BAND_ROW_COUNT + 1

#: 统计带只用这两种样式，底色是它们的可分辨特征（COLOR_DATA_BG / FILL_NA）
FILL_OF = {'data': 'FFFFFF', 'na': 'F2F3F5'}
LABEL_OF_FILL = {v: k for k, v in FILL_OF.items()}

PARAMS = tuple(f'PAR{i:04d}' for i in range(1, 10))

# 每个参数的「失效形态」—— 刻意让同一行内 data/na 混排，逼出游程边界：
#   PAR0001 限值与 stats 全可用        → 所有行 data
#   PAR0002 metadata 里没有限值        → 两条限值行 na，其余 data
#   PAR0003 限值是空白串               → 同上（走 is_limit 分支里 `not raw.strip()` 那一条）
#   PAR0004 该角色没有该参数的 stats   → 12 行走三分支的 else（只有样式、不写值）＝ data
#   PAR0005 限值是 'Min'/'Max'         → 限值行写成文本 + data（与相邻 na 段同宽不同 id，M-a 的靶）
#   PAR0006 stats['std'] is None       → 只有 STD 行 na
#   PAR0007 除限值外全 'N/A'           → 12 行 na、限值行 data
#   PAR0008 限值是空白串               → 限值行 na（与 PAR0003 之间隔着 data ⇒ 限值行 5 段）
#   PAR0009 该角色没有该参数的 stats   → 同 PAR0004
MIXED_KINDS = {
    PARAMS[0]: 'full', PARAMS[1]: 'no_limit', PARAMS[2]: 'blank_limit',
    PARAMS[3]: 'missing_stats', PARAMS[4]: 'text_limit', PARAMS[5]: 'na_std',
    PARAMS[6]: 'na_values', PARAMS[7]: 'blank_limit', PARAMS[8]: 'missing_stats',
}
ALL_NA_KINDS = dict.fromkeys(PARAMS[:4], 'blank_limit')

#: 形状表**深层只读**。它和里面的 kinds 表都被多个用例复用，一旦有用例改到它，
#: 另一个用例的输入帧就被换掉了（判据会从「比出产品变了」退化成「比出上一个用例改了什么」）
#: ⇒ 用 ``MappingProxyType`` 包到第二层，改它当场 ``TypeError``，而不是让污染跨用例活着。
SHAPES = MappingProxyType({
    # 混排带：9 参数 × FT/QA1/QA2 ⇒ 限值行 5 段、普通行 3 段，是 ②④ 的靶形
    'mixed': MappingProxyType({
        'params': PARAMS, 'kinds': MappingProxyType(MIXED_KINDS),
        'roles': ('FT', 'QA1', 'QA2'),
    }),
    # 整带 na：验「游程化不只在全 data 时才成立」，也是单段 na 区间的靶形
    'all_na': MappingProxyType({
        'params': PARAMS[:4], 'kinds': MappingProxyType(ALL_NA_KINDS),
        'roles': ('FT', 'QA1'), 'na_all': True,
    }),
    # 与 mixed 同列数、多一个角色 ⇒ 行数变、列字母调用必须不变（③）
    'four_roles': MappingProxyType({
        'params': PARAMS, 'kinds': MappingProxyType(MIXED_KINDS),
        'roles': ('FT', 'QA1', 'QA2', 'QA3'),
    }),
})


# ────────────────────────── 输入帧（自足：不读真实样例、不依赖 tasks/ 脚本） ──────────────────────────


def _stats(mean, lower=0.5, upper=1.5):
    """形态同 ``test_buyoff_layout.py`` 的 ``_stats()``（``compute_buyoff_stats`` 的最小替身）。"""
    return {
        'lower_limit': lower, 'upper_limit': upper,
        'min': mean - 0.1, 'max': mean + 0.1, 'range': 0.2,
        'mean': mean, 'std': 0.05,
        'mean_minus_6std': mean - 0.3, 'mean_minus_3std': mean - 0.15,
        'mean_plus_3std': mean + 0.15, 'mean_plus_6std': mean + 0.3,
        'ca': 0.0, 'cp': 3.33, 'cpk': 3.0,
    }


def _limits(kind):
    """限值行 metadata 的三种失效形态；``None`` 表示字典里根本没有该参数。"""
    if kind == 'no_limit':
        return None, None
    if kind == 'blank_limit':
        return '   ', '   '
    if kind == 'text_limit':
        return 'Min', 'Max'
    return '0.5', '1.5'


def _metadata(cfg):
    mins, maxs, units = {}, {}, {}
    for param in cfg['params']:
        lo, hi = _limits(cfg['kinds'][param])
        if lo is not None:
            mins[param], maxs[param] = lo, hi
        units[param] = 'mV'
    return {'format': 'CTA8290D', 'units': units, 'mins': mins, 'maxs': maxs}


def _role_stats(cfg, role):
    """stats 形态照 ``compute_buyoff_stats`` 的返回口径：限值只有 float/None，其余可落 'N/A'
    （那条 docstring 明写「``lower_limit``/``upper_limit`` 可能是 ``None``、
    ``ca``/``cp``/``cpk`` 无法判定时为字符串 ``'N/A'``」。整带 na 的形状因此**不能**
    给 lower/upper 塞字符串 —— 那是 ``_qa_range`` 接不住的假输入形态。
    """
    mean_base = 1.0 + 0.03 * cfg['roles'].index(role)
    out = {}
    for idx, param in enumerate(cfg['params']):
        kind = cfg['kinds'][param]
        if kind == 'missing_stats' and not cfg.get('na_all'):
            continue                     # 视图会跳过 stats 为空的参数（缺陷 #5 那条通路）
        stats = _stats(mean_base + 0.01 * idx)
        if cfg.get('na_all'):
            stats = {k: (None if k in ('lower_limit', 'upper_limit') else NA)
                     for k in stats}
        elif kind == 'na_std':
            stats['std'] = None
        elif kind == 'na_values':
            # 限值仍可用（能力指数那两格走 metadata 分支），其余统计量全部无定义
            stats = {k: (v if k in ('lower_limit', 'upper_limit') else NA)
                     for k, v in stats.items()}
        out[param] = stats
    return out


def _payload(shape):
    """``(role_mapping, common_items, all_stats, datasets, ordered_roles)``。"""
    cfg = SHAPES[shape]
    role_mapping, datasets, all_stats = {}, {}, {}
    for idx, role in enumerate(cfg['roles'], start=1):
        fname = f'{role}.csv'
        role_mapping[role] = fname
        datasets[fname] = {'df': None, 'file_id': idx,
                           'numeric_cols': list(cfg['params']),
                           'metadata': _metadata(cfg)}
        all_stats[role] = _role_stats(cfg, role)
    return (dict(role_mapping), list(cfg['params']), all_stats, datasets,
            list(cfg['roles']))


def _build(shape):
    """真实构建，返回**打开着**的 excelize 句柄（用例自己 close）。"""
    f = excelize.new_file()
    layout.build_buyoff_form(f, *_payload(shape))
    return f


def _save_bytes(f):
    """句柄 → 工作簿字节。**不用 ``tempfile.mktemp()``**：那条只返回一个还没被占住的名字，
    同机并发跑到同一个名字就会互相覆写（竞态）。改用 ``NamedTemporaryFile(delete=False)``
    当场把名字占住，落盘后在 ``finally`` 里显式清理。
    """
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        f.save_as(tmp_path)
        with open(tmp_path, 'rb') as fh:
            return fh.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _safe_close(f):
    try:
        f.close()
    except Exception:  # noqa: BLE001 — 已 close 过就无所谓
        pass


# ────────────────────────── 预言：统计带每格该是哪种样式 ──────────────────────────


def _band_rows(shape):
    """``[(行号, 角色名, (stat_name, stat_key, is_limit))]`` —— 统计带的行域。"""
    out = []
    for ri, role in enumerate(SHAPES[shape]['roles']):
        base = FIRST_BAND_ROW + ri * ROWS_PER_ROLE
        out.extend((base + si, role, layout.STAT_ROWS[si])
                   for si in range(BAND_ROW_COUNT))
    return out


def _expected_cells(shape):
    """``{行号: {列号: 'na'|'data'}}`` —— 拿**产品实际消费的那份 payload** 独立判每一格。

    只复刻「哪一个分支被走到」这件事 —— 统计带内层参数循环里的那条三分支：
    ``if is_limit``（限值的两种缺法都归 na） / ``elif param in all_stats.get(...)``
    （值 ``None`` 或 ``NA`` 归 na） / 收尾的 ``else``（该角色没有这个参数的 stats ⇒
    只有样式不写值，归 data）。不复刻任何下发写法，也不指产品行号（行号会漂）。
    """
    role_mapping, items, all_stats, datasets, _roles = _payload(shape)
    cells = {}
    for row, role, (stat_name, stat_key, is_limit) in _band_rows(shape):
        meta = datasets[role_mapping[role]].get('metadata') or {}
        table = 'mins' if stat_name == 'Lower Limit' else 'maxs'
        per_row = {}
        for off, param in enumerate(items):
            if is_limit:
                raw = meta.get(table, {}).get(param)
                label = 'na' if (raw is None
                                 or (isinstance(raw, str) and not raw.strip())) else 'data'
            elif param in all_stats.get(role, {}):
                val = all_stats[role][param].get(stat_key)
                label = 'na' if val is None or val == NA else 'data'
            else:
                label = 'data'
            per_row[TEST_COL_START + off] = label
        cells[row] = per_row
    return cells


def _last_col(shape):
    return TEST_COL_START + len(SHAPES[shape]['params']) - 1


# ────────────────────────── 读回（实现在 sheet_readback.py，这里只按形状缓存） ──────────────────────────

_RB_CACHE = {}


def _readback(shape):
    """同一形状只读回一次（digest 判据只由输入决定；重建路径由 ① 自己钉住等价）。

    **返回的是深副本，不是缓存里那个对象**：这份缓存被多个用例复用，返回共享可变对象
    等于把「上一个用例改了什么」当成判据取数（复审当场注入过：改掉某一行的游程首段，
    后面那条覆盖判据就比的是假数据）。钉它的是
    ``test_shared_fixture_state_cannot_pollute_another_case``。
    """
    if shape not in _RB_CACHE:
        f = _build(shape)
        try:
            _RB_CACHE[shape] = readback(_save_bytes(f))
        finally:
            _safe_close(f)
    return deepcopy(_RB_CACHE[shape])


# ────────────────────────── 下发记录（spy）：④ 的取数来源 ──────────────────────────

def _record(shape):
    """跑一次完整生成，录下样式/值下发与它们的先后次序，返回 ``(记录, 句柄)``。"""
    events, cell_calls, col_calls = [], [], []
    origin_style = excelize.File.set_cell_style
    origin_value = excelize.File.set_cell_value
    origin_col = excelize.File.set_col_style

    def spy_style(self, sheet, top_left, bottom_right, style_id):
        col_from, row_from = excelize.cell_name_to_coordinates(top_left)
        col_to, row_to = excelize.cell_name_to_coordinates(bottom_right)
        events.append(('style', sheet, row_from, row_to, col_from, col_to, style_id))
        cell_calls.append((sheet, top_left, bottom_right, style_id))
        return origin_style(self, sheet, top_left, bottom_right, style_id)

    def spy_value(self, sheet, cell, value):
        col_idx, row = excelize.cell_name_to_coordinates(cell)
        events.append(('value', sheet, row, row, col_idx, col_idx, cell, value))
        return origin_value(self, sheet, cell, value)

    def spy_col(self, sheet, columns, style_id):
        col_calls.append((sheet, columns, style_id))
        return origin_col(self, sheet, columns, style_id)

    f = excelize.new_file()
    with mock.patch.object(excelize.File, 'set_cell_style', spy_style), \
            mock.patch.object(excelize.File, 'set_cell_value', spy_value), \
            mock.patch.object(excelize.File, 'set_col_style', spy_col):
        layout.build_buyoff_form(f, *_payload(shape))
    return {'style': cell_calls, 'col': col_calls, 'events': events}, f


def _band_spans(rec, sheet_row, lo, hi):
    """该行在统计带列域 ``[lo, hi]`` 内的下发，摊成 ``[[起列, 末列, style_id], ...]``。"""
    out = []
    for _sheet, top, bottom, style_id in rec['style']:
        if _sheet != SHEET:
            continue
        col_from, row_from = excelize.cell_name_to_coordinates(top)
        col_to, row_to = excelize.cell_name_to_coordinates(bottom)
        if not (row_from <= sheet_row <= row_to):
            continue
        left, right = max(col_from, lo), min(col_to, hi)
        if left <= right:
            out.append([left, right, style_id])
    return out


def _label_by_id(f, style_ids):
    """样式 id → 'data'/'na'（按底色），把下发记录与预言对齐；未知底色直接判红。"""
    out = {}
    for style_id in set(style_ids):
        style = f.get_style(style_id)
        fill = getattr(style, 'fill', None)
        colors = getattr(fill, 'color', None) if fill is not None else None
        color = str(colors[0]).upper() if colors else ''
        label = LABEL_OF_FILL.get(color)
        if label is None:
            raise AssertionError(f'统计带出现了第三种样式 id={style_id} 底色={color!r}')
        out[style_id] = label
    return out
