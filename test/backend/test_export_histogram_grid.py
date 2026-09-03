"""导出直方图网格回归（apps/export/charts.py + histogram_grid.py）。

覆盖缺陷：

* **#3 x 轴标签与 bin 边界错开**：x 轴刻度必须由 bin 边界推导（bin 中心），
  不能另算一套公式（此前 ``low + (i-2)*gap`` 与 ``low - 2.5*gap`` 起点各自
  硬编码，两者只是碰巧相等——改一处就漂移）。
* **#4 导出与屏幕网格不一致**：屏幕侧 25 条内边界 + ±inf = 27 边界（26 bin，
  含 under/overflow），导出侧曾是 26 条有限边界（25 bin、无兜底）→ 网格平移
  0.5·gap 且超范围值被 ``np.histogram`` 静默丢弃。
* **#5 幻影 limit 使导出图空白**：``low == high``（限值缺失时上游回退 0.0）
  → gap 兜底 1.0、bins −2.5..22.5，TEMP 型数据（25~33）8 个点全部落空。

运行：``manage.py test test.backend.test_export_histogram_grid``
"""

import numpy as np
import pandas as pd
from types import SimpleNamespace

from django.test import SimpleTestCase
from matplotlib.axes import Axes

from apps.analysis.services.data_services import compute_histogram_stats
from apps.analysis.services.statistics import filter_finite
from apps.export.charts import _render_histogram_payload, build_histogram_bins
from apps.export.export_ppt import build_batch_charts_pptx
from apps.export.histogram_grid import build_histogram_grid, resolve_bin_range

TEMP = np.array([25.0, 26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 33.0])


def _assert_pair(test, actual, expected, places=9):
    """逐元素比较 (low, high)——assertAlmostEqual 不接受元组。"""
    test.assertEqual(len(actual), 2)
    for got, want in zip(actual, expected):
        test.assertAlmostEqual(got, want, places=places)


def _spy_ax_bar(test):
    """截获 ``Axes.bar`` 的实参（patch 的是实际消费方的类绑定）并 addCleanup 还原。

    直方图“是否空白”无法从 PNG 字节判定，只能从柱高判定。
    """
    recorded = []
    original = Axes.bar

    def spy(self, x, height, *args, **kwargs):
        recorded.append((list(np.asarray(x, dtype=float)),
                         list(np.asarray(height, dtype=float))))
        return original(self, x, height, *args, **kwargs)

    Axes.bar = spy
    test.addCleanup(setattr, Axes, 'bar', original)
    return recorded


