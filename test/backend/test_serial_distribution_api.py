"""Tests for analysis API bare-200 error paths → 400 migration.

Pins the fix for "缺列时图表静默空白无报错"（serial_distribution +
wafer_map）：之前缺 Serial_No / 坐标列时后端以 HTTP 200 返回
``{'error': '...'}``，前端把它当正常数据渲染出空图/空白（无任何提示）。
修复后这些错误必须走 400 + detail，前端 axios 错误路径才能弹出提示。

Run directly:  python test/backend/test_serial_distribution_api.py
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

from django.test import TestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.datafiles.models import DataFile  # noqa: E402

PASSWORD = 'x-pass-12345678'

META_HEADER = 'CTA8280F\nDevice Name,TEST_DEVICE\nTestFileName,C:\\x\\prog.dll\n'


def _write_csv(dirpath, name, content):
    path = os.path.join(dirpath, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def _no_serial_csv():
    """CTA8280F 最小文件：serial/dut/part 候选列全无（连 Dut_No 都没有）。"""
    return (
        META_HEADER
        + '[Data]\n'
        + 'Site_No,SW_Bin,KELVIN_VIN,\n'
        + 'Unit,Unit,ohm,\n'
        + 'Min,Min,0,\n'
        + 'Max,Max,2,\n'
        + '1,1,0.5,\n'
        + '1,1,0.7,\n'
    )


def _dut_only_csv():
    """真实机台导出形态：无 Serial_No，唯一标识是 Dut_No（每 site 内序号）。"""
    return (
        META_HEADER
        + '[Data]\n'
        + 'Dut_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_CODE,Test_Time,Data_Num,KELVIN_VIN,\n'
        + 'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,\n'
        + 'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,\n'
        + 'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,\n'
        + ' 1,1,TRUE,1,0,0,None,4.1,10,0.5,\n'
        + ' 2,1,TRUE,1,0,0,None,4.2,10,0.7,\n'
    )


def _with_serial_csv():
    """标准 CTA8280F 最小文件：含 Index_No / Serial_No / 坐标列。"""
    return (
        META_HEADER
        + '[Data]\n'
        + 'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,Test_Time,Data_Num,KELVIN_VIN,\n'
        + 'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,\n'
        + 'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,\n'
        + 'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,\n'
        + '1,1,1,1,TRUE,1,0,0,None,4.1,10,0.5,\n'
        + '2,1,2,1,TRUE,1,0,0,None,4.2,10,0.7,\n'
    )


def _no_coord_csv():
    """CTA8280F 最小文件：无 X_COORD/Y_COORD 坐标列（晶圆图缺陷形态）。"""
    return (
        META_HEADER
        + '[Data]\n'
        + 'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,QR_Code,Test_Time,Data_Num,KELVIN_VIN,\n'
        + 'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,\n'
        + 'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,\n'
        + 'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,\n'
        + '1,1,1,1,TRUE,1,None,4.1,10,0.5,\n'
        + '2,1,2,1,TRUE,1,None,4.2,10,0.7,\n'
    )


class SerialDistributionApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = tempfile.mkdtemp(prefix='serial_dist_test_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user('serial_tester', 'st@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _register_file(self, name, content):
        path = _write_csv(self.tmpdir, name, content)
        return DataFile.objects.create(
            owner=self.user,
            filename=name,
            file_path=path,
            file_size=os.path.getsize(path),
            format_type='CTA8280F',
            status='ready',
        )

    def _post(self, datafile, param='KELVIN_VIN'):
        return self.client.post(
            '/api/v1/analysis/serial_distribution/',
            {'file_id': datafile.id, 'param': param},
            format='json',
        )

    def test_no_serial_column_returns_400_with_detail(self):
        """回归钉：serial/dut/part 候选全无必须 400 + 中文 detail（此前 200 静默空白）。"""
        df_row = self._register_file('no_serial.csv', _no_serial_csv())
        resp = self._post(df_row)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'no_serial_column')
        self.assertTrue(resp.data.get('detail'))

    def test_dut_only_column_falls_back_to_dut_no(self):
        """回归钉：无 Serial_No 但有 Dut_No（真实机台导出）→ 200 回退 Dut_No。

        Dut_No 是每 site 内序号（与 STS8200 的 PART_ID 同语义），此前
        ``get_serial_column`` 只匹配 serial / part+id → 400 序列图不可用。
        """
        df_row = self._register_file('dut_only.csv', _dut_only_csv())
        resp = self._post(df_row)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.data
        self.assertEqual(body['serial_col'], 'Dut_No')
        self.assertEqual(body['serial_candidates'], ['Dut_No'])
        self.assertEqual(body['continuous_serials'], [1, 2])
        total = sum(len(s['data']) for s in body['series_data'])
        self.assertEqual(total, 2, '每行一个序列点')

    def test_with_serial_column_returns_points(self):
        df_row = self._register_file('with_serial.csv', _with_serial_csv())
        resp = self._post(df_row)
        self.assertEqual(resp.status_code, 200)
        body = resp.data
        self.assertEqual(body['serial_col'], 'Serial_No')
        self.assertEqual(body['continuous_serials'], [1, 2])
        total = sum(len(s['data']) for s in body['series_data'])
        self.assertEqual(total, 2, '每行一个 serial 点')

    def test_missing_file_id_400(self):
        resp = self.client.post(
            '/api/v1/analysis/serial_distribution/',
            {'param': 'KELVIN_VIN'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'file_id_required')


class WaferMapApiTests(TestCase):
    """回归钉：无坐标列必须 400 + detail（此前裸 200 导致晶圆图静默空白）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = tempfile.mkdtemp(prefix='wafer_map_test_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user('wafer_tester', 'wt@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _register_file(self, name, content):
        path = _write_csv(self.tmpdir, name, content)
        return DataFile.objects.create(
            owner=self.user,
            filename=name,
            file_path=path,
            file_size=os.path.getsize(path),
            format_type='CTA8280F',
            status='ready',
        )

    def _post(self, datafile):
        return self.client.post(
            '/api/v1/analysis/wafer_map/',
            {'file_id': datafile.id},
            format='json',
        )

    def test_no_coord_columns_returns_400_with_detail(self):
        df_row = self._register_file('no_coord.csv', _no_coord_csv())
        resp = self._post(df_row)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'no_coord_columns')
        self.assertTrue(resp.data.get('detail'))

    def test_with_coord_columns_returns_points(self):
        df_row = self._register_file('with_coord.csv', _with_serial_csv())
        resp = self._post(df_row)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['x_col'], 'X_COORD')
        self.assertEqual(resp.data['y_col'], 'Y_COORD')
        self.assertEqual(len(resp.data['points']), 2)


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_serial_distribution_api'])
    sys.exit(1 if failures else 0)
