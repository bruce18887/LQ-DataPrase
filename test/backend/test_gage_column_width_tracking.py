"""A5 第四段（其二）：列宽记账通路本体的判据（只有新实现存在才跑得起来）。

与 ``test_gage_column_width_parity.py`` 的分工：那一份钉「下发的宽度 == 整表回读算的宽度」，
在改前树上也全绿（夹具非空转的证据）；这一份钉新通路自己的四条性质——

① **值的渲染口径**：记账必须用 Go 会读回的那串文本量宽度（``cell_display_text``），
   不是 Python ``str()``；复刻不了的值出域（返回 ``None``）并触发整表回读回退。
② **形状口径**：``min_row`` 之上 / 非横向合并锚点 / 非空 三条筛选与旧通路逐格一致；
   同一格后写覆盖前写；``None`` 与 ``''`` 不记账（``write_cell`` 本来就不落盘，
   落了会变成文本格让数值型条件格式把空白判红）。
③ **通路口径**：真实生成里 Summary 再也没被 ``get_cols`` 整表读回（省下的就是那 20%），
   而每一格经 ``write_cell`` 写进 Summary 的都在账上 —— 漏记等于未来加一条直写通路时静默变窄。
④ **前提口径**：Summary 上「带自定义数字格式的格」不许是数值。实测 ``0.000%`` 把 0.4242
   渲染成 ``'42.420%'``（比原值宽），而记账量的是原值。今天唯一的数字格式挂在 R&R% 列，
   那一列只有公式（读回空串）与 ``'N/A'`` 文本 ⇒ 前提成立；这条红了就说明有人新加了格式列。

基准与录放助手在 ``width_scan_reference.py``（复刻口径见那份文档）。
runner: ``python -X utf8 manage.py test test.backend.test_gage_column_width_tracking``
"""
import ast
import datetime
import inspect
import math
import re
import unicodedata
from unittest import mock

import excelize
from django.test import SimpleTestCase

from apps.export import excel_theme
from apps.export.excel_theme import (
    COL_MAX_WIDTH, COL_MIN_WIDTH, COL_WIDTH_PADDING, ColumnWidthTracker, cell_display_text,
)
from apps.gage import gage_legacy_builder
from apps.gage.gage_legacy_builder import build_gage_summary_excel
from apps.gage.gage_summary_sheet import SUMMARY_HEADER_ROW, SUMMARY_SHEET, write_cell
from test.backend.gage_shape_fixtures import LONG_PARAM, WIDE_PARAM, datasets
from test.backend.width_scan_reference import (
    capture_col_widths, delivered, widths_by_full_scan,
)

#: 对抗形状 ``(格子地址, 值)``。列序**故意打乱** —— 下发必须按列号升序，不能靠写入顺序。
#: 每一项都对着旧扫描的一条规则（``min_row`` 切顶 / 非空才计 / 横向合并锚点跳过 / 钳位上下界
#: / 东亚宽字符按 2 / 同格后写覆盖）；缺任何一项，对应那条规则就没人验。
ADVERSARIAL_CELLS = [
    ('Q5', '这一列只有表头以上的内容' * 2),   # Q 列唯一的格子在 min_row 之上吗？没有 ⇒ 不下发
    ('C11', 'Test Name'),                     # 表头 9 ⇒ 11.5
    ('A11', 'File Name'),                     # 表头 9 ⇒ 11.5
    ('A1', 'Gage R&R Summary Report ' * 4),   # 长标题在行 1（表头区）⇒ 不撑宽 A
    ('K11', 'Max'),                           # 3 ⇒ 下界 8.0
    ('K12', 100000.0),                        # Go 读回 '100000'（6）⇒ 8.5；str() 会是 '100000.0'（8）
    ('I11', 'Min CPK'),                       # 7 ⇒ 9.5；I16 是横向合并锚点，必须被跳过
    ('I16', 'B' * 60),                        # 锚点：旧扫描跳过 ⇒ I 仍是 9.5 而不是 42.0
    ('D12', WIDE_PARAM),                      # 6 个汉字 ⇒ 12 ⇒ 14.5（按 1 计会得 8.5）
    ('C12', LONG_PARAM),                      # 51 ⇒ 钳到上界 42.0
    ('E13', None),                            # 空值：不写、不记账
    ('F13', ''),                              # 空串：不写、不记账（写了就是文本格）
    ('G14', 'short'),                         # 同一格后写覆盖前写
    ('G14', 'much longer value here'),        # ⇒ G 记这一条的宽度
    ('H15', 'FORMULA'),                       # 公式格读回空串 ⇒ H 完全不下发
    ('J21', -0.0001),                         # '-0.0001'（7）⇒ 9.5
    ('L22', 1e-05),                           # Go 读回 '0.00001'（7）⇒ 9.5；str() 是 '1e-05'（5）
    ('M23', float('nan')),                    # Go 读回 'NaN'（3）⇒ 下界 8.0
    ('N24', 42),                              # int ⇒ '42'（2）⇒ 下界 8.0
    ('O25', True),                            # bool ⇒ Go 读回 'TRUE'（4）⇒ 下界 8.0
    ('P17', '纵向合并里的长内容不该被当锚点跳过' * 2),   # 纵向合并 ⇒ 照常计数
]

