"""Optimized Excel export: excelize 表头模板 + 手写数据区 XML。

策略（实测 CTA8280F 10000×188：35s → 2.1s，POC 见 tasks/poc_handwritten_xml.py）：
- excelize 绑定层每值 17μs Python→C 转换是硬瓶颈（188 万值 ≈ 30s），
  StreamWriter 与普通 API 同样受限于此（绑定逐值 py_value_to_c_interface）。
- 表头/统计区（行 1-11，调用量小）+ 样式/冻结/筛选/列宽/隐藏列由 excelize 生成（毫秒级）；
- 数据区（行 12+，万行 × 百列）绕开绑定层：手写 sheet XML（数值 <v>、
  字符串 inlineStr、样式直接带 ID）+ zip 重打包，字符串拼接无逐值 ctypes。

样式（对齐用户截图默认风格，2026-08-26）：
- 表头/统计区：白底黑字细灰边框；数据区同款白底；
- fail 单元格（SoftBin 列 + 失败测试项）：纯红底 #FF0000 + 黑加粗；
- 数据恰好等于上下限（未超限但贴限值）：橙底 #FFC000；
- 每列宽度按内容自适应；hidden_columns 中的列保留数据但设为 Excel 隐藏列。
"""

import io
import os
import tempfile
import zipfile
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Set
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import pandas as pd
import excelize

from apps.analysis.services.statistics import (
    ensure_numeric, get_bin_column_name, detect_fail_data,
    get_columns_with_limits, compute_cpk, filter_finite, get_1d_from,
)
from apps.datafiles.parsers.base import SYSTEM_COLUMNS
from .columns import measurable_numeric_columns
from .spec_limits import spec_limits
from .excelize_helpers import (
    make_plain_header_style, make_plain_data_style,
    make_plain_red_style, make_plain_orange_style,
    to_native, save_excelize,
)

_EPOCH = datetime(1899, 12, 30)

# 自适应列宽参数（Excel 默认字体 11pt Calibri 下「字符数 → 宽度单位」的近似换算）
_WIDTH_FACTOR = 1.12
_WIDTH_PADDING = 2.0
_WIDTH_MIN = 8.0
_WIDTH_MAX = 64.0
# 数据值长度测量采样上限（超大型文件 40M+ 单元格 astype(str) 会拖慢导出；
# 列宽取 5k 行样本已足够贴近真实内容宽度）
_WIDTH_SAMPLE_ROWS = 5000


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


def _data_rows_xml(rows: List[List], col_names: List[str], col_letters: List[str],
                   data_start_row: int, data_style_id: int, red_style_id: int,
                   orange_style_id: int, fail_by_pos: Dict[int, Set[str]],
                   orange_by_pos: Dict[int, Set[str]]) -> str:
    """生成数据区 <row> 元素串（逐格样式）。

    fail 单元格（SoftBin + 失败测试项）→ 红样式；与上下限重叠的单元格 → 橙样式；
    其余 → 数据样式。仅标 red/orange 命中格，绝不给整行染色。
    """
    out = []
    append = out.append
    for i, row in enumerate(rows):
        row_num = data_start_row + i
        fails = fail_by_pos.get(i)
        oranges = orange_by_pos.get(i)
        cells = []
        for col_idx, v in enumerate(row):
            if fails is not None and col_names[col_idx] in fails:
                sid = red_style_id
            elif oranges is not None and col_names[col_idx] in oranges:
                sid = orange_style_id
            else:
                sid = data_style_id
            cells.append(f'<c r="{col_letters[col_idx]}{row_num}" s="{sid}"' + _cell_body(v))
        append(f'<row r="{row_num}">{"".join(cells)}</row>')
    return ''.join(out)


def _limit_overlap_cells(df: pd.DataFrame, metadata: Dict) -> Dict[int, Set[str]]:
    """「数据恰好等于上下限」的单元格集合 {行位置: {列名}}（橙标目标）。

    仅对带数值上下限的列比较（与 detect_fail_data 同一限值口径）；超限单元格
    由 fail_cells 承担红标，此处只收集 =min 或 =max（与限值重叠）的单元格。
    """
    orange_by_pos: Dict[int, Set[str]] = {}
    for col in get_columns_with_limits(df, metadata):
        min_val = float(str(metadata['mins'][col]).strip())
        max_val = float(str(metadata['maxs'][col]).strip())
        col_data = ensure_numeric(df, col)
        mask = (col_data == min_val) | (col_data == max_val)
        for pos in mask.to_numpy().nonzero()[0]:
            orange_by_pos.setdefault(int(pos), set()).add(col)
    return orange_by_pos


