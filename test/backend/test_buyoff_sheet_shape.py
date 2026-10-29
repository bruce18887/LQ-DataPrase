"""A5 第三段：buyoff 统计带「下发形状」回归（产物字节 / 逐格读回+预言 / 跨界上界 / 游程下发）。

钉的是 **FFI 下发形状**，不是某一行实现，分层与 ``test_gage_sheet_shape.py`` 同源。
输入帧与游程预言在 ``buyoff_sheet_fixture.py``，XML 读回在 ``sheet_readback.py``（与 gage 段
共用那一份，两条口径的「为什么」写在那份模块文档里）；分文件只因 600 行闸，四条判据全在本文件。

① 产物 xlsx 的 sha256 与**改前基线**逐字节相等。可复现性在钉住的依赖版本下成立
   （``requirements/base.txt`` 里钉的 ``excelize==0.0.9``、``numpy==2.4.6``）：zip 成员的
   ``date_time`` 恒为 ``(1980,0,0,0,0,0)``、``docProps/core.xml`` 的时间是 excelize 硬编码值
   ⇒ 无易变成员。**换 excelize/numpy 版本要先重测这条再改本文件的钉值**。
② 逐格读回（非空格子的样式内容序列、按行样式游程、列宽、合并区）与基线一致；另有一条
   **输入模型预言**：统计带每一格最终是 ``data`` 还是 ``na`` 样式，由夹具拿同一份
   ``datasets``/``all_stats`` 独立算一遍（三分支语义照 ``build_buyoff_form`` 统计带内层
   循环的那一条：``if is_limit`` / ``elif param in all_stats.get(...)`` / 收尾 ``else``），
   与 XML 读回逐格比 —— ①②红时用这条把偏差定位到「哪一行的哪一段样式真的变了」。
③ 列字母换算（每次都要跨 Go 边界，实测实现见 ``excelize.py:6736``）只随**列数**增长，
   不随角色数（=统计带的行数）增长。
④ 统计带同一行内样式的逐格重复下发必须收成**游程区间**：``set_cell_style(左上, 右下, id)``
   是覆盖写、不 append/merge（``excelize.py:5432-5434``），所以「区间覆盖的格子集合 / 每格拿到的
   id / 值与样式的先后次序」三者都与原逐格相同才叫等价 ⇒ 三者各有一条判据，另有一条
   「全程零次 ``set_col_style``」守着（它是整列语义、会把样式写进 ``<col>`` 并覆写列宽，
   与区间下发不等价）。

上面那两处 ``excelize.py:…`` 是**第三方取证引用**，与仓内文件的行号不是一回事：它们指
site-packages 里 ``excelize==0.0.9`` 那个单文件的行号，**仓内 grep 不到**，换 excelize
版本后必然失效 ⇒ 复用前先按新版本重核，别拿它当「产品侧同名文件」的坐标。

runner: ``python -X utf8 manage.py test test.backend.test_buyoff_sheet_shape``
"""
import hashlib
import json
from unittest import mock

import excelize
from django.test import SimpleTestCase

from apps.buyoff import excelize_layout as layout
from test.backend.buyoff_sheet_fixture import (
    BAND_ROW_COUNT, FIRST_BAND_ROW, SHEET, SHAPES, TEST_COL_START,
    _band_rows, _band_spans, _build, _expected_cells, _label_by_id, _last_col,
    _payload, _readback, _record, _safe_close, _save_bytes,
)
from test.backend.sheet_readback import canonical, runs_from_mapping

# ────────────────────────── 钉住的基线值（改前实测；改产品前后各跑一次自证没动） ──────────────────────────

