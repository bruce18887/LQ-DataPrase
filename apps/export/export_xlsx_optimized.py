"""Optimized Excel export using excelize."""

import pandas as pd
import excelize
from typing import Dict
from apps.analysis.services.statistics import (
    ensure_numeric, get_bin_column_name, detect_fail_data,
    compute_cpk,
)
from .excelize_helpers import (
    make_header_style, make_data_style, make_red_style,
    to_native, save_excelize,
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

        # Shared styles from excelize_helpers
        header_style_id = make_header_style(f, 12)
        data_style_id = make_data_style(f)
        red_style_id = make_red_style(f)

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
                    col_cpk = round(compute_cpk(col_avg, col_std, min_val, max_val)['cpk'], 6)
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

        # ── Fail 标红 ──
        # 原实现「每个 fail 行 × 每列 set_cell_style」在万行 × 百列文件下产生数十万次
        # Python→C 调用（ETS88 1438 行实测 62s），导致前端 30s 超时 → Broken pipe。
        # 改为 fail 行整行标红：每行一次范围样式调用（fail 行数 ≈ 千级 → 毫秒级）。
        # 视觉变化：fail 行的整行（含非 fail 单元格）标红，定位更醒目。
        fail_row_indices = set(fail_cells.keys())
        for row_idx in fail_row_indices:
            excel_row = data_start_row + row_idx
            f.set_cell_style(sheet_name, f"A{excel_row}", f"{last_col_name}{excel_row}", red_style_id)

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

        return save_excelize(f)

    except Exception as e:
        f.close()
        raise e
