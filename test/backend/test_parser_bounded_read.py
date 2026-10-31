"""BaseAteCsvParser 有界读取的等价与分配峰值判据（H2）。

旧实现 ``f.readlines()`` 把整只 CSV 读成 Python 字符串列表，随后
``pd.read_csv`` 再把整文件读第二遍——大文件上两份全量同时驻留。新实现只
保留「前 80 个物理行」+「marker 行及其后 max(offset) 行」，marker 语义与
找不到 marker 时返回 ``(None, None)`` 的既有契约不变。

等价的判据分两层：

* 四种格式（CTA8290D / CTA8280F / STS8200 走基类，ETS88 走自己的解析器）
  在共享的富夹具上与冻结的 DataFrame / metadata 逐字段相等；
* 头部元数据助手必须收到**前 min(80, 总行数) 个物理行**——不是「marker
  之前的行」，也不是更少。这里用 spy 直接钉住传给三个助手的列表，因为
  旧行为传的是整文件、而助手只扫前 80 行；把有界读取写成「读到 marker
  为止」会让第 80 行窗口缩水，是本次改动最主要的等价陷阱。

峰值口径（与计划正文的偏差及理由）：计划写「用 ``apps/common/memory.py``
的既有采集」，但该模块只有时点采样（``process_private_bytes`` /
``system_memory_snapshot`` / ``memory_snapshot``），**没有峰值收集器**；
在单测里断言进程 RSS 差值只会是机器负载噪音。这里改用标准库
``tracemalloc`` 量 Python 分配峰值（确定性、无 ctypes、不碰进程 RSS）。
pandas 3 的 ``read_csv`` 自身会把整文件读进 Python 缓冲区（本机实测约
1.8× 文件体积），所以「早 marker」用例量的是 parse 峰值减去同参数
``read_csv`` 基线——即本次改动真正控制的「头部读取额外分配」。夹具数据区
只放数值列，且测量前先 warm up 一次，避免首次解析的内部对象抬高基线。
"""

import gc
import inspect
import os
import tempfile
import tracemalloc
import unittest

import pandas as pd
from django.test import SimpleTestCase
from pandas.testing import assert_frame_equal

from apps.datafiles.parsers.base import HEADER_KEEP
from apps.datafiles.parsers.cta8280f import CTA8280FParser
from apps.datafiles.parsers.cta8290d import CTA8290DParser
from apps.datafiles.parsers.ets88 import ETS88Parser
from apps.datafiles.parsers.sts8200 import STS8200Parser

NAN = float('nan')

FILLER_ROWS = 70
CTA_FILLER = [f'{100 + i},F{i},1,1.0,2.0,3.0,4.0' for i in range(FILLER_ROWS)]
F8280_FILLER = [
    f'{100 + i},{100 + i},{1000 + i},1,1.0,2.0,3.0,4.0'
    for i in range(FILLER_ROWS)
]
STS_FILLER = [
    f'{100 + i},F{i},1,1,0.5,1.0,2.0,3.0' for i in range(FILLER_ROWS)
]

ETS_TEST_COLUMNS = [f'T{i}' for i in range(55)]
ETS_COLUMNS = ['Site #', 'Serial #', 'Bin', 'XCoord', 'YCoord'] + ETS_TEST_COLUMNS


# ── 共享富夹具 ──────────────────────────────────────────────────────

def cta8290d_text():
    lines = [
        'TestFile,/opt/programs/rich_program.pgs',
        'LotID,LOT-RICH',
        'Operator,alice',
        'Station,ST-RICH',
        'Device_Name,DEV-RICH',
        'Tester_Type,T1',
        'TestType,FT',
        'AllTestTime,12.5',
        'HandlerName,H-RICH',
        'StartTime,2026-01-01 10:00:00',
        'EndTime,2026-01-01 10:05:00',
        '[Data]',
        'Serial_No,Part_No,Site_No,V1,V2,V3,V1',
        ',,,V,A,,mV',
        ',,,0,0,,0',
        ',,,10,5,,100',
        '1,P1,1,1.0,2.0,3.0,4.0',
        '2,P2,1,1.5-,2.5,abc,5.0',
        '3,,2,,3.0,,6.0',
        '4,P4,2,-2.25,4.5,7.0,8.0',
        ',5,1,5.0,,9.0,10.0',
        '6,P6,1,0,1.0,2.0,3.0',
        '7,P7,2,1e3,1E-2,0.0,1.0',
        '8,P8,1,10.0,5.0,3.0,4.0',
    ]
    return '\n'.join(lines + CTA_FILLER) + '\n'