PIN_SHA256 = {
    'mixed': '70ac83c3a3a1add1b3b442cb23759006101413938c1cad31a7e9d37f088f6fa8',
    'all_na': '54d52eb40eb7c12b3b89a3ce58a38c8587855853992f26edd968d50907b69aec',
    'four_roles': '9cb6f0bb8692a3fa4f574c2bcb0db271127cca2b28f98275135a26d0fed317e0',
}
PIN_READBACK_DIGEST = {
    'mixed': 'd4ddd0fc26a5bc993d34e81ff9b11b64e3ac039879adc14056700d8c3a509903',
    'all_na': '268c59029c4a690a40f65872f5e830da7556aa2647c8a16a85e272fa8d013fb5',
    'four_roles': 'd4467070fb6db624018354e6fb906587ab7c91c933c5abd508cb8cadfeb4a306',
}
#: 统计带的实测游程基线（FT 段，含 A/B 两列）：6=Lower Limit / 8=Min / 12=STD
#: 数据列域（C..K）里分别 5 / 3 / 3 段 —— na 与 data 混排，是 M-a 的靶形。
PIN_BAND_RUNS = {
    '6': [[1, 1, '9b67d1321f92'], [2, 2, '1ea86322fac9'], [3, 3, '753007a5dbf4'],
          [4, 5, '720a5569dee5'], [6, 9, '753007a5dbf4'], [10, 10, '720a5569dee5'],
          [11, 11, '753007a5dbf4']],
    '8': [[2, 2, '1ea86322fac9'], [3, 8, '753007a5dbf4'], [9, 9, '720a5569dee5'],
          [10, 11, '753007a5dbf4']],
    '12': [[2, 2, '1ea86322fac9'], [3, 7, '753007a5dbf4'], [8, 9, '720a5569dee5'],
           [10, 11, '753007a5dbf4']],
}
#: 列宽口径来自 ``build_buyoff_form`` 末尾「── Column widths ──」那一段的三次
#: ``set_col_width``（A=8、B=22、C.. 各 18）；
#: 本次不动列宽 ⇒ 改这里的钉值等于改产物
PIN_WIDTHS = {'A': 8.0, 'B': 22.0, 'C': 18.0, 'D': 18.0, 'E': 18.0, 'F': 18.0,
              'G': 18.0, 'H': 18.0, 'I': 18.0, 'J': 18.0, 'K': 18.0}


# ────────────────────────── ① 产物字节 ──────────────────────────


class BuyoffArtifactBytesTests(SimpleTestCase):
    """产物 xlsx 逐字节等于改前基线：游程区间化与列字母预计算不许动一个字节。"""

    def test_bytes_equal_pinned_baseline(self):
        for shape in SHAPES:
            with self.subTest(shape=shape):
                f = _build(shape)
                self.addCleanup(_safe_close, f)
                first = hashlib.sha256(_save_bytes(f)).hexdigest()
                again_f = _build(shape)
                self.addCleanup(_safe_close, again_f)
                again = hashlib.sha256(_save_bytes(again_f)).hexdigest()
                # 判据自己先要可复现：同一输入、同进程内两次构建必须同串
                self.assertEqual(first, again, f'{shape} 两次构建字节不同')
                self.assertEqual(first, PIN_SHA256[shape],
                                 f'{shape} 产物偏离改前基线 ⇒ 版式真变了')


# ────────────────────────── ② 逐格读回 + 输入模型预言 ──────────────────────────