def _fail_cells_by_position(df: pd.DataFrame, fail_cells: Dict[int, List[str]]) -> Dict[int, Set[str]]:
    """detect_fail_data 的 fail_cells（键=df.index 值）→ 键=行位置（0 起）。"""
    return {
        int(df.index.get_loc(idx)): set(cols)
        for idx, cols in fail_cells.items()
    }


def _auto_fit_widths(df: pd.DataFrame, header_rows: Sequence[Sequence]) -> List[float]:
    """每列自适应列宽：表头区（行 1-11 文本）与数据值的最大字符数 → 宽度。

    数据值用向量化 astype(str).str.len() 测量（NaN→"nan" 为 3 字符，影响
    上限 +3，可忽略）；头部行文本按原字符串长度。
    """
    n_cols = len(df.columns)
    max_chars = [0] * n_cols
    for row in header_rows:
        for i in range(min(n_cols, len(row))):
            v = row[i]
            if v is None:
                continue
            s = '' if isinstance(v, float) and v != v else str(v)
            if len(s) > max_chars[i]:
                max_chars[i] = len(s)
    if len(df):
        sample = df.head(_WIDTH_SAMPLE_ROWS)
        for i, col in enumerate(df.columns):
            try:
                length = sample[col].astype(str).str.len()
                m = int(length.max()) if len(length) else 0
                if m > max_chars[i]:
                    max_chars[i] = m
            except (ValueError, TypeError):
                pass  # 列损坏时跳过该列测量，仅以表头宽度为准
    return [
        min(_WIDTH_MAX, max(_WIDTH_MIN, round(c * _WIDTH_FACTOR + _WIDTH_PADDING, 1)))
        for c in max_chars
    ]


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


