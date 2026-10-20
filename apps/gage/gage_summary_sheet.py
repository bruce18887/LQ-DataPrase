"""Gage R&R Summary 工作表的版式写出。

从 `gage_legacy_builder` 逐字迁出：页眉信息区、逐测试项数据行（含 V/W/X/Y 公式）、
组边框与折叠、R&R% 条件格式与收尾。数值口径在 `gage_summary_stats`，本模块只做
Excel 布局，所以改版式不会牵动统计。
"""
import numpy as np
import excelize

from apps.export.excel_theme import (
    add_threshold_verdict_rules, autofit_columns, set_formula, enable_full_recalc,
)
from apps.gage.gage_summary_stats import RR_PCT_BAD1, RR_PCT_BAD2

SUMMARY_SHEET = "Summary"

# 第 11 行是表头，数据从第 12 行起；隐藏列 R-U(18-21) 是组级中间量。
DATA_FIRST_ROW = 12
HIDDEN_COL_FROM = 18
HIDDEN_COL_TO = 21

SUMMARY_HEADERS = [
    'File Name', 'Tester ID', 'Test Name', 'Test#', 'LowLimit', 'HighLimit', 'Unit',
    'Mean', 'STD', 'Min', 'Max', 'CP', 'CPK',
    '', 'Mean', 'STD', '6*STD', 'Min CPK', 'Max CPK', 'Total CP', 'Total CPK',
    'Repeatibility', 'Reproducibility', 'R&R', 'R&R%', 'Fail Level', 'Comments'
]
SUMMARY_HEADER_COUNT = len(SUMMARY_HEADERS)

# Cache last column letter for merge operations
LAST_COL = excelize.column_number_to_name(SUMMARY_HEADER_COUNT)

COL_V = 22
COL_W = 23
COL_RR = 24
COL_RR_PCT = 25
COL_FAIL = 26
COL_COMMENTS = 27


def calc_d2(n):
    """d2* 常数表（用于信息区 B8）；n≥20 统一取 3.80537。"""
    d2_map = {1: 1.0, 2: 1.41421, 3: 1.91155, 4: 2.23887, 5: 2.48124,
               6: 2.67253, 7: 2.82981, 8: 2.96288, 9: 3.07794, 10: 3.17905,
               11: 3.26909, 12: 3.35016, 13: 3.42378, 14: 3.49116, 15: 3.55333,
               16: 3.61071, 17: 3.66422, 18: 3.71424, 19: 3.76118}
    if n >= 20:
        return 3.80537
    return d2_map.get(n, 1.0)


def write_cell(f, sheet, cell, value):
    """写单元格：numpy 标量降为原生类型，空值留真空格。

    空串会被写成**文本**单元格（t="s"）。Excel 里文本恒大于任何数值，
    所以数值型条件格式（如 R&R% >= 30%）会把空白格也判中 → 整列标红。
    留真空格才是正确的「没有值」表示。
    """
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or value == '':
        return
    f.set_cell_value(sheet, cell, value)


def write_summary_intro(f, num_files, styles, set_cell):
    """标题、Failed Items 占位、警示条、信息区与表头行，并隐藏 4–10 行。"""
    set_cell(SUMMARY_SHEET, "A1", f"Gage R&R Summary Report ({num_files} files)")
    f.set_cell_style(SUMMARY_SHEET, "A1", "A1", styles.title)
    f.merge_cell(SUMMARY_SHEET, "A1", f"{LAST_COL}1")

    # Bad1 count with label
    set_cell(SUMMARY_SHEET, "A3", "Failed Items (R&R% >= 30%):")
    f.set_cell_style(SUMMARY_SHEET, "A3", "A3", styles.info_label)
    set_cell(SUMMARY_SHEET, "B3", "")
    f.set_cell_style(SUMMARY_SHEET, "B3", "B3", styles.info_value)

    # Warning text
    set_cell(SUMMARY_SHEET, "C3", "HW Gage FAIL. These tests must be fixed before release. Must get manager's/supervisor's approval if it cannot be fixed. (R&R% >= 30.00 %)")
    f.set_cell_style(SUMMARY_SHEET, "C3", "C3", styles.warning)
    f.merge_cell(SUMMARY_SHEET, "C3", f"{LAST_COL}3")

    # Info section
    set_cell(SUMMARY_SHEET, "A7", "FileQuantity:")
    f.set_cell_style(SUMMARY_SHEET, "A7", "A7", styles.info_label)
    set_cell(SUMMARY_SHEET, "B7", num_files)
    f.set_cell_style(SUMMARY_SHEET, "B7", "B7", styles.info_value)

    set_cell(SUMMARY_SHEET, "A8", "d2*:")
    f.set_cell_style(SUMMARY_SHEET, "A8", "A8", styles.info_label)
    set_cell(SUMMARY_SHEET, "B8", calc_d2(num_files))
    f.set_cell_style(SUMMARY_SHEET, "B8", "B8", styles.info_value)

    set_cell(SUMMARY_SHEET, "A9", "# of Sigma for R&R:")
    f.set_cell_style(SUMMARY_SHEET, "A9", "A9", styles.info_label)
    set_cell(SUMMARY_SHEET, "B9", 6)
    f.set_cell_style(SUMMARY_SHEET, "B9", "B9", styles.info_value)

    # Header row 11
    for col_idx, header in enumerate(SUMMARY_HEADERS, 1):
        col_letter = excelize.column_number_to_name(col_idx)
        set_cell(SUMMARY_SHEET, f"{col_letter}11", header)
        f.set_cell_style(SUMMARY_SHEET, f"{col_letter}11", f"{col_letter}11",
                         styles.header)

    # Hide rows 4-10
    for row in range(4, 11):
        f.set_row_visible(SUMMARY_SHEET, row, False)


