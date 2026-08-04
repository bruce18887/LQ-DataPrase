"""Optimized Excel export: excelize 表头模板 + 手写数据区 XML。

策略（实测 CTA8280F 10000×188：35s → 2.1s，POC 见 tasks/poc_handwritten_xml.py）：
- excelize 绑定层每值 17μs Python→C 转换是硬瓶颈（188 万值 ≈ 30s），
  StreamWriter 与普通 API 同样受限于此（绑定逐值 py_value_to_c_interface）。
- 表头/统计区（行 1-11，调用量小）+ 样式/冻结/筛选由 excelize 生成（毫秒级）；
- 数据区（行 12+，万行 × 百列）绕开绑定层：手写 sheet XML（数值 <v>、
  字符串 inlineStr、样式直接带 ID）+ zip 重打包，字符串拼接无逐值 ctypes。
"""

import io
import os
import tempfile
import zipfile
from datetime import date, datetime
from typing import Dict, List, Set
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import pandas as pd
import excelize

from apps.analysis.services.statistics import (
    ensure_numeric, get_bin_column_name, detect_fail_data,
    compute_cpk,
)
from .excelize_helpers import (
    make_header_style, make_data_style, make_red_style,
    to_native, save_excelize,
)

_EPOCH = datetime(1899, 12, 30)


def _vectorized_native_rows(df: pd.DataFrame) -> List[List]:
    """DataFrame → 原生 Python 标量行列表（NaN/None→''，numpy 标量→Python 标量）。

    与 export_csv._convert_to_native_type 逐值语义等价，但向量化。
    注意：excelize 绑定 py_value_to_c_interface 只接受原生类型，
    numpy 标量会静默丢值，因此必须先经 astype(object) 归一化。
    """
    cleaned = df.astype(object).where(pd.notna(df), "").fillna("")
    return cleaned.values.tolist()


def _datetime_serial(v) -> float:
    """datetime/date → Excel 序列号（1899-12-30 起天数，含小数时间）。"""
    if isinstance(v, datetime):
        delta = v - _EPOCH
        return delta.days + delta.seconds / 86400.0
    if isinstance(v, date):
        return (v - _EPOCH.date()).days
    return None


def _data_rows_xml(rows: List[List], col_letters: List[str], data_start_row: int,
                   data_style_id: int, red_style_id: int,
                   fail_rows: Set[int]) -> str:
    """生成数据区 <row> 元素串。fail 行整行用红样式，其余用数据样式。"""
    out = []
    append = out.append
    for i, row in enumerate(rows):
        row_num = data_start_row + i
        sid = red_style_id if i in fail_rows else data_style_id
        cells = [''.join((
            f'<c r="{col_letters[col_idx]}{row_num}" s="{sid}"',
            _cell_body(v),
        )) for col_idx, v in enumerate(row)]
        append(f'<row r="{row_num}">{"".join(cells)}</row>')
    return ''.join(out)


def _cell_body(value) -> str:
    """单元格 <c> 元素的属性与内容部分（<c r=.. s=..> 之后的剩余）。"""
    if value == '' or value is None:
        return '></c>'
    if isinstance(value, bool):
        return f' t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return f'><v>{int(value)}</v></c>'
    if isinstance(value, (float,)):
        if value != value or value in (float('inf'), float('-inf')):
            return f' t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
        return f'><v>{value!r}</v></c>'
    if isinstance(value, (datetime, date)):
        return f'><v>{_datetime_serial(value)!r}</v></c>'
    return f' t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _find_sheet_path(z: zipfile.ZipFile, sheet_name: str) -> str:
    """通过 workbook.xml + rels 定位 sheet_name 对应的 worksheets/*.xml 路径。"""
    wb_xml = z.read('xl/workbook.xml').decode('utf-8')
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rattr = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
    root = ElementTree.fromstring(wb_xml)
    rid = None
    for sheet in root.findall('.//m:sheets/m:sheet', ns):
        if sheet.get('name') == sheet_name:
            rid = sheet.get(rattr)
            break
    if not rid:
        raise KeyError(f'sheet {sheet_name} not found')
    rels = z.read('xl/_rels/workbook.xml.rels').decode('utf-8')
    rroot = ElementTree.fromstring(rels)
    rns = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
    for rel in rroot.findall('r:Relationship', rns):
        if rel.get('Id') == rid:
            return 'xl/' + rel.get('Target')
    raise KeyError(f'relationship {rid} not found')


