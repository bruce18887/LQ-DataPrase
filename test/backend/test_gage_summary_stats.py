"""Gage R&R 统计口径的直接单测（不经过 Excel）。

这些断言原先只能从生成的 xlsx 单元格反推；统计拆到
``apps.gage.gage_summary_stats`` 后可以按手算值直接钉住，覆盖历史上
逐个修过的缺陷：#1 空文件不污染、#3 限值 0 要当真值、#4 Min/Max CPK
不是 overall_cpk、#5 缺公差时 R&R%/Fail Level 一起 N/A、#7 系统列恒排除。
"""
import math

import pandas as pd
from django.test import SimpleTestCase

from apps.gage.gage_summary_stats import (
    RR_PCT_BAD1,
    RR_PCT_BAD2,
    analyze_test_item,
    safe_float_or_none,
    select_test_columns,
)

PARAM = 'TestA'
# [1,2,3] 的均值 2、总体 σ = sqrt(2/3)
MEAN_A = 2.0
STD_123 = math.sqrt(2 / 3)
CPK_0_10 = (MEAN_A - 0.0) / (3 * STD_123)


def _dataset(filename, values, low=None, high=None, extra=None, fmt='CTA8290D'):
    columns = {PARAM: values}
    if extra:
        columns.update(extra)
    df = pd.DataFrame(columns)
    metadata = {'format': fmt, 'units': {}, 'mins': {}, 'maxs': {}}
    if low is not None:
        metadata['mins'][PARAM] = low
    if high is not None:
        metadata['maxs'][PARAM] = high
    return {'filename': filename, 'df': df, 'metadata': metadata}


class SafeFloatOrNoneTests(SimpleTestCase):
    def test_distinguishes_real_zero_from_missing(self):
        """defect #3：0 与 '0' 都是合法限值，只有缺失/非数值才返回 None。"""
        self.assertEqual(safe_float_or_none(0), 0.0)
        self.assertEqual(safe_float_or_none('0'), 0.0)
        self.assertIsNone(safe_float_or_none(None))
        self.assertIsNone(safe_float_or_none('MAX'))


class SelectTestColumnsTests(SimpleTestCase):
    def test_excludes_system_and_non_numeric_columns(self):
        """defect #7：系统列（Serial_No 等）恒排除，非数值测试项也排除。"""
        ds = _dataset('f1.csv', [1.0, 2.0, 3.0], extra={
            'Serial_No': ['1', '2', '3'],
            'Note': ['aa', 'bb', 'cc'],
        })
        self.assertEqual(select_test_columns([ds]), [PARAM])

    def test_ignore_no_limit_drops_items_without_numeric_limits(self):
        without_limits = _dataset('f1.csv', [1.0, 2.0, 3.0])
        self.assertEqual(select_test_columns([without_limits], True), [])

        with_limits = _dataset('f1.csv', [1.0, 2.0, 3.0], low='0', high='10')
        self.assertEqual(select_test_columns([with_limits], True), [PARAM])

        keyword_limits = _dataset('f1.csv', [1.0, 2.0, 3.0], low='0', high='MAX')
        self.assertEqual(select_test_columns([keyword_limits], True), [])