#: P 列的显示宽度（'纵向合并里的长内容不该被当锚点跳过' 是 17 个宽字符 = 34，两条 = 68 ⇒ 钳 42.0）
LONG_CJK_TEXT = '纵向合并里的长内容不该被当锚点跳过' * 2


def _write_adversarial(f, widths=None):
    """把对抗形状写进一张 Summary。给了 ``widths`` 就是记账通路，不给就是裸写。"""
    for cell, value in ADVERSARIAL_CELLS:
        if value == 'FORMULA':
            excel_theme.set_formula(f, SUMMARY_SHEET, cell, '=ROUND(K12/L12,4)')
            continue
        write_cell(f, SUMMARY_SHEET, cell, value, widths=widths)
    # 合并区建在写完之后 —— 与生产同序（``format_summary_sheet`` 就是后段才合并），
    # 所以「锚点跳过」必须在收尾时读合并区，不能在记账时判断。
    f.merge_cell(SUMMARY_SHEET, 'I16', 'K16')
    f.merge_cell(SUMMARY_SHEET, 'P17', 'P18')
    return f


def _new_file():
    f = excelize.new_file()
    f.new_sheet(SUMMARY_SHEET)
    return f


def stale_ledger_entries(records, handle, cells, min_row):
    """把「写进 `cells` 的格子」与账本/产物最终读回对一遍，返回问题列表。

    两个方向都查：**缺席**（写了却没记账）与**过期**（记的是早先那次的宽度，之后又被
    直接 ``set_cell_value`` 覆盖过）。对照物取 Go 自己的 ``get_cell_value``，不是
    ``cell_display_text`` 的第二份副本 —— 否则「两边一起改错」的变异永远不红（与本文件
    其余平价判据同一条纪律）。公式格读回空串、``min_row`` 之上的行两条都跳过：旧扫描
    本来就不计它们。
    """
    problems = []
    for cell in cells:
        coord = excelize_coordinates(cell)
        if coord is None or coord[1] < min_row:
            continue
        col, row = coord
        text = handle.get_cell_value(SUMMARY_SHEET, cell)
        if not text:
            continue
        recorded = records.get(col, {}).get(row)
        if recorded is None:
            problems.append(f'{cell} 写了却没记账（列宽会静默变窄）')
        elif recorded != excel_theme._display_width(text):
            problems.append(f'{cell} 账={recorded} 但产物读回 {text!r}'
                            f'（宽 {excel_theme._display_width(text)}）⇒ 账是过期的')
    return problems


