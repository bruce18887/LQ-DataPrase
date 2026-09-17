"""Gage Summary 工作簿的样式工厂。

配色全部取自 `apps/export/excel_theme`（与 buyoff 共用同一套素雅配色）。
本模块只负责把这些通用样式组合成 Gage 需要的两组固定顺序元组，
不含任何布局或统计逻辑。
"""
import excelize

from apps.export import excel_theme as theme

_FONT = "Calibri"


def _grid_style(f, strong):
    """组框格：``strong`` 里的边用中灰中等线，其余用浅灰细线。

    ``strong`` 取 {"left", "top", "bottom", "right"} 的子集。
    """
    return f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=theme.COLOR_FONT, family=_FONT),
        fill=excelize.Fill(type="pattern", color=[theme.COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(
                type=side,
                color=theme.COLOR_BORDER_STRONG if side in strong else theme.COLOR_BORDER,
                style=2 if side in strong else 1,
            )
            for side in ("left", "top", "bottom", "right")
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def _text_style(f, color, size, bold=True, align="left"):
    """无填充无边框的纯文字样式（用于表头区的标签/计数）。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=bold, size=float(size), color=color, family=_FONT),
        alignment=excelize.Alignment(horizontal=align, vertical="center"),
    ))


def create_summary_styles(f):
    """创建 Summary 工作表所需样式（固定顺序，返回元组）。

    调用方按下面的顺序解包：
        header_style, title_style, info_label_style, info_value_style,
        warning_style, data_style, thick_top_style, thick_top_mid_style,
        thick_top_right_style, thick_left_style, thick_right_style,
        thick_bottom_style, thick_bottom_mid_style, thick_bottom_right_style,
        r_r_pct_style, bad1_ok_style, bad1_fail_style
    """
    header_style = theme.make_header_style(f, 12)
    title_style = theme.make_title_style(f, 16)
    info_label_style = _text_style(f, theme.COLOR_FONT, 10)
    info_value_style = _text_style(f, theme.COLOR_FONT, 10, bold=False)
    # 警示文字：深红粗体、无底色（旧版用 F5B7B1 当字体色，粉字压白底几乎看不清）
    warning_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=9, color=theme.FONT_FAIL, family=_FONT),
        alignment=excelize.Alignment(horizontal="left", vertical="center", wrap_text=True),
    ))
    data_style = theme.make_data_style(f, 10)

    # 每个测试项的组框：外缘中灰中等线、内部浅灰细线
    thick_top_style = _grid_style(f, {"left", "top"})
    thick_top_mid_style = _grid_style(f, {"top"})
    thick_top_right_style = _grid_style(f, {"top", "right"})
    thick_left_style = _grid_style(f, {"left"})
    thick_right_style = _grid_style(f, {"right"})
    thick_bottom_style = _grid_style(f, {"left", "bottom"})
    thick_bottom_mid_style = _grid_style(f, {"bottom"})
    thick_bottom_right_style = _grid_style(f, {"bottom", "right"})

    # R&R% 列：set_cell_style 是替换语义，必须自带底与边框，否则会在网格上留洞。
    # 超标的高亮交给条件格式（见 builder 的 add_threshold_verdict_rules）——
    # 条件格式是叠加的，不会替换掉这里的底与边框。
    r_r_pct_style = theme.make_data_style(f, 10, num_fmt="0.000%")

    bad1_ok_style = _text_style(f, theme.FONT_PASS, 11)
    bad1_fail_style = _text_style(f, theme.FONT_FAIL, 11)

    return (
        header_style, title_style, info_label_style, info_value_style,
        warning_style, data_style, thick_top_style, thick_top_mid_style,
        thick_top_right_style, thick_left_style, thick_right_style,
        thick_bottom_style, thick_bottom_mid_style, thick_bottom_right_style,
        r_r_pct_style, bad1_ok_style, bad1_fail_style,
    )


def create_file_sheet_styles(f):
    """创建单个文件工作表所需样式（固定顺序，返回元组）。

    调用方按顺序解包：header_block_style, gray_style,
    stats_gray_style, stats_border_style。
    """
    header_block_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[theme.COLOR_TITLE_BG], pattern=1),
        border=theme.thin_border(),
    ))
    gray_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[theme.FILL_NA], pattern=1),
        border=theme.thin_border(),
    ))
    stats_gray_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[theme.FILL_NA], pattern=1),
        border=theme.thin_border(),
        alignment=excelize.Alignment(horizontal="right"),
    ))
    stats_border_style = f.new_style(excelize.Style(
        border=theme.thin_border(),
        alignment=excelize.Alignment(horizontal="right"),
    ))
    return header_block_style, gray_style, stats_gray_style, stats_border_style
