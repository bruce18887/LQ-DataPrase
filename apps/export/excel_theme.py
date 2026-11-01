"""统一的 Excel 输出配色与样式工厂。

骨架：浅灰标题带（`F2F2F2`）+ 深蓝表头带（`1F4E79`）+ 中性灰分层。
判定：用**底色 + 配套字色**表达 —— pass 浅绿、warn 浅黄、fail 深红配白字；
表内判定走 **Excel 条件格式**（`add_*_rules`），用户改值后颜色自动跟随。
「无法判定」保留静态极浅灰底，与三档判定色区分。

buyoff 与 Gage 共用本模块。注意与 `apps/export/excelize_helpers.py` 区分：后者被
batch_report / sigma-limit / 数据导出消费，配色保持原样，不要混用。
"""
import math
import re
import unicodedata

import excelize

from .fonts import EXCEL_FONT_FAMILY as _FONT

#: ``repr`` 的负指数写法（``'1.2345e-09'``）；正指数不匹配 —— Go 那一头也改成了科学计数法。
_EXPONENT_REPR = re.compile(r'\A(-?\d+)(?:\.(\d+))?e(-\d+)\Z')

# ── 骨架色 ──
COLOR_TITLE_BG = "F2F2F2"      # 浅灰：标题带
COLOR_HEADER_BG = "1F4E79"     # 深蓝：表头带
COLOR_HEADER_FONT = "FFFFFF"
COLOR_LABEL_BG = "F7F8F9"      # 行名/参数名列
COLOR_DATA_BG = "FFFFFF"
COLOR_FONT = "1F2A37"          # 正文近黑
COLOR_FONT_MUTED = "5B6671"

# ── 边框 ──
COLOR_BORDER = "D9D9D9"        # 细网格
COLOR_BORDER_STRONG = "B0B7BD"  # 表格外框 / 分区左缘

# ── 判定底色 + 配套字色（对比度均 ≥ 4.5:1，见 test_excel_theme）──
FILL_PASS = "D5F5E3"
FONT_ON_PASS = "145A32"
FILL_WARN = "FFE0B2"          # 橙色：Bad2 / 5–10% 边际档
FONT_ON_WARN = "6B5607"       # 比黄底时代更深一档，压橙色仍有 5.6:1
FILL_FAIL = "C62828"
FONT_ON_FAIL = "FFFFFF"
FILL_NA = "F2F3F5"
FONT_NA = "5B6470"

# 浅底上（不铺底色）的语义字色：Gage 表头区的计数/警示这类"只是一行字"的地方用。
FONT_PASS = "1E7A34"
FONT_WARN = "8A5A00"
FONT_FAIL = "B3261E"

_VERDICT = {
    'pass': (FILL_PASS, FONT_ON_PASS),
    'warn': (FILL_WARN, FONT_ON_WARN),
    'fail': (FILL_FAIL, FONT_ON_FAIL),
    'na': (FILL_NA, FONT_NA),
}


def _border(left=COLOR_BORDER, top=COLOR_BORDER,
            bottom=COLOR_BORDER, right=COLOR_BORDER):
    return [
        excelize.Border(type="left", color=left, style=1),
        excelize.Border(type="top", color=top, style=1),
        excelize.Border(type="bottom", color=bottom, style=1),
        excelize.Border(type="right", color=right, style=1),
    ]


def thin_border(color=COLOR_BORDER):
    """四边同色细线（默认浅灰网格）。"""
    return _border(color, color, color, color)


def set_formula(f, sheet, cell, expr):
    """写入一个公式（Buyoff/Gage 的派生值）。

    excelize 的 ``set_cell_formula`` 把字符串**原样**塞进 ``<f>``。若带前导 ``=``
    会得到非法的 ``<f>=A1+A2</f>``（Excel 打开可能提示修复），所以这里统一去掉前导
    ``=`` —— 调用方可以照常写 ``"=A1+A2"``。
    """
    f.set_cell_formula(sheet, cell, expr[1:] if expr.startswith('=') else expr)