def cta8280f_text():
    lines = [
        'TestFileName,/opt/programs/rich_program2.pgs',
        'LotID,LOT-RICH2',
        'Operator,bob',
        'Test Station,ST-RICH2',
        'Device Name,DEV-RICH2',
        'Tester type,T2',
        'TestType,FT',
        'AllTestTime,11.5',
        'HandlerType,H-RICH2',
        'StartTime,2026-01-02 11:00:00',
        'EndTime,2026-01-02 11:05:00',
        '[Data]',
        'Index_No,Dut_No,Serial_No,Site_No,V1,V2,V3,V1',
        ',,,,V,A,,mV',
        ',,,,0,0,,0',
        ',,,,10,5,,100',
        '0,1,100,1,1.0,2.0,3.0,4.0',
        '1,2,101,1,1.5-,2.5,abc,5.0',
        '2,3,,2,,3.0,,6.0',
        '3,4,103,2,-2.25,4.5,7.0,8.0',
        '4,5,104,1,5.0,,9.0,10.0',
        '5,6,105,1,0,1.0,2.0,3.0',
        '6,7,106,2,1e3,1E-2,0.0,1.0',
        '7,8,107,1,10.0,5.0,3.0,4.0',
    ]
    return '\n'.join(lines + F8280_FILLER) + '\n'


def sts8200_text():
    lines = [
        'STS8200-43 StationA',
        'Beginning Time: 2026-01-03 09:00:00',
        'Ending Time: 2026-01-03 09:05:00',
        'LOT_ID: LOT-C',
        'User: carol',
        'Total Testing Time: 9.5',
        'Handler: H3',
        'Program: /remote/path/JAVBN281R3CYCAAV1.6.pgs',
        'SITE_NUM,PART_ID,PASSFG,SOFT_BIN,T_TIME,TestA,TestB,TestA',
        ',,,,ms,V,V,V',
        ',,,,0,0,0,0',
        ',,,,10,5,5,10',
        '# end of limits',
        '1,P1,1,1,0.1,1.5,2.5,3.5',
        '2,P2,1,1,0.2,1.5-,abc,4.5',
        '3,,1,1,0.3,,2.5,5.5',
        '4,P4,2,9,0.4,-2.25,3.5,6.5',
        '5,P5,1,1,,5.0,,7.5',
        '6,P6,1,1,0.6,0,1.0,8.5',
        '7,P7,1,1,0.7,1e3,1E-2,9.5',
        '8,P8,1,1,0.8,10.0,5.0,1.0',
    ]
    return '\n'.join(lines + STS_FILLER) + '\n'


def ets88_text():
    header_names = ['Test Name', '', '', '', ''] + ETS_TEST_COLUMNS
    units = ['Units', '', '', '', ''] + ['V'] * 55
    lows = ['Lower Limit', '', '', '', ''] + ['0'] * 55
    highs = ['Upper Limit', '', '', '', ''] + ['10'] * 55
    marker = ['Site #', 'Serial #', 'Bin', 'XCoord', 'YCoord']
    rows = []
    for r in range(3):
        values = [str(r + 1), f'S{r + 1}', str(1 + r), '10.5', '20.5']
        values += [f'{r}.{i}' for i in range(55)]
        rows.append(','.join(values))
    # 后置负号：旧行为在 str/object 列上走 fix_negative_decimal（T0 第二行）
    rows[1] = rows[1].replace('1.0,', '1.0-,', 1)
    lines = [
        'Data Sheet File,/opt/programs/ets_program.pgs',
        'Datalog for Lot Number,LOT-E',
        'Data collected by operator,eve',
        'Data collected on station,ST-E',
        'Tester_ID,T-E',
        'Data collection type,FT',
        'Handler/Prober ID,H-E',
        ','.join(header_names),
        ','.join(units),
        ','.join(lows),
        ','.join(highs),
        ','.join(marker),
    ]
    tail = [
        'Data Collection Start Date,01/05/2026 08:00:00',
        'Data Collection Stop  Date,01/05/2026 08:05:00',
    ]
    return '\n'.join(lines + rows + tail) + '\n'


