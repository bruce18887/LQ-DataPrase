"""Excel layout builders for Gage R&R reports."""

import numpy as np
import pandas as pd
import excelize
import tempfile
import os
from apps.analysis.services.statistics import ensure_numeric
from apps.export.excelize_helpers import (
    make_header_style, make_data_style, make_title_style,
    COLOR_BORDER, COLOR_FONT_DARK, COLOR_DATA_BG, COLOR_RED_BG,
)
from apps.gage.services.rr_analysis import _calc_d2, _safe_float, SUMMARY_COLS, COL_RR_PCT

# ── Constants ──
NON_NUMERIC_KEYWORDS = ['min', 'max', 'lower limit', 'upper limit', 'n/a', 'na', '-', 'none']
FILL_GRAY_HEX = "E0E0E0"
FILL_LIGHT_BLUE_HEX = "D6EAF8"

# ── Style Factories ──

def make_info_label_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=10, color=COLOR_FONT_DARK, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center"),
    ))

def make_info_value_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center"),
    ))

def make_warning_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(size=9, color=COLOR_RED_BG, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center", wrap_text=True),
    ))

def make_good_rate_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=11, color="27AE60", family="Calibri"),
    ))

def make_bad_rate_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=11, color="FFFFFF", family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
    ))

def make_rr_pct_style(f):
    return f.new_style(excelize.Style(custom_num_fmt="0.000%"))

def make_red_rr_pct_style(f):
    return f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
        custom_num_fmt="0.000%",
    ))

# ── Helpers ──

def _set_cell(f, sheet, cell, value):
    if isinstance(value, np.generic):
        value = value.item()
    f.set_cell_value(sheet, cell, value)


# ── Summary Sheet Builder ──

def build_summary_sheet(f, file_datasets, all_test_cols, test_name_stats, bad1_count):
    num_files = len(file_datasets)
    last_col = excelize.column_number_to_name(SUMMARY_COLS)
    d2_val = _calc_d2(num_files)

    title_style = make_title_style(f)
    header_style = make_header_style(f, 12)
    data_style = make_data_style(f)
    info_label_style = make_info_label_style(f)
    info_value_style = make_info_value_style(f)
    warning_style = make_warning_style(f)
    rr_pct_style = make_rr_pct_style(f)
    red_rr_pct_style = make_red_rr_pct_style(f)
    bad1_ok_style = make_good_rate_style(f)
    bad1_fail_style = make_bad_rate_style(f)

    # Title row
    _set_cell(f, "Summary", "A1", f"Gage R&R Summary Report ({num_files} files)")
    f.set_cell_style("Summary", "A1", "A1", title_style)
    f.merge_cell("Summary", "A1", f"{last_col}1")

    # Info section - Bad1 count with conditional styling
    _set_cell(f, "Summary", "A3", "Failed Items (R&R% >= 30%):")
    f.set_cell_style("Summary", "A3", "A3", info_label_style if bad1_count == 0 else bad1_fail_style)
    _set_cell(f, "Summary", "B3", bad1_count)
    f.set_cell_style("Summary", "B3", "B3", bad1_ok_style if bad1_count == 0 else bad1_fail_style)

    warning_text = ("HW Gage FAIL. These tests must be fixed before release. "
                    "Must get manager's/supervisor's approval if it cannot be fixed. (R&R% >= 30.00 %)")
    _set_cell(f, "Summary", "C3", warning_text)
    f.set_cell_style("Summary", "C3", "C3", warning_style)
    f.merge_cell("Summary", "C3", f"{last_col}3")

    _set_cell(f, "Summary", "A7", "FileQuantity:")
    f.set_cell_style("Summary", "A7", "A7", info_label_style)
    _set_cell(f, "Summary", "B7", num_files)
    f.set_cell_style("Summary", "B7", "B7", info_value_style)

    _set_cell(f, "Summary", "A8", "d2*:")
    f.set_cell_style("Summary", "A8", "A8", info_label_style)
    _set_cell(f, "Summary", "B8", d2_val)
    f.set_cell_style("Summary", "B8", "B8", info_value_style)

    _set_cell(f, "Summary", "A9", "# of Sigma for R&R:")
    f.set_cell_style("Summary", "A9", "A9", info_label_style)
    _set_cell(f, "Summary", "B9", 6)
    f.set_cell_style("Summary", "B9", "B9", info_value_style)

    # Hide rows 4-10
    for r in range(4, 11):
        f.set_row_visible("Summary", r, False)

    # Column headers (row 11)
    headers = [
        'File Name', 'Tester ID', 'Test Name', 'Test#', 'LowLimit', 'HighLimit', 'Unit',
        'Mean', 'STD', 'Min', 'Max', 'CP', 'CPK',
        '', 'Mean', 'STD', '6*STD', 'Min CPK', 'Max CPK', 'Total CP', 'Total CPK',
        'Repeatibility', 'Reproducibility', 'R&R', 'R&R%', 'Fail Level', 'Comments',
    ]
    for c_idx, h in enumerate(headers, 1):
        cl = excelize.column_number_to_name(c_idx)
        _set_cell(f, "Summary", f"{cl}11", h)
        f.set_cell_style("Summary", f"{cl}11", f"{cl}11", header_style)

    # Data rows
    current_row = 12
    group_info = []

    for test_name in all_test_cols:
        stats = test_name_stats[test_name]
        group_start = current_row
        group_first_row = None

        for file_idx, ds in enumerate(file_datasets):
            fn = ds['filename']
            ll = stats['test_mins'].get(fn, 0)
            hl = stats['test_maxs'].get(fn, 4)
            unit = stats['test_units'].get(fn, '')
            fs = stats['file_stats'][file_idx]

            if fs['has_data']:
                if group_first_row is None:
                    group_first_row = current_row

                row_data = [
                    fn, '', test_name, '', ll, hl, unit,
                    round(fs['mean'], 4), round(fs['std'], 4),
                    round(fs['min'], 4), round(fs['max'], 4),
                    round(fs['cp'], 4), round(fs['cpk'], 4),
                    '', '', '', '', '', '', '', '',
                    '', '', '', '', '', '',
                ]
                for c, val in enumerate(row_data, 1):
                    cl = excelize.column_number_to_name(c)
                    if val != '':
                        _set_cell(f, "Summary", f"{cl}{current_row}", val)

                # Write global stats only on first row of group
                if current_row == group_first_row:
                    _set_cell(f, "Summary", f"O{current_row}", round(stats['global_mean'], 4))
                    _set_cell(f, "Summary", f"P{current_row}", round(stats['global_std'], 4))
                    _set_cell(f, "Summary", f"Q{current_row}", round(6 * stats['global_std'], 4))
                    _set_cell(f, "Summary", f"R{current_row}", round(stats['overall_cpk'], 4))
                    _set_cell(f, "Summary", f"S{current_row}", round(stats['overall_cpk'], 4))
                    _set_cell(f, "Summary", f"T{current_row}", round(stats['overall_cp'], 4))
                    _set_cell(f, "Summary", f"U{current_row}", round(stats['overall_cpk'], 4))
                    _set_cell(f, "Summary", f"V{current_row}", round(stats['repeatability'], 4))
                    _set_cell(f, "Summary", f"W{current_row}", round(stats['reproducibility'], 4))
                    _set_cell(f, "Summary", f"X{current_row}", round(stats['r_r'], 4))
                    _set_cell(f, "Summary", f"Y{current_row}", round(stats['r_r_pct'], 6))
                    _set_cell(f, "Summary", f"Z{current_row}", stats['fail_level'])
                # Write percentage breakdown on second row
                elif file_idx == 1 and group_first_row is not None:
                    denom = stats['reproducibility'] ** 2 + stats['repeatability'] ** 2
                    v_pct = (stats['repeatability'] ** 2 / denom) if denom > 0 else 0
                    w_pct = (stats['reproducibility'] ** 2 / denom) if denom > 0 else 0
                    _set_cell(f, "Summary", f"V{current_row}", round(v_pct, 4))
                    _set_cell(f, "Summary", f"W{current_row}", round(w_pct, 4))
            else:
                row_data = [
                    fn, '', test_name, '', ll, hl, unit,
                    '', '', '', '', '', '',
                    '', '', '', '', '', '', '', '',
                    '', '', '', '', '', '',
                ]
                for c, val in enumerate(row_data, 1):
                    cl = excelize.column_number_to_name(c)
                    if val != '':
                        _set_cell(f, "Summary", f"{cl}{current_row}", val)

            current_row += 1

        group_end = current_row - 1
        group_info.append((group_start, group_end, stats['is_bad'], stats['r_r_pct']))

    last_data_row = current_row - 1

    # Apply borders to all data cells
    f.set_cell_style("Summary", f"A11", f"{last_col}{last_data_row}", data_style)
    for c_idx in range(1, SUMMARY_COLS + 1):
        cl = excelize.column_number_to_name(c_idx)
        f.set_cell_style("Summary", f"{cl}11", f"{cl}11", header_style)

    # Apply R&R% style to Y column per group (with red fill for Bad1)
    for gs, ge, is_bad, _ in group_info:
        rr_style = red_rr_pct_style if is_bad else rr_pct_style
        yy_cl = excelize.column_number_to_name(COL_RR_PCT)
        f.set_cell_style("Summary", f"{yy_cl}{gs}", f"{yy_cl}{gs}", rr_style)

    # Row grouping for Good groups (R&R% < 30%) - collapse by default
    for gs, ge, is_bad, _ in group_info:
        if not is_bad:
            for r in range(gs, ge + 1):
                f.set_row_outline_level("Summary", r, 1)
                f.set_row_visible("Summary", r, False)

    # Hide columns R-U (18-21) - intermediate CPK calculations
    for col_num in range(18, 22):
        cl = excelize.column_number_to_name(col_num)
        f.set_col_visible("Summary", cl, False)
        f.set_col_outline_level("Summary", cl, 1)

    # Freeze panes at E12 (after first 4 columns, after header row)
    f.set_panes("Summary", excelize.Panes(
        freeze=True, split=False, x_split=4, y_split=11, top_left_cell="E12",
    ))