class BuyoffReadbackEquivalenceTests(SimpleTestCase):
    """逐格读回与基线一致；统计带每一格的最终样式与预言算出的那一格相同。"""

    def test_full_readback_digest(self):
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.assertEqual(_readback(shape)['digest'], PIN_READBACK_DIGEST[shape])

    def test_band_runs_equal_pinned_runs(self):
        """游程基线是真判据：逐行比对实测读回游程（样式内容哈希，不是 id）。"""
        runs = _readback('mixed')['body']['sheets'][SHEET]['runs']
        band = [str(row) for row, _role, _stat in _band_rows('mixed')]
        for row in band:
            self.assertIn(row, runs, f'带行 {row} 在读回里不存在 ⇒ 行域假设失效')
        for row in PIN_BAND_RUNS:
            self.assertIn(row, band, f'{row} 不是统计带的行')
            with self.subTest(row=row):
                self.assertEqual(runs[row], PIN_BAND_RUNS[row])

    def test_band_row_style_matches_input_model(self):
        """预言 ↔ 读回：每一段的列区间与顺序逐字相等，且 label↔样式内容是双射。

        M-a（把游程段扩到盖住相邻不同 id 的段）会把相邻两格写成同一个样式内容
        ⇒ 要么段边界与预言不同，要么「na 对应两种内容 / 同一样式内容被期望成两种
        label」，这条当场红，不用等 ① 的字节红才知道。
        """
        for shape in SHAPES:
            runs = _readback(shape)['body']['sheets'][SHEET]['runs']
            expected = _expected_cells(shape)
            to_key, from_key = {}, {}
            for row in sorted(expected):
                segs = [seg for seg in runs[str(row)] if seg[0] >= TEST_COL_START]
                want = runs_from_mapping(expected[row])
                with self.subTest(shape=shape, row=row):
                    self.assertEqual([seg[:2] for seg in segs], [seg[:2] for seg in want],
                                     f'第 {row} 行的游程边界与预言不同')
                    for (col_from, col_to, key), (_a, _b, label) in zip(segs, want):
                        self.assertLessEqual(col_to, _last_col(shape))
                        self.assertEqual(to_key.setdefault(label, key), key,
                                         f'{label} 样式出现两种内容 ⇒ 预言与读回不能同时成立')
                        self.assertEqual(from_key.setdefault(key, label), label,
                                         '同一样式内容被期望成两种 label')
            with self.subTest(shape=shape, check='bijection'):
                self.assertEqual(len(to_key), len(from_key), 'label↔样式 映射必须双射')

    def test_band_columns_covered_exactly_once(self):
        """每行 C..末列都被覆盖恰好一次：既不能漏格，也不能把 B 列的行名样式带进来。"""
        for shape in SHAPES:
            runs = _readback(shape)['body']['sheets'][SHEET]['runs']
            for row in sorted(_expected_cells(shape)):
                covered = [col for seg in runs[str(row)] if seg[0] >= TEST_COL_START
                           for col in range(seg[0], seg[1] + 1)]
                with self.subTest(shape=shape, row=row):
                    self.assertEqual(covered, list(range(TEST_COL_START, _last_col(shape) + 1)),
                                     f'第 {row} 行的数据列覆盖集合不等于 C..{_last_col(shape)}')

    def test_column_widths_are_the_pinned_widths(self):
        self.assertEqual(_readback('mixed')['body']['sheets'][SHEET]['widths'], PIN_WIDTHS)

    def test_scanner_sees_styled_blank_cells_that_dimension_omits(self):
        """扫描器自证：读回的格子集合含「有样式但无值」的格子，而 ``<dimension>`` 盖不住它们。

        这条不给产品记分，只保证 ② 的取数来源没有静默漏读 —— 漏读时游程判据会看着像绿。
        """
        rb = _readback('mixed')
        nonempty = {ref for ref, _key in rb['body']['sheets'][SHEET]['nonempty_styles']}
        # PAR0004（下标 3 ⇒ 第 6 列 = F）在 FT 的 Min 行（第 8 行）走三分支的 else：只有样式、没有值
        self.assertIn((8, 6), rb['refs'][SHEET], '「有样式但空值」的格子没被读回来')
        self.assertNotIn('F8', nonempty, '该格本不该有值，读成非空说明 nonempty 判据反了')
        dim = rb['dimension'][SHEET]
        self.assertTrue(dim, '没读到 <dimension>，这条自证变成了空转')
        # 实测 dimension 是 'A1'（单个 ref，不是区间）⇒ 它连统计带的第一行都盖不住。
        col, row = excelize.cell_name_to_coordinates(dim.split(':')[-1])
        self.assertLess(row, FIRST_BAND_ROW + BAND_ROW_COUNT,
                        f'<dimension> 说只到 {dim}，那它根本盖不住统计带 ⇒ 必须按 XML 读')
        self.assertLess(col, _last_col('mixed'),
                        f'<dimension> 说只到 {dim}，那它盖不住统计带的末列 ⇒ 必须按 XML 读')

    def test_shared_fixture_state_cannot_pollute_another_case(self):
        """夹具自证：读回缓存与形状表被多个用例复用 ⇒ 一处改动不得影响另一处的取数。

        复审当场注入成功过一次：拿到共享的读回对象后改掉某一行游程的首段，后面那条覆盖
        判据比的就成了「上一个用例改了什么」而不是产品下发的形状 —— 判据看着还绿，实际
        已经空转。这条只钉夹具自己的契约（返回新副本 + 形状表深层只读），不钉产物字节
        ⇒ 任何产品变异下它都应当保持绿（红 = 夹具被改回共享可变对象，不是产品变好/变坏）。
        """
        rb = _readback('mixed')
        pristine = canonical(rb['body']['sheets'][SHEET]['runs'])
        rb['body']['sheets'][SHEET]['runs'][str(FIRST_BAND_ROW)][0][:2] = [-999, -999]
        self.assertEqual(canonical(_readback('mixed')['body']['sheets'][SHEET]['runs']),
                         pristine, '改一份读回结果影响了另一份 ⇒ 夹具返回的是共享可变对象')
        with self.assertRaises(TypeError):
            SHAPES['mixed'] = {}                      # 形状表只读：换整个形状当场报错
        with self.assertRaises(TypeError):
            SHAPES['mixed']['roles'] = ('X',)         # 深层只读：改内层的角色也一样