def enable_full_recalc(f):
    """让 Excel 打开时就重算全书。

    excelize 写公式时不落缓存值（``get_cell_value`` 读回空串），不设这个标志的话
    文件在重算前一片空白。``full_calc_on_load`` 会写进 workbook.xml 的 ``calcPr``。
    """
    f.set_calc_props(excelize.CalcPropsOptions(full_calc_on_load=True))


def make_title_style(f, size=14, align="left"):
    """标题带：浅灰底 + 深色粗字。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=float(size), color=COLOR_FONT, family=_FONT),
        fill=excelize.Fill(type="pattern", color=[COLOR_TITLE_BG], pattern=1),
        alignment=excelize.Alignment(horizontal=align, vertical="center"),
    ))


def make_header_style(f, size=12):
    """表头带：深蓝底 + 白色粗字 + 细线。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=float(size), color=COLOR_HEADER_FONT, family=_FONT),
        fill=excelize.Fill(type="pattern", color=[COLOR_HEADER_BG], pattern=1),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def make_label_style(f, size=10, bold=True, align="left"):
    """行名格：浅灰底 + 深色字。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=bold, size=float(size), color=COLOR_FONT, family=_FONT),
        fill=excelize.Fill(type="pattern", color=[COLOR_LABEL_BG], pattern=1),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal=align, vertical="center"),
    ))


def make_data_style(f, size=10, num_fmt=None, align="center"):
    """数据格：白底 + 深色字 + 细线。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(size=float(size), color=COLOR_FONT, family=_FONT),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal=align, vertical="center"),
        custom_num_fmt=num_fmt,
    ))


def make_unit_style(f):
    """单位行：白底 + 斜体灰字。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(size=9, color=COLOR_FONT_MUTED, italic=True, family=_FONT),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def make_section_style(f, size=11):
    """分区标签（A 列合并区）：横向粗体深色，不铺底。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=float(size), color=COLOR_FONT, family=_FONT),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def make_verdict_style(f, kind, size=10, num_fmt=None):
    """判定格的静态样式（底色 + 配套字色）。``kind`` ∈ {pass, warn, fail, na}。

    表内判定一般不用这个，而是靠下面的条件格式；这里是给「无法判定」这类
    静态态、以及条件格式未命中时的基色用的。
    """
    fill_color, font_color = _VERDICT[kind]
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=float(size), color=font_color, family=_FONT),
        fill=excelize.Fill(type="pattern", color=[fill_color], pattern=1),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
        custom_num_fmt=num_fmt,
    ))


def _make_dxf_verdict_style(f, kind, size=10):
    """条件格式专用判定样式（与 make_verdict_style 同色，但走 new_conditional_style）。"""
    fill_color, font_color = _VERDICT[kind]
    return f.new_conditional_style(excelize.Style(
        font=excelize.Font(bold=True, size=float(size), color=font_color, family=_FONT),
        fill=excelize.Fill(type="pattern", color=[fill_color], pattern=1),
    ))


def add_percent_verdict_rules(f, sheet, range_ref, warn, fail, size=10):
    """按 |百分比| 给区域加条件格式：>fail 红、>warn 黄，其余靠基色（浅绿）。

    ``warn`` / ``fail`` 以**百分数**给出（如 5 / 10），单元格里存的是小数
    （0.05 配 `0.000000%` 格式），所以这里内部除以 100。

    注意不能用 ``criteria='between'``：excelize 会写出 ``operator="between"``
    但**丢掉两个边界 formula**，规则是坏的。改用严格比较 + ``stop_if_true``
    逐条短路，边界与原来的 Python 判断（``>fail`` 红 / ``>warn`` 黄）完全一致。
    """
    warn_v = warn / 100
    fail_v = fail / 100
    fail_fmt = _make_dxf_verdict_style(f, 'fail', size)
    warn_fmt = _make_dxf_verdict_style(f, 'warn', size)
    f.set_conditional_format(sheet, range_ref, [
        excelize.ConditionalFormatOptions(
            type='cell', criteria='greater than', value=str(fail_v),
            format=fail_fmt, stop_if_true=True),
        excelize.ConditionalFormatOptions(
            type='cell', criteria='greater than', value=str(warn_v),
            format=warn_fmt, stop_if_true=True),
        excelize.ConditionalFormatOptions(
            type='cell', criteria='less than', value=str(-fail_v),
            format=fail_fmt, stop_if_true=True),
        excelize.ConditionalFormatOptions(
            type='cell', criteria='less than', value=str(-warn_v),
            format=warn_fmt, stop_if_true=True),
    ])