# ── 冻结的期望值（改前实跑快照） ────────────────────────────────────

def cta8290d_expected():
    return pd.DataFrame({
        'Serial_No': [1.0, 2.0, 3.0, 4.0, NAN, 6.0, 7.0, 8.0]
        + [float(100 + i) for i in range(FILLER_ROWS)],
        'Part_No': ['P1', 'P2', None, 'P4', '5', 'P6', 'P7', 'P8']
        + [f'F{i}' for i in range(FILLER_ROWS)],
        'Site_No': [1, 1, 2, 2, 1, 1, 2, 1] + [1] * FILLER_ROWS,
        'V1': ['1.0', '1.5-', None, '-2.25', '5.0', '0', '1e3', '10.0']
        + ['1.0'] * FILLER_ROWS,
        'V2': [2.0, 2.5, 3.0, 4.5, None, 1.0, 0.01, 5.0] + [2.0] * FILLER_ROWS,
        'V3': ['3.0', 'abc', None, '7.0', '9.0', '2.0', '0.0', '3.0']
        + ['3.0'] * FILLER_ROWS,
        'V1.1': [4.0, 5.0, 6.0, 8.0, 10.0, 3.0, 1.0, 4.0]
        + [4.0] * FILLER_ROWS,
    })


def cta8280f_expected():
    return pd.DataFrame({
        'Index_No': list(range(8)) + [100 + i for i in range(FILLER_ROWS)],
        'Dut_No': list(range(1, 9)) + [100 + i for i in range(FILLER_ROWS)],
        'Serial_No': [100, 101, None, 103, 104, 105, 106, 107]
        + [1000 + i for i in range(FILLER_ROWS)],
        'Site_No': [1, 1, 2, 2, 1, 1, 2, 1] + [1] * FILLER_ROWS,
        'V1': ['1.0', '1.5-', None, '-2.25', '5.0', '0', '1e3', '10.0']
        + ['1.0'] * FILLER_ROWS,
        'V2': [2.0, 2.5, 3.0, 4.5, None, 1.0, 0.01, 5.0] + [2.0] * FILLER_ROWS,
        'V3': ['3.0', 'abc', None, '7.0', '9.0', '2.0', '0.0', '3.0']
        + ['3.0'] * FILLER_ROWS,
        'V1.1': [4.0, 5.0, 6.0, 8.0, 10.0, 3.0, 1.0, 4.0]
        + [4.0] * FILLER_ROWS,
    })


def sts8200_expected():
    return pd.DataFrame({
        'SITE_NUM': list(range(1, 9)) + [100 + i for i in range(FILLER_ROWS)],
        'PART_ID': ['P1', 'P2', None, 'P4', 'P5', 'P6', 'P7', 'P8']
        + [f'F{i}' for i in range(FILLER_ROWS)],
        'PASSFG': [1, 1, 1, 2, 1, 1, 1, 1] + [1] * FILLER_ROWS,
        'SOFT_BIN': [1, 1, 1, 9, 1, 1, 1, 1] + [1] * FILLER_ROWS,
        'T_TIME': [0.1, 0.2, 0.3, 0.4, None, 0.6, 0.7, 0.8]
        + [0.5] * FILLER_ROWS,
        'TestA': ['1.5', '1.5-', None, '-2.25', '5.0', '0', '1e3', '10.0']
        + ['1.0'] * FILLER_ROWS,
        'TestB': ['2.5', 'abc', '2.5', '3.5', None, '1.0', '1E-2', '5.0']
        + ['2.0'] * FILLER_ROWS,
        'TestA.1': [3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 1.0]
        + [3.0] * FILLER_ROWS,
    })


def ets88_expected():
    data = {
        'Site #': ['1', '2', '3'],
        'Serial #': ['S1', 'S2', 'S3'],
        'Bin': [1.0, 2.0, 3.0],
        'XCoord': [10.5, 10.5, 10.5],
        'YCoord': [20.5, 20.5, 20.5],
        'T0': ['0.0', '1.0-', '2.0'],
    }
    for i in range(1, 55):
        data[f'T{i}'] = [float(f'{r}.{i}') for r in range(3)]
    return pd.DataFrame(data)[ETS_COLUMNS]


