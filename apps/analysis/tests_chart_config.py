"""图表配置开关（忽略无Limit/仅Pass/仅Fail/低CPK 等）的直方图与相关性矩阵
API 回归测试。MultiFileCorrelationFilterApiTests 复用本文件
ChartConfigFilterTests 的帧 fixture，故与之同模块。
（自 2473 行的 tests.py 按主题拆出，用例逐字搬迁。）
"""
import numpy as np
import pandas as pd
import types
from django.test import SimpleTestCase
from apps.analysis.tests_param_guards import StaleParamAcrossFileSwitchTests


class ChartConfigFilterTests(SimpleTestCase):
    """Chart-config switches on the analysis endpoints.

    Locks down the four new switches — ignore_no_test_value /
    data_only_bin1 / only_fail_test_item / only_low_cpk — on the
    histogram fast path (param list), the histogram compute path,
    site_stats and serial_distribution. Reuses the fake
    ``_load_df_from_request`` harness from StaleParamAcrossFileSwitchTests
    (no DB); the fake user has no ``settings`` attribute, which also pins
    the ``get_cpk_b_threshold`` fallback path.
    """

    METADATA = {
        'format': 'CTA8290D',
        'mins': {'Param0': '8.0', 'Param1': '0.5', 'FailOnly': '8.0',
                 'ParamBin1Empty': '8.0', 'ParamLowCpk': '8.0',
                 'ParamHighCpk': '8.0', 'ParamMidCpk': '8.0',
                 'ParamOutlierLow': '8.0'},
        'maxs': {'Param0': '14.3', 'Param1': '3.5', 'FailOnly': '14.3',
                 'ParamBin1Empty': '14.3', 'ParamLowCpk': '14.3',
                 'ParamHighCpk': '14.3', 'ParamMidCpk': '14.3',
                 'ParamOutlierLow': '14.3'},
        'units': {'Param0': 'V', 'Param1': 'uA', 'FailOnly': 'V',
                  'ParamBin1Empty': 'V', 'ParamLowCpk': 'V',
                  'ParamHighCpk': 'V', 'ParamMidCpk': 'V',
                  'ParamOutlierLow': 'V'},
    }

    def _frame(self):
        """10 rows: pass-bin rows are 0,2,3,4,6,7,8,9; fail rows 1,5."""
        return pd.DataFrame({
            'serial': list(range(101, 111)),
            'SW_Bin': [1, 2, 1, 1, 1, 2, 1, 1, 1, 1],
            'Site': [1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            'Param0': [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0],
            'Param1': [1.9, 2.0, 2.05, 1.95, 2.1, 1.98, 2.02, 1.96, 2.04, 2.0],
            # fail rows (1,5) exceed USL 14.3 → the only fail test item
            'FailOnly': [10.1, 15.0, 10.3, 10.4, 10.5, 15.0, 10.7, 10.8, 10.9, 11.0],
            'ParamAllNan': [np.nan] * 10,
            # values exist only on fail rows → empty inside Bin1
            'ParamBin1Empty': [np.nan, 10.1, np.nan, np.nan, np.nan,
                               10.2, np.nan, np.nan, np.nan, np.nan],
            # cpk ≈ 0.9 → low
            'ParamLowCpk': [8.5, 8.6, 8.7, 8.8, 8.9, 8.4, 8.6, 8.8, 9.0, 9.2],
            # cpk ≫ 1.33 → not low
            'ParamHighCpk': [10.9, 11.0, 11.05, 11.0, 11.02, 11.03, 10.98, 11.01, 10.99, 11.0],
            # cpk ≈ 1.43 → between 1.33 and 2.0, used for the settings test
            'ParamMidCpk': [8.6, 8.66, 8.72, 8.78, 8.84, 8.96, 9.02, 9.08, 9.14, 9.2],
            # 行 0（bin1）有 14.4 超 usl 14.3 的异常值：全量 CPK 低、filtered CPK 健康
            'ParamOutlierLow': [14.4, 11.0, 11.05, 11.0, 11.02,
                                11.0, 10.98, 11.01, 10.99, 11.0],
            'ParamNoLimit': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        })

    def _post(self, payload, user=None):
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(self._frame(), metadata=self.METADATA)
        self.addCleanup(restore)
        if user is None:
            user = types.SimpleNamespace(
                pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
                is_staff=False, is_superuser=False,
            )
        request = factory.post('/api/v1/analysis/histogram/', payload, format='json')
        force_authenticate(request, user=user)
        return request

    # ── fast path (param list) ──────────────────────────────────────

    def test_fast_path_default_list_keeps_sparse_but_skips_empty(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = set(resp.data['results'].keys())
        self.assertIn('ParamBin1Empty', keys)   # has values on fail rows
        self.assertNotIn('ParamAllNan', keys)   # fully empty, always excluded

    def test_fast_path_data_only_bin1_and_ignore_no_test_value(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'data_only_bin1': True,
                              'ignore_no_test_value': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = set(resp.data['results'].keys())
        self.assertNotIn('ParamBin1Empty', keys)  # empty inside Bin1 → hidden
        self.assertIn('Param0', keys)

    def test_fast_path_only_fail_test_item(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'only_fail_test_item': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(resp.data['results'].keys()), {'FailOnly'})

    def test_fast_path_only_low_cpk_default_threshold(self):
        """Fake user has no settings row → fallback 1.33, no crash."""
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'only_low_cpk': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(resp.data['results'].keys()), {'ParamLowCpk'})
        self.assertNotIn('ParamMidCpk', resp.data['results'])  # 1.43 > 1.33
        # FailOnly 含超限异常值（15.0）→ filtered CPK 健康 → 不列入（显示口径）

    def test_fast_path_only_low_cpk_uses_filtered_cpk(self):
        """低 CPK 判定无条件跟随 CPK 卡显示口径：异常值拉低的参数不列入。

        Regression: 用户反馈「3.1897 (filtered)」这种剔除异常值后 CPK 健康
        的参数也被列入了低 CPK 列表。前端 CPK 卡总是优先显示 filtered_cpk
        （与异常值处理开关无关），因此默认（无 outlier_handling 参数）时
        也不能把 ParamOutlierLow（含 14.4 异常值、filtered 健康）列入。
        """
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'only_low_cpk': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertNotIn('ParamOutlierLow', resp.data['results'])
        self.assertIn('ParamLowCpk', resp.data['results'])

    def test_fast_path_only_low_cpk_reads_user_setting(self):
        user = types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False,
            settings=types.SimpleNamespace(cpk_b_threshold=2.0),
        )
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'only_low_cpk': True}, user=user)
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('ParamMidCpk', resp.data['results'])  # 1.43 < 2.0

    # ── compute path ────────────────────────────────────────────────

    def test_compute_path_data_only_bin1_total_count(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'params': ['Param0'],
                              'data_only_bin1': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['results']['Param0']['total_count'], 8)

    def test_compute_path_only_fail_test_item_drops_non_fail(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'params': ['FailOnly', 'Param1'],
                              'only_fail_test_item': True})
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(resp.data['results'].keys()), {'FailOnly'})

    # ── site_stats / serial_distribution ────────────────────────────

    def test_site_stats_data_only_bin1_drops_bin2_site(self):
        from apps.analysis.views import statistics_views, StatisticsViewSet
        df = pd.DataFrame({
            'serial': list(range(101, 111)),
            'SW_Bin': [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
            'Site': [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
            'Param0': [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0],
        })
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(df, metadata=self.METADATA)
        self.addCleanup(restore)

        request = factory.post('/api/v1/statistics/site_stats/', {
            'file_id': 1, 'param': 'Param0', 'data_only_bin1': True,
        }, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        resp = StatisticsViewSet.as_view({'post': 'site_stats'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        site_names = [s['Site'] for s in resp.data['site_data']]
        self.assertEqual(site_names, ['Site1', 'ALL Site'])  # Site2 gone

    def test_site_stats_display_format(self):
        """site_stats 展示格式：Yield=百分比3位小数(总数)、Fail/<Min/>Max=数量(百分比3位)。

        回归：用户指定格式（2026-08-13）——Yield 改为 `100.000%(5865)`，
        Fail/<Min/>Max 改为 `3(0.181%)`；数字字段 FailCountNum/TotalNum 保留供
        前端行样式等逻辑使用。
        """
        from apps.analysis.views import StatisticsViewSet
        df = pd.DataFrame({
            'serial': list(range(101, 111)),
            'SW_Bin': [1] * 10,
            'Site': [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
            'Param0': [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0],
        })
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(df, metadata=self.METADATA)
        self.addCleanup(restore)
        request = factory.post('/api/v1/statistics/site_stats/', {
            'file_id': 1, 'param': 'Param0',
        }, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        resp = StatisticsViewSet.as_view({'post': 'site_stats'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        import re
        for row in resp.data['site_data']:
            self.assertRegex(row['Yield'], r'^\d+\.\d{3}%\(\d+\)$', row)
            self.assertRegex(row['FailCount'], r'^\d+\(\d+\.\d{3}%\)$', row)
            self.assertRegex(row['ExceedMin'], r'^\d+\(\d+\.\d{3}%\)$', row)
            self.assertRegex(row['ExceedMax'], r'^\d+\(\d+\.\d{3}%\)$', row)
            self.assertIsInstance(row['FailCountNum'], int)
            self.assertIsInstance(row['TotalNum'], int)
        # Param0 范围 [8.0, 14.3]：10 行全部在限内 → yield 100.000%(10)
        self.assertEqual(resp.data['site_data'][0]['Yield'], '100.000%(5)')

    def test_serial_distribution_data_only_bin1(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'Param0',
                              'data_only_bin1': True})
        resp = AnalysisViewSet.as_view({'post': 'serial_distribution'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        total = sum(len(s['data']) for s in resp.data['series_data'])
        self.assertEqual(total, 8)  # 10 rows − 2 fail rows

    def test_serial_distribution_full_frame_keeps_all_points(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'Param0'})
        resp = AnalysisViewSet.as_view({'post': 'serial_distribution'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        total = sum(len(s['data']) for s in resp.data['series_data'])
        self.assertEqual(total, 10)

    # ── qqplot / boxplot row filter ─────────────────────────────────

    def test_qqplot_data_only_bin1(self):
        """data_only_bin1 narrows the QQ plot to pass-bin rows (n = 8)."""
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'Param0',
                              'data_only_bin1': True})
        resp = AnalysisViewSet.as_view({'post': 'qqplot'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['n'], 8)  # 10 rows − 2 fail rows

    def test_qqplot_full_frame_keeps_all_points(self):
        """Without the switch the QQ plot still covers the whole frame."""
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'Param0'})
        resp = AnalysisViewSet.as_view({'post': 'qqplot'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['n'], 10)

    def test_qqplot_returns_fit_params(self):
        """QQ plot response carries the probplot fit line parameters:
        intercept≈data mean, slope≈data std (the front end draws the
        reference line as y = intercept + slope·x instead of y=x, which
        only fits zero-mean/unit-variance data)."""
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'Param0'})
        resp = AnalysisViewSet.as_view({'post': 'qqplot'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        slope, intercept = resp.data['slope'], resp.data['intercept']
        self.assertIsNotNone(slope)
        self.assertIsNotNone(intercept)
        # Param0 = 10.1..11.0 → mean ≈ 10.5, std ≈ 0.3
        self.assertLess(abs(intercept - 10.5), 1)
        self.assertLess(abs(slope - 0.3), 0.3)

    def test_qqplot_constant_data_horizontal_fit_line(self):
        """Constant data yields the horizontal fit line slope=0 /
        intercept=const (the front end draws y = intercept + slope·x,
        which degenerates to y = const — all points sit on it)."""
        from apps.analysis.services.statistics.computations import compute_qqplot
        result = compute_qqplot(pd.Series([5.0, 5.0, 5.0]))
        self.assertEqual(result['slope'], 0.0)
        self.assertEqual(result['intercept'], 5.0)
        self.assertFalse(result['is_normal'])
        # Short data path carries the fields (None — no fit computed)
        short = compute_qqplot(pd.Series([1.0, 2.0]))
        self.assertIsNone(short['slope'])
        self.assertIsNone(short['intercept'])

    def test_qqplot_data_only_bin1_empty_in_bin1_400(self):
        """Param all-NaN inside Bin1 → existing param_no_valid_data 400,
        never a 500 (filtering must happen before series extraction)."""
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'ParamBin1Empty',
                              'data_only_bin1': True})
        resp = AnalysisViewSet.as_view({'post': 'qqplot'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data.get('error'), 'param_no_valid_data')

    def test_boxplot_data_only_bin1_overall_count(self):
        """data_only_bin1 narrows the box plot overall stats (count = 8)."""
        from apps.analysis.views import StatisticsViewSet
        request = self._post({'file_id': 1, 'params': ['Param0'],
                              'data_only_bin1': True})
        resp = StatisticsViewSet.as_view({'post': 'boxplot'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['results']['Param0']['overall']['count'], 8)

    def test_boxplot_data_only_bin1_by_bin_only_bin1(self):
        """Grouped by bin, the filtered frame leaves only pass bin "1"
        (fail rows are removed before grouping — consistent with the
        histogram Bin1 mode)."""
        from apps.analysis.views import StatisticsViewSet
        request = self._post({'file_id': 1, 'params': ['Param0'],
                              'data_only_bin1': True, 'group_by': 'bin'})
        resp = StatisticsViewSet.as_view({'post': 'boxplot'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        by_bin = resp.data['results']['Param0']['by_bin']
        self.assertEqual(set(by_bin.keys()), {'1'})
        self.assertEqual(by_bin['1']['count'], 8)


class MultiFileCorrelationFilterApiTests(SimpleTestCase):
    """数据筛选开关（忽略无Limit/无测试值/仅Pass/仅Fail/低CPK）在
    multi_lot / correlation / correlation_matrix 端点的口径（2026-08-20）。

    与 histogram 同口径的关键不变量：fail 集合必须基于全量 df 预计算
    （bin1 过滤前）——fail 行永远不是 Bin1，先过滤再算 fail 集会清空
    fail 集合。fixture 复用 ChartConfigFilterTests 的帧结构
    （SW_Bin 行 1/5 为 fail；FailOnly 是唯一 fail 测试项）。
    """

    METADATA = ChartConfigFilterTests.METADATA

    def _frame(self):
        return ChartConfigFilterTests._frame(self)

    @staticmethod
    def _fake_objects(by_id):
        """DataFile 查询桩：filter(pk=...) → first() 返回对应 fake 对象。"""
        class _FakeQS:
            def __init__(self, obj):
                self._obj = obj
            def first(self):
                return self._obj

        class _FakeManager:
            def filter(self, **kw):
                return _FakeQS(by_id.get(kw.get('pk')))

        return _FakeManager()

    def _multi_lot(self, payload, frames):
        """打桩 multi_lot 的 DataFile 查询与文件加载，在 patch 作用域内调用视图。

        注意：patch 必须覆盖「构建请求 → 视图执行」全程，不能在请求构建完
        就退出（视图内会再查 DataFile.objects）。
        """
        import types
        from unittest.mock import patch
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis.views import analysis_views, AnalysisViewSet

        objs = {}
        for fid in frames:
            objs[fid] = types.SimpleNamespace(
                id=fid, filename=f'f{fid}.csv', format_type='CTA8290D',
                file_path='/tmp/__nonexistent__',  # os.stat 失败 → 缓存 key 无 mtime 守卫
            )

        def fake_load(fid, user_id, obj=None):
            df, meta = frames[fid]
            return df, meta, 'CTA8290D'

        with patch.object(analysis_views.DataFile, 'objects', self._fake_objects(objs)), \
             patch.object(analysis_views, 'get_cached_parsed_file', fake_load):
            factory = APIRequestFactory()
            request = factory.post('/api/v1/analysis/multi_lot/', payload, format='json')
            force_authenticate(request, user=types.SimpleNamespace(
                pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
                is_staff=False, is_superuser=False,
            ))
            resp = AnalysisViewSet.as_view({'post': 'multi_lot'})(request)
            resp.render()
            return resp

    def _correlation_request(self, payload, df=None):
        """打桩 correlation/correlation_matrix 的 _load_df_from_request。"""
        import types
        from rest_framework.test import APIRequestFactory, force_authenticate
        factory, force_auth, restore = StaleParamAcrossFileSwitchTests._patched_view(
            df if df is not None else self._frame(), metadata=self.METADATA)
        self.addCleanup(restore)
        request = factory.post('/api/v1/analysis/correlation/', payload, format='json')
        force_auth(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False,
        ))
        return request

    # ── multi_lot ───────────────────────────────────────────────────

    def test_multi_lot_data_only_bin1_reduces_distribution_count(self):
        """data_only_bin1：首个公共参数分布的 lot count 从 10 收缩到 8。"""
        f1 = self._frame()
        f2 = self._frame()
        resp = self._multi_lot(
            {'file_ids': [1, 2], 'data_only_bin1': True},
            {1: (f1, self.METADATA), 2: (f2, self.METADATA)})
        self.assertEqual(resp.status_code, 200, resp.content)
        lots = {lot['file_id']: lot for lot in resp.data['lot_data']}
        self.assertEqual(lots[1]['count'], 8, 'bin1 过滤后应只剩 8 行')
        self.assertEqual(lots[2]['count'], 8)

    def test_multi_lot_only_fail_test_item_keeps_fail_items_from_full_df(self):
        """仅显示Fail测试项：common_params 只含 FailOnly。

        回归不变量：fail 集合基于全量 df 预计算（bin1 过滤前）——FailOnly 的
        fail 行（1/5）不是 Bin1，若先过滤行再算 fail 集则 fail 恒空 →
        common_params 空（旧实现路径必失败）。
        """
        f1 = self._frame()
        f2 = self._frame()
        resp = self._multi_lot(
            {'file_ids': [1, 2], 'only_fail_test_item': True},
            {1: (f1, self.METADATA), 2: (f2, self.METADATA)})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['common_params'], ['FailOnly'])

    def test_multi_lot_only_fail_test_item_with_bin1_keeps_fail_items(self):
        """仅Fail + 仅Pass 同时开：fail 集仍来自全量 df（组合开关不互相破坏）。"""
        f1 = self._frame()
        f2 = self._frame()
        resp = self._multi_lot(
            {'file_ids': [1, 2], 'only_fail_test_item': True, 'data_only_bin1': True},
            {1: (f1, self.METADATA), 2: (f2, self.METADATA)})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['common_params'], ['FailOnly'])

    def test_multi_lot_ignore_no_test_value_filters_sparse_params(self):
        """忽略无测试值 + 仅Pass：ParamBin1Empty（值只在 fail 行）从 common 中移除。

        单独开 ignore_no_test_value 时 ParamBin1Empty 有 20% 有效值（2/10）
        ≥ 5% 阈值会被保留——与单文件口径一致；组合 data_only_bin1 后
        bin1 行内全空 → 剔除。
        """
        f1 = self._frame()
        f2 = self._frame()
        resp = self._multi_lot(
            {'file_ids': [1, 2], 'ignore_no_test_value': True,
             'data_only_bin1': True},
            {1: (f1, self.METADATA), 2: (f2, self.METADATA)})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertNotIn('ParamBin1Empty', resp.data['common_params'])
        self.assertIn('Param0', resp.data['common_params'])

    # ── correlation ─────────────────────────────────────────────────

    def test_correlation_data_only_bin1_changes_n(self):
        """correlation：bin1 过滤行后 n 从 10 → 8。"""
        from apps.analysis.views import AnalysisViewSet
        request = self._correlation_request(
            {'file_id': 1, 'param_x': 'Param0', 'param_y': 'Param1',
             'data_only_bin1': True})
        resp = AnalysisViewSet.as_view({'post': 'correlation'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['n'], 8)

    def test_correlation_only_fail_test_item_400_when_param_filtered(self):
        """correlation + 仅Fail：param_x=Param0（非 fail 项）→ 400 no_valid_params。"""
        from apps.analysis.views import AnalysisViewSet
        request = self._correlation_request(
            {'file_id': 1, 'param_x': 'Param0', 'param_y': 'FailOnly',
             'only_fail_test_item': True})
        resp = AnalysisViewSet.as_view({'post': 'correlation'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data.get('error'), 'no_valid_params')

    # ── correlation_matrix ──────────────────────────────────────────

    def test_correlation_matrix_data_only_bin1_ok(self):
        """correlation_matrix：bin1 过滤行后正常 200（参数列表仍 ≥2）。"""
        from apps.analysis.views import StatisticsViewSet
        request = self._correlation_request(
            {'file_id': 1, 'params': ['Param0', 'Param1', 'FailOnly'],
             'data_only_bin1': True})
        resp = StatisticsViewSet.as_view({'post': 'correlation_matrix'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_correlation_matrix_only_fail_test_item_400_when_below_two(self):
        """correlation_matrix + 仅Fail：重放后只剩 FailOnly 一个参数 → 400。"""
        from apps.analysis.views import StatisticsViewSet
        request = self._correlation_request(
            {'file_id': 1, 'params': ['Param0', 'Param1', 'FailOnly'],
             'only_fail_test_item': True})
        resp = StatisticsViewSet.as_view({'post': 'correlation_matrix'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data.get('error'), 'need_at_least_2_params')