def _repack_xlsx(template: bytes, sheet_path: str, new_sheet_xml: str) -> bytes:
    """zip 重打包：替换 sheet_path 条目（手写数据区），其余条目原样保留。"""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template)) as zin:
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = new_sheet_xml.encode('utf-8') if item.filename == sheet_path else zin.read(item.filename)
                zout.writestr(item, data)
    return out.getvalue()


def export_to_xlsx_optimized(df: pd.DataFrame, metadata: Dict) -> bytes:
    f = excelize.new_file()
    try:
        sheet_name = "Data"
        sheet_index = f.new_sheet(sheet_name)
        f.set_active_sheet(sheet_index)

        cols = df.columns.tolist()
        num_cols = len(cols)
        last_col_name = excelize.column_number_to_name(num_cols)

        # Shared styles from excelize_helpers
        header_style_id = make_header_style(f, 12)
        data_style_id = make_data_style(f)
        red_style_id = make_red_style(f)

        # ── 表头与统计区（行 1-11）：excelize 普通 API（调用量小，毫秒级）──
        f.set_sheet_row(sheet_name, "A1", cols)
        for row_idx, key in enumerate(("units", "mins", "maxs"), start=2):
            row_vals = [to_native(metadata[key].get(col, "")) for col in cols]
            f.set_sheet_row(sheet_name, f"A{row_idx}", row_vals)

        numeric_cols = [col for col in cols if df[col].dtype in ['int64', 'float64']]
        col_positions = {col: i for i, col in enumerate(cols)}

        stats_values = {}
        for col_name in numeric_cols:
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

                pos = col_positions[col_name]
                for label, val in (
                    ("Min", col_min), ("Avg", col_avg), ("Max", col_max),
                    ("Range", col_range), ("STD", col_std), ("CPK", col_cpk),
                ):
                    stats_values.setdefault(label, {})[pos] = val

        for i, label in enumerate(["Min", "Avg", "Max", "Range", "STD", "CPK"]):
            row_vals = [""] * num_cols
            row_vals[0] = label
            for pos, val in stats_values.get(label, {}).items():
                row_vals[pos] = val
            f.set_sheet_row(sheet_name, f"A{5 + i}", row_vals)

        # 样式（范围调用）：表头行 + 统计区
        f.set_cell_style(sheet_name, f"A1", f"{last_col_name}1", header_style_id)
        f.set_cell_style(sheet_name, f"A2", f"{last_col_name}11", data_style_id)

        format_type = metadata.get('format', 'CTA8290D')
        target_bin_col = get_bin_column_name(format_type)
        target_bin_col_idx = cols.index(target_bin_col) + 1 if target_bin_col in cols else 1

        fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata)

        bin_col_letter = excelize.column_number_to_name(target_bin_col_idx + 1)
        f.set_panes(sheet_name, excelize.Panes(
            freeze=True,
            split=False,
            x_split=target_bin_col_idx,
            y_split=11,
            top_left_cell=f"{bin_col_letter}12",
        ))
        last_cell = excelize.coordinates_to_cell_name(num_cols, 11, False)
        f.auto_filter(sheet_name, f"A11:{last_cell}", [])

        template = save_excelize(f)

        # ── 数据区（行 12+）：手写 sheet XML，绕开绑定层逐值 ctypes ──
        df_values = _vectorized_native_rows(df)
        data_start_row = 12
        col_letters = [excelize.column_number_to_name(c) for c in range(1, num_cols + 1)]
        fail_row_indices = set(fail_cells.keys())
        data_xml = _data_rows_xml(
            df_values, col_letters, data_start_row,
            data_style_id, red_style_id, fail_row_indices,
        )

        with zipfile.ZipFile(io.BytesIO(template)) as z:
            sheet_path = _find_sheet_path(z, sheet_name)
            sheet_xml = z.read(sheet_path).decode('utf-8')
        new_sheet_xml = sheet_xml.replace('</sheetData>', data_xml + '</sheetData>', 1)

        return _repack_xlsx(template, sheet_path, new_sheet_xml)

    except Exception as e:
        try:
            f.close()
        except Exception:  # noqa: BLE001 — save_excelize 可能已 close
            pass
        raise e