class CellDisplayTextTests(SimpleTestCase):
    """``cell_display_text`` 只在「与 Go 读回逐字相同」时给串，否则给 ``None``。"""

    SWEEP = [
        'V', 'N/A', 'PAR0001', 'File Name', LONG_PARAM, WIDE_PARAM, '  spaced  ',
        0, 1, -1, 42, 999, -7, 2 ** 30, -(2 ** 30), 2 ** 31 - 1, -(2 ** 31),
        0.0, -0.0, 6.0, 100.0, 100000.0, 999999999999999.0, 12345.6789, -12345.6789,
        round(1 / 3, 4), round(0.1 + 0.2, 4), 1.00005, 655.36, 0.0001, -0.0001,
        1234567890.1234, 1e-05, 1.2345e-09, 1.2345e-10, 1e-14, math.nan, math.inf,
        -math.inf, True, False,
    ]

    def test_in_domain_values_match_the_go_read_back(self):
        """写进表里再逐格读回：给了串的必须逐字相等（宽度口径的前提）。"""
        f = excelize.new_file()
        f.new_sheet('Sweep')
        try:
            for i, value in enumerate(self.SWEEP, start=1):
                f.set_cell_value('Sweep', f'A{i}', value)
            col = (f.get_cols('Sweep') or [[]])[0]
            for i, value in enumerate(self.SWEEP):
                ours = cell_display_text(value)
                if ours is None:
                    continue
                got = col[i] if i < len(col) else None
                self.assertEqual(ours, got, f'{value!r} 的复刻与 Go 读回不一致')
        finally:
            f.close()

    def test_whole_and_tiny_floats_are_not_python_str(self):
        """Go 把 6.0 写成 '6'、把 1e-05 写成 '0.00001' —— 直接用 ``str()`` 宽度就错。"""
        self.assertEqual(cell_display_text(6.0), '6')
        self.assertEqual(cell_display_text(-0.0), '-0')
        self.assertEqual(cell_display_text(100000.0), '100000')
        self.assertEqual(cell_display_text(1e-05), '0.00001')
        self.assertEqual(cell_display_text(1.2345e-09), '0.0000000012345')
        self.assertNotEqual(cell_display_text(6.0), str(6.0))
        self.assertNotEqual(cell_display_text(1e-05), str(1e-05))

    def test_non_numeric_scalars_follow_the_go_spelling(self):
        """布尔与 nan/inf 的读回是 Go 的写法，不是 Python 的 ``str``。"""
        self.assertEqual(cell_display_text(True), 'TRUE')
        self.assertEqual(cell_display_text(False), 'FALSE')
        self.assertEqual(cell_display_text(math.nan), 'NaN')
        self.assertEqual(cell_display_text(math.inf), '+Inf')
        self.assertEqual(cell_display_text(-math.inf), '-Inf')

    def test_out_of_domain_values_return_none_instead_of_guessing(self):
        """出域必须给 ``None``（那才会触发整表回读），不许给一个「大概差不多」的串。

        本机实测这几类 Go 的读回与 Python 的字符串口径不同或根本不可靠：超过 15 位数字会舍入、
        1e15 起改科学计数法、整数按 **int32 回绕**（``2**31`` 读回 ``'-2147483648'``、
        ``10**14`` 读回 ``'276447232'``）、日期这类非数值标量另有渲染路径。
        """
        for value in (0.00010000000000000002, 1234567890123456.0, 123456789012345.6,
                      2e15, 1e16, 1.5e17, 123456789012345678, 2 ** 31, -(2 ** 31) - 1,
                      2 ** 53 + 2, 10 ** 14, 10 ** 20, -(10 ** 20), 1e-15, 1.2345e-11,
                      datetime.date(2026, 1, 1), datetime.datetime(2026, 1, 1),
                      object(), [1, 2]):
            self.assertIsNone(cell_display_text(value), f'{value!r} 应当出域')

    def test_in_domain_covers_what_the_summary_actually_writes(self):
        """反向：Summary 真会写的那些形状不许出域 —— 出域就是整表回读，等于白改。"""
        for value in ('PAR0001', 'V', 'Good', 'Bad1', 'pin1.csv_S1', 'N/A',
                      0, 6, 42, 2 ** 30, 0.0, 6.0, 1.2345, 12345.6789, 1e-05, 655.36,
                      1234567890.1234, 999999999999999.0, True, math.nan):
            self.assertIsNotNone(cell_display_text(value), f'{value!r} 不该出域')


