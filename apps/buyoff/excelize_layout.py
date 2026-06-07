"""Buyoff Excel form builder using excelize.
Generates the single-sheet buyoff form with vertical FT/QA1/QA2 sections.
"""

import excelize
from apps.export.excelize_helpers import (
    make_header_style, make_data_style, make_red_style,
    make_unit_style, make_title_style,
    COLOR_BORDER, COLOR_FONT_DARK, thin_border,
)

# ── Section Colors ──
COLOR_SECTION_FT = "3498DB"
COLOR_SECTION_QA1 = "27AE60"
COLOR_SECTION_QA2 = "E67E22"
COLOR_RESULT_BG = "8E44AD"
COLOR_STAT_LABEL_BG = "ECF0F1"
COLOR_GREEN_BG = "D5F5E3"
COLOR_YELLOW_BG = "FCF3CF"
COLOR_RED_BG = "F5B7B1"

# ── Stat rows definition ──
STAT_ROWS = [
    ("Lower Limit", "lower_limit", True),
    ("Upper Limit", "upper_limit", True),
    ("Min", "min", False),
    ("Max", "max", False),
    ("Range", "range", False),
    ("Mean", "mean", False),
    ("STD", "std", False),
    ("Mean-6*STD", "mean_minus_6std", False),
    ("Mean-3*STD", "mean_minus_3std", False),
    ("Mean+3*STD", "mean_plus_3std", False),
    ("Mean+6*STD", "mean_plus_6std", False),
    ("Ca", "ca", False),
    ("Cp", "cp", False),
    ("Cpk", "cpk", False),
]


def _section_style(f, color_hex):
    """Create a section header style with colored background."""
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=13, color="FFFFFF", family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[color_hex], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=2),
            excelize.Border(type="top", color=COLOR_BORDER, style=2),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=2),
            excelize.Border(type="right", color=COLOR_BORDER, style=2),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center", text_rotation=255),
    ))


