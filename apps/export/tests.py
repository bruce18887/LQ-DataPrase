"""Export 导出测试。

回归目标（2026-08-04）：
- to_excel 万行 × 百列大文件导出耗时（excelize 绑定每值 17μs 转换瓶颈 →
  手写数据区 XML + zip 重打包，实测 35s → 2.1s，断言 30s 留余量）
- fail 行标红 / 数据完整性 / 样式完整性（header/数据区/冻结/筛选）
- 手写 XML 的边界（空 df、纯字符串列、XML 转义、全 fail）
- 向量化值转换与逐值转换逐格等价
- API 端点（to_excel / batch_charts）
"""

import io
import os
import time
import unittest

import pandas as pd
import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser
from apps.analysis.services.statistics import detect_fail_data
from apps.export.export_xlsx_optimized import (
    export_to_xlsx_optimized, _vectorized_native_rows,
)
from apps.export.export_csv import _convert_to_native_type

User = get_user_model()

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'Data', 'SampleData')
CTA8280F_PATH = os.path.join(
    SAMPLE_DATA_DIR, 'CTA8280F',
    'DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_FT_20260420_164504.csv',
)
GAGE_S1_PATH = os.path.join(SAMPLE_DATA_DIR, 'Gage', 'gage_m_S1.csv')


def _empty_metadata():
    return {'units': {}, 'mins': {}, 'maxs': {}, 'format': 'CTA8290D'}


