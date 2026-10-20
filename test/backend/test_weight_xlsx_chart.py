# test/backend/test_weight_xlsx_chart.py
"""分项 sheet 里的原生图：圆点、均值标签、线型、独立轴与 16×11cm 几何。

2026-10-20 版式（用户提供截图）：
- 4 条原始曲线：细线 + 小圆点（circle, size 4，圆点填成线色），保留组基色与组内线型；
- 均值线：深灰 1.5pt **细虚线**、无圆点 + 每个点的数值标签（5 位小数）；虚线是为了不盖住
  贴在它上面的 4 条原始线（用户实测：2.5pt 实线会把它们整条遮住）；
- 每张图 x 轴到本组最长系列 - 1，y 轴 auto；图例在右侧（底部会挤掉 x 轴刻度）。

本文件不读夹具，用合成文档覆盖「不等宽组 / 零长度组 / 字面 A_Avg / 调色板探针」，
夹具的 14 组形状由 `test_weight_xlsx.py` 的结构用例钉住。
"""
import io
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.test import TestCase  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from openpyxl.utils.units import cm_to_EMU  # noqa: E402

from apps.weight.parser import parse_weight_text  # noqa: E402
from apps.weight.xlsx import (  # noqa: E402
    CHART_HEIGHT_CM, CHART_WIDTH_CM, DASH_BY_WITHIN_GROUP, DEFAULT_PALETTE,
    DETAIL_COL_VALUE0, DETAIL_FIRST_DATA_ROW, DETAIL_HEADER_ROW, LINE_WIDTH,
    MARKER_SIZE, MEAN_DASH, MEAN_WIDTH, SUMMARY_SHEET, build_weight_workbook,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(_ROOT, 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')


def _doc():
    with io.open(FIXTURE, encoding='utf-8', newline='') as f:
        return parse_weight_text(f.read())


def _raw(doc=None, **kw):
    kw.setdefault('palette', DEFAULT_PALETTE)
    return build_weight_workbook(doc or _doc(), **kw)


def _wb(doc=None, **kw):
    return load_workbook(io.BytesIO(_raw(doc, **kw)))


def _charts(doc=None, **kw):
    """[(sheet 名, chart)]，按 sheet 顺序（总览之后；零长度组没有图，跳过）。"""
    wb = _wb(doc, **kw)
    return [(name, wb[name]._charts[0]) for name in wb.sheetnames
            if name != SUMMARY_SHEET and wb[name]._charts]


def _chart_xmls(doc=None, **kw):
    with zipfile.ZipFile(io.BytesIO(_raw(doc, **kw))) as zf:
        names = [n for n in zf.namelist() if re.fullmatch(r'xl/charts/chart\d+\.xml', n)]
        names.sort(key=lambda n: int(re.search(r'(\d+)\.xml$', n).group(1)))
        return [zf.read(n).decode('utf-8') for n in names]


def _xml(doc=None, **kw):
    return ''.join(_chart_xmls(doc, **kw))


def _title(chart):
    runs = [getattr(r, 't', '') for p in chart.title.tx.rich.p
            for r in (p.r or [])] if chart.title else []
    return ''.join(runs) or None


def _axis_title(ax):
    runs = [getattr(r, 't', '') for p in ax.title.tx.rich.p
            for r in (p.r or [])] if ax.title else []
    return ''.join(runs) or None


def _group_max(doc, name):
    g = next(g for g in doc.groups if g.name == name)
    return max(len(s.values) for s in g.series) - 1


def _text(counts, length=8):
    lines = []
    for name, repeats in counts:
        for k in range(repeats):
            body = ', '.join(str(v + k) for v in range(length))
            lines.append(f'double {name}[{length}] = {{{body}}};')
    return '\n'.join(lines)


class ChartPerSheetTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = _doc()
        cls.charts = _charts(cls.doc)
        cls.xml = _xml(cls.doc)

    def test_one_chart_per_detail_sheet_and_none_in_summary(self):
        wb = _wb(self.doc)
        self.assertEqual(wb[SUMMARY_SHEET]._charts, [])
        self.assertEqual(len(self.charts), 14)
        self.assertEqual([name for name, _ in self.charts],
                         [f'WT{i + 1:04d}' for i in range(14)])

    def test_titles_are_test_item_names(self):
        self.assertEqual([_title(c) for _, c in self.charts], [g.name for g in self.doc.groups])

    def test_series_belong_to_the_sheet_group(self):
        name, chart = self.charts[0]
        self.assertEqual(name, 'WT0001')
        self.assertEqual([s.tx.v for s in chart.series],
                         ['WT0001_1', 'WT0001_2', 'WT0001_3', 'WT0001_4'])

    def test_geometry_is_16x11cm_at_a1(self):
        for _, chart in self.charts:
            self.assertEqual((chart.anchor._from.col, chart.anchor._from.row), (0, 0))
            self.assertEqual(chart.anchor.ext.cx, cm_to_EMU(CHART_WIDTH_CM))
            self.assertEqual(chart.anchor.ext.cy, cm_to_EMU(CHART_HEIGHT_CM))


class MarkerAndLabelTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = _doc()
        cls.plain = _charts(cls.doc)
        cls.with_mean = _charts(cls.doc, show_mean=True)
        cls.xml = _xml(cls.doc)
        cls.xml_mean = _xml(cls.doc, show_mean=True)

    def test_every_raw_series_has_a_filled_circle_marker(self):
        for _, chart in self.plain:
            for ser in chart.series:
                self.assertEqual(ser.marker.symbol, 'circle')
                self.assertEqual(ser.marker.size, MARKER_SIZE)
                # 标记必须显式填成线色；不填时 Excel 用主题默认色，图例和线会不同色
                self.assertEqual(ser.marker.graphicalProperties.solidFill.srgbClr,
                                 ser.graphicalProperties.line.solidFill.srgbClr)
        self.assertEqual(self.xml.count('<symbol val="circle"/>'), 56)

    def test_mean_has_no_marker(self):
        # marker.symbol='none' 读回是 None（与「未设置」同形）⇒ 真值只能看 XML 里的 none 标记
        for _, chart in self.with_mean:
            self.assertIsNone(chart.series[-1].marker.symbol)
        self.assertEqual(self.xml_mean.count('<symbol val="none"/>'), 14)

    def test_labels_only_on_the_mean_series(self):
        for _, chart in self.with_mean:
            for ser in chart.series[:-1]:
                self.assertIsNone(ser.dLbls)
            labels = chart.series[-1].dLbls
            self.assertTrue(labels.showVal)
            self.assertFalse(labels.showSerName)
            self.assertFalse(labels.showCatName)
            self.assertFalse(labels.showLegendKey)
            self.assertEqual(labels.numFmt, '0.00000')
            self.assertEqual(labels.position, 't')
        self.assertEqual(self.xml_mean.count('<dLbls>'), 14)

    def test_no_labels_when_mean_is_off(self):
        self.assertNotIn('<dLbls>', self.xml)

    def test_legend_is_right_on_every_chart(self):
        for _, chart in self.plain:
            self.assertIsNotNone(chart.legend)
            self.assertEqual(chart.legend.position, 'r')
        self.assertEqual(self.xml.count('legendPos val="r"'), 14)


class LineStyleAndColourTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = _doc()
        cls.charts = _charts(cls.doc)
        cls.charts_mean = _charts(cls.doc, show_mean=True)

    def test_dash_follows_within_group_and_resets_per_sheet(self):
        for _, chart in self.charts:
            self.assertEqual([s.graphicalProperties.line.dashStyle for s in chart.series],
                             list(DASH_BY_WITHIN_GROUP))

    def test_members_are_1_25_pt_and_use_the_group_colour(self):
        for _, chart in self.charts:
            for ser in chart.series:
                self.assertEqual(ser.graphicalProperties.line.w, LINE_WIDTH)
        for index, (_, chart) in enumerate(self.charts):
            want = DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)]
            for ser in chart.series:
                self.assertEqual(ser.graphicalProperties.line.solidFill.srgbClr, want)

    def test_mean_is_grey_dashed_and_not_covering_the_raw_lines(self):
        for _, chart in self.charts_mean:
            mean = chart.series[-1]
            self.assertEqual(mean.graphicalProperties.line.solidFill.srgbClr, '4B5563')
            self.assertEqual(mean.graphicalProperties.line.w, MEAN_WIDTH)
            self.assertEqual(mean.graphicalProperties.line.dashStyle, MEAN_DASH)
            self.assertGreater(MEAN_WIDTH, LINE_WIDTH)      # 仍比原始线粗一点
            self.assertIsNone(mean.marker.symbol)           # 'none' 读回 None；不盖原始圆点

    def test_palette_is_normalised_and_falls_back_per_slot(self):
        probe = ['#112233'] * 8
        first = _charts(self.doc, palette=probe)[0][1]
        self.assertEqual(first.series[0].graphicalProperties.line.solidFill.srgbClr, '112233')
        weird = _charts(self.doc, palette=['zzzzzz', 'x'] + ['2563eb'] * 6)
        self.assertEqual(weird[0][1].series[0].graphicalProperties.line.solidFill.srgbClr,
                         DEFAULT_PALETTE[0])
        self.assertEqual(weird[1][1].series[0].graphicalProperties.line.solidFill.srgbClr,
                         DEFAULT_PALETTE[1])
        self.assertEqual(weird[2][1].series[0].graphicalProperties.line.solidFill.srgbClr, '2563EB')

    def test_bad_mean_colour_falls_back_to_grey(self):
        chart = _charts(self.doc, show_mean=True, mean_color='nope')[0][1]
        self.assertEqual(chart.series[-1].graphicalProperties.line.solidFill.srgbClr, '4B5563')


class AxisTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = _doc()
        cls.charts = _charts(cls.doc)

    def test_x_axis_uses_each_groups_own_max(self):
        for name, chart in self.charts:
            want = float(_group_max(self.doc, name))
            self.assertEqual((chart.x_axis.scaling.min, chart.x_axis.scaling.max), (0.0, want), name)

    def test_y_axis_is_left_auto(self):
        for _, chart in self.charts:
            self.assertIsNone(chart.y_axis.scaling.min)
            self.assertIsNone(chart.y_axis.scaling.max)

    def test_axis_titles_and_numeric_axis(self):
        for _, chart in self.charts:
            self.assertEqual(type(chart.x_axis).__name__, 'NumericAxis')
            self.assertEqual(_axis_title(chart.x_axis), 'Code')
            self.assertEqual(_axis_title(chart.y_axis), 'Weight')

    def test_axes_are_bottom_left_with_visible_tick_labels(self):
        """openpyxl 默认两条轴都 axPos='l'，X/Y 叠在左侧、刻度被挤掉（用户实测）。
        这里逐图断：X 在底部、Y 在左侧、crosses=min（X 轴落在 y 最小值，不是穿过 y=0）、
        刻度标签 nextTo 且 delete=False。"""
        for _, chart in self.charts:
            self.assertEqual(chart.x_axis.axPos, 'b')
            self.assertEqual(chart.y_axis.axPos, 'l')
            self.assertEqual(chart.x_axis.crosses, 'min')
            self.assertEqual(chart.y_axis.crosses, 'min')
            self.assertEqual(chart.x_axis.tickLblPos, 'nextTo')
            self.assertEqual(chart.y_axis.tickLblPos, 'nextTo')
            self.assertFalse(chart.x_axis.delete)
            self.assertFalse(chart.y_axis.delete)

    def test_refs_point_at_this_sheets_header_and_rows(self):
        for name, chart in self.charts:
            g = next(g for g in self.doc.groups if g.name == name)
            last_col = get_column_letter(DETAIL_COL_VALUE0 + _group_max(self.doc, name))
            want_x = f"'{name}'!${get_column_letter(DETAIL_COL_VALUE0)}${DETAIL_HEADER_ROW}:${last_col}${DETAIL_HEADER_ROW}"
            for i, (ser, member) in enumerate(zip(chart.series, g.series)):
                row = DETAIL_FIRST_DATA_ROW + i
                self.assertEqual(ser.xVal.numRef.f, want_x, name)
                end = get_column_letter(DETAIL_COL_VALUE0 + len(member.values) - 1)
                self.assertEqual(ser.yVal.numRef.f,
                                 f"'{name}'!${get_column_letter(DETAIL_COL_VALUE0)}${row}:${end}${row}")
                self.assertIsNone(ser.val)