def write_test_item_rows(f, item, start_row, set_cell):
    """写一个测试项的逐文件行（首个有数据的行带组级列与公式）。

    返回 ``(下一空行, group_start_row, group_end_row)``。
    """
    current_row = start_row
    # 组的行范围（每文件一行）与「公差来源行」，供 V/W/X/Y 公式引用。
    group_last_row = start_row + len(item.per_file) - 1
    tol_row = (start_row + item.tol_idx if item.tol_idx is not None else None)
    group_first_data_row = None

    for entry in item.per_file:
        fn = entry['fn']
        low_l = entry['low_l']
        high_l = entry['high_l']
        unit = entry['unit']
        low_disp = low_l if low_l is not None else 'N/A'
        high_disp = high_l if high_l is not None else 'N/A'

        if entry['has_data']:
            if group_first_data_row is None:
                group_first_data_row = current_row

            cp = entry['cp'] if entry['cp'] is not None else 0.0
            cpk = entry['cpk'] if entry['cpk'] is not None else 0.0

            row_data = [
                fn, '', item.test_name, '', low_disp, high_disp, unit,
                round(entry['mean'], 4), round(entry['std'], 4),
                round(entry['min'], 4), round(entry['max'], 4),
                round(cp, 4), round(cpk, 4),
                '', '', '', '', '', '', '', '',
                '', '', '', '', '', ''
            ]

            for col_idx, val in enumerate(row_data, 1):
                col_letter = excelize.column_number_to_name(col_idx)
                set_cell(SUMMARY_SHEET, f"{col_letter}{current_row}", val)

            if current_row == group_first_data_row:
                set_cell(SUMMARY_SHEET, f"O{current_row}", round(item.global_mean, 4))
                set_cell(SUMMARY_SHEET, f"P{current_row}", round(item.global_std, 4))
                set_cell(SUMMARY_SHEET, f"Q{current_row}", round(6 * item.global_std, 4))
                set_cell(SUMMARY_SHEET, f"R{current_row}", round(item.min_cpk, 4))
                set_cell(SUMMARY_SHEET, f"S{current_row}", round(item.max_cpk, 4))
                set_cell(SUMMARY_SHEET, f"T{current_row}", round(item.overall_cp, 4))
                set_cell(SUMMARY_SHEET, f"U{current_row}", round(item.overall_cpk, 4))

                v_col = excelize.column_number_to_name(COL_V)
                w_col = excelize.column_number_to_name(COL_W)
                rr_col = excelize.column_number_to_name(COL_RR)
                rr_pct_col = excelize.column_number_to_name(COL_RR_PCT)
                fail_col = excelize.column_number_to_name(COL_FAIL)

                # V/W/X/Y 写成公式（引用本表逐文件的 H(Mean)/I(STD) 与 E/F(限值)），
                # 用户改逐文件数值后自动重算。ROUND 位数与旧 Python 口径一致，
                # 故显示不变。Python 仍算同一批值，供 Fail Level / 折叠 / B3 使用。
                r = current_row
                # 注意 6 要放在 SQRT 之后：excelize 的内置计算器解析不了
                # `6*SQRT(.../B7)` 这种「常数 × SQRT(除法)」形式（算出 0），
                # `SQRT(...)*6` 正常。Excel 本身两种都对。
                set_formula(f, SUMMARY_SHEET, f"{v_col}{r}",
                            f"=ROUND(SQRT(SUMSQ(I{start_row}:I{group_last_row})/B7)*6,4)")
                # 用 `STDEVP`（无点号）而非 `STDEV.P`：带点号的函数名是 Excel 2010 才加的，
                # 部分查看器认不出 —— `STDEV.P` 报错后被 IFERROR 悄悄吞成 0，整列 Reproducibility 全 0。
                # 单文件时 STDEVP 本身会 #DIV/0!，用 `IF(COUNT<2,…)` 显式给 0（与 Python 口径一致），
                # 不用 IFERROR —— 免得再出现"报错被吞成 0"的静默失败。
                set_formula(f, SUMMARY_SHEET, f"{w_col}{r}",
                            f"=ROUND(IF(COUNT(H{start_row}:H{group_last_row})<2,0,"
                            f"STDEVP(H{start_row}:H{group_last_row})*6),4)")
                set_formula(f, SUMMARY_SHEET, f"{rr_col}{r}",
                            f"=ROUND(SQRT({v_col}{r}*{v_col}{r}+{w_col}{r}*{w_col}{r}),4)")

                if tol_row is not None:
                    set_formula(f, SUMMARY_SHEET, f"{rr_pct_col}{r}",
                                f"=ROUND({rr_col}{r}/(F{tol_row}-E{tol_row}),6)")
                else:
                    set_cell(SUMMARY_SHEET, f"{rr_pct_col}{r}", 'N/A')

                set_cell(SUMMARY_SHEET, f"{fail_col}{current_row}", item.fail_level)
        else:
            row_data = [
                fn, '', item.test_name, '', low_disp, high_disp, unit,
                '', '', '', '',
                '', '',
                '', '', '', '', '', '', '', '',
                '', '', '', '', '', ''
            ]
            for col_idx, val in enumerate(row_data, 1):
                col_letter = excelize.column_number_to_name(col_idx)
                set_cell(SUMMARY_SHEET, f"{col_letter}{current_row}", val)

        current_row += 1

    return current_row, start_row, current_row - 1


