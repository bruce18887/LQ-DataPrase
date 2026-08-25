"""Excel builder functions extracted from views.py.

Each function accepts an excelize file handle (``f``) and writes
content to one or more sheets.  The caller is responsible for creating
the file handle and saving/serializing the result.
"""

import pandas as pd
import excelize

from apps.analysis.services.statistics import get_1d_from
from .excelize_helpers import (
    COLOR_FONT_DARK, COLOR_ORIGINAL_LIMIT, COLOR_SIGMA_TIGHT, COLOR_SIGMA_NOT_TIGHT,
    make_header_style,
    make_template_title_style, make_template_header_style,
    make_template_data_style, make_template_red_style,
    to_native,
)


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


def build_file_correlation_sheet(f, result):
    """Build the two-file correlation sheet in template layout.

    Layout mirrors ``Data/TemplateExport/Correlation_Excel/Correlation.xlsx``:

        Row 1 : title "Data A VS Data B" (merged across the table)
        Row 2 : A2 'Corr Result' (merged A2:A3) | B2 'Test Name' (merged B2:I2)
                | per-serial block '1'/'2'/... (J2:M2, N2:Q2, ...) | 'Comment'
        Row 3 : Parameters | LSL A | USL A | LSL B | USL B | LSL Diff
                | USL Diff | Unit | per-serial ATE/Bench/Delta/% Diff | Comment
        Rows 4+ : one row per test item, in FILE 1 column order.

    - Delta / %Diff are written as Excel formulas (``=Bench-ATE`` and
      ``=Delta/ATE`` — Δ/ATE 口径, user-confirmed) only when both sides have
      finite values; %Diff cells use the ``0.00%`` number format.
    - Red fills are decided statically from the same computed values as the
      JSON endpoint (embedded in ``result``), so export and panel agree:
      |%Diff| > threshold → Delta/%Diff red; LSL/USL Diff rule fail → red.
    - ``limits_only`` result → no per-serial columns, only the limit columns.

    Parameters
    ----------
    f : excelize.File
    result : dict
        ``compute_file_correlation`` output (rows / serials / limits_only).
    """
    sheet_name = '文件相关性对比'
    sheet_index = f.new_sheet(sheet_name)
    f.set_active_sheet(sheet_index)

    title_style = make_template_title_style(f)
    header_style = make_template_header_style(f)
    data_style = make_template_data_style(f)
    pct_style = make_template_data_style(f, '0.00%')
    red_style = make_template_red_style(f)
    red_pct_style = make_template_red_style(f, '0.00%')

    serials = result.get('serials', [])
    n_seq = len(serials)
    # 固定列: A角 B参数 C-F limits G/H Diff I Unit; 序列块从第 10 列(J) 起,
    # 每序列 4 列 (ATE/Bench/Delta/%Diff); 末列 Comment（纯列字母）
    last_col = 10 + n_seq * 4
    comment_col = excelize.column_number_to_name(last_col)

    # Row 1: 标题跨全表合并
    f.set_cell_value(sheet_name, 'A1', 'Data A VS Data B')
    f.set_cell_style(sheet_name, 'A1', f'{comment_col}1', title_style)
    f.merge_cell(sheet_name, 'A1', f'{comment_col}1')
    f.set_row_height(sheet_name, 1, 18)
    f.set_row_height(sheet_name, 2, 14.25)

    # Row 2: 组标题
    f.set_cell_value(sheet_name, 'A2', 'Corr Result')
    f.set_cell_style(sheet_name, 'A2', 'A2', header_style)
    f.merge_cell(sheet_name, 'A2', 'A3')
    f.set_cell_value(sheet_name, 'B2', 'Test Name')
    f.set_cell_style(sheet_name, 'B2', 'I2', header_style)
    f.merge_cell(sheet_name, 'B2', 'I2')
    for i, ser in enumerate(serials):
        c0 = 10 + i * 4
        cell1 = excelize.coordinates_to_cell_name(c0, 2, False)
        cell2 = excelize.coordinates_to_cell_name(c0 + 3, 2, False)
        f.set_cell_value(sheet_name, cell1, to_native(ser))
        f.set_cell_style(sheet_name, cell1, cell2, header_style)
        f.merge_cell(sheet_name, cell1, cell2)
    # 模板 R2/R3 均为 'Comment'（单格未合并）
    f.set_cell_value(sheet_name, f'{comment_col}2', 'Comment')
    f.set_cell_style(sheet_name, f'{comment_col}2', f'{comment_col}2', header_style)

    # Row 3: 子表头
    sub_headers = ['Parameters', 'LSL A', 'USL A', 'LSL B', 'USL B',
                   'LSL Diff', 'USL Diff', 'Unit']
    for c_idx, h in enumerate(sub_headers, 2):
        cell = excelize.coordinates_to_cell_name(c_idx, 3, False)
        f.set_cell_value(sheet_name, cell, h)
        f.set_cell_style(sheet_name, cell, cell, header_style)
    for i in range(n_seq):
        base = 10 + i * 4
        for j, h in enumerate(['ATE', 'Bench', 'Delta', '% Diff']):
            cell = excelize.coordinates_to_cell_name(base + j, 3, False)
            f.set_cell_value(sheet_name, cell, h)
            f.set_cell_style(sheet_name, cell, cell, header_style)
    f.set_cell_value(sheet_name, f'{comment_col}3', 'Comment')
    f.set_cell_style(sheet_name, f'{comment_col}3', f'{comment_col}3', header_style)

    # 数据行
    row_idx = 4
    for r in result['rows']:
        # 参数 + Limits（无 limit 留空）
        f.set_cell_value(sheet_name,
                         excelize.coordinates_to_cell_name(2, row_idx, False),
                         to_native(r['param']))
        for c_idx, key in ((3, 'lsl_a'), (4, 'usl_a'), (5, 'lsl_b'), (6, 'usl_b')):
            cell = excelize.coordinates_to_cell_name(c_idx, row_idx, False)
            v = r.get(key)
            if v is not None:
                f.set_cell_value(sheet_name, cell, float(v))
            f.set_cell_style(sheet_name, cell, cell, data_style)
        # LSL/USL Diff（有符号 B−A；按 diff_rule 标红）
        for c_idx, key, fail in ((7, 'lsl_diff', r['lsl_fail']),
                                 (8, 'usl_diff', r['usl_fail'])):
            cell = excelize.coordinates_to_cell_name(c_idx, row_idx, False)
            v = r.get(key)
            if v is not None:
                f.set_cell_value(sheet_name, cell, float(v))
            f.set_cell_style(sheet_name, cell, cell,
                             red_style if fail else data_style)
        # Unit
        unit_cell = excelize.coordinates_to_cell_name(9, row_idx, False)
        f.set_cell_value(sheet_name, unit_cell, to_native(r.get('unit')))
        f.set_cell_style(sheet_name, unit_cell, unit_cell, data_style)

        # 每序列 4 列块（单侧有值只写该侧，同模板）
        for i, cell_data in enumerate(r['cells']):
            base = 10 + i * 4
            a_cell = excelize.coordinates_to_cell_name(base, row_idx, False)
            b_cell = excelize.coordinates_to_cell_name(base + 1, row_idx, False)
            d_cell = excelize.coordinates_to_cell_name(base + 2, row_idx, False)
            p_cell = excelize.coordinates_to_cell_name(base + 3, row_idx, False)
            ate, bench = cell_data.get('ate'), cell_data.get('bench')
            if ate is not None:
                f.set_cell_value(sheet_name, a_cell, float(ate))
            f.set_cell_style(sheet_name, a_cell, a_cell, data_style)
            if bench is not None:
                f.set_cell_value(sheet_name, b_cell, float(bench))
            f.set_cell_style(sheet_name, b_cell, b_cell, data_style)
            if ate is not None and bench is not None:
                is_fail = cell_data['fail']
                # Δ/ATE 口径（用户确认）；标红按 Python 计算值静态决定。
                # excelize 会自动补 '=' 前缀，公式字符串不带 '='。
                f.set_cell_formula(sheet_name, d_cell, f'{b_cell}-{a_cell}')
                f.set_cell_formula(sheet_name, p_cell, f'{d_cell}/{a_cell}')
                f.set_cell_style(sheet_name, d_cell, d_cell,
                                 red_style if is_fail else data_style)
                f.set_cell_style(sheet_name, p_cell, p_cell,
                                 red_pct_style if is_fail else pct_style)

        # Comment: 判定摘要
        comment = _row_comment(r)
        if comment:
            f.set_cell_value(sheet_name, f'{comment_col}{row_idx}', comment)
        f.set_cell_style(sheet_name, f'{comment_col}{row_idx}',
                         f'{comment_col}{row_idx}', data_style)
        row_idx += 1

    # 列宽对齐模板（序列块统一 9.125）
    widths = {'A': 10.375, 'B': 33.125, 'C': 6.0, 'D': 6.25, 'E': 6.0, 'F': 6.25,
              'G': 7.375, 'H': 7.375, 'I': 9.0}
    for cl, w in widths.items():
        f.set_col_width(sheet_name, cl, cl, w)
    for i in range(n_seq):
        base = 10 + i * 4
        start = excelize.column_number_to_name(base)
        end = excelize.column_number_to_name(base + 3)
        f.set_col_width(sheet_name, start, end, 9.125)
    f.set_col_width(sheet_name, comment_col, comment_col, 9.0)

    # 冻结前 3 行 + A 列（表头与角列在横向/纵向滚动时保持可见）
    f.set_panes(sheet_name, excelize.Panes(
        freeze=True, split=False, x_split=1, y_split=3, top_left_cell='C4',
    ))


def _row_comment(r) -> str:
    """判定摘要：'PASS' 或失败原因（超差数 / LSL/USL Diff）。"""
    parts = []
    if r.get('fail_count'):
        parts.append(f"{r['fail_count']} 超差")
    if r.get('lsl_fail'):
        parts.append('LSL Diff')
    if r.get('usl_fail'):
        parts.append('USL Diff')
    return 'PASS' if not parts else '；'.join(parts)

