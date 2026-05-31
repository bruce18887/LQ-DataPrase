"""Complete export functions from old version."""

import pandas as pd
import numpy as np
import excelize
import tempfile
import os
from typing import Dict, Optional
from apps.analysis.services.statistics import ensure_numeric, get_bin_column_name, detect_fail_data, get_site_column

# ── Helper Functions ──

def _convert_to_native_type(val):
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (ValueError, TypeError):
        pass
    if isinstance(val, (bool,)):
        return val
    if isinstance(val, (int,)):
        return int(val) if hasattr(val, 'item') else val
    if isinstance(val, (float,)):
        if hasattr(val, 'item'):
            native = val.item()
        else:
            native = val
        if pd.isna(native):
            return ""
        return native
    if hasattr(val, 'item'):
        native = val.item()
        try:
            if pd.isna(native):
                return ""
        except (ValueError, TypeError):
            pass
        return native
    return str(val) if val is not None else ""



# 导出DataFrame为CSV，支持Site过滤、Pass/Fail过滤和原始格式匹配
def export_to_csv(df: pd.DataFrame, metadata: Dict, site_filter=None, passfail_filter=None, 
                  keep_header=False, match_original_format=False, raw_lines=None) -> bytes:
    try:
       
        export_df = df.copy()
        
        if site_filter and site_filter != "全部":
            site_col = get_site_column(df)
            if site_col:
                export_df = export_df[export_df[site_col].astype(str) == str(site_filter)]
        
        if passfail_filter and passfail_filter != "全部":

            format_type = metadata.get('format', 'CTA8290D')
            bin_col = get_bin_column_name(format_type)
            
            if bin_col in export_df.columns:
                if passfail_filter == "Pass":
                    export_df = export_df[ensure_numeric(export_df, bin_col) == 1]
                elif passfail_filter == "Fail":
                    export_df = export_df[ensure_numeric(export_df, bin_col) != 1]
        
        if keep_header and raw_lines:

            format_type = metadata.get('format', 'CTA8290D')
            config = DATA_FORMAT_CONFIG.get(format_type)
            
            if config and raw_lines:
                data_marker_line = None
                for i, line in enumerate(raw_lines):
                    if config['marker'] in line:
                        data_marker_line = i
                        break
                
                if data_marker_line is not None:
                    if format_type in ['CTA8290D', 'CTA8280F']:
                        header_end_line = data_marker_line + config['max_offset']
                    elif format_type == 'ETS88':
                        header_end_line = data_marker_line + 3
                    else:
                        header_end_line = data_marker_line
                    
                    header_lines = []
                    for i in range(header_end_line + 1):
                        header_lines.append(raw_lines[i].rstrip('\n').rstrip('\r'))
                    
                    header_content = '\n'.join(header_lines)
                    
                    if len(export_df) > 0:
                        if match_original_format:
                            if format_type == 'ETS88':
                                export_bin_col = get_bin_column_name(format_type)
                                coord_x_col = 'XCoord'
                                coord_y_col = 'YCoord'
                                
                                meta_cols = ['Site #', 'Serial #', export_bin_col, coord_x_col, coord_y_col]
                                existing_meta_cols = [c for c in meta_cols if c in export_df.columns]
                                other_cols = [c for c in export_df.columns if c not in meta_cols]
                                ordered_cols = existing_meta_cols + other_cols
                                export_df = export_df[ordered_cols]
                            
                            data_csv = export_df.to_csv(index=False, header=False)
                            csv_content = header_content + '\n' + data_csv
                        else:
                            data_csv = export_df.to_csv(index=False)
                            csv_content = header_content + '\n' + data_csv
                    else:
                        csv_content = header_content
                else:
                    csv_content = export_df.to_csv(index=False)
            else:
                csv_content = export_df.to_csv(index=False)
        elif match_original_format and raw_lines:

            format_type = metadata.get('format', 'CTA8290D')
            config = DATA_FORMAT_CONFIG.get(format_type)
            
            if config and raw_lines:
                data_start = None
                for i, line in enumerate(raw_lines):
                    if config['marker'] in line:
                        data_start = i
                        break
                
                if data_start is not None:
                    marker_line = raw_lines[data_start].strip()
                    
                    if len(export_df) > 0:
                        if format_type == 'ETS88':
                            export_bin_col = get_bin_column_name(format_type)
                            coord_x_col = 'XCoord'
                            coord_y_col = 'YCoord'
                            
                            meta_cols = ['Site #', 'Serial #', export_bin_col, coord_x_col, coord_y_col]
                            existing_meta_cols = [c for c in meta_cols if c in export_df.columns]
                            other_cols = [c for c in export_df.columns if c not in meta_cols]
                            ordered_cols = existing_meta_cols + other_cols
                            export_df = export_df[ordered_cols]
                        
                        data_csv = export_df.to_csv(index=False, header=False)
                        csv_content = marker_line + '\n' + data_csv
                    else:
                        csv_content = marker_line
                else:
                    csv_content = export_df.to_csv(index=False)
            else:
                csv_content = export_df.to_csv(index=False)
        else:
            csv_content = export_df.to_csv(index=False)
        
        return csv_content.encode('utf-8-sig')
    except ImportError:
        # Fallback when app module is not available
        export_df = df.copy()
        if site_filter and site_filter != "全部":
            # Simplified site filtering without get_site_column
            site_cols = [col for col in df.columns if 'Site' in col or 'site' in col]
            if site_cols:
                export_df = export_df[export_df[site_cols[0]].astype(str) == str(site_filter)]
        if passfail_filter and passfail_filter != "全部":
            # Simplified pass/fail filtering
            bin_cols = [col for col in df.columns if 'Bin' in col or 'bin' in col]
            if bin_cols:
                if passfail_filter == "Pass":
                    export_df = export_df[pd.to_numeric(export_df[bin_cols[0]], errors='coerce') == 1]
                elif passfail_filter == "Fail":
                    export_df = export_df[pd.to_numeric(export_df[bin_cols[0]], errors='coerce') != 1]
        return export_df.to_csv(index=False).encode('utf-8-sig')



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

