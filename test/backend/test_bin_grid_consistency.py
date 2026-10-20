"""Single-file histogram and multi-lot chart must share the same bin grid.

Both endpoints build 25 inner edges / 24 normal bins / underflow+overflow.
If either side changes the count, range or rounding, the two charts silently
disagree — this test pins them together for every range_type.
"""
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.binning import build_bin_grid
from apps.analysis.services.data_services.histogram import compute_histogram_stats
from apps.analysis.services.data_services.multi_lot import (
    compute_multi_lot_distribution,
)

PARAM = 'P'
VALUES = [
    10.4480, 10.4495, 10.4510, 10.4519, 10.4530, 10.4545, 10.4553,
    10.4460, 10.4580, 10.4600, 10.4420, 10.4620, 10.4380, 10.4660,
    10.4700, 10.4300, 10.4740, 10.4260, 10.4780, 10.4200,
]
METADATA = {
    'mins': {PARAM: '8.0'},
    'maxs': {PARAM: '14.3'},
    'units': {PARAM: 'uA'},
    'format': 'CTA8290D',
}


class BinGridConsistencyTests(SimpleTestCase):
    def setUp(self):
        self.df = pd.DataFrame({PARAM: VALUES})
        self.series = self.df[PARAM]

    def _histogram(self, range_type):
        return compute_histogram_stats(
            self.df, METADATA, PARAM, None, range_type=range_type)

    def _multi_lot(self, range_type, **kwargs):
        datasets = {
            1: {
                'series': self.series,
                'metadata': METADATA,
                'df': self.df,
                'file_id': 1,
                'name': 'file-1',
            },
        }
        return compute_multi_lot_distribution(
            datasets, [self.series], PARAM, range_type=range_type, **kwargs)

    def test_single_and_multi_share_bin_centers(self):
        for range_type in ('RDL', 'DR', 'S3', 'S4', 'S6'):
            with self.subTest(range_type=range_type):
                histogram = self._histogram(range_type)
                multi_lot = self._multi_lot(range_type)
                self.assertEqual(
                    histogram['bin_centers'], multi_lot['bin_centers'],
                    f'{range_type}: 单文件与多文件分箱中心不一致',
                )
                self.assertEqual(len(multi_lot['bin_centers']), 26)

    def test_custom_limits_share_bin_centers(self):
        histogram = compute_histogram_stats(
            self.df, METADATA, PARAM, None,
            range_type='CL', custom_low=10.40, custom_high=10.50)
        multi_lot = self._multi_lot(
            'CL', custom_low=10.40, custom_high=10.50)
        self.assertEqual(histogram['bin_centers'], multi_lot['bin_centers'])

    def test_multi_lot_bar_data_uses_the_same_center_array(self):
        multi_lot = self._multi_lot('S4')
        bars = multi_lot['lot_data'][0]['bar_data']
        self.assertEqual([bar[0] for bar in bars], multi_lot['bin_centers'])

    def test_round_centers_flag_matches_serialised_rounding(self):
        _, raw_centers, _ = build_bin_grid(0.0, 3.0)
        _, rounded_centers, _ = build_bin_grid(0.0, 3.0, round_centers=True)
        self.assertEqual(rounded_centers, [round(c, 6) for c in raw_centers])
        self.assertEqual(len(raw_centers), 26)
