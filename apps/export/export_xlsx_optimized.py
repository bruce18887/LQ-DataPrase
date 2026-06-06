"""Optimized Excel export using excelize."""

import pandas as pd
import excelize
import tempfile
import os
from typing import Dict
from apps.analysis.services.statistics import (
    ensure_numeric, get_bin_column_name, detect_fail_data,
)
from .export_csv import _convert_to_native_type


def export_to_xlsx_optimized(df: pd.DataFrame, metadata: Dict) -> bytes:
    f = excelize.new_file()

    try:
        sheet_name = "Data"
        sheet_index = f.new_sheet(sheet_name)
        f.set_active_sheet(sheet_index)

        cols = df.columns.tolist()
        num_cols = len(cols)

        # 现代专业配色（与 buyoff 统一）
        COLOR_HEADER_BG = "2C3E50"
        COLOR_HEADER_FONT = "FFFFFF"
        COLOR_DATA_BG = "F8F9FA"
        COLOR_ALT_ROW = "EDF2F7"
        COLOR_BORDER = "BDC3C7"
        COLOR_FONT_DARK = "2C3E50"
        COLOR_RED_BG = "F5B7B1"

        header_style_id = f.new_style(excelize.Style(
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

        data_style_id = f.new_style(excelize.Style(
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

        red_style_id = f.new_style(excelize.Style(
            font=excelize.Font(bold=True, size=10, color="FFFFFF", family="Calibri"),
            fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
            border=[
                excelize.Border(type="left", color=COLOR_BORDER, style=1),
                excelize.Border(type="top", color=COLOR_BORDER, style=1),
                excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
                excelize.Border(type="right", color=COLOR_BORDER, style=1),
            ],
            alignment=excelize.Alignment(horizontal="center", vertical="center"),
        ))

        red_bin_style_id = f.new_style(excelize.Style(
            font=excelize.Font(bold=True, size=10, color="FFFFFF", family="Calibri"),
            fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
            border=[
                excelize.Border(type="left", color=COLOR_BORDER, style=1),
                excelize.Border(type="top", color=COLOR_BORDER, style=1),
                excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
                excelize.Border(type="right", color=COLOR_BORDER, style=1),
            ],
            alignment=excelize.Alignment(horizontal="center", vertical="center"),
        ))

        for col_idx, col_name in enumerate(cols):
            cell = excelize.coordinates_to_cell_name(col_idx + 1, 1, False)
            f.set_cell_style(sheet_name, cell, cell, header_style_id)
            f.set_cell_value(sheet_name, cell, col_name)

            cell = excelize.coordinates_to_cell_name(col_idx + 1, 2, False)
            f.set_cell_style(sheet_name, cell, cell, data_style_id)
            f.set_cell_value(sheet_name, cell, metadata['units'].get(col_name, ""))

            cell = excelize.coordinates_to_cell_name(col_idx + 1, 3, False)
            f.set_cell_style(sheet_name, cell, cell, data_style_id)
            f.set_cell_value(sheet_name, cell, metadata['mins'].get(col_name, ""))

            cell = excelize.coordinates_to_cell_name(col_idx + 1, 4, False)
            f.set_cell_style(sheet_name, cell, cell, data_style_id)
            f.set_cell_value(sheet_name, cell, metadata['maxs'].get(col_name, ""))

        f.set_cell_value(sheet_name, "A5", "Min")
        f.set_cell_value(sheet_name, "A6", "Avg")
        f.set_cell_value(sheet_name, "A7", "Max")
        f.set_cell_value(sheet_name, "A8", "Range")
        f.set_cell_value(sheet_name, "A9", "STD")
        f.set_cell_value(sheet_name, "A10", "CPK")

        numeric_cols = [col for col in cols if df[col].dtype in ['int64', 'float64']]

        for col_name in numeric_cols:
            col_idx = cols.index(col_name) + 1
            col_data = ensure_numeric(df, col_name).dropna()

            if len(col_data) > 0:
                col_min = round(float(col_data.min()), 6)
                col_avg = round(float(col_data.mean()), 6)
                col_max = round(float(col_data.max()), 6)
                col_range = round(float(col_data.max() - col_data.min()), 6)
                col_std = round(float(col_data.std()), 6)

                try:
                    min_val = float(metadata['mins'][col_name])
                    max_val = float(metadata['maxs'][col_name])
                    col_cpk = round(min((max_val - col_avg) / (3 * col_std), (col_avg - min_val) / (3 * col_std)), 6) if col_std > 0 else 0
                except (ValueError, TypeError, KeyError):
                    col_cpk = 0

                cell = excelize.coordinates_to_cell_name(col_idx, 5, False)
                f.set_cell_style(sheet_name, cell, cell, data_style_id)
                f.set_cell_value(sheet_name, cell, col_min)

                cell = excelize.coordinates_to_cell_name(col_idx, 6, False)
                f.set_cell_style(sheet_name, cell, cell, data_style_id)
                f.set_cell_value(sheet_name, cell, col_avg)

                cell = excelize.coordinates_to_cell_name(col_idx, 7, False)
                f.set_cell_style(sheet_name, cell, cell, data_style_id)
                f.set_cell_value(sheet_name, cell, col_max)

                cell = excelize.coordinates_to_cell_name(col_idx, 8, False)
                f.set_cell_style(sheet_name, cell, cell, data_style_id)
                f.set_cell_value(sheet_name, cell, col_range)

                cell = excelize.coordinates_to_cell_name(col_idx, 9, False)
                f.set_cell_style(sheet_name, cell, cell, data_style_id)
                f.set_cell_value(sheet_name, cell, col_std)

                cell = excelize.coordinates_to_cell_name(col_idx, 10, False)
                f.set_cell_style(sheet_name, cell, cell, data_style_id)
                f.set_cell_value(sheet_name, cell, col_cpk)

        format_type = metadata.get('format', 'CTA8290D')
        target_bin_col = get_bin_column_name(format_type)
        target_bin_col_idx = cols.index(target_bin_col) + 1 if target_bin_col in cols else 1


        fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata)

        fail_row_indices = set()
        fail_col_idx_map = {col_name: idx for idx, col_name in enumerate(cols)}
        fail_cells_by_row_idx = {}
        for idx, col_list in fail_cells.items():
            fail_row_indices.add(idx)
            fail_cells_by_row_idx[idx] = set(fail_col_idx_map.get(c, -1) for c in col_list if c in fail_col_idx_map)

        data_start_row = 12

        df_values = df.values.tolist()
        data_end_row = data_start_row + len(df_values) - 1
        last_col_name = excelize.column_number_to_name(num_cols)

        f.set_cell_style(sheet_name, f"A{data_start_row}", f"{last_col_name}{data_end_row}", data_style_id)
        for row_idx in range(len(df_values)):
            excel_row = data_start_row + row_idx
            row_data = [_convert_to_native_type(v) for v in df_values[row_idx]]
            cell_ref = excelize.coordinates_to_cell_name(1, excel_row, False)
            f.set_sheet_row(sheet_name, cell_ref, row_data)

        for row_idx in fail_row_indices:
            excel_row = data_start_row + row_idx
            row_fail_col_indices = fail_cells_by_row_idx.get(row_idx, set())

            for col_idx in range(num_cols):
                cell = excelize.coordinates_to_cell_name(col_idx + 1, excel_row, False)
                if cols[col_idx] == target_bin_col:
                    f.set_cell_style(sheet_name, cell, cell, red_bin_style_id)
                elif col_idx in row_fail_col_indices:
                    f.set_cell_style(sheet_name, cell, cell, red_style_id)

        last_cell = excelize.coordinates_to_cell_name(num_cols, 11, False)
        bin_col_letter = excelize.column_number_to_name(target_bin_col_idx + 1)
        top_left_cell_ref = f"{bin_col_letter}12"
        f.set_panes(sheet_name, excelize.Panes(
            freeze=True,
            split=False,
            x_split=target_bin_col_idx,
            y_split=11,
            top_left_cell=top_left_cell_ref,
        ))

        f.auto_filter(sheet_name, f"A11:{last_cell}", [])

        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp_path = tmp.name

        f.save_as(tmp_path)
        f.close()

        with open(tmp_path, 'rb') as tmp_file:
            data = tmp_file.read()

        os.unlink(tmp_path)

        return data

    except Exception as e:
        f.close()
        raise e