class DegenerateAndLiteralTests(TestCase):
    def test_zero_length_group_gets_no_chart(self):
        doc = parse_weight_text('double E[0] = {};\ndouble F[2] = {1.5, 2.5};\n')
        charts = _charts(doc)
        self.assertEqual([name for name, _ in charts], ['F'])

    def test_literal_avg_name_is_not_mistaken_for_the_mean_line(self):
        doc = parse_weight_text('double A[2] = {1.0, 2.0};\ndouble A[2] = {3.0, 4.0};\n'
                                'double A_Avg[2] = {5.0, 6.0};\n')
        charts = _charts(doc, show_mean=True)
        self.assertEqual([name for name, _ in charts], ['A', 'A_Avg'])
        a_chart = charts[0][1]
        self.assertEqual([s.tx.v for s in a_chart.series], ['A_1', 'A_2', 'A_Avg'])
        self.assertIsNone(a_chart.series[0].dLbls)
        self.assertIsNone(a_chart.series[1].dLbls)
        self.assertTrue(a_chart.series[2].dLbls.showVal)       # 真均值
        literal_chart = charts[1][1]
        self.assertEqual([s.tx.v for s in literal_chart.series], ['A_Avg', 'A_Avg_Avg'])
        self.assertIsNone(literal_chart.series[0].dLbls)        # 字面成员不是均值
        self.assertEqual(literal_chart.series[0].graphicalProperties.line.w, LINE_WIDTH)
        self.assertTrue(literal_chart.series[1].dLbls.showVal)

    def test_uneven_groups_each_get_their_own_chart(self):
        doc = parse_weight_text(_text((('A', 3), ('B', 2), ('C', 4))))
        charts = _charts(doc)
        self.assertEqual([[s.tx.v for s in chart.series] for _, chart in charts],
                         [['A_1', 'A_2', 'A_3'], ['B_1', 'B_2'],
                          ['C_1', 'C_2', 'C_3', 'C_4']])
        self.assertEqual([[s.graphicalProperties.line.dashStyle for s in chart.series]
                          for _, chart in charts],
                         [['solid', 'dash', 'dot'], ['solid', 'dash'],
                          ['solid', 'dash', 'dot', 'dashDot']])

    def test_only_visible_groups_get_charts(self):
        charts = _charts(_doc(), visible_group_indexes=[3])
        self.assertEqual([name for name, _ in charts], ['WT0004'])
        self.assertEqual([s.tx.v for s in charts[0][1].series],
                         ['WT0004_1', 'WT0004_2', 'WT0004_3', 'WT0004_4'])


class PaletteArgumentTests(TestCase):
    def test_palette_is_a_required_keyword_argument(self):
        doc = _doc()
        with self.assertRaisesRegex(TypeError, 'palette'):
            build_weight_workbook(doc)
        self.assertTrue(build_weight_workbook(doc, palette=DEFAULT_PALETTE))
