"""批量参数分布图 xlsx：工作表命名与总览超链接的完整性判据（T1）。

存量缺陷（2026-11-15 实测）：

* 参数名含 Excel 非法字符（如 ``VTH_MOS[V]``）→ ``create_sheet`` 抛 ValueError
  → 落到 ``Chart_N``，而总览超链接仍按原名拼 → 点开断链；
* 长参数名截断后相同 → openpyxl 自动去重成 ``name1``，但两条超链接都指向
  第一张 → 点错图。

修复口径：先统一分配唯一 sheet 名，再用同一份映射写总览链接与建明细表。
命名规则与权重导出共用 ``apps.common.sheet_names``。
"""

import io
import re

import numpy as np
import pandas as pd
from django.test import SimpleTestCase
from openpyxl import load_workbook

from apps.common.sheet_names import clean_sheet_name, unique_sheet_names
from apps.export.export_batch_charts_xlsx import build_batch_charts_xlsx_with_charts

INVALID = re.compile(r"[\\/*?:\[\]']")


def _build(params):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({p: rng.normal(10, 1, 60) for p in params})
    metadata = {
        'units': {p: 'V' for p in params},
        'mins': {p: '0' for p in params},
        'maxs': {p: '20' for p in params},
        'format': 'CTA8290D',
    }
    return build_batch_charts_xlsx_with_charts(
        df, metadata, params, site_col=None, dpi=72, workers=1)


class SheetNameRulesTests(SimpleTestCase):
    def test_invalid_chars_replaced(self):
        names = unique_sheet_names(['VTH_MOS[V]', 'A*B?C:D', 'E/F\\G', "O'Brien"])
        for name in names:
            self.assertIsNone(INVALID.search(name), name)

    def test_long_names_collide_but_stay_unique_and_bounded(self):
        base = 'PARAMETER_NAME_ABCDEFGHIJKLMNOPQRSTUVWXYZ_'
        names = unique_sheet_names([base + '001', base + '002'])
        self.assertEqual(len({n.lower() for n in names}), 2)
        self.assertTrue(all(len(n) <= 31 for n in names), names)

    def test_case_insensitive_dedup(self):
        names = unique_sheet_names(['Abc', 'abc'])
        self.assertNotEqual(names[0].lower(), names[1].lower())

    def test_reserved_names_not_stolen(self):
        names = unique_sheet_names(['总览', 'History'])
        lowered = {n.lower() for n in names}
        self.assertNotIn('总览', lowered)
        self.assertNotIn('history', lowered)

    def test_empty_name_fallback(self):
        self.assertEqual(clean_sheet_name('   '), '测试项')


class SummaryLinkIntegrityTests(SimpleTestCase):
    PARAMS = [
        'VTH_MOS[V]',
        'LONG_PARAMETER_NAME_ABCDEFGHIJKLMN_001',
        'LONG_PARAMETER_NAME_ABCDEFGHIJKLMN_002',
        '总览',
        'NORMAL',
    ]

    def test_every_link_points_to_its_own_sheet(self):
        wb = load_workbook(io.BytesIO(_build(self.PARAMS)))
        self.assertEqual(wb.sheetnames[0], '总览')
        lowered = [s.lower() for s in wb.sheetnames]
        self.assertEqual(len(lowered), len(set(lowered)),
                         f'sheet 名必须大小写不敏感唯一：{wb.sheetnames}')
        self.assertFalse([s for s in wb.sheetnames if s.startswith('Chart_')],
                         f'不得出现 Chart_N 兜底表：{wb.sheetnames}')

        ws = wb['总览']
        for row in range(2, 2 + len(self.PARAMS)):
            param = ws.cell(row=row, column=2).value
            hyperlink = ws.cell(row=row, column=2).hyperlink
            self.assertIsNotNone(hyperlink, f'{param} 缺少超链接')
            target = hyperlink.target
            self.assertTrue(target.endswith("'!A1"), target)
            sheet = target[2:].rsplit("'!", 1)[0]
            self.assertIn(sheet, wb.sheetnames, f'{param} 的链接目标不存在：{target}')
            self.assertEqual(
                wb[sheet].cell(row=2, column=1).value, param,
                f'{param} 的链接指向了别的参数的 sheet：{sheet}')
