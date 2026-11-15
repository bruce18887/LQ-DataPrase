"""导出直方图视觉规格与屏幕直方图的对齐判据（light 主题口径）。

屏幕侧权威实现：

* 色板 / 柱高百分比格式 / 轴刻度格式：``frontend/src/utils/chart-bar.ts``
* 版式（标题、双 Y 轴、All Site 系列）：``frontend/src/pages/analysis/components/HistogramChart.vue``

为什么不直接 import 前端 TS：Python 侧读不了 TS 模块，色板是一份复制。
两份字面量漂移时没有任何运行时症状（导出图照常生成，只是颜色变了），
只有肉眼能发现 ⇒ 用源码扫描把「逐值相等」钉成 T1 判据。
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from apps.export import charts, grouping
from apps.export.charts import _format_axis_value, _format_percent

BASE_DIR = Path(__file__).resolve().parents[2]
CHART_BAR_TS = BASE_DIR / 'frontend' / 'src' / 'utils' / 'chart-bar.ts'
GROUPING_TS = BASE_DIR / 'frontend' / 'src' / 'pages' / 'data' / 'composables' / 'exportGrouping.ts'


class SitePaletteParityTests(SimpleTestCase):
    """导出站点 8 色必须与前端 SITE_COLORS_8_LIGHT 逐值相同。"""

    def test_backend_palette_matches_frontend_light_palette(self):
        source = CHART_BAR_TS.read_text(encoding='utf-8')
        match = re.search(r'SITE_COLORS_8_LIGHT[^=]*=\s*\[(.*?)\]', source, re.S)
        self.assertIsNotNone(match, 'frontend chart-bar.ts 的 SITE_COLORS_8_LIGHT 未找到')
        frontend = re.findall(r'#[0-9A-Fa-f]{6}', match.group(1))
        self.assertEqual(
            [c.upper() for c in charts.COLORS_SITE_8],
            [c.upper() for c in frontend],
            '导出站点色板必须与前端 SITE_COLORS_8_LIGHT 逐值一致（改色两边同改）',
        )


class GroupingConstantParityTests(SimpleTestCase):
    """分类保留名与「每页上限」三常量必须与前端 `exportGrouping.ts` 逐值相同。

    前端按这些值渲染下拉框与「其他」行，后端按它们做契约校验与装箱。单侧改动
    没有任何运行时症状（导出照常出文件），只有用户选到后端不认的值时才 400 ——
    所以同样用源码扫描把「逐值相等」钉成 T1 判据。
    """

    def test_frontend_literals_match_backend_grouping_constants(self):
        source = GROUPING_TS.read_text(encoding='utf-8')

        other = re.search(r"OTHER_GROUP_NAME\s*=\s*'([^']*)'", source)
        self.assertIsNotNone(other, 'frontend exportGrouping.ts 的 OTHER_GROUP_NAME 未找到')
        self.assertEqual(other.group(1), grouping.OTHER_GROUP_NAME,
                         '「其他」保留名必须两边同值')

        options = re.search(r'MAX_ITEMS_OPTIONS\s*=\s*\[([^\]]*)\]', source)
        self.assertIsNotNone(options, 'frontend exportGrouping.ts 的 MAX_ITEMS_OPTIONS 未找到')
        self.assertEqual([int(v) for v in re.findall(r'\d+', options.group(1))],
                         list(grouping.ALLOWED_MAX_ITEMS_PER_SHEET),
                         '每页上限可选值必须与后端白名单逐值一致（否则下拉能选出 400）')

        default = re.search(r'DEFAULT_MAX_ITEMS\s*=\s*(\d+)', source)
        self.assertIsNotNone(default, 'frontend exportGrouping.ts 的 DEFAULT_MAX_ITEMS 未找到')
        self.assertEqual(int(default.group(1)), grouping.DEFAULT_MAX_ITEMS_PER_SHEET,
                         '默认上限必须与后端缺省一致')


class PercentFormatTests(SimpleTestCase):
    """柱顶百分比标签必须与前端 formatPercent 同口径（2→3 位自适应）。"""

    def test_zero_and_tiny_values(self):
        self.assertEqual(_format_percent(0), '0')
        self.assertEqual(_format_percent(-1), '0')
        self.assertEqual(_format_percent(0.0004), '<0.001')

    def test_adaptive_decimals(self):
        self.assertEqual(_format_percent(0.005), '0.005')
        self.assertEqual(_format_percent(0.05), '0.05')
        self.assertEqual(_format_percent(0.12), '0.12')
        self.assertEqual(_format_percent(3.10), '3.1')
        self.assertEqual(_format_percent(10.0), '10')


class AxisValueFormatTests(SimpleTestCase):
    """X 轴刻度必须与前端 formatAxisValue 同口径：整数原样、最多 4 位去尾零。"""

    def test_integer_passthrough(self):
        self.assertEqual(_format_axis_value(10), '10')
        self.assertEqual(_format_axis_value(-3), '-3')

    def test_trailing_zeros_stripped(self):
        self.assertEqual(_format_axis_value(10.5), '10.5')
        self.assertEqual(_format_axis_value(12.34567), '12.3457')
        self.assertEqual(_format_axis_value(0.3), '0.3')
