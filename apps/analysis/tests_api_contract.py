"""分析页 API 契约回归测试（2026-09-02 审计批次 1）。

三组契约：
1. ``site_stats`` 的参数/站点守卫与同族端点（serial_distribution、qqplot）对齐，
   失败一律 4xx + 结构化 code，不再 500 或 200+body.error（lessons R3①）。
2. ``file_id`` 传非数字时 400 而非 ``int('abc')`` 抛 ValueError → 500。
3. ``/statistics/zonal_yield/`` 按晶圆半径 1/3、2/3 切中心/中间/边缘三区并给出良率
   —— 几何口径必须与晶圆图（前端画的圆环）同源。
"""
import types

import pandas as pd
from django.test import SimpleTestCase


def _fake_user():
    return types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False,
    )


class _PatchedViewMixin:
    """把 ``_load_df_from_request`` 替换成返回给定 df 的假实现（不碰 DB）。

    必须 patch **消费模块**里的绑定（``from ._helpers import ...`` 会各自
    建一份名字），patch 包名不生效 —— lessons R6③。
    """

    def _patch(self, df, metadata=None, datafile=None):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.analysis.views import analysis_views, statistics_views

        if metadata is None:
            metadata = {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}}
        if datafile is None:
            datafile = types.SimpleNamespace(id=1, filename='fake.csv',
                                             format_type='CTA8290D')

        def fake_load(request):
            return df, datafile, metadata, None

        originals = [
            (analysis_views, getattr(analysis_views, '_load_df_from_request')),
            (statistics_views, getattr(statistics_views, '_load_df_from_request')),
        ]
        analysis_views._load_df_from_request = fake_load
        statistics_views._load_df_from_request = fake_load

        def restore():
            for module, original in originals:
                module._load_df_from_request = original
        self.addCleanup(restore)

        return APIRequestFactory(), force_authenticate

    def _post(self, factory, force_authenticate, url, payload):
        request = factory.post(url, payload, format='json')
        force_authenticate(request, user=_fake_user())
        return request


class SiteStatsParamGuardTests(_PatchedViewMixin, SimpleTestCase):
    """/statistics/site_stats/ 的守卫必须与兄弟端点同形。"""

    def test_unknown_param_returns_400_param_not_found(self):
        from apps.analysis.views import StatisticsViewSet

        df = pd.DataFrame({'Site': ['1', '2'], 'Param0': [1.0, 2.0]})
        factory, force_authenticate = self._patch(df)
        request = self._post(factory, force_authenticate,
                             '/api/v1/statistics/site_stats/',
                             {'file_id': 1, 'param': '__bogus__'})
        response = StatisticsViewSet.as_view({'post': 'site_stats'})(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'param_not_found')

    def test_bool_param_column_does_not_500(self):
        """bool dtype 列：``is_numeric_dtype(True)==True`` 的历史坑（lessons R4①）。

        特征化测试（写它时行为已正确），锁住后续重构不回退。
        """
        from apps.analysis.views import StatisticsViewSet

        df = pd.DataFrame({'Site': ['1', '2'], 'Flag': [True, False]})
        factory, force_authenticate = self._patch(df)
        request = self._post(factory, force_authenticate,
                             '/api/v1/statistics/site_stats/',
                             {'file_id': 1, 'param': 'Flag'})
        response = StatisticsViewSet.as_view({'post': 'site_stats'})(request)
        response.render()

        self.assertLess(response.status_code, 500, response.content)

    def test_missing_site_column_returns_400_without_dumping_columns(self):
        from apps.analysis.views import StatisticsViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0], 'Param1': [3.0, 4.0]})
        factory, force_authenticate = self._patch(df)
        request = self._post(factory, force_authenticate,
                             '/api/v1/statistics/site_stats/',
                             {'file_id': 1, 'param': 'Param0'})
        response = StatisticsViewSet.as_view({'post': 'site_stats'})(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'no_site_column')
        # 大文件有 800+ 列，把列名全量塞进错误响应既无用又撑大载荷
        self.assertNotIn('available_columns', response.data)


