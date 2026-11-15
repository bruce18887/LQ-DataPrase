"""Batch charts Excel export with embedded histogram images.

装配顺序固定为：逐参数算总览统计 → 写总览表 → （可选）并行渲染 PNG → 逐参数
写明细 sheet → 保存。openpyxl 在 ``wb.save()`` 时才懒读图片数据，所以每个
BytesIO 必须活到 save() 之后，由编排层持有并在收尾统一关闭。
"""

import io
import os
from concurrent.futures import ProcessPoolExecutor
from typing import NamedTuple

import matplotlib
matplotlib.use('Agg')
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XlImage

from apps.analysis.services.statistics import (
    get_1d_from, filter_finite, compute_range_statistics, compute_cpk, compute_site_stats,
)
from apps.common.sheet_names import unique_sheet_names
from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS
from apps.export.grouping import DEFAULT_MAX_ITEMS_PER_SHEET, OTHER_GROUP_NAME
from .charts import _align_site_series, _create_histogram_chart, EXPORT_DPI_DEFAULT
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

SUMMARY_HEADERS = ["序号", "参数", "分类", "数据点数", "Mean", "STD", "Min", "Max",
                   "CPK", "CPK Level", "ALL Site Yield"]
DETAIL_HEADERS = ["统计项", "Low Limit", "High Limit", "Unit"]
SITE_HEADERS = ["Site", "Yield", "FailCount", "ExceedMin", "ExceedMax"]


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
        # Site 数组按本参数过滤后的索引对齐：各参数的有限值集合可能不同，
        # 不能像旧实现那样整列预提取一次共用（参数值为 NaN 的行会静默错位）。
        site_arrays = _align_site_series(df, site_col, data_series)
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
                # 图标题要显示「参数名 (单位)」，单位来自元数据
                'unit': stats.get('unit', ''),
                # Site 按 data_series 索引对齐（屏幕口径）：参数值非有限的行不参与
                # 站点统计。并行渲染与串行兜底共用这一份，避免各自重算漂移。
                'site_values': site_arrays[0],
                'site_series': site_arrays[1],
            },
        }))
    return rows


def _plan_pages(rows, groups, max_items):
    """按分组顺序装箱：每页装满后开新页，末页放余数。

    组内顺序 = rows 的文件列序；组内参数若不在 rows（列不存在/无数据）则跳过；
    rows 中未被任何组覆盖的参数兜底进「其他」（前端已发，装配层再兜一次）。
    """
    order = [title for title, _entry in rows]
    pages, assigned = [], set()
    for group in groups:
        wanted = set(group['params'])
        members = [t for t in order if t in wanted]
        if not members:
            continue
        parts = [members[i:i + max_items] for i in range(0, len(members), max_items)]
        for i, part in enumerate(parts, 1):
            base = group['name'] if len(parts) == 1 else f"{group['name']}_{i}"
            pages.append((base, part))
        assigned.update(members)
    rest = [t for t in order if t not in assigned]
    if rest:
        parts = [rest[i:i + max_items] for i in range(0, len(rest), max_items)]
        for i, part in enumerate(parts, 1):
            base = OTHER_GROUP_NAME if len(parts) == 1 else f'{OTHER_GROUP_NAME}_{i}'
            pages.append((base, part))
    return pages


def _groups_by_param(titles, groups):
    """参数 → 所属分类名列表（保持分组入参顺序，重复出现只记一次）。"""
    out = {title: [] for title in titles}
    for group in groups:
        for title in group['params']:
            if title in out and group['name'] not in out[title]:
                out[title].append(group['name'])
    for names in out.values():
        if not names:
            names.append(OTHER_GROUP_NAME)
    return out


def _plan_targets(pages, sheet_names, rows_by_title):
    """参数 → 首次出现处的 ``(sheet 名, 块起始行)``；多属只记第一次。"""
    targets = {}
    for (base, titles), sheet_name in zip(pages, sheet_names):
        start = 1
        for title in titles:
            targets.setdefault(title, (sheet_name, start))
            start += _block_height(rows_by_title[title])
    return targets


