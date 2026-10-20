# apps/weight/xlsx.py
"""权重画图 → xlsx：总览表 + 每个测试项一张工作表（原生散点折线图 + 明细数据）。

与页面同一解析器（spec §2 第 4 条）；颜色由调用方按当前主题传入，本模块不存色板，
`DEFAULT_PALETTE` 只是「调用方给了畸形色」时的逐项回退（spec §6.1），不是第二处色板真源。

结构（2026-10-20 用户点定，对齐批量参数分布导出的形态）：

- `总览`：序号 / 测试项（蓝色超链接）/ 系列数 / 数据点数 / 最长 Code / 最小权重 / 最大权重；
  只列**可见**测试项。
- 每个可见测试项一张 sheet（sheet 名 = 测试项名，非法字符替换、31 字符上限、重名加 `_2`）：
  - 图锚 `A1`（16 × 11cm），标题 = 测试项名，x 轴到本组最长系列 - 1，y 轴 auto，图例在底部；
  - 4 条原始曲线：细线 + 小圆点，保留组基色与组内线型；
  - 均值线（show_mean 时）：深灰粗线 + 圆点 + **每个点的数值标签**（与表格一致的 6 位小数）；
  - 数据表在 `DETAIL_HEADER_ROW` 起（原序号 / 系列名 / code 0..本组最长），均值行紧跟组末；
  - `A23` 放「← 返回总览」超链接。

形态结论（本树 venv 实测，证据 `tasks/probe_task4_chart.py` / `tasks/probe_chart_labels.py`）：
- `ScatterChart().x_axis` 天生是 `NumericAxis`；
- `Marker(symbol='circle', size=...)` 与 `DataLabelList(showVal=True, position='t', numFmt=...)`
  都能写进 chart XML 并读回；
- 散点系列的数在 `series.yVal.numRef.f`；系列名读回是 `series.tx.v`；
- 轴标题读回住在 `Title.tx.rich.p[*].r[*].t`；`chart.width/height` 不往返 —— 只有锚的 `ext.{cx,cy}` 是真数。

不键名：`series.name` 在解析器里不保证唯一（同名不去重，见 parser 模块 docstring），
所以「这条是不是均值」由写行时已知的事实（`s is g.mean`）带到画图层，不从名字后缀 `_Avg` 反推。
"""
from __future__ import annotations

import io
import re
from typing import Sequence

from openpyxl import Workbook
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.marker import Marker
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.export.fonts import EXCEL_FONT_FAMILY

from .parser import WeightDoc, WeightGroup, WeightSeries

SUMMARY_SHEET = '总览'
SUMMARY_HEADERS = ('序号', '测试项', '系列数', '数据点数', '最长 Code', '最小权重', '最大权重')

DETAIL_COL_SOURCE_INDEX = 1   # A：原序号
DETAIL_COL_NAME = 2           # B：系列名
DETAIL_COL_VALUE0 = 3         # C：code 0
DETAIL_RETURN_ROW = 23        # 图下方一行放返回链接
DETAIL_HEADER_ROW = 24
DETAIL_FIRST_DATA_ROW = 25

CHART_ANCHOR = 'A1'
PT = 12700
LINE_WIDTH = int(1.25 * PT)
# 均值线 1.5pt 细虚线：它画在最上层，若用 2.5pt 实线会把贴得很近的 4 条原始线整条盖住
# （2026-10-20 用户实测：图例里有四条、图上只看得到均值）。虚线让原始线从缝隙里露出来。
MEAN_WIDTH = int(1.5 * PT)
MEAN_DASH = 'dash'
MARKER_SIZE = 4
DASH_BY_WITHIN_GROUP = ('solid', 'dash', 'dot', 'dashDot')   # 按组内序、每组边界重置
CODE_COL_WIDTH = 12         # 5 位小数带负号约 9–11 字符；7 会显示成 ####（用户实测）
NAME_COL_WIDTH = 22
INDEX_COL_WIDTH = 8
ALT_FILL = 'F7F7F8'
# 截图（用户 2026-10-20 提供）约 16 × 11cm；默认列宽 1.693cm、行高 0.5292cm
# ⇒ 图纵向占约 21 行，因此数据表从第 24 行表头、第 25 行数据起。
CHART_WIDTH_CM = 16
CHART_HEIGHT_CM = 11

