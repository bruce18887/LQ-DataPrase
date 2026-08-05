"""Dashboard 测试：测试项总览（CPK 参数表 ∪ Fail 测试项明细）与 summary API。"""

import os
import unittest

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.analysis.services.statistics import (
    calculate_fail_test_item_statistics,
    get_columns_with_limits,
)
from apps.datafiles.models import DataFile
from apps.datafiles.services import clear_parse_cache
from apps.dashboard.views import compute_test_item_overview, _derive_param_stats

User = get_user_model()

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'Data', 'SampleData')
GAGE_S1_PATH = os.path.join(SAMPLE_DATA_DIR, 'Gage', 'gage_m_S1.csv')
CTA8280F_PATH = os.path.join(
    SAMPLE_DATA_DIR, 'CTA8280F',
    'DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_FT_20260420_164504.csv',
)


def _make_df():
    """构造小 DataFrame：P1(限+fail) P2(限无fail) P3(无限无fail) P4(无限+fail) + Site/Bin。"""
    return pd.DataFrame({
        'P1': [1.0, 2.0, 3.0, 4.0],
        'P2': [10.0, 11.0, 12.0, 12.0],
        'P3': [100.0, 200.0, 300.0, 400.0],
        'P4': ['ok', 'ng', 'ok', 'ng'],
        'Site': ['S1', 'S1', 'S2', 'S2'],
        'Bin': [1, 2, 1, 1],
    })


def _make_meta():
    return {
        'format': 'CTA8290D',
        'units': {'P1': 'V'},
        'mins': {'P1': '0.5', 'P2': '9.0'},
        'maxs': {'P1': '5.0', 'P2': '13.0'},
    }


def _make_fail_stats():
    return {
        'P1': {'fail_count': 3, 'percentage': 60.0},
        'P4': {'fail_count': 2, 'percentage': 40.0},
    }


