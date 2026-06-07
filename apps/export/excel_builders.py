"""Excel builder functions extracted from views.py.

Each function accepts an excelize file handle (``f``) and writes
content to one or more sheets.  The caller is responsible for creating
the file handle and saving/serializing the result.
"""

import pandas as pd
import numpy as np
import excelize

from apps.analysis.services.statistics import (
    detect_fail_data, compute_cpk, compute_range_statistics,
    get_1d_from, get_bin_column_name,
)
from .excelize_helpers import (
    COLOR_FONT_DARK, COLOR_ORIGINAL_LIMIT, COLOR_SIGMA_TIGHT, COLOR_SIGMA_NOT_TIGHT,
    make_header_style, make_data_style, make_red_style, make_unit_style,
    to_native,
)


def build_to_excel_sheet(f, export_df, metadata, datafile_format_type):
    """Build the main export Excel sheet with header, units, limits, stats, data rows.

    Parameters
    ----------
    f : excelize.File
        An active excelize workbook handle.
    export_df : pd.DataFrame
        The (already site/passfail filtered) dataframe to export.
    metadata : dict
        File metadata containing ``units``, ``mins``, ``maxs`` keys.
    datafile_format_type : str
        Format type string used to determine the bin column name.

    Sheet layout
    ------------
    Row  1 : Column headers  (dark bg ``#2C3E50``, white bold 12pt)
    Row  2 : Units            (italic 9pt)
    Row  3 : Low limits       (data style)
    Row  4 : High limits      (data style)
    Rows 5-10 : Statistics (Min, Avg, Max, Range, STD, CPK)
    Row 11     : (empty — auto-filter target)
    Row 12+    : Data rows with alternating ``#F8F9FA`` / ``#EDF2F7``

    Fail cells are highlighted with red background (``#F5B7B1``) and
    white bold text.  Freeze panes are set after the target-bin column
    at row 11.  Auto-filter is applied on row 11.
    """
    # Rename the default sheet, don't create a new one
    sheet_name = "Data"
    sheet_list = f.get_sheet_list()
    if sheet_list:
        f.set_sheet_name(sheet_list[0], sheet_name)

    header_style = make_header_style(f, 12)
    data_style = make_data_style(f)
    red_style = make_red_style(f)
    unit_style = make_unit_style(f)

    cols = list(export_df.columns)
    num_cols = len(cols)
    target_bin = get_bin_column_name(datafile_format_type)

    # ── Row 1: Column headers ──
    for c_idx, col_name in enumerate(cols, 1):
        cell = excelize.coordinates_to_cell_name(c_idx, 1, False)
        f.set_cell_style(sheet_name, cell, cell, header_style)
        f.set_cell_value(sheet_name, cell, col_name)

    # ── Row 2: Units ──
    for c_idx, col_name in enumerate(cols, 1):
        cell = excelize.coordinates_to_cell_name(c_idx, 2, False)
        f.set_cell_style(sheet_name, cell, cell, unit_style)
        f.set_cell_value(sheet_name, cell, metadata.get('units', {}).get(col_name, ''))

    # ── Row 3: Min limits ──
    for c_idx, col_name in enumerate(cols, 1):
        cell = excelize.coordinates_to_cell_name(c_idx, 3, False)
        f.set_cell_style(sheet_name, cell, cell, data_style)
        f.set_cell_value(sheet_name, cell, metadata.get('mins', {}).get(col_name, ''))

    # ── Row 4: Max limits ──
    for c_idx, col_name in enumerate(cols, 1):
        cell = excelize.coordinates_to_cell_name(c_idx, 4, False)
        f.set_cell_style(sheet_name, cell, cell, data_style)
        f.set_cell_value(sheet_name, cell, metadata.get('maxs', {}).get(col_name, ''))

    # ── Rows 5-10: Statistics ──
    stats_labels = ['Min', 'Avg', 'Max', 'Range', 'STD', 'CPK']
    for r_idx, label in enumerate(stats_labels):
        cell = excelize.coordinates_to_cell_name(1, 5 + r_idx, False)
        f.set_cell_style(sheet_name, cell, cell, data_style)
        f.set_cell_value(sheet_name, cell, label)

    numeric_cols = [c for c in export_df.columns if export_df[c].dtype in ('int64', 'float64')]
    for col_name in numeric_cols:
        c_idx = cols.index(col_name) + 1
        col_data = pd.to_numeric(export_df[col_name], errors='coerce').dropna()
        if len(col_data) > 0:
            v_min = round(float(col_data.min()), 6)
            v_avg = round(float(col_data.mean()), 6)
            v_max = round(float(col_data.max()), 6)
            v_range = round(float(v_max - v_min), 6)
            v_std = round(float(col_data.std()), 6)
            try:
                min_v = float(metadata['mins'][col_name])
                max_v = float(metadata['maxs'][col_name])
                v_cpk = round(compute_cpk(v_avg, v_std, min_v, max_v)['cpk'], 6)
            except Exception:
                v_cpk = 0

            for row_offset, val in [
                (5, v_min), (6, v_avg), (7, v_max), (8, v_range), (9, v_std), (10, v_cpk),
            ]:
                cell = excelize.coordinates_to_cell_name(c_idx, row_offset, False)
                f.set_cell_value(sheet_name, cell, val)

    # ── Detect fail data on the (already filtered) dataframe ──
    # Reset index BEFORE detect_fail_data to ensure indices start from 0
    export_df = export_df.reset_index(drop=True)
    fail_indices, _, fail_cells = detect_fail_data(export_df, metadata)
    fail_set = set(fail_indices)
    fail_cells_map = fail_cells

    # ── Write data starting at row 12 ──
    data_start = 12
    last_col_letter = excelize.column_number_to_name(num_cols)

    # Convert to list for batch processing
    df_values = export_df.values.tolist()
    data_end_row = data_start + len(df_values) - 1

    # Apply default data style to all data cells first
    f.set_cell_style(sheet_name, f"A{data_start}", f"{last_col_letter}{data_end_row}", data_style)

    # Write data rows in batch
    for r_idx in range(len(df_values)):
        excel_row = data_start + r_idx
        row_data = [to_native(v) for v in df_values[r_idx]]
        cell_ref = excelize.coordinates_to_cell_name(1, excel_row, False)
        f.set_sheet_row(sheet_name, cell_ref, row_data)

    # Apply red style to fail cells
    for r_idx in fail_set:
        excel_row = data_start + r_idx
        for c_idx, col_name in enumerate(cols):
            is_bin = (col_name == target_bin)
            in_fail_cells = r_idx in fail_cells_map and col_name in fail_cells_map[r_idx]
            if is_bin or in_fail_cells:
                cell = excelize.coordinates_to_cell_name(c_idx + 1, excel_row, False)
                f.set_cell_style(sheet_name, cell, cell, red_style)

    # ── Freeze panes ──
    target_bin_c_idx = (cols.index(target_bin) + 1) if target_bin in cols else 1
    top_left_cell = excelize.coordinates_to_cell_name(target_bin_c_idx + 1, data_start, False)
    f.set_panes(sheet_name, excelize.Panes(
        freeze=True, split=False,
        x_split=target_bin_c_idx,
        y_split=data_start - 1,
        top_left_cell=top_left_cell,
    ))

    # ── Auto-filter on row 11 ──
    f.auto_filter(sheet_name, f"A11:{last_col_letter}11", [])

    # ── Column widths ──
    for c_idx in range(1, num_cols + 1):
        cl = excelize.column_number_to_name(c_idx)
        f.set_col_width(sheet_name, cl, cl, 14)


