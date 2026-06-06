"""Style constants and factories for Gage R&R Excel reports."""

import numpy as np
import excelize
from apps.export.excelize_helpers import COLOR_BORDER, COLOR_FONT_DARK, COLOR_DATA_BG, COLOR_RED_BG

# ── Constants ──
NON_NUMERIC_KEYWORDS = ['min', 'max', 'lower limit', 'upper limit', 'n/a', 'na', '-', 'none']
FILL_GRAY_HEX = "E0E0E0"
FILL_LIGHT_BLUE_HEX = "D6EAF8"

# ── Style Factories ──

def make_info_label_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=10, color=COLOR_FONT_DARK, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center"),
    ))

def make_info_value_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center"),
    ))

def make_warning_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(size=9, color=COLOR_RED_BG, family="Calibri"),
        alignment=excelize.Alignment(horizontal="left", vertical="center", wrap_text=True),
    ))

def make_good_rate_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=11, color="27AE60", family="Calibri"),
    ))

def make_bad_rate_style(f):
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=11, color="FFFFFF", family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
    ))

def make_rr_pct_style(f):
    return f.new_style(excelize.Style(custom_num_fmt="0.000%"))

def make_red_rr_pct_style(f):
    return f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
        custom_num_fmt="0.000%",
    ))

# ── Helpers ──

def _set_cell(f, sheet, cell, value):
    if isinstance(value, np.generic):
        value = value.item()
    f.set_cell_value(sheet, cell, value)
