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


def build_file_correlation_workbook(f, result):
    """Build the two-file correlation workbook with two sheets.

    需求（2026-08）：Limit 对比与测试值对比拆分为两个 Sheet ——

    Sheet「Limit对比」: 单行表头（Parameters / LSL A / USL A / LSL B /
        USL B / LSL Diff / USL Diff / Unit / 判定）+ 每测试项一行；
        差值按 diff_rule 标红（zero：差值≠0；wider：B 更紧），判定列
        仅按 limit 差异给 PASS/FAIL。

    Sheet「测试值对比」: 模板布局（对齐 Correlation.xlsx）——标题行 +
        两行表头（A 参数列跨两行；'Limit / Unit (Data A)' 组 LSL A/USL A/
        Unit；每序列组标题 ATE/Bench/Delta/%Diff；末列 Comment）+
        每测试项一行；Delta/%Diff 写公式（``=Bench-ATE`` / ``=Delta/ATE``，
        Δ/ATE 口径），|%Diff| > threshold → 红底（静态判定，与 JSON 端点
        一致）；Comment 列仅含超差摘要（N 超差 / PASS）。

    Excelize 默认 Sheet1 被删除——导出的 workbook 只含以上两个 Sheet。

    Parameters
    ----------
    f : excelize.File
    result : dict
        ``compute_file_correlation`` output (rows / serials / limits_only).
    """
    sheet_limit = 'Limit对比'
    sheet_data = '测试值对比'
    f.new_sheet(sheet_limit)   # index 1（默认 Sheet1 之外的首个）
    idx_data = f.new_sheet(sheet_data)
    f.set_active_sheet(idx_data)
    f.delete_sheet('Sheet1')   # excelize 默认空表（先例：export_xlsx_optimized）

    title_style = make_template_title_style(f)
    header_style = make_template_header_style(f)
    data_style = make_template_data_style(f)
    pct_style = make_template_data_style(f, '0.00%')
    red_style = make_template_red_style(f)
    red_pct_style = make_template_red_style(f, '0.00%')

    serials = result.get('serials', [])
    n_seq = len(serials)

    # ── Sheet 1: Limit 对比 ──
    # 固定 9 列：A Parameters | B-E LSL/USL | F/G Diff | H Unit | I 判定
    f.set_cell_value(sheet_limit, 'A1', 'Data A VS Data B（Limit 对比）')
    f.set_cell_style(sheet_limit, 'A1', 'I1', title_style)
    f.merge_cell(sheet_limit, 'A1', 'I1')
    f.set_row_height(sheet_limit, 1, 18)
    f.set_row_height(sheet_limit, 2, 14.25)
    limit_headers = ['Parameters', 'LSL A', 'USL A', 'LSL B', 'USL B',
                     'LSL Diff', 'USL Diff', 'Unit', '判定']
    for c_idx, h in enumerate(limit_headers, 1):
        cell = excelize.coordinates_to_cell_name(c_idx, 2, False)
        f.set_cell_value(sheet_limit, cell, h)
        f.set_cell_style(sheet_limit, cell, cell, header_style)

    row_idx = 3
    for r in result['rows']:
        f.set_cell_value(sheet_limit,
                         excelize.coordinates_to_cell_name(1, row_idx, False),
                         to_native(r['param']))
        for c_idx, key in ((2, 'lsl_a'), (3, 'usl_a'), (4, 'lsl_b'), (5, 'usl_b')):
            cell = excelize.coordinates_to_cell_name(c_idx, row_idx, False)
            v = r.get(key)
            if v is not None:
                f.set_cell_value(sheet_limit, cell, float(v))
            f.set_cell_style(sheet_limit, cell, cell, data_style)
        # LSL/USL Diff（有符号 B−A；按 diff_rule 标红）
        for c_idx, key, fail in ((6, 'lsl_diff', r['lsl_fail']),
                                 (7, 'usl_diff', r['usl_fail'])):
            cell = excelize.coordinates_to_cell_name(c_idx, row_idx, False)
            v = r.get(key)
            if v is not None:
                f.set_cell_value(sheet_limit, cell, float(v))
            f.set_cell_style(sheet_limit, cell, cell,
                             red_style if fail else data_style)
        unit_cell = excelize.coordinates_to_cell_name(8, row_idx, False)
        f.set_cell_value(sheet_limit, unit_cell, to_native(r.get('unit')))
        f.set_cell_style(sheet_limit, unit_cell, unit_cell, data_style)
        verdict_cell = excelize.coordinates_to_cell_name(9, row_idx, False)
        f.set_cell_value(sheet_limit, verdict_cell, _limit_verdict(r))
        f.set_cell_style(sheet_limit, verdict_cell, verdict_cell,
                         red_style if (r['lsl_fail'] or r['usl_fail']) else data_style)
        row_idx += 1

    limit_widths = {'A': 33.125, 'B': 6.0, 'C': 6.25, 'D': 6.0, 'E': 6.25,
                    'F': 7.375, 'G': 7.375, 'H': 9.0, 'I': 9.0}
    for cl, w in limit_widths.items():
        f.set_col_width(sheet_limit, cl, cl, w)
    f.set_panes(sheet_limit, excelize.Panes(
        freeze=True, split=False, x_split=1, y_split=2, top_left_cell='B3',
    ))

    # ── Sheet 2: 测试值对比（模板布局）──
    # A 列 Parameters；B-D 组 'Limit / Unit (Data A)'（LSL A/USL A/Unit）；
    # 序列块自 E（第 5 列）起，每序列 4 列；末列 Comment
    last_col = 5 + n_seq * 4
    comment_col = excelize.column_number_to_name(last_col)

    f.set_cell_value(sheet_data, 'A1', 'Data A VS Data B（测试值对比）')
    f.set_cell_style(sheet_data, 'A1', f'{comment_col}1', title_style)
    f.merge_cell(sheet_data, 'A1', f'{comment_col}1')
    f.set_row_height(sheet_data, 1, 18)
    f.set_row_height(sheet_data, 2, 14.25)

    # Row 2/3: 组标题（参数列跨两行 + Limit/Unit(Data A) 组 + 每序列组标题 +
    # Comment）。注意：合并目标内的所有值必须先写再 merge。
    f.set_cell_value(sheet_data, 'A2', 'Parameters')
    f.set_cell_style(sheet_data, 'A2', 'A3', header_style)
    f.merge_cell(sheet_data, 'A2', 'A3')
    f.set_cell_value(sheet_data, 'B2', 'Limit / Unit (Data A)')
    f.set_cell_style(sheet_data, 'B2', 'D2', header_style)
    f.merge_cell(sheet_data, 'B2', 'D2')
    for c_idx, h in ((2, 'LSL A'), (3, 'USL A'), (4, 'Unit')):
        cell = excelize.coordinates_to_cell_name(c_idx, 3, False)
        f.set_cell_value(sheet_data, cell, h)
        f.set_cell_style(sheet_data, cell, cell, header_style)
    for i, ser in enumerate(serials):
        c0 = 5 + i * 4
        cell1 = excelize.coordinates_to_cell_name(c0, 2, False)
        cell2 = excelize.coordinates_to_cell_name(c0 + 3, 2, False)
        f.set_cell_value(sheet_data, cell1, to_native(ser))
        f.set_cell_style(sheet_data, cell1, cell2, header_style)
        f.merge_cell(sheet_data, cell1, cell2)
    f.set_cell_value(sheet_data, f'{comment_col}2', 'Comment')
    f.set_cell_style(sheet_data, f'{comment_col}2', f'{comment_col}2', header_style)

    # Row 3: 子表头（序列块 + Comment；A3 已随 A2:A3 合并写入）
    for i in range(n_seq):
        base = 5 + i * 4
        for j, h in enumerate(['ATE', 'Bench', 'Delta', '% Diff']):
            cell = excelize.coordinates_to_cell_name(base + j, 3, False)
            f.set_cell_value(sheet_data, cell, h)
            f.set_cell_style(sheet_data, cell, cell, header_style)
    f.set_cell_value(sheet_data, f'{comment_col}3', 'Comment')
    f.set_cell_style(sheet_data, f'{comment_col}3', f'{comment_col}3', header_style)

    # 数据行
    row_idx = 4
    for r in result['rows']:
        # 参数 + Data A 的 Limit/Unit
        f.set_cell_value(sheet_data,
                         excelize.coordinates_to_cell_name(1, row_idx, False),
                         to_native(r['param']))
        f.set_cell_style(sheet_data,
                         excelize.coordinates_to_cell_name(1, row_idx, False),
                         excelize.coordinates_to_cell_name(1, row_idx, False),
                         data_style)
        for c_idx, key in ((2, 'lsl_a'), (3, 'usl_a'), (4, 'unit')):
            cell = excelize.coordinates_to_cell_name(c_idx, row_idx, False)
            v = r.get(key)
            if v is not None:
                f.set_cell_value(sheet_data, cell, float(v) if isinstance(v, (int, float)) else to_native(v))
            f.set_cell_style(sheet_data, cell, cell, data_style)
        for i, cell_data in enumerate(r['cells']):
            base = 5 + i * 4
            a_cell = excelize.coordinates_to_cell_name(base, row_idx, False)
            b_cell = excelize.coordinates_to_cell_name(base + 1, row_idx, False)
            d_cell = excelize.coordinates_to_cell_name(base + 2, row_idx, False)
            p_cell = excelize.coordinates_to_cell_name(base + 3, row_idx, False)
            ate, bench = cell_data.get('ate'), cell_data.get('bench')
            if ate is not None:
                f.set_cell_value(sheet_data, a_cell, float(ate))
            f.set_cell_style(sheet_data, a_cell, a_cell, data_style)
            if bench is not None:
                f.set_cell_value(sheet_data, b_cell, float(bench))
            f.set_cell_style(sheet_data, b_cell, b_cell, data_style)
            if ate is not None and bench is not None:
                is_fail = cell_data['fail']
                # Δ/ATE 口径（用户确认）；标红按 Python 计算值静态决定。
                # excelize 会自动补 '=' 前缀，公式字符串不带 '='。
                f.set_cell_formula(sheet_data, d_cell, f'{b_cell}-{a_cell}')
                f.set_cell_formula(sheet_data, p_cell, f'{d_cell}/{a_cell}')
                f.set_cell_style(sheet_data, d_cell, d_cell,
                                 red_style if is_fail else data_style)
                f.set_cell_style(sheet_data, p_cell, p_cell,
                                 red_pct_style if is_fail else pct_style)

        comment = _data_comment(r)
        f.set_cell_value(sheet_data, f'{comment_col}{row_idx}', comment)
        f.set_cell_style(sheet_data, f'{comment_col}{row_idx}',
                         f'{comment_col}{row_idx}', data_style)
        row_idx += 1

    # 列宽（A 参数列 33.125；Limit/Unit 6-9；序列块统一 9.125；Comment 9）
    f.set_col_width(sheet_data, 'A', 'A', 33.125)
    f.set_col_width(sheet_data, 'B', 'B', 9.0)
    f.set_col_width(sheet_data, 'C', 'C', 9.0)
    f.set_col_width(sheet_data, 'D', 'D', 9.0)
    for i in range(n_seq):
        base = 5 + i * 4
        start = excelize.column_number_to_name(base)
        end = excelize.column_number_to_name(base + 3)
        f.set_col_width(sheet_data, start, end, 9.125)
    f.set_col_width(sheet_data, comment_col, comment_col, 9.0)

    # 冻结前 3 行 + A 列（表头与参数列在横向/纵向滚动时保持可见）
    f.set_panes(sheet_data, excelize.Panes(
        freeze=True, split=False, x_split=1, y_split=3, top_left_cell='B4',
    ))


def _limit_verdict(r) -> str:
    """Limit 判定：仅按 LSL/USL Diff 规则给出 PASS/FAIL。"""
    return 'FAIL' if (r.get('lsl_fail') or r.get('usl_fail')) else 'PASS'


def _data_comment(r) -> str:
    """测试值判定摘要：超差数量（Limit 差异已在 Limit Sheet 判定列）。"""
    fail_count = r.get('fail_count') or 0
    return 'PASS' if not fail_count else f'{fail_count} 超差'