class TestItemOverviewUnitTests(SimpleTestCase):
    """compute_test_item_overview / _derive_param_stats 纯函数测试。"""

    def test_rows_union_and_column_order(self):
        """行集 = 限值参数 ∪ fail 项，按 df.columns 原始顺序；无规格限无 fail 的列不出现。"""
        rows = compute_test_item_overview(_make_df(), _make_meta(), _make_fail_stats())
        self.assertEqual([r['name'] for r in rows], ['P1', 'P2', 'P4'])
        # P3 / Site / Bin 不在行集
        self.assertNotIn('P3', [r['name'] for r in rows])
        self.assertNotIn('Site', [r['name'] for r in rows])

    def test_no_fail_param_gets_zero(self):
        rows = compute_test_item_overview(_make_df(), _make_meta(), _make_fail_stats())
        p2 = next(r for r in rows if r['name'] == 'P2')
        self.assertEqual(p2['fail_count'], 0)
        self.assertEqual(p2['percentage'], 0.0)

    def test_fail_without_limits_shows_none_stats(self):
        """无规格限 fail 项：统计列全 None（前端显示 N/A），fail 计数正确。"""
        rows = compute_test_item_overview(_make_df(), _make_meta(), _make_fail_stats())
        p4 = next(r for r in rows if r['name'] == 'P4')
        self.assertEqual(p4['fail_count'], 2)
        self.assertEqual(p4['percentage'], 40.0)
        for key in ('mean', 'std', 'min', 'max', 'lsl', 'usl', 'cpk', 'cpk_level', 'cpk_color'):
            self.assertIsNone(p4[key], f'{key} 应为 None')

    def test_numeric_stats_correct(self):
        """已知序列的 count/mean/std(ddof=0)/min/max/lsl/usl 与 4 位舍入。"""
        rows = compute_test_item_overview(_make_df(), _make_meta(), _make_fail_stats())
        p1 = next(r for r in rows if r['name'] == 'P1')
        self.assertEqual(p1['data_count'], 4)
        self.assertEqual(p1['mean'], 2.5)
        self.assertAlmostEqual(p1['std'], 1.1180, places=3)
        self.assertEqual(p1['min'], 1.0)
        self.assertEqual(p1['max'], 4.0)
        self.assertEqual(p1['lsl'], 0.5)
        self.assertEqual(p1['usl'], 5.0)
        self.assertEqual(p1['unit'], 'V')

    def test_cpk_level_color_present(self):
        """cpk/cpk_level/cpk_color 与 compute_cpk 输出一致（有限值）。"""
        from apps.analysis.services.statistics import compute_cpk
        rows = compute_test_item_overview(_make_df(), _make_meta(), _make_fail_stats())
        p1 = next(r for r in rows if r['name'] == 'P1')
        expected = compute_cpk(2.5, 1.1180, 0.5, 5.0)
        self.assertEqual(p1['cpk'], round(expected['cpk'], 3))
        self.assertEqual(p1['cpk_level'], expected['cpk_level'])
        self.assertEqual(p1['cpk_color'], expected['cpk_color'])
        self.assertIsNotNone(p1['cpk'])

    def test_single_sided_limit_kept(self):
        """单边限参数保留（回归：旧 compute_parameter_summary 语义），缺失侧 None，cpk 为单边值。"""
        df = pd.DataFrame({'P': [1.0, 2.0, 3.0]})
        meta = {
            'format': 'CTA8290D', 'units': {},
            'mins': {}, 'maxs': {'P': '4.0'},  # 只有 USL
        }
        rows = compute_test_item_overview(df, meta, {})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsNone(row['lsl'])
        self.assertEqual(row['usl'], 4.0)
        # 单边 CPK = (4-2)/(3*std(ddof=0))，std=sqrt(2/3)≈0.8165
        self.assertIsNotNone(row['cpk'])
        self.assertAlmostEqual(row['cpk'], round((4.0 - 2.0) / (3 * 0.8165), 3), places=2)

    def test_all_nan_column_yields_none_stats(self):
        """全 NaN 限值列：data_count=0、统计列 None、cpk None（防 inf 破坏 JSON）。"""
        df = pd.DataFrame({'P': [float('nan'), float('nan')]})
        meta = {'format': 'CTA8290D', 'units': {}, 'mins': {'P': '0.0'}, 'maxs': {'P': '1.0'}}
        rows = compute_test_item_overview(df, meta, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['data_count'], 0)
        self.assertIsNone(rows[0]['cpk'])
        self.assertIsNone(rows[0]['mean'])

    def test_duplicate_column_guard(self):
        """重复列名兜底：不崩溃（df[col] 返回 DataFrame，取第一列），每列各一行。"""
        df = pd.concat([
            pd.DataFrame({'P': [1.0, 2.0, 3.0]}),
            pd.DataFrame({'P': [9.0, 9.0, 9.0]}),
        ], axis=1)
        meta = {'format': 'CTA8290D', 'units': {}, 'mins': {'P': '0.0'}, 'maxs': {'P': '5.0'}}
        rows = compute_test_item_overview(df, meta, {})
        self.assertEqual(len(rows), 2)  # 重复列名出现两次 → 两行（与旧行为一致）
        for row in rows:
            self.assertEqual(row['data_count'], 3)
            self.assertEqual(row['mean'], 2.0)  # 取第一列

    def test_derive_param_stats_sorted_and_keys(self):
        """_derive_param_stats：cpk 升序、键集 = 旧 param_stats 键集、过滤 cpk None。"""
        rows = compute_test_item_overview(_make_df(), _make_meta(), _make_fail_stats())
        stats = _derive_param_stats(rows)
        keys = set(stats[0].keys())
        self.assertEqual(
            keys,
            {'param', 'mean', 'std', 'cpk', 'cpk_level', 'cpk_color', 'unit', 'lsl', 'usl'},
        )
        self.assertEqual([s['cpk'] for s in stats], sorted(s['cpk'] for s in stats))
        self.assertEqual([s['param'] for s in stats], ['P1', 'P2'])  # P1 cpk≈0.596 < P2≈0.704
        # P4 cpk 为 None 被过滤
        self.assertNotIn('P4', [s['param'] for s in stats])

    def test_empty_df(self):
        rows = compute_test_item_overview(pd.DataFrame(), {'format': 'CTA8290D'}, {})
        self.assertEqual(rows, [])