class FileIdTypeGuardTests(SimpleTestCase):
    """``file_id`` 非数字 → 400 ``file_id_invalid``，不是 500。"""

    def test_non_numeric_file_id_returns_400(self):
        from apps.analysis.views import AnalysisViewSet
        from rest_framework.test import APIRequestFactory, force_authenticate

        factory = APIRequestFactory()
        request = factory.post('/api/v1/analysis/histogram/',
                               {'file_id': 'abc', 'params': ['Param0']},
                               format='json')
        force_authenticate(request, user=_fake_user())
        response = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'file_id_invalid')


class ZonalYieldServiceTests(SimpleTestCase):
    """分区口径：距圆心 r/3 内中心区、2r/3 内中间区、其余边缘区。"""

    _WAFER = {'center_x': 0.0, 'center_y': 0.0, 'radius': 30.0}

    def _summarize(self, xs, ys, fails, wafer=_WAFER):
        from apps.analysis.services.data_services import compute_wafer_zone_stats
        return compute_wafer_zone_stats(xs, ys, fails, wafer)

    def _by_name(self, zones):
        return {z['name']: z for z in zones}

    def test_zones_are_partitioned_by_radius_thirds(self):
        zones = self._by_name(self._summarize(
            [5.0, 20.0, 29.0],          # 距圆心 5 / 20 / 29（r=30）
            [0.0, 0.0, 0.0],
            [False, True, False]))

        self.assertEqual(set(zones), {'中心区', '中间区', '边缘区'})
        self.assertEqual(zones['中心区']['total'], 1)
        self.assertEqual(zones['中心区']['pass'], 1)
        self.assertEqual(zones['中间区']['fail'], 1)
        self.assertEqual(zones['边缘区']['total'], 1)

    def test_yield_is_percentage_of_pass_and_none_for_empty_zone(self):
        zones = self._by_name(self._summarize([1.0, 2.0], [0.0, 0.0],
                                              [False, True]))
        self.assertAlmostEqual(zones['中心区']['yield'], 50.0)
        self.assertEqual(zones['中间区']['total'], 0)
        self.assertIsNone(zones['中间区']['yield'])

    def test_non_finite_coordinates_are_skipped(self):
        zones = self._summarize([float('nan'), 5.0], [0.0, 0.0], [False, False])
        self.assertEqual(sum(z['total'] for z in zones), 1)

    def test_missing_wafer_geometry_returns_empty(self):
        self.assertEqual(self._summarize([1.0], [1.0], [False], wafer=None), [])

    def test_zone_geometry_comes_from_the_same_source_as_the_map(self):
        """分区半径与晶圆图边缘圆同源，否则环和统计对不上。"""
        from apps.analysis.services.data_services import (
            compute_wafer_geometry, compute_wafer_map_data)

        df = pd.DataFrame({'X_COORD': [-10.0, 10.0, 0.0],
                           'Y_COORD': [-10.0, 10.0, 0.0],
                           'Site': ['1', '1', '2'],
                           'P1': [1.0, 2.0, 3.0]})
        meta = {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}}
        wm = compute_wafer_map_data(df, meta, None, 'result', 'X_COORD', 'Y_COORD')
        geom = compute_wafer_geometry([-10.0, 10.0, 0.0], [-10.0, 10.0, 0.0])

        self.assertEqual(geom, wm['wafer'])