# ────────────────────────── ③ 跨界调用上界 ──────────────────────────

#: 每列被换算字母的次数上界：预计算表 1 次 + 行 3/4/5 各 1 次 + Result 四行各 1 次
#: + Comments 行 1 次 + 列宽 1 次 = 10，留 1 次余量。**统计带那 BAND_ROW_COUNT×角色数 次
#: 必须为 0** —— 它才是本次要消掉的「随行数增长」。
LETTER_CALL_BOUND_PER_COLUMN = 11


class BuyoffColumnLetterBoundaryTests(SimpleTestCase):
    """列字母换算只随列数增长：只要它随角色数（统计带行数）增长就必须红。"""

    def _letter_calls(self, shape):
        seen = []
        origin = excelize.column_number_to_name

        def spy(col):
            seen.append(col)
            return origin(col)

        f = excelize.new_file()
        self.addCleanup(_safe_close, f)
        with mock.patch.object(excelize, 'column_number_to_name', spy):
            layout.build_buyoff_form(f, *_payload(shape))
        return len(SHAPES[shape]['params']), len(seen)

    def test_calls_bounded_by_column_count(self):
        for shape in SHAPES:
            ncols, calls = self._letter_calls(shape)
            rows = len(_band_rows(shape))
            with self.subTest(shape=shape, ncols=ncols, band_rows=rows):
                self.assertLessEqual(
                    calls, LETTER_CALL_BOUND_PER_COLUMN * ncols,
                    f'{rows} 行 × {ncols} 列换算了 {calls} 次字母 ⇒ 表没建在行循环外')

    def test_row_count_does_not_add_calls(self):
        """mixed(3 角色) 与 four_roles(4 角色) 同列数：多 14 行不得多算一次字母。"""
        _ncols, three = self._letter_calls('mixed')
        _ncols2, four = self._letter_calls('four_roles')
        self.assertEqual(three, four, f'角色从 3 涨到 4 让列字母从 {three} 涨到 {four}')



class BuyoffStyleDeliveryTests(SimpleTestCase):
    """统计带的样式下发：区间 = 预言游程，格子集合/id/先后次序三者都不许变。"""

    def test_whole_build_never_falls_back_to_whole_column_style(self):
        """``set_col_style`` 是整列语义（写 ``<col>`` 级样式、覆写列宽），与区间下发不等价。"""
        rec, f = _record('mixed')
        self.addCleanup(_safe_close, f)
        self.assertEqual(rec['col'], [], f'出现了整列样式下发：{rec["col"]}')

    def test_band_delivers_exactly_the_expected_runs(self):
        """每行的下发区间逐段等于预言游程（段数、边界、顺序），且该段用的样式就是预言那段。"""
        rec, f = _record('mixed')
        self.addCleanup(_safe_close, f)
        expected = _expected_cells('mixed')
        hi = _last_col('mixed')
        band_ids = [sid for row in expected
                    for _l, _r, sid in _band_spans(rec, row, TEST_COL_START, hi)]
        label_of = _label_by_id(f, band_ids)
        for row in sorted(expected):
            spans = [[l, r, label_of[sid]]
                     for l, r, sid in _band_spans(rec, row, TEST_COL_START, hi)]
            with self.subTest(row=row):
                self.assertEqual(spans, runs_from_mapping(expected[row]),
                                 f'第 {row} 行的下发 ≠ 预言游程：{spans}')

    def test_band_call_count_is_run_count_not_cell_count(self):
        """合并必须真的发生：带内下发总次数 == 游程段数 < 格子数。"""
        rec, f = _record('mixed')
        self.addCleanup(_safe_close, f)
        expected = _expected_cells('mixed')
        hi = _last_col('mixed')
        delivered = sum(len(_band_spans(rec, row, TEST_COL_START, hi)) for row in expected)
        want = sum(len(runs_from_mapping(cells)) for cells in expected.values())
        cells_total = sum(len(cells) for cells in expected.values())
        self.assertEqual(delivered, want, '下发次数 ≠ 游程段数 ⇒ 要么没合要么多刷')
        self.assertLess(want, cells_total, '预言游程段数等于格子数 ⇒ 这个形状证不了合并')

    def test_value_then_style_order_is_preserved(self):
        """次序判据（三条一起）：

        ① 每格的值早于覆盖它的那次下发；
        ② 一行内的下发严格自左至右、互不重叠；
        ③ 覆盖 ``[a,b]`` 的那次下发早于本行 ``b`` 之后的**任何**一次值写。

        原逐格的次序是 值(c)→样式(c)→值(c+1)→…，所以 ①②③ 在游程化**之前**就成立，
        游程化之后必须照样成立 —— 它钉的是「段的下发时机 == 段末那一格原逐格下发的时机」。
        把游程收尾挪到下一格的值写完之后（M-c），或拆成「先写完所有值再刷样式」两趟遍历，
        都会破 ③ / ①③。
        """
        rec, f = _record('mixed')
        self.addCleanup(_safe_close, f)
        value_seq = {}
        style_events = []
        for i, ev in enumerate(rec['events']):
            if ev[1] != SHEET:
                continue
            if ev[0] == 'value':
                value_seq.setdefault((ev[2], ev[4]), i)
            else:
                style_events.append((i, ev))
        expected = _expected_cells('mixed')
        hi = _last_col('mixed')
        for row in sorted(expected):
            row_styles = [(i, ev) for i, ev in style_events
                          if ev[2] <= row <= ev[3] and ev[4] <= hi and ev[5] >= TEST_COL_START]
            prev_end = 0
            for i, ev in row_styles:
                left, right = max(ev[4], TEST_COL_START), min(ev[5], hi)
                with self.subTest(row=row, col=left):
                    self.assertGreater(left, prev_end,
                                       f'第 {row} 行的下发重叠或乱序：{row_styles}')
                    prev_end = right
                    for col in range(left, right + 1):
                        seq = value_seq.get((row, col))
                        if seq is not None:
                            self.assertLess(seq, i,
                                            f'第 {row} 行第 {col} 列的值写在了样式之后')
                    later = [seq for (r, c), seq in value_seq.items()
                             if r == row and TEST_COL_START <= c <= hi and c > right]
                    if later:
                        self.assertLess(i, min(later),
                                        f'第 {row} 行 [{left},{right}] 的收尾晚于后续格的值写')


