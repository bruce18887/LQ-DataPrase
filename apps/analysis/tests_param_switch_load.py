"""切测试项提效第一批的两条契约：站点表并入直方图响应、KDE 按需算。

背景（2026-10-17 实测，ETS88 35,246 行 × 1,702 测试项那只样例文件）：一次切换发
**两个**请求，且 histogram 计算里 64ms/90ms 花在**两条** KDE 曲线上，而界面只显示
其中一条（``HistogramChart.vue`` 按「KDE含超限」二选一，``filtered_kde_curve`` 为
None 时回退全量）。所以：

1. 站点表改由 histogram 响应承载 ⇒ 必须与 ``/statistics/site_stats/`` **逐字段相等**，
   否则就是「为了省一个请求把数值口径改了」。本文件用同一帧、同一参数把两个端点
   各跑一遍再比。
2. KDE 由请求旗标决定算哪一条：``include_kde=false`` 一条都不算，``kde_variant``
   只算界面要用的那条；不传旗标时保持旧行为（两条都算），导出与历史用例不受影响。

fixture 为什么是 100 行：n≤10 时任何点离均值都不超过 ``(n-1)/√n ≈ 2.85`` 个样本 σ，
**±3σ 口径永远框住全部数据**，S3 与 RDL 的 fail 数恒等 ⇒ 等价性判退化成空断言。
按口径分工，每条判据都带 fail 数守卫（防止将来有人改小夹具把判据哑掉）：
  ``Param0``       全落在 RDL 内、无 IQR 异常值 —— RDL 口径 + KDE 无异常值回退
  ``ParamTail``    99 点紧贴 10.4~10.5 + 1 点 13.9（仍在 RDL 8.0~14.3 内）
                   → RDL 0 fail、S3 1 fail（两个口径必须不同）
  ``ParamOutlier`` 94 点紧贴 10.4~10.5 + 6 点 14.4（超 USL）
                   → RDL 6 fail、DR 0 fail（数据极值口径必须不同）+ KDE 曲线分岔
帧 fixture 自带（不继承 ``ChartConfigFilterTests``，免得把它的 60 例再跑一遍）。
"""
import types

import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.test_support import fake_datafile, patch_df_loader

_N = 100
_TIGHT = [10.4 + 0.05 * (i % 3) for i in range(_N)]  # 10.40 / 10.45 / 10.50 交替
_PARAMS = ('Param0', 'ParamTail', 'ParamOutlier')

_FRAME = {
    'serial': list(range(101, 101 + _N)),
    # 只有行 5 落在 Bin 2：Bin1 过滤必须真的删掉一行，但又不能把各参数的尾部
    # 特征行（行 0 的 13.9 / 14.4）一起筛掉，否则 S3+Bin1 那条判据会变成空断言。
    'SW_Bin': [2 if i == 5 else 1 for i in range(_N)],
    'Site': [1 + (i % 2) for i in range(_N)],
    'Param0': list(_TIGHT),
    'ParamTail': [13.9] + _TIGHT[:_N - 1],
    'ParamOutlier': [14.4] * 6 + _TIGHT[:_N - 6],
}

_USER = types.SimpleNamespace(
    pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
    is_staff=False, is_superuser=False,
)


class SwitchRequestHarness(SimpleTestCase):
    """一次装帧 + 分别打两个端点，返回响应体（同一帧是等价性判据的前提）。"""

    def setUp(self):
        self.df = pd.DataFrame(_FRAME)
        self.metadata = {
            'format': 'CTA8290D',
            'mins': {p: '8.0' for p in _PARAMS},
            'maxs': {p: '14.3' for p in _PARAMS},
            'units': {p: 'V' for p in _PARAMS},
        }
        self._repatch()

    def tearDown(self):
        self.restore()

    def _repatch(self):
        """帧的唯一持有者：多处打桩会互相还原成前一个假 loader（跨用例污染）。"""
        self.restore = patch_df_loader(
            self.df, fake_datafile(format_type='CTA8290D'), self.metadata)

    def _request(self, url, payload):
        from rest_framework.test import APIRequestFactory, force_authenticate
        request = APIRequestFactory().post(url, payload, format='json')
        force_authenticate(request, user=_USER)
        return request

    @staticmethod
    def _with_flags(payload, flags, keys):
        for key in keys:
            if key in flags:
                payload[key] = flags[key]
        return payload

    def histogram(self, param='Param0', **flags):
        from apps.analysis.views import AnalysisViewSet
        payload = self._with_flags(
            {'file_id': 1, 'params': [param]}, flags,
            ('range_type', 'custom_low', 'custom_high', 'data_only_bin1',
             'include_kde', 'kde_variant'))
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(
            self._request('/api/v1/analysis/histogram/', payload))
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data['results'][param]

    def site_stats_endpoint(self, param='Param0', **flags):
        """端点收单数 ``param``，且只认它自己那四个旗标（没有 KDE 开关）。"""
        from apps.analysis.views import StatisticsViewSet
        payload = self._with_flags(
            {'file_id': 1, 'param': param}, flags,
            ('range_type', 'custom_low', 'custom_high', 'data_only_bin1'))
        resp = StatisticsViewSet.as_view({'post': 'site_stats'})(
            self._request('/api/v1/statistics/site_stats/', payload))
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data['site_data']


