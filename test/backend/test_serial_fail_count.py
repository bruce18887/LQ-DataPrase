"""Tests for serial-distribution fail-count semantics.

Regression pins for "serial 分布中，散点图显示的 fail 数量与 fail 颗数不符":

* fail 判定必须按 die 的**最终** bin（重测行取最后一条），且与文件 bin 汇总
  口径一致（任一测试项 fail 即 fail，不论当前查看的参数值是否超限）；
* 值远超规格限的 fail 点必须带 ``anchor`` 标记（否则被显式 Y 轴裁切不可见）；
* 无测量值（NaN）的 fail die 计入 ``fail_count`` 并产出 anchor=1 点。

Run directly:  python test/backend/test_serial_fail_count.py
(Runs against an isolated test DB via DiscoverRunner — dev db.sqlite3 is
never touched.)
"""
import os
import shutil
import sys
import tempfile

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

import pandas as pd  # noqa: E402
from django.test import TestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.analysis.services.data_services.serial_distribution import compute_serial_distribution_data  # noqa: E402
from apps.datafiles.models import DataFile  # noqa: E402

PASSWORD = 'x-pass-12345678'

META = {
    'format': 'CTA8280F',
    'units': {'KELVIN_VIN': 'ohm'},
    'mins': {'KELVIN_VIN': '0'},
    'maxs': {'KELVIN_VIN': '2'},
}

# 8 行 → 6 颗 die（KELVIN_VIN 规格限 [0,2]，Y 轴 [-0.2, 2.2]）：
#  serial 1: pass，值 1.0（正常点）
#  serial 2: 首测 fail(3.0) → 复测 pass(1.5)  ← 重测对：最终 pass、取末值
#  serial 3: 首测 pass(0.5) → 复测 fail(5000.0)  ← 重测对：最终 fail、超高锚定
#  serial 4: fail，值 2.5（> y_max 2.2 → anchor=2）
#  serial 5: fail（在其它测试项 fail），值 1.0 在限内 → anchor=0
#  serial 6: fail，无测量值 → anchor=1
def _build_df():
    return pd.DataFrame([
        {'Serial_No': 1, 'Site_No': 1, 'SW_Bin': 1, 'KELVIN_VIN': 1.0},
        {'Serial_No': 2, 'Site_No': 1, 'SW_Bin': 5, 'KELVIN_VIN': 3.0},
        {'Serial_No': 2, 'Site_No': 1, 'SW_Bin': 1, 'KELVIN_VIN': 1.5},
        {'Serial_No': 3, 'Site_No': 1, 'SW_Bin': 1, 'KELVIN_VIN': 0.5},
        {'Serial_No': 3, 'Site_No': 1, 'SW_Bin': 7, 'KELVIN_VIN': 5000.0},
        {'Serial_No': 4, 'Site_No': 1, 'SW_Bin': 5, 'KELVIN_VIN': 2.5},
        {'Serial_No': 5, 'Site_No': 1, 'SW_Bin': 5, 'KELVIN_VIN': 1.0},
        {'Serial_No': 6, 'Site_No': 1, 'SW_Bin': 5, 'KELVIN_VIN': None},
    ])


def _points(result):
    return [pt for s in result['series_data'] for pt in s['data']]


def _point_by_serial(result, serial):
    for pt in _points(result):
        if pt[0] == serial:
            return pt
    raise AssertionError(f'serial {serial} missing from points: {_points(result)}')


