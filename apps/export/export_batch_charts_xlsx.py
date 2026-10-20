"""Batch charts Excel export with embedded histogram images.

装配顺序固定为：逐参数算总览统计 → 写总览表 → （可选）并行渲染 PNG → 逐参数
写明细 sheet → 保存。openpyxl 在 ``wb.save()`` 时才懒读图片数据，所以每个
BytesIO 必须活到 save() 之后，由编排层持有并在收尾统一关闭。
"""

import io
import os
from concurrent.futures import ProcessPoolExecutor
from typing import NamedTuple

import pandas as pd

import matplotlib
matplotlib.use('Agg')
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XlImage

from apps.analysis.services.statistics import (
    get_1d_from, filter_finite, compute_range_statistics, compute_cpk, compute_site_stats,
)
from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS
from .charts import _create_histogram_chart, EXPORT_DPI_DEFAULT
from .chart_workers import render_histogram_worker
from .fonts import EXCEL_FONT_FAMILY, apply_matplotlib_fonts
from .histogram_grid import finite_or_none

HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(name=EXCEL_FONT_FAMILY, color="FFFFFF", bold=True, size=11)
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center")
# 数据单元格的居中对齐与表头同形状，但语义无关，单列一个常量免得混用
CENTER_ALIGNMENT = Alignment(horizontal="center", vertical="center")

FAIL_FILL = PatternFill(start_color="F54927", end_color="F54927", fill_type="solid")
FAIL_FONT = Font(color="FFFFFF", bold=True)
ALL_FILL = PatternFill(start_color="F5F5F5", end_color="F5F5F5", fill_type="solid")
NORMAL_FILL = PatternFill(start_color="E0E0E0", end_color="E0E0E0", fill_type="solid")
STATS_LABEL_FILL = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
LINK_FONT = Font(name=EXCEL_FONT_FAMILY, size=11, color="0563C1")

# CPK 等级色（底色, 字色）；未知等级走灰色
CPK_COLOR_MAP = {
    'green': ("4CAF50", "FFFFFF"), 'orange': ("FFA726", "FFFFFF"),
    'darkorange': ("FF7043", "FFFFFF"), 'red': ("F44336", "FFFFFF"),
}

SUMMARY_HEADERS = ["序号", "参数", "数据点数", "Mean", "STD", "Min", "Max", "CPK", "CPK Level", "ALL Site Yield"]
DETAIL_HEADERS = ["统计项", "Low Limit", "High Limit", "Unit"]
SITE_HEADERS = ["Site", "Yield", "FailCount", "ExceedMin", "ExceedMax"]
SHEET_NAME_MAX_LEN = 28


class ChartFlags(NamedTuple):
    """透传给渲染函数/worker 的图表开关（一次装配内所有参数共用）。"""

    show_limit: bool
    show_3sigma: bool
    show_4sigma: bool
    show_6sigma: bool
    show_normal: bool
    show_kde: bool
    dpi: int


def _site_fail_count(si: dict) -> int:
    """站点失败数（数字）：优先 FailCountNum——2026-08-13 站点统计改版后
    FailCount 是展示字符串（`3(0.181%)`），与 int 比较会 TypeError；旧格式/
    缺字段时从 FailCount 前缀解析兜底。"""
    v = si.get('FailCountNum')
    if isinstance(v, int):
        return v
    raw = si.get('FailCount', 0)
    try:
        return int(str(raw).split('(')[0])
    except (TypeError, ValueError):
        return 0


def _apply_cpk_style(cell, cpk_color_name):
    bg, fg = CPK_COLOR_MAP.get(cpk_color_name, ("9E9E9E", "FFFFFF"))
    cell.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
    cell.font = Font(color=fg, bold=True)
    cell.alignment = CENTER_ALIGNMENT


def _get_text_width(text):
    s = str(text) if text is not None else ""
    cn_len = len([c for c in s if '一' <= c <= '鿿'])
    return len(s) + cn_len + 2


