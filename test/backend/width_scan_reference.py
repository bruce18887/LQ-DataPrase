"""「整表回读算列宽」的**独立复刻** + 列宽下发侧的录放助手 —— 列宽平价判据的基准。

为什么不直接调生产的 ``apps.export.excel_theme.scan_column_widths`` 当基准：判据与实现共用同一段
代码时，两边一起改错（例如把夹在 8.0/42.0 的钳位常数改掉、或把东亚宽字符按 1 计）就永远不会红。
这里把旧通路的四条规则**逐条重写一遍**，常数按字面值写死 —— 它们同时被
``test_gage_sheet_shape.PIN_SUMMARY_WIDTHS`` 与产物 sha256 钉住，改错会先在那两处红。

旧通路（``scan_column_widths`` + ``apply_column_widths``，本模块复刻的对象）的四条规则：

1. ``get_cols(sheet)`` 把整张表物化回 Python（每列一个字符串列表）—— 这就是本次要消掉的开销；
2. 只认**读回来非空**的格：``not value`` 直接跳过（公式格的读回是空串 ⇒ 公式不撑宽任何列，
   实测 ``get_cols`` 对 ``set_cell_formula`` 写的格返回 ``''``）；
3. ``row < min_row`` 的格跳过；**横向合并区的锚点格**跳过（跨列标题不该把首列撑到整行宽），
   纵向合并（同列多行）不受影响；
4. ``longest`` 为 0 的列**完全不下发**（保持 Excel 默认宽），否则
   ``min(max(longest + 2.5, 8.0), 42.0)``；显示宽度里东亚宽/全角字符按 2 计。

文件名不以 ``test`` 开头 ⇒ ``DiscoverRunner`` 不收它（同 ``sheet_readback.py``、
``gage_shape_fixtures.py`` 的先例）。
"""
import contextlib
import unicodedata
from unittest import mock

import excelize

MIN_WIDTH = 8.0
MAX_WIDTH = 42.0
PADDING = 2.5


def display_width(text):
    """文本显示宽度：东亚 Wide/Full 字符按 2 计（与旧通路同口径，但这是重写的一份）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in str(text))


def horizontal_anchors(handle, sheet):
    """横向合并区的锚点坐标集合 ``{(列号, 行号)}``（旧通路也是这么算的）。"""
    anchors = set()
    for merged in handle.get_merge_cells(sheet):
        first_col, first_row = excelize.cell_name_to_coordinates(merged.get_start_axis())
        last_col, _ = excelize.cell_name_to_coordinates(merged.get_end_axis())
        if last_col > first_col:
            anchors.add((first_col, first_row))
    return anchors


def widths_by_full_scan(handle, sheet, min_row=1):
    """旧通路：整表回读 → ``{列号: 宽度}``（只含拿到正宽度的列）。"""
    anchors = horizontal_anchors(handle, sheet)
    widths = {}
    for col_idx, column in enumerate(handle.get_cols(sheet), start=1):
        longest = 0
        for offset, value in enumerate(column):
            row = offset + 1
            if row < min_row or not value or (col_idx, row) in anchors:
                continue
            longest = max(longest, display_width(value))
        if longest:
            widths[col_idx] = min(max(longest + PADDING, MIN_WIDTH), MAX_WIDTH)
    return widths


def as_letters(widths):
    """``{列号: 宽}`` → ``{列字母: 宽}``（与 sheet XML 的 ``<col>`` 口径对齐用）。"""
    return {excelize.column_number_to_name(idx): w for idx, w in widths.items()}


@contextlib.contextmanager
def capture_col_widths():
    """录下 ``set_col_width`` 的下发 ``[(sheet, 首列, 末列, 宽度), ...]``（按调用顺序）。

    判据要的是「下发了什么」，不只是「XML 最后是什么」：把若干列并成一次区间下发、
    或让列序变成字典插入序，产物字节可能照旧，但下发形状已经不是旧通路那一手。
    """

    calls = []
    origin = excelize.File.set_col_width

    def spy(self, sheet, first_col, last_col, width):
        calls.append((sheet, first_col, last_col, width))
        return origin(self, sheet, first_col, last_col, width)

    with mock.patch.object(excelize.File, 'set_col_width', spy):
        yield calls


def delivered(calls, sheet):
    """该 sheet 的列宽下发摊成 ``(顺序列号列表, {列号: 宽度})``。

    出现「首列 != 末列」的区间下发当场报错：旧通路是逐列下发的，任何区间接写法都不等价
    （``set_col_width`` 的区间会把两端之间所有列压成同一个宽度）。
    """
    order, widths = [], {}
    for name, first, last, width in calls:
        if name != sheet:
            continue
        if first != last:
            raise AssertionError(f'列宽下发出现区间写法：{first}..{last} = {width}')
        col_idx, _row = excelize.cell_name_to_coordinates(f'{first}1')
        order.append(col_idx)
        widths[col_idx] = width
    return order, widths
