"""Unit tests for batch_report batch-level aggregation helpers.

Covers the pure functions in ``apps.batch_report.aggregation`` that roll per-phase
structures up to batch level for the batch report (Bin x Site cross table + UPH),
matching the single-file analysis output shapes consumed by the frontend.
"""
from django.test import TestCase

from apps.batch_report.aggregation import (
    aggregate_bin_site_table,
    aggregate_uph,
)


def _phase_with_bins(bin_info):
    return {'phase': 'CP1', 'bin_info': bin_info}


class AggregateBinSiteTableTests(TestCase):
    def setUp(self):
        # 2 phases, 2 sites (A, B), 2 bins (pass '1', fail '2').
        # Phase 1: Bin1 -> A:10 B:20 ; Bin2 -> A:1 B:3
        # Phase 2: Bin1 -> A:5  B:7  ; Bin2 -> A:2 B:0
        self.phases = [
            _phase_with_bins([
                {'name': '1', 'sites': {'A': 10, 'B': 20}},
                {'name': '2', 'sites': {'A': 1, 'B': 3}},
            ]),
            _phase_with_bins([
                {'name': '1', 'sites': {'A': 5, 'B': 7}},
                {'name': '2', 'sites': {'A': 2, 'B': 0}},
            ]),
        ]
        self.sorted_sites = ['A', 'B']

    def test_columns_match_sorted_sites(self):
        _, cols = aggregate_bin_site_table(self.phases, self.sorted_sites)
        self.assertEqual(cols, ['A', 'B'])

    def test_per_cell_sums_and_row_totals(self):
        rows, _ = aggregate_bin_site_table(self.phases, self.sorted_sites)
        by_bin = {r['bin']: r for r in rows}

        # Bin 1 (pass): A = 10+5 = 15, B = 20+7 = 27, all_site = 42
        self.assertEqual(by_bin['Bin 1']['A'], 15)
        self.assertEqual(by_bin['Bin 1']['B'], 27)
        self.assertEqual(by_bin['Bin 1']['all_site'], 42)

        # Bin 2 (fail): A = 1+2 = 3, B = 3+0 = 3, all_site = 6
        self.assertEqual(by_bin['Bin 2']['A'], 3)
        self.assertEqual(by_bin['Bin 2']['B'], 3)
        self.assertEqual(by_bin['Bin 2']['all_site'], 6)

    def test_total_row(self):
        rows, _ = aggregate_bin_site_table(self.phases, self.sorted_sites)
        total = next(r for r in rows if r['bin'] == 'Total')
        # A column total = 15 + 3 = 18, B = 27 + 3 = 30, grand = 48
        self.assertEqual(total['A'], 18)
        self.assertEqual(total['B'], 30)
        self.assertEqual(total['all_site'], 48)

    def test_output_shape_matches_single_file(self):
        """Keys must match compute_bin_site_table so BinSiteCrossTable.vue renders.

        Single-file rows: {'bin': 'Bin N'|'Total', <site>: int, ..., 'all_site': int}.
        """
        rows, cols = aggregate_bin_site_table(self.phases, self.sorted_sites)
        # Total row is last; pass bin (Bin 1) is first.
        self.assertEqual(rows[0]['bin'], 'Bin 1')
        self.assertEqual(rows[-1]['bin'], 'Total')
        for r in rows:
            self.assertIn('bin', r)
            self.assertIn('all_site', r)
            for c in cols:
                self.assertIn(c, r)
                self.assertIsInstance(r[c], int)

    def test_empty_when_no_sites(self):
        rows, cols = aggregate_bin_site_table(self.phases, [])
        self.assertEqual(rows, [])
        self.assertEqual(cols, [])

    def test_empty_when_no_bin_info(self):
        rows, cols = aggregate_bin_site_table([{'phase': 'CP1', 'bin_info': []}], ['A'])
        self.assertEqual(rows, [])
        self.assertEqual(cols, [])