def _write_summary_sheet(ws_summary, rows, group_names_by_param, targets):
    """总览：序号/参数/分类/统计…；参数超链接指向实际 sheet 的块起始行。

    ``targets`` 是参数 → ``(sheet 名, 块起始行)``，由 ``_plan_targets`` 按装箱结果
    算出：链接必须指向真实存在的表与实际块位置，不能拿参数名现拼（含非法字符/
    截断撞名时会断链或互指）。
    """
    for col_idx, header in enumerate(SUMMARY_HEADERS, 1):
        cell = ws_summary.cell(row=1, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT

    col_max_widths = {i: _get_text_width(SUMMARY_HEADERS[i - 1]) for i in range(1, len(SUMMARY_HEADERS) + 1)}

    for param_idx, (selected_param, entry) in enumerate(rows, 1):
        stats_data = entry['stats_data']
        row = param_idx + 1
        cell_param = ws_summary.cell(row=row, column=2, value=selected_param)
        sheet_name, anchor_row = targets[selected_param]
        cell_param.hyperlink = f"#'{sheet_name}'!A{anchor_row}"
        cell_param.font = LINK_FONT

        ws_summary.cell(row=row, column=1, value=param_idx).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=3,
                        value=' / '.join(group_names_by_param.get(selected_param, []))).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=4, value=stats_data['count']).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=5, value=str(stats_data['mean_val'])).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=6, value=str(stats_data['std_val'])).alignment = Alignment(horizontal="center")

        range_parts = str(stats_data['data_range']).split(' ~ ')
        ws_summary.cell(row=row, column=7, value=range_parts[0] if len(range_parts) > 0 else '').alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=8, value=range_parts[1] if len(range_parts) > 1 else '').alignment = Alignment(horizontal="center")

        cell_cpk = ws_summary.cell(row=row, column=9, value=stats_data['cpk_str'])
        _apply_cpk_style(cell_cpk, stats_data.get('cpk_color', 'gray'))
        ws_summary.cell(row=row, column=10, value=str(stats_data['cpk_str'])).alignment = Alignment(horizontal="center")

        all_site_yield = "100.00%"
        for site_info in entry['site_stats']:
            if site_info.get('Site') == 'ALL Site':
                all_site_yield = site_info.get('Yield', '100.00%')
                break
        cell_yield = ws_summary.cell(row=row, column=11, value=all_site_yield)
        cell_yield.alignment = Alignment(horizontal="center")
        for site_info in entry['site_stats']:
            if site_info.get('Site') == 'ALL Site':
                if _site_fail_count(site_info) > 0:
                    cell_yield.fill = FAIL_FILL
                    cell_yield.font = FAIL_FONT
                else:
                    cell_yield.fill = NORMAL_FILL
                break

        row_vals = [(1, param_idx), (2, selected_param), (3, ' / '.join(group_names_by_param.get(selected_param, []))),
                    (4, stats_data['count']), (5, str(stats_data['mean_val'])), (6, str(stats_data['std_val'])),
                    (7, range_parts[0] if len(range_parts) > 0 else ''), (8, range_parts[1] if len(range_parts) > 1 else ''),
                    (9, str(stats_data['cpk_str'])), (10, str(stats_data['cpk_str'])), (11, all_site_yield)]
        for col_i, val in row_vals:
            width = _get_text_width(val)
            if width > col_max_widths.get(col_i, 0):
                col_max_widths[col_i] = width

    for col in range(1, len(SUMMARY_HEADERS) + 1):
        ws_summary.column_dimensions[get_column_letter(col)].width = min(col_max_widths.get(col, 15), 40)


def _pick_workers(workers):
    """``workers=None`` 沿用今天的 ``min(8, cpu)``；显式传值原样生效。

    **作业化时必须传 1**：作业本身已经跑在常驻作业池的子进程里，这里再开一层
    就是「作业池 4 × 渲染池 8 = 32 个 Python 进程」，每个常驻 150–250MB，
    20 人档会直接把机器打爆。
    """
    return min(8, max(2, os.cpu_count() or 4)) if workers is None else workers


def _render_chart_pngs(rows, flags, workers):
    """多进程并行渲染全部参数图表（瓶颈在 matplotlib；worker 见 chart_workers.py）。

    返回 ``{param: png_bytes | None}``；``workers<=1`` 或并行整体失败时返回空
    dict，装配循环会逐参数走同一条串行渲染兜底（产出不受影响，只是慢）。
    """
    n_workers = _pick_workers(workers)
    if n_workers <= 1:
        return {}

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
                        # 每参数各自的索引对齐结果（_collect_param_stats 已算好）
                        'site_values': chart_data.get('site_values'),
                        'site_series': chart_data.get('site_series'),
                        'mean_val': chart_data['mean_val'],
                        'std_val': chart_data['std_val'],
                        'rdl_min': chart_data['rdl_min'],
                        'rdl_max': chart_data['rdl_max'],
                        'unit': chart_data.get('unit', ''),
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