def write_average_row(f, repeatability_series, reproducibility_series, row,
                      styles, set_cell):
    """Average 行取自内存里的 6σ 序列，绝不回读单元格（defect #6）。"""
    avg_repeatability = (sum(repeatability_series) / len(repeatability_series)) if repeatability_series else 0
    avg_reproducibility = (sum(reproducibility_series) / len(reproducibility_series)) if reproducibility_series else 0

    set_cell(SUMMARY_SHEET, f"A{row}", "Average")
    v_col = excelize.column_number_to_name(COL_V)
    w_col = excelize.column_number_to_name(COL_W)
    set_cell(SUMMARY_SHEET, f"{v_col}{row}", round(avg_repeatability, 4))
    set_cell(SUMMARY_SHEET, f"{w_col}{row}", round(avg_reproducibility, 4))
    f.set_cell_style(SUMMARY_SHEET, f"A{row}", f"A{row}", styles.thick_left)


def write_bad1_count(f, bad1_count, styles):
    """B3 的 Bad1 计数与配色（0 个用绿，有则红）。"""
    f.set_cell_value(SUMMARY_SHEET, "B3", bad1_count)
    bad1_style = styles.bad1_fail if bad1_count > 0 else styles.bad1_ok
    f.set_cell_style(SUMMARY_SHEET, "B3", "B3", bad1_style)