class GridMatchesScreenTests(SimpleTestCase):
    """缺陷 #4：导出网格必须与屏幕直方图服务逐值一致。"""

    PARAM = 'P'

    def setUp(self):
        self.df = pd.DataFrame({self.PARAM: np.linspace(0.5, 19.5, 200)})
        self.metadata = {'units': {self.PARAM: 'V'}, 'mins': {self.PARAM: '0'},
                         'maxs': {self.PARAM: '20'}, 'format': 'CTA8290D'}
        self.screen = compute_histogram_stats(
            self.df, self.metadata, self.PARAM, None, range_type='RDL')
        self.data = filter_finite(self.df[self.PARAM])
        self.edges, self.centers, self.gap = build_histogram_grid(
            self.screen['lower_limit'], self.screen['upper_limit'], self.data)

    def test_screen_reference_is_the_rdl_grid(self):
        """用例前置：屏幕侧 26 个 bin 中心（1 underflow + 24 常规 + 1 overflow）。"""
        self.assertEqual(len(self.screen['bin_centers']), 26)

    def test_export_centers_equal_screen_centers(self):
        self.assertEqual([round(c, 6) for c in self.centers],
                         self.screen['bin_centers'],
                         msg='导出 bin 中心必须与屏幕逐值相同')

    def test_edges_are_27_with_infinite_catch_all(self):
        self.assertEqual(len(self.edges), 27)
        self.assertEqual(self.edges[0], -np.inf)
        self.assertEqual(self.edges[-1], np.inf)
        self.assertEqual(len(self.centers), len(self.edges) - 1)

    def test_bin_width_equals_gap(self):
        finite = self.edges[np.isfinite(self.edges)]
        self.assertEqual(len(finite), 25)
        self.assertTrue(np.allclose(np.diff(finite), self.gap))
        self.assertAlmostEqual(self.gap, 1.0, places=9)      # (20-0)/20

    def test_inner_edges_start_two_gaps_below_low_limit(self):
        """屏幕外扩口径：两侧各 2 个细分 bin（不是导出侧曾经的 2.5 gap）。"""
        finite = self.edges[np.isfinite(self.edges)]
        self.assertAlmostEqual(finite[0], 0.0 - 2 * self.gap, places=9)
        self.assertAlmostEqual(finite[-1], 0.0 + 22 * self.gap, places=9)

    def test_out_of_range_values_are_not_dropped(self):
        data = np.array([-50.0, 0.5, 10.0, 19.5, 999.0])
        edges, centers, _ = build_histogram_grid(0.0, 20.0, data)
        counts, _ = np.histogram(data, bins=edges)
        self.assertEqual(len(counts), len(centers))
        self.assertEqual(int(counts.sum()), len(data), '超范围值不得被静默丢弃')
        self.assertEqual(int(counts[0]), 1, 'underflow bin 应捕获 −50')
        self.assertEqual(int(counts[-1]), 1, 'overflow bin 应捕获 999')


class XLabelsDerivedFromBinsTests(SimpleTestCase):
    """缺陷 #3：x 轴刻度 == bin 中心，由边界推导而非另算一套。"""

    def test_labels_are_bin_centers_for_every_bin(self):
        edges, centers, gap = build_histogram_grid(0.0, 20.0)
        finite = edges[np.isfinite(edges)]
        expected = ([finite[0] - gap]
                    + [(finite[i] + finite[i + 1]) / 2 for i in range(len(finite) - 1)]
                    + [finite[-1] + gap])
        self.assertEqual(len(centers), len(expected))
        self.assertTrue(np.allclose(centers, expected))

    def test_labels_span_matches_bin_span(self):
        """刻度间距：常规 bin 之间 == gap；首/末（under/overflow 中心）== 1.5·gap。"""
        _, centers, gap = build_histogram_grid(0.0, 20.0)
        steps = np.diff(centers)
        self.assertTrue(np.allclose(steps[1:-1], gap))
        self.assertAlmostEqual(steps[0], 1.5 * gap, places=9)
        self.assertAlmostEqual(steps[-1], 1.5 * gap, places=9)


class DegenerateLimitTests(SimpleTestCase):
    """缺陷 #5：限值退化（缺失/占位/零宽）必须回退到数据范围。"""

    def test_zero_width_limits_fall_back_to_data_range(self):
        low, high = resolve_bin_range(0.0, 0.0, TEMP)
        self.assertAlmostEqual(low, 25.0, places=9)
        self.assertAlmostEqual(high, 33.0, places=9)

    def test_none_limits_fall_back_to_data_range(self):
        """parse_limit_string 新语义：限值缺失/占位/'Min'/'Max' → None。"""
        for low_in, high_in in ((None, None), (None, 20.0), (0.0, None)):
            with self.subTest(limits=(low_in, high_in)):
                low, high = resolve_bin_range(low_in, high_in, TEMP)
                self.assertLess(low, high)
                self.assertAlmostEqual(low, 25.0, places=9)
                self.assertAlmostEqual(high, 33.0, places=9)

    def test_inverted_limits_fall_back_to_data_range(self):
        _assert_pair(self, resolve_bin_range(30.0, 10.0, TEMP), (25.0, 33.0))

    def test_no_data_zero_width_yields_nonzero_window(self):
        """数据也退化时给 ±0.5 窗口（与屏幕 histogram.py 同口径），gap > 0。"""
        _assert_pair(self, resolve_bin_range(10.0, 10.0, None), (9.5, 10.5))
        _, centers, gap = build_histogram_grid(10.0, 10.0, None)
        self.assertGreater(gap, 0.0)
        self.assertEqual(len(centers), 26)

    def test_nan_limit_is_treated_as_missing(self):
        _assert_pair(self, resolve_bin_range(float('nan'), float('nan'), TEMP),
                     (25.0, 33.0))

    def test_grid_captures_all_points_under_phantom_limits(self):
        edges, centers, _ = build_histogram_grid(0.0, 0.0, TEMP)
        counts, _ = np.histogram(TEMP, bins=edges)
        self.assertEqual(int(counts.sum()), len(TEMP),
                         msg='幻影 limit（0,0）下 8 个数据点必须全部入 bin')


