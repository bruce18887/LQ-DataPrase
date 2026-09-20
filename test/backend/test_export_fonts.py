"""导出物字族单一来源守门测试。

用户反馈「字体没有统一的设计语言」，导出侧的实际症状是同一家报告里混用
Calibri、等线、Arial 三种字族，且 matplotlib 有 3 份互不相同的候选列表。
这里用两层断言把「只有一个来源」固化下来：

1. 从**真实的 excelize 样式对象**读回 ``font.family``（走工厂的那部分）；
2. 扫 ``apps/export`` / ``apps/gage`` 源码，拦住就地写字面量的旁路
   （``excel_builders`` 在建表函数里直接 new_style，第 1 层覆盖不到）。

配色不在本测试范围内：buyoff/Gage 家族与 excelize_helpers 家族的配色被明确
要求保持分离（见 ``excel_theme`` 模块 docstring），本文件只锁字族。

runner: ``manage.py test test.backend.test_export_fonts``
"""
import pathlib
import re

import excelize
from django.test import SimpleTestCase

from apps.export import excel_theme, excelize_helpers, fonts
from apps.export.views import ATE_REPORT_CSS
from apps.gage import gage_styles

_FONT_SOURCE_NAME = 'fonts.py'
_LITERAL_FAMILY = re.compile(r"""family\s*=\s*['"]""")
_OWN_FONT_STACK = re.compile(r"""rcParams\[\s*['"]font\.sans-serif['"]\]""")


def _style_sources():
    """导出侧全部 Python 源文件（唯一字族声明处 fonts.py 除外）。"""
    roots = [pathlib.Path(fonts.__file__).parent,
             pathlib.Path(gage_styles.__file__).parent]
    for root in roots:
        for path in root.rglob('*.py'):
            if path.name != _FONT_SOURCE_NAME:
                yield path


def _flatten_style_ids(node):
    """把工厂返回值（int / tuple / list / dict）展平成 style id 列表。"""
    if isinstance(node, int):
        return [node]
    if isinstance(node, (tuple, list)):
        return [i for sub in node for i in _flatten_style_ids(sub)]
    if isinstance(node, dict):
        return [i for sub in node.values() for i in _flatten_style_ids(sub)]
    raise AssertionError(f'样式工厂返回了非 style id 形状：{node!r}')


class ExcelizeFamilyTests(SimpleTestCase):
    """两条 Excel 通道的所有样式工厂都必须落在同一个字族上。"""

    def setUp(self):
        self.f = excelize.new_file()

    def _assert_family(self, style_id, label):
        family = self.f.get_style(style_id).font.family
        self.assertEqual(
            family, fonts.EXCEL_FONT_FAMILY,
            f'{label} 的字族是 {family!r}，不是 {fonts.EXCEL_FONT_FAMILY!r}')

    def test_helpers_builders(self):
        builders = [
            excelize_helpers.make_header_style,
            excelize_helpers.make_data_style,
            excelize_helpers.make_red_style,
            excelize_helpers.make_unit_style,
            excelize_helpers.make_title_style,
            excelize_helpers.make_template_title_style,
            excelize_helpers.make_template_header_style,
            excelize_helpers.make_template_data_style,
            excelize_helpers.make_template_red_style,
            excelize_helpers.make_plain_header_style,
            excelize_helpers.make_plain_data_style,
            excelize_helpers.make_plain_red_style,
            excelize_helpers.make_plain_orange_style,
        ]
        for build in builders:
            self._assert_family(build(self.f), f'excelize_helpers.{build.__name__}')

    def test_excel_theme_builders(self):
        builders = [
            excel_theme.make_title_style,
            excel_theme.make_header_style,
            excel_theme.make_label_style,
            excel_theme.make_data_style,
            excel_theme.make_unit_style,
            excel_theme.make_section_style,
        ]
        for build in builders:
            self._assert_family(build(self.f), f'excel_theme.{build.__name__}')
        for kind in ('pass', 'warn', 'fail', 'na'):
            self._assert_family(
                excel_theme.make_verdict_style(self.f, kind),
                f'excel_theme.make_verdict_style({kind})')

    def test_gage_style_groups(self):
        for build in (gage_styles.create_summary_styles,
                      gage_styles.create_file_sheet_styles):
            for style_id in _flatten_style_ids(build(self.f)):
                self._assert_family(style_id, f'gage_styles.{build.__name__}')


class NoBypassSourceTests(SimpleTestCase):
    """源码级守门：绕过 ``fonts`` 就地写字族/字族列表，测试必须红。"""

    def _offenders(self, pattern):
        return sorted(path.name for path in _style_sources() if pattern.search(
            path.read_text(encoding='utf-8')))

    def test_no_literal_font_family(self):
        self.assertEqual(
            self._offenders(_LITERAL_FAMILY), [],
            '有文件就地写死了字族字面量，应改用 fonts.EXCEL_FONT_FAMILY')

    def test_no_entrypoint_owns_a_font_stack(self):
        self.assertEqual(
            self._offenders(_OWN_FONT_STACK), [],
            '有渲染入口自带 font.sans-serif 列表，应改调 fonts.apply_matplotlib_fonts()')


class OpenpyxlFamilyTests(SimpleTestCase):
    def test_header_font_names_family(self):
        from apps.export import export_batch_charts_xlsx as batch
        self.assertEqual(batch.HEADER_FONT.name, fonts.EXCEL_FONT_FAMILY)


class MatplotlibFontsTests(SimpleTestCase):
    def test_apply_sets_shared_stack(self):
        from matplotlib import pyplot as plt
        original = {k: plt.rcParams[k] for k in ('font.sans-serif', 'axes.unicode_minus')}
        try:
            fonts.apply_matplotlib_fonts()
            self.assertEqual(list(plt.rcParams['font.sans-serif']),
                             list(fonts.MATPLOTLIB_SANS_SERIF))
            self.assertFalse(plt.rcParams['axes.unicode_minus'])
        finally:
            plt.rcParams.update(original)

    def test_cjk_fallback_precedes_deja_vu(self):
        """DejaVu 无中文字形，排在它后面的候选命中就等于渲染方块 —— 中文兜底必须在它之前。"""
        stack = list(fonts.MATPLOTLIB_SANS_SERIF)
        self.assertIn('DejaVu Sans', stack)
        cjk_before = [n for n in stack[:stack.index('DejaVu Sans')]
                      if n in ('SimHei', 'Microsoft YaHei', 'SimSun')]
        self.assertTrue(cjk_before, f'DejaVu 之前没有中文字体候选：{stack}')

    def test_first_candidate_keeps_legacy_look(self):
        """SimHei 居首是刻意的：换优先级会让既有报告的 PNG 字形从黑体变雅黑。"""
        self.assertEqual(fonts.MATPLOTLIB_SANS_SERIF[0], 'SimHei')


class HtmlReportFontTests(SimpleTestCase):
    def test_report_css_uses_cjk_stack(self):
        self.assertIn(fonts.HTML_FONT_STACK, ATE_REPORT_CSS)
        for name in ('Microsoft YaHei', 'Noto Sans CJK SC'):
            self.assertIn(name, ATE_REPORT_CSS)

    def test_report_css_has_no_bare_arial_body(self):
        """中文正文写裸 Arial 时没有 CJK 回退，靠浏览器猜。"""
        self.assertNotIn('font-family:Arial', ATE_REPORT_CSS)