def build_sigma_limit_sheet(f, df, metadata, sigma_level=3, only_valid=False):
    """Build sigma limit comparison Excel sheet.

    Parameters
    ----------
    f : excelize.File
    df : pd.DataFrame
    metadata : dict
    sigma_level : int
        Number of sigma (3, 4, 5, 6, …).
    only_valid : bool
        When True, skip parameters whose limits are non-numeric strings.

    Sheet layout
    ------------
    Row 1 : Headers (dark bg)
    Row 2+ : One row per numeric parameter:
        - Col A (序号) : serial number
        - Col B (测试项) : parameter name
        - Col C (原LimitL) : original lower limit — blue bg (#D6EAF8)
        - Col D (原LimitH) : original upper limit — blue bg (#D6EAF8)
        - Col E ({n}σ LimitL) : sigma lower limit — red (#F5B7B1) if
          sigma range is tighter than original, yellow (#FCF3CF) otherwise
        - Col F ({n}σ LimitH) : sigma upper limit — same color rule

    Freeze panes at A2.  Column widths: A=8, B=40, C=15, D=15, E=18, F=18.
    """
    sheet_name = "TestItem_Limit"
    sheet_index = f.new_sheet(sheet_name)
    f.set_active_sheet(sheet_index)

    header_style = make_header_style(f, 12)

    orig_limit_fill = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[COLOR_ORIGINAL_LIMIT], pattern=1),
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    sigma_tight_fill = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[COLOR_SIGMA_TIGHT], pattern=1),
        font=excelize.Font(bold=True, size=10, color="FFFFFF", family="Calibri"),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    sigma_not_tight_fill = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[COLOR_SIGMA_NOT_TIGHT], pattern=1),
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))

    headers = ['序号', '测试项', '原LimitL', '原LimitH',
               f'{sigma_level}σ LimitL', f'{sigma_level}σ LimitH']
    for c_idx, h in enumerate(headers, 1):
        cell = excelize.coordinates_to_cell_name(c_idx, 1, False)
        f.set_cell_style(sheet_name, cell, cell, header_style)
        f.set_cell_value(sheet_name, cell, h)

    numeric_cols = [c for c in df.columns if df[c].dtype in ('int64', 'float64')]
    row_idx = 2
    serial = 1
    NON_NUM = ['min', 'max', 'lower limit', 'upper limit', 'n/a', 'na', '-', 'none', '']

    for param in numeric_cols:
        if param not in metadata.get('mins', {}) or param not in metadata.get('maxs', {}):
            continue
        min_str = str(metadata['mins'][param]).strip()
        max_str = str(metadata['maxs'][param]).strip()
        if only_valid and (min_str.lower() in NON_NUM or max_str.lower() in NON_NUM):
            continue

        data_series = get_1d_from(df, param).dropna()
        if len(data_series) == 0:
            continue

        mean_val = float(data_series.mean())
        std_val = float(data_series.std(ddof=0)) if len(data_series) > 1 else 0
        sigma_min = mean_val - sigma_level * std_val
        sigma_max = mean_val + sigma_level * std_val

        try:
            rdl_min = float(min_str)
        except (ValueError, TypeError):
            rdl_min = None
        try:
            rdl_max = float(max_str)
        except (ValueError, TypeError):
            rdl_max = None

        f.set_cell_value(sheet_name, excelize.coordinates_to_cell_name(1, row_idx, False), serial)
        f.set_cell_value(sheet_name, excelize.coordinates_to_cell_name(2, row_idx, False), param)

        # Columns 3-4: Original limits (blue bg)
        l3 = excelize.coordinates_to_cell_name(3, row_idx, False)
        f.set_cell_value(sheet_name, l3, round(rdl_min, 4) if rdl_min is not None else 'N/A')
        f.set_cell_style(sheet_name, l3, l3, orig_limit_fill)

        l4 = excelize.coordinates_to_cell_name(4, row_idx, False)
        f.set_cell_value(sheet_name, l4, round(rdl_max, 4) if rdl_max is not None else 'N/A')
        f.set_cell_style(sheet_name, l4, l4, orig_limit_fill)

        # Columns 5-6: Sigma limits (red/yellow based on tightness)
        l5 = excelize.coordinates_to_cell_name(5, row_idx, False)
        f.set_cell_value(sheet_name, l5, round(sigma_min, 4))
        l6 = excelize.coordinates_to_cell_name(6, row_idx, False)
        f.set_cell_value(sheet_name, l6, round(sigma_max, 4))

        is_tighter = False
        if rdl_min is not None and rdl_max is not None:
            orig_range = rdl_max - rdl_min
            sigma_range = sigma_max - sigma_min
            if sigma_range < orig_range and sigma_min >= rdl_min and sigma_max <= rdl_max:
                is_tighter = True

        tight_style = sigma_tight_fill if is_tighter else sigma_not_tight_fill
        f.set_cell_style(sheet_name, l5, l5, tight_style)
        f.set_cell_style(sheet_name, l6, l6, tight_style)

        row_idx += 1
        serial += 1

    # Column widths
    widths = {'A': 8, 'B': 40, 'C': 15, 'D': 15, 'E': 18, 'F': 18}
    for cl, w in widths.items():
        f.set_col_width(sheet_name, cl, cl, w)

    f.set_panes(sheet_name, excelize.Panes(
        freeze=True, split=False, y_split=1, top_left_cell='A2',
    ))