class AnalyzeTestItemTests(SimpleTestCase):
    def test_two_identical_files_are_repeatibility_only(self):
        """两份同值文件：组内均值无差异 ⇒ Reproducibility=0，R&R% 由 Repeatability 决定。"""
        files = [
            _dataset('f1.csv', [1.0, 2.0, 3.0], low='0', high='10'),
            _dataset('f2.csv', [1.0, 2.0, 3.0], low='0', high='10'),
        ]
        item = analyze_test_item(PARAM, files, num_files=2)

        self.assertAlmostEqual(item.global_mean, MEAN_A, places=6)
        # 两份 [1,2,3] 合并后的总体 σ 与单份相同（同分布拼接不改变离散度）
        self.assertAlmostEqual(item.global_std, STD_123, places=6)
        self.assertAlmostEqual(item.repeatability,
                               6 * math.sqrt((STD_123 ** 2 * 2) / 2), places=6)
        self.assertAlmostEqual(item.reproducibility, 0.0, places=9)
        self.assertAlmostEqual(item.r_r_pct,
                               item.repeatability / 10.0, places=6)
        self.assertEqual(item.fail_level, 'Bad1')
        self.assertTrue(item.is_bad_group)

    def test_shifted_means_add_reproducibility(self):
        """两份文件均值差 2 ⇒ Reproducibility = 6 × σ(文件均值) = 6.0。"""
        files = [
            _dataset('f1.csv', [1.0, 2.0, 3.0], low='0', high='10'),
            _dataset('f2.csv', [3.0, 4.0, 5.0], low='0', high='10'),
        ]
        item = analyze_test_item(PARAM, files, num_files=2)

        self.assertAlmostEqual(item.reproducibility, 6.0, places=6)
        self.assertEqual(item.tol_idx, 0, '公差取第一个有效且非退化的文件（f1）')
        self.assertEqual(item.fail_level, 'Bad1')

    def test_wide_tolerance_downgrades_to_bad2(self):
        """同一组数据把公差放宽到 20 ⇒ R&R% 落到 Bad2 档，但不算 Bad1。"""
        files = [
            _dataset('f1.csv', [1.0, 2.0, 3.0], low='0', high='20'),
            _dataset('f2.csv', [1.0, 2.0, 3.0], low='0', high='20'),
        ]
        item = analyze_test_item(PARAM, files, num_files=2)

        self.assertLess(item.r_r_pct, RR_PCT_BAD1)
        self.assertGreaterEqual(item.r_r_pct, RR_PCT_BAD2)
        self.assertEqual(item.fail_level, 'Bad2')
        self.assertFalse(item.is_bad_group)

    def test_missing_limits_make_rr_pct_na(self):
        """defect #5：没有可用公差时 R&R% 与 Fail Level 一起 N/A，且不计入 Bad1。"""
        files = [_dataset('f1.csv', [1.0, 2.0, 3.0])]
        item = analyze_test_item(PARAM, files, num_files=1)

        self.assertIsNone(item.r_r_pct)
        self.assertEqual(item.fail_level, 'N/A')
        self.assertFalse(item.is_bad_group)
        self.assertEqual(item.tolerance, 0.0)
        self.assertIsNone(item.tol_idx)

    def test_empty_file_does_not_pollute_group_stats(self):
        """defect #1：全空的第二份文件不贡献数据，也不把均值/σ 拉成 0。"""
        files = [
            _dataset('f1.csv', [1.0, 2.0, 3.0], low='0', high='10'),
            _dataset('f2.csv', [None, None, None], low='0', high='10'),
        ]
        item = analyze_test_item(PARAM, files, num_files=2)

        self.assertFalse(item.per_file[1]['has_data'])
        self.assertAlmostEqual(item.global_mean, MEAN_A, places=6)
        self.assertAlmostEqual(item.global_std, STD_123, places=6)
        # 分母仍是文件总数（旧口径），不是「有数据的文件数」
        self.assertAlmostEqual(item.repeatability,
                               6 * math.sqrt((STD_123 ** 2) / 2), places=6)
        self.assertAlmostEqual(item.reproducibility, 0.0, places=9)

    def test_zero_lower_limit_is_honoured(self):
        """defect #3：LSL=0 是真限值，CPK 不该被当成缺失而归零。"""
        files = [_dataset('f1.csv', [1.0, 2.0, 3.0], low='0', high='4')]
        item = analyze_test_item(PARAM, files, num_files=1)

        self.assertAlmostEqual(item.per_file[0]['cpk'], CPK_0_10, places=6)
        self.assertAlmostEqual(item.min_cpk, CPK_0_10, places=6)
        self.assertAlmostEqual(item.max_cpk, CPK_0_10, places=6)

    def test_min_max_cpk_span_files_not_overall(self):
        """defect #4：Min/Max CPK 是逐文件 CPK 的两端，不是 overall_cpk。"""
        files = [
            _dataset('f1.csv', [1.0, 2.0, 3.0], low='0', high='10'),
            _dataset('f2.csv', [3.0, 4.0, 5.0], low='0', high='10'),
        ]
        item = analyze_test_item(PARAM, files, num_files=2)
        per_file_cpks = [e['cpk'] for e in item.per_file]

        self.assertAlmostEqual(item.min_cpk, min(per_file_cpks), places=9)
        self.assertAlmostEqual(item.max_cpk, max(per_file_cpks), places=9)
        self.assertNotAlmostEqual(item.max_cpk, item.overall_cpk, places=3)
