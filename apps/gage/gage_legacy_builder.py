"""Legacy monolithic Gage R&R summary Excel builder.

`build_gage_summary_excel` 负责编排：写 Summary 工作表（跨文件对比 + R&R）
并逐个写文件工作表。样式与单文件版式已拆到 `gage_styles` / `gage_file_sheet`，
本模块只保留统计与布局编排逻辑。
"""

import numpy as np
import excelize
import tempfile
import os
from apps.analysis.services.statistics import ensure_numeric
from apps.common.constants import NON_NUMERIC_KEYWORDS
from apps.datafiles.parsers.base import SYSTEM_COLUMNS
from apps.gage.gage_file_sheet import write_file_sheet
from apps.gage.gage_styles import create_summary_styles, create_file_sheet_styles
from apps.export.excel_theme import (
    add_threshold_verdict_rules, autofit_columns, set_formula, enable_full_recalc,
)

# R&R% 分档：≥ 30% = Bad1（红），≥ 10% = Bad2（橙）。
# 同一组阈值既决定 Fail Level / 分组折叠，也是 R&R% 列条件格式的分档。
RR_PCT_BAD1 = 0.30
RR_PCT_BAD2 = 0.10


def _safe_float_or_none(val):
    """Parse a spec-limit cell into float, or None when missing/non-numeric.

    Returning None (never a magic 0/4) is what lets the caller distinguish a
    legitimate limit of 0 or 4 from an absent one (defect #3).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


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
    (header_style, title_style, info_label_style, info_value_style,
     warning_style, data_style, thick_top_style, thick_top_mid_style,
     thick_top_right_style, thick_left_style, thick_right_style,
     thick_bottom_style, thick_bottom_mid_style, thick_bottom_right_style,
     r_r_pct_style, bad1_ok_style,
     bad1_fail_style) = create_summary_styles(f)

    # === WRITE SUMMARY SHEET HEADER INFO ===
    def _set_cell(sheet, cell, value):
        if isinstance(value, np.generic):
            value = value.item()
        # 空串会被写成**文本**单元格（t="s"）。Excel 里文本恒大于任何数值，
        # 所以数值型条件格式（如 R&R% >= 30%）会把空白格也判中 → 整列标红。
        # 留真空格才是正确的「没有值」表示。
        if value is None or value == '':
            return
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

    # Build the list of test columns (defect #7): system columns (Serial_No /
    # QR_Code / Start_T / Dut_Pass / SW_Bin …) and non-numeric columns are
    # ALWAYS excluded regardless of ignore_no_limit; ignore_no_limit only
    # decides whether to further drop items without a valid numeric limit.
    format_type = first_metadata.get('format', '')
    system_cols = set(SYSTEM_COLUMNS.get(format_type, []))

    def _col_has_numeric(col):
        for ds in file_datasets:
            dfx = ds['df']
            if col in dfx.columns:
                try:
                    if len(ensure_numeric(dfx, col).dropna()) > 0:
                        return True
                except Exception:
                    pass
        return False

    all_test_cols = []
    for col in first_df.columns:
        if col in system_cols:
            continue
        if not _col_has_numeric(col):
            continue
        if ignore_no_limit:
            min_raw = first_metadata.get('mins', {}).get(col)
            max_raw = first_metadata.get('maxs', {}).get(col)
            if min_raw is None or max_raw is None:
                continue
            min_str = str(min_raw).strip()
            max_str = str(max_raw).strip()
            if not min_str or not max_str:
                continue
            if min_str.lower() in non_numeric_keywords or max_str.lower() in non_numeric_keywords:
                continue
            try:
                float(min_str)
                float(max_str)
            except (ValueError, TypeError):
                continue
        all_test_cols.append(col)

    current_row = 12
    has_fail_tests = False
    bad1_count = 0
    group_info = []
    # Per-test 6σ values kept in memory so the Average row is computed from
    # these arrays, never by reading cells back (defect #6).
    repeatability_series = []
    reproducibility_series = []

    for test_name in all_test_cols:
        test_values_by_file = {}
        test_units_by_file = {}
        test_mins_by_file = {}
        test_maxs_by_file = {}

        for file_info in file_datasets:
            fn = file_info['filename']
            df = file_info['df']
            metadata = file_info['metadata']

            # Missing limit stays None (never magic 0/4) — defect #3.
            test_mins_by_file[fn] = metadata.get('mins', {}).get(test_name)
            test_maxs_by_file[fn] = metadata.get('maxs', {}).get(test_name)
            test_units_by_file[fn] = metadata.get('units', {}).get(test_name, '')

            if test_name in df.columns:
                try:
                    vals = ensure_numeric(df, test_name).dropna().tolist()
                except Exception:
                    vals = []
                test_values_by_file[fn] = vals
            else:
                test_values_by_file[fn] = []

        # ── Per-file statistics, computed once and shared by every consumer
        # (per-file row, Min/Max CPK, group stats) so they cannot diverge.
        # `fs` is always initialized inside the n>0 branch (defect #2): a
        # single-value file gets std 0.0 instead of inheriting the previous
        # test item's std or raising UnboundLocalError.
        per_file = []
        for file_info in file_datasets:
            fn = file_info['filename']
            vals = test_values_by_file.get(fn, [])
            low_l = _safe_float_or_none(test_mins_by_file.get(fn))
            high_l = _safe_float_or_none(test_maxs_by_file.get(fn))
            unit = test_units_by_file.get(fn, '')
            arr = np.array(vals, dtype=np.float64) if vals else np.array([], dtype=np.float64)
            n = len(arr)
            entry = {'fn': fn, 'vals': vals, 'low_l': low_l, 'high_l': high_l,
                     'unit': unit, 'has_data': n > 0, 'mean': None, 'std': None,
                     'min': None, 'max': None, 'cp': None, 'cpk': None}
            if n > 0:
                fm = float(arr.mean())
                fs = float(arr.std(ddof=0)) if n > 1 else 0.0
                entry['mean'] = fm
                entry['std'] = fs
                entry['min'] = float(arr.min())
                entry['max'] = float(arr.max())
                # Legit limits of 0 or 4 are honoured; only None means missing
                # (defect #3 — no `!= 0` / `!= 4` sentinel).
                if fs > 0 and low_l is not None and high_l is not None:
                    tol_f = high_l - low_l
                    entry['cp'] = tol_f / (6 * fs) if tol_f > 0 else 0.0
                    cpk_low_f = (fm - low_l) / (3 * fs)
                    cpk_high_f = (high_l - fm) / (3 * fs)
                    entry['cpk'] = min(cpk_low_f, cpk_high_f)
            per_file.append(entry)

        # ── Group statistics over files that actually have data (defect #1):
        # an empty file contributes nothing instead of a 0.0 / uninitialized
        # garbage mean that would pollute reproducibility.
        all_values = []
        file_means_list = []
        file_stds_list = []
        for entry in per_file:
            if entry['has_data']:
                all_values.extend(entry['vals'])
                file_means_list.append(entry['mean'])
                file_stds_list.append(entry['std'])

        all_arr = np.array(all_values, dtype=np.float64) if all_values else np.array([], dtype=np.float64)
        global_mean = float(all_arr.mean()) if len(all_arr) > 0 else 0.0
        global_std = float(all_arr.std(ddof=0)) if len(all_arr) > 0 else 0.0

        # Tolerance from the first file with valid, non-equal numeric limits.
        low_limit = None
        high_limit = None
        tolerance = 0.0
        tol_idx = None
        for idx, entry in enumerate(per_file):
            lv, hv = entry['low_l'], entry['high_l']
            if lv is not None and hv is not None and hv != lv:
                low_limit, high_limit = lv, hv
                tolerance = hv - lv
                tol_idx = idx
                break

        overall_cp = 0.0
        overall_cpk = 0.0
        if global_std > 0 and tolerance > 0 and low_limit is not None and high_limit is not None:
            overall_cp = tolerance / (6 * global_std)
            cpk_low = (global_mean - low_limit) / (3 * global_std)
            cpk_high = (high_limit - global_mean) / (3 * global_std)
            overall_cpk = min(cpk_low, cpk_high)

        num_sigma = 6
        means_arr = np.array(file_means_list, dtype=np.float64) if file_means_list else np.array([], dtype=np.float64)
        stds_arr = np.array(file_stds_list, dtype=np.float64) if file_stds_list else np.array([], dtype=np.float64)

        # Repeatability keeps the existing 6*sqrt(sum(std^2)/num_files) formula.
        if len(stds_arr) > 0 and float(np.sum(stds_arr)) > 0:
            repeatability_val = num_sigma * (float(np.sum(np.square(stds_arr))) / num_files) ** 0.5
        else:
            repeatability_val = 0.0

        # Reproducibility = 6*std(file_means) over data-bearing files only.
        if len(means_arr) > 1:
            reproducibility_val = num_sigma * float(means_arr.std(ddof=0))
        else:
            reproducibility_val = 0.0

        r_r_val = (repeatability_val ** 2 + reproducibility_val ** 2) ** 0.5

        # R&R% and Fail Level share one source (defect #5). Missing tolerance
        # → both N/A, and the item is NOT counted as a Bad1 failure. No silent
        # fallback to r_r/|global_mean| (different dimension).
        r_r_pct = (r_r_val / tolerance) if tolerance > 0 else None

        repeatability_series.append(repeatability_val)
        reproducibility_series.append(reproducibility_val)

        group_start_row = current_row
        # 组的行范围（每文件一行）与「公差来源行」，供 V/W/X/Y 公式引用。
        group_last_row = group_start_row + len(per_file) - 1
        tol_row = group_start_row + tol_idx if tol_idx is not None else None
        group_first_data_row = None

        if r_r_pct is None:
            fail_level = 'N/A'
            is_bad_group = False
        else:
            fail_level = ('Bad1' if r_r_pct >= RR_PCT_BAD1
                          else 'Bad2' if r_r_pct >= RR_PCT_BAD2 else 'Good')
            is_bad_group = r_r_pct >= RR_PCT_BAD1
        if is_bad_group:
            has_fail_tests = True
            bad1_count += 1

        # Min/Max CPK across files with a valid CPK (defect #4 — not overall_cpk).
        valid_cpks = [e['cpk'] for e in per_file if e['cpk'] is not None]
        min_cpk = min(valid_cpks) if valid_cpks else 0.0
        max_cpk = max(valid_cpks) if valid_cpks else 0.0

        for file_idx, entry in enumerate(per_file):
            fn = entry['fn']
            low_l = entry['low_l']
            high_l = entry['high_l']
            unit = entry['unit']
            low_disp = low_l if low_l is not None else 'N/A'
            high_disp = high_l if high_l is not None else 'N/A'

            if entry['has_data']:
                if group_first_data_row is None:
                    group_first_data_row = current_row

                fm = entry['mean']
                fs = entry['std']
                fmin = entry['min']
                fmax = entry['max']
                cp = entry['cp'] if entry['cp'] is not None else 0.0
                cpk = entry['cpk'] if entry['cpk'] is not None else 0.0

                row_data = [
                    fn, '', test_name, '', low_disp, high_disp, unit,
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
                    _set_cell("Summary", f"R{current_row}", round(min_cpk, 4))
                    _set_cell("Summary", f"S{current_row}", round(max_cpk, 4))
                    _set_cell("Summary", f"T{current_row}", round(overall_cp, 4))
                    _set_cell("Summary", f"U{current_row}", round(overall_cpk, 4))

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
                    set_formula(f, "Summary", f"{v_col}{r}",
                                f"=ROUND(SQRT(SUMSQ(I{group_start_row}:I{group_last_row})/B7)*6,4)")
                    # 用 `STDEVP`（无点号）而非 `STDEV.P`：带点号的函数名是 Excel 2010 才加的，
                    # 部分查看器认不出 —— `STDEV.P` 报错后被 IFERROR 悄悄吞成 0，整列 Reproducibility 全 0。
                    # 单文件时 STDEVP 本身会 #DIV/0!，用 `IF(COUNT<2,…)` 显式给 0（与 Python 口径一致），
                    # 不用 IFERROR —— 免得再出现"报错被吞成 0"的静默失败。
                    set_formula(f, "Summary", f"{w_col}{r}",
                                f"=ROUND(IF(COUNT(H{group_start_row}:H{group_last_row})<2,0,"
                                f"STDEVP(H{group_start_row}:H{group_last_row})*6),4)")
                    set_formula(f, "Summary", f"{rr_col}{r}",
                                f"=ROUND(SQRT({v_col}{r}*{v_col}{r}+{w_col}{r}*{w_col}{r}),4)")

                    if tol_row is not None:
                        set_formula(f, "Summary", f"{rr_pct_col}{r}",
                                    f"=ROUND({rr_col}{r}/(F{tol_row}-E{tol_row}),6)")
                    else:
                        _set_cell("Summary", f"{rr_pct_col}{r}", 'N/A')

                    _set_cell("Summary", f"{fail_col}{current_row}", fail_level)
            else:
                row_data = [
                    fn, '', test_name, '', low_disp, high_disp, unit,
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

    # Average row — computed from the in-memory 6σ series (defect #6), never
    # by reading cells back (which used to pick up variance-fraction values and
    # silently average only part of the tests when num_files > 2).
    if num_files >= 2:
        avg_repeatability = (sum(repeatability_series) / len(repeatability_series)) if repeatability_series else 0
        avg_reproducibility = (sum(reproducibility_series) / len(reproducibility_series)) if reproducibility_series else 0

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
    # 从第 12 行起（数据首行）。第 11 行是表头，必须留在上面的 header_style，
    # 否则整片 data_style 会把刚写好的深色表头带覆盖成浅灰。
    for row in range(12, last_data_row + 1):
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

        # R&R% 格统一用基样式；Bad1 的红色高亮由 Y 列上的条件格式统一处理。
        # （条件格式是叠加的，不像 set_cell_style 那样把格子的底色与边框替换掉。）
        rr_pct_col_letter = excelize.column_number_to_name(COL_RR_PCT)
        f.set_cell_style("Summary", f"{rr_pct_col_letter}{group_start}",
                         f"{rr_pct_col_letter}{group_start}", r_r_pct_style)

    # R&R% 分档上色：Bad1 红、Bad2 橙。一条规则覆盖整条 R&R% 数据区，
    # 改值后颜色自动跟随；空白格不参与（见 _set_cell 的空串说明）。
    rr_pct_col_letter = excelize.column_number_to_name(COL_RR_PCT)
    add_threshold_verdict_rules(
        f, "Summary", f"{rr_pct_col_letter}12:{rr_pct_col_letter}{last_data_row}",
        [(RR_PCT_BAD1, 'fail'), (RR_PCT_BAD2, 'warn')])

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

    # 列宽按显示内容自适应（表头 "Repeatability"/"Reproducibility" 等否则会被截断）。
    # 从表头行（11）起算，免得上面那行 "Failed Items (...)" 标签把 A 列撑宽。
    autofit_columns(f, "Summary", min_row=11)

    # Freeze panes at E12
    f.set_panes("Summary", excelize.Panes(
        freeze=True,
        split=False,
        x_split=4,
        y_split=11,
        top_left_cell="E12",
    ))

    # V/W/X/Y 是公式，Excel 打开时须重算（否则在重算前显示空白）。
    enable_full_recalc(f)

    # Pre-create styles for individual file sheets
    file_styles = create_file_sheet_styles(f)

    # === INDIVIDUAL FILE SHEETS ===
    for file_info in file_datasets:
        write_file_sheet(f, file_info, ignore_no_limit, non_numeric_keywords,
                         file_styles, _set_cell)

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
