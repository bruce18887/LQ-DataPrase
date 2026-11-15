"""批量参数分布图分组契约与装箱的 T1 判据。"""

import re

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

    def _metadata(self):
        return {
            'units': {p: 'V' for p in self.PARAMS},
            'mins': {p: '0' for p in self.PARAMS},
            'maxs': {p: '20' for p in self.PARAMS},
            'format': 'CTA8290D',
        }

    def _build(self, **kwargs):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({p: rng.normal(10, 1, 40) for p in self.PARAMS})
        return build_batch_charts_xlsx_with_charts(
            df, self._metadata(), self.PARAMS, dpi=72, workers=1, **kwargs)

    def _build_with_site(self):
        """带 Site 列的一档：3 个 site 值（[1,1,2,2,3,3] 重复两轮 = 12 行）。"""
        rng = np.random.default_rng(0)
        df = pd.DataFrame({p: rng.normal(10, 1, 12) for p in self.PARAMS})
        df['Site'] = [1, 1, 2, 2, 3, 3] * 2
        return build_batch_charts_xlsx_with_charts(
            df, self._metadata(), self.PARAMS, site_col='Site', dpi=72, workers=1)

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

    def test_site_branch_layout_rows_and_anchor(self):
        """有 Site 行时的块版式：Site 表 6–10 列、数据行 S+2+i、图锚点在其下方。

        这是重构里唯一改了公式形状的分支（旧 ``max(9, n+4)`` ↔ 新 ``S + max(8, n+3)``），
        无 Site 用例钉不到它：只在本分支才写的第 6 列与 ``A{锚点行}`` 此前全无所指。
        """
        from openpyxl import load_workbook
        import io
        wb = load_workbook(io.BytesIO(self._build_with_site()))
        ws = wb['P00']

        # Site 表：S 行第 6 列是横幅表头，S+1 行起是列头，S+2+i 是数据行。
        # compute_site_stats 每个 site 一行后再追加 'ALL Site'：3 个 site → 4 行。
        self.assertEqual(ws.cell(1, 6).value, 'Site统计')
        self.assertEqual(ws.cell(2, 6).value, 'Site')
        self.assertEqual(ws.cell(3, 6).value, 'Site1')      # 第一条 site 数据（site 值 1）
        self.assertEqual(ws.cell(6, 6).value, 'ALL Site')   # 数据块末行 = S+2+3

        # 左侧统计沿用无 Site 用例的版式（代表两条：参数行与首个标签）
        self.assertEqual(ws.cell(2, 1).value, 'P00')
        self.assertEqual(ws.cell(4, 1).value, 'Mean')

        self.assertEqual(ws.cell(8, 5).value, '← 返回总览')

        self.assertEqual(len(ws._images), 1)
        # openpyxl 无公开的锚点行读数；OneCellAnchor._from 是 0-based AnchorMarker
        anchor = ws._images[0].anchor._from
        self.assertEqual(anchor.col + 1, 1)                 # A 列
        self.assertEqual(anchor.row + 1, _block_image_row(1, 3))
        # 字面钉住：公式若退回 max(9, …) 一类形状则锚点漂到 10 行，这里立刻红
        self.assertEqual(anchor.row + 1, 9)