class DisplayWidthFastPathTests(SimpleTestCase):
    """ASCII 快路与逐字符口径必须同值（快路是给记账用的，口径不能变）。"""

    CASES = ['V', 'PAR0001', LONG_PARAM, WIDE_PARAM, '  spaced  ', '-0.0001',
             'Mixed 中英 123', '\t tab\n', '①②③', 'Ａ Ｂ Ｃ', '', '0']

    def test_fast_path_equals_the_char_by_char_rule(self):
        for text in self.CASES:
            with self.subTest(text=text):
                by_char = sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1
                              for ch in text)
                self.assertEqual(excel_theme._display_width(text), by_char)


class ColumnWidthTrackerShapeTests(SimpleTestCase):
    """对抗形状上：新通路 == 旧通路（``scan_column_widths`` + ``apply_column_widths``）
    == 整表回读基准。"""

    def test_matches_the_reference_full_scan(self):
        f = _new_file()
        try:
            widths = ColumnWidthTracker(SUMMARY_SHEET)
            _write_adversarial(f, widths=widths)
            self.assertFalse(widths.fell_back(), '对抗形状全在定义域内却触发了回退')
            with capture_col_widths() as calls:
                widths.apply(f, min_row=SUMMARY_HEADER_ROW)
            order, applied = delivered(calls, SUMMARY_SHEET)
            oracle = widths_by_full_scan(f, SUMMARY_SHEET, min_row=SUMMARY_HEADER_ROW)
        finally:
            f.close()
        self.assertEqual(applied, oracle, f'记账下发 {applied} ≠ 整表回读 {oracle}')
        self.assertEqual(order, sorted(order), f'下发顺序不是列号升序：{order}')
        self.assertEqual(len(order), len(set(order)), f'同一列被下发两次：{order}')

    def test_matches_the_old_full_scan_on_the_same_shape(self):
        """两张内容相同的表：一张走旧「扫 + 发」两步，一张走记账 ⇒ 下发必须一模一样。

        旧 ``autofit_columns`` 那层包装已删（Gage 换记账通路后它在生产里零调用方），
        这里用它的两个本体函数现场复刻那一步，对照物没有跟着变。
        """
        f_old, f_new = _new_file(), _new_file()
        try:
            _write_adversarial(f_old)
            with capture_col_widths() as old_calls:
                excel_theme.apply_column_widths(
                    f_old, SUMMARY_SHEET,
                    excel_theme.scan_column_widths(f_old, SUMMARY_SHEET,
                                                   min_row=SUMMARY_HEADER_ROW))
            old_order, old_applied = delivered(old_calls, SUMMARY_SHEET)

            widths = ColumnWidthTracker(SUMMARY_SHEET)
            _write_adversarial(f_new, widths=widths)
            with capture_col_widths() as new_calls:
                widths.apply(f_new, min_row=SUMMARY_HEADER_ROW)
            new_order, new_applied = delivered(new_calls, SUMMARY_SHEET)
        finally:
            f_old.close()
            f_new.close()
        self.assertTrue(old_applied and new_applied, '两张表都没下发宽度 ⇒ 判据空转')
        self.assertEqual(new_applied, old_applied,
                         f'记账 {new_applied} ≠ 旧通路 {old_applied}')
        self.assertEqual(new_order, old_order, '下发顺序与旧通路不一致')
        # 这几列是这套形状的靶心：锚点跳过 / 公式不计数 / min_row / 钳位 / 宽字符
        self.assertNotIn(_col_of('H'), new_applied, '公式那一列本不该被下发')
        self.assertNotIn(_col_of('Q'), new_applied, '只有表头以上内容的列本不该被下发')
        self.assertEqual(new_applied[_col_of('I')], 9.5, '横向合并锚点没被跳过')
        self.assertEqual(new_applied[_col_of('C')], 42.0, '超长参数名那列没钳到上界')
        self.assertEqual(new_applied[_col_of('D')], 14.5, '宽字符没按 2 计')
        self.assertEqual(new_applied[_col_of('P')], 42.0, '纵向合并的锚点被误跳过了')

    def test_records_cover_every_written_cell_and_honour_last_write_wins(self):
        f = _new_file()
        try:
            widths = ColumnWidthTracker(SUMMARY_SHEET)
            _write_adversarial(f, widths=widths)
            records = widths.records()
            for cell, value in ADVERSARIAL_CELLS:
                if value is None or value == '' or value == 'FORMULA':
                    continue
                col, row = excelize_coordinates(cell)
                self.assertIn(row, records.get(col, {}), f'{cell} 写了却没记账')
            self.assertNotIn(13, records.get(_col_of('E'), {}), 'None 不该记账')
            self.assertNotIn(13, records.get(_col_of('F'), {}), "空串不该记账")
            self.assertNotIn(_col_of('H'), records, '公式格进了账 ⇒ 宽度会凭空多一列')
            self.assertEqual(records[_col_of('G')][14], len('much longer value here'),
                             f'G14 记的是 {records[_col_of("G")][14]}，应为后写那条')
        finally:
            f.close()

    def test_other_sheets_are_not_recorded(self):
        """记账只认自己那一张表：文件表那一列×行矩阵绝不该进账。"""
        f = _new_file()
        try:
            widths = ColumnWidthTracker(SUMMARY_SHEET)
            widths.note('SomeFileSheet', 'A12', LONG_PARAM)
            widths.note(SUMMARY_SHEET, 'A12', 'ok')
            self.assertEqual(widths.records(), {1: {12: 2}}, '别的表的格子被记进来了')
        finally:
            f.close()

    def test_min_row_and_clamp_are_honoured_per_call(self):
        """同一张账本换 ``min_row`` / 钳位下界，下发必须跟着变（不是记死在账本里）。"""
        f = _new_file()
        try:
            widths = ColumnWidthTracker(SUMMARY_SHEET)
            write_cell(f, SUMMARY_SHEET, 'A11', 'File Name', widths=widths)
            write_cell(f, SUMMARY_SHEET, 'A12', 'x' * 30, widths=widths)
            self.assertEqual(widths.widths(f, min_row=12), {1: 32.5})
            self.assertEqual(widths.widths(f, min_row=13), {}, 'min_row 之上没内容就不下发')
            self.assertEqual(widths.widths(f, min_row=11), {1: 32.5})
            self.assertEqual(widths.widths(f, min_row=11, max_width=20.0), {1: 20.0})
        finally:
            f.close()


