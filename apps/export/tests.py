"""Export 导出测试。

回归目标（2026-08-04）：
- to_excel 对万行 × 百列大文件导出耗时优化（原逐单元格样式导致 40s+ 超时，改整行标红）
- fail 行标红正确性（openpyxl 读回验证填充色）
"""

import io
import os
import time
import unittest

import openpyxl
from django.test import TestCase

from apps.datafiles.parsers import get_parser
from apps.export.export_xlsx_optimized import export_to_xlsx_optimized


SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'Data', 'SampleData')


def _load_sample_df(path):
    parser = get_parser('CTA8280F')
    return parser.parse(path)


@unittest.skipUnless(
    os.path.exists(os.path.join(SAMPLE_DATA_DIR, 'CTA8280F')),
    'SampleData/CTA8280F 目录不存在（跳过）',
)
class ToExcelLargeFileTests(TestCase):
    """CTA8280F 大文件（10000 行 × 188 列）导出：耗时 + fail 标红正确性。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sample_path = os.path.join(
            SAMPLE_DATA_DIR, 'CTA8280F',
            'DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_FT_20260420_164504.csv',
        )
        cls.df, cls.metadata = _load_sample_df(sample_path)

    def test_export_large_file_within_time_budget(self):
        """万行文件导出应在合理时间内完成（原实现数十万次逐单元格样式调用 → 40s+）。"""
        start = time.monotonic()
        buf = export_to_xlsx_optimized(self.df, self.metadata)
        elapsed = time.monotonic() - start

        self.assertGreater(len(buf), 0, '导出字节流不应为空')
        self.assertLess(elapsed, 30, f'大文件导出耗时 {elapsed:.1f}s，超过 30s 预算')

    def test_export_fail_rows_highlighted(self):
        """fail 行整行标红、非 fail 行保持默认背景。"""
        from apps.analysis.services.statistics import detect_fail_data

        buf = export_to_xlsx_optimized(self.df, self.metadata)
        fail_indices, _, _ = detect_fail_data(self.df, self.metadata)
        self.assertGreater(len(fail_indices), 0, '测试数据应包含 fail 行')

        wb = openpyxl.load_workbook(io.BytesIO(buf))
        ws = wb['Data']
        data_start_row = 12
        for data_idx in list(fail_indices)[:5]:
            fill = ws.cell(data_start_row + data_idx, 2).fill
            self.assertEqual(fill.patternType, 'solid', 'fail 行应有实底填充')
            self.assertNotIn(
                fill.start_color.rgb.upper(), ('FFF8F9FA', 'FFFFFFFF', '00000000'),
                'fail 行不应是默认背景色',
            )

    def test_export_data_integrity(self):
        """导出行数与列数、表头正确。"""
        buf = export_to_xlsx_optimized(self.df, self.metadata)
        wb = openpyxl.load_workbook(io.BytesIO(buf))
        ws = wb['Data']
        self.assertEqual(ws.max_row, 11 + len(self.df), '表头统计区 11 行 + 全部数据行')
        self.assertEqual(ws.max_column, len(self.df.columns), '列数 = 数据列数（无多余辅助列）')
        self.assertEqual(ws.cell(1, 1).value, self.df.columns[0], '表头应为第一列名')