class GroupedLayoutTests(SimpleTestCase):
    """分组装配：sheet 装箱、总览分类列、每参数精确锚点、多属重复嵌入。"""

    PARAMS = ['P00', 'P01', 'P02', 'P03', 'P04']

    def _build(self, groups, max_items=50, params=None):
        # params 默认取全量；只测部分参数时显式收窄，否则未覆盖的参数会被
        # _plan_pages 兜底塞进「其他」页，多出预期之外的块。
        params = list(params or self.PARAMS)
        rng = np.random.default_rng(0)
        df = pd.DataFrame({p: rng.normal(10, 1, 40) for p in params})
        metadata = {
            'units': {p: 'V' for p in params},
            'mins': {p: '0' for p in params},
            'maxs': {p: '20' for p in params},
            'format': 'CTA8290D',
        }
        return build_batch_charts_xlsx_with_charts(
            df, metadata, params, dpi=72, workers=1,
            groups=groups, max_items_per_sheet=max_items)

    @staticmethod
    def _wb(payload):
        import io
        from openpyxl import load_workbook
        return load_workbook(io.BytesIO(payload))

    def test_groups_sheets_links_and_category_column(self):
        wb = self._wb(self._build([
            {'name': 'A', 'params': ['P00', 'P01']},
            {'name': 'B', 'params': ['P02', 'P03', 'P04']},
        ]))
        self.assertEqual(wb.sheetnames, ['总览', 'A', 'B'])
        summary = wb['总览']
        self.assertEqual(summary.cell(1, 3).value, '分类')
        self.assertEqual([summary.cell(r, 3).value for r in range(2, 7)], ['A', 'A', 'B', 'B', 'B'])
        self.assertEqual(summary.cell(2, 2).hyperlink.target, "#'A'!A1")
        # 无 Site → 块高 32：第二块从第 33 行开始
        self.assertEqual(summary.cell(3, 2).hyperlink.target, "#'A'!A33")
        self.assertEqual(summary.cell(4, 2).hyperlink.target, "#'B'!A1")
        self.assertEqual(wb['A'].cell(2, 1).value, 'P00')
        self.assertEqual(wb['A'].cell(34, 1).value, 'P01')
        self.assertEqual(wb['B'].cell(2, 1).value, 'P02')

    def test_page_cap_packs_full_pages_not_even_split(self):
        groups = [{'name': 'G', 'params': self.PARAMS}]
        wb = self._wb(self._build(groups, max_items=2))
        self.assertEqual(wb.sheetnames, ['总览', 'G_1', 'G_2', 'G_3'])
        summary = wb['总览']
        # 第 3 个参数 P02 落在 G_2 的第一块
        self.assertEqual(summary.cell(4, 2).hyperlink.target, "#'G_2'!A1")

    def test_illegal_and_overlong_group_names_yield_valid_sheets_and_links(self):
        """分类名含 Excel 非法字符/超长时：sheet 名仍合法唯一，总览链接仍指向真实块。

        `A[]:*?/\\B'` 与 40 字分类名是用户的正常输入，不是攻击样本。建表与链接
        必须同源（同一份 `unique_sheet_names` 映射），否则会断链到不存在的表、
        或两个分类经清洗后互指（2026-11-15 实测过的两类事故）。
        """
        long_name = 'G' * 40
        wb = self._wb(self._build([
            {'name': "A[]:*?/\\B'", 'params': ['P00', 'P01']},
            {'name': long_name, 'params': ['P02', 'P03', 'P04']},
        ]))

        # 1) 所有 sheet 名合法：≤31 字符、无 Excel 禁用字符、大小写不敏感唯一
        illegal = set("[]:*?/\\'")
        for name in wb.sheetnames:
            self.assertLessEqual(len(name), 31, f'sheet 名超过 31 字符: {name!r}')
            self.assertFalse(illegal & set(name), f'sheet 名含 Excel 禁用字符: {name!r}')
        lowered = [name.lower() for name in wb.sheetnames]
        self.assertEqual(len(lowered), len(set(lowered)),
                         f'sheet 名必须大小写不敏感唯一: {wb.sheetnames}')

        # 2) 总览每条链接的目标表存在，且块起始行下方那行第 1 列就是该参数名
        #    （A<S> 是「统计项」表头，参数名在 S+1 —— 见 §7.2 块布局）
        summary = wb['总览']
        for row in range(2, 2 + len(self.PARAMS)):
            cell = summary.cell(row, 2)
            match = re.match(r"^#'(.+)'!A(\d+)$", cell.hyperlink.target or '')
            self.assertIsNotNone(match, f'链接形状异常: {cell.hyperlink.target!r}')
            sheet_name, anchor_row = match.group(1), int(match.group(2))
            self.assertIn(sheet_name, wb.sheetnames, '总览链接必须指向实际建出的表')
            self.assertEqual(wb[sheet_name].cell(anchor_row, 1).value, '统计项',
                             '链接的块起始行必须是该参数块的统计表头')
            self.assertEqual(wb[sheet_name].cell(anchor_row + 1, 1).value, cell.value,
                             '链接的块起始行必须落在该参数的块首')

    def test_multi_assign_embeds_block_twice_and_links_first(self):
        wb = self._wb(self._build([
            {'name': 'A', 'params': ['P00', 'P01']},
            {'name': 'B', 'params': ['P00', 'P02']},
        ]))
        summary = wb['总览']
        self.assertEqual(summary.cell(2, 3).value, 'A / B')
        self.assertEqual(summary.cell(2, 2).hyperlink.target, "#'A'!A1")
        self.assertEqual(wb['B'].cell(2, 1).value, 'P00')
        self.assertEqual(len(wb['A']._images), 2)
        self.assertEqual(len(wb['B']._images), 2)

    def test_multi_assign_renders_each_param_once(self):
        """多属参数只渲染一次 PNG（spec §6.2「同一张图只渲染一次」）。

        A 组 3 块 + B 组 2 块 = 5 次块出现，唯一参数 3 个 → 应只渲染 3 次。
        ``workers=1`` 时 ``_render_chart_pngs`` 返回空 dict，串行兜底是唯一渲染
        入口，用 spy 计数即可钉住「不重复渲染」；嵌图次数不受缓存影响。
        """
        from unittest.mock import patch

        from apps.export import export_batch_charts_xlsx as mod

        with patch.object(mod, '_create_histogram_chart',
                          wraps=mod._create_histogram_chart) as spy:
            wb = self._wb(self._build([
                {'name': 'A', 'params': ['P00', 'P01', 'P02']},
                {'name': 'B', 'params': ['P00', 'P01']},
            ], params=['P00', 'P01', 'P02']))
        # 5 次块出现全部落表（缓存只省渲染，不省嵌图）
        self.assertEqual(len(wb['A']._images), 3)
        self.assertEqual(len(wb['B']._images), 2)
        self.assertEqual(spy.call_count, 3,
                         f'3 个唯一参数应只渲染 3 次，实得 {spy.call_count}')