# ── Per-File Sheet Builder ──

def build_per_file_sheets(f, file_datasets, all_test_cols):
    for ds in file_datasets:
        fn = ds['filename']
        sheet_name = fn[:31]
        f.new_sheet(sheet_name)

        df = ds['df']
        metadata = ds['metadata']

        test_cols = [c for c in all_test_cols if c in df.columns]
        site_col = 'Site #'
        if site_col not in df.columns:
            site_col = 'Site'
        serial_col = 'Serial #'
        if serial_col not in df.columns:
            serial_col = 'Serial'

        # Header info
        _set_cell(f, sheet_name, "A1", "RawData2")
        _set_cell(f, sheet_name, "B1", len(test_cols))
        _set_cell(f, sheet_name, "C1", min(len(df), 100))
        _set_cell(f, sheet_name, "D1", "Changchuan")
        _set_cell(f, sheet_name, "E1", "CTA8290D")

        tester_id = metadata.get('tester_id', '')
        program_name = metadata.get('program_name', '')
        start_time = metadata.get('start_time', '')
        _set_cell(f, sheet_name, "B3", f"LotID,{fn}")
        _set_cell(f, sheet_name, "B4", f"Tester ID,{tester_id}")
        _set_cell(f, sheet_name, "B5", "User,admin")
        _set_cell(f, sheet_name, "B6", f"Program Name,{program_name}")
        _set_cell(f, sheet_name, "B7", f"DateTime,{start_time}")

        test_units = metadata.get('units', {})
        test_mins = metadata.get('mins', {})
        test_maxs = metadata.get('maxs', {})

        # Column meta info rows (8-12)
        _set_cell(f, sheet_name, "A8", "Test Name")
        _set_cell(f, sheet_name, "A9", "Test Number")
        _set_cell(f, sheet_name, "A10", "Test Units")
        _set_cell(f, sheet_name, "A11", "Low Limits")
        _set_cell(f, sheet_name, "A12", "High Limits")
        _set_cell(f, sheet_name, "H8", "Data_Cnt")

        light_blue_style = f.new_style(excelize.Style(
            fill=excelize.Fill(type="pattern", color=["D6EAF8"], pattern=1),
            border=[excelize.Border(type=t, color="000000", style=1) for t in ("left", "top", "bottom", "right")],
        ))
        gray_style = f.new_style(excelize.Style(
            fill=excelize.Fill(type="pattern", color=["E0E0E0"], pattern=1),
            border=[excelize.Border(type=t, color="000000", style=1) for t in ("left", "top", "bottom", "right")],
        ))
        stats_border_style = f.new_style(excelize.Style(
            border=[excelize.Border(type=t, color="000000", style=1) for t in ("left", "top", "bottom", "right")],
            alignment=excelize.Alignment(horizontal="right"),
        ))
        stats_gray_style = f.new_style(excelize.Style(
            fill=excelize.Fill(type="pattern", color=["E0E0E0"], pattern=1),
            border=[excelize.Border(type=t, color="000000", style=1) for t in ("left", "top", "bottom", "right")],
            alignment=excelize.Alignment(horizontal="right"),
        ))

        # Apply light blue style to header area (rows 8-12, cols 8+)
        for r in range(8, 13):
            for c in range(8, len(test_cols) + 9):
                cl = excelize.column_number_to_name(c)
                f.set_cell_style(sheet_name, f"{cl}{r}", f"{cl}{r}", light_blue_style)
        f.set_cell_style(sheet_name, "H8", "H8", light_blue_style)

        for t_idx, col_name in enumerate(test_cols):
            cl = excelize.column_number_to_name(t_idx + 9)
            _set_cell(f, sheet_name, f"{cl}8", col_name)
            _set_cell(f, sheet_name, f"{cl}10", test_units.get(col_name, ''))
            _set_cell(f, sheet_name, f"{cl}11", test_mins.get(col_name, 0))
            _set_cell(f, sheet_name, f"{cl}12", test_maxs.get(col_name, 4))

        # Row 13: data column headers
        for c in range(2, 8):
            cl = excelize.column_number_to_name(c)
            f.set_cell_style(sheet_name, f"{cl}13", f"{cl}13", gray_style)
        for c in range(8, len(test_cols) + 9):
            cl = excelize.column_number_to_name(c)
            f.set_cell_style(sheet_name, f"{cl}13", f"{cl}13", gray_style)

        _set_cell(f, sheet_name, "B13", "Site #")
        _set_cell(f, sheet_name, "C13", "Serial #")
        _set_cell(f, sheet_name, "D13", "Bin")
        _set_cell(f, sheet_name, "E13", "XCoord")
        _set_cell(f, sheet_name, "F13", "YCoord")
        _set_cell(f, sheet_name, "G13", "Test Time")

        # Data rows (up to 100)
        data_rows = min(len(df), 100)
        has_site = site_col in df.columns
        has_serial = serial_col in df.columns

        for row_idx in range(data_rows):
            er = 14 + row_idx
            row_data = df.iloc[row_idx]

            _set_cell(f, sheet_name, f"B{er}", float(row_data[site_col]) if has_site else 1)
            _set_cell(f, sheet_name, f"C{er}", float(row_data[serial_col]) if has_serial else row_idx + 1)
            _set_cell(f, sheet_name, f"D{er}", 1)
            _set_cell(f, sheet_name, f"E{er}", -30000)
            _set_cell(f, sheet_name, f"F{er}", -30000)
            _set_cell(f, sheet_name, f"G{er}", -1)
            _set_cell(f, sheet_name, f"H{er}", len(df))

            for t_idx, col_name in enumerate(test_cols):
                try:
                    val = row_data[col_name]
                    if pd.notna(val):
                        cl = excelize.column_number_to_name(t_idx + 9)
                        _set_cell(f, sheet_name, f"{cl}{er}", float(val))
                except (ValueError, TypeError):
                    pass

        # Statistics rows (115-128)
        for r in range(115, 129):
            for c in range(2, 8):
                cl = excelize.column_number_to_name(c)
                f.set_cell_style(sheet_name, f"{cl}{r}", f"{cl}{r}", stats_gray_style)
            for c in range(8, len(test_cols) + 9):
                cl = excelize.column_number_to_name(c)
                f.set_cell_style(sheet_name, f"{cl}{r}", f"{cl}{r}", stats_border_style)

        stat_labels = [
            (115, "Low Limit"), (116, "High Limit"), (117, "Min"), (118, "Max"),
            (119, "Range"), (120, "Mean"), (121, "Std"), (122, "Mean-6*std"),
            (123, "Mean-3*std"), (124, "Mean+3*std"), (125, "Mean+6*std"),
            (126, "CPK-LowLimti"), (127, "CPK-HighLimit"), (128, "CPK"),
        ]
        for rn, lbl in stat_labels:
            _set_cell(f, sheet_name, f"A{rn}", lbl)

        for t_idx, col_name in enumerate(test_cols):
            cl = excelize.column_number_to_name(t_idx + 9)
            col_data = ensure_numeric(df, col_name).dropna()
            low_val = _safe_float(test_mins.get(col_name, 0), 0)
            high_val = _safe_float(test_maxs.get(col_name, 4), 4)

            _set_cell(f, sheet_name, f"{cl}115", low_val)
            _set_cell(f, sheet_name, f"{cl}116", high_val)

            if len(col_data) > 0:
                cmin = float(col_data.min())
                cmax = float(col_data.max())
                crange = cmax - cmin
                cmean = float(col_data.mean())
                cstd = float(col_data.std(ddof=1)) if len(col_data) > 1 else 0

                _set_cell(f, sheet_name, f"{cl}117", round(cmin, 6))
                _set_cell(f, sheet_name, f"{cl}118", round(cmax, 6))
                _set_cell(f, sheet_name, f"{cl}119", round(crange, 6))
                _set_cell(f, sheet_name, f"{cl}120", round(cmean, 6))
                _set_cell(f, sheet_name, f"{cl}121", round(cstd, 6))
                _set_cell(f, sheet_name, f"{cl}122", round(cmean - 6 * cstd, 6))
                _set_cell(f, sheet_name, f"{cl}123", round(cmean - 3 * cstd, 6))
                _set_cell(f, sheet_name, f"{cl}124", round(cmean + 3 * cstd, 6))
                _set_cell(f, sheet_name, f"{cl}125", round(cmean + 6 * cstd, 6))

                if cstd > 0:
                    cpk_l = (cmean - float(low_val)) / (3 * cstd)
                    cpk_h = (float(high_val) - cmean) / (3 * cstd)
                    _set_cell(f, sheet_name, f"{cl}126", round(cpk_l, 6))
                    _set_cell(f, sheet_name, f"{cl}127", round(cpk_h, 6))
                    _set_cell(f, sheet_name, f"{cl}128", round(min(cpk_l, cpk_h), 6))