class PhantomLimitChartNotEmptyTests(SimpleTestCase):
    """端到端：rdl=(0,0) + TEMP 数据 → 导出直方图柱高之和 == 100%。"""

    def test_precondition_legacy_grid_captures_nothing(self):
        """用例前置（旧代码为何图是空的）：限值缺失时上游 parse_limit_string
        回退 0.0 → 幻影 (0, 0) → 旧几何 gap 兜底 1.0、bins −2.5..22.5，
        TEMP 型数据（25~33）的 8 个点**全部落在 bin 范围外**。
        """
        legacy_bins, legacy_gap = build_histogram_bins(0.0, 0.0)
        self.assertEqual(legacy_gap, 1.0)
        counts, _ = np.histogram(TEMP, bins=legacy_bins)
        self.assertEqual(int(counts.sum()), 0,
                         '前置不成立：旧网格应把 8 个点全部丢弃')

    def test_chart_captures_all_points_with_degenerate_limits(self):
        recorded = _spy_ax_bar(self)
        buf = _render_histogram_payload(
            'TEMP', TEMP, None, None,
            float(TEMP.mean()), float(TEMP.std(ddof=0)), 0.0, 0.0,
        )
        self.addCleanup(buf.close)
        self.assertGreater(buf.getbuffer().nbytes, 0, 'PNG 不应为空')
        self.assertTrue(recorded, '渲染必须画柱')
        total = sum(sum(heights) for _, heights in recorded)
        self.assertAlmostEqual(total, 100.0, places=3,
                               msg='柱高百分比之和应为 100%（此前恒为 0 → 导出图空白）')

    def test_chart_captures_all_points_with_none_limits(self):
        recorded = _spy_ax_bar(self)
        buf = _render_histogram_payload(
            'TEMP', TEMP, None, None,
            float(TEMP.mean()), float(TEMP.std(ddof=0)), None, None,
        )
        self.addCleanup(buf.close)
        total = sum(sum(heights) for _, heights in recorded)
        self.assertAlmostEqual(total, 100.0, places=3)

    def test_site_grouped_chart_captures_all_points(self):
        recorded = _spy_ax_bar(self)
        site_series = np.array([1, 1, 1, 1, 2, 2, 2, 2])
        buf = _render_histogram_payload(
            'TEMP', TEMP, [1, 2], site_series,
            float(TEMP.mean()), float(TEMP.std(ddof=0)), None, None,
        )
        self.addCleanup(buf.close)
        self.assertEqual(len(recorded), 2, '两个 site 各画一组柱')
        for _, heights in recorded:
            self.assertAlmostEqual(sum(heights), 100.0, places=3,
                                     msg='每个 site 内部归一，柱高之和应为 100%'
                                         '（此前恒为 0 → 导出图空白）')