class AggregateUphTests(TestCase):
    def _phase_uph(self, total_tested, total_time_seconds, avg_test_time,
                   by_site=None, source='col', warnings=None):
        return {'uph': {
            'total_tested': total_tested,
            'total_time_seconds': total_time_seconds,
            'avg_test_time': avg_test_time,
            'by_site': by_site or [],
            'source': source,
            'site_count': len(by_site or []),
            'warnings': warnings or [],
        }}

    def test_totals_and_uph(self):
        # Phase 1: 100 units, 50s wall-clock (avg 1.0s serial, 2 sites)
        # Phase 2: 200 units, 200s wall-clock (avg 2.0s serial, 2 sites)
        phases = [
            self._phase_uph(100, 50.0, 1.0,
                            by_site=[{'site': '1', 'tested': 50, 'uph': 3600.0},
                                     {'site': '2', 'tested': 50, 'uph': 3600.0}]),
            self._phase_uph(200, 200.0, 2.0,
                            by_site=[{'site': '1', 'tested': 100, 'uph': 1800.0},
                                     {'site': '2', 'tested': 100, 'uph': 1800.0}]),
        ]
        agg = aggregate_uph(phases)

        self.assertEqual(agg['total_tested'], 300)
        self.assertAlmostEqual(agg['total_time_seconds'], 250.0, places=1)
        # uph = 300 / 250 * 3600 = 4320
        self.assertAlmostEqual(agg['uph'], 4320.0, places=1)
        # avg_test_time = (1.0*100 + 2.0*200) / 300 = 500/300 = 1.667
        self.assertAlmostEqual(agg['avg_test_time'], 1.667, places=3)
        self.assertEqual(agg['source'], 'batch')

    def test_by_site_aggregation(self):
        phases = [
            self._phase_uph(100, 50.0, 1.0,
                            by_site=[{'site': '1', 'tested': 50, 'uph': 3600.0},
                                     {'site': '2', 'tested': 50, 'uph': 3600.0}]),
            self._phase_uph(200, 200.0, 2.0,
                            by_site=[{'site': '1', 'tested': 100, 'uph': 1800.0},
                                     {'site': '2', 'tested': 100, 'uph': 1800.0}]),
        ]
        agg = aggregate_uph(phases)
        by_site = {s['site']: s for s in agg['by_site']}

        # Site 1: tested = 50 + 100 = 150.
        # serial = 50*3600/3600 + 100*3600/1800 = 50 + 200 = 250s
        # uph = 3600 * 150 / 250 = 2160
        self.assertEqual(by_site['1']['tested'], 150)
        self.assertAlmostEqual(by_site['1']['uph'], 2160.0, places=1)
        self.assertEqual(by_site['2']['tested'], 150)
        self.assertAlmostEqual(by_site['2']['uph'], 2160.0, places=1)
        self.assertEqual(agg['site_count'], 2)

    def test_partial_data_warning(self):
        phases = [
            self._phase_uph(100, 50.0, 1.0,
                            by_site=[{'site': '1', 'tested': 100, 'uph': 3600.0}]),
            # Phase missing UPH (e.g. no test time column)
            {'uph': {'total_tested': 0, 'total_time_seconds': 0.0,
                     'avg_test_time': 0.0, 'by_site': [], 'source': 'unavailable',
                     'site_count': 0, 'warnings': ['未找到测试时间列，无法计算 UPH']}},
        ]
        agg = aggregate_uph(phases)
        self.assertEqual(agg['total_tested'], 100)
        # Partial warning present
        self.assertTrue(any('部分汇总' in w for w in agg['warnings']))
        # Per-phase warning merged
        self.assertTrue(any('未找到测试时间列' in w for w in agg['warnings']))

    def test_all_missing_returns_zero(self):
        phases = [
            {'uph': {'total_tested': 0, 'total_time_seconds': 0.0,
                     'avg_test_time': 0.0, 'by_site': [], 'source': 'unavailable',
                     'site_count': 0, 'warnings': []}},
        ]
        agg = aggregate_uph(phases)
        self.assertEqual(agg['total_tested'], 0)
        self.assertEqual(agg['uph'], 0.0)
        self.assertEqual(agg['by_site'], [])
        self.assertEqual(agg['source'], 'batch')

    def test_output_shape(self):
        phases = [
            self._phase_uph(100, 50.0, 1.0,
                            by_site=[{'site': '1', 'tested': 100, 'uph': 3600.0}]),
        ]
        agg = aggregate_uph(phases)
        for key in ('uph', 'avg_test_time', 'total_tested', 'total_time_seconds',
                    'source', 'by_site', 'site_count', 'warnings'):
            self.assertIn(key, agg)
        for s in agg['by_site']:
            self.assertEqual(set(s.keys()), {'site', 'tested', 'uph'})