class TrackerFallbackTests(SimpleTestCase):
    """出域值 ⇒ 回退整表回读：付时间，不付宽度。"""

    OUT_OF_DOMAIN = (0.00010000000000000002, 1e16, 2e15, 10 ** 20, 1e-15)

    def test_out_of_domain_value_falls_back_and_keeps_widths(self):
        for value in self.OUT_OF_DOMAIN:
            with self.subTest(value=value):
                f = _new_file()
                try:
                    widths = ColumnWidthTracker(SUMMARY_SHEET)
                    write_cell(f, SUMMARY_SHEET, 'C11', 'Test Name', widths=widths)
                    write_cell(f, SUMMARY_SHEET, 'C12', value, widths=widths)
                    self.assertTrue(widths.fell_back(), f'{value!r} 没触发回退 ⇒ 宽度按原值算')
                    with capture_col_widths() as calls:
                        widths.apply(f, min_row=SUMMARY_HEADER_ROW)
                    _order, applied = delivered(calls, SUMMARY_SHEET)
                    oracle = widths_by_full_scan(f, SUMMARY_SHEET,
                                                 min_row=SUMMARY_HEADER_ROW)
                    self.assertEqual(applied, oracle)
                finally:
                    f.close()

    def test_fallback_actually_reads_the_sheet_back(self):
        """回退必须真的走 ``get_cols`` —— 否则「回退」只是句空话，宽度照样错。"""
        f = _new_file()
        try:
            widths = ColumnWidthTracker(SUMMARY_SHEET)
            write_cell(f, SUMMARY_SHEET, 'C12', 1e16, widths=widths)
            with mock.patch.object(excelize.File, 'get_cols', autospec=True) as get_cols:
                get_cols.side_effect = lambda self, sheet, *a, **k: [[]]
                widths.apply(f, min_row=SUMMARY_HEADER_ROW)
            self.assertGreaterEqual(get_cols.call_count, 1, '回退没走整表回读')
        finally:
            f.close()


