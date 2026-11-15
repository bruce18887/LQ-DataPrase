"""批量参数分布图分组契约与装箱的 T1 判据。"""

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.export.export_batch_charts_xlsx import (
    _block_height, _block_image_row, build_batch_charts_xlsx_with_charts,
)
from apps.export.grouping import (
    DEFAULT_MAX_ITEMS_PER_SHEET, GroupingError, normalize_batch_grouping,
)


def _normalize(*args, **kwargs):
    return normalize_batch_grouping(*args, **kwargs)


class NormalizeGroupingTests(SimpleTestCase):
    PARAMS = ['A', 'B', 'C']

    def test_absent_groups_returns_legacy(self):
        self.assertEqual(_normalize(None, None, self.PARAMS), (None, DEFAULT_MAX_ITEMS_PER_SHEET))

    def test_valid_groups_are_trimmed(self):
        groups, max_items = _normalize(
            [{'name': ' LKG ', 'params': ['A']}, {'name': '其他', 'params': ['B', 'C']}],
            None, self.PARAMS)
        self.assertEqual(groups[0], {'name': 'LKG', 'params': ['A']})
        self.assertEqual(max_items, DEFAULT_MAX_ITEMS_PER_SHEET)

    def test_union_must_equal_params(self):
        with self.assertRaises(GroupingError) as ctx:
            _normalize([{'name': 'A', 'params': ['A']}], None, self.PARAMS)
        self.assertEqual((ctx.exception.code, ctx.exception.field), ('invalid_groups', 'groups'))

    def test_duplicate_within_group_rejected(self):
        with self.assertRaises(GroupingError):
            _normalize([{'name': 'A', 'params': ['A', 'A', 'B', 'C']}], None, self.PARAMS)

    def test_unknown_param_rejected(self):
        with self.assertRaises(GroupingError):
            _normalize([{'name': 'A', 'params': ['A', 'B', 'C', 'X']}], None, self.PARAMS)

    def test_bad_page_size_rejected(self):
        for bad in (20, '50', True):
            with self.assertRaises(GroupingError) as ctx:
                _normalize([{'name': 'A', 'params': ['A', 'B', 'C']}], bad, self.PARAMS)
            self.assertEqual((ctx.exception.code, ctx.exception.field),
                             ('invalid_page_size', 'max_items_per_sheet'))

    def test_pptx_with_groups_rejected(self):
        with self.assertRaises(GroupingError) as ctx:
            _normalize([{'name': 'A', 'params': ['A', 'B', 'C']}], 50, self.PARAMS, 'pptx')
        self.assertEqual((ctx.exception.code, ctx.exception.field),
                         ('groups_not_supported', 'groups'))

    def test_multi_assign_allowed_across_groups(self):
        groups, _ = _normalize(
            [{'name': 'A', 'params': ['A', 'B']}, {'name': 'B', 'params': ['A', 'C']}],
            None, self.PARAMS)
        self.assertEqual([g['params'] for g in groups], [['A', 'B'], ['A', 'C']])


class BlockLayoutTests(SimpleTestCase):
    """块布局的行距公式，以及「S=1 时版式与重构前逐字一致」的不变量。"""

    PARAMS = ['P00', 'P01', 'P02']

    def _build(self, **kwargs):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({p: rng.normal(10, 1, 40) for p in self.PARAMS})
        metadata = {
            'units': {p: 'V' for p in self.PARAMS},
            'mins': {p: '0' for p in self.PARAMS},
            'maxs': {p: '20' for p in self.PARAMS},
            'format': 'CTA8290D',
        }
        return build_batch_charts_xlsx_with_charts(
            df, metadata, self.PARAMS, dpi=72, workers=1, **kwargs)

    def test_block_math(self):
        self.assertEqual(_block_height({}), 32)
        self.assertEqual(_block_height({'site_stats': [{}] * 3}), 32)
        self.assertEqual(_block_height({'site_stats': [{}] * 10}), 37)
        self.assertEqual(_block_image_row(1, 0), 9)
        self.assertEqual(_block_image_row(1, 10), 14)
        self.assertEqual(_block_image_row(33, 0), 41)

    def test_legacy_sheet_layout_unchanged(self):
        from openpyxl import load_workbook
        import io
        wb = load_workbook(io.BytesIO(self._build()))
        self.assertEqual(wb.sheetnames, ['总览', 'P00', 'P01', 'P02'])
        ws = wb['P00']
        self.assertEqual(ws.cell(1, 1).value, '统计项')
        self.assertEqual(ws.cell(2, 1).value, 'P00')
        self.assertEqual(ws.cell(8, 5).value, '← 返回总览')
        self.assertEqual(len(ws._images), 1)
        # 总览链接仍指向 A1
        self.assertEqual(wb['总览'].cell(2, 2).hyperlink.target, "#'P00'!A1")