def format_summary_sheet(f, group_info, last_data_row, styles):
    """数据区底色带 + 每组外框、Comments 合并与 R&R% 基样式。"""
    # 从第 12 行起（数据首行）。第 11 行是表头，必须留在上面的 header 样式，
    # 否则整片 data 样式会把刚写好的深色表头带覆盖成浅灰。
    for row in range(DATA_FIRST_ROW, last_data_row + 1):
        f.set_cell_style(SUMMARY_SHEET, f"A{row}", f"{LAST_COL}{row}", styles.data)

    for group_start, group_end, _is_bad in group_info:
        # Group borders
        f.set_cell_style(SUMMARY_SHEET, f"A{group_start}", f"A{group_start}",
                         styles.thick_top)
        for col_num in range(2, SUMMARY_HEADER_COUNT):
            cl = excelize.column_number_to_name(col_num)
            f.set_cell_style(SUMMARY_SHEET, f"{cl}{group_start}", f"{cl}{group_start}",
                             styles.thick_top_mid)
        f.set_cell_style(SUMMARY_SHEET, f"{LAST_COL}{group_start}",
                         f"{LAST_COL}{group_start}", styles.thick_top_right)

        for row_idx in range(group_start + 1, group_end):
            f.set_cell_style(SUMMARY_SHEET, f"A{row_idx}", f"A{row_idx}",
                             styles.thick_left)
            for col_num in range(2, SUMMARY_HEADER_COUNT):
                cl = excelize.column_number_to_name(col_num)
                f.set_cell_style(SUMMARY_SHEET, f"{cl}{row_idx}", f"{cl}{row_idx}",
                                 styles.data)
            f.set_cell_style(SUMMARY_SHEET, f"{LAST_COL}{row_idx}",
                             f"{LAST_COL}{row_idx}", styles.thick_right)

        f.set_cell_style(SUMMARY_SHEET, f"A{group_end}", f"A{group_end}",
                         styles.thick_bottom)
        for col_num in range(2, SUMMARY_HEADER_COUNT):
            cl = excelize.column_number_to_name(col_num)
            f.set_cell_style(SUMMARY_SHEET, f"{cl}{group_end}", f"{cl}{group_end}",
                             styles.thick_bottom_mid)
        f.set_cell_style(SUMMARY_SHEET, f"{LAST_COL}{group_end}",
                         f"{LAST_COL}{group_end}", styles.thick_bottom_right)

        # Merge Comments column
        comments_col = excelize.column_number_to_name(COL_COMMENTS)
        f.merge_cell(SUMMARY_SHEET, f"{comments_col}{group_start}",
                     f"{comments_col}{group_end}")

        # R&R% 格统一用基样式；Bad1 的红色高亮由 Y 列上的条件格式统一处理。
        # （条件格式是叠加的，不像 set_cell_style 那样把格子的底色与边框替换掉。）
        rr_pct_col = excelize.column_number_to_name(COL_RR_PCT)
        f.set_cell_style(SUMMARY_SHEET, f"{rr_pct_col}{group_start}",
                         f"{rr_pct_col}{group_start}", styles.rr_pct)


def apply_rr_pct_verdict_rules(f, last_data_row):
    """R&R% 分档上色：Bad1 红、Bad2 橙。一条规则覆盖整条 R&R% 数据区，
    改值后颜色自动跟随；空白格不参与（见 ``write_cell`` 的空串说明）。"""
    rr_pct_col = excelize.column_number_to_name(COL_RR_PCT)
    add_threshold_verdict_rules(
        f, SUMMARY_SHEET,
        f"{rr_pct_col}{DATA_FIRST_ROW}:{rr_pct_col}{last_data_row}",
        [(RR_PCT_BAD1, 'fail'), (RR_PCT_BAD2, 'warn')])


def fold_good_groups(f, group_info):
    """把 R&R% 未达 Bad1 的组折叠起来（Good 组默认收起）。"""
    for group_start, group_end, is_bad in group_info:
        if not is_bad:
            for row in range(group_start, group_end + 1):
                f.set_row_outline_level(SUMMARY_SHEET, row, 1)
                f.set_row_visible(SUMMARY_SHEET, row, False)


def mark_failed_label(f, bad1_count, styles):
    """有 Bad1 项时把 A3 标签改成红字并带上计数。"""
    if bad1_count <= 0:
        return
    f.set_cell_value(SUMMARY_SHEET, "A3", f"Failed Items (R&R% >= 30%):  {bad1_count}")
    f.set_cell_style(SUMMARY_SHEET, "A3", "A3", styles.bad1_fail)


def hide_helper_columns(f):
    """隐藏组级中间量列 R-U（18-21），折叠到 1 级。"""
    for col_num in range(HIDDEN_COL_FROM, HIDDEN_COL_TO + 1):
        cl = excelize.column_number_to_name(col_num)
        f.set_col_visible(SUMMARY_SHEET, cl, False)
        f.set_col_outline_level(SUMMARY_SHEET, cl, 1)


def finalize_summary_sheet(f):
    """列宽自适应、冻结 E12，并要求 Excel 打开时全量重算。"""
    # 列宽按显示内容自适应（表头 "Repeatability"/"Reproducibility" 等否则会被截断）。
    # 从表头行（11）起算，免得上面那行 "Failed Items (...)" 标签把 A 列撑宽。
    autofit_columns(f, SUMMARY_SHEET, min_row=11)

    f.set_panes(SUMMARY_SHEET, excelize.Panes(
        freeze=True,
        split=False,
        x_split=4,
        y_split=11,
        top_left_cell="E12",
    ))

    # V/W/X/Y 是公式，Excel 打开时须重算（否则在重算前显示空白）。
    enable_full_recalc(f)
