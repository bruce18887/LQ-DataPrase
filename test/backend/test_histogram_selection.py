"""T1：histogram 选区（子集直方图）解析与行级过滤 + 视图接线契约。

判据分层（testing-gates §2）：守卫全组合/过滤正确性/CPK 口径都在这一档；
浏览器只留接线证明（e2e/analysis/subset-drilldown.spec.ts）。
用 SimpleTestCase：manage.py test 只收集 unittest.TestCase。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

import pandas as pd  # noqa: E402
from django.test import SimpleTestCase  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

from apps.analysis import test_support  # noqa: E402
from apps.analysis.services.data_services.subset_selection import (  # noqa: E402
    parse_selection, filter_df_by_selection,
)
from apps.analysis.test_support import fake_datafile  # noqa: E402
from apps.analysis.views import AnalysisViewSet  # noqa: E402

PARAM = 'P1'


def _frame():
    return pd.DataFrame({
        'Serial_No': [1, 2, 3, 4, 5, 6],
        'Site_No': ['1', '1', '1', '2', '2', '2'],
        'P1': [1.0, 2.0, 3.0, 10.0, 11.0, 12.0],
    })


def _md():
    return {'format': 'CTA8290D', 'units': {PARAM: 'V'},
            'mins': {PARAM: '0'}, 'maxs': {PARAM: '5'}}


def _fake_user():
    return types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False, settings=None,
    )


class ParseSelectionTests(SimpleTestCase):
    def test_none_means_no_selection(self):
        sel, err = parse_selection(None)
        self.assertIsNone(sel)
        self.assertIsNone(err)

    def test_value_range_finite(self):
        sel, err = parse_selection({'kind': 'value_range', 'lo': 1.0, 'hi': 2.0})
        self.assertIsNone(err)
        self.assertEqual(sel, {'kind': 'value_range', 'lo': 1.0, 'hi': 2.0})

    def test_value_range_null_hi_is_unbounded(self):
        sel, err = parse_selection({'kind': 'value_range', 'lo': 9.0, 'hi': None})
        self.assertIsNone(err)
        self.assertIsNone(sel['hi'])

    def test_value_range_both_null_rejected(self):
        _, err = parse_selection({'kind': 'value_range', 'lo': None, 'hi': None})
        self.assertEqual(err.status_code, 400)
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_value_range_lo_gt_hi_rejected(self):
        _, err = parse_selection({'kind': 'value_range', 'lo': 3.0, 'hi': 1.0})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_value_range_nan_rejected(self):
        _, err = parse_selection({'kind': 'value_range', 'lo': float('nan'), 'hi': 1.0})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_value_range_bool_rejected(self):
        _, err = parse_selection({'kind': 'value_range', 'lo': True, 'hi': 1.0})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_ok(self):
        sel, err = parse_selection({'kind': 'serials', 'serials': [1, 2], 'serial_col': 'Serial_No'})
        self.assertIsNone(err)
        self.assertEqual(sel['serials'], [1, 2])
        self.assertEqual(sel['serial_col'], 'Serial_No')

    def test_serials_empty_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': []})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_not_list_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': '1,2'})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_bool_element_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [True]})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_nan_element_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [float('nan')]})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_over_cap_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': list(range(100001))})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serial_col_non_string_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [1], 'serial_col': 5})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_unknown_kind_rejected(self):
        _, err = parse_selection({'kind': 'magic'})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_non_dict_rejected(self):
        _, err = parse_selection([1, 2])
        self.assertEqual(err.data['code'], 'invalid_selection')


class FilterDfTests(SimpleTestCase):
    def test_value_range_filters_rows(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'value_range', 'lo': 9.0, 'hi': 11.5})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [10.0, 11.0])

    def test_value_range_unbounded_hi(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'value_range', 'lo': 9.0, 'hi': None})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [10.0, 11.0, 12.0])

    def test_value_range_coerces_string_column(self):
        df = _frame()
        df[PARAM] = df[PARAM].astype(str)
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'value_range', 'lo': 9.0, 'hi': None})
        self.assertIsNone(err)
        self.assertEqual(len(out), 3)

    def test_serials_numeric_column(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'serials', 'serials': [2, 4, 6]})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [2.0, 10.0, 12.0])

    def test_serials_string_column(self):
        df = _frame()
        df['Serial_No'] = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6']
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'serials', 'serials': ['S2', 'S5']})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [2.0, 11.0])

    def test_serials_numeric_wanted_string_column_coerces(self):
        df = _frame()
        df['Serial_No'] = df['Serial_No'].astype(str)
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'serials', 'serials': [3]})
        self.assertIsNone(err)
        self.assertEqual(out[PARAM].tolist(), [3.0])

    def test_serial_col_override(self):
        df = _frame()
        df['Dut_No'] = [101, 102, 103, 104, 105, 106]
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'serials', 'serials': [104], 'serial_col': 'Dut_No'})
        self.assertIsNone(err)
        self.assertEqual(out[PARAM].tolist(), [10.0])

    def test_invalid_serial_col_rejected(self):
        _, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'serials', 'serials': [1], 'serial_col': 'NOPE'})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_no_serial_column_rejected(self):
        df = _frame().drop(columns=['Serial_No'])
        _, err = filter_df_by_selection(df, PARAM, {'kind': 'serials', 'serials': [1]})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_unmatched_serials_ignored(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'serials', 'serials': [2, 999]})
        self.assertIsNone(err)
        self.assertEqual(out[PARAM].tolist(), [2.0])

    def test_empty_subset_rejected(self):
        _, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'value_range', 'lo': 100.0, 'hi': 200.0})
        self.assertEqual(err.data['code'], 'empty_selection')