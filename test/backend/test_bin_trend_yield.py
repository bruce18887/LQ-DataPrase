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
"""
import pandas as pd
from django.test import SimpleTestCase

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


class BinTrendYieldTests(SimpleTestCase):
    def test_int64_bin_keys_yield_is_not_zero(self):
        """The actual bug: int64 SW_Bin made every yield 0.0."""
        result = compute_bin_trend([_file(77, 23)])
        self.assertEqual(result['yield_trend'], [77.0])

    def test_agrees_with_compute_yield_trend(self):
        """The two yield endpoints must not contradict each other."""
        files = [_file(77, 23, file_id=1), _file(90, 10, file_id=2)]
        bin_trend = compute_bin_trend(files)
        yield_trend = compute_yield_trend(files)
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
        limits = compute_yield_trend(files)['spc_limits']
        self.assertEqual(limits['ucl'], 100.0)
        self.assertLessEqual(limits['ucl'], 100.0)

    def test_lcl_clamped_to_zero(self):
        """mean=1.5, std=0.5 -> raw lcl=0.0; a wider spread must floor at 0."""
        files = [_file(2, 0, file_id=1), _file(1, 99, file_id=2)]
        limits = compute_yield_trend(files)['spc_limits']
        self.assertGreaterEqual(limits['lcl'], 0.0)

    def test_precision_is_six_decimals_not_two(self):
        """33.333333% and 71.428571% -> cl must keep 6 decimals (was 52.38)."""
        files = [_file(1, 2, file_id=1), _file(5, 2, file_id=2)]
        limits = compute_yield_trend(files)['spc_limits']
        self.assertEqual(limits['cl'], 52.380952)

    def test_single_file_has_degenerate_limits(self):
        limits = compute_yield_trend([_file(77, 23)])['spc_limits']
        self.assertEqual(limits['ucl'], limits['cl'])
        self.assertEqual(limits['cl'], limits['lcl'])
        self.assertEqual(limits['cl'], 77.0)

    def test_no_files_gives_none_limits(self):
        limits = compute_yield_trend([])['spc_limits']
        self.assertIsNone(limits['ucl'])
        self.assertIsNone(limits['cl'])
        self.assertIsNone(limits['lcl'])
