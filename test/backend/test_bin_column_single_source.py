"""Bin 列名单一来源护栏（架构评审 P1-4）。

``get_bin_column_name`` 曾有 6 份实现：``statistics/helpers.py`` 的查表函数 + 5 个
parser 的静态方法（base/cta8280f/cta8290d 各写 ``'SW_Bin'``、ets88 写 ``'Bin'``、
sts8200 写 ``'SOFT_BIN'``）。Bin 列名同时被解析、统计、导出、看板消费，是跨模块契约，
多份字面量必然漂移（lessons 2026-09-19「同一个数值的三份字面量必然漂移」）。

现在只剩 ``BIN_COLUMN_MAPPING`` 一处，本用例扫描源码把三件事钉住：
parsers 里不得再出现同名方法、登记表覆盖每个注册格式、表值与该格式的真实表头列一致。
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

from apps.analysis.services.statistics.helpers import (
    BIN_COLUMN_MAPPING,
    get_bin_column_name,
)
from apps.datafiles.parsers import PARSER_REGISTRY
from apps.datafiles.parsers.base import SYSTEM_COLUMNS

PARSERS_DIR = Path(__file__).resolve().parents[2] / 'apps' / 'datafiles' / 'parsers'


class BinColumnSingleSourceTests(SimpleTestCase):
    """Bin 列名只能由 ``BIN_COLUMN_MAPPING`` 提供。"""

    def test_parsers_declare_no_bin_column_method(self):
        """parser 不得自带 get_bin_column_name（改动前这条必红：5 份字面量都在 parsers 里）。"""
        pattern = re.compile(r'\bget_bin_column_name\b')
        offenders = []
        for path in sorted(PARSERS_DIR.glob('*.py')):
            for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f'{path.name}:{lineno}')
        self.assertEqual(
            offenders, [],
            'Bin 列名只在 apps/analysis/services/statistics/helpers.py 的 '
            'BIN_COLUMN_MAPPING 里声明，parser 不得再写一份')

    def test_registry_is_fully_covered(self):
        """新增机台格式必须同时补登记表，否则会静默走 SW_Bin 兜底。"""
        missing = [fmt for fmt in PARSER_REGISTRY if fmt not in BIN_COLUMN_MAPPING]
        self.assertEqual(missing, [], f'PARSER_REGISTRY 中的格式缺少 Bin 列名: {missing}')

    def test_mapping_matches_each_formats_header_columns(self):
        """表值必须与该格式自己的系统列表头一致（两份独立声明交叉验证）。"""
        for fmt, expected in sorted(BIN_COLUMN_MAPPING.items()):
            header_cols = SYSTEM_COLUMNS.get(fmt)
            self.assertIsNotNone(header_cols, f'{fmt} 缺少 SYSTEM_COLUMNS 定义')
            self.assertIn(
                expected, header_cols,
                f'{fmt} 的 Bin 列 {expected!r} 不在其表头列中：系统列写错了，'
                f'还是 BIN_COLUMN_MAPPING 写错了？')

    def test_browse_payload_uses_the_table(self):
        """datafiles 侧曾调 parser.get_bin_column_name()，现在必须查同一张表。"""
        source = (PARSERS_DIR.parent / 'views' / 'browse_views.py').read_text(
            encoding='utf-8')
        self.assertIn('get_bin_column_name(datafile.format_type)', source)
        self.assertNotIn('parser.get_bin_column_name', source)

    def test_unknown_format_falls_back_to_sw_bin(self):
        """未知格式不得抛错（文件浏览要能继续），兜底值要显式钉住。"""
        self.assertEqual(get_bin_column_name('NOT_A_FORMAT'), 'SW_Bin')
        self.assertEqual(get_bin_column_name(''), 'SW_Bin')