def build_buyoff_form(f, role_mapping, common_items, all_stats, datasets, ordered_roles):
    """Build the buyoff form on an existing excelize file handle.

    Layout (single sheet):
      Row 1:  Merged title "Buyoff Analysis Report"
      Row 3-5: Column headers + test number + units
      FT section:  14 stat rows (blue #3498DB section header)
      QA1 section: 14 stat rows (green #27AE60 section header)
      QA2 section: 14 stat rows (orange #E67E22 section header)
      Results: 5 rows (purple #8E44AD section header)
       - FT-LL minus QA-LL
       - QA-UL minus FT-UL
       - (QA1 Mean - FT Mean)/range %
       - (QA2 Mean - FT Mean)/range %
       - Comments
      Freeze panes at C6
    """
    sheet_name = "Buyoff data"
    sheet_list = f.get_sheet_list()
    if sheet_list:
        f.set_sheet_name(sheet_list[0], sheet_name)

    # ── Shared styles ──
    header_style = make_header_style(f, 12)
    data_style = make_data_style(f)
    red_style = make_red_style(f)
    unit_style = make_unit_style(f)
    title_style = make_title_style(f)

    ft_section_style = _section_style(f, COLOR_SECTION_FT)
    qa1_section_style = _section_style(f, COLOR_SECTION_QA1)
    qa2_section_style = _section_style(f, COLOR_SECTION_QA2)
    result_section_style = _section_style(f, COLOR_RESULT_BG)

    stat_label_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=10, color=COLOR_FONT_DARK, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_STAT_LABEL_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="left", vertical="center"),
    ))

    green_result_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=10, color="145A32", family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_GREEN_BG], pattern=1),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    yellow_result_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=10, color="7D6608", family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_YELLOW_BG], pattern=1),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))
    red_result_style = f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=10, color="FFFFFF", family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))

    section_styles = {
        'FT': ft_section_style,
        'QA1': qa1_section_style,
        'QA2': qa2_section_style,
    }

    # ── Layout setup ──
    test_col_start = 3  # A=section header, B=stat label, C+=test items
    last_col_letter = excelize.column_number_to_name(test_col_start - 1 + len(common_items))

    # Get units
    test_units = {}
    for param in common_items:
        for role_name in ordered_roles:
            fname = role_mapping[role_name]
            unit = datasets[fname]['metadata'].get('units', {}).get(param, '')
            if unit:
                test_units[param] = unit
                break

    # ── Row 1: Title ──
    f.merge_cell(sheet_name, "A1", f"{last_col_letter}1")
    f.set_cell_value(sheet_name, "A1", "Buyoff Analysis Report")
    f.set_cell_style(sheet_name, "A1", "A1", title_style)
    f.set_row_height(sheet_name, 1, 30)

    # ── Row 3: Column headers ──
    f.set_cell_value(sheet_name, "A3", "Parameters")
    f.set_cell_style(sheet_name, "A3", "A3", header_style)
    f.set_cell_value(sheet_name, "B3", "Test Name")
    f.set_cell_style(sheet_name, "B3", "B3", header_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        f.set_cell_value(sheet_name, f"{cl}3", param)
        f.set_cell_style(sheet_name, f"{cl}3", f"{cl}3", header_style)

    # ── Row 4: Test number ──
    f.set_cell_value(sheet_name, "A4", "")
    f.set_cell_style(sheet_name, "A4", "A4", header_style)
    f.set_cell_value(sheet_name, "B4", "Test Number")
    f.set_cell_style(sheet_name, "B4", "B4", header_style)
    for c_num in range(test_col_start, test_col_start + len(common_items)):
        cl = excelize.column_number_to_name(c_num)
        f.set_cell_style(sheet_name, f"{cl}4", f"{cl}4", header_style)

    # ── Row 5: Units ──
    f.set_cell_value(sheet_name, "A5", "")
    f.set_cell_style(sheet_name, "A5", "A5", unit_style)
    f.set_cell_value(sheet_name, "B5", "Units")
    f.set_cell_style(sheet_name, "B5", "B5", unit_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        f.set_cell_value(sheet_name, f"{cl}5", test_units.get(param, ''))
        f.set_cell_style(sheet_name, f"{cl}5", f"{cl}5", unit_style)

    # ── Section writing loop ──
    row_idx = 6
    for role_name in ordered_roles:
        section_start = row_idx
        fname = role_mapping[role_name]
        ds = datasets[fname]

        for stat_name, stat_key, is_limit in STAT_ROWS:
            # Col B: stat label
            f.set_cell_value(sheet_name, f"B{row_idx}", stat_name)
            f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)

            # Cols C+: data for each test item
            for c_num, param in enumerate(common_items, start=test_col_start):
                cl = excelize.column_number_to_name(c_num)
                cell = f"{cl}{row_idx}"

                if is_limit:
                    if stat_name == "Lower Limit":
                        val = ds['metadata'].get('mins', {}).get(param, "")
                    else:
                        val = ds['metadata'].get('maxs', {}).get(param, "")
                    f.set_cell_value(sheet_name, cell, val)
                elif param in all_stats.get(role_name, {}):
                    val = all_stats[role_name][param].get(stat_key, "")
                    if isinstance(val, float):
                        val = round(val, 6)
                    f.set_cell_value(sheet_name, cell, val)

                f.set_cell_style(sheet_name, cell, cell, data_style)

            row_idx += 1

        section_end = row_idx - 1

        # Merge col A for section header
        f.merge_cell(sheet_name, f"A{section_start}", f"A{section_end}")
        f.set_cell_value(sheet_name, f"A{section_start}", role_name)
        style = section_styles.get(role_name, ft_section_style)
        f.set_cell_style(sheet_name, f"A{section_start}", f"A{section_start}", style)

        # Blank row between sections
        row_idx += 1

    # ── Results section ──
    results_start = row_idx
    margin = 5
    results_end = results_start + margin - 1

    f.merge_cell(sheet_name, f"A{results_start}", f"A{results_end}")
    f.set_cell_value(sheet_name, f"A{results_start}", "Result")
    f.set_cell_style(sheet_name, f"A{results_start}", f"A{results_start}", result_section_style)

    # Result row 1: FT Lower Limit - QA Lower Limit
    f.set_cell_value(sheet_name, f"B{row_idx}", "FT Lower Limit - QA Lower Limit")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        if 'FT' in role_mapping and 'QA1' in role_mapping:
            ft_ll = datasets[role_mapping['FT']]['metadata'].get('mins', {}).get(param, 0)
            qa_ll = datasets[role_mapping['QA1']]['metadata'].get('mins', {}).get(param, 0)
            try:
                diff = float(ft_ll) - float(qa_ll)
            except (ValueError, TypeError):
                diff = 0
            f.set_cell_value(sheet_name, cell, round(diff, 6))
            f.set_cell_style(sheet_name, cell, cell, red_style if diff <= 0 else data_style)
        else:
            f.set_cell_style(sheet_name, cell, cell, data_style)
    row_idx += 1

    # Result row 2: QA Upper Limit - FT Upper Limit
    f.set_cell_value(sheet_name, f"B{row_idx}", "QA Upper Limit - FT Upper Limit")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        if 'FT' in role_mapping and 'QA1' in role_mapping:
            ft_ul = datasets[role_mapping['FT']]['metadata'].get('maxs', {}).get(param, 0)
            qa_ul = datasets[role_mapping['QA1']]['metadata'].get('maxs', {}).get(param, 0)
            try:
                diff = float(qa_ul) - float(ft_ul)
            except (ValueError, TypeError):
                diff = 0
            f.set_cell_value(sheet_name, cell, round(diff, 6))
            f.set_cell_style(sheet_name, cell, cell, red_style if diff <= 0 else data_style)
        else:
            f.set_cell_style(sheet_name, cell, cell, data_style)
    row_idx += 1

    # Result row 3: (QA1 Mean - FT Mean) / range
    f.set_cell_value(sheet_name, f"B{row_idx}", "(QA1 Mean - FT Mean)/ (QA Upper Limit - QA Lower Limit)")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        if 'FT' in role_mapping and 'QA1' in role_mapping and param in all_stats.get('QA1', {}):
            qa1_s = all_stats['QA1'][param]
            ft_s = all_stats['FT'][param]
            mean_diff = qa1_s['mean'] - ft_s['mean']
            qa_range = qa1_s['upper_limit'] - qa1_s['lower_limit']
            if qa_range == 0:
                qa_range = 1
            pct = (mean_diff / qa_range) * 100
            f.set_cell_value(sheet_name, cell, f"{pct:.2f}%")
            if abs(pct) > 10:
                f.set_cell_style(sheet_name, cell, cell, red_result_style)
            elif abs(pct) > 5:
                f.set_cell_style(sheet_name, cell, cell, yellow_result_style)
            else:
                f.set_cell_style(sheet_name, cell, cell, green_result_style)
        else:
            f.set_cell_style(sheet_name, cell, cell, data_style)
    row_idx += 1

    # Result row 4: (QA2 Mean - FT Mean) / range
    f.set_cell_value(sheet_name, f"B{row_idx}", "(QA2 Mean - FT Mean)/ (QA Upper Limit - QA Lower Limit)")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        if 'FT' in role_mapping and 'QA2' in role_mapping and param in all_stats.get('QA2', {}):
            qa2_s = all_stats['QA2'][param]
            ft_s = all_stats['FT'][param]
            mean_diff = qa2_s['mean'] - ft_s['mean']
            qa_range = qa2_s['upper_limit'] - qa2_s['lower_limit']
            if qa_range == 0:
                qa_range = 1
            pct = (mean_diff / qa_range) * 100
            f.set_cell_value(sheet_name, cell, f"{pct:.2f}%")
            if abs(pct) > 10:
                f.set_cell_style(sheet_name, cell, cell, red_result_style)
            elif abs(pct) > 5:
                f.set_cell_style(sheet_name, cell, cell, yellow_result_style)
            else:
                f.set_cell_style(sheet_name, cell, cell, green_result_style)
        else:
            f.set_cell_style(sheet_name, cell, cell, data_style)
    row_idx += 1

    # Result row 5: Comments
    f.set_cell_value(sheet_name, f"B{row_idx}", "Comments")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num in range(test_col_start, test_col_start + len(common_items)):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        f.set_cell_style(sheet_name, cell, cell, data_style)
    row_idx += 2  # blank rows

    # ── Freeze panes ──
    f.set_panes(sheet_name, excelize.Panes(
        freeze=True, split=False,
        x_split=2, y_split=5,
        top_left_cell="C6",
    ))

    # ── Column widths ──
    f.set_col_width(sheet_name, "A", "A", 8)
    f.set_col_width(sheet_name, "B", "B", 22)
    for c_num in range(test_col_start, test_col_start + len(common_items)):
        cl = excelize.column_number_to_name(c_num)
        f.set_col_width(sheet_name, cl, cl, 18)
