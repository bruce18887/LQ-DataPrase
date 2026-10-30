"""Regression guard: bin-trend yield and SPC control limits.

``compute_bin_trend`` compared bin keys against the *strings* ``'Bin1'``/``'1'``,
but ``calculate_fail_bin_statistics`` returns the raw pandas ``value_counts``
keys -- and on real CTA8290D data ``SW_Bin`` is ``int64``, so the keys are
Python ``int``. ``1 == '1'`` is False, ``pass_count`` never left 0 and
``yield_trend`` was a flat line of zeros, while ``compute_yield_trend`` (which
goes through ``compute_pass_yield``/``is_pass_bin``) reported the correct yield
for the very same file. Two yield endpoints contradicting each other.

Also pinned here: the SPC limits clamp both ends (yield is a percentage, so
``ucl`` must not exceed 100 -- the old code only clamped ``lcl >= 0``) and use
the project's 6-decimal precision instead of 2.

Two endpoints, **two input shapes** (2026-10-30 审查 Important 1 定稿)：
``compute_bin_trend`` 吃 ``df``+``metadata``（它本来就要逐帧扫 bin），
``compute_yield_trend`` **只**吃调用方算好的 ``bin_stats``+``total``（见
``YieldTrendPrecomputedInputTests``）。所以下面凡是调 ``compute_yield_trend`` 的
用例都先过 ``_precomputed`` 这一道换算 —— 那不是修辞，是把「只有一种入参形状」
这件事落在调用点上。
"""
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.statistics import calculate_fail_bin_statistics
from apps.analysis.services.statistics.trends import (
    compute_bin_trend,
    compute_yield_trend,
)

META = {'format': 'CTA8290D'}


def _file(pass_count, fail_count, bin_pass=1, bin_fail=7, file_id=1):
    """One synthetic file whose SW_Bin column has the requested pass/fail split."""
    df = pd.DataFrame({
        'SW_Bin': pd.Series([bin_pass] * pass_count + [bin_fail] * fail_count),
    })
    return {'df': df, 'metadata': dict(META), 'file_id': file_id,
            'filename': f'f{file_id}.csv', 'timestamp': ''}


def _precomputed(file_data):
    """把一份 ``df`` 形状夹具换成 ``compute_yield_trend`` 认的那份入参。

    这就是生产里唯一真实存在的那条通路：``apps/batch_report/services.py`` 在同一次遍历里
    已经跑过 ``calculate_fail_bin_statistics``，把 ``bin_stats`` 与 ``total = df.shape[0]``
    一起带下来。``total`` 取 ``shape[0]`` 而不是 bin 计数之和，正是「bin 列缺失 ⇒
    ``bin_stats`` 为空但行数不是 0」那格还要靠它的原因（见
    ``test_missing_bin_column_still_reports_the_caller_total``）。
    """
    return {
        'bin_stats': calculate_fail_bin_statistics(
            file_data['df'], file_data.get('metadata', {})),
        'total': file_data['df'].shape[0],
        'file_id': file_data['file_id'],
        'filename': file_data['filename'],
        'timestamp': file_data['timestamp'],
    }


class BinTrendYieldTests(SimpleTestCase):
    def test_int64_bin_keys_yield_is_not_zero(self):
        """The actual bug: int64 SW_Bin made every yield 0.0."""
        result = compute_bin_trend([_file(77, 23)])
        self.assertEqual(result['yield_trend'], [77.0])

    def test_agrees_with_compute_yield_trend(self):
        """The two yield endpoints must not contradict each other."""
        files = [_file(77, 23, file_id=1), _file(90, 10, file_id=2)]
        bin_trend = compute_bin_trend(files)
        yield_trend = compute_yield_trend([_precomputed(f) for f in files])
        from_bin = bin_trend['yield_trend']
        from_yield = [row['yield'] for row in yield_trend['trend_data']]
        self.assertEqual(from_bin, from_yield)
        self.assertEqual(from_bin, [77.0, 90.0])

    def test_text_bin_keys_still_recognised(self):
        """``'Bin1'``/``'Bin 1'`` variants must keep working (is_pass_bin)."""
        result = compute_bin_trend([_file(80, 20, bin_pass='Bin1', bin_fail='Bin7')])
        self.assertEqual(result['yield_trend'], [80.0])

    def test_float_bin_keys_recognised(self):
        result = compute_bin_trend([_file(60, 40, bin_pass=1.0, bin_fail=7.0)])
        self.assertEqual(result['yield_trend'], [60.0])

    def test_bins_sorted_pass_first_then_numeric(self):
        """Old key ``(x != 'Bin1' and x != '1', x)`` never ordered int keys."""
        df = pd.DataFrame({'SW_Bin': pd.Series([22, 7, 1, 25, 7, 1, 1])})
        result = compute_bin_trend(
            [{'df': df, 'metadata': dict(META), 'file_id': 1,
              'filename': 'f.csv', 'timestamp': ''}])
        self.assertEqual(result['bins'][0], 1)
        self.assertEqual(sorted(result['bins'][1:]), result['bins'][1:])

    def test_mixed_int_and_str_bin_keys_do_not_raise(self):
        """``sorted`` on mixed int/str raises TypeError -- must not."""
        files = [
            _file(70, 30, bin_pass=1, bin_fail=7, file_id=1),
            _file(80, 20, bin_pass='Bin1', bin_fail='Bin7', file_id=2),
        ]
        result = compute_bin_trend(files)
        self.assertEqual(result['yield_trend'], [70.0, 80.0])

    def test_all_fail_file_yields_zero(self):
        result = compute_bin_trend([_file(0, 50)])
        self.assertEqual(result['yield_trend'], [0.0])