class ZonalYieldApiTests(_PatchedViewMixin, SimpleTestCase):
    """/statistics/zonal_yield/ 端点：分区良率统计 + 与兄弟端点同形的守卫。"""

    _META = {'format': 'CTA8290D',
             'mins': {'P1': '0'}, 'maxs': {'P1': '10'}, 'units': {'P1': 'mV'}}

    def test_returns_three_zones_with_global_judgement(self):
        from apps.analysis.views import StatisticsViewSet

        # 坐标对称于原点 → center=(0,0)、r=10.8（bounds 3.6/7.2/10.8）；P1<0 判 Fail
        df = pd.DataFrame({
            'X_COORD': [-10.0, 10.0, 0.0, 5.0, 10.0],
            'Y_COORD': [-10.0, 10.0, 0.0, 0.0, 0.0],
            'Site': ['1', '1', '2', '2', '1'],
            'P1': [1.0, 2.0, -1.0, 3.0, -2.0],
        })
        factory, force_authenticate = self._patch(df, metadata=self._META)
        request = self._post(factory, force_authenticate,
                             '/api/v1/statistics/zonal_yield/', {'file_id': 1})
        response = StatisticsViewSet.as_view({'post': 'zonal_yield'})(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        zones = response.data['zones']
        self.assertEqual([z['name'] for z in zones], ['中心区', '中间区', '边缘区'])
        # 0 距 → 中心区；5 距 → 中间区；10 与两个 14.14（外接圆外的角 die）→ 边缘区
        self.assertEqual([z['total'] for z in zones], [1, 1, 3])
        self.assertEqual(sum(z['total'] for z in zones), 5)
        self.assertEqual(zones[0]['fail'], 1)
        self.assertEqual(zones[1]['pass'], 1)

    def test_selected_param_limits_judgement_to_that_param(self):
        from apps.analysis.views import StatisticsViewSet

        # P1 超限（Fail）、P2 也在 Limit 内 —— 只按 P1 判定时中心区应为 Fail
        df = pd.DataFrame({
            'X_COORD': [0.0], 'Y_COORD': [0.0], 'Site': ['1'],
            'P1': [-1.0], 'P2': [1.0],
        })
        meta = {'format': 'CTA8290D',
                'mins': {'P1': '0', 'P2': '0'}, 'maxs': {'P1': '10', 'P2': '10'},
                'units': {}}
        factory, force_authenticate = self._patch(df, metadata=meta)
        request = self._post(factory, force_authenticate,
                             '/api/v1/statistics/zonal_yield/',
                             {'file_id': 1, 'param': 'P1'})
        response = StatisticsViewSet.as_view({'post': 'zonal_yield'})(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['zones'][0]['fail'], 1)

    def test_unknown_param_returns_400(self):
        from apps.analysis.views import StatisticsViewSet

        df = pd.DataFrame({'X_COORD': [5.0], 'Y_COORD': [0.0], 'P1': [1.0]})
        factory, force_authenticate = self._patch(df, metadata=self._META)
        request = self._post(factory, force_authenticate,
                             '/api/v1/statistics/zonal_yield/',
                             {'file_id': 1, 'param': '__bogus__'})
        response = StatisticsViewSet.as_view({'post': 'zonal_yield'})(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'param_not_found')

    def test_missing_coord_columns_returns_400(self):
        from apps.analysis.views import StatisticsViewSet

        df = pd.DataFrame({'Site': ['1'], 'P1': [1.0]})
        factory, force_authenticate = self._patch(df, metadata=self._META)
        request = self._post(factory, force_authenticate,
                             '/api/v1/statistics/zonal_yield/', {'file_id': 1})
        response = StatisticsViewSet.as_view({'post': 'zonal_yield'})(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'no_coord_columns')

    def test_single_coordinate_row_still_returns_zones(self):
        """只有 1 个 die（radius 退化）时不崩，点落在中心区。"""
        from apps.analysis.views import StatisticsViewSet

        df = pd.DataFrame({'X_COORD': [3.0], 'Y_COORD': [4.0], 'P1': [1.0]})
        factory, force_authenticate = self._patch(df, metadata=self._META)
        request = self._post(factory, force_authenticate,
                             '/api/v1/statistics/zonal_yield/', {'file_id': 1})
        response = StatisticsViewSet.as_view({'post': 'zonal_yield'})(request)
        response.render()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(sum(z['total'] for z in response.data['zones']), 1)