def add_fail_if_nonpositive_rule(f, sheet, range_ref, size=10):
    """差值行：``<= 0`` 时判红（沿用既有业务口径）。"""
    f.set_conditional_format(sheet, range_ref, [
        excelize.ConditionalFormatOptions(
            type='cell', criteria='less than or equal to', value='0',
            format=_make_dxf_verdict_style(f, 'fail', size), stop_if_true=True),
    ])


def add_threshold_verdict_rules(f, sheet, range_ref, tiers, size=10):
    """按数值阈值分档上色。``tiers`` 为 ``[(阈值, kind), ...]``，须按阈值**从大到小**排列。

    只有 ``>= 阈值`` 一种比较（excelize 的 ``between`` 会丢掉边界 formula，不能用）；
    配合 ``stop_if_true`` 逐条短路，先命中高档。

    空白单元格按 0 处理，不会命中正的阈值 —— 前提是单元格真的是空的：
    写入 ``''`` 会变成文本单元格，而 Excel 里**文本恒大于任何数值**，
    于是 ``>= 阈值`` 会对空白格成立、把整列都标红。
    """
    rules = [
        excelize.ConditionalFormatOptions(
            type='cell', criteria='greater than or equal to', value=str(value),
            format=_make_dxf_verdict_style(f, kind, size), stop_if_true=True)
        for value, kind in tiers
    ]
    f.set_conditional_format(sheet, range_ref, rules)


def _display_width(text):
    """文本显示宽度：东亚宽字符按 2 计。

    ASCII 快路不是风格偏好：记账通路每写一格要量一次（本机实测 425 参数 × 4 文件那一趟
    Summary 读回非空 22,139 格，账上要量到同量级），逐字符走 ``unicodedata`` 是纯亏。
    ASCII 字符的 ``east_asian_width``
    恒为 ``'N'``/``'Na'`` ⇒ 两条口径同值，由 ``DisplayWidthFastPathTests`` 逐例钉住。
    """
    if type(text) is not str:
        text = str(text)
    if text.isascii():
        return len(text)
    return sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in text)


# ── 列宽：钳位常数是产品契约（`test_gage_sheet_shape.PIN_SUMMARY_WIDTHS` 钉着落点）──
COL_MIN_WIDTH = 8.0
COL_MAX_WIDTH = 42.0
COL_WIDTH_PADDING = 2.5

_CELL_REF = re.compile(r'\A([A-Z]+)(\d+)\Z')

# ── Go 侧「常规」格式的三道界（`cell_display_text` 的定义域就到这里为止）──
# 三个数都是本机拿 excelize 的 get_cols 读回实测出来的（判据 CellDisplayTextTests 逐条对
# Go 读回，含边界内/边界外两侧）。它们必须**一起**动：把 GO_SIG_DIGITS 改掉而 GO_FIXED_MAX_LEN
# 不动，`|x|<1` 那条就会一半按 15 一半按旧值判 —— 所以宁可named，别留在两处裸字面量里。
#: 整数值进 int32 回绕范围之外时 Go 读回的是回绕值，不是原值 ⇒ 出域，交给整表回读。
GO_INT32_MIN, GO_INT32_MAX = -(2 ** 31), 2 ** 31 - 1
#: 十进制有效数字上限：超了 Go 会舍入（``123456789012345.6`` 读回 ``'123456789012346'``）。
GO_SIG_DIGITS = 15
#: ``|x|<1`` 且靠补零展开的定点串最长就这样；再长 Go 改写成科学计数法（``1e-15`` → ``'1E-15'``）。
GO_FIXED_MAX_LEN = 16


