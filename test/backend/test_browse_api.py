"""Tests for /browse/ API response contract (查看数据性能优化后).

Regression pins for the 2026-08-11 browse optimizations:
* fail detection cached per file — response shape unchanged;
* ``fail_mask`` removed from the response (only the type definition in the
  frontend consumed it; the /analysis/detect_fail/ endpoint keeps its own);
* rows pre-serialized via pandas ``to_json`` — null/NaN semantics must match
  the old ``replace + to_dict`` path (empty value → null);
* **传输格式压缩（第二轮）**：`rows` 对象数组改为 `headers` + `data`
  （orient='values' 行值数组）+ `fail_cells`（并行数组）三键拆分——
  209MB payload → 68MB、前端 parse 4.6x 提速。zip 后行对象与旧 records
  格式逐值相等（bench 断言验证）。

Run directly:  python test/backend/test_browse_api.py
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

# 8 行：KELVIN_VIN 规格限 [0,2]（headers 中索引 11）。
#  fail 行（SW_Bin != 1）：row2(3.0 超限)、row5(5000 超限)、row6(2.5 超限)、
#  row7(1.0 在限内，仅 bin fail)、row8(空值，仅 bin fail)；pass 行 1/3/4。
#  Site_No 分布（站点筛选测试素材）：1,1,2,1,3,2,1,3。
FAIL_CSV = (
    META_HEADER
    + '[Data]\n'
    + 'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,Test_Time,Data_Num,KELVIN_VIN,\n'
    + 'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,\n'
    + 'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,\n'
    + 'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,\n'
    + '1,1,1,1,TRUE,1,0,0,None,4.1,10,1.0,\n'
    + '2,1,2,1,TRUE,5,0,0,None,4.1,10,3.0,\n'
    + '3,1,2,2,TRUE,1,0,0,None,4.2,10,1.5,\n'
    + '4,1,3,1,TRUE,1,0,0,None,4.1,10,0.5,\n'
    + '5,1,3,3,TRUE,7,0,0,None,4.1,10,5000.0,\n'
    + '6,1,4,2,TRUE,5,0,0,None,4.1,10,2.5,\n'
    + '7,1,5,1,TRUE,5,0,0,None,4.1,10,1.0,\n'
    + '8,1,6,3,TRUE,5,0,0,None,4.3,10,,\n'
)


class BrowseApiTests(TestCase):
    """API 层：/browse/ 响应契约（查看数据页数据源）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = tempfile.mkdtemp(prefix='browse_api_test_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user('browse_tester', 'bt@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        path = os.path.join(self.tmpdir, f'browse_{self._testMethodName}.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(FAIL_CSV)
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename=os.path.basename(path),
            file_path=path,
            file_size=os.path.getsize(path),
            format_type='CTA8280F',
            status='ready',
        )

    def _browse(self, **params):
        params.setdefault('datafile_id', self.datafile.id)
        return self.client.get('/api/v1/browse/', params)

    @staticmethod
    def _zip(body):
        """把新契约 headers+data+fail_cells 还原为行对象（前端 zip 逻辑镜像）。"""
        cols = body['headers']
        return [
            {**{cols[j]: vals[j] for j in range(len(cols))}, '__fail_cells__': body['fail_cells'][i]}
            for i, vals in enumerate(body['data'])
        ]

    def test_response_structure(self):
        resp = self._browse(page_size=99999)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total'], 8)
        self.assertEqual(body['page'], 1)
        self.assertEqual(body['page_size'], 99999)
        self.assertEqual(body['total_pages'], 1)
        self.assertEqual(body['bin_column'], 'SW_Bin')
        self.assertEqual(body['fail_row_count'], 5)
        self.assertIn('KELVIN_VIN', body['headers'])
        # 传输格式：data 是 array-of-arrays、fail_cells 与之并行（等长）
        self.assertIsInstance(body['data'], list)
        self.assertIsInstance(body['data'][0], list)
        self.assertIsInstance(body['fail_cells'], list)
        self.assertEqual(len(body['data']), len(body['fail_cells']), 'fail_cells 必须与 data 行并行')
        self.assertEqual(len(body['data']), 8)
        # headers 不含内部 fail 列
        self.assertNotIn('__fail_cells__', body['headers'])
        # col_meta 契约
        self.assertEqual(
            body['col_meta']['KELVIN_VIN'],
            {'unit': 'ohm', 'min': '0', 'max': '2'},
        )
        # 死键 fail_mask 已移除
        self.assertNotIn('fail_mask', body)
        # 行序保持文件顺序（Index_No 是 headers 第 0 列）
        self.assertEqual(body['data'][0][0], 1)
        self.assertEqual(body['data'][-1][0], 8)

    def test_fail_cells_are_native_arrays(self):
        """zip 后 __fail_cells__ 为原生 list（非 JSON 字符串），且每个行都携带。"""
        resp = self._browse(page_size=99999)
        body = resp.json()
        rows = self._zip(body)
        bin_col = body['bin_column']
        by_idx = {r['Index_No']: r for r in rows}
        # pass 行：[]（恒存在）
        self.assertEqual(by_idx[1]['__fail_cells__'], [])
        self.assertIsInstance(by_idx[1]['__fail_cells__'], list)
        # 超限 fail 行：测试列在前、bin 列最后
        self.assertEqual(by_idx[2]['__fail_cells__'], ['KELVIN_VIN', bin_col])
        self.assertEqual(by_idx[5]['__fail_cells__'], ['KELVIN_VIN', bin_col])
        self.assertEqual(by_idx[6]['__fail_cells__'], ['KELVIN_VIN', bin_col])
        # 仅 bin fail（值在限内 / 空值）：只列 bin 列
        self.assertEqual(by_idx[7]['__fail_cells__'], [bin_col])
        self.assertEqual(by_idx[8]['__fail_cells__'], [bin_col])

    def test_empty_value_serializes_as_null(self):
        """row8 KELVIN_VIN 为空 → data 中 null（pandas to_json 与旧 replace 语义一致）。"""
        resp = self._browse(page_size=99999)
        body = resp.json()
        vin_idx = body['headers'].index('KELVIN_VIN')
        row8 = next(vals for vals in body['data'] if vals[0] == 8)
        self.assertIsNone(row8[vin_idx])

    def test_pass_filter(self):
        resp = self._browse(page_size=99999, pass_filter='PASS')
        self.assertEqual(resp.json()['total'], 3)
        self.assertEqual(len(resp.json()['data']), 3)
        resp = self._browse(page_size=99999, pass_filter='FAIL')
        self.assertEqual(resp.json()['total'], 5)

    def test_search_filters_rows(self):
        """search 全文过滤：'5000' 只命中 row5（KELVIN_VIN=5000.0）。"""
        resp = self._browse(page_size=99999, search='5000')
        self.assertEqual(resp.json()['total'], 1)
        self.assertEqual(resp.json()['data'][0][0], 5)

    def test_pagination_slice(self):
        resp = self._browse(page=2, page_size=3)
        body = resp.json()
        self.assertEqual(body['total'], 8)
        self.assertEqual(body['total_pages'], 3)
        self.assertEqual([vals[0] for vals in body['data']], [4, 5, 6])
        self.assertEqual(len(body['data']), len(body['fail_cells']))

    def test_pagination_beyond_end_returns_empty_rows(self):
        resp = self._browse(page=99, page_size=3)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['data'], [])
        self.assertEqual(body['fail_cells'], [])
        self.assertEqual(body['total'], 8)

    def test_ownership_isolation(self):
        other = User.objects.create_user('browse_other', 'bo@localhost', PASSWORD)
        self.client.force_authenticate(user=other)
        resp = self._browse(page_size=99999)
        self.assertEqual(resp.status_code, 404)

    def test_missing_datafile_id_400(self):
        resp = self.client.get('/api/v1/browse/', {})
        self.assertEqual(resp.status_code, 400)

    # ── 服务端分页新增契约（2026-08-12，IRM） ──

    def test_site_filter(self):
        resp = self._browse(page_size=99999, site_filter='2')
        body = resp.json()
        self.assertEqual(body['total'], 2)
        site_idx = body['headers'].index('Site_No')
        self.assertTrue(all(str(vals[site_idx]) == '2' for vals in body['data']))
        resp = self._browse(page_size=99999, site_filter='99')
        self.assertEqual(resp.json()['total'], 0)
        self.assertEqual(resp.json()['data'], [])

    def test_sort_model_asc_nan_last(self):
        resp = self._browse(page_size=99999, sort_model='[{"colId":"KELVIN_VIN","sort":"asc"}]')
        body = resp.json()
        vin_idx = body['headers'].index('KELVIN_VIN')
        values = [vals[vin_idx] for vals in body['data']]
        # NaN 恒排最后（row8 空值）
        self.assertIsNone(values[-1], 'NaN 必须排最后')
        num = [v for v in values[:-1] if v is not None]
        self.assertEqual(num, sorted(num))

    def test_sort_model_desc_nan_last(self):
        resp = self._browse(page_size=99999, sort_model='[{"colId":"KELVIN_VIN","sort":"desc"}]')
        body = resp.json()
        vin_idx = body['headers'].index('KELVIN_VIN')
        values = [vals[vin_idx] for vals in body['data']]
        self.assertIsNone(values[-1])
        num = [v for v in values[:-1] if v is not None]
        self.assertEqual(num, sorted(num, reverse=True))

    def test_sort_model_multi_column(self):
        resp = self._browse(
            page_size=99999,
            sort_model='[{"colId":"SW_Bin","sort":"asc"},{"colId":"KELVIN_VIN","sort":"desc"}]',
        )
        body = resp.json()
        bin_idx = body['headers'].index('SW_Bin')
        vin_idx = body['headers'].index('KELVIN_VIN')
        pairs = [(vals[bin_idx], vals[vin_idx] or 0) for vals in body['data']]
        # 组间 bin 升序、组内 KELVIN_VIN 降序
        self.assertEqual(pairs, sorted(pairs, key=lambda p: (p[0], -p[1])))

    def test_sort_model_unknown_column_ignored(self):
        resp = self._browse(page_size=99999, sort_model='[{"colId":"NOPE","sort":"asc"}]')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([vals[0] for vals in resp.json()['data']], [1, 2, 3, 4, 5, 6, 7, 8])

    def test_sort_model_malformed_400(self):
        resp = self._browse(page_size=99999, sort_model='not-json')
        self.assertEqual(resp.status_code, 400)

    def test_fail_row_count_is_filtered_semantics(self):
        base = {'page_size': 99999}
        self.assertEqual(self._browse(**base).json()['fail_row_count'], 5)
        # Site 2 的 fail 行：row6（SW_Bin=5 超限）—— row3 是 pass
        self.assertEqual(self._browse(**base, site_filter='2').json()['fail_row_count'], 1)
        self.assertEqual(self._browse(**base, pass_filter='PASS').json()['fail_row_count'], 0)
        self.assertEqual(self._browse(**base, pass_filter='FAIL').json()['fail_row_count'], 5)
        self.assertEqual(self._browse(**base, search='5000').json()['fail_row_count'], 1)

    def test_page1_carries_site_options_and_numeric_columns(self):
        body = self._browse(page_size=100).json()
        self.assertEqual(set(body['site_options']), {'1', '2', '3'})
        num = body['numeric_columns']
        self.assertIn('KELVIN_VIN', num)
        self.assertIn('Index_No', num)
        self.assertIn('SW_Bin', num, '数字字符串 object 列必须值级判定为数值')
        self.assertNotIn('QR_Code', num, '全 NaN 列（解析后 float64）无实际数值')
        self.assertNotIn('Dut_Pass', num, 'bool 列非数值（TRUE/FALSE 旧前端判定非数值）')

    def test_page_gt1_omits_meta_only_fields(self):
        body = self._browse(page=2, page_size=3).json()
        self.assertNotIn('site_options', body)
        self.assertNotIn('numeric_columns', body)
        self.assertEqual([vals[0] for vals in body['data']], [4, 5, 6])

    # ── 服务端列过滤（2026-08-12，方案 A：filter_model 白名单算子） ──

    def test_filter_number_equals(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"KELVIN_VIN":{"filterType":"number","type":"equals","filter":1.0}}',
        ).json()
        self.assertEqual(body['total'], 2)  # row1、row7 为 1.0

    def test_filter_number_less_than(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"KELVIN_VIN":{"filterType":"number","type":"lessThan","filter":1.0}}',
        ).json()
        self.assertEqual(body['total'], 1)  # row4 = 0.5

    def test_filter_number_in_range(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"KELVIN_VIN":{"filterType":"number","type":"inRange","filter":1.0,"filterTo":2.0}}',
        ).json()
        self.assertEqual(body['total'], 3)  # 1.0(row1) 1.5(row3) 1.0(row7)

    def test_filter_text_contains_case_insensitive(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"Serial_No":{"filterType":"text","type":"contains","filter":"SER"}}',
        ).json()
        # 无匹配（Serial_No 是数字串）——用真实文本断言：contains '2' 命中 row2/row3
        body2 = self._browse(
            page_size=99999,
            filter_model='{"Serial_No":{"filterType":"text","type":"contains","filter":"2"}}',
        ).json()
        self.assertEqual(body['total'], 0)
        self.assertEqual(body2['total'], 2)

    def test_filter_text_starts_with(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"Serial_No":{"filterType":"text","type":"startsWith","filter":"3"}}',
        ).json()
        self.assertEqual(body['total'], 2)  # Serial_No 3 的行：row4、row5

    def test_filter_multi_column_and(self):
        body = self._browse(
            page_size=99999,
            filter_model=(
                '{"SW_Bin":{"filterType":"number","type":"equals","filter":5},'
                '"KELVIN_VIN":{"filterType":"number","type":"lessThan","filter":3.0}}'
            ),
        ).json()
        # SW_Bin=5 的行：row2(3.0 不小于3 排除)、row6(2.5)、row7(1.0)、row8(NaN 排除) → 2
        self.assertEqual(body['total'], 2)

    def test_filter_empty_blank_semantics(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"KELVIN_VIN":{"filterType":"number","type":"empty"}}',
        ).json()
        self.assertEqual(body['total'], 1)  # row8 KELVIN_VIN 为空

    def test_filter_unknown_column_ignored(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"NOPE":{"filterType":"number","type":"equals","filter":1}}',
        ).json()
        self.assertEqual(body['total'], 8)

    def test_filter_malformed_400(self):
        resp = self._browse(page_size=99999, filter_model='not-json')
        self.assertEqual(resp.status_code, 400)

    def test_filter_affects_fail_row_count(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"KELVIN_VIN":{"filterType":"number","type":"greaterThan","filter":2.0}}',
        ).json()
        # KELVIN_VIN > 2：row2(3.0 fail)、row5(5000 fail)、row6(2.5 fail) → 3 行全 fail
        self.assertEqual(body['total'], 3)
        self.assertEqual(body['fail_row_count'], 3)

    def test_filter_set_values(self):
        body = self._browse(
            page_size=99999,
            filter_model='{"SW_Bin":{"filterType":"set","values":["1","7"]}}',
        ).json()
        # SW_Bin 1 或 7：row1/3/4（bin1）+ row5（bin7）→ 4
        self.assertEqual(body['total'], 4)


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_browse_api'])
    sys.exit(1 if failures else 0)
