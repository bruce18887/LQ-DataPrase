"""Excel layout builders for Gage R&R reports."""

import numpy as np
import pandas as pd
import excelize
from apps.analysis.services.statistics import ensure_numeric
from apps.export.excelize_helpers import (
    make_header_style, make_data_style, make_title_style,
    COLOR_BORDER, COLOR_FONT_DARK, COLOR_DATA_BG, COLOR_RED_BG,
)
from apps.gage.services.rr_analysis import _calc_d2, SUMMARY_COLS, COL_RR_PCT

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

    # Info section
    if bad1_count > 0:
        _set_cell(f, "Summary", "A3", f"Failed Items (R&R% >= 30%):  {bad1_count}")
        f.set_cell_style("Summary", "A3", "A3", bad1_fail_style)
    else:
        _set_cell(f, "Summary", "A3", "Failed Items (R&R% >= 30%):")
        f.set_cell_style("Summary", "A3", "A3", info_label_style)
    _set_cell(f, "Summary", "B3", bad1_count)
    f.set_cell_style("Summary", "B3", "B3", bad1_fail_style if bad1_count > 0 else bad1_ok_style)

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

    # Apply borders
    f.set_cell_style("Summary", f"A11", f"{last_col}{last_data_row}", data_style)
    for c_idx in range(1, SUMMARY_COLS + 1):
        cl = excelize.column_number_to_name(c_idx)
        f.set_cell_style("Summary", f"{cl}11", f"{cl}11", header_style)

    # Apply R&R% style to Y column per group
    for gs, ge, is_bad, _ in group_info:
        rr_style = red_rr_pct_style if is_bad else rr_pct_style
        yy_cl = excelize.column_number_to_name(COL_RR_PCT)
        f.set_cell_style("Summary", f"{yy_cl}{gs}", f"{yy_cl}{gs}", rr_style)

    # Row grouping for Good groups (R&R% < 30%)
    for gs, ge, is_bad, _ in group_info:
        if not is_bad:
            for r in range(gs, ge + 1):
                f.set_row_outline_level("Summary", r, 1)
                f.set_row_visible("Summary", r, False)

    # Hide columns R-U (18-21)
    for col_num in range(18, 22):
        cl = excelize.column_number_to_name(col_num)
        f.set_col_visible("Summary", cl, False)
        f.set_col_outline_level("Summary", cl, 1)

    # Freeze panes
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
            low_val = test_mins.get(col_name, 0)
            high_val = test_maxs.get(col_name, 4)

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