class SummaryWriteSeamTests(SimpleTestCase):
    """生产通路的两条前提：真实生成不再整表回读；每一格都被记账。"""

    def _build_with_tracker(self, shape):
        """跑一次真实生成，同时把**账本**和**产物字节**交回来。

        只交回账本的话，判据顶多问「这格记没记」，问不出「记的是不是最终那次的宽度」——
        后者才是直写覆盖（A3 那种「先记账写一遍、再裸写覆盖一遍」）的真实失效形状。
        """
        created = []
        real = ColumnWidthTracker

        class _Spy(real):
            def __init__(self, sheet):
                super().__init__(sheet)
                created.append(self)

        with mock.patch.object(gage_legacy_builder, 'ColumnWidthTracker', _Spy):
            payload = build_gage_summary_excel(datasets(shape))
        self.assertEqual(len(created), 1, f'builder 建了 {len(created)} 本账')
        return created[0], payload

    def test_real_build_never_reads_the_summary_back(self):
        """钉死形状上 Summary 一次都没被 ``get_cols`` 读回（这就是省下的那 20%）。"""
        seen = []
        origin = excelize.File.get_cols

        def spy(self, sheet, *args, **kwargs):
            seen.append(sheet)
            return origin(self, sheet, *args, **kwargs)

        for shape in ('narrow', 'wide'):
            seen.clear()
            with mock.patch.object(excelize.File, 'get_cols', spy):
                build_gage_summary_excel(datasets(shape))
            self.assertNotIn(SUMMARY_SHEET, seen,
                             f'{shape} 的生成仍把 Summary 整表读回 ⇒ 通路没换过来')

    def test_every_summary_cell_written_by_the_builder_is_recorded(self):
        """表头行及其下每一格：账上不但**有**，而且记的就是产物最终读回那串的宽度。

        只钉「记没记」抓不到**过期**：将来若有人加一条「先经 ``write_cell`` 记一笔、再直接
        ``set_cell_value`` 覆盖成更长的串」的通路（今天 A3/B3 就是这个形状，只是行 3 落在
        ``min_row`` 之上不参与算宽），成员判据照样绿，列宽已经悄悄错了。对照物用 Go 自己的
        ``get_cell_value``，不是 ``cell_display_text`` 的第二份副本 ⇒「两边一起改错」也红。
        这条判据今天的判别力见 ``test_width_check_catches_a_raw_overwrite_of_a_recorded_cell``
        （那条把「将来要抓的形状」现在就造出来，证明它不是装饰）。

        ``write_bad1_count`` / ``mark_failed_label`` 直接 ``f.set_cell_value`` 写 B3/A3：
        行 3 在 ``min_row`` 之上，旧扫描本来就不计 ⇒ 不进账才是正确形状。
        """
        written = []
        origin = excelize.File.set_cell_value

        def spy(self, sheet, cell, value, *args, **kwargs):
            if sheet == SUMMARY_SHEET:
                written.append(cell)
            return origin(self, sheet, cell, value, *args, **kwargs)

        with mock.patch.object(excelize.File, 'set_cell_value', spy):
            tracker, payload = self._build_with_tracker('narrow')
        records = tracker.records()
        self.assertFalse(tracker.fell_back(), '钉死形状不该回退')
        self.assertTrue(written, '一格都没写 ⇒ 判据空转')
        contributing = {excelize_coordinates(cell) for cell in written
                        if excelize_coordinates(cell)[1] >= SUMMARY_HEADER_ROW}
        self.assertTrue(contributing, '表头行以下一格都没写 ⇒ 判据空转')
        recorded = {(col, row) for col, rows in records.items() for row in rows}
        self.assertTrue(recorded <= {excelize_coordinates(c) for c in written},
                        '账上有格子根本没被写过 ⇒ 记错了列或行')

        handle = excelize.open_reader(payload)
        try:
            problems = stale_ledger_entries(records, handle, written, SUMMARY_HEADER_ROW)
        finally:
            handle.close()
        self.assertFalse(problems, '记账与产物不一致：\n' + '\n'.join(problems[:8]))

    def test_width_check_catches_a_raw_overwrite_of_a_recorded_cell(self):
        """判据自身的判别力：记完账再裸写覆盖 ⇒ ``stale_ledger_entries`` 必须报出来。

        真实产物今天没有这种通路（唯一的裸写 A3/B3 都在 ``min_row`` 之上），所以产品级那条
        判据此刻只验到「缺席」那一半。这里手工造出「过期」那一半：同一格先经 ``write_cell``
        记账（短串），再直接 ``set_cell_value`` 写成短→长，判据必须红着指出来 —— 否则那条
        产品级判据就只是成员检查的换了个写法。
        """
        f = _new_file()
        try:
            widths = ColumnWidthTracker(SUMMARY_SHEET)
            write_cell(f, SUMMARY_SHEET, 'C12', 'AB', widths=widths)        # 账上 2
            f.set_cell_value(SUMMARY_SHEET, 'C12', 'OVERWRITTEN-RAW-LONG')  # 产物 20，且没记账
            self.assertEqual(widths.records()[3][12], 2, '前提：账上是第一次那格的宽度')
            problems = stale_ledger_entries(widths.records(), f, ['C12'], SUMMARY_HEADER_ROW)
        finally:
            f.close()
        self.assertEqual(len(problems), 1, f'覆盖写没被抓出来：{problems}')
        self.assertIn('C12', problems[0])

    def test_unrecorded_cell_that_reads_back_empty_is_not_reported(self):
        """读回空串的格子（公式就是这一类）本就不进旧扫描的账 ⇒ 不许报成漏记。

        ``written`` 来自 ``set_cell_value`` 的 spy，所以公式格不会出现在里面；但判据的入参
        形状是「一批格子地址」，将来只要有人把公式地址一起交进来（``set_formula`` 也落在同一
        张表上），少了这道闸就会把「正确不该计数的格」报成漏记 —— 判据随即失去可用性。
        这条钉的是闸本身。
        """
        f = _new_file()
        try:
            widths = ColumnWidthTracker(SUMMARY_SHEET)
            write_cell(f, SUMMARY_SHEET, 'C11', 'Test Name', widths=widths)
            excel_theme.set_formula(f, SUMMARY_SHEET, 'H15', '=ROUND(K12/L12,4)')
            self.assertEqual(f.get_cell_value(SUMMARY_SHEET, 'H15'), '',
                             '前提：公式格读回空串（本机实测口径）')
            problems = stale_ledger_entries(
                widths.records(), f, ['C11', 'H15'], SUMMARY_HEADER_ROW)
        finally:
            f.close()
        self.assertEqual(problems, [], f'公式格被冤成漏记：{problems}')

    def test_no_numeric_summary_cell_carries_a_custom_number_format(self):
        """记账量的是**原值**的渲染：数值格一挂数字格式，Go 读回就变长（实测 ``0.000%`` 下
        0.4242 → ``'42.420%'``），宽度就会比旧扫描窄。今天唯一的格式挂在 R&R% 列，
        那一列只有公式与 ``'N/A'``。"""
        numeric = re.compile(r'\A-?\d+(\.\d+)?\Z')
        handle = excelize.open_reader(build_gage_summary_excel(datasets('narrow')))
        try:
            style_cache, offenders = {}, []
            for col_idx, column in enumerate(handle.get_cols(SUMMARY_SHEET), start=1):
                for offset, value in enumerate(column):
                    row = offset + 1
                    if row < SUMMARY_HEADER_ROW or not value or not numeric.match(value):
                        continue
                    ref = f'{excelize.column_number_to_name(col_idx)}{row}'
                    style_id = handle.get_cell_style(SUMMARY_SHEET, ref)
                    if style_id not in style_cache:
                        style_cache[style_id] = handle.get_style(style_id).custom_num_fmt
                    if style_cache[style_id] is not None:
                        offenders.append((ref, value, style_cache[style_id]))
            self.assertEqual(offenders, [], f'带数字格式的数值格会被记账侧算窄：{offenders}')
        finally:
            handle.close()