# ────────────────────────── 钉值与预言的「不是永真」自检 ──────────────────────────


class BuyoffPinsLookRealTests(SimpleTestCase):
    """基线常量表与预言表本身不许是空的或占位值 —— 否则上面几条判据全都恒绿。"""

    def test_pins_are_filled(self):
        for table in (PIN_SHA256, PIN_READBACK_DIGEST):
            self.assertNotIn('PLACEHOLDER', json.dumps(table))
            for shape in SHAPES:
                self.assertRegex(table[shape], r'^[0-9a-f]{64}$')
        self.assertNotIn('PLACEHOLDER', json.dumps(PIN_BAND_RUNS))
        self.assertTrue(PIN_BAND_RUNS, '游程基线表是空的')
        self.assertTrue(PIN_WIDTHS, '列宽基线是空的')
        self.assertTrue(all(v > 0 for v in PIN_WIDTHS.values()))
        for row, segs in PIN_BAND_RUNS.items():
            self.assertTrue(segs, f'第 {row} 行的游程基线是空的')
            for seg in segs:
                self.assertLessEqual(seg[0], seg[1])
                self.assertRegex(seg[2], r'^[0-9a-f]{12}$')

    def test_band_rows_assumption_matches_the_written_labels(self):
        """行域假设要对着产品真写出来的 B 列行名校验，否则 ②④ 比的是别的行。"""
        f = _build('mixed')
        self.addCleanup(_safe_close, f)
        for row, _role, (stat_name, _key, _is_limit) in _band_rows('mixed'):
            self.assertEqual(f.get_cell_value(SHEET, f'B{row}'), stat_name, f'第 {row} 行')

    def test_shapes_really_mix_na_and_data(self):
        """预言不许退化成一色：混排形状既有 na 又有 data，且有 4 段以上的行。"""
        cells = _expected_cells('mixed')
        labels = {v for row in cells.values() for v in row.values()}
        self.assertEqual(labels, {'na', 'data'})
        seg_counts = [len(runs_from_mapping(row)) for row in cells.values()]
        self.assertGreaterEqual(max(seg_counts), 4, '混排形状游程段太少，判据会空转')
        all_na = _expected_cells('all_na')
        self.assertEqual({v for row in all_na.values() for v in row.values()}, {'na'})
