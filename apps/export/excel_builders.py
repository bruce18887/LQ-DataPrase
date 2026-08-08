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
    make_header_style, make_data_style, make_red_style, make_unit_style,
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