def _cell_coordinates(ref):
    """``'AA12'`` → ``(列号, 行号)``；形状不认识时返回 ``None``（调用方据此回退）。

    列号换算在 Python 侧做，是为了不让「记账」这件事再往每格一次 ctypes→Go 的路上加钱。
    两侧判据（都在 ``test_gage_column_width_tracking``）：``CellCoordinatesTests`` 拿 Go 自己的
    ``cell_name_to_coordinates`` 扫单/双字母 × 各种行号的形状（含 ``AA``/``AB`` 与越界写法），
    ``SummaryWriteSeamTests`` 再拿真实构建里逐个**真写出去**的地址对一遍 —— 前者管换算，
    后者管「产品真会写出这种地址」。
    """
    match = _CELL_REF.match(ref)
    if match is None:
        return None
    letters, row = match.group(1), match.group(2)
    col_idx = 0
    for ch in letters:
        col_idx = col_idx * 26 + (ord(ch) - 64)     # 'A' → 1 … 'Z' → 26，'AA' → 27
    return col_idx, int(row)


def cell_display_text(value):
    """原生值 → ``get_cols`` 会读回的那串文本；``None`` 表示「复刻不了」，调用方必须回退。

    ``write_cell`` 把 numpy 标量降成 Python 原生值后交给 excelize，Go 侧再按 Excel「常规」
    口径把数值渲染成字符串。下列差异都是本机实测，它们直接决定宽度，所以不能拿
    ``str(value)`` 顶替；可重跑的口径是仓内判据 —— ``CellDisplayTextTests`` 拿 Go 自己的
    ``get_cols`` 读回逐个对（含「定义域内逐字相等」与「出域必须返回 ``None``」两侧），
    定义域覆盖面另由 ``test_in_domain_covers_what_the_summary_actually_writes`` 对着
    Summary 真正写出的那批值钉：

    * 整数值浮点不写小数点：``6.0`` → ``'6'``、``-0.0`` → ``'-0'``（``str`` 会多写 ``'.0'``）；
    * 小于 1 的数按定点展开：``1e-05`` → ``'0.00001'``；定点写法超过 16 字符就改科学计数法
      （``1e-15`` → ``'1E-15'``）；
    * 数字位数超过 15 会舍入（``123456789012345.6`` → ``'123456789012346'``）、整数字位到
      1e15 起改科学计数法（``2e15`` → ``'2E+15'``）；
    * 布尔是 ``'TRUE'``/``'FALSE'``，``nan``/``inf`` 是 ``'NaN'``/``'+Inf'``/``'-Inf'``；
    * 整数过 Go 那道墙按 **int32 回绕**（本机实测 ``2**31`` 读回 ``'-2147483648'``、
      ``10**14`` 读回 ``'276447232'``、``10**20`` 读回 ``'1661992960'``）—— 超出
      ``[-2**31, 2**31)`` 的一律出域，宽度交给整表回读。
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, int):
        return str(value) if GO_INT32_MIN <= value <= GO_INT32_MAX else None
    if isinstance(value, float):
        if value != value:
            return 'NaN'
        if value == math.inf:
            return '+Inf'
        if value == -math.inf:
            return '-Inf'
        repr_text = repr(value)
        exponent_form = 'e' in repr_text
        if exponent_form:
            match = _EXPONENT_REPR.match(repr_text)
            if match is None:
                return None                       # 正指数（>=1e16）：Go 用科学计数法
            head, frac, exp = match.group(1), match.group(2) or '', int(match.group(3))
            digits = head.lstrip('-') + frac
            zeros = '0' * (-exp - 1)
            text = (('-' if head.startswith('-') else '') + '0.' + zeros + digits)
        else:
            text = repr_text[:-2] if repr_text.endswith('.0') else repr_text
        head, _, tail = text.lstrip('-').partition('.')
        if head.lstrip('0'):                      # |x| >= 1：整串位数上限就是 GO_SIG_DIGITS
            return text if len(head) + len(tail) <= GO_SIG_DIGITS else None
        # |x| < 1：有效数字 <=15；指数写法还要求定点串本身不超过 16 字符（再长 Go 就改科学计数法）
        if len((head + tail).lstrip('0')) > GO_SIG_DIGITS:
            return None
        return None if (exponent_form and len(text) > GO_FIXED_MAX_LEN) else text
    return None


def _horizontal_anchor_cells(f, sheet):
    """横向合并区的锚点 ``{(列号, 行号)}``：跨列标题不该把首列撑到整行宽。纵向合并不在内。"""
    anchors = set()
    for merged in f.get_merge_cells(sheet):
        first_col, first_row = excelize.cell_name_to_coordinates(merged.get_start_axis())
        last_col, _ = excelize.cell_name_to_coordinates(merged.get_end_axis())
        if last_col > first_col:
            anchors.add((first_col, first_row))
    return anchors


def _clamped_width(longest, min_width, max_width, padding):
    return min(max(longest + padding, min_width), max_width)


def scan_column_widths(f, sheet, min_row=1, min_width=COL_MIN_WIDTH,
                       max_width=COL_MAX_WIDTH, padding=COL_WIDTH_PADDING):
    """整表回读算列宽：``{列号: 宽度}``（没有正宽度的列**不出现在表里**）。

    旧 ``autofit_columns`` 的算法本体（那个「扫一遍再逐列下发」的包装函数已随本刀删除：
    Gage 改用 ``ColumnWidthTracker`` 后它在生产里零调用方，留着只会让下一次清扫把它当
    死代码删掉、而判据还依赖它）。保留这条通路有两个真实用途：``ColumnWidthTracker``
    遇到出域值时的**回退**，以及列宽平价判据手里那条**对照**。

    三条筛选口径（``ColumnWidthTracker.widths`` 必须与它们逐格一致，平价判据钉的就是这个）：
    ``min_row`` 之前的行不参与（标题带/说明标签如 "Failed Items (R&R% >= 30%):  3" 不是列
    内容，否则把该列撑得很宽）；读回为空的不计；横向合并区的**锚点格**跳过（跨列长标题
    会把首列撑到整行宽），纵向合并（单列）不受影响。
    """
    anchors = _horizontal_anchor_cells(f, sheet)
    widths = {}
    for col_idx, column in enumerate(f.get_cols(sheet), start=1):
        longest = 0
        for offset, value in enumerate(column):
            row = offset + 1
            if row < min_row or not value or (col_idx, row) in anchors:
                continue
            longest = max(longest, _display_width(value))
        if longest:
            widths[col_idx] = _clamped_width(longest, min_width, max_width, padding)
    return widths


def apply_column_widths(f, sheet, widths):
    """按列号**升序**逐列下发。顺序是承重的：旧通路是 ``get_cols`` 从左到右，下发次序换了
    ``<cols>`` 的写法就可能跟着换（``test_gage_sheet_shape`` 的 sha256 判据会抓）。"""
    for col_idx in sorted(widths):
        name = excelize.column_number_to_name(col_idx)
        f.set_col_width(sheet, name, name, widths[col_idx])


class ColumnWidthTracker:
    """写格子时顺手记账每列最大显示宽度，收尾一次下发 —— 替掉整表回读那条通路。

    等价性论证（也是 ``test_gage_column_width_parity.py`` 钉的东西）：整表回读那条通路算出的
    宽度只取决于「``min_row`` 之上、读回非空、不是横向合并锚点」这些格的显示宽度，
    而一张表里满足条件的格子全部经 ``write_cell`` 落盘；把同一批格在写的时候量好，收尾
    就不必读回来。省下的是整表物化 —— 本机实测（同一合成形状、best-of-3 墙钟、改前/改后
    两棵树各跑一遍）：425 参数 × 4 文件 × 500 行那一趟 `get_cols` 要读回 27 列共 46,220 个
    格子（非空 22,139），整次导出 5,011ms → 4,005ms（省 20%）；300 参数 × 4 文件是
    3,500ms → 2,841ms，40 参数 × 2 文件是 296ms → 236ms。三档产物 sha256 逐字节不变。

    三条前提，全部有判据守着（``test/backend/test_gage_column_width_tracking.py``）：

    ① **能撑宽的那几格**都走了 ``note``：判据按 ``set_cell_value`` 的录放逐格核对账本，凡
       行号 ≥ ``min_row`` 的写格必须在账上（绕过 ``write_cell`` 直写的新通路会让那一列静默
       变窄，当场红）。``min_row`` 之上的直写豁免且是对的 —— Summary 现在就有两处（A3 标签、
       B3 计数，行 3），旧扫描本来也不计它们，账上没有才是正确形状；
    ② 记账格子的样式**不带自定义数字格式** —— 实测 ``0.000%`` 把 0.4242 渲染成 ``'42.420%'``，
       比原值宽，量原值就会算窄；Gage Summary 里唯一的数字格式挂在 R&R% 列，那一列只有公式
       （读回空串，本来就不计数）与 ``'N/A'`` 文本；
    ③ 值的渲染能复刻（``cell_display_text`` 给得出串）。复刻不了的值不猜：一旦记到就直接
       回退整表回读，付时间而不付宽度。

    公式格（``set_cell_formula``）不经这里：实测 ``get_cols`` 对公式格返回空串，旧通路同样
    不计数 ⇒ 公式不撑宽任何列。
    """

    def __init__(self, sheet):
        self._sheet = sheet
        self._records = {}          # {列号: {行号: 显示宽度}} —— 同一格后写覆盖前写
        self._needs_full_scan = False

    def note(self, sheet, cell, value):
        """记一格。不是自己那张表、或者值复刻不了，就不记（后者触发整表回读）。"""
        if sheet != self._sheet or self._needs_full_scan:
            return
        coord = _cell_coordinates(cell)
        if coord is None:
            self._needs_full_scan = True
            return
        text = cell_display_text(value)
        if text is None:
            self._needs_full_scan = True
            return
        width = _display_width(text)
        if width:
            col_idx, row = coord
            self._records.setdefault(col_idx, {})[row] = width

    def records(self):
        """账本本体 ``{列号: {行号: 宽度}}`` —— 只给判据用，生产别调。"""
        return self._records

    def fell_back(self):
        """是否因为出域值而打算回退整表回读 —— 只给判据用。"""
        return self._needs_full_scan

    def widths(self, f, min_row=1, min_width=COL_MIN_WIDTH,
               max_width=COL_MAX_WIDTH, padding=COL_WIDTH_PADDING):
        """按旧通路的三条筛选（``min_row`` / 非空 / 非横向合并锚点）摊开账本。

        ``f`` 只在两种情况下用到：回退时整表回读，以及取合并区的锚点坐标（每表一次跨界调用）。
        """
        if self._needs_full_scan:
            return scan_column_widths(
                f, self._sheet, min_row, min_width, max_width, padding)
        anchors = _horizontal_anchor_cells(f, self._sheet)
        widths = {}
        for col_idx, row_widths in self._records.items():
            longest = 0
            for row, width in row_widths.items():
                if row < min_row or (col_idx, row) in anchors:
                    continue
                if width > longest:
                    longest = width
            if longest:
                widths[col_idx] = _clamped_width(longest, min_width, max_width, padding)
        return widths

    def apply(self, f, min_row=1, min_width=COL_MIN_WIDTH,
              max_width=COL_MAX_WIDTH, padding=COL_WIDTH_PADDING):
        apply_column_widths(f, self._sheet, self.widths(
            f, min_row, min_width, max_width, padding))
