"""单个文件工作表（RawData 版式）的写出逻辑。

从 `gage_legacy_builder` 逐字迁出：表头区、测试项列头、数据行（上限 100）、
预计算统计行（115–128）与数据行分组折叠。布局与数值均未改动。
"""
import pandas as pd
import excelize

from apps.analysis.services.statistics import ensure_numeric
from apps.analysis.services.statistics.helpers import get_site_column


def write_file_sheet(f, file_info, ignore_no_limit, non_numeric_keywords,
                     file_styles, set_cell):
    """写一个文件的独立工作表。

    ``file_styles`` 为 ``gage_styles.create_file_sheet_styles`` 的返回值；
    ``set_cell(sheet, cell, value)`` 是 builder 传入的单元格写入闭包。
    """
    filename = file_info['filename']
    df = file_info['df']
    metadata = file_info['metadata']
    (light_blue_style, gray_style,
     stats_gray_style, stats_border_style) = file_styles

    # 工作表名由视图统一生成（stem + 工位，唯一且 ≤31 字符）；
    # 同一文件可分配到多个工位槽位，不能再简单用 filename[:31]（会重名）。
    sheet_name = file_info.get('sheet_name') or filename[:31]
    f.new_sheet(sheet_name)

    tester_id = metadata.get('tester_id', '')
    program_name = metadata.get('program_name', '')
    start_time = metadata.get('start_time', '')

    # Header rows (1-7)
    set_cell(sheet_name, "A1", "RawData2")
    set_cell(sheet_name, "B1", len(df.columns))
    set_cell(sheet_name, "C1", min(len(df), 100))
    set_cell(sheet_name, "D1", "Changchuan")
    set_cell(sheet_name, "E1", "CTA8290D")

    set_cell(sheet_name, "B3", f"LotID,{filename}")
    set_cell(sheet_name, "B4", f"Tester ID,{tester_id}")
    set_cell(sheet_name, "B5", "User,admin")
    set_cell(sheet_name, "B6", f"Program Name,{program_name}")
    set_cell(sheet_name, "B7", f"DateTime,{start_time}")

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
    set_cell(sheet_name, "A8", "Test Name")
    set_cell(sheet_name, "A9", "Test Number")
    set_cell(sheet_name, "A10", "Test Units")
    set_cell(sheet_name, "A11", "Low Limits")
    set_cell(sheet_name, "A12", "High Limits")
    set_cell(sheet_name, "H8", "Data_Cnt")

    for row in range(8, 13):
        for col in range(8, len(data_header) + 9):
            cl = excelize.column_number_to_name(col)
            f.set_cell_style(sheet_name, f"{cl}{row}", f"{cl}{row}", light_blue_style)
    f.set_cell_style(sheet_name, "H8", "H8", light_blue_style)

    # Write test item headers (columns 9+)
    cl_h = excelize.column_number_to_name(8)
    for test_idx, col_name in enumerate(data_header):
        col_letter = excelize.column_number_to_name(test_idx + 9)
        set_cell(sheet_name, f"{col_letter}8", col_name)
        f.set_cell_value(sheet_name, f"{col_letter}9", "")
        set_cell(sheet_name, f"{col_letter}10", test_units.get(col_name, ''))
        low_raw = test_mins.get(col_name)
        high_raw = test_maxs.get(col_name)
        set_cell(sheet_name, f"{col_letter}11", low_raw if low_raw not in (None, '') else 'N/A')
        set_cell(sheet_name, f"{col_letter}12", high_raw if high_raw not in (None, '') else 'N/A')

    # Data header row 13 (gray fill)
    for col in range(2, 8):
        cl = excelize.column_number_to_name(col)
        f.set_cell_style(sheet_name, f"{cl}13", f"{cl}13", gray_style)
    for col in range(8, len(data_header) + 9):
        cl = excelize.column_number_to_name(col)
        f.set_cell_style(sheet_name, f"{cl}13", f"{cl}13", gray_style)

    set_cell(sheet_name, "B13", "Site #")
    set_cell(sheet_name, "C13", "Serial #")
    set_cell(sheet_name, "D13", "Bin")
    set_cell(sheet_name, "E13", "XCoord")
    set_cell(sheet_name, "F13", "YCoord")
    set_cell(sheet_name, "G13", "Test Time")

    # Write data rows (up to 100)
    data_start_row = 14
    data_rows_to_write = min(len(df), 100)

    # 工位列名随格式不同（CTA Site_No / ETS88 Site # / STS8200 SITE_NUM）：
    # 统一走共享探测函数，避免只认 'Site'/'Site #' 把 CTA/STS 工位写成常量 1。
    site_col = get_site_column(df)
    serial_col = 'Serial'
    bin_col = 'Bin'
    xcol = 'XCoord'
    ycol = 'YCoord'

    if 'Serial #' in df.columns:
        serial_col = 'Serial #'

    has_site = site_col is not None
    has_serial = serial_col in df.columns
    has_bin = bin_col in df.columns
    has_xcol = xcol in df.columns
    has_ycol = ycol in df.columns

    for row_idx in range(data_rows_to_write):
        excel_row = data_start_row + row_idx
        row_data = df.iloc[row_idx]

        set_cell(sheet_name, f"B{excel_row}", float(row_data[site_col]) if has_site else 1)
        set_cell(sheet_name, f"C{excel_row}", float(row_data[serial_col]) if has_serial else (row_idx + 1))
        set_cell(sheet_name, f"D{excel_row}", float(row_data[bin_col]) if has_bin else 1)
        set_cell(sheet_name, f"E{excel_row}", float(row_data[xcol]) if has_xcol else -30000)
        set_cell(sheet_name, f"F{excel_row}", float(row_data[ycol]) if has_ycol else -30000)
        set_cell(sheet_name, f"G{excel_row}", -1)
        set_cell(sheet_name, f"H{excel_row}", len(df))

        for test_idx, col_name in enumerate(data_header):
            try:
                val = row_data[col_name]
                if pd.notna(val):
                    col_letter = excelize.column_number_to_name(test_idx + 9)
                    set_cell(sheet_name, f"{col_letter}{excel_row}", float(val))
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
        set_cell(sheet_name, f"A{row_num}", label)

    # Pre-calculate statistics for each test column
    for test_idx, col_name in enumerate(data_header):
        col_letter = excelize.column_number_to_name(test_idx + 9)
        col_data = ensure_numeric(df, col_name).dropna()

        low_val = test_mins.get(col_name)
        high_val = test_maxs.get(col_name)

        # Limits (rows 115-116) — 'N/A' when missing, never a magic 0/4 (defect #3)
        set_cell(sheet_name, f"{col_letter}115", low_val if low_val not in (None, '') else 'N/A')
        set_cell(sheet_name, f"{col_letter}116", high_val if high_val not in (None, '') else 'N/A')

        if len(col_data) > 0:
            col_min = float(col_data.min())
            col_max = float(col_data.max())
            col_range = col_max - col_min
            col_mean = float(col_data.mean())
            col_std = float(col_data.std(ddof=1)) if len(col_data) > 1 else 0.0

            set_cell(sheet_name, f"{col_letter}117", round(col_min, 6))
            set_cell(sheet_name, f"{col_letter}118", round(col_max, 6))
            set_cell(sheet_name, f"{col_letter}119", round(col_range, 6))
            set_cell(sheet_name, f"{col_letter}120", round(col_mean, 6))
            set_cell(sheet_name, f"{col_letter}121", round(col_std, 6))
            set_cell(sheet_name, f"{col_letter}122", round(col_mean - 6 * col_std, 6))
            set_cell(sheet_name, f"{col_letter}123", round(col_mean - 3 * col_std, 6))
            set_cell(sheet_name, f"{col_letter}124", round(col_mean + 3 * col_std, 6))
            set_cell(sheet_name, f"{col_letter}125", round(col_mean + 6 * col_std, 6))

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
                    set_cell(sheet_name, f"{col_letter}126", round(cpk_low, 6))
                if high_float is not None:
                    cpk_high = abs(col_mean - high_float) / (3 * col_std)
                    set_cell(sheet_name, f"{col_letter}127", round(cpk_high, 6))
                if low_float is not None and high_float is not None:
                    cpk = min(abs(col_mean - low_float), abs(col_mean - high_float)) / (3 * col_std)
                    set_cell(sheet_name, f"{col_letter}128", round(cpk, 6))

    # Row group for data rows (> 6), default collapsed
    if data_rows_to_write > 6:
        group_start = data_start_row + 3
        group_end = last_data_row_excel - 3
        for row in range(group_start, group_end + 1):
            f.set_row_outline_level(sheet_name, row, 1)
            f.set_row_visible(sheet_name, row, False)