class YieldSpcLimitTests(SimpleTestCase):
    def test_ucl_clamped_to_100(self):
        """mean=99.5, std=0.5 -> raw ucl=101.0 must clamp to 100.0."""
        files = [_file(100, 0, file_id=1), _file(99, 1, file_id=2)]
        limits = compute_yield_trend([_precomputed(f) for f in files])['spc_limits']
        self.assertEqual(limits['ucl'], 100.0)
        self.assertLessEqual(limits['ucl'], 100.0)

    def test_lcl_clamped_to_zero(self):
        """mean=1.5, std=0.5 -> raw lcl=0.0; a wider spread must floor at 0."""
        files = [_file(2, 0, file_id=1), _file(1, 99, file_id=2)]
        limits = compute_yield_trend([_precomputed(f) for f in files])['spc_limits']
        self.assertGreaterEqual(limits['lcl'], 0.0)

    def test_precision_is_six_decimals_not_two(self):
        """33.333333% and 71.428571% -> cl must keep 6 decimals (was 52.38)."""
        files = [_file(1, 2, file_id=1), _file(5, 2, file_id=2)]
        limits = compute_yield_trend([_precomputed(f) for f in files])['spc_limits']
        self.assertEqual(limits['cl'], 52.380952)

    def test_single_file_has_degenerate_limits(self):
        limits = compute_yield_trend([_precomputed(_file(77, 23))])['spc_limits']
        self.assertEqual(limits['ucl'], limits['cl'])
        self.assertEqual(limits['cl'], limits['lcl'])
        self.assertEqual(limits['cl'], 77.0)

    def test_no_files_gives_none_limits(self):
        limits = compute_yield_trend([])['spc_limits']
        self.assertIsNone(limits['ucl'])
        self.assertIsNone(limits['cl'])
        self.assertIsNone(limits['lcl'])


class YieldTrendPrecomputedInputTests(SimpleTestCase):
    """``compute_yield_trend`` 的**唯一**入参形状：调用方算好的 ``bin_stats``/``total``。

    批次报告（``apps/batch_report/services.py``，它是本函数唯一的生产调用方）在同一次
    遍历里已经跑过 ``calculate_fail_bin_statistics``，把那份结果直接带下来 ⇒
    ``compute_yield_trend`` 既不必再跑第二趟，也没有理由再拿到 ``df``。

    2026-10-30 审查 Important 1 撤掉了先前的 ``df`` 兼容层：那条 fallback 当时由
    「``_load_files_from_request`` 产出的就是 ``df``+``metadata`` 形状」这句话背书，但那份
    形状只喂 ``compute_bin_trend`` / ``compute_param_trend``，一个都到不了这里 ⇒
    垫片零生产调用方，按本仓规则（能直接改代码就别留兼容层）删除。
    先前为「两种方言互相同意」写的平价用例（同一批文件分别带 ``df`` 与带 ``bin_stats``，
    断两份输出逐值相同）随垫片一起删：它钉的不是契约，是垫片自己。
    """

    def test_precomputed_input_needs_no_dataframe(self):
        """省账的**全部意义**在这：入参里没有 ``df`` 也必须算得出来（不抛 KeyError）。"""
        entry = _precomputed(_file(60, 40, file_id=9))
        self.assertNotIn('df', entry)
        out = compute_yield_trend([entry])
        self.assertEqual([row['yield'] for row in out['trend_data']], [60.0])
        self.assertEqual(out['trend_data'][0]['total_count'], 100)

    def test_missing_bin_column_still_reports_the_caller_total(self):
        """``bin_stats`` 空（文件没有 bin 列）时 ``total_count`` 取调用方带的 ``total``。

        这不是「为了喂旧形状而保留的分支」，是生产里真会出现的一格，调用链在这儿：
        ``compute_batch_yield_data`` 给趋势输入的是
        ``total = df.shape[0]``（服务循环里那一行）与
        ``bin_stats = calculate_fail_bin_statistics(df, metadata)``，而后者在
        ``get_bin_column_name(format_type) not in df.columns`` 时**整块返回 ``{}``**
        （``apps/analysis/services/statistics/limits.py`` 的那条早退）。
        ⇒ 一个有行、无 bin 列的批次文件，``bin_stats`` 是空的但 ``total`` 不是 0：
        少了这条回落，趋势会把它报成 0 颗而不是真实行数。
        """
        out = compute_yield_trend([
            {'bin_stats': {}, 'total': 5, 'file_id': 1,
             'filename': 'nb.csv', 'timestamp': ''}])
        self.assertEqual(out['trend_data'][0]['total_count'], 5)
        self.assertEqual(out['trend_data'][0]['fail_count'], 5)

    def test_frame_shape_is_rejected_there_is_no_second_dialect(self):
        """反垫片判据：只认 ``bin_stats``/``total``，``df``+``metadata`` 与缺 ``total`` 都要炸。

        把 ``_bin_stats_and_total`` 的 ``df`` 分支加回去 ⇒ 第一格不再抛 ``KeyError`` ⇒
        本条转红（这正是「兼容层不许悄悄回来」的哨兵）。
        """
        frame = pd.DataFrame({'SW_Bin': pd.Series([1, 1, 7])})
        shapes = {
            'df 形状（已删除的方言）': {
                'df': frame, 'metadata': dict(META), 'file_id': 1,
                'filename': 'f.csv', 'timestamp': ''},
            '缺 total 的 bin_stats 形状': {
                'bin_stats': {1: {'count': 2, 'percentage': 66.666667}},
                'file_id': 1, 'filename': 'f.csv', 'timestamp': ''},
        }
        for label, entry in shapes.items():
            with self.subTest(shape=label):
                with self.assertRaises(KeyError):
                    compute_yield_trend([entry])
