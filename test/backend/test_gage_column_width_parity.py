"""A5 第四段（其一）：gage Summary 列宽的**平价判据** —— 下发的宽度必须等于整表回读算出来的。

被优化掉的那条通路是「整表回读算列宽」（当时是 ``excel_theme.autofit_columns``，现在是
``scan_column_widths`` + ``apply_column_widths`` 两步）：它 ``get_cols`` 把整张 Summary 物化回
Python（本机实测 425 参数 × 4 文件时读回 46,220 个格子、其中非空 22,139；整次导出
5,011ms → 改后 4,005ms，best-of-3 墙钟、两棵树各跑一遍），只为量每列最宽的那个格。改成
「写格子时顺手记账、收尾一次下发」之后，验收判据不是「看起来差不多」而是
**逐列逐宽相等**（产物 xlsx 字节级不变由 ``test_gage_sheet_shape`` 钉，这里钉算法等价）。

基准在 ``width_scan_reference.py``：**独立重写**的一份旧通路复刻，不 import 生产实现
（两边共用同一段代码时，「一起改错」的变异永远不红）。判据比的是 ``set_col_width`` 的
**下发**，不是 XML 的最终形状 —— 区间接写法、列序变化只在下发侧看得见。

这一份在**改前树上也全绿**（它是「夹具非空转」的证据）：改前 ``finalize_summary_sheet``
走的就是整表回读，与基准同源同值；改后走记账通路，必须仍然全绿。只有新实现才跑得起来的那份
判据在 ``test_gage_column_width_tracking.py``。

对抗形状钉的是「旧扫描真会撞上」的格：数据行里的超长参数名（钳位上边界）、东亚宽字符、
公式格（V/W/X/Y 每行都有）、A1/C3 的横向合并标题、以及会踩到「Go 的读数渲染 ≠ Python
``str()``」的形状 —— 本机实测：整数值浮点 6.0 读回 '6'、1e-05 读回 '0.00001'、
超过 15 位有效数字读回会被舍入（'0.00010000000000000002' → '0.0001'）。

runner: ``python -X utf8 manage.py test test.backend.test_gage_column_width_parity``
"""
import ast
import inspect

import excelize
from django.test import SimpleTestCase

from apps.gage.gage_legacy_builder import build_gage_summary_excel
from apps.gage.gage_summary_sheet import SUMMARY_SHEET
from test.backend import width_scan_reference as ref
from test.backend.gage_shape_fixtures import (
    LONG_PARAM, WIDE_PARAM, build_shape, datasets, synthetic_dataset,
)
from test.backend.width_scan_reference import (
    as_letters, capture_col_widths, delivered, widths_by_full_scan,
)

#: 旧通路的调用口径：从表头行（11）起算 —— 表头区那几行标签不该撑宽列。
#: 这个数由 ``test_gage_sheet_shape.PIN_SUMMARY_WIDTHS`` 与产物 sha256 钉住（改了就红）。
MIN_ROW = 11


def _imported_modules(module):
    """模块里所有 import 语句点到的模块名（``from a.b import c`` 取 ``a.b``）。

    用 AST 而不是 grep 源码：基准的文档正文里本来就要写生产实现的名字来解释「为什么不复用它」，
    grep 会把说明文字判成违规；而真正要防的是 `import apps... as 别名` 这种绕过字面匹配的取用。
    """

    names = []
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _measure(label, file_datasets):
    """跑一次真实生成，量「下发了哪些列宽」，并把整表回读的基准一起返回。

    返回 ``(下发顺序, 下发宽度, 基准宽度)``；比较由各用例自己做，红信息带上形状名。
    """
    with capture_col_widths() as calls:
        data = build_gage_summary_excel(file_datasets)
    handle = excelize.open_reader(data)
    try:
        order, applied = delivered(calls, SUMMARY_SHEET)
        oracle = widths_by_full_scan(handle, SUMMARY_SHEET, min_row=MIN_ROW)
    finally:
        handle.close()
    return order, applied, oracle


def _pin_widths_by_index():
    """把 ``PIN_SUMMARY_WIDTHS``（列字母口径）换成列号口径，便于与下发直接比。"""
    from test.backend.test_gage_sheet_shape import PIN_SUMMARY_WIDTHS
    out = {}
    for letter, width in PIN_SUMMARY_WIDTHS.items():
        col_idx, _row = excelize.cell_name_to_coordinates(f'{letter}1')
        out[col_idx] = width
    return out


