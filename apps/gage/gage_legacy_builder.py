"""Gage R&R summary Excel builder（编排层）。

`build_gage_summary_excel` 只做编排：建工作簿 → 写 Summary 页眉 → 逐测试项算统计
（`gage_summary_stats`）并写行（`gage_summary_sheet`）→ 收尾版式 → 逐个写单文件
工作表（`gage_file_sheet`）→ 存成字节。样式来自 `gage_styles`。
"""

import os
import tempfile
from functools import partial

import excelize

from apps.common.constants import NON_NUMERIC_KEYWORDS
from apps.gage.gage_file_sheet import write_file_sheet
from apps.gage.gage_styles import create_file_sheet_styles, create_summary_styles
from apps.gage.gage_summary_sheet import (
    DATA_FIRST_ROW,
    SUMMARY_SHEET,
    apply_rr_pct_verdict_rules,
    finalize_summary_sheet,
    fold_good_groups,
    format_summary_sheet,
    hide_helper_columns,
    mark_failed_label,
    write_average_row,
    write_bad1_count,
    write_cell,
    write_summary_intro,
    write_test_item_rows,
)
from apps.gage.gage_summary_stats import analyze_test_item, select_test_columns


def build_gage_summary_excel(file_datasets, ignore_no_limit=False):
    """写 Gage R&R 汇总（Summary + 每文件一张表），返回 xlsx 字节。"""
    f = excelize.new_file()

    # Rename default sheet to Summary
    sheet_list = f.get_sheet_list()
    if sheet_list:
        f.set_sheet_name(sheet_list[0], SUMMARY_SHEET)

    num_files = len(file_datasets)
    non_numeric_keywords = NON_NUMERIC_KEYWORDS
    styles = create_summary_styles(f)
    set_cell = partial(write_cell, f)

    write_summary_intro(f, num_files, styles, set_cell)

    # 测试项筛选（系统列/非数值列恒排除，defect #7）口径见 gage_summary_stats
    all_test_cols = select_test_columns(file_datasets, ignore_no_limit)

    current_row = DATA_FIRST_ROW
    bad1_count = 0
    group_info = []
    # Per-test 6σ values kept in memory so the Average row is computed from
    # these arrays, never by reading cells back (defect #6).
    repeatability_series = []
    reproducibility_series = []

    for test_name in all_test_cols:
        item = analyze_test_item(test_name, file_datasets, num_files)
        repeatability_series.append(item.repeatability)
        reproducibility_series.append(item.reproducibility)
        if item.is_bad_group:
            bad1_count += 1

        current_row, group_start, group_end = write_test_item_rows(
            f, item, current_row, set_cell)
        group_info.append((group_start, group_end, item.is_bad_group))

    last_data_row = current_row - 1

    # Average row 取自内存里的 6σ 序列（defect #6），绝不回读单元格。
    if num_files >= 2:
        write_average_row(f, repeatability_series, reproducibility_series,
                          current_row, styles, set_cell)

    write_bad1_count(f, bad1_count, styles)
    format_summary_sheet(f, group_info, last_data_row, styles)
    apply_rr_pct_verdict_rules(f, last_data_row)
    fold_good_groups(f, group_info)
    mark_failed_label(f, bad1_count, styles)
    hide_helper_columns(f)
    finalize_summary_sheet(f)

    # Pre-create styles for individual file sheets
    file_styles = create_file_sheet_styles(f)

    # === INDIVIDUAL FILE SHEETS ===
    for file_info in file_datasets:
        write_file_sheet(f, file_info, ignore_no_limit, non_numeric_keywords,
                         file_styles, set_cell)

    # Save to bytes — try/finally guarantees the temp file and the excelize
    # handle are released even if save_as / read raises (defect #10). Mirrors
    # apps/export/excelize_helpers.save_excelize, kept local to avoid a
    # cross-module dependency on apps/export (edited in parallel).
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp_path = tmp.name
        f.save_as(tmp_path)
        with open(tmp_path, 'rb') as fh:
            data = fh.read()
        return data
    finally:
        try:
            f.close()
        except Exception:
            pass
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
