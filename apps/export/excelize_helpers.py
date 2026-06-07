"""Shared excelize styling helpers for all export modules."""

import os, tempfile
import pandas as pd
import numpy as np
import excelize

# ── Color Palette (matches old project) ──
COLOR_HEADER_BG = "2C3E50"
COLOR_HEADER_FONT = "FFFFFF"
COLOR_DATA_BG = "F8F9FA"
COLOR_ALT_ROW = "EDF2F7"
COLOR_BORDER = "BDC3C7"
COLOR_FONT_DARK = "2C3E50"
COLOR_RED_BG = "F5B7B1"
COLOR_ORIGINAL_LIMIT = "D6EAF8"
COLOR_SIGMA_TIGHT = "F5B7B1"
COLOR_SIGMA_NOT_TIGHT = "FCF3CF"

# CPK color fills
CPK_A_FILL = ["4CAF50"]   # green — CPK >= 1.67
CPK_B_FILL = ["8BC34A"]   # light green — CPK >= 1.33
CPK_C_FILL = ["FFC107"]   # yellow — CPK >= 1.0
CPK_D_FILL = ["F44336"]   # red — CPK < 1.0

# ── Style Builders ──

def make_header_style(f, font_size=12):
    """Dark header with white bold text, medium borders."""
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=float(font_size), color=COLOR_HEADER_FONT, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_HEADER_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=2),
            excelize.Border(type="top", color=COLOR_BORDER, style=2),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=2),
            excelize.Border(type="right", color=COLOR_BORDER, style=2),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def make_data_style(f):
    """Light gray background, dark text, thin borders."""
    return f.new_style(excelize.Style(
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


def make_red_style(f):
    """Red background, white bold text — for fail cell highlighting."""
    return f.new_style(excelize.Style(
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


def make_unit_style(f):
    """Italic 9pt for unit rows."""
    return f.new_style(excelize.Style(
        font=excelize.Font(size=9, color=COLOR_FONT_DARK, italic=True, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_DATA_BG], pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def make_title_style(f):
    """Large title style for report headers."""
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=16, color=COLOR_HEADER_FONT, family="Calibri"),
        fill=excelize.Fill(type="pattern", color=[COLOR_HEADER_BG], pattern=1),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def make_cpk_fill(f, cpk_val):
    """Return fill colors list for a CPK value."""
    if cpk_val >= 1.67:
        return CPK_A_FILL
    elif cpk_val >= 1.33:
        return CPK_B_FILL
    elif cpk_val >= 1.0:
        return CPK_C_FILL
    else:
        return CPK_D_FILL


def make_cpk_style(f, cpk_val):
    """Create a style with CPK-based fill color."""
    fill_color = make_cpk_fill(f, cpk_val)
    return f.new_style(excelize.Style(
        font=excelize.Font(bold=True, size=10,
                           color="FFFFFF" if cpk_val < 1.33 else "000000",
                           family="Calibri"),
        fill=excelize.Fill(type="pattern", color=fill_color, pattern=1),
        border=[
            excelize.Border(type="left", color=COLOR_BORDER, style=1),
            excelize.Border(type="top", color=COLOR_BORDER, style=1),
            excelize.Border(type="bottom", color=COLOR_BORDER, style=1),
            excelize.Border(type="right", color=COLOR_BORDER, style=1),
        ],
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


# ── Border Factories ──

def thin_border(color=COLOR_BORDER):
    """Return a list of 4 thin borders (left/top/bottom/right) for reuse."""
    return [excelize.Border(type=t, color=color, style=1) for t in ("left", "top", "bottom", "right")]


def medium_border(color=COLOR_BORDER):
    """Return a list of 4 medium borders (left/top/bottom/right) for reuse."""
    return [excelize.Border(type=t, color=color, style=2) for t in ("left", "top", "bottom", "right")]


# ── Utilities ──

def save_excelize(f):
    """Save excelize workbook to bytes via temp file."""
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        f.save_as(tmp_path)
        f.close()
        with open(tmp_path, 'rb') as fh:
            return fh.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def to_native(val):
    """Convert a (possibly numpy) value to a native Python type for excelize."""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (ValueError, TypeError):
        pass
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, np.integer)):
        return int(val)
    if isinstance(val, (float, np.floating)):
        if pd.isna(val):
            return ""
        return float(val)
    if hasattr(val, 'item'):
        try:
            native = val.item()
            try:
                if pd.isna(native):
                    return ""
            except (ValueError, TypeError):
                pass
            return native
        except (ValueError, TypeError):
            pass
    return str(val) if val is not None else ""


def auto_widths(f, sheet, col_count, min_width=8, max_width=40):
    """Set all column A..N to auto-computed widths.  Quick heuristic."""
    for i in range(1, col_count + 1):
        cl = excelize.column_number_to_name(i)
        f.set_col_width(sheet, cl, cl, min_width)
