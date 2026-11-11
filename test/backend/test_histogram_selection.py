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

    def test_serials_inf_element_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [float('inf')]})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_over_cap_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': list(range(100001))})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serial_col_non_string_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [1], 'serial_col': 5})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serial_col_empty_string_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [1], 'serial_col': ''})
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

    def test_value_range_drops_dirty_rows(self):
        df = pd.DataFrame({'Serial_No': [1, 2, 3, 4], 'P1': ['1.0', 'abc', None, '10.0']})
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'value_range', 'lo': 0.0, 'hi': None})
        self.assertIsNone(err)
        self.assertEqual(len(out), 2)
        self.assertEqual(sorted(pd.to_numeric(out[PARAM]).tolist()), [1.0, 10.0])

    def test_value_range_unbounded_lo(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'value_range', 'lo': None, 'hi': 2.5})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [1.0, 2.0])

    def test_value_range_lo_equals_hi_inclusive(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'value_range', 'lo': 2.0, 'hi': 2.0})
        self.assertIsNone(err)
        self.assertEqual(out[PARAM].tolist(), [2.0])

    def test_all_unmatched_serials_empty_selection(self):
        _, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'serials', 'serials': [999, 1000]})
        self.assertEqual(err.data['code'], 'empty_selection')

    def test_serials_numeric_column_string_wanted_coerces(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'serials', 'serials': ['4']})
        self.assertIsNone(err)
        self.assertEqual(out[PARAM].tolist(), [10.0])


class HistogramViewSelectionTests(SimpleTestCase):
    def _post(self, payload, df=None, metadata=None):
        df = df if df is not None else _frame()
        metadata = metadata if metadata is not None else _md()
        restore = test_support.patch_df_loader(df, fake_datafile(), metadata)
        try:
            request = APIRequestFactory().post(
                '/api/v1/analysis/histogram/', dict(payload), format='json')
            force_authenticate(request, user=_fake_user())
            response = AnalysisViewSet.as_view({'post': 'histogram'})(request)
            response.render()
            return response
        finally:
            restore()

    def _base(self, **extra):
        return dict({'file_id': 1, 'params': [PARAM]}, **extra)

    def test_value_range_subset_count_and_limits(self):
        r = self._post(self._base(selection={'kind': 'value_range', 'lo': 9.0, 'hi': None}))
        self.assertEqual(r.status_code, 200, r.content)
        res = r.data['results'][PARAM]
        self.assertEqual(res['total_count'], 3)
        # 规格限仍是原参数（D1/D2）：CPK 锚 RDL，不随子集变
        self.assertEqual(res['lower_limit'], 0.0)
        self.assertEqual(res['upper_limit'], 5.0)
        # 子集 mean=11 → CPK 为负（USL=5 远小于 mean）
        self.assertLess(res['cpk'], 0)

    def test_selection_forces_dr_binning(self):
        # 客户端故意传 RDL：后端必须强制 DR，子集 {10,11,12} 的 bin 跨度 hugs 自身值域
        r = self._post(self._base(range_type='RDL',
                                  selection={'kind': 'value_range', 'lo': 9.0, 'hi': None}))
        self.assertEqual(r.status_code, 200, r.content)
        centers = r.data['results'][PARAM]['bin_centers']
        self.assertGreater(centers[0], 5.0)   # 不跨原规格限 [0,5]
        self.assertLess(centers[-1], 15.0)

    def test_serials_subset(self):
        r = self._post(self._base(selection={'kind': 'serials', 'serials': [2, 4, 6]}))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['results'][PARAM]['total_count'], 3)

    def test_empty_selection_400(self):
        r = self._post(self._base(selection={'kind': 'value_range', 'lo': 100.0, 'hi': 200.0}))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'empty_selection')

    def test_selection_requires_single_param(self):
        r = self._post(self._base(params=[PARAM, 'Site_No'],
                                  selection={'kind': 'value_range', 'lo': 0.0, 'hi': 5.0}))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'invalid_selection')

    def test_invalid_kind_400(self):
        r = self._post(self._base(selection={'kind': 'magic'}))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'invalid_selection')

    def test_fast_path_ignores_selection(self):
        r = self._post(self._base(params=[], selection={'kind': 'magic'}))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn(PARAM, r.data['results'])

    def test_bin1_context_applies_before_selection(self):
        df = _frame()
        df['SW_Bin'] = ['1', '1', '1', '5', '5', '5']
        md = _md()
        md['units']['SW_Bin'] = ''
        md['mins']['SW_Bin'] = ''
        md['maxs']['SW_Bin'] = ''
        # Bin1 只剩 {1,2,3}；选区 lo=9 在 Bin1 行里无匹配 → empty_selection
        r = self._post(self._base(data_only_bin1=True,
                                  selection={'kind': 'value_range', 'lo': 9.0, 'hi': None}),
                       df=df, metadata=md)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'empty_selection')

    def test_no_selection_keeps_old_behavior(self):
        r = self._post(self._base())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['results'][PARAM]['total_count'], 6)
