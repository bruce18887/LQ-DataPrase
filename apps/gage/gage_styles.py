"""Gage Summary 工作簿的样式工厂。

把 `gage_legacy_builder` 里成组的配色常量与 `new_style` 调用集中到这里，
让 builder 只保留表格布局与统计逻辑（文件行数控制）。
所有样式定义逐字从原 builder 迁出，未做任何视觉改动。
"""
import excelize

# 现代专业配色（与 buyoff 统一）
COLOR_HEADER_BG = "2C3E50"
COLOR_HEADER_FONT = "FFFFFF"
COLOR_DATA_BG = "F8F9FA"
COLOR_BORDER = "BDC3C7"
COLOR_FONT_DARK = "2C3E50"
COLOR_RED_BG = "F5B7B1"
COLOR_GREEN_OK = "27AE60"

FILL_GRAY_HEX = "E0E0E0"
FILL_LIGHT_BLUE_HEX = "D6EAF8"


def create_summary_styles(f):
    """创建 Summary 工作表所需样式（固定顺序，返回元组）。

    调用方按下面的顺序解包：
        header_style, title_style, info_label_style, info_value_style,
        warning_style, data_style, thick_top_style, thick_top_mid_style,
        thick_top_right_style, thick_left_style, thick_right_style,
        thick_bottom_style, thick_bottom_mid_style, thick_bottom_right_style,
        red_cell_style, r_r_pct_style, red_rr_pct_style, bad1_ok_style,
        bad1_fail_style
    """
    header_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=12, color=COLOR_HEADER_FONT, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_HEADER_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=2),
            excelize.Border(type="top", color=COLOR_BORDER, style=2),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=2),
            excelize.Border(type="right", color=COLOR_BORDER, style=2),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    title_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=16, color=COLOR_HEADER_FONT, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_HEADER_BG], pattern=1),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    info_label_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=10, color=COLOR_FONT_DARK, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center"),
    ))
    info_value_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center"),
    ))
    warning_style = f.new_style(excelize.Style(
        font=excelize.Font(size=9, color=COLOR_RED_BG, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center", wrap_text=True),
    ))
    data_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    thick_top_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=2),
            excelize.Border(type="top", color=COLOR_BORDER, style=2),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    thick_top_mid_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=2),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    thick_top_right_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=2),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=2),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    thick_left_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=2),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    thick_right_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=2),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    thick_bottom_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=2),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=2),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    thick_bottom_mid_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=2),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    thick_bottom_right_style = f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=2),
            excelize.Border(type="right", color=COLOR_BORDER, style=2),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))

    # Regular red fill style for direct cell coloring
    red_cell_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
    ))

    # Percentage format style for R&R% column
    r_r_pct_style = f.new_style(excelize.Style(
        custom_num_fmt="0.000%",
    ))

    # Red fill + percentage format for Bad1 R&R% cells
    red_rr_pct_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
        custom_num_fmt="0.000%",
    ))

    # Bold style for Bad1 count
    bad1_ok_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=11, color=COLOR_GREEN_OK, family="Calibri"),
    ))
    bad1_fail_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=11, color="FFFFFF", family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
    ))

    return (
        header_style, title_style, info_label_style, info_value_style,
        warning_style, data_style, thick_top_style, thick_top_mid_style,
        thick_top_right_style, thick_left_style, thick_right_style,
        thick_bottom_style, thick_bottom_mid_style, thick_bottom_right_style,
        red_cell_style, r_r_pct_style, red_rr_pct_style, bad1_ok_style,
        bad1_fail_style,
    )


def create_file_sheet_styles(f):
    """创建单个文件工作表所需样式（固定顺序，返回元组）。

    调用方按顺序解包：light_blue_style, gray_style,
    stats_gray_style, stats_border_style。
    """
    light_blue_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[FILL_LIGHT_BLUE_HEX], pattern=1),
        border=[
            excelize.Border(type="left", color="000000", style=1),
            excelize.Border(type="top", color="000000", style=1),
            excelize.Border(type="bottom", color="000000", style=1),
            excelize.Border(type="right", color="000000", style=1),
        ],
    ))
    gray_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[FILL_GRAY_HEX], pattern=1),
        border=[
            excelize.Border(type="left", color="000000", style=1),
            excelize.Border(type="top", color="000000", style=1),
            excelize.Border(type="bottom", color="000000", style=1),
            excelize.Border(type="right", color="000000", style=1),
        ],
    ))
    stats_gray_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[FILL_GRAY_HEX], pattern=1),
        border=[
            excelize.Border(type="left", color="000000", style=1),
            excelize.Border(type="top", color="000000", style=1),
            excelize.Border(type="bottom", color="000000", style=1),
            excelize.Border(type="right", color="000000", style=1),
        ],
        alignment=excelize.Alignment(horizontal="right"),
    ))
    stats_border_style = f.new_style(excelize.Style(
        border=[
            excelize.Border(type="left", color="000000", style=1),
            excelize.Border(type="top", color="000000", style=1),
            excelize.Border(type="bottom", color="000000", style=1),
            excelize.Border(type="right", color="000000", style=1),
        ],
        alignment=excelize.Alignment(horizontal="right"),
    ))
    return light_blue_style, gray_style, stats_gray_style, stats_border_style