def _ets_meta(pairs):
    """ETS88 的 units/mins/maxs 都按列序 zip；这里按同一列序构造。"""
    return dict(zip(ETS_COLUMNS, pairs))


def base_meta(**overrides):
    meta = {
        'format': overrides.pop('format'),
        'program_name': overrides.pop('program_name'),
        'units': overrides.pop('units'),
        'mins': overrides.pop('mins'),
        'maxs': overrides.pop('maxs'),
    }
    meta.update(overrides)
    return meta


def cta8290d_meta():
    return base_meta(
        format='CTA8290D',
        program_name='rich_program.pgs',
        units={'Serial_No': '', 'Part_No': '', 'Site_No': '',
               'V1': 'V', 'V2': 'A', 'V3': '', 'V1.1': 'mV'},
        mins={'Serial_No': '', 'Part_No': '', 'Site_No': '',
              'V1': '0', 'V2': '0', 'V3': '', 'V1.1': '0'},
        maxs={'Serial_No': '', 'Part_No': '', 'Site_No': '',
              'V1': '10', 'V2': '5', 'V3': '', 'V1.1': '100'},
        lot_id='LOT-RICH',
        operator='alice',
        station='ST-RICH',
        device_name='DEV-RICH',
        tester_type='T1',
        test_type='FT',
        total_test_time='12.5',
        handler='H-RICH',
        start_time='2026-01-01 10:00:00',
        end_time='2026-01-01 10:05:00',
    )


def cta8280f_meta():
    return base_meta(
        format='CTA8280F',
        program_name='rich_program2.pgs',
        units={'Index_No': '', 'Dut_No': '', 'Serial_No': '', 'Site_No': '',
               'V1': 'V', 'V2': 'A', 'V3': '', 'V1.1': 'mV'},
        mins={'Index_No': '', 'Dut_No': '', 'Serial_No': '', 'Site_No': '',
              'V1': '0', 'V2': '0', 'V3': '', 'V1.1': '0'},
        maxs={'Index_No': '', 'Dut_No': '', 'Serial_No': '', 'Site_No': '',
              'V1': '10', 'V2': '5', 'V3': '', 'V1.1': '100'},
        lot_id='LOT-RICH2',
        operator='bob',
        station='ST-RICH2',
        device_name='DEV-RICH2',
        tester_type='T2',
        test_type='FT',
        total_test_time='11.5',
        handler='H-RICH2',
        start_time='2026-01-02 11:00:00',
        end_time='2026-01-02 11:05:00',
    )


def sts8200_meta():
    return base_meta(
        format='STS8200',
        program_name='JAVBN281R3CYCAAV1.6.pgs',
        units={'SITE_NUM': '', 'PART_ID': '', 'PASSFG': '', 'SOFT_BIN': '',
               'T_TIME': 'ms', 'TestA': 'V', 'TestB': 'V', 'TestA.1': 'V'},
        mins={'SITE_NUM': '', 'PART_ID': '', 'PASSFG': '', 'SOFT_BIN': '',
              'T_TIME': '0', 'TestA': '0', 'TestB': '0', 'TestA.1': '0'},
        maxs={'SITE_NUM': '', 'PART_ID': '', 'PASSFG': '', 'SOFT_BIN': '',
              'T_TIME': '10', 'TestA': '5', 'TestB': '5', 'TestA.1': '10'},
        lot_id='LOT-C',
        operator='carol',
        station='STS8200-43 StationA',
        device_name='BN281R3CYCAAV1.6',
        total_test_time='9.5',
        handler='H3',
        start_time='2026-01-03 09:00:00',
        end_time='2026-01-03 09:05:00',
    )


def ets88_meta():
    return base_meta(
        format='ETS88',
        program_name='ets_program.pgs',
        # 既有行为：header 行首列就是 'Test Name'，被 device_name 映射整体收下
        device_name=','.join(['', '', '', ''] + ETS_TEST_COLUMNS),
        units=_ets_meta(['Units', '', '', '', ''] + ['V'] * 55),
        mins=_ets_meta(['', '', '', '', ''] + ['0'] * 55),
        maxs=_ets_meta(['', '', '', '', ''] + ['10'] * 55),
        lot_id='LOT-E',
        operator='eve',
        station='ST-E',
        tester_type='T-E',
        test_type='FT',
        handler='H-E',
        start_time='01/05/2026 08:00:00',
        end_time='01/05/2026 08:05:00',
    )


