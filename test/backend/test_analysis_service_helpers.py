"""序列分布与分箱区间的纯函数单测。

这些判据原先只能从 ``/analysis/serial/`` 与 ``/analysis/histogram/`` 的整体
响应里间接观察；抽成纯函数后可以直接钉住行为（anchor 编码、降采样是否丢
超界点、markLine 的开关与数值、退化区间的兜底顺序）。
"""
import math

import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.data_services.histogram import resolve_bin_range
from apps.analysis.services.data_services.serial_distribution import (
    anchor_for,
    build_mark_lines,
    build_serial_points,
    downsample_points,
    _group_final_rows,
)
from apps.analysis.services.statistics.downsample import DOWN_SAMPLE_THRESHOLD


class AnchorForTests(SimpleTestCase):
    def test_flags_out_of_range_and_missing_value(self):
        self.assertEqual(anchor_for(1.5, 0.0, 2.0), 0)
        self.assertEqual(anchor_for(2.5, 0.0, 2.0), 2)
        self.assertEqual(anchor_for(-1.0, 0.0, 2.0), 3)
        self.assertEqual(anchor_for(float('nan'), 0.0, 2.0), 1)
        self.assertEqual(anchor_for(None, 0.0, 2.0), 1)

    def test_open_axis_never_clips(self):
        """缺限值时不存在「超出轴」，超大值也必须按正常点画。"""
        self.assertEqual(anchor_for(1e9, None, None), 0)


class BuildSerialPointsTests(SimpleTestCase):
    def setUp(self):
        self.grouped = pd.DataFrame({
            'Serial_No': [1, 2, 3],
            'VOLT': [1.0, None, 3.0],
        })

    def test_two_tuple_shape_when_file_has_no_bin_column(self):
        pts = build_serial_points(self.grouped, 'Serial_No', 'VOLT',
                                  [1, 2, 3], None, 0.0, 2.0)
        self.assertEqual(len(pts), 3)
        self.assertEqual(pts[0], [1, 1.0])
        self.assertTrue(all(len(p) == 2 for p in pts))

    def test_four_tuple_shape_carries_fail_and_anchor(self):
        fail_by_serial = {1: 0, 2: 0, 3: 1}
        pts = build_serial_points(self.grouped, 'Serial_No', 'VOLT',
                                  [1, 2, 3], fail_by_serial, 0.0, 2.0)
        self.assertEqual(pts[0], [1, 1.0, 0, 0])
        # 无测量值：值写成 None（不能把 NaN 送进 JSON），anchor=1
        self.assertIsNone(pts[1][1])
        self.assertEqual(pts[1][2:], [0, 1])
        # 有值但超出上界：anchor=2，且 die 级 fail 仍按最终 Bin
        self.assertEqual(pts[2], [3, 3.0, 1, 2])

    def test_serials_absent_from_the_group_are_skipped(self):
        pts = build_serial_points(self.grouped, 'Serial_No', 'VOLT',
                                  [1, 2, 3, 4], None, 0.0, 2.0)
        self.assertEqual([p[0] for p in pts], [1, 2, 3])


class DownsamplePointsTests(SimpleTestCase):
    def test_small_point_sets_pass_through(self):
        pts = [[i, float(i)] for i in range(3)]
        self.assertEqual(downsample_points(pts), pts)

    def test_anchor_flagged_points_are_always_kept(self):
        """降采样只压体量，不许丢掉「被锚到轴边的超界点」——那是它唯一的视觉信息。"""
        n = DOWN_SAMPLE_THRESHOLD + 50
        pts = [[i, 1.0 + (i % 5) * 0.1, 0, 0] for i in range(n)]
        out_of_range = [123, 4001]
        for row in out_of_range:
            pts[row] = [row, 99.0, 1, 2]

        kept = downsample_points(pts)

        self.assertLess(len(kept), len(pts))
        for row in out_of_range:
            self.assertIn(pts[row], kept, f'anchor≠0 的行 {row} 被降采样丢了')
        self.assertTrue(all(isinstance(p[1], float) and not math.isnan(p[1])
                            for p in kept))


