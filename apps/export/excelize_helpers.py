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


# ── Correlation 模板样式（对齐 Data/TemplateExport/Correlation_Excel/Correlation.xlsx）──

def make_template_title_style(f):
    """模板标题：等线 14、居中、thin 边框（无填充）。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(size=14, family="等线"),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def make_template_header_style(f):
    """模板表头：Arial 10、居中、thin 边框（无深色底）。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(size=10, family="Arial"),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
    ))


def make_template_data_style(f, num_fmt=None):
    """模板数据格：等线 10、居中、thin 边框（无填充）；可选数字格式。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(size=10, family="等线"),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
        custom_num_fmt=num_fmt,
    ))


def make_template_red_style(f, num_fmt=None):
    """模板 Fail 格：等线 10、浅红底（F5B7B1）、thin 边框；可选数字格式。"""
    return f.new_style(excelize.Style(
        font=excelize.Font(size=10, family="等线"),
        fill=excelize.Fill(type="pattern", color=[COLOR_RED_BG], pattern=1),
        border=thin_border(),
        alignment=excelize.Alignment(horizontal="center", vertical="center"),
        custom_num_fmt=num_fmt,
    ))


# ── Border Factories ──

def thin_border(color=COLOR_BORDER):
    """Return a list of 4 thin borders (left/top/bottom/right) for reuse."""
    return [excelize.Border(type=t, color=color, style=1) for t in ("left", "top", "bottom", "right")]


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
