"""文件相关性服务层与序列接口的回归测试。
（自 2473 行的 tests.py 按主题拆出，用例逐字搬迁。）
"""
import pandas as pd
import types
from django.test import SimpleTestCase
from django.test import TestCase


class FileCorrelationServiceTests(SimpleTestCase):
    """compute_file_correlation 纯计算单测（无 mock，直接调服务）。"""

    @staticmethod
    def _frames():
        df1 = pd.DataFrame({
            'Serial_No': [1, 2, 3],
            'ParamA': [1.0, 2.0, 3.0],
            'ParamB': [10.0, 20.0, 30.0],
        })
        df2 = pd.DataFrame({
            'Serial_No': [1, 2, 3],
            'ParamA': [1.1, 2.1, 3.1],
            'ParamB': [10.0, 21.0, 29.0],
        })
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        meta = {'mins': {'ParamA': '0.5', 'ParamB': '-'},
                'maxs': {'ParamA': '2.0', 'ParamB': '40'},
                'units': {'ParamA': 'V', 'ParamB': 'nA'}}
        return df1, df2, meta

    def test_vectorized_matches_hand_computation(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, meta = self._frames()
        r = compute_file_correlation(df1, meta, df2, meta, FileCorrelationConfig())
        self.assertEqual(r['serials'], [1, 2, 3])
        self.assertFalse(r['limits_only'])
        self.assertFalse(r['truncated'])
        # 参数按文件A列顺序（序列列不参与）
        self.assertEqual(r['params'], ['ParamA', 'ParamB'])

        by_param = {row['param']: row for row in r['rows']}
        pa = by_param['ParamA']
        # 有符号 Δ/ATE：10% / 5% / 3.33%
        self.assertEqual([c['delta'] for c in pa['cells']], [0.1, 0.1, 0.1])
        self.assertEqual([round(c['diff_pct'], 2) for c in pa['cells']],
                         [10.0, 5.0, 3.33])
        self.assertEqual([c['fail'] for c in pa['cells']], [True, True, True])
        self.assertEqual(pa['compared'], 3)
        self.assertEqual(pa['fail_count'], 3)
        self.assertEqual(pa['max_diff'], 10.0)

        pb = by_param['ParamB']
        self.assertEqual([round(c['diff_pct'], 2) for c in pb['cells']],
                         [0.0, 5.0, -3.33])
        self.assertEqual([c['fail'] for c in pb['cells']], [False, True, True])
        self.assertEqual(pb['pass_rate'], 33.33)

        # totals 汇总
        self.assertEqual(r['totals']['paired_cells'], 6)
        self.assertEqual(r['totals']['fail_cells'], 5)
        self.assertEqual(r['totals']['overall_pass_rate'], 16.67)

    def test_serial_cap_takes_first_n_ascending(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1 = pd.DataFrame({'Serial_No': [5, 3, 1, 4, 2], 'ParamA': [1.0] * 5})
        df2 = pd.DataFrame({'Serial_No': [1, 2, 3, 4, 5], 'ParamA': [1.0] * 5})
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        meta = {'mins': {'ParamA': '0'}, 'maxs': {'ParamA': '5'}, 'units': {}}
        r = compute_file_correlation(df1, meta, df2, meta,
                                     FileCorrelationConfig(max_serials=2))
        self.assertTrue(r['truncated'])
        self.assertEqual(r['serials'], [1, 2])
        self.assertEqual(len(r['rows'][0]['cells']), 2)

    def test_limit_parsing_sentinels(self):
        from apps.analysis.services.file_correlation import _parse_limit

        for raw in ('·', '-', '—', '', '  ', 'n/a', 'N/A', 'min', 'max', None):
            self.assertIsNone(_parse_limit(raw), raw)
        self.assertEqual(_parse_limit('0.5'), 0.5)
        self.assertEqual(_parse_limit('"1.2"'), 1.2)
        self.assertEqual(_parse_limit('abc'), None)

    def test_ignore_no_limit_filters_params_without_limits(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, meta = self._frames()
        # 加入两侧都无 limit 的 ParamC（'-'/'-'）→ 默认被 ignore_no_limit 过滤
        df1['ParamC'] = [0.1, 0.2, 0.3]
        df2['ParamC'] = [0.1, 0.2, 0.3]
        meta['mins']['ParamC'] = '-'
        meta['maxs']['ParamC'] = '-'
        r = compute_file_correlation(df1, meta, df2, meta, FileCorrelationConfig())
        self.assertEqual(r['params'], ['ParamA', 'ParamB'])
        # 关闭后 ParamC 参与（数据相同 → 无超差）
        r2 = compute_file_correlation(df1, meta, df2, meta,
                                      FileCorrelationConfig(ignore_no_limit=False))
        self.assertEqual(r2['params'], ['ParamA', 'ParamB', 'ParamC'])

    def test_missing_limit_on_one_side_fails_both_rules(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, _ = self._frames()
        meta_a = {'mins': {'ParamA': '0.5'}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        meta_b = {'mins': {}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        for rule in ('zero', 'wider'):
            r = compute_file_correlation(df1, meta_a, df2, meta_b,
                                         FileCorrelationConfig(diff_rule=rule,
                                                              ignore_no_limit=False))
            row = r['rows'][0]
            self.assertTrue(row['lsl_fail'], rule)
            self.assertFalse(row['usl_fail'], rule)
            self.assertIsNone(row['lsl_diff'], rule)

    def test_diff_rule_zero_and_wider(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, _ = self._frames()
        meta_a = {'mins': {'ParamA': '0.5'}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        # B 更宽（0.4/2.5）
        meta_wide = {'mins': {'ParamA': '0.4'}, 'maxs': {'ParamA': '2.5'}, 'units': {}}
        # B 更紧（0.6/1.9）
        meta_tight = {'mins': {'ParamA': '0.6'}, 'maxs': {'ParamA': '1.9'}, 'units': {}}

        r_zero = compute_file_correlation(df1, meta_a, df2, meta_wide,
                                          FileCorrelationConfig(diff_rule='zero'))
        self.assertEqual(r_zero['rows'][0]['lsl_diff'], -0.1)
        self.assertTrue(r_zero['rows'][0]['lsl_fail'])   # diff ≠ 0 → fail
        self.assertTrue(r_zero['rows'][0]['usl_fail'])   # 0.5 ≠ 0 → fail

        r_wider = compute_file_correlation(df1, meta_a, df2, meta_wide,
                                           FileCorrelationConfig(diff_rule='wider'))
        self.assertFalse(r_wider['rows'][0]['lsl_fail'])  # B 更宽 → pass
        self.assertFalse(r_wider['rows'][0]['usl_fail'])

        r_tight = compute_file_correlation(df1, meta_a, df2, meta_tight,
                                           FileCorrelationConfig(diff_rule='wider'))
        self.assertTrue(r_tight['rows'][0]['lsl_fail'])
        self.assertTrue(r_tight['rows'][0]['usl_fail'])

    def test_zero_ate_pair_is_uncomputable(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1 = pd.DataFrame({'Serial_No': [1, 2], 'ParamA': [0.0, 2.0]})
        df2 = pd.DataFrame({'Serial_No': [1, 2], 'ParamA': [1.0, 2.05]})
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        meta = {'mins': {'ParamA': '0'}, 'maxs': {'ParamA': '5'}, 'units': {}}
        r = compute_file_correlation(df1, meta, df2, meta, FileCorrelationConfig())
        cells = r['rows'][0]['cells']
        # ATE=0 的对无法计算 %Diff → 不计入对比、不 fail
        self.assertIsNone(cells[0]['diff_pct'])
        self.assertFalse(cells[0]['fail'])
        self.assertEqual(r['rows'][0]['compared'], 1)

    def test_limits_only_mode_when_no_common_serials(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1 = pd.DataFrame({'Serial_No': [1, 2], 'ParamA': [1.0, 2.0]})
        df2 = pd.DataFrame({'Serial_No': [99], 'ParamA': [5.0]})
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        meta = {'mins': {'ParamA': '0.5'}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        r = compute_file_correlation(df1, meta, df2, meta, FileCorrelationConfig())
        self.assertTrue(r['limits_only'])
        self.assertEqual(r['serials'], [])
        self.assertEqual(r['rows'][0]['cells'], [])
        self.assertEqual(r['rows'][0]['compared'], 0)
        # limit 列仍完整可对比
        self.assertEqual(r['rows'][0]['lsl_a'], 0.5)
        self.assertFalse(r['rows'][0]['lsl_fail'])

    def test_no_common_params_raises(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig, NoCommonParamsError)

        df1 = pd.DataFrame({'Serial_No': [1, 2], 'ParamA': [1.0, 2.0]})
        df2 = pd.DataFrame({'Serial_No': [1, 2], 'Other': [1.0, 2.0]})
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        with self.assertRaises(NoCommonParamsError):
            compute_file_correlation(df1, {}, df2, {}, FileCorrelationConfig())

    def test_duplicate_serial_rows_take_first_occurrence(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1 = pd.DataFrame({'Serial_No': [1, 1, 2], 'ParamA': [1.0, 99.0, 3.0]})
        df2 = pd.DataFrame({'Serial_No': [1, 2], 'ParamA': [1.05, 3.0]})
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        meta = {'mins': {'ParamA': '0'}, 'maxs': {'ParamA': '5'}, 'units': {}}
        r = compute_file_correlation(df1, meta, df2, meta, FileCorrelationConfig())
        # 序列 1 在文件A 出现两次 → 取 first（1.0），diff_pct = 5%
        self.assertEqual(r['rows'][0]['cells'][0]['ate'], 1.0)
        self.assertAlmostEqual(r['rows'][0]['cells'][0]['diff_pct'], 5.0)

    def test_explicit_serials_selected_in_request_order(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1 = pd.DataFrame({'Serial_No': [5, 3, 1, 4, 2], 'ParamA': [1.0] * 5})
        df2 = pd.DataFrame({'Serial_No': [1, 2, 3, 4, 5], 'ParamA': [1.0] * 5})
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        meta = {'mins': {'ParamA': '0'}, 'maxs': {'ParamA': '5'}, 'units': {}}
        r = compute_file_correlation(df1, meta, df2, meta,
                                     FileCorrelationConfig(serials=[3, 1]))
        # 显式选择：保持请求顺序；无「截断」语义
        self.assertEqual(r['serials'], [3, 1])
        self.assertFalse(r['truncated'])
        self.assertEqual(r['totals']['serials'], 2)
        self.assertEqual([c['serial'] for c in r['rows'][0]['cells']], [3, 1])

    def test_explicit_serials_filters_invalid_and_dedups(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1 = pd.DataFrame({'Serial_No': [1, 2], 'ParamA': [1.0, 2.0]})
        df2 = pd.DataFrame({'Serial_No': [1, 2], 'ParamA': [1.0, 2.0]})
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        meta = {'mins': {'ParamA': '0'}, 'maxs': {'ParamA': '5'}, 'units': {}}
        r = compute_file_correlation(df1, meta, df2, meta,
                                     FileCorrelationConfig(serials=[2, 99, 2, 1]))
        self.assertEqual(r['serials'], [2, 1])

    def test_explicit_serials_empty_limits_only(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, meta = self._frames()
        r = compute_file_correlation(df1, meta, df2, meta,
                                     FileCorrelationConfig(serials=[]))
        self.assertTrue(r['limits_only'])
        self.assertEqual(r['serials'], [])
        self.assertFalse(r['truncated'])
        self.assertEqual(r['rows'][0]['cells'], [])
        # limit 列仍完整可对比
        self.assertEqual(r['rows'][0]['lsl_a'], 0.5)

    def test_explicit_serials_overrides_max_serial_fallback(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, meta = self._frames()
        r = compute_file_correlation(df1, meta, df2, meta,
                                     FileCorrelationConfig(serials=[1, 2, 3],
                                                           max_serials=1))
        self.assertEqual(r['serials'], [1, 2, 3])
        self.assertFalse(r['truncated'])
        self.assertEqual(r['totals']['serials'], 3)

    def test_list_common_serials_ascending(self):
        from apps.analysis.services.file_correlation import list_common_serials

        df1 = pd.DataFrame({'Serial_No': [3, 1, 2], 'ParamA': [1.0, 1.0, 1.0]})
        df2 = pd.DataFrame({'Serial_No': [2, 1, 99], 'ParamA': [1.0, 1.0, 1.0]})
        for d in (df1, df2):
            d['__serial__'] = pd.to_numeric(d['Serial_No'], errors='coerce')
        self.assertEqual(list_common_serials(df1, df2), [1, 2])


class FileCorrelationSerialsApiTests(TestCase):
    """file_correlation_serials 端点：公共序列列表（序列勾选器数据源）。"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user(
            username='fc_serials_test', password='x')

    def _call(self, frames, body=None):
        from rest_framework.test import APIClient
        # 必须 patch 实际消费模块（R6③）：三端点已迁到 file_correlation_views
        from apps.analysis.views import file_correlation_views as fc_views

        orig_404 = fc_views.get_object_or_404
        orig_load = fc_views.get_cached_parsed_file
        orig_serial = fc_views.get_serial_column

        fc_views.get_object_or_404 = (
            lambda model, *a, **k: types.SimpleNamespace(
                id=k['pk'], filename=f'FILE{k["pk"]}.csv',
                format_type='CTA8290D'))
        fc_views.get_cached_parsed_file = (
            lambda fid, owner_id, datafile=None: (
                frames[int(fid)], {'format': 'CTA8290D'}, 'CTA8290D'))
        fc_views.get_serial_column = lambda df: 'Serial_No'
        self.addCleanup(lambda: setattr(fc_views, 'get_object_or_404', orig_404))
        self.addCleanup(lambda: setattr(fc_views, 'get_cached_parsed_file', orig_load))
        self.addCleanup(lambda: setattr(fc_views, 'get_serial_column', orig_serial))

        client = APIClient()
        client.force_authenticate(user=self.user)
        return client.post('/api/v1/analysis/file_correlation_serials/', {
            'file1_id': 1, 'file2_id': 2, **(body or {}),
        }, format='json')

    def test_returns_ascending_common_serials(self):
        df1 = pd.DataFrame({'Serial_No': [3, 1, 2], 'ParamA': [1.0, 1.0, 1.0]})
        df2 = pd.DataFrame({'Serial_No': [2, 1, 99], 'ParamA': [1.0, 1.0, 1.0]})
        resp = self._call({1: df1, 2: df2})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data, {'serials': [1, 2], 'total': 2})

    def test_no_common_serials_empty_list(self):
        df1 = pd.DataFrame({'Serial_No': [1, 2], 'ParamA': [1.0, 2.0]})
        df2 = pd.DataFrame({'Serial_No': [99], 'ParamA': [5.0]})
        resp = self._call({1: df1, 2: df2})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data, {'serials': [], 'total': 0})

    def test_missing_ids_returns_400(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user)
        resp = client.post('/api/v1/analysis/file_correlation_serials/', {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'need_two_files')