class SerialFailCountServiceTests(TestCase):
    """服务层：直接调用 compute_serial_distribution_data。"""

    def test_counts_match_file_bin_summary(self):
        result = compute_serial_distribution_data(_build_df(), META, 'KELVIN_VIN', 'RDL', [])
        self.assertEqual(result['fail_count'], 4, 'serials 3/4/5/6 最终 bin != 1')
        self.assertEqual(result['pass_count'], 2, 'serials 1/2 最终 bin == 1')

    def test_retest_pair_uses_final_row(self):
        result = compute_serial_distribution_data(_build_df(), META, 'KELVIN_VIN', 'RDL', [])
        # 首测 fail → 复测 pass：最终 pass、值取复测 1.5（此前 .first() 画成 fail 值 3.0）
        self.assertEqual(_point_by_serial(result, 2), [2, 1.5, 0, 0])
        # 首测 pass → 复测 fail（值 5000 远超限）：最终 fail、超高锚定顶部
        self.assertEqual(_point_by_serial(result, 3), [3, 5000.0, 1, 2])

    def test_cross_test_item_fail_is_marked(self):
        result = compute_serial_distribution_data(_build_df(), META, 'KELVIN_VIN', 'RDL', [])
        # 值 1.0 在限内，但 die 在其它测试项 fail → is_fail=1、anchor=0（正常位置红点）
        self.assertEqual(_point_by_serial(result, 5), [5, 1.0, 1, 0])

    def test_slightly_over_limit_value_anchors(self):
        result = compute_serial_distribution_data(_build_df(), META, 'KELVIN_VIN', 'RDL', [])
        self.assertEqual(result['y_max'], 2.2, 'USL 2.0 + 10% padding')
        self.assertEqual(_point_by_serial(result, 4), [4, 2.5, 1, 2])

    def test_no_value_fail_die_still_counts_and_emits_point(self):
        result = compute_serial_distribution_data(_build_df(), META, 'KELVIN_VIN', 'RDL', [])
        self.assertEqual(_point_by_serial(result, 6), [6, None, 1, 1])
        self.assertEqual(result['fail_count'], 4, '无值 fail die 计入 fail_count')

    def test_under_lower_limit_anchors_bottom(self):
        df = _build_df().copy()
        df.loc[df['Serial_No'] == 5, 'KELVIN_VIN'] = -500.0
        result = compute_serial_distribution_data(df, META, 'KELVIN_VIN', 'RDL', [])
        self.assertEqual(_point_by_serial(result, 5), [5, -500.0, 1, 3])

    def test_no_bin_column_keeps_legacy_format(self):
        df = _build_df().drop(columns=['SW_Bin'])
        result = compute_serial_distribution_data(df, META, 'KELVIN_VIN', 'RDL', [])
        self.assertIsNone(result['fail_count'])
        self.assertIsNone(result['pass_count'])
        for pt in _points(result):
            self.assertEqual(len(pt), 2, '无 bin 列保持 [serial, value] 格式')

    def test_no_site_column_single_series(self):
        df = _build_df().drop(columns=['Site_No'])
        result = compute_serial_distribution_data(df, META, 'KELVIN_VIN', 'RDL', [])
        self.assertEqual(len(result['series_data']), 1)
        self.assertEqual(result['fail_count'], 4)
        self.assertEqual(_point_by_serial(result, 6), [6, None, 1, 1])

    def test_data_only_bin1_all_pass(self):
        """仅 Pass 数据（视图层 filter_bin1_rows 后）：fail_count 归零。"""
        df = _build_df()
        from apps.analysis.services.statistics.filters import filter_bin1_rows
        df = filter_bin1_rows(df, META)
        result = compute_serial_distribution_data(df, META, 'KELVIN_VIN', 'RDL', [])
        self.assertEqual(result['fail_count'], 0)
        self.assertEqual(result['pass_count'], len(_points(result)))


META_HEADER = 'CTA8280F\nDevice Name,TEST_DEVICE\nTestFileName,C:\\x\\prog.dll\n'

FAIL_CSV = (
    META_HEADER
    + '[Data]\n'
    + 'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,Test_Time,Data_Num,KELVIN_VIN,\n'
    + 'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,\n'
    + 'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,\n'
    + 'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,\n'
    + '1,1,1,1,TRUE,1,0,0,None,4.1,10,1.0,\n'
    + '2,1,2,1,TRUE,5,0,0,None,4.1,10,3.0,\n'
    + '3,1,2,1,TRUE,1,0,0,None,4.2,10,1.5,\n'
    + '4,1,3,1,TRUE,1,0,0,None,4.1,10,0.5,\n'
    + '5,1,3,1,TRUE,7,0,0,None,4.1,10,5000.0,\n'
    + '6,1,4,1,TRUE,5,0,0,None,4.1,10,2.5,\n'
    + '7,1,5,1,TRUE,5,0,0,None,4.1,10,1.0,\n'
    + '8,1,6,1,TRUE,5,0,0,None,4.3,10,,\n'
)


class SerialFailCountApiTests(TestCase):
    """API 层：/analysis/serial_distribution/ 响应契约。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = tempfile.mkdtemp(prefix='serial_fail_test_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user('serial_fail_tester', 'sft@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        path = os.path.join(self.tmpdir, 'fail.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(FAIL_CSV)
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename='fail.csv',
            file_path=path,
            file_size=os.path.getsize(path),
            format_type='CTA8280F',
            status='ready',
        )

    def test_response_carries_die_level_counts_and_anchors(self):
        resp = self.client.post(
            '/api/v1/analysis/serial_distribution/',
            {'file_id': self.datafile.id, 'param': 'KELVIN_VIN'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.data
        self.assertEqual(body['fail_count'], 4)
        self.assertEqual(body['pass_count'], 2)
        pts = [pt for s in body['series_data'] for pt in s['data']]
        by_serial = {p[0]: p for p in pts}
        # 重测对最终 pass（值取复测 1.5）；超高 fail anchor=2；无值 fail anchor=1
        self.assertEqual(by_serial[2], [2, 1.5, 0, 0])
        self.assertEqual(by_serial[3], [3, 5000.0, 1, 2])
        self.assertEqual(by_serial[6], [6, None, 1, 1])


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_serial_fail_count'])
    sys.exit(1 if failures else 0)