class HistogramSiteStatsEquivalenceTests(SwitchRequestHarness):
    """``histogram`` 响应里的站点表必须逐字段等于 ``/statistics/site_stats/``。"""

    def _assert_same_rows(self, label, param, expect_fail, **flags):
        merged = self.histogram(param, **flags).get('site_stats')
        endpoint = self.site_stats_endpoint(param, **flags)
        self.assertEqual(
            merged, endpoint,
            f'{label} 口径下并入直方图的站点表与独立端点数值不一致')
        total_fail = sum(r.get('FailCountNum', 0) for r in endpoint
                         if r['Site'] != 'ALL Site')
        if expect_fail:
            self.assertGreater(total_fail, 0,
                               f'{label} 夹具必须真的产生 fail，否则等价性是空断言')
        else:
            self.assertEqual(total_fail, 0, f'{label} 口径不该有 fail')

    def test_rdl_limits_site_rows_match(self):
        self._assert_same_rows('RDL', 'Param0', expect_fail=False,
                               range_type='RDL')

    def test_sigma3_site_rows_match(self):
        """ParamTail 的 13.9 在 RDL 内、3σ 外：旧实现恒按 RDL 报 0 fail，必须判红。"""
        self._assert_same_rows('S3', 'ParamTail', expect_fail=True,
                               range_type='S3')

    def test_data_range_site_rows_match(self):
        """ParamOutlier 的 14.4 超 USL：RDL 报 6 fail、DR 报 0 fail，口径须跟着 range_type。"""
        self._assert_same_rows('DR', 'ParamOutlier', expect_fail=False,
                               range_type='DR')

    def test_custom_limit_site_rows_match(self):
        """CL 用用户自定义限：2026-09-05 审查契约#4 修好的语义，不能回退。

        自定义限取 10.42~10.48：紧贴值里的 10.40/10.50 各 1/3 落到限外（约 63 fail），
        而 RDL 8.0~14.3 只算出 14.4 那 6 个 → 两个口径的 fail 数必然不同。
        （先前写 10.40~10.50 时紧贴值全在限内，CL 与 RDL 同报 6 fail，判据是空的。）
        """
        self._assert_same_rows('CL', 'ParamOutlier', expect_fail=True,
                               range_type='CL', custom_low=10.42, custom_high=10.48)

    def test_bin1_filtered_site_rows_match(self):
        self._assert_same_rows('Bin1+S3', 'ParamTail', expect_fail=True,
                               range_type='S3', data_only_bin1=True)

    def test_no_site_column_leaves_field_absent(self):
        """无 Site 列 → 字段缺席/None（前端据此显示「该文件没有 Site 列」内联提示）。"""
        from apps.analysis.views import AnalysisViewSet
        self.df = self.df.drop(columns=['Site'])
        self.tearDown()
        self._repatch()
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(
            self._request('/api/v1/analysis/histogram/',
                          {'file_id': 1, 'params': ['Param0']}))
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.data['results']['Param0'].get('site_stats'))


class HistogramKdeOnDemandTests(SwitchRequestHarness):
    """KDE 曲线由请求旗标决定：``include_kde`` + ``kde_variant``。"""

    TAIL_X = (14.2, 14.6)  # 14.4 那 6 个点所在的 x 窗口

    def test_default_no_flags_keeps_both_curves(self):
        """不传旗标 = 旧口径两条都算（导出/历史用例的依赖面）。"""
        r = self.histogram('ParamOutlier')
        self.assertIsNotNone(r.get('kde_curve'))
        self.assertIsNotNone(r.get('filtered_kde_curve'))

    def test_include_kde_false_computes_neither(self):
        r = self.histogram('ParamOutlier', include_kde=False)
        self.assertIsNone(r.get('kde_curve'))
        self.assertIsNone(r.get('filtered_kde_curve'))
        # 只砍曲线：分箱与统计卡照旧，否则前端整片会空
        self.assertGreater(len(r['bin_centers']), 1)
        self.assertIsNotNone(r['cpk'])

    def test_variant_all_returns_only_raw_with_fail_bump(self):
        """「KDE含超限」= 只要全量那条：fail 峰可见，且不产出裁剪曲线。"""
        r = self.histogram('ParamOutlier', range_type='DR', kde_variant='all')
        curve = r['kde_curve']
        self.assertIsNotNone(curve)
        self.assertIsNone(r.get('filtered_kde_curve'))
        tail = [y for x, y in curve if self.TAIL_X[0] <= x <= self.TAIL_X[1]]
        self.assertTrue(tail, '采样网格必须覆盖到 fail 值所在区间')
        self.assertGreater(max(tail), 0, '全量曲线必须带 fail 峰')

    def test_variant_filtered_returns_only_filtered_without_fail_bump(self):
        r = self.histogram('ParamOutlier', range_type='DR', kde_variant='filtered')
        curve = r.get('filtered_kde_curve')
        self.assertIsNotNone(curve, '有异常值时必须给出裁剪曲线')
        self.assertIsNone(r.get('kde_curve'), '只算一条：全量那条不该出现在响应里')
        self.assertTrue(all(y == 0 for x, y in curve
                            if self.TAIL_X[0] <= x <= self.TAIL_X[1]),
                        '裁剪曲线必须排除 fail 峰')

    def test_variant_filtered_without_outliers_falls_back_to_raw(self):
        """无异常值时界面本就回退全量曲线 → 回退的那一条必须是算出来的那条。"""
        r = self.histogram('Param0', kde_variant='filtered')
        self.assertIsNotNone(r.get('kde_curve'))
        self.assertIsNone(r.get('filtered_kde_curve'))

    def test_unknown_variant_falls_back_to_legacy_both(self):
        """非法值不改语义：白名单外一律按旧口径两条都算。"""
        r = self.histogram('ParamOutlier', kde_variant='nonsense')
        self.assertIsNotNone(r.get('kde_curve'))
        self.assertIsNotNone(r.get('filtered_kde_curve'))
