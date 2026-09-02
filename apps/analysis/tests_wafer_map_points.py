"""晶圆图点位构建的回归网（为向量化重构兜底）。

``compute_wafer_map_data`` 历史上逐行 ``df.loc[idx, col]`` 取 5–6 列，
10 万行实测约 4.7s 且产 7.6MB JSON。向量化改写属于**行为保持**重构，
因此这里先把「输出必须逐字段一致」钉死，再加一条量级性能守卫。
"""
import time

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.data_services import compute_wafer_map_data


def _meta():
    return {'format': 'CTA8290D',
            'mins': {'P1': '0'}, 'maxs': {'P1': '10'}, 'units': {'P1': 'mV'}}


class WaferMapPointsShapeTests(SimpleTestCase):
    """点集的字段、顺序、跳过规则与状态判定。"""

    def test_point_fields_and_order_match_rows(self):
        df = pd.DataFrame({
            'X_COORD': [0.0, 10.0, 20.0],
            'Y_COORD': [0.0, 10.0, 20.0],
            'Serial_No': ['A1', 'A2', 'A3'],
            'SW_Bin': ['1', '2', '1'],
            'Site': ['1', '2', '1'],
            'P1': [1.0, -5.0, 3.0],
        })
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        pts = out['points']

        self.assertEqual([(p['x'], p['y']) for p in pts],
                         [(0.0, 0.0), (10.0, 10.0), (20.0, 20.0)],
                         '点顺序必须跟随行顺序（前端 dataZoom/tooltip 依赖）')
        self.assertEqual([p['status'] for p in pts], ['Pass', 'Fail', 'Pass'])
        self.assertEqual(pts[1]['serial'], 'A2')
        self.assertEqual(pts[1]['bin'], '2')
        self.assertEqual(pts[1]['site'], '2')
        # color_by != 'site' → 不带 color_group
        self.assertNotIn('color_group', pts[0])
        self.assertEqual(out['stats']['total'], 3)
        self.assertEqual(out['stats']['fail_count'], 1)

    def test_color_by_site_adds_color_group(self):
        df = pd.DataFrame({'X_COORD': [0.0, 1.0], 'Y_COORD': [0.0, 1.0],
                           'Site': ['3', '4'], 'P1': [1.0, 2.0]})
        out = compute_wafer_map_data(df, _meta(), 'P1', 'site', 'X_COORD', 'Y_COORD')
        self.assertEqual([p['color_group'] for p in out['points']],
                         ['Site 3', 'Site 4'])

    def test_rows_with_non_finite_or_non_numeric_coords_are_skipped(self):
        df = pd.DataFrame({'X_COORD': [0.0, np.nan, 'abc', 30.0],
                           'Y_COORD': [0.0, 10.0, 10.0, 30.0],
                           'Site': ['1'] * 4, 'P1': [1.0] * 4})
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual(len(out['points']), 2)
        self.assertEqual([(p['x'], p['y']) for p in out['points']],
                         [(0.0, 0.0), (30.0, 30.0)])

    def test_skipped_rows_still_count_in_stats(self):
        """stats 走全量判定口径（compute_wafer_fail_data），不因坐标缺而少计。"""
        df = pd.DataFrame({'X_COORD': [0.0, np.nan], 'Y_COORD': [0.0, 1.0],
                           'Site': ['1', '1'], 'P1': [-1.0, 5.0]})
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual(len(out['points']), 1)
        self.assertEqual(out['stats']['fail_count'], 1)

    def test_string_typed_coord_columns_are_coerced(self):
        """解析器给出的坐标列常是 object（字符串数字），必须能用。"""
        df = pd.DataFrame({'X_COORD': ['0', '10'], 'Y_COORD': ['0', '10'],
                           'Site': ['1', '1'], 'P1': [1.0, 2.0]})
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual([p['x'] for p in out['points']], [0.0, 10.0])

    def test_bool_site_column_is_stringified_not_summed(self):
        df = pd.DataFrame({'X_COORD': [0.0, 1.0], 'Y_COORD': [0.0, 1.0],
                           'Site': [True, False], 'P1': [1.0, 2.0]})
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual([p['site'] for p in out['points']], ['True', 'False'])

    def test_geometry_is_none_without_any_valid_point(self):
        df = pd.DataFrame({'X_COORD': [np.nan], 'Y_COORD': [np.nan],
                           'Site': ['1'], 'P1': [1.0]})
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual(out['points'], [])
        self.assertIsNone(out['wafer'])

    def test_no_param_uses_global_judgement(self):
        df = pd.DataFrame({'X_COORD': [0.0, 10.0], 'Y_COORD': [0.0, 10.0],
                           'Site': ['1', '1'], 'P1': [5.0, -9.0]})
        out = compute_wafer_map_data(df, _meta(), None, 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual([p['status'] for p in out['points']], ['Pass', 'Fail'])

    def test_duplicate_columns_do_not_yield_dataframe_rows(self):
        """重名列经视图层去重后仍取单列；此处直接给重名列，必须不崩。"""
        df = pd.DataFrame(np.array([[0.0, 0.0, 1.0], [10.0, 10.0, 2.0]]),
                          columns=['X_COORD', 'X_COORD', 'P1'])
        df['Site'] = ['1', '2']
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'X_COORD')
        self.assertEqual(len(out['points']), 2)


class WaferMapBuildSpeedGuardTests(SimpleTestCase):
    """量级守卫：向量化前 50k 行约 2.3s，向量化后应远低于该量级。

    给 6× 余量（阈值 2.0s）以免慢盘/CI 抖动误报；它仍能在有人退回逐行
    ``df.loc`` 时立刻变红。
    """

    def test_50k_rows_build_under_two_seconds(self):
        n = 50_000
        rng = np.random.default_rng(7)
        df = pd.DataFrame({
            'X_COORD': rng.integers(-300, 300, n).astype(float),
            'Y_COORD': rng.integers(-300, 300, n).astype(float),
            'Serial_No': [f'S{i}' for i in range(n)],
            'HardBin': rng.choice(['1', '2', '3'], n),
            'Site': rng.choice(['1', '2', '3', '4'], n),
            'P1': rng.normal(5, 1, n),
        })
        started = time.perf_counter()
        out = compute_wafer_map_data(df, _meta(), 'P1', 'site', 'X_COORD', 'Y_COORD')
        elapsed = time.perf_counter() - started

        self.assertEqual(len(out['points']), n)
        self.assertLess(elapsed, 2.0,
                        f'50k 行构建耗时 {elapsed:.2f}s，疑似退回逐行 df.loc')