class SummaryWidthsSourceTripwireTests(SimpleTestCase):
    """头号退化方式是「收尾悄悄退回整表回读」，所以在源码层面也钉一道。

    行为层的判据是 ``test_real_build_never_reads_the_summary_back``；这一道钉的是**引用形状**：
    ``gage_summary_sheet`` 不再 import 整表回读那对函数（``scan_column_widths`` /
    ``apply_column_widths``）、`finalize_summary_sheet`` 也不直接调它们 —— 哪天有人为了
    「省事」把老通路接回来，行为层判据要跑完整生成才红，这道当场红。
    """

    def test_summary_module_no_longer_reaches_for_the_full_scan(self):
        """按 AST 扫，不按文本 —— 文档里写着「原先这里是整表回读」不该把判据弄红。"""
        from apps.gage import gage_summary_sheet

        imported = {n.name for node in ast.walk(
            ast.parse(inspect.getsource(gage_summary_sheet)))
            if isinstance(node, ast.ImportFrom) for n in node.names}
        self.assertNotIn('scan_column_widths', imported | set(dir(gage_summary_sheet)),
                         'Summary 模块又把整表回读那条通路 import 回来了')
        tree = ast.parse(inspect.getsource(gage_summary_sheet))
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        called |= {n.func.attr for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertNotIn('scan_column_widths', called, 'Summary 里还有人整表回读算宽度')
        self.assertIn('apply', called, '收尾没有走账本下发宽度')


class ClampContractTests(SimpleTestCase):
    """钳位常数是产品契约：两条通路取的是同一份，且默认值没漂。"""

    def test_scan_defaults_are_the_shared_constants(self):
        params = list(inspect.signature(excel_theme.scan_column_widths).parameters.values())
        defaults = {p.name: p.default for p in params[3:]}
        self.assertEqual([defaults['min_width'], defaults['max_width'], defaults['padding']],
                         [COL_MIN_WIDTH, COL_MAX_WIDTH, COL_WIDTH_PADDING])
        tracker_params = list(
            inspect.signature(ColumnWidthTracker.widths).parameters.values())
        tracker_defaults = {p.name: p.default for p in tracker_params[2:]}
        self.assertEqual(
            [tracker_defaults['min_width'], tracker_defaults['max_width'],
             tracker_defaults['padding']],
            [COL_MIN_WIDTH, COL_MAX_WIDTH, COL_WIDTH_PADDING],
            '记账通路与旧通路的钳位默认值已经漂移')

    def test_the_constants_are_the_ones_the_product_ships_with(self):
        """8.0 / 42.0 / 2.5 是产物列宽的落点，改了要先过 ``test_gage_sheet_shape`` 的钉值。"""
        self.assertEqual([COL_MIN_WIDTH, COL_MAX_WIDTH, COL_WIDTH_PADDING], [8.0, 42.0, 2.5])


class CellCoordinatesTests(SimpleTestCase):
    """Python 侧的地址解析必须与 Go 的换算逐格一致（列算错 = 宽度发给隔壁列）。"""

    def test_matches_go_for_every_summary_address(self):
        refs = [f'{letter}{row}' for letter in _LETTERS for row in (1, 11, 12, 250, 46220)]
        for ref in refs:
            want = excelize.cell_name_to_coordinates(ref)
            self.assertEqual(excel_theme._cell_coordinates(ref), want, ref)

    def test_rejects_shapes_the_product_never_writes(self):
        """认不出的地址要给 ``None`` ⇒ 触发回退，而不是猜一个列号。"""
        for ref in ('12', 'A', '', 'a12', 'A12B', 'A0X'):
            self.assertIsNone(excel_theme._cell_coordinates(ref), ref)


def _col_of(letter):
    return excelize.cell_name_to_coordinates(f'{letter}1')[0]


def excelize_coordinates(ref):
    return excelize.cell_name_to_coordinates(ref)


_LETTERS = [excelize.column_number_to_name(i) for i in range(1, 52)]