def _block_image_row(start_row: int, site_rows: int) -> int:
    """图块锚点行：统计/Site 表下方，至少留到 S+8（现状 S=1 → 第 9 行）。"""
    return start_row + max(8, site_rows + 3)


def _block_height(entry) -> int:
    """一个块占用的行数：图锚点行距 + 450px（≈23 行）+ 1 行间隔。"""
    return max(8, len(entry.get('site_stats') or []) + 3) + 24


def _set_detail_column_widths(ws):
    """明细 sheet 的列宽：前 5 列放统计项，6–10 列放 Site 表（每张 sheet 设一次）。"""
    for col in range(1, 6):
        ws.column_dimensions[get_column_letter(col)].width = 18
    for col in range(6, 11):
        ws.column_dimensions[get_column_letter(col)].width = 14


def _write_block(ws, start_row, title, entry, png, df, metadata, site_col, flags):
    """在 ws 的 start_row 起写一个「统计 + 图」块；返回图片 buffer（或 None）。

    ``png`` 为并行渲染结果；None 时就地串行渲染。渲染不出图（空 buffer）时
    不写任何内容并返回 None —— 调用方可据此决定是否推进块偏移。
    行号一律以 ``start_row`` 偏移：``start_row=1`` 与改造前的单页版式逐字一致。

    调用方须保留返回的 buffer 到 ``wb.save()`` 之后。
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
            dpi=flags.dpi, unit=stats_data.get('unit', ''),
        )
    else:
        img_buffer = io.BytesIO(png)
    if img_buffer.getbuffer().nbytes == 0:
        img_buffer.close()
        return None

    for col_idx, header in enumerate(DETAIL_HEADERS, 1):
        cell = ws.cell(row=start_row, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT

    if stats_data:
        row_param = start_row + 1
        ws.cell(row=row_param, column=1, value=stats_data.get('param_name', ''))
        ws.cell(row=row_param, column=2, value=stats_data.get('low_limit', 0)).number_format = '0.0000'
        ws.cell(row=row_param, column=3, value=stats_data.get('high_limit', 0)).number_format = '0.0000'
        ws.cell(row=row_param, column=4, value=stats_data.get('unit', ''))

        left_labels = [("Mean", "mean_val", start_row + 3, 1), ("STD", "std_val", start_row + 4, 1),
                       ("Range", "data_range", start_row + 5, 1), ("数据点数", "count", start_row + 6, 1),
                       ("CPK", "cpk_str", start_row + 7, 1)]
        for label, key, row, col in left_labels:
            ws.cell(row=row, column=col, value=label).fill = STATS_LABEL_FILL
            ws.cell(row=row, column=col).alignment = CENTER_ALIGNMENT
            cell = ws.cell(row=row, column=col + 1, value=str(stats_data.get(key, '')))
            cell.alignment = CENTER_ALIGNMENT
            if key == "cpk_str":
                _apply_cpk_style(cell, stats_data.get('cpk_color', 'gray'))
            elif key in ("mean_val", "std_val"):
                cell.number_format = '0.0000'

    if site_stats_list:
        ws.cell(row=start_row, column=6, value="Site统计").fill = HEADER_FILL
        ws.cell(row=start_row, column=6).font = HEADER_FONT
        ws.cell(row=start_row, column=6).alignment = HEADER_ALIGNMENT
        for col_idx, header in enumerate(SITE_HEADERS, 1):
            cell = ws.cell(row=start_row + 1, column=col_idx + 5, value=header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = HEADER_ALIGNMENT
        for row_offset, site_info in enumerate(site_stats_list):
            is_fail = _site_fail_count(site_info) > 0
            is_all = site_info.get('Site') == 'ALL Site'
            for col_idx, key in enumerate(SITE_HEADERS, 1):
                cell = ws.cell(row=start_row + 2 + row_offset, column=col_idx + 5,
                               value=site_info.get(key, ''))
                cell.alignment = CENTER_ALIGNMENT
                if is_fail:
                    cell.fill = FAIL_FILL
                    cell.font = FAIL_FONT
                elif is_all:
                    cell.fill = ALL_FILL
                else:
                    cell.fill = NORMAL_FILL

    return_cell = ws.cell(row=start_row + 7, column=5, value="← 返回总览")
    return_cell.hyperlink = "#'总览'!A1"
    return_cell.font = LINK_FONT

    img_buffer.seek(0)
    image = XlImage(img_buffer)
    image.width = 800
    image.height = 450
    ws.add_image(image, f'A{_block_image_row(start_row, len(site_stats_list))}')
    return img_buffer


def build_batch_charts_xlsx_with_charts(df, metadata, params, site_col=None,
                                         show_limit=True, show_3sigma=False,
                                         show_4sigma=False, show_6sigma=True,
                                         show_normal=False, show_kde=False,
                                         dpi=EXPORT_DPI_DEFAULT,
                                         cpk_thresholds=None,
                                         workers=None, progress_cb=None,
                                         groups=None,
                                         max_items_per_sheet=DEFAULT_MAX_ITEMS_PER_SHEET):
    """Build batch charts Excel with embedded histogram images.

    ``cpk_thresholds``（CpkThresholds）= 当前账号的 CPK 分级阈值，决定总览 CPK 单元格
    的等级色；None 时用默认 1.67/1.33/1.0。必须在主进程用（worker 只收渲染标量）。

    ``workers``：渲染用的进程数，缺省沿用今天的 ``min(8, …)``。
    **作业化时必须传 1** —— 详见 ``_pick_workers``。传 1 时整段并行块跳过，
    走逐参数串行渲染兜底（同一条渲染函数，产出不受影响，只是慢）。

    ``progress_cb(percent:int)``：每装配完一个参数回调一次，供作业把进度落进侧车文件。
    只在**调用方进程**里执行，绝不跨进程传（lambda 不可 pickle）。

    ``groups``：已校验的分组 ``[{'name', 'params'}]``（见 ``normalize_batch_grouping``）。
    None 时沿用「每参数一张 sheet、链接指向 A1」的旧版式；给了分组就按组顺序装箱，
    每页最多 ``max_items_per_sheet`` 个块，总览链接指向块起始行，同一参数命中多个
    分类时按组各嵌一份图（链接只指向首次出现处）。``max_items_per_sheet`` 只在
    有分组时生效。

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
    rows_by_title = dict(rows)
    titles = [title for title, _entry in rows]

    if groups:
        page_cap = int(max_items_per_sheet or DEFAULT_MAX_ITEMS_PER_SHEET)
        pages = _plan_pages(rows, groups, page_cap)
        group_names = _groups_by_param(titles, groups)
    else:
        # 无分组 = 旧版式：每参数一页、每页一个块，与改造前逐字一致。
        pages = [(title, [title]) for title in titles]
        group_names = {title: [] for title in titles}

    # 先分配唯一 sheet 名，再用同一份映射写总览链接与建明细表 —— 两处各自
    # 现拼会在非法字符/截断撞名时断链或互指（2026-11-15 实测）。
    sheet_names = unique_sheet_names([base for base, _titles in pages])
    targets = _plan_targets(pages, sheet_names, rows_by_title)
    _write_summary_sheet(ws_summary, rows, group_names, targets)

    # openpyxl lazily reads image data during wb.save(), so we must keep each
    # buffer alive until after save() and close them all at the end.
    open_buffers = []
    png_results = _render_chart_pngs(rows, flags, workers)
    done = set()

    for (_base, page_titles), sheet_name in zip(pages, sheet_names):
        ws = wb.create_sheet(title=sheet_name)
        _set_detail_column_widths(ws)
        start = 1
        has_content = False
        for title in page_titles:
            # 多属参数在每个所属分类的页里各嵌一份图（png 复用，buffer 各自新建）。
            buffer = _write_block(ws, start, title, rows_by_title[title],
                                  png_results.get(title), df, metadata, site_col, flags)
            if buffer is None:
                continue
            has_content = True
            open_buffers.append(buffer)
            start += _block_height(rows_by_title[title])
            if title not in done:
                done.add(title)
                if progress_cb:
                    # 报的是「已装配完几个参数」，总数由调用方持有 —— 这里不猜百分比语义。
                    # 多属参数只报一次，否则进度会超过总数。
                    progress_cb(len(done))
        if not has_content:
            # 整页一个块都渲染不出图时不留空 sheet（总览链接会指向该页，见残余风险）。
            wb.remove(ws)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    result = output.getvalue()
    output.close()
    for buf in open_buffers:
        buf.close()
    return result