def _sheet_name(param: str) -> str:
    """参数名 → 合法 sheet 名（Excel 禁用字符换下划线，限长 28）。"""
    return (param.replace("/", "_").replace("\\", "_")
                .replace(" ", "_").replace("-", "_"))[:SHEET_NAME_MAX_LEN]


def _collect_param_stats(df, metadata, params, site_col, th):
    """逐参数算总览统计与图表输入，按文件列序排序。

    只算不画：图片留到明细 sheet 阶段再渲染，总览行才能先落表。
    """
    param_order = {col: idx for idx, col in enumerate(df.columns)}
    rows = []

    for selected_param in sorted(params, key=lambda x: param_order.get(x, 999999)):
        if selected_param not in df.columns:
            continue
        data_series = filter_finite(get_1d_from(df, selected_param))
        if len(data_series) == 0:
            continue

        stats = compute_range_statistics(data_series, metadata, selected_param)
        # 限值可能为 None（parse_limit_string 新语义）或非有限 → 统一收敛，下游
        # 的 ``is not None`` 守卫与图表回退才能真正生效（缺陷 #5）
        rdl_min = finite_or_none(stats['rdl'][0])
        rdl_max = finite_or_none(stats['rdl'][1])
        cpk_result = compute_cpk(stats['mean'], stats['std'], rdl_min, rdl_max,
                                 **th.as_kwargs())
        mean_val = stats['mean']
        std_val = stats['std']

        # Site stats
        site_stats = []
        if site_col and site_col in df.columns:
            site_series = get_1d_from(df, selected_param)
            site_idx = get_1d_from(df, site_col)
            site_stats = compute_site_stats(site_series, site_idx, rdl_min, rdl_max, None, None, False) or []

        rows.append((selected_param, {
            'stats_data': {
                'param_name': selected_param, 'mean_val': round(mean_val, 4),
                'std_val': round(std_val, 4), 'data_range': f"{round(float(data_series.min()), 4)} ~ {round(float(data_series.max()), 4)}",
                'count': len(data_series), 'cpk_str': round(cpk_result['cpk'], 4),
                'cpk_color': cpk_result.get('cpk_color', 'gray'),
                'low_limit': round(rdl_min, 4) if rdl_min is not None else 'N/A',
                'high_limit': round(rdl_max, 4) if rdl_max is not None else 'N/A',
                'unit': stats.get('unit', ''),
            },
            'site_stats': site_stats,
            'chart_data': {
                'data_series': data_series,
                'mean_val': mean_val,
                'std_val': std_val,
                'rdl_min': rdl_min,
                'rdl_max': rdl_max,
            },
        }))
    return rows