class _TempCsvMixin:
    def write_csv(self, text):
        fd, path = tempfile.mkstemp(suffix='.csv', text=True)
        os.close(fd)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path


class RichFixtureEquivalenceTests(_TempCsvMixin, SimpleTestCase):
    """四种格式在共享富夹具上的输出与改前逐字段相等。"""

    def assert_matches(self, parser, text, expected_df, expected_meta):
        path = self.write_csv(text)
        df, meta = parser.parse(path)
        assert_frame_equal(df, expected_df)
        meta = dict(meta)
        self.assertEqual(meta.pop('file_path'), os.path.abspath(path))
        self.assertEqual(meta, expected_meta)

    def test_cta8290d(self):
        self.assert_matches(CTA8290DParser(), cta8290d_text(),
                            cta8290d_expected(), cta8290d_meta())

    def test_cta8280f(self):
        self.assert_matches(CTA8280FParser(), cta8280f_text(),
                            cta8280f_expected(), cta8280f_meta())

    def test_sts8200(self):
        self.assert_matches(STS8200Parser(), sts8200_text(),
                            sts8200_expected(), sts8200_meta())

    def test_ets88(self):
        self.assert_matches(ETS88Parser(), ets88_text(),
                            ets88_expected(), ets88_meta())


class HeaderWindowTests(_TempCsvMixin, SimpleTestCase):
    """头部助手看到的必须是前 min(HEADER_KEEP, 总行数) 个物理行。"""

    def _spy_helpers(self):
        parser = CTA8290DParser()
        seen = {}
        original = (
            parser.extract_header_metadata,
            parser._extract_program_name,
            parser.postprocess_header_meta,
        )

        def spy_header(head, mapping, scan_limit=HEADER_KEEP):
            seen['header'] = list(head)
            return original[0](head, mapping, scan_limit)

        def spy_program(head):
            seen['program'] = list(head)
            return original[1](head)

        def spy_post(head, program_name, header_meta):
            seen['post'] = list(head)
            return original[2](head, program_name, header_meta)

        parser.extract_header_metadata = spy_header
        parser._extract_program_name = spy_program
        parser.postprocess_header_meta = spy_post
        return parser, seen

    def test_first_80_lines_even_when_marker_is_early(self):
        text = cta8290d_text()
        lines = text.splitlines(keepends=True)
        self.assertGreater(len(lines), HEADER_KEEP)
        parser, seen = self._spy_helpers()
        df, _ = parser.parse(self.write_csv(text))
        self.assertIsNotNone(df)
        expected = lines[:HEADER_KEEP]
        for key in ('header', 'program', 'post'):
            self.assertEqual(seen[key], expected, key)

    def test_short_file_helpers_see_every_line(self):
        text = (
            'TestFile,/opt/programs/short.pgs\n'
            '[Data]\n'
            'Serial_No,Part_No,Site_No,V1\n'
            ',,,V\n'
            ',,,0\n'
            ',,,10\n'
            '1,P1,1,1.0\n'
            '2,P2,1,2.0\n'
        )
        lines = text.splitlines(keepends=True)
        parser, seen = self._spy_helpers()
        df, _ = parser.parse(self.write_csv(text))
        self.assertEqual(len(df), 2)
        for key in ('header', 'program', 'post'):
            self.assertEqual(seen[key], lines, key)

    def test_marker_after_header_window_is_still_found(self):
        lines = ['TestFile,/opt/programs/late.pgs']
        lines += [f'# filler line {i}' for i in range(HEADER_KEEP + 20)]
        lines += [
            '[Data]',
            'Serial_No,Part_No,Site_No,V1',
            ',,,V',
            ',,,0',
            ',,,10',
            '1,P1,1,1.0',
            '2,P2,1,2.0',
        ]
        text = '\n'.join(lines) + '\n'
        parser, seen = self._spy_helpers()
        df, meta = parser.parse(self.write_csv(text))
        self.assertEqual(len(df), 2)
        self.assertEqual(meta['program_name'], 'late.pgs')
        expected = text.splitlines(keepends=True)[:HEADER_KEEP]
        for key in ('header', 'program', 'post'):
            self.assertEqual(seen[key], expected, key)