# ── Complete Gage Summary Excel Builder (from old version) ──

def build_gage_summary_excel(file_datasets, ignore_no_limit=False):
    f = excelize.new_file()

    # Rename default sheet to Summary
    sheet_list = f.get_sheet_list()
    if sheet_list:
        f.set_sheet_name(sheet_list[0], "Summary")

    num_files = len(file_datasets)
    first_dataset = file_datasets[0]
    first_df = first_dataset['df']
    first_metadata = first_dataset['metadata']
    non_numeric_keywords = NON_NUMERIC_KEYWORDS

    # Determine column constants
    summary_headers = [
        'File Name', 'Tester ID', 'Test Name', 'Test#', 'LowLimit', 'HighLimit', 'Unit',
        'Mean', 'STD', 'Min', 'Max', 'CP', 'CPK',
        '', 'Mean', 'STD', '6*STD', 'Min CPK', 'Max CPK', 'Total CP', 'Total CPK',
        'Repeatibility', 'Reproducibility', 'R&R', 'R&R%', 'Fail Level', 'Comments'
    ]
    summary_header_count = len(summary_headers)

    COL_V = 22
    COL_W = 23
    COL_RR = 24
    COL_RR_PCT = 25
    COL_FAIL = 26
    COL_COMMENTS = 27

    # Pre-compute d2* value
    def _calc_d2(n):
        d2_map = {1: 1.0, 2: 1.41421, 3: 1.91155, 4: 2.23887, 5: 2.48124,
                   6: 2.67253, 7: 2.82981, 8: 2.96288, 9: 3.07794, 10: 3.17905,
                   11: 3.26909, 12: 3.35016, 13: 3.42378, 14: 3.49116, 15: 3.55333,
                   16: 3.61071, 17: 3.66422, 18: 3.71424, 19: 3.76118}
        if n >= 20:
            return 3.80537
        return d2_map.get(n, 1.0)

    # Cache last column letter for merge operations (must be before any usage)
    col_letter_27 = excelize.column_number_to_name(summary_header_count)

    # === STYLES ===
    # 现代专业配色（与 buyoff 统一）
    COLOR_HEADER_BG = "2C3E50"
    COLOR_HEADER_FONT = "FFFFFF"
    COLOR_DATA_BG = "F8F9FA"
    COLOR_ALT_ROW = "EDF2F7"
    COLOR_BORDER = "BDC3C7"
    COLOR_FONT_DARK = "2C3E50"
    COLOR_RED_BG = "F5B7B1"
    COLOR_GREEN_OK = "27AE60"

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

    # === WRITE SUMMARY SHEET HEADER INFO ===
    def _set_cell(sheet, cell, value):
        if isinstance(value, np.generic):
            value = value.item()
        f.set_cell_value(sheet, cell, value)

    # Title row
    _set_cell("Summary", "A1", f"Gage R&R Summary Report ({num_files} files)")
    f.set_cell_style("Summary", "A1", "A1", title_style)
    f.merge_cell("Summary", "A1", f"{col_letter_27}1")

    # Bad1 count with label
    _set_cell("Summary", "A3", "Failed Items (R&R% >= 30%):")
    f.set_cell_style("Summary", "A3", "A3", info_label_style)
    _set_cell("Summary", "B3", "")
    f.set_cell_style("Summary", "B3", "B3", info_value_style)

    # Warning text
    _set_cell("Summary", "C3", "HW Gage FAIL. These tests must be fixed before release. Must get manager's/supervisor's approval if it cannot be fixed. (R&R% >= 30.00 %)")
    f.set_cell_style("Summary", "C3", "C3", warning_style)
    f.merge_cell("Summary", "C3", f"{col_letter_27}3")

    # Info section
    _set_cell("Summary", "A7", "FileQuantity:")
    f.set_cell_style("Summary", "A7", "A7", info_label_style)
    _set_cell("Summary", "B7", num_files)
    f.set_cell_style("Summary", "B7", "B7", info_value_style)

    _set_cell("Summary", "A8", "d2*:")
    f.set_cell_style("Summary", "A8", "A8", info_label_style)
    _set_cell("Summary", "B8", _calc_d2(num_files))
    f.set_cell_style("Summary", "B8", "B8", info_value_style)

    _set_cell("Summary", "A9", "# of Sigma for R&R:")
    f.set_cell_style("Summary", "A9", "A9", info_label_style)
    _set_cell("Summary", "B9", 6)
    f.set_cell_style("Summary", "B9", "B9", info_value_style)

    # Cache last column letter for merge operations
    # Header row 11
    for col_idx, header in enumerate(summary_headers, 1):
        col_letter = excelize.column_number_to_name(col_idx)
        _set_cell("Summary", f"{col_letter}11", header)
        f.set_cell_style("Summary", f"{col_letter}11", f"{col_letter}11", header_style)

    # Hide rows 4-10
    for row in range(4, 11):
        f.set_row_visible("Summary", row, False)

    # Get test columns
    all_test_cols = []
    for col in first_df.columns:
        if ignore_no_limit:
            if col in first_metadata.get('mins', {}) and col in first_metadata.get('maxs', {}):
                min_str = first_metadata['mins'][col].strip()
                max_str = first_metadata['maxs'][col].strip()
                if min_str and max_str and min_str.lower() not in non_numeric_keywords and max_str.lower() not in non_numeric_keywords:
                    try:
                        float(min_str)
                        float(max_str)
                        all_test_cols.append(col)
                    except (ValueError, TypeError):
                        pass
        else:
            all_test_cols.append(col)

    current_row = 12
    has_fail_tests = False
    bad1_count = 0
    group_info = []

    for test_name in all_test_cols:
        test_values_by_file = {}
        test_units_by_file = {}
        test_mins_by_file = {}
        test_maxs_by_file = {}

        for file_info in file_datasets:
            fn = file_info['filename']
            df = file_info['df']
            metadata = file_info['metadata']

            test_mins_by_file[fn] = metadata.get('mins', {}).get(test_name, 0)
            test_maxs_by_file[fn] = metadata.get('maxs', {}).get(test_name, 4)
            test_units_by_file[fn] = metadata.get('units', {}).get(test_name, '')

            if test_name in df.columns:
                try:
                    vals = ensure_numeric(df, test_name).dropna().tolist()
                except Exception:
                    vals = []
                test_values_by_file[fn] = vals
            else:
                test_values_by_file[fn] = []

        repeatability_val = 0
        reproducibility_val = 0
        r_r_val = 0
        r_r_pct = 0
        global_mean = 0
        global_std = 0
        overall_cp = 0
        overall_cpk = 0
        tolerance = 0
        low_limit = 0
        high_limit = 0

        file_stats_cache = {}

        if test_values_by_file:
            all_arrays = []
            file_means_arr = np.empty(num_files)
            file_stds_arr = np.zeros(num_files)
            file_mins_arr = np.empty(num_files)
            file_maxs_arr = np.empty(num_files)

            for fi_idx, (fn, vals) in enumerate(test_values_by_file.items()):
                arr = np.array(vals, dtype=np.float64)
                all_arrays.append(arr)
                n = len(arr)
                if n > 0:
                    fm = arr.mean()
                    file_means_arr[fi_idx] = fm
                    if n > 1:
                        fs = arr.std(ddof=0)
                        file_stds_arr[fi_idx] = fs
                    file_stats_cache[fn] = (fm, fs, arr.min(), arr.max())

            all_arr = np.concatenate(all_arrays) if len(all_arrays) > 0 else np.array([])
            global_mean = all_arr.mean() if len(all_arr) > 0 else 0
            global_std = all_arr.std(ddof=0) if len(all_arr) > 0 else 0

            def _safe_float_or_none(val):
                if isinstance(val, (int, float)):
                    return val
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            low_limit = 0
            high_limit = 0
            tolerance = 0
            for fn in test_mins_by_file:
                low_val = _safe_float_or_none(test_mins_by_file.get(fn, 0))
                high_val = _safe_float_or_none(test_maxs_by_file.get(fn, 4))
                if low_val is not None and high_val is not None and high_val != low_val:
                    low_limit = low_val
                    high_limit = high_val
                    tolerance = high_limit - low_limit
                    break

            if global_std > 0 and tolerance > 0:
                overall_cp = tolerance / (6 * global_std)
                cpk_low = (global_mean - low_limit) / (3 * global_std)
                cpk_high = (high_limit - global_mean) / (3 * global_std)
                overall_cpk = min(cpk_low, cpk_high)

            num_sigma = 6
            sumsq_stds = np.sum(np.square(file_stds_arr))
            repeatability_val = num_sigma * (sumsq_stds / num_files) ** 0.5 if file_stds_arr.sum() > 0 else 0

            if len(all_arrays) > 0:
                mean_of_means = file_means_arr.mean()
                reproducibility_val = num_sigma * file_means_arr.std(ddof=0) if len(file_means_arr) > 1 else 0
            else:
                mean_of_means = 0
                reproducibility_val = 0

            r_r_val = (repeatability_val ** 2 + reproducibility_val ** 2) ** 0.5

            if tolerance > 0:
                r_r_pct = r_r_val / tolerance
            elif global_mean != 0:
                r_r_pct = r_r_val / abs(global_mean)
            else:
                r_r_pct = 0

        group_start_row = current_row
        group_first_data_row = None

        r_r_pct_display = r_r_pct * 100
        fail_level = 'Bad1' if r_r_pct_display >= 30 else ('Bad2' if r_r_pct_display >= 10 else 'Good')
        is_bad_group = (r_r_pct_display >= 30)
        if is_bad_group:
            has_fail_tests = True
            bad1_count += 1

        for file_idx, file_info in enumerate(file_datasets):
            fn = file_info['filename']
            vals = test_values_by_file.get(fn, [])
            low_l = _safe_float_or_none(test_mins_by_file.get(fn, 0)) or 0
            high_l = _safe_float_or_none(test_maxs_by_file.get(fn, 4)) or 4
            unit = test_units_by_file.get(fn, '')

            if vals:
                if group_first_data_row is None:
                    group_first_data_row = current_row

                stats = file_stats_cache.get(fn)
                if stats:
                    fm, fs, fmin, fmax = stats
                else:
                    fm = sum(vals) / len(vals)
                    fs = (sum((x - fm) ** 2 for x in vals) / len(vals)) ** 0.5 if len(vals) > 1 else 0
                    fmin = min(vals)
                    fmax = max(vals)

                cp = 0
                cpk = 0
                if fs > 0 and low_l != 0 and high_l != 4:
                    tol = high_l - low_l
                    cp = tol / (6 * fs) if tol > 0 else 0
                    cpk_low = (fm - low_l) / (3 * fs) if fs > 0 else 0
                    cpk_high = (high_l - fm) / (3 * fs) if fs > 0 else 0
                    cpk = min(cpk_low, cpk_high)

                row_data = [
                    fn, '', test_name, '', low_l, high_l, unit,
                    round(fm, 4), round(fs, 4), round(fmin, 4), round(fmax, 4),
                    round(cp, 4), round(cpk, 4),
                    '', '', '', '', '', '', '', '',
                    '', '', '', '', '', ''
                ]

                for col_idx, val in enumerate(row_data, 1):
                    col_letter = excelize.column_number_to_name(col_idx)
                    _set_cell("Summary", f"{col_letter}{current_row}", val)

                if current_row == group_first_data_row:
                    _set_cell("Summary", f"O{current_row}", round(global_mean, 4))
                    _set_cell("Summary", f"P{current_row}", round(global_std, 4))
                    _set_cell("Summary", f"Q{current_row}", round(6 * global_std, 4))
                    _set_cell("Summary", f"R{current_row}", round(overall_cpk, 4))
                    _set_cell("Summary", f"S{current_row}", round(overall_cpk, 4))
                    _set_cell("Summary", f"T{current_row}", round(overall_cp, 4))
                    _set_cell("Summary", f"U{current_row}", round(overall_cpk, 4))

                    v_col = excelize.column_number_to_name(COL_V)
                    w_col = excelize.column_number_to_name(COL_W)
                    rr_col = excelize.column_number_to_name(COL_RR)
                    rr_pct_col = excelize.column_number_to_name(COL_RR_PCT)
                    fail_col = excelize.column_number_to_name(COL_FAIL)

                    _set_cell("Summary", f"{v_col}{current_row}", round(repeatability_val, 4))
                    _set_cell("Summary", f"{w_col}{current_row}", round(reproducibility_val, 4))
                    _set_cell("Summary", f"{rr_col}{current_row}", round(r_r_val, 4))

                    if tolerance > 0:
                        _set_cell("Summary", f"{rr_pct_col}{current_row}", round(r_r_pct, 6))
                    else:
                        _set_cell("Summary", f"{rr_pct_col}{current_row}", 0)

                    _set_cell("Summary", f"{fail_col}{current_row}", fail_level)
                elif group_first_data_row is not None and file_idx == 1:
                    v_col = excelize.column_number_to_name(COL_V)
                    w_col = excelize.column_number_to_name(COL_W)
                    denom = reproducibility_val ** 2 + repeatability_val ** 2
                    v_pct = (repeatability_val ** 2 / denom) if denom > 0 else 0
                    w_pct = (reproducibility_val ** 2 / denom) if denom > 0 else 0
                    _set_cell("Summary", f"{v_col}{current_row}", round(v_pct, 4))
                    _set_cell("Summary", f"{w_col}{current_row}", round(w_pct, 4))
            else:
                row_data = [
                    fn, '', test_name, '', low_l, high_l, unit,
                    '', '', '', '',
                    '', '',
                    '', '', '', '', '', '', '', '',
                    '', '', '', '', '', ''
                ]
                for col_idx, val in enumerate(row_data, 1):
                    col_letter = excelize.column_number_to_name(col_idx)
                    _set_cell("Summary", f"{col_letter}{current_row}", val)

            current_row += 1

        group_end_row = current_row - 1
        group_info.append((group_start_row, group_end_row, is_bad_group))

    last_data_row = current_row - 1

    # Average row
    if num_files >= 2:
        repeatability_vals = []
        reproducibility_vals = []
        for test_idx in range(len(all_test_cols)):
            row_idx = 12 + test_idx * num_files + num_files - 1
            v_col = excelize.column_number_to_name(COL_V)
            w_col = excelize.column_number_to_name(COL_W)
            v_val = f.get_cell_value("Summary", f"{v_col}{row_idx}")
            w_val = f.get_cell_value("Summary", f"{w_col}{row_idx}")
            if v_val is not None:
                try:
                    repeatability_vals.append(float(v_val))
                except (ValueError, TypeError):
                    pass
            if w_val is not None:
                try:
                    reproducibility_vals.append(float(w_val))
                except (ValueError, TypeError):
                    pass

        avg_repeatability = sum(repeatability_vals) / len(repeatability_vals) if repeatability_vals else 0
        avg_reproducibility = sum(reproducibility_vals) / len(reproducibility_vals) if reproducibility_vals else 0

        _set_cell("Summary", "A" + str(current_row), "Average")
        v_col = excelize.column_number_to_name(COL_V)
        w_col = excelize.column_number_to_name(COL_W)
        _set_cell("Summary", f"{v_col}{current_row}", round(avg_repeatability, 4))
        _set_cell("Summary", f"{w_col}{current_row}", round(avg_reproducibility, 4))
        f.set_cell_style("Summary", f"A{current_row}", f"A{current_row}", thick_left_style)

    # Write Bad1 count to B3 with conditional styling
    f.set_cell_value("Summary", "B3", bad1_count)
    bad1_style = bad1_fail_style if bad1_count > 0 else bad1_ok_style
    f.set_cell_style("Summary", "B3", "B3", bad1_style)

    # === FORMATTING: Borders ===
    for row in range(11, last_data_row + 1):
        start_cell = f"A{row}"
        end_cell = f"{col_letter_27}{row}"
        f.set_cell_style("Summary", start_cell, end_cell, data_style)

    for group_start, group_end, is_bad in group_info:
        # Group borders
        col_last = excelize.column_number_to_name(summary_header_count)
        f.set_cell_style("Summary", f"A{group_start}", f"A{group_start}", thick_top_style)
        for col_num in range(2, summary_header_count):
            cl = excelize.column_number_to_name(col_num)
            f.set_cell_style("Summary", f"{cl}{group_start}", f"{cl}{group_start}", thick_top_mid_style)
        f.set_cell_style("Summary", f"{col_last}{group_start}", f"{col_last}{group_start}", thick_top_right_style)

        for row_idx in range(group_start + 1, group_end):
            f.set_cell_style("Summary", f"A{row_idx}", f"A{row_idx}", thick_left_style)
            for col_num in range(2, summary_header_count):
                cl = excelize.column_number_to_name(col_num)
                f.set_cell_style("Summary", f"{cl}{row_idx}", f"{cl}{row_idx}", data_style)
            f.set_cell_style("Summary", f"{col_last}{row_idx}", f"{col_last}{row_idx}", thick_right_style)

        f.set_cell_style("Summary", f"A{group_end}", f"A{group_end}", thick_bottom_style)
        for col_num in range(2, summary_header_count):
            cl = excelize.column_number_to_name(col_num)
            f.set_cell_style("Summary", f"{cl}{group_end}", f"{cl}{group_end}", thick_bottom_mid_style)
        f.set_cell_style("Summary", f"{col_last}{group_end}", f"{col_last}{group_end}", thick_bottom_right_style)

        # Merge Comments column
        comments_col = excelize.column_number_to_name(COL_COMMENTS)
        f.merge_cell("Summary", f"{comments_col}{group_start}", f"{comments_col}{group_end}")

        # Direct red fill on R&R% cell for bad groups (matching original behavior)
        if is_bad:
            rr_pct_col = excelize.column_number_to_name(COL_RR_PCT)
        # Apply R&R% style (red+percentage for Bad1, percentage-only for others)
        rr_pct_col_letter = excelize.column_number_to_name(COL_RR_PCT)
        rr_style = red_rr_pct_style if is_bad else r_r_pct_style
        f.set_cell_style("Summary", f"{rr_pct_col_letter}{group_start}", f"{rr_pct_col_letter}{group_start}", rr_style)

    # Row grouping: fold Good groups (R&R% < 30%)
    for group_start, group_end, is_bad in group_info:
        if not is_bad:
            for row in range(group_start, group_end + 1):
                f.set_row_outline_level("Summary", row, 1)
                f.set_row_visible("Summary", row, False)

    if has_fail_tests:
        f.set_cell_value("Summary", "A3", f"Failed Items (R&R% >= 30%):  {bad1_count}")
        f.set_cell_style("Summary", "A3", "A3", bad1_fail_style)

    # Hide columns R-U (18-21)
    for col_num in range(18, 22):
        cl = excelize.column_number_to_name(col_num)
        f.set_col_visible("Summary", cl, False)
        f.set_col_outline_level("Summary", cl, 1)

    # Freeze panes at E12
    f.set_panes("Summary", excelize.Panes(
        freeze=True,
        split=False,
        x_split=4,
        y_split=11,
        top_left_cell="E12",
    ))

    # Pre-create styles for individual file sheets
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

    # === INDIVIDUAL FILE SHEETS ===
    for file_info in file_datasets:
        filename = file_info['filename']
        df = file_info['df']
        metadata = file_info['metadata']

        sheet_name = filename[:31]
        f.new_sheet(sheet_name)

        tester_id = metadata.get('tester_id', '')
        program_name = metadata.get('program_name', '')
        start_time = metadata.get('start_time', '')

        # Header rows (1-7)
        _set_cell(sheet_name, "A1", "RawData2")
        _set_cell(sheet_name, "B1", len(df.columns))
        _set_cell(sheet_name, "C1", min(len(df), 100))
        _set_cell(sheet_name, "D1", "Changchuan")
        _set_cell(sheet_name, "E1", "CTA8290D")

        _set_cell(sheet_name, "B3", f"LotID,{filename}")
        _set_cell(sheet_name, "B4", f"Tester ID,{tester_id}")
        _set_cell(sheet_name, "B5", "User,admin")
        _set_cell(sheet_name, "B6", f"Program Name,{program_name}")
        _set_cell(sheet_name, "B7", f"DateTime,{start_time}")

        # Determine columns for this sheet
        data_header = list(df.columns)
        test_units = metadata.get('units', {})
        test_mins = metadata.get('mins', {})
        test_maxs = metadata.get('maxs', {})

        if ignore_no_limit:
            data_header = [col for col in data_header
                          if col in test_mins and col in test_maxs
                          and test_mins[col].strip() and test_maxs[col].strip()
                          and test_mins[col].strip().lower() not in non_numeric_keywords
                          and test_maxs[col].strip().lower() not in non_numeric_keywords]

        # Column A styles
        _set_cell(sheet_name, "A8", "Test Name")
        _set_cell(sheet_name, "A9", "Test Number")
        _set_cell(sheet_name, "A10", "Test Units")
        _set_cell(sheet_name, "A11", "Low Limits")
        _set_cell(sheet_name, "A12", "High Limits")
        _set_cell(sheet_name, "H8", "Data_Cnt")

        for row in range(8, 13):
            for col in range(8, len(data_header) + 9):
                cl = excelize.column_number_to_name(col)
                f.set_cell_style(sheet_name, f"{cl}{row}", f"{cl}{row}", light_blue_style)
        f.set_cell_style(sheet_name, "H8", "H8", light_blue_style)

        # Write test item headers (columns 9+)
        cl_h = excelize.column_number_to_name(8)
        for test_idx, col_name in enumerate(data_header):
            col_letter = excelize.column_number_to_name(test_idx + 9)
            _set_cell(sheet_name, f"{col_letter}8", col_name)
            f.set_cell_value(sheet_name, f"{col_letter}9", "")
            _set_cell(sheet_name, f"{col_letter}10", test_units.get(col_name, ''))
            _set_cell(sheet_name, f"{col_letter}11", test_mins.get(col_name, 0))
            _set_cell(sheet_name, f"{col_letter}12", test_maxs.get(col_name, 4))

        # Data header row 13 (gray fill)
        for col in range(2, 8):
            cl = excelize.column_number_to_name(col)
            f.set_cell_style(sheet_name, f"{cl}13", f"{cl}13", gray_style)
        for col in range(8, len(data_header) + 9):
            cl = excelize.column_number_to_name(col)
            f.set_cell_style(sheet_name, f"{cl}13", f"{cl}13", gray_style)

        _set_cell(sheet_name, "B13", "Site #")
        _set_cell(sheet_name, "C13", "Serial #")
        _set_cell(sheet_name, "D13", "Bin")
        _set_cell(sheet_name, "E13", "XCoord")
        _set_cell(sheet_name, "F13", "YCoord")
        _set_cell(sheet_name, "G13", "Test Time")

        # Write data rows (up to 100)
        data_start_row = 14
        data_rows_to_write = min(len(df), 100)

        site_col = 'Site'
        serial_col = 'Serial'
        bin_col = 'Bin'
        xcol = 'XCoord'
        ycol = 'YCoord'

        if 'Site #' in df.columns:
            site_col = 'Site #'
        if 'Serial #' in df.columns:
            serial_col = 'Serial #'

        has_site = site_col in df.columns
        has_serial = serial_col in df.columns
        has_bin = bin_col in df.columns
        has_xcol = xcol in df.columns
        has_ycol = ycol in df.columns

        for row_idx in range(data_rows_to_write):
            excel_row = data_start_row + row_idx
            row_data = df.iloc[row_idx]

            _set_cell(sheet_name, f"B{excel_row}", float(row_data[site_col]) if has_site else 1)
            _set_cell(sheet_name, f"C{excel_row}", float(row_data[serial_col]) if has_serial else (row_idx + 1))
            _set_cell(sheet_name, f"D{excel_row}", float(row_data[bin_col]) if has_bin else 1)
            _set_cell(sheet_name, f"E{excel_row}", float(row_data[xcol]) if has_xcol else -30000)
            _set_cell(sheet_name, f"F{excel_row}", float(row_data[ycol]) if has_ycol else -30000)
            _set_cell(sheet_name, f"G{excel_row}", -1)
            _set_cell(sheet_name, f"H{excel_row}", len(df))

            for test_idx, col_name in enumerate(data_header):
                try:
                    val = row_data[col_name]
                    if pd.notna(val):
                        col_letter = excelize.column_number_to_name(test_idx + 9)
                        _set_cell(sheet_name, f"{col_letter}{excel_row}", float(val))
                except (ValueError, TypeError):
                    pass

        last_data_row_excel = data_start_row + data_rows_to_write - 1

        # Pre-calculated statistics rows (115-128) instead of formulas

        for row in range(115, 129):
            for col in range(2, 8):
                cl = excelize.column_number_to_name(col)
                f.set_cell_style(sheet_name, f"{cl}{row}", f"{cl}{row}", stats_gray_style)
            for col in range(8, len(data_header) + 9):
                cl = excelize.column_number_to_name(col)
                f.set_cell_style(sheet_name, f"{cl}{row}", f"{cl}{row}", stats_border_style)

        stat_labels = [
            (115, "Low Limit"), (116, "High Limit"), (117, "Min"), (118, "Max"),
            (119, "Range"), (120, "Mean"), (121, "Std"), (122, "Mean-6*std"),
            (123, "Mean-3*std"), (124, "Mean+3*std"), (125, "Mean+6*std"),
            (126, "CPK-LowLimti"), (127, "CPK-HighLimit"), (128, "CPK"),
        ]
        for row_num, label in stat_labels:
            _set_cell(sheet_name, f"A{row_num}", label)

        # Pre-calculate statistics for each test column
        for test_idx, col_name in enumerate(data_header):
            col_letter = excelize.column_number_to_name(test_idx + 9)
            col_data = ensure_numeric(df, col_name).dropna()

            low_val = test_mins.get(col_name, 0)
            high_val = test_maxs.get(col_name, 4)

            # Limits (rows 115-116) — direct values
            _set_cell(sheet_name, f"{col_letter}115", low_val)
            _set_cell(sheet_name, f"{col_letter}116", high_val)

            if len(col_data) > 0:
                col_min = float(col_data.min())
                col_max = float(col_data.max())
                col_range = col_max - col_min
                col_mean = float(col_data.mean())
                col_std = float(col_data.std(ddof=1)) if len(col_data) > 1 else 0.0

                _set_cell(sheet_name, f"{col_letter}117", round(col_min, 6))
                _set_cell(sheet_name, f"{col_letter}118", round(col_max, 6))
                _set_cell(sheet_name, f"{col_letter}119", round(col_range, 6))
                _set_cell(sheet_name, f"{col_letter}120", round(col_mean, 6))
                _set_cell(sheet_name, f"{col_letter}121", round(col_std, 6))
                _set_cell(sheet_name, f"{col_letter}122", round(col_mean - 6 * col_std, 6))
                _set_cell(sheet_name, f"{col_letter}123", round(col_mean - 3 * col_std, 6))
                _set_cell(sheet_name, f"{col_letter}124", round(col_mean + 3 * col_std, 6))
                _set_cell(sheet_name, f"{col_letter}125", round(col_mean + 6 * col_std, 6))

                # CPK calculations
                if col_std > 0:
                    try:
                        low_float = float(low_val) if low_val not in ('', None) and str(low_val).strip().lower() not in non_numeric_keywords else None
                    except (ValueError, TypeError):
                        low_float = None
                    try:
                        high_float = float(high_val) if high_val not in ('', None) and str(high_val).strip().lower() not in non_numeric_keywords else None
                    except (ValueError, TypeError):
                        high_float = None

                    if low_float is not None:
                        cpk_low = abs(col_mean - low_float) / (3 * col_std)
                        _set_cell(sheet_name, f"{col_letter}126", round(cpk_low, 6))
                    if high_float is not None:
                        cpk_high = abs(col_mean - high_float) / (3 * col_std)
                        _set_cell(sheet_name, f"{col_letter}127", round(cpk_high, 6))
                    if low_float is not None and high_float is not None:
                        cpk = min(abs(col_mean - low_float), abs(col_mean - high_float)) / (3 * col_std)
                        _set_cell(sheet_name, f"{col_letter}128", round(cpk, 6))

        # Row group for data rows (> 6), default collapsed
        if data_rows_to_write > 6:
            group_start = data_start_row + 3
            group_end = last_data_row_excel - 3
            for row in range(group_start, group_end + 1):
                f.set_row_outline_level(sheet_name, row, 1)
                f.set_row_visible(sheet_name, row, False)

    # Save to bytes
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        tmp_path = tmp.name

    f.save_as(tmp_path)
    f.close()

    with open(tmp_path, 'rb') as fh:
        data = fh.read()

    os.unlink(tmp_path)
    return data