def _write_summary_sheet(ws_summary, rows):
    """总览表头 + 每参数一行（含跳转链接与 ALL Site 良率着色）+ 列宽。"""
    for col_idx, h in enumerate(SUMMARY_HEADERS, 1):
        cell = ws_summary.cell(row=1, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT

    col_max_widths = {i: _get_text_width(SUMMARY_HEADERS[i - 1])
                      for i in range(1, len(SUMMARY_HEADERS) + 1)}

    for param_idx, (selected_param, entry) in enumerate(rows, 1):
        stats_data = entry['stats_data']
        site_stats_list = entry['site_stats']

        cell_param = ws_summary.cell(row=param_idx + 1, column=2, value=selected_param)
        cell_param.hyperlink = f"#'{_sheet_name(selected_param)}'!A1"
        cell_param.font = LINK_FONT

        ws_summary.cell(row=param_idx + 1, column=1, value=param_idx).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=param_idx + 1, column=3, value=stats_data['count']).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=param_idx + 1, column=4, value=str(stats_data['mean_val'])).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=param_idx + 1, column=5, value=str(stats_data['std_val'])).alignment = Alignment(horizontal="center")

        range_parts = str(stats_data['data_range']).split(' ~ ')
        ws_summary.cell(row=param_idx + 1, column=6, value=range_parts[0] if len(range_parts) > 0 else '').alignment = Alignment(horizontal="center")
        ws_summary.cell(row=param_idx + 1, column=7, value=range_parts[1] if len(range_parts) > 1 else '').alignment = Alignment(horizontal="center")

        cell_cpk = ws_summary.cell(row=param_idx + 1, column=8, value=stats_data['cpk_str'])
        _apply_cpk_style(cell_cpk, stats_data.get('cpk_color', 'gray'))
        ws_summary.cell(row=param_idx + 1, column=9, value=str(stats_data['cpk_str'])).alignment = Alignment(horizontal="center")

        all_site_yield = "100.00%"
        for si in site_stats_list:
            if si.get('Site') == 'ALL Site':
                all_site_yield = si.get('Yield', '100.00%')
                break
        cell_yield = ws_summary.cell(row=param_idx + 1, column=10, value=all_site_yield)
        cell_yield.alignment = Alignment(horizontal="center")
        for si in site_stats_list:
            if si.get('Site') == 'ALL Site':
                if _site_fail_count(si) > 0:
                    cell_yield.fill = FAIL_FILL
                    cell_yield.font = FAIL_FONT
                else:
                    cell_yield.fill = NORMAL_FILL
                break

        row_vals = [(1, param_idx), (2, selected_param), (3, stats_data['count']),
                     (4, str(stats_data['mean_val'])), (5, str(stats_data['std_val'])),
                     (6, range_parts[0] if len(range_parts) > 0 else ''),
                     (7, range_parts[1] if len(range_parts) > 1 else ''),
                     (8, str(stats_data['cpk_str'])), (9, str(stats_data['cpk_str'])), (10, all_site_yield)]
        for col_i, val in row_vals:
            w = _get_text_width(val)
            if w > col_max_widths.get(col_i, 0):
                col_max_widths[col_i] = w

    for col in range(1, len(SUMMARY_HEADERS) + 1):
        ws_summary.column_dimensions[get_column_letter(col)].width = min(col_max_widths.get(col, 15), 40)


def _pick_workers(workers):
    """``workers=None`` 沿用今天的 ``min(8, cpu)``；显式传值原样生效。

    **作业化时必须传 1**：作业本身已经跑在常驻作业池的子进程里，这里再开一层
    就是「作业池 4 × 渲染池 8 = 32 个 Python 进程」，每个常驻 150–250MB，
    20 人档会直接把机器打爆。
    """
    return min(8, max(2, os.cpu_count() or 4)) if workers is None else workers


def _site_arrays(df, site_col):
    """预提取 site 数据（可 pickle 的 ndarray/标量，供多进程任务）。"""
    if not site_col or site_col not in df.columns:
        return None, None
    site_series_raw = df[site_col]
    if isinstance(site_series_raw, pd.DataFrame):
        site_series_raw = site_series_raw.iloc[:, 0]
    site_values = sorted(site_series_raw.dropna().unique(),
                         key=lambda x: (isinstance(x, float), x))
    return site_series_raw.to_numpy(), site_values


def _render_chart_pngs(rows, site_col, df, flags, workers):
    """多进程并行渲染全部参数图表（瓶颈在 matplotlib；worker 见 chart_workers.py）。

    返回 ``{param: png_bytes | None}``；``workers<=1`` 或并行整体失败时返回空
    dict，装配循环会逐参数走同一条串行渲染兜底（产出不受影响，只是慢）。
    """
    n_workers = _pick_workers(workers)
    if n_workers <= 1:
        return {}

    site_series, site_values = _site_arrays(df, site_col)
    try:
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futures = {}
            for title, entry in rows:
                chart_data = entry['chart_data']
                futures[title] = ex.submit(
                    render_histogram_worker,
                    {
                        'param': title,
                        'data_series': chart_data['data_series'].to_numpy(),
                        'site_values': site_values,
                        'site_series': site_series,
                        'mean_val': chart_data['mean_val'],
                        'std_val': chart_data['std_val'],
                        'rdl_min': chart_data['rdl_min'],
                        'rdl_max': chart_data['rdl_max'],
                        'show_limit': flags.show_limit,
                        'show_3sigma': flags.show_3sigma,
                        'show_4sigma': flags.show_4sigma,
                        'show_6sigma': flags.show_6sigma,
                        'show_normal': flags.show_normal,
                        'show_kde': flags.show_kde,
                        # DPI 必须是已钳位的纯标量：worker 进程禁读 Django/DB
                        'dpi': flags.dpi,
                    },
                )
            return {title: _take_png(futures[title]) for title, _entry in rows}
    except Exception:
        return {}  # 并行整体失败 → 全量串行兜底（与现状等价）