class GageAppliedWidthsMatchFullScanTests(SimpleTestCase):
    """钉死形状与对抗形状上，「记账下发的列宽」与「整表回读算的列宽」逐列相等。"""

    def assertParity(self, order, applied, oracle, label):
        """三条一起钉：值相等、按列升序下发、每列恰好一次（区间/重复下发都不是旧通路那一手）。"""
        self.assertEqual(applied, oracle, f'{label}: 下发 {applied} ≠ 整表回读 {oracle}')
        self.assertEqual(order, sorted(order), f'{label}: 列宽下发不是按列升序 {order}')
        self.assertEqual(len(order), len(set(order)), f'{label}: 同一列被下发多次 {order}')

    def test_pinned_narrow_shape(self):
        order, applied, oracle = _measure('narrow', datasets('narrow'))
        self.assertParity(order, applied, oracle, 'narrow')
        self.assertEqual(applied, _pin_widths_by_index(), '窄表列宽偏离钉死基线')

    def test_pinned_wide_shape(self):
        order, applied, oracle = _measure('wide', datasets('wide'))
        self.assertParity(order, applied, oracle, 'wide')

    def test_adversarial_long_param_name_hits_the_clamp(self):
        """超长参数名那一列必须被钳到 42.0（而不是按内容给 53.5）。"""
        rows = [1.0, 2.0, 3.0, 4.0]
        files = [synthetic_dataset(f'pin{i}.csv', {LONG_PARAM: rows}) for i in (1, 2)]
        order, applied, oracle = _measure('超长参数名', files)
        self.assertParity(order, applied, oracle, '超长参数名')
        self.assertEqual(oracle[3], 42.0, f'基准自己没钳到 42.0：{oracle}')

    def test_adversarial_east_asian_param_name_counts_wide_chars_as_two(self):
        """6 个汉字 ⇒ 14.5；把宽字符按 1 计会得 8.5（不是被 8.0 下界掩盖的那种巧合）。"""
        rows = [1.0, 2.0, 3.0, 4.0]
        files = [synthetic_dataset(f'pin{i}.csv', {WIDE_PARAM: rows}) for i in (1, 2)]
        order, applied, oracle = _measure('宽字符参数名', files)
        self.assertParity(order, applied, oracle, '宽字符参数名')
        self.assertEqual(oracle[3], 14.5, f'基准口径自查（6 字宽=12 ⇒ 14.5）：{oracle}')
        self.assertEqual(applied.get(3), 14.5, f'宽字符列下发 {applied.get(3)}，应为 14.5')

    def test_adversarial_missing_limit_writes_na_text(self):
        """缺规格限 ⇒ R&R% 与 Fail Level 写 'N/A' 文本，Y 列不再是公式；宽度仍须相等。"""
        rows = [1.0, 2.0, 3.0, 4.0]
        files = [
            synthetic_dataset('pin1.csv', {'PAR0001': rows},
                              mins={'PAR0001': None}, maxs={'PAR0001': None}),
            synthetic_dataset('pin2.csv', {'PAR0001': rows},
                              mins={'PAR0001': ''}, maxs={'PAR0001': ''}),
        ]
        order, applied, oracle = _measure('缺规格限', files)
        self.assertParity(order, applied, oracle, '缺规格限')

    def test_adversarial_file_without_data(self):
        """有一趟写的是整排空串 ⇒ 那些格一个都不该进宽度账（空串在两侧都不计数）。"""
        rows = [1.0, 2.0, 3.0]
        files = [
            synthetic_dataset('pin1.csv', {'PAR0001': rows}),
            synthetic_dataset('pin2.csv', {'PAR0001': [''] * 3}),
        ]
        order, applied, oracle = _measure('空数据文件', files)
        self.assertParity(order, applied, oracle, '空数据文件')

    def test_adversarial_whole_float_and_tiny_limit(self):
        """整数值浮点与小数量级规格限：Go 读回 '6' / '0.00001'，Python ``str`` 是 '6.0' / '1e-05'。

        这两类正是「记账侧直接用 str() 就会把宽度算长/算短」的形状，走真实生成通路钉一次。
        """
        rows = [6.0, 6.0, 6.0, 6.0]
        files = [
            synthetic_dataset(f'pin{i}.csv', {'PAR0001': rows},
                              mins={'PAR0001': '0.00001'}, maxs={'PAR0001': '6.0'})
            for i in (1, 2)
        ]
        order, applied, oracle = _measure('整数浮点与小数量级', files)
        self.assertParity(order, applied, oracle, '整数浮点与小数量级')

    def test_adversarial_beyond_15_significant_digits(self):
        """超过 15 位有效数字的规格限：Go 读回会舍入（Python str 不会）⇒ 仍须与基准相等。

        记账侧对这种值走「整表回读」回退（见 ``ColumnWidthTracker``）—— 回退付的是时间，
        不是宽度；这条判据钉的就是「回退以后仍然等价」。
        """
        rows = [1.0000000000000002, 2.0, 3.0, 4.0]
        files = [
            synthetic_dataset(f'pin{i}.csv', {'PAR0001': rows},
                              mins={'PAR0001': '0.00010000000000000002'},
                              maxs={'PAR0001': '10000000000000.5'})
            for i in (1, 2)
        ]
        order, applied, oracle = _measure('超 15 位有效数字', files)
        self.assertParity(order, applied, oracle, '超 15 位有效数字')


class WidthScanReferenceIsRealTests(SimpleTestCase):
    """基准自己必须先是那条旧通路，否则上面的平价断言全是空转。"""

    def test_reference_replica_reproduces_the_pinned_product_widths(self):
        """基准复刻算出的宽度 == 产物 XML 里钉死的 ``PIN_SUMMARY_WIDTHS``（逐字母）。"""
        from test.backend.test_gage_sheet_shape import PIN_SUMMARY_WIDTHS
        handle = excelize.open_reader(build_shape('narrow'))
        try:
            got = as_letters(widths_by_full_scan(handle, SUMMARY_SHEET, min_row=MIN_ROW))
        finally:
            handle.close()
        self.assertEqual(got, PIN_SUMMARY_WIDTHS, '基准复刻与产物钉值不一致 ⇒ 基准不是那条旧通路')

    def test_reference_replica_is_an_independent_full_scan(self):
        """基准必须自己走 ``get_cols``，且不许从生产模块取任何东西（含 ``import … as`` 别名）。"""
        src = inspect.getsource(ref)
        self.assertIn('get_cols', src, '基准不再是整表回读 ⇒ 平价判据失去基准')
        self.assertNotIn('scan_column_widths(', src, '基准改调生产实现 ⇒ 同错的变异两边一起绿')
        from_prod = [m for m in _imported_modules(ref) if m.split('.')[0] == 'apps']
        self.assertFalse(from_prod,
                         f'基准从生产模块取常数/函数 ⇒ 钳位或宽字符口径改错无人红：{from_prod}')