def export_to_xlsx_optimized(df: pd.DataFrame, metadata: Dict,
                             hidden_columns: Optional[Sequence[str]] = None) -> bytes:
    f = excelize.new_file()
    try:
        sheet_name = "Data"
        sheet_index = f.new_sheet(sheet_name)
        f.set_active_sheet(sheet_index)
        # 删除 excelize 默认 Sheet1：导出文件只保留 Data 一个 sheet
        try:
            f.delete_sheet("Sheet1")
        except Exception:  # noqa: BLE001 — 无 Sheet1（异常情况）时忽略
            pass

        cols = df.columns.tolist()
        num_cols = len(cols)
        last_col_name = excelize.column_number_to_name(num_cols)

        # Shared styles（默认风格：白底黑字细边框 + 红/橙标色）
        header_style_id = make_plain_header_style(f)
        data_style_id = make_plain_data_style(f)
        red_style_id = make_plain_red_style(f)
        orange_style_id = make_plain_orange_style(f)

        # ── 表头与统计区（行 1-11）：excelize 普通 API（调用量小，毫秒级）──
        f.set_sheet_row(sheet_name, "A1", cols)
        header_rows = [cols]
        for row_idx, key in enumerate(("units", "mins", "maxs"), start=2):
            row_vals = [to_native(metadata[key].get(col, "")) for col in cols]
            header_rows.append(row_vals)
            f.set_sheet_row(sheet_name, f"A{row_idx}", row_vals)

        # 可分析数值列（缺陷 #11）：旧白名单 ``dtype in ['int64','float64']`` 会漏掉
        # int32/float32/UInt8 等窄 dtype；pandas 3.0 下字符串列是 str dtype（== object
        # 恒 False）；bool 列（Dut_Pass）虽是数值 dtype 但不是测量值，须排除。
        numeric_cols = measurable_numeric_columns(df)
        col_positions = {col: i for i, col in enumerate(cols)}

        format_type = metadata.get('format', 'CTA8290D')

        # 统计行（Min/Avg/Max/Range/STD/CPK）只针对「测试项」数值列：截图语义——
        # 记录级列（Serial_No/Part_No/SW_Bin 等 SYSTEM_COLUMNS）不参与统计，
        # 第一列（列名标签）不被记录列统计值覆盖。
        system_cols = SYSTEM_COLUMNS.get(format_type, [])
        stats_cols = [c for c in numeric_cols if c not in system_cols]

        stats_values = {}
        for col_name in stats_cols:
            # filter_finite 与屏幕侧同源：NaN 与 ±inf 一并滤掉（inf 会让
            # mean=inf / std=nan，再被 excelize 写成文本 'NaN'）
            col_data = filter_finite(get_1d_from(df, col_name))
            if len(col_data) > 0:
                # 统计值统一保留 4 位小数（对齐截图 Min/Avg/Max/Range/STD/CPK 行）；
                # CPK 用**未舍入**原值计算，避免二次舍入（缺陷 #1）——窄分布上
                # round(std, 4) 会归零，把 0 喂给 compute_cpk 得到恒定 CPK=0。
                raw_min = float(col_data.min())
                raw_avg = float(col_data.mean())
                raw_max = float(col_data.max())
                # ddof=0（总体标准差）：与 computations.compute_range_statistics /
                # histogram / buyoff / multi_lot 全仓口径一致（缺陷 #1）。pandas 默认
                # ddof=1，n=10 时 σ 偏大 √(10/9)=5.4%，CPK 反向偏小 5.4%。
                raw_std = float(col_data.std(ddof=0))

                col_min = round(raw_min, 4)
                col_avg = round(raw_avg, 4)
                col_max = round(raw_max, 4)
                col_std = round(raw_std, 4)
                # Range 由**表格里展示的** Max − Min 得出（缺陷 #2）：Min/Max 各自
                # 已 round 到 4 位，用未舍入极值相减会出现 Range ≠ Max − Min。
                col_range = round(col_max - col_min, 4)

                # 限值缺失/占位 → None（不回退 0.0），compute_cpk 对 None 返回 0.0
                min_val, max_val = spec_limits(metadata, col_name)
                col_cpk = round(compute_cpk(raw_avg, raw_std, min_val, max_val)['cpk'], 4)

                pos = col_positions[col_name]
                for label, val in (
                    ("Min", col_min), ("Avg", col_avg), ("Max", col_max),
                    ("Range", col_range), ("STD", col_std), ("CPK", col_cpk),
                ):
                    stats_values.setdefault(label, {})[pos] = val

        for i, label in enumerate(["Min", "Avg", "Max", "Range", "STD", "CPK"]):
            row_vals = [""] * num_cols
            for pos, val in stats_values.get(label, {}).items():
                row_vals[pos] = val
            # 第一列恒为统计行名（截图语义），不会被任何列统计值覆盖
            row_vals[0] = label
            header_rows.append(row_vals)
            f.set_sheet_row(sheet_name, f"A{5 + i}", row_vals)

        # 样式（范围调用）：表头行 + 统计区
        f.set_cell_style(sheet_name, f"A1", f"{last_col_name}1", header_style_id)
        f.set_cell_style(sheet_name, f"A2", f"{last_col_name}11", data_style_id)

        target_bin_col = get_bin_column_name(format_type)
        target_bin_col_idx = cols.index(target_bin_col) + 1 if target_bin_col in cols else 1

        # 自适应列宽（逐列 set_col_width，毫秒级）
        widths = _auto_fit_widths(df, header_rows)
        for i, w in enumerate(widths):
            letter = excelize.column_number_to_name(i + 1)
            f.set_col_width(sheet_name, letter, letter, w)

        # 默认隐藏列：列保留在文件中，仅设 Excel 隐藏属性
        if hidden_columns:
            for col in hidden_columns:
                if col in cols:
                    letter = excelize.column_number_to_name(cols.index(col) + 1)
                    f.set_col_visible(sheet_name, letter, False)

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

        # fail 单元格（SoftBin + 失败测试项）→ 红；恰好等于限值 → 橙；其余白底
        _, _, fail_cells = detect_fail_data(df, metadata)
        fail_by_pos = _fail_cells_by_position(df, fail_cells)
        orange_by_pos = _limit_overlap_cells(df, metadata)

        data_xml = _data_rows_xml(
            df_values, cols, col_letters, data_start_row,
            data_style_id, red_style_id, orange_style_id,
            fail_by_pos, orange_by_pos,
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
