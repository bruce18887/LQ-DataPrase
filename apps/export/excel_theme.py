"""统一的 Excel 输出配色与样式工厂。

骨架：浅灰标题带（`F2F2F2`）+ 深蓝表头带（`1F4E79`）+ 中性灰分层。
判定：用**底色 + 配套字色**表达 —— pass 浅绿、warn 浅黄、fail 深红配白字；
表内判定走 **Excel 条件格式**（`add_*_rules`），用户改值后颜色自动跟随。
「无法判定」保留静态极浅灰底，与三档判定色区分。

buyoff 与 Gage 共用本模块。注意与 `apps/export/excelize_helpers.py` 区分：后者被
batch_report / sigma-limit / 数据导出消费，配色保持原样，不要混用。
"""
import unicodedata

import excelize

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

_FONT = "Calibri"

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
    """文本显示宽度：东亚宽字符按 2 计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in str(text))


def autofit_columns(f, sheet, min_row=1, min_width=8.0, max_width=42.0, padding=2.5):
    """按单元格**显示值**设置列宽（excelize 没有 auto-fit，这里自己算）。

    ``min_row`` 之前的行不参与 —— 标题带、说明标签这类表头区文字（如
    "Failed Items (R&R% >= 30%):  3"）不是表格列的内容，否则会把该列撑得很宽。
    横向合并区（跨列标题）也只按锚点列计一次并**跳过**，否则跨列长标题会把首列
    撑到整行宽；纵向合并（单列）不受影响。
    """
    horizontal_anchor_cols = set()
    for merged in f.get_merge_cells(sheet):
        first_col, first_row = excelize.cell_name_to_coordinates(merged.get_start_axis())
        last_col, _ = excelize.cell_name_to_coordinates(merged.get_end_axis())
        if last_col > first_col:
            horizontal_anchor_cols.add((first_col, first_row))

    for col_idx, column in enumerate(f.get_cols(sheet), start=1):
        longest = 0
        for offset, value in enumerate(column):
            row = offset + 1
            if row < min_row or not value:
                continue
            if (col_idx, row) in horizontal_anchor_cols:
                continue
            longest = max(longest, _display_width(value))
        if longest:
            width = min(max(longest + padding, min_width), max_width)
            name = excelize.column_number_to_name(col_idx)
            f.set_col_width(sheet, name, name, width)