class HeaderKeepCouplingTests(SimpleTestCase):
    """HEADER_KEEP 与 extract_header_metadata 的默认扫描窗口不得漂移。"""

    def test_keep_window_covers_legacy_helper_window(self):
        # 助手历史上的扫描窗口是 80 行；有界读取保留得更少会让元数据缩水。
        self.assertGreaterEqual(HEADER_KEEP, 80)

    def test_helper_default_scan_limit_is_header_keep(self):
        default = inspect.signature(
            CTA8290DParser.extract_header_metadata
        ).parameters['scan_limit'].default
        self.assertEqual(default, HEADER_KEEP,
                         '阅读窗口与助手默认窗口必须由同一个常量驱动')


class BoundedReadPeakTests(_TempCsvMixin, SimpleTestCase):
    """大文件上 parse() 的 Python 分配峰值必须远低于文件体积。

    判断口径：pandas 3 的 ``read_csv`` 自身就会把整文件读进 Python 缓冲区
    （本机实测约 1.8× 文件体积），这部分与本次改动无关，也消不掉。所以
    「早 marker」用例量的是 **parse 峰值减去同参数 read_csv 基线峰值**——
    即「整文件 readlines()」为头部多付的那一份；旧实现这一份约 2.9× 文件
    体积，新实现只剩头部 HEADER_KEEP（80）+ marker 行 + max_offset（4）
    = 85 行的常数级开销。找不到 marker 的用例不读 CSV，
    直接断言 parse 峰值 < 文件体积 / 4。
    """

    ROWS = 350_000

    def _large_with_marker(self):
        head = [
            'TestFile,/opt/programs/large.pgs',
            'LotID,LOT-LARGE',
            '[Data]',
            'Serial_No,Site_No,V1,V2,V3',
            ',ms,V,V,V',
            ',0,0,0,0',
            ',10,5,5,10',
        ]
        rows = [
            f'{i},1,{i % 1000}.5,{i % 100}.25,{i % 10}.125'
            for i in range(self.ROWS)
        ]
        return '\n'.join(head + rows) + '\n'

    def _large_without_marker(self):
        return ''.join(f'{i:024d}\n' for i in range(self.ROWS))

    @staticmethod
    def _measure(fn):
        gc.collect()
        tracemalloc.start()
        try:
            result = fn()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return result, peak

    def _read_csv_baseline_peak(self, path, skiprows):
        def read():
            return pd.read_csv(path, skiprows=skiprows, header=None,
                               on_bad_lines='skip', encoding='utf-8')

        read()  # warm up：首次解析的内部对象不计入被测区间
        _, peak = self._measure(read)
        return peak

    def test_peak_bounded_with_early_marker(self):
        text = self._large_with_marker()
        path = self.write_csv(text)
        file_size = os.path.getsize(path)
        self.assertGreater(file_size, 8 * 1024 * 1024,
                           '夹具应达到 8MB 量级')
        data_start_row = text.splitlines().index('[Data]') + 5
        parser = CTA8290DParser()
        parser.parse(path)  # warm up
        baseline = self._read_csv_baseline_peak(path, data_start_row)
        (df, meta), peak = self._measure(lambda: parser.parse(path))
        self.assertEqual(len(df), self.ROWS)
        self.assertEqual(meta['program_name'], 'large.pgs')
        extra = peak - baseline
        self.assertLess(
            extra, file_size // 4,
            f'parse peak {peak} - read_csv baseline {baseline} = {extra} bytes '
            f'/ file {file_size} bytes (头部读取的额外分配应低于文件体积的 1/4)',
        )

    def test_missing_marker_returns_none_with_bounded_peak(self):
        path = self.write_csv(self._large_without_marker())
        file_size = os.path.getsize(path)
        self.assertGreater(file_size, 8 * 1024 * 1024,
                           '夹具应达到 8MB 量级')
        parser = CTA8290DParser()
        parser.parse(path)  # warm up
        (df, meta), peak = self._measure(lambda: parser.parse(path))
        self.assertIsNone(df)
        self.assertIsNone(meta)
        self.assertLess(
            peak, file_size // 4,
            f'tracemalloc peak {peak} bytes / file {file_size} bytes '
            f'(应为文件体积的 1/4 以下)',
        )


if __name__ == '__main__':
    unittest.main()