def build_batch_charts_xlsx(f, df, metadata, params):
    """Build batch charts summary Excel sheet.

    Parameters
    ----------
    f : excelize.File
    df : pd.DataFrame
    metadata : dict
    params : list of str
        Parameter (column) names to include.
    """
    sheet_name = "Summary"
    sheet_index = f.new_sheet(sheet_name)
    f.set_active_sheet(sheet_index)

    header_style = make_header_style(f, 12)
    data_style = make_data_style(f)

    headers = ['参数', 'Mean', 'STD', 'CPK', 'CPK Level', 'Min', 'Max',
               'Data Min', 'Data Max', 'Lower Limit', 'Upper Limit',
               '3σ Min', '3σ Max', '6σ Min', '6σ Max', 'N', 'Unit']
    for c_idx, h in enumerate(headers, 1):
        cell = excelize.coordinates_to_cell_name(c_idx, 1, False)
        f.set_cell_style(sheet_name, cell, cell, header_style)
        f.set_cell_value(sheet_name, cell, h)

    row_idx = 2
    for param in params:
        if param not in df.columns:
            continue
        data_series = get_1d_from(df, param).dropna()
        data_series = data_series[data_series.apply(lambda x: abs(x) < float('inf'))]
        if len(data_series) == 0:
            continue

        stats = compute_range_statistics(data_series, metadata, param)
        cpk_result = compute_cpk(
            stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1]
        )

        vals = [
            param,
            round(stats['mean'], 4), round(stats['std'], 4),
            round(cpk_result['cpk'], 4), cpk_result['cpk_level'],
            round(stats['dr'][0], 4), round(stats['dr'][1], 4),
            round(stats['dr'][0], 4), round(stats['dr'][1], 4),
            round(stats['rdl'][0], 4), round(stats['rdl'][1], 4),
            round(stats['s3'][0], 4), round(stats['s3'][1], 4),
            round(stats['s6'][0], 4), round(stats['s6'][1], 4),
            len(data_series), stats['unit'],
        ]
        for c_idx, v in enumerate(vals, 1):
            cell = excelize.coordinates_to_cell_name(c_idx, row_idx, False)
            f.set_cell_style(sheet_name, cell, cell, data_style)
            if v is not None:
                f.set_cell_value(sheet_name, cell, v)
        row_idx += 1

    for c_idx in range(1, len(headers) + 1):
        cl = excelize.column_number_to_name(c_idx)
        f.set_col_width(sheet_name, cl, cl, 16)