class PptxPhantomLimitTests(SimpleTestCase):
    """缺陷 #5 端到端（PPT 侧）：限值缺失不得让导出的 PPT 直方图完全空白。

    ``build_histogram_bins(0.0, 0.0)`` 走 ``data_gap=1.0`` 兜底、bins 变成
    −2.5..22.5，而屏幕侧会回退到数据范围正常渲染 → 用户看屏有图、导出空白。
    """

    def _bars(self, raw_low, raw_high):
        recorded = _spy_ax_bar(self)
        df = pd.DataFrame({'TEMP': TEMP})
        metadata = {'units': {'TEMP': 'C'}, 'mins': {'TEMP': raw_low},
                    'maxs': {'TEMP': raw_high}, 'format': 'CTA8290D'}
        datafile = SimpleNamespace(filename='t.csv', format_type='CTA8290D',
                                  program_name='P')
        blob = build_batch_charts_pptx(datafile, df, metadata, ['TEMP'])
        self.assertGreater(len(blob), 0, 'PPTX 不得为空')
        return recorded

    def test_missing_limits_chart_is_not_blank(self):
        """空串限值（上游回退 0.0 → 幻影 (0,0)）下 8 个点必须全部入 bin。"""
        recorded = self._bars('', '')
        self.assertTrue(recorded, '渲染必须画柱')
        self.assertEqual(sum(sum(heights) for _, heights in recorded), len(TEMP),
                         msg='柱高（频数）之和应为 8，此前恒为 0 → PPT 图空白')

    def test_placeholder_keyword_limits_chart_is_not_blank(self):
        """``parse_limit_string`` 新语义下字面 'Min'/'Max' → None，同样不得空白。"""
        recorded = self._bars('Min', 'Max')
        self.assertEqual(sum(sum(heights) for _, heights in recorded), len(TEMP))

    def test_normal_limits_still_capture_all_points(self):
        recorded = self._bars('20', '40')
        self.assertEqual(sum(sum(heights) for _, heights in recorded), len(TEMP))


class TinyBarPrecisionTests(SimpleTestCase):
    """缺陷 #12：导出直方图百分比必须 6 位口径。

    屏幕侧 histogram.py 已因同一问题回归过（tiny-fail-bar：1/50000 = 0.002%
    被 ``round(…, 2)`` 归零 → 柱高 0，fail bin 在图上看不见），导出侧仍是 2 位。
    """

    def test_single_point_in_50000_keeps_nonzero_bar(self):
        recorded = _spy_ax_bar(self)
        data = np.full(50000, 10.0)
        data[0] = 0.5                      # 独占一个 bin → 1/50000 = 0.002%
        buf = _render_histogram_payload(
            'P', data, None, None, float(data.mean()), float(data.std(ddof=0)),
            0.0, 20.0,
        )
        self.addCleanup(buf.close)
        heights = [h for _, hs in recorded for h in hs]
        nonzero = [h for h in heights if h > 0]
        self.assertEqual(len(nonzero), 2, f'应有两个非零柱，实际 {heights}')
        self.assertAlmostEqual(min(nonzero), 0.002, places=6,
                               msg='1/50000 的柱不得被 round(…, 2) 归零')
        self.assertAlmostEqual(sum(heights), 100.0, places=3)


class LegacyBinsShimTests(SimpleTestCase):
    """``build_histogram_bins`` 保留为兼容 shim（既有 apps/export/tests.py 仍 pin 它）。

    生产路径必须走 ``build_histogram_grid``；shim 只保证旧断言不破。
    """

    def test_shim_keeps_legacy_geometry(self):
        bins, gap = build_histogram_bins(10.0, 30.0)
        self.assertEqual(len(bins), 26)
        self.assertAlmostEqual(gap, 1.0, places=9)
        self.assertAlmostEqual(bins[0], 7.5, places=9)

    def test_shim_is_not_used_by_grid(self):
        _, centers, _ = build_histogram_grid(10.0, 30.0)
        self.assertEqual(len(centers), 26)
        self.assertNotAlmostEqual(centers[0], 7.5, places=9)