@unittest.skipUnless(os.path.exists(GAGE_S1_PATH), 'SampleData/Gage 目录不存在（跳过）')
class SummaryApiGageTests(APITestCase):
    """GET /api/v1/summary/：GAGE 样例（233 个限值参数、无 fail 项）。"""

    def setUp(self):
        self.user = User.objects.create_user(username='dashuser', password='pw')
        self.client.force_authenticate(self.user)
        clear_parse_cache()
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename='gage_m_S1.csv',
            file_path=GAGE_S1_PATH,
            file_size=os.path.getsize(GAGE_S1_PATH),
            format_type='CTA8290D',
            status='ready',
        )

    def test_summary_returns_overview_in_column_order(self):
        """200 + test_item_overview 行名序列 == 限值参数（按 df.columns 顺序）。"""
        from apps.datafiles.parsers import get_parser
        resp = self.client.get('/api/v1/summary/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        df, meta = get_parser('CTA8290D').parse(GAGE_S1_PATH)
        # 独立复算宽松限值集（与实现同语义：有有效 LSL 或 USL）
        limits = [
            c for c in df.columns
            if (str(meta.get('mins', {}).get(c, '')).strip().lower() not in ('', 'nan', 'none', 'n/a') and
                str(meta.get('mins', {}).get(c, '')).strip())
            or (str(meta.get('maxs', {}).get(c, '')).strip().lower() not in ('', 'nan', 'none', 'n/a') and
                str(meta.get('maxs', {}).get(c, '')).strip())
        ]
        names = [r['name'] for r in resp.data['test_item_overview']]
        self.assertEqual(names, [c for c in df.columns if c in limits])

    def test_overview_row_schema(self):
        """每行含全部 13 键；限值行统计为数值；无 fail 行 fail_count==0。"""
        resp = self.client.get('/api/v1/summary/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data['test_item_overview']
        self.assertGreater(len(rows), 0)
        expected_keys = {
            'name', 'data_count', 'mean', 'std', 'min', 'max', 'lsl', 'usl',
            'cpk', 'cpk_level', 'cpk_color', 'unit', 'fail_count', 'percentage',
        }
        for row in rows:
            self.assertEqual(set(row.keys()), expected_keys, f'{row["name"]} 键集')
            self.assertEqual(row['fail_count'], 0)  # GAGE 无 fail
            self.assertEqual(row['percentage'], 0.0)
            self.assertGreaterEqual(row['data_count'], 0)
            if row['data_count'] > 0:
                self.assertIsInstance(row['mean'], float)
                self.assertIsInstance(row['cpk'], float)
                self.assertIsInstance(row['lsl'], float)
                self.assertIsInstance(row['usl'], float)
            else:
                self.assertIsNone(row['cpk'], f'{row["name"]} 全 NaN 列 cpk 应为 None')

    def test_param_stats_derived_consistent(self):
        """param_stats 与 overview 同名行 cpk 一致（防双路径漂移）+ CPK 升序。"""
        resp = self.client.get('/api/v1/summary/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        overview_by_name = {r['name']: r for r in resp.data['test_item_overview']}
        stats = resp.data['param_stats']
        self.assertGreater(len(stats), 0)
        for s in stats:
            self.assertEqual(s['cpk'], overview_by_name[s['param']]['cpk'], s['param'])
        cpks = [s['cpk'] for s in stats]
        self.assertEqual(cpks, sorted(cpks))

    def test_fail_test_items_field_kept(self):
        """响应仍含 fail_test_items（DataQualityOverview 契约）。"""
        resp = self.client.get('/api/v1/summary/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('fail_test_items', resp.data)
        self.assertEqual(resp.data['fail_test_items'], [])

    def test_unauthorized_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/v1/summary/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 401)

    def test_invalid_file_404(self):
        resp = self.client.get('/api/v1/summary/', {'file_id': 999999})
        self.assertEqual(resp.status_code, 404)


@unittest.skipUnless(os.path.exists(CTA8280F_PATH), 'SampleData/CTA8280F 目录不存在（跳过）')
class SummaryApiCta8280fTests(APITestCase):
    """GET /api/v1/summary/：CTA8280F 样例（含 fail 项，验证 fail 并集）。"""

    def setUp(self):
        self.user = User.objects.create_user(username='dashuser2', password='pw')
        self.client.force_authenticate(self.user)
        clear_parse_cache()
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename='DA35_CTA8280F.csv',
            file_path=CTA8280F_PATH,
            file_size=os.path.getsize(CTA8280F_PATH),
            format_type='CTA8280F',
            status='ready',
        )

    def test_fail_items_included_in_overview(self):
        """每个 fail 测试项都出现在 overview 行集，且 fail_count 与独立复算一致。"""
        from apps.datafiles.parsers import get_parser
        resp = self.client.get('/api/v1/summary/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        df, meta = get_parser('CTA8280F').parse(CTA8280F_PATH)
        fails = calculate_fail_test_item_statistics(df, meta)
        self.assertGreater(len(fails), 0, '样例应含 fail 项')
        overview_by_name = {r['name']: r for r in resp.data['test_item_overview']}
        for name, info in fails.items():
            self.assertIn(name, overview_by_name, f'{name} 应在 overview 中')
            self.assertEqual(overview_by_name[name]['fail_count'], info['fail_count'])
            self.assertEqual(overview_by_name[name]['percentage'], info['percentage'])
        # 有 fail 的行统计列有值（fail 判定依赖规格限，均值应为数值）
        first_fail = next(iter(fails))
        self.assertIsInstance(overview_by_name[first_fail]['mean'], float)
        self.assertIsInstance(overview_by_name[first_fail]['cpk'], float)
