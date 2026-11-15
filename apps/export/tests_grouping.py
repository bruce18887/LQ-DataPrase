"""批量参数分布图分组契约与装箱的 T1 判据。"""

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

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
