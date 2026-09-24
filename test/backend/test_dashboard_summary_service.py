"""`compute_dashboard_summary` 特征化测试：锁定 payload key 集合与关键数值。

服务从 views.py 抽出（供 /summary/ API 与 HTML 报告共用），本测试防止组装体
在搬移/复用过程中漂移。

runner: ``manage.py test test.backend.test_dashboard_summary_service``
"""

from types import SimpleNamespace
from django.test import SimpleTestCase

from apps.dashboard.services import compute_dashboard_summary

EXPECTED_KEYS = {
    'file_id', 'filename', 'program_name', 'metrics', 'bin_pie_data',
    'site_yield_data', 'fail_test_items', 'quality_overview',
    'bin_table_data', 'bin_site_columns', 'param_stats',
    'test_item_overview', 'quality_alerts',
}


def _df():
    import pandas as pd
    return pd.DataFrame({
        'P1': [1.0, 2.0, 3.0, 4.0],
        'P2': [10.0, 11.0, 12.0, 12.0],
        'P3': [100.0, 200.0, 300.0, 400.0],
        'P4': ['ok', 'ng', 'ok', 'ng'],
        'Site': ['S1', 'S1', 'S2', 'S2'],
        'SW_Bin': [1, 2, 1, 1],
    })


def _meta():
    return {
        'format': 'CTA8290D',
        'units': {'P1': 'V'},
        'mins': {'P1': '0.5', 'P2': '9.0'},
        'maxs': {'P1': '5.0', 'P2': '13.0'},
    }


def _datafile():
    return SimpleNamespace(id=7, filename='demo.csv', program_name='PROG')


class ComputeDashboardSummaryTests(SimpleTestCase):
    def test_payload_key_set_locked(self):
        out = compute_dashboard_summary(_df(), _datafile(), 'CTA8290D', _meta())
        self.assertEqual(set(out.keys()), EXPECTED_KEYS)

    def test_metrics_values(self):
        out = compute_dashboard_summary(_df(), _datafile(), 'CTA8290D', _meta())
        m = out['metrics']
        self.assertEqual(m['total_rows'], 4)
        self.assertEqual(m['pass_count'], 3)
        self.assertEqual(m['fail_count'], 1)
        self.assertEqual(m['yield_pct'], 75.0)
        self.assertEqual(m['format'], 'CTA8290D')

    def test_identity_fields(self):
        out = compute_dashboard_summary(_df(), _datafile(), 'CTA8290D', _meta())
        self.assertEqual(out['file_id'], 7)
        self.assertEqual(out['filename'], 'demo.csv')
        self.assertEqual(out['program_name'], 'PROG')

    def test_quality_overview_keys(self):
        out = compute_dashboard_summary(_df(), _datafile(), 'CTA8290D', _meta())
        self.assertEqual(
            set(out['quality_overview'].keys()),
            {'numeric_items', 'items_with_limits', 'site_count',
             'bin_types', 'fail_bin_count'},
        )