HEADER_FILL = PatternFill('solid', fgColor='4472C4')
HEADER_FONT = Font(name=EXCEL_FONT_FAMILY, color='FFFFFF', bold=True, size=11)
HEADER_ALIGNMENT = Alignment(horizontal='center', vertical='center', wrap_text=True)
LINK_FONT = Font(name=EXCEL_FONT_FAMILY, size=11, color='0563C1')

# 调用方传了畸形色时的逐项回退，不是第二处色板真源（spec §6.1）。
DEFAULT_PALETTE = ('2563EB', '047857', 'D97706', 'B91C1C', '0284C7', '86198F', '475569', '0D9488')
_MEAN_COLOR_DEFAULT = '4B5563'
_HEX_RE = re.compile(r'[0-9a-fA-F]{6}')
# Excel sheet 名不能含 []:*?/\，且不能以 ' 开头/结尾；这里连同 ' 一起换掉，超链接引用就不用转义。
_ILLEGAL_SHEET_CHARS = re.compile(r"[\[\]:*?/\\']")
_RESERVED_SHEET_NAMES = {'总览', 'history'}


def _clean_sheet_name(name: str) -> str:
    """测试项名 → 合法 sheet 名：非法字符换 `_`、31 字符上限；空名给 `测试项`。"""
    cleaned = _ILLEGAL_SHEET_CHARS.sub('_', (name or '').strip())[:31]
    return cleaned or '测试项'


def weight_detail_sheet_names(groups: Sequence[WeightGroup]) -> dict[int, str]:
    """按组序分配唯一 sheet 名：Excel 表名大小写不敏感，重名/截断冲突加 `_2`、`_3`。

    `总览` 与 Excel 保留名 `History` 不分配给测试项；只有可见组会被调用方传进来，
    因此隐藏组不会占用名字。
    """
    used = {name.lower() for name in _RESERVED_SHEET_NAMES}
    out: dict[int, str] = {}
    for g in groups:
        base = _clean_sheet_name(g.name)
        candidate = base
        n = 2
        while candidate.lower() in used:
            suffix = f'_{n}'
            candidate = base[:31 - len(suffix)] + suffix
            n += 1
        used.add(candidate.lower())
        out[g.index] = candidate
    return out


def _sheet_link(sheet: str) -> str:
    """内部超链接；表名里的 `'` 按 Excel 公式规则翻倍（本模块的清洗已换掉，仍自守）。"""
    return "#'" + sheet.replace("'", "''") + "'!A1"


def _hex(value: str, fallback: str) -> str:
    """6 位十六进制（可带 `#`）→ 大写；其余一律回退，绝不把脏串塞进 XML。"""
    v = (value or '').strip().lstrip('#')
    return v.upper() if _HEX_RE.fullmatch(v) else fallback


def _fmt(decimals: int) -> str:
    """spec §7.4：按该声明原文的最大小数位写显示格式，`d=0` 不给小数点。"""
    return '0' if decimals <= 0 else '0.' + '0' * decimals