def _take_png(future):
    try:
        return future.result()
    except Exception:
        return None  # 单参数失败 → 串行兜底


def _write_detail_sheet(wb, idx, title, entry, png, df, metadata, site_col, flags):
    """写一个参数的明细 sheet，返回图片 buffer（调用方须保留到 ``wb.save()`` 后）。

    ``png`` 为并行渲染结果；None 时就地串行渲染。渲染不出图（空 buffer）时
    不建 sheet，返回 None。
    """
    stats_data = entry.get('stats_data', {})
    site_stats_list = entry.get('site_stats', [])
    chart_data = entry.get('chart_data', {})

    if png is None:
        img_buffer = _create_histogram_chart(
            df, metadata, title, chart_data['data_series'],
            chart_data['mean_val'], chart_data['std_val'],
            chart_data['rdl_min'], chart_data['rdl_max'],
            show_limit=flags.show_limit, show_3sigma=flags.show_3sigma,
            show_4sigma=flags.show_4sigma, show_6sigma=flags.show_6sigma,
            show_normal=flags.show_normal, show_kde=flags.show_kde, site_col=site_col,
            dpi=flags.dpi,
        )
    else:
        img_buffer = io.BytesIO(png)
    if img_buffer.getbuffer().nbytes == 0:
        img_buffer.close()
        return None

    try:
        ws = wb.create_sheet(title=_sheet_name(title))
    except ValueError:
        ws = wb.create_sheet(title=f"Chart_{idx}")

    # Stats header
    for col_idx, h in enumerate(DETAIL_HEADERS, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT

    if stats_data:
        ws.cell(row=2, column=1, value=stats_data.get('param_name', ''))
        ws.cell(row=2, column=2, value=stats_data.get('low_limit', 0)).number_format = '0.0000'
        ws.cell(row=2, column=3, value=stats_data.get('high_limit', 0)).number_format = '0.0000'
        ws.cell(row=2, column=4, value=stats_data.get('unit', ''))

        left_labels = [("Mean", "mean_val", 4, 1), ("STD", "std_val", 5, 1),
                       ("Range", "data_range", 6, 1), ("数据点数", "count", 7, 1),
                       ("CPK", "cpk_str", 8, 1)]
        for label, key, row, col in left_labels:
            ws.cell(row=row, column=col, value=label).fill = STATS_LABEL_FILL
            ws.cell(row=row, column=col).alignment = CENTER_ALIGNMENT
            val = stats_data.get(key, '')
            cell = ws.cell(row=row, column=col + 1, value=str(val))
            cell.alignment = CENTER_ALIGNMENT
            if key == "cpk_str":
                _apply_cpk_style(cell, stats_data.get('cpk_color', 'gray'))
            elif key in ("mean_val", "std_val"):
                cell.number_format = '0.0000'

    # Site stats table
    if site_stats_list:
        ws.cell(row=1, column=6, value="Site统计").fill = HEADER_FILL
        ws.cell(row=1, column=6).font = HEADER_FONT
        ws.cell(row=1, column=6).alignment = HEADER_ALIGNMENT

        for col_idx, h in enumerate(SITE_HEADERS, 1):
            cell = ws.cell(row=2, column=col_idx + 5, value=h)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = HEADER_ALIGNMENT

        for row_offset, site_info in enumerate(site_stats_list):
            is_fail = _site_fail_count(site_info) > 0
            is_all = site_info.get('Site') == 'ALL Site'
            for col_idx, key in enumerate(SITE_HEADERS, 1):
                cell = ws.cell(row=row_offset + 3, column=col_idx + 5, value=site_info.get(key, ''))
                cell.alignment = CENTER_ALIGNMENT
                if is_fail:
                    cell.fill = FAIL_FILL
                    cell.font = FAIL_FONT
                elif is_all:
                    cell.fill = ALL_FILL
                else:
                    cell.fill = NORMAL_FILL

    # Column widths
    for col in range(1, 6):
        ws.column_dimensions[get_column_letter(col)].width = 18
    for col in range(6, 11):
        ws.column_dimensions[get_column_letter(col)].width = 14

    # Return hyperlink
    return_cell = ws.cell(row=8, column=5, value="← 返回总览")
    return_cell.hyperlink = "#'总览'!A1"
    return_cell.font = LINK_FONT

    # Embed chart image
    max_site_rows = 2 + len(site_stats_list) + 1 if site_stats_list else 2
    chart_row = max(9, max_site_rows + 1)

    img_buffer.seek(0)
    img = XlImage(img_buffer)
    img.width = 800
    img.height = 450
    ws.add_image(img, f'A{chart_row}')
    return img_buffer


def build_batch_charts_xlsx_with_charts(df, metadata, params, site_col=None,
                                         show_limit=True, show_3sigma=False,
                                         show_4sigma=False, show_6sigma=True,
                                         show_normal=False, show_kde=False,
                                         dpi=EXPORT_DPI_DEFAULT,
                                         cpk_thresholds=None,
                                         workers=None, progress_cb=None):
    """Build batch charts Excel with embedded histogram images.

    ``cpk_thresholds``（CpkThresholds）= 当前账号的 CPK 分级阈值，决定总览 CPK 单元格
    的等级色；None 时用默认 1.67/1.33/1.0。必须在主进程用（worker 只收渲染标量）。

    ``workers``：渲染用的进程数，缺省沿用今天的 ``min(8, …)``。
    **作业化时必须传 1** —— 详见 ``_pick_workers``。传 1 时整段并行块跳过，
    走逐参数串行渲染兜底（同一条渲染函数，产出不受影响，只是慢）。

    ``progress_cb(percent:int)``：每装配完一个参数回调一次，供作业把进度落进侧车文件。
    只在**调用方进程**里执行，绝不跨进程传（lambda 不可 pickle）。

    Ported from old project's export_batch_distribution_chart_excel + _export_charts_to_xlsx.
    Returns bytes of the .xlsx file.
    """
    th = cpk_thresholds or DEFAULT_CPK_THRESHOLDS
    apply_matplotlib_fonts()
    flags = ChartFlags(show_limit, show_3sigma, show_4sigma, show_6sigma,
                       show_normal, show_kde, dpi)

    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "总览"

    rows = _collect_param_stats(df, metadata, params, site_col, th)
    _write_summary_sheet(ws_summary, rows)

    # openpyxl lazily reads image data during wb.save(), so we must keep each
    # buffer alive until after save() and close them all at the end.
    open_buffers = []
    png_results = _render_chart_pngs(rows, site_col, df, flags, workers)

    for idx, (title, entry) in enumerate(rows):
        if progress_cb:
            # 报的是「已装配到第几个」，总人数由调用方持有 —— 这里不猜百分比语义。
            # 放在循环体第一行：下面渲染不出图时会跳过 sheet，放后面就漏报。
            progress_cb(idx + 1)
        buffer = _write_detail_sheet(wb, idx, title, entry,
                                     png_results.get(title), df, metadata,
                                     site_col, flags)
        if buffer is not None:
            open_buffers.append(buffer)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    result = output.getvalue()
    output.close()
    for buf in open_buffers:
        buf.close()
    return result