class GroupFinalRowsTests(SimpleTestCase):
    """「一颗 die 只算一次，取最后一次重测」是全条链路的前提。"""

    def test_retest_rows_collapse_to_the_last_value(self):
        df = pd.DataFrame({'Serial_No': [1, 1, 2], 'VOLT': [1.0, 2.5, 3.0]})
        grouped = _group_final_rows(df, 'VOLT', 'Serial_No', None, None)
        self.assertEqual(list(grouped.columns), ['Serial_No', 'VOLT'])
        self.assertEqual(grouped['Serial_No'].tolist(), [1, 2])
        self.assertEqual(grouped['VOLT'].tolist(), [2.5, 3.0])

    def test_site_key_keeps_same_serial_apart(self):
        df = pd.DataFrame({
            'Site_No': ['1', '1', '2'],
            'Serial_No': [1, 1, 1],
            'VOLT': [1.0, 2.0, 3.0],
        })
        grouped = _group_final_rows(df, 'VOLT', 'Serial_No', 'Site_No', None)
        self.assertEqual(list(grouped.columns), ['Site_No', 'Serial_No', 'VOLT'])
        self.assertEqual(grouped['VOLT'].tolist(), [2.0, 3.0])

    def test_unmeasured_die_survives_because_it_still_has_a_bin(self):
        df = pd.DataFrame({
            'Serial_No': [1, 2],
            'VOLT': [1.0, float('nan')],
            'SW_Bin': [1, 2],
        })
        grouped = _group_final_rows(df, 'VOLT', 'Serial_No', None, 'SW_Bin')
        self.assertEqual(list(grouped.columns), ['Serial_No', 'VOLT', 'SW_Bin'])
        self.assertEqual(grouped['SW_Bin'].tolist(), [1, 2])
        self.assertTrue(math.isnan(grouped['VOLT'].tolist()[1]))

    def test_inf_rows_are_dropped(self):
        """inf 不是有限值，也不该被当成「没测到」画出来。"""
        df = pd.DataFrame({
            'Serial_No': [1, 2],
            'VOLT': [1.0, float('inf')],
            'SW_Bin': [1, 1],
        })
        grouped = _group_final_rows(df, 'VOLT', 'Serial_No', None, 'SW_Bin')
        self.assertEqual(grouped['Serial_No'].tolist(), [1])

    def test_object_dtype_param_is_coerced(self):
        """str dtype 的测试项（列里混了文本）必须能比较，而不是抛类型错。"""
        df = pd.DataFrame({'Serial_No': [1, 2], 'VOLT': ['1.5', '2.5']})
        grouped = _group_final_rows(df, 'VOLT', 'Serial_No', None, None)
        self.assertEqual(grouped['VOLT'].tolist(), [1.5, 2.5])


class BuildMarkLinesTests(SimpleTestCase):
    def test_spec_limit_pair(self):
        marks = build_mark_lines(0.0, 10.0, 5.0, 1.0, ['limit'])
        self.assertEqual([m['name'] for m in marks], ['规格限'])
        entries = marks[0]['markLine']['data']
        self.assertEqual([e['yAxis'] for e in entries], [0.0, 10.0])
        self.assertEqual([e['label']['formatter'] for e in entries], ['LSL', 'USL'])

    def test_one_sided_limits_omit_the_group(self):
        """缺任一侧就不画「规格限」线，避免把单侧限画成一对幻影线。"""
        self.assertEqual(build_mark_lines(None, 10.0, 5.0, 1.0, ['limit']), [])
        self.assertEqual(build_mark_lines(0.0, None, 5.0, 1.0, ['limit']), [])

    def test_sigma_groups_follow_config_order_and_width(self):
        marks = build_mark_lines(0.0, 10.0, 5.0, 1.0, ['s6', 's3'])
        self.assertEqual([m['name'] for m in marks], ['3σ范围', '6σ范围'])
        self.assertEqual([e['yAxis'] for e in marks[0]['markLine']['data']], [2.0, 8.0])
        self.assertEqual([e['yAxis'] for e in marks[1]['markLine']['data']], [-1.0, 11.0])
        self.assertEqual(
            [e['label']['formatter'] for e in marks[0]['markLine']['data']],
            ['3σ下限', '3σ上限'])

    def test_empty_config_produces_nothing(self):
        self.assertEqual(build_mark_lines(0.0, 10.0, 5.0, 1.0, []), [])


def _stats(rdl=None, dr=None, cl=None, s3=None, s4=None, s6=None):
    return {
        'rdl': rdl or (0.0, 0.0),
        'dr': dr or (0.0, 0.0),
        'cl': cl or (0.0, 0.0),
        's3': s3 or (0.0, 0.0),
        's4': s4 or (0.0, 0.0),
        's6': s6 or (0.0, 0.0),
    }


class ResolveBinRangeTests(SimpleTestCase):
    def test_custom_bounds_win_in_cl(self):
        series = pd.Series([1.0, 2.0, 3.0])
        self.assertEqual(
            resolve_bin_range('CL', _stats(), 10.4, 10.5, series),
            (10.4, 10.5))

    def test_cl_without_custom_falls_back_to_stats(self):
        series = pd.Series([1.0, 2.0, 3.0])
        stats = _stats(cl=(1.0, 3.0))
        self.assertEqual(resolve_bin_range('CL', stats, 10.4, None, series),
                         (1.0, 3.0))

    def test_one_sided_limit_falls_back_per_side(self):
        """单边限值（USL 写成 'MAX' 占位）不能让 None 活到 safe_gap → 500。"""
        series = pd.Series([1.0, 2.0, 3.0])
        stats = _stats(rdl=(0.0, None))
        self.assertEqual(resolve_bin_range('RDL', stats, None, None, series),
                         (0.0, 3.0))

    def test_zero_width_sigma_range_widens_to_data_then_pm_half(self):
        """std==0 时 σ 区间零宽：先回退数据范围，数据也零宽再 ±0.5。"""
        flat = pd.Series([5.0, 5.0, 5.0])
        stats = _stats(s3=(5.0, 5.0), dr=(5.0, 5.0))
        self.assertEqual(resolve_bin_range('S3', stats, None, None, flat),
                         (4.5, 5.5))

    def test_unrecognized_range_type_falls_back_to_data_range(self):
        series = pd.Series([1.0, 2.0, 3.0])
        self.assertEqual(resolve_bin_range('S9', _stats(), None, None, series),
                         (1.0, 3.0))