@unittest.skipUnless(
    os.path.exists(CTA8280F_PATH),
    'SampleData/CTA8280F 目录不存在（跳过）',
)
class ToExcelLargeFileTests(TestCase):
    """CTA8280F 大文件（10000 行 × 188 列）导出：耗时 + 样式/完整性。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.df, cls.metadata = get_parser('CTA8280F').parse(CTA8280F_PATH)
        cls.fail_indices, _, _ = detect_fail_data(cls.df, cls.metadata)
        # 3 个用例共享一次导出（套件墙钟 3×导出 → 1×导出）
        t0 = time.monotonic()
        cls.buf = export_to_xlsx_optimized(cls.df, cls.metadata)
        cls.export_time = time.monotonic() - t0

    def _load_ws(self):
        return openpyxl.load_workbook(io.BytesIO(self.buf))['Data']

    def test_export_large_file_within_time_budget(self):
        """万行文件导出应在合理时间内完成（原实现 40s+，手写 XML 后 ~2s）。"""
        self.assertGreater(len(self.buf), 0, '导出字节流不应为空')
        self.assertLess(self.export_time, 30, f'大文件导出耗时 {self.export_time:.1f}s，超过 30s 预算')

    def test_export_fail_rows_highlighted(self):
        """fail 行整行标红、非 fail 行保持默认背景。"""
        ws = self._load_ws()
        data_start_row = 12
        for data_idx in list(self.fail_indices)[:5]:
            fill = ws.cell(data_start_row + data_idx, 2).fill
            self.assertEqual(fill.patternType, 'solid', 'fail 行应有实底填充')
            self.assertEqual(fill.start_color.rgb.upper(), 'FFF5B7B1', 'fail 行应为红底')

    def test_export_data_integrity(self):
        """导出行数与列数、表头正确。"""
        ws = self._load_ws()
        self.assertEqual(ws.max_row, 11 + len(self.df), '表头统计区 11 行 + 全部数据行')
        self.assertEqual(ws.max_column, len(self.df.columns), '列数 = 数据列数（无多余辅助列）')
        self.assertEqual(ws.cell(1, 1).value, self.df.columns[0], '表头应为第一列名')

    def test_export_style_completeness(self):
        """样式完整性：header 深色、统计区/数据区浅灰、冻结与筛选。"""
        ws = self._load_ws()
        self.assertEqual(ws.cell(1, 1).fill.start_color.rgb.upper(), 'FF2C3E50', '表头深色底')
        self.assertEqual(ws.cell(5, 1).fill.start_color.rgb.upper(), 'FFF8F9FA', '统计区浅灰底')
        # 数据区取第一个非 fail 行（fail 行会被红样式覆盖）
        fail_set = set(self.fail_indices)
        non_fail = next(r for r in range(100) if r not in fail_set)
        self.assertEqual(
            ws.cell(12 + non_fail, 1).fill.start_color.rgb.upper(), 'FFF8F9FA',
            '非 fail 数据行应为浅灰底',
        )
        self.assertIsNotNone(ws.freeze_panes, '应存在冻结窗格')
        self.assertIsNotNone(ws.auto_filter.ref, '应存在自动筛选')


@unittest.skipUnless(
    os.path.exists(GAGE_S1_PATH),
    'SampleData/Gage 目录不存在（跳过）',
)
class ToExcelEdgeCaseTests(TestCase):
    """手写 XML 数据区的边界情况（小数据，快）。"""

    def test_empty_df(self):
        """空 df：不崩，仅 11 行统计区。"""
        df = pd.DataFrame(columns=['a', 'b'])
        buf = export_to_xlsx_optimized(df, _empty_metadata())
        ws = openpyxl.load_workbook(io.BytesIO(buf))['Data']
        self.assertEqual(ws.max_row, 11)
        self.assertEqual(ws.max_column, 2)

    def test_single_column_strings_and_escape(self):
        """单列纯字符串 + XML 转义字符读回一致。"""
        df = pd.DataFrame({'text': ['甲', '乙&<c>', '']})
        buf = export_to_xlsx_optimized(df, _empty_metadata())
        ws = openpyxl.load_workbook(io.BytesIO(buf))['Data']
        self.assertEqual(ws.cell(12, 1).value, '甲')
        self.assertEqual(ws.cell(13, 1).value, '乙&<c>', 'XML 转义应读回原始文本')
        self.assertIsNone(ws.cell(14, 1).value, '空字符串应导出为空单元格')

    def test_all_fail_rows_red(self):
        """全 fail 小 df：所有数据行标红。"""
        df = pd.DataFrame({'V1': [1.0, 2.0, 3.0], 'SW_Bin': [5, 6, 7]})
        buf = export_to_xlsx_optimized(df, _empty_metadata())
        ws = openpyxl.load_workbook(io.BytesIO(buf))['Data']
        for r in (12, 13, 14):
            self.assertEqual(ws.cell(r, 1).fill.start_color.rgb.upper(), 'FFF5B7B1')

    def test_vectorized_native_equiv(self):
        """_vectorized_native_rows 与逐值 _convert_to_native_type 逐格等价。"""
        df = pd.DataFrame({
            'i': [1, 2, None],
            'f': [1.5, float('nan'), -0.25],
            'b': [True, False, True],
            's': ['a', '乙&<', None],
            'm': [1, 'x', 3.14],
        })
        rows = _vectorized_native_rows(df)
        expected = [
            [_convert_to_native_type(v) for v in df.iloc[i].tolist()]
            for i in range(len(df))
        ]
        self.assertEqual(rows, expected)


@unittest.skipUnless(
    os.path.exists(GAGE_S1_PATH),
    'SampleData/Gage 目录不存在（跳过）',
)
class ExportApiTests(APITestCase):
    """导出 API 端点测试。"""

    def setUp(self):
        self.user = User.objects.create_user(username='exporter', password='pw')
        self.client.force_authenticate(self.user)
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename='gage_m_S1.csv',
            file_path=GAGE_S1_PATH,
            file_size=os.path.getsize(GAGE_S1_PATH),
            format_type='CTA8290D',
            status='ready',
        )

    def test_to_excel_api(self):
        """POST /export/to_excel/：200 + xlsx 可解析 + 行数列数正确。"""
        resp = self.client.post('/api/v1/export/to_excel/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertIn('attachment', resp['Content-Disposition'])
        df_parsed, _ = get_parser('CTA8290D').parse(GAGE_S1_PATH)
        buf = b''.join(resp.streaming_content)
        ws = openpyxl.load_workbook(io.BytesIO(buf))['Data']
        self.assertEqual(ws.max_row, 11 + len(df_parsed), '数据行数 = 文件行数')
        self.assertEqual(ws.max_column, len(df_parsed.columns))

    def test_batch_charts_api(self):
        """POST /export/batch_charts/：200 + 总览 sheet 行数 = 参数数 + 1。"""
        df_parsed, _ = get_parser('CTA8290D').parse(GAGE_S1_PATH)
        numeric_cols = [c for c in df_parsed.columns if df_parsed[c].dtype in ('int64', 'float64')][:2]
        self.assertGreaterEqual(len(numeric_cols), 2, 'GAGE 数据应至少 2 个数值列')
        resp = self.client.post('/api/v1/export/batch_charts/', {
            'file_id': self.datafile.id,
            'params': numeric_cols,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        buf = b''.join(resp.streaming_content)
        wb = openpyxl.load_workbook(io.BytesIO(buf))
        self.assertEqual(wb['总览'].max_row, 1 + len(numeric_cols), '总览表头 + 每参数一行')

    def test_batch_charts_data_only_bin1(self):
        """POST /export/batch_charts/ + data_only_bin1：200，图表仍按过滤后数据生成。"""
        df_parsed, _ = get_parser('CTA8290D').parse(GAGE_S1_PATH)
        numeric_cols = [c for c in df_parsed.columns if df_parsed[c].dtype in ('int64', 'float64')][:2]
        resp = self.client.post('/api/v1/export/batch_charts/', {
            'file_id': self.datafile.id,
            'params': numeric_cols,
            'data_only_bin1': True,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        buf = b''.join(resp.streaming_content)
        wb = openpyxl.load_workbook(io.BytesIO(buf))
        self.assertEqual(wb['总览'].max_row, 1 + len(numeric_cols), '总览表头 + 每参数一行')

    def test_sigma_limit_data_only_bin1(self):
        """POST /export/sigma_limit/ + data_only_bin1：200 xlsx，不因行过滤崩溃。"""
        resp = self.client.post('/api/v1/export/sigma_limit/', {
            'file_id': self.datafile.id,
            'sigma': 3,
            'data_only_bin1': True,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        buf = b''.join(resp.streaming_content)
        self.assertGreater(len(buf), 0)


def _parse_content_disposition(cd: str) -> str:
    """从 Content-Disposition 提取 RFC 5987 filename*= 或 filename= 的文件名。"""
    import re as _re
    star = _re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", cd)
    if star:
        return _re.sub(r'^"|"$', '', star.group(1).strip()).replace('%20', ' ')
    plain = _re.search(r'filename\s*=\s*"?([^";]+)"?', cd)
    return plain.group(1).strip() if plain else ''


@unittest.skipUnless(
    os.path.exists(GAGE_S1_PATH),
    'SampleData/Gage 目录不存在（跳过）',
)
class ExportFilenameTemplateApiTests(APITestCase):
    """导出文件名自定义模板端到端（设置 → 导出 → Content-Disposition）。"""

    def setUp(self):
        self.user = User.objects.create_user(username='tpluser', password='pw')
        self.client.force_authenticate(self.user)
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename='gage_m_S1.csv',
            file_path=GAGE_S1_PATH,
            file_size=os.path.getsize(GAGE_S1_PATH),
            format_type='CTA8290D',
            status='ready',
        )

    def _set_template(self, key: str, template: str):
        resp = self.client.put('/api/v1/auth/settings/',
                               {'export_filename_templates': {key: template}},
                               format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_to_excel_custom_template_with_datetime(self):
        self._set_template('to_excel', '{filename}_{datetime}')
        resp = self.client.post('/api/v1/export/to_excel/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        name = _parse_content_disposition(resp['Content-Disposition'])
        self.assertRegex(name, r'^gage_m_S1_\d{8}_\d{6}\.xlsx$')

    def test_to_csv_default_template(self):
        resp = self.client.post('/api/v1/export/to_csv/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        name = _parse_content_disposition(resp['Content-Disposition'])
        self.assertEqual(name, 'gage_m_S1_data.csv')

    def test_sigma_limit_sigma_variable(self):
        self._set_template('sigma_limit', '{filename}_{sigma}sigma')
        resp = self.client.post('/api/v1/export/sigma_limit/',
                                {'file_id': self.datafile.id, 'sigma': 6}, format='json')
        self.assertEqual(resp.status_code, 200)
        name = _parse_content_disposition(resp['Content-Disposition'])
        self.assertEqual(name, 'gage_m_S1_6sigma.xlsx')

    def test_batch_charts_both_formats(self):
        self._set_template('batch_charts', '{filename}_charts')
        for fmt in ('xlsx', 'pptx'):
            resp = self.client.post('/api/v1/export/batch_charts/',
                                    {'file_id': self.datafile.id, 'params': [],
                                     'format': fmt}, format='json')
            self.assertEqual(resp.status_code, 200, fmt)
            name = _parse_content_disposition(resp['Content-Disposition'])
            self.assertEqual(name, f'gage_m_S1_charts.{fmt}')

    def test_html_report_chinese_filename_encoded(self):
        """中文源文件名 → FileResponse 自动 RFC 5987 编码（回归：手写 header 会
        UnicodeEncodeError，且会带上 .csv 扩展名）。"""
        self.datafile.filename = '测试_文件.csv'
        self.datafile.save()
        self._set_template('html_report', '{filename}_report')
        resp = self.client.post('/api/v1/export/html_report/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        cd = resp['Content-Disposition']
        self.assertIn("filename*=", cd)
        star = cd.split("filename*=")[1].split("''", 1)[1].split(';')[0].strip()
        import urllib.parse
        decoded = urllib.parse.unquote(star)
        self.assertEqual(decoded, '测试_文件_report.html')

    def test_sanitize_applied_in_response(self):
        self._set_template('to_excel', '{filename}:bad?')
        resp = self.client.post('/api/v1/export/to_excel/', {'file_id': self.datafile.id})
        self.assertEqual(resp.status_code, 200)
        name = _parse_content_disposition(resp['Content-Disposition'])
        self.assertEqual(name, 'gage_m_S1_bad_.xlsx')