def _write_summary(ws, doc: WeightDoc, visible: set[int], names: dict[int, str]) -> None:
    for col, header in enumerate(SUMMARY_HEADERS, 1):
        cell = ws.cell(1, col, header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT

    row = 2
    for g in doc.groups:
        if g.index not in visible:
            continue
        raw = [v for s in g.series for v in s.values if v is not None]
        longest = max((len(s.values) for s in g.series), default=0)
        ws.cell(row, 1, row - 1).alignment = HEADER_ALIGNMENT
        link = ws.cell(row, 2, g.name)
        link.hyperlink = _sheet_link(names[g.index])
        link.font = LINK_FONT
        ws.cell(row, 3, len(g.series)).alignment = HEADER_ALIGNMENT
        ws.cell(row, 4, sum(len(s.values) for s in g.series)).alignment = HEADER_ALIGNMENT
        ws.cell(row, 5, max(longest - 1, 0)).alignment = HEADER_ALIGNMENT
        for col, value in ((6, min(raw) if raw else 'N/A'), (7, max(raw) if raw else 'N/A')):
            ws.cell(row, col, value).alignment = HEADER_ALIGNMENT
        row += 1

    for col, width in enumerate((8, 40, 10, 12, 12, 16, 16), 1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _write_detail(wb: Workbook, g: WeightGroup, sheet_name: str,
                  pal: Sequence[str], mean_hex: str, show_mean: bool):
    ws = wb.create_sheet(title=sheet_name)
    members: list[WeightSeries] = list(g.series) + ([g.mean] if show_mean else [])
    group_max = max((len(s.values) for s in members), default=0) - 1
    group_max = max(group_max, 0)

    ws.cell(DETAIL_HEADER_ROW, DETAIL_COL_SOURCE_INDEX, '原序号')
    ws.cell(DETAIL_HEADER_ROW, DETAIL_COL_NAME, '系列名')
    for code in range(group_max + 1):
        ws.cell(DETAIL_HEADER_ROW, DETAIL_COL_VALUE0 + code, code)
    header_font = Font(name=EXCEL_FONT_FAMILY, bold=True)
    for col in range(DETAIL_COL_SOURCE_INDEX, DETAIL_COL_VALUE0 + group_max + 1):
        ws.cell(DETAIL_HEADER_ROW, col).font = header_font
    ws.column_dimensions[get_column_letter(DETAIL_COL_SOURCE_INDEX)].width = INDEX_COL_WIDTH
    ws.column_dimensions[get_column_letter(DETAIL_COL_NAME)].width = NAME_COL_WIDTH
    for code in range(group_max + 1):
        ws.column_dimensions[get_column_letter(DETAIL_COL_VALUE0 + code)].width = CODE_COL_WIDTH

    rows: list[tuple[WeightSeries, int, int, bool]] = []
    row = DETAIL_FIRST_DATA_ROW
    alt_fill = PatternFill('solid', fgColor=ALT_FILL) if g.index % 2 else None
    for within, s in enumerate(members):
        is_mean = s is g.mean
        ws.cell(row, DETAIL_COL_SOURCE_INDEX, None if is_mean else s.source_index)
        name_cell = ws.cell(row, DETAIL_COL_NAME, s.name)
        name_cell.font = Font(
            name=EXCEL_FONT_FAMILY, bold=is_mean,
            color=mean_hex if is_mean else _series_color(pal, g.index))
        if alt_fill is not None:
            name_cell.fill = alt_fill
        fmt = _fmt(s.decimals)
        for code, value in enumerate(s.values):
            if value is None:                   # 缺席点留空格，不写 0、不写 NaN
                continue
            cell = ws.cell(row, DETAIL_COL_VALUE0 + code, value)
            cell.number_format = fmt
            cell.alignment = Alignment(horizontal='right')
        rows.append((s, row, within, is_mean))
        row += 1

    back = ws.cell(DETAIL_RETURN_ROW, DETAIL_COL_SOURCE_INDEX, '← 返回总览')
    back.hyperlink = _sheet_link(SUMMARY_SHEET)
    back.font = LINK_FONT

    if any(s.values for s, _row, _within, _is_mean in rows):
        chart = _build_group_chart(ws, g, rows, group_max, pal, mean_hex)
        ws.add_chart(chart, CHART_ANCHOR)


def _series_color(palette: Sequence[str], group_index: int) -> str:
    """组色 = `palette[组序 % len(palette)]`（spec §6：14 组吃 8 色是已知取舍，靠 chip 收敛）。"""
    return palette[group_index % len(palette)]


def _visible_indexes(doc: WeightDoc, visible_group_indexes) -> set[int]:
    """None → 全可见；元素级容错（Task 5 只验「是不是 list」，不验内容）。
    认不出的条目按「不可见」处理，绝不因为一个脏索引把导出打成 500。"""
    if visible_group_indexes is None:
        return {g.index for g in doc.groups}
    wanted = set()
    for raw in visible_group_indexes:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    return wanted


def build_weight_workbook(
    doc: WeightDoc, *, palette: Sequence[str],
    visible_group_indexes: Sequence[int] | None = None,
    show_mean: bool = False, mean_color: str = _MEAN_COLOR_DEFAULT,
) -> bytes:
    """色板必填（从前端当前主题取 8 项）：漏传是 TypeError，不会悄悄退回后端默认板。"""
    visible = _visible_indexes(doc, visible_group_indexes)
    pal = tuple(_hex(c, DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)])
                for i, c in enumerate(palette)) or DEFAULT_PALETTE
    mean_hex = _hex(mean_color, _MEAN_COLOR_DEFAULT)

    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = SUMMARY_SHEET
    visible_groups = [g for g in doc.groups if g.index in visible]
    names = weight_detail_sheet_names(visible_groups)
    _write_summary(ws_summary, doc, visible, names)
    for g in visible_groups:
        _write_detail(wb, g, names[g.index], pal, mean_hex, show_mean)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_group_chart(ws, g: WeightGroup,
                       rows: Sequence[tuple[WeightSeries, int, int, bool]],
                       group_max: int, pal: Sequence[str], mean_hex: str):
    """单测试项的图：4 条原始线带圆点；均值带圆点 + 数值标签；只含本组系列。"""
    chart = ScatterChart(scatterStyle='lineMarker')
    # Excel 内置「样式 1」的淡色网格/边框（用户 2026-10-20 指定）；显式写一层浅灰网格，
    # 避免不同 Excel 版本把默认黑框/深网格画出来。
    chart.style = 1
    chart.graphical_properties = GraphicalProperties(
        solidFill='FFFFFF', ln=LineProperties(solidFill='D9D9D9'))
    # openpyxl 默认把两条 valAx 都写成 axPos="l"，X 轴会和 Y 轴叠在左侧、刻度/标题都被挤掉
    # （用户实测「没有 X/Y 轴刻度」）。X 必须放底部、Y 放左侧；crosses=min 保证 X 轴落在
    # y 最小值处，而不是穿过 y=0 的数据中间。
    chart.x_axis.axPos = 'b'
    chart.y_axis.axPos = 'l'
    for ax in (chart.x_axis, chart.y_axis):
        ax.delete = False
        ax.crosses = 'min'
        ax.tickLblPos = 'nextTo'
        ax.majorTickMark = 'out'
        ax.minorTickMark = 'none'
        ax.majorGridlines.spPr = GraphicalProperties(
            ln=LineProperties(solidFill='E5E7EB'))
        ax.spPr = GraphicalProperties(ln=LineProperties(solidFill='BFBFBF'))
    chart.title = g.name
    chart.x_axis.scaling.min = 0
    chart.x_axis.scaling.max = group_max
    chart.x_axis.title = 'Code'
    chart.y_axis.title = 'Weight'
    # 图例放右侧：放底部时会把 x 轴刻度/title 挤没（用户实测截图）。
    chart.legend.position = 'r'
    chart.width, chart.height = CHART_WIDTH_CM, CHART_HEIGHT_CM
    xref = Reference(ws, min_col=DETAIL_COL_VALUE0, min_row=DETAIL_HEADER_ROW,
                     max_col=DETAIL_COL_VALUE0 + group_max, max_row=DETAIL_HEADER_ROW)
    for s, row, within, is_mean in rows:
        if not s.values:
            # 零长度声明合法；openpyxl 不校验反向区域，无点即无线。
            continue
        yref = Reference(ws, min_col=DETAIL_COL_VALUE0, min_row=row,
                         max_col=DETAIL_COL_VALUE0 + len(s.values) - 1, max_row=row)
        ser = Series(yref, xref, title=s.name)
        color = mean_hex if is_mean else _series_color(pal, g.index)
        if is_mean:
            # 均值不画圆点：圆点会正好压在原始线的点上，且图例只靠虚线区分。
            ser.marker = Marker(symbol='none')
        else:
            ser.marker = Marker(symbol='circle', size=MARKER_SIZE)
            # 标记必须显式填成线色：不填时 Excel 用主题默认色，图例会冒出与线不同的颜色
            # （用户实测：图例四色、图上只见均值）。
            ser.marker.graphicalProperties = GraphicalProperties(
                solidFill=color, ln=LineProperties(solidFill=color))
        ser.graphicalProperties.line = LineProperties(
            solidFill=color,
            w=MEAN_WIDTH if is_mean else LINE_WIDTH,
            prstDash=MEAN_DASH if is_mean else DASH_BY_WITHIN_GROUP[within % len(DASH_BY_WITHIN_GROUP)])
        ser.smooth = False
        if is_mean:
            labels = DataLabelList()
            labels.showVal = True
            labels.showSerName = False
            labels.showCatName = False
            labels.showLegendKey = False
            labels.numFmt = _fmt(s.decimals)       # 均值 6 位，与表格一致
            labels.position = 't'
            ser.dLbls = labels
        chart.series.append(ser)
    return chart
