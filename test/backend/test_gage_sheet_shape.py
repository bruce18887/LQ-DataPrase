"""A5 第二段：gage 工作表「下发形状」回归（产物字节 / 逐格读回 / 跨界调用上界 / 冗余样式）。

钉的是 **FFI 下发形状**，不是某一行实现：

① 产物 xlsx 的 sha256 与**改前基线**逐字节相等。可复现性在钉住的依赖版本下成立
   （``requirements/base.txt`` 里钉的 ``excelize==0.0.9``、``numpy==2.4.6``）：同进程两次 /
   跨进程两次 / 换构建顺序全部相等；zip 成员的 ``date_time`` 恒为 ``(1980,0,0,0,0,0)``
   （月份/日都为 0，不是 ``(1980,1,1,...)``），**成员数随形状变**（本文件两份形状是
   4 文件 14 个 / 2 文件 12 个，别把具体成员数当常量），``docProps/core.xml`` 的时间是
   excelize 硬编码值 ⇒ 无易变成员。**换 excelize/numpy 版本要先重测这条再改本文件的钉值**。
② 逐格读回（非空格子的样式内容序列、按行样式游程、列宽、合并区）与基线一致 ——
   ①红时用这条定位「版式真变了」还是「只是样式编号平移了」；
③ 列字母换算（每次都要跨 Go 边界）只随**列数**增长，不随行数增长；
④ 同一行内同一样式的**逐格重复下发**必须收成区间调用（``set_cell_style`` 的
   top-left / bottom-right 传区间是同一件事的批量写法；``set_col_style`` 是整列语义、
   会把样式写到 ``<col>`` 级、不等价 ⇒ 另有一条「全程零次 set_col_style」守着）。

读回实现在 ``sheet_readback.py`` —— 与 buyoff 段共用那一份（原先两边各写一份，78 行逐字
重复且已漂移：一份用 sheet XML 的 ``r=`` 属性、另一份由坐标反推 ref）。「为什么以 sheet
XML 为准 / 为什么不信 ``<dimension>`` / 为什么样式取内容不取 id / 为什么列宽自己展开
``<col min max>``」四条口径都写在那份模块文档里。为什么它落在 ``test/backend/`` 而不是
import ``tasks/a5_readback.py``：``tasks/`` 不入库（``.gitignore`` 的 ``/tasks/*``），CI 的
干净检出里那个路径根本不存在，判据必须能独立跑。

输入形状（两份钉死的 shape 与它的合成帧）住在 ``gage_shape_fixtures.py``，被本文件与
「列宽 = 整表回读」的平价判据 ``test_gage_column_width_parity.py`` 共用：两组判据必须跑在
同一批形状上，各自造数据就等于各算各的列宽。

runner: ``python -X utf8 manage.py test test.backend.test_gage_sheet_shape``
"""
import hashlib
import json
from functools import partial
from unittest import mock

import excelize
from django.test import SimpleTestCase

from apps.common.constants import NON_NUMERIC_KEYWORDS
from apps.gage.gage_file_sheet import write_file_sheet
from apps.gage.gage_legacy_builder import build_gage_summary_excel
from apps.gage.gage_styles import create_file_sheet_styles
from apps.gage.gage_summary_sheet import (
    COL_RR_PCT, SUMMARY_HEADER_COUNT, SUMMARY_SHEET,
    write_cell,
)
from test.backend.gage_shape_fixtures import (
    SHAPES, build_shape, datasets, file_info, group_rows,
)
from test.backend.sheet_readback import readback

# ────────────────────────── 版式常量（读回实现见 sheet_readback.py） ──────────────────────────

#: Summary 组框的「中间列」区间与最后一列的列号（都从版式常量推，不写魔法数）
MID_COL_FROM, MID_COL_TO = 2, SUMMARY_HEADER_COUNT - 1
LAST_COL_IDX = SUMMARY_HEADER_COUNT


# ────────────────────────── 钉住的基线值（改前实测；在钉住的 excelize/numpy 版本下由改前态重建即得） ──────────────────────────

PIN_SHA256 = {
    'narrow': '543d2b4fcbfdfe03453e0bbe4dece56ad0f0d6ba34da9d383c7e75523ca22627',
    'wide': 'eacd2e546736523e2388bd2c519653839732c0366f7e27aa226e5f4d9db21991',
}
PIN_READBACK_DIGEST = {
    'narrow': '3ec1576ac4840bb0329201af3ef916bc112d57eef65667e4916569f89c4c97ed',
    'wide': '926eb895446bdd9851423165fdd660bc1270126bfb8541151a102a3137ef1fa7',
}
# Summary 的列宽（XML 口径，autofit 的落点）：N 列没有表头文字，故不在表里
PIN_SUMMARY_WIDTHS = {
    'A': 13.5, 'AA': 10.5, 'B': 11.5, 'C': 11.5, 'D': 8.0, 'E': 10.5, 'F': 11.5,
    'G': 8.0, 'H': 9.5, 'I': 8.5, 'J': 9.5, 'K': 9.5, 'L': 8.5, 'M': 9.5, 'O': 9.5,
    'P': 8.5, 'Q': 8.5, 'R': 9.5, 'S': 9.5, 'T': 10.5, 'U': 11.5, 'V': 15.5,
    'W': 17.5, 'X': 8.0, 'Y': 8.0, 'Z': 12.5,
}
# 按行样式游程：组首（被 R&R% 打断）/ 组中（数据带原色）/ 组末 / Average 行
PIN_SUMMARY_RUNS = {
    '12': [[1, 1, '7c769b4d36f2'], [2, 24, 'c81a9ffb185d'], [25, 25, '7e7eb6488e04'],
           [26, 26, 'c81a9ffb185d'], [27, 27, '18bbe182e247']],
    '13': [[1, 1, 'cdafd1863e46'], [2, 26, '753007a5dbf4'], [27, 27, 'a6aa7cace69d']],
    '15': [[1, 1, '7b2c3d093d58'], [2, 26, 'c4b82a7556f8'], [27, 27, 'bdec6f9bacd8']],
    '36': [[1, 1, 'cdafd1863e46'], [22, 23, '55561a4462a0']],
}
# 第一张文件表（narrow，last_col=17）的表头带（8）、灰带（13）、统计带首行（115）逐行游程。
# 统计带这一批从逐格收成两段区间下发（B..G 灰底 / H..last_col 边框），读回游程与改前**逐字
# 相同** ⇒ 钉值不变。这张表本身不是承重判据（它的红必然连带 ② 的 digest 红），用途是
# ①②红时把偏差定位到具体行；真正钉「同行同 id 不许多次下发」的是判据 ④。
PIN_FILE_RUNS = {
    '8': [[1, 1, '55561a4462a0'], [8, 17, '7cad170b9655']],
    '13': [[2, 17, '2efcffe74a11']],
    '115': [[1, 1, '55561a4462a0'], [2, 7, '419b4773c5fb'], [8, 17, 'e50acb36f53a']],
}


# ────────────────────────── ① 产物字节 ──────────────────────────


class GageArtifactBytesTests(SimpleTestCase):
    """产物 xlsx 逐字节等于改前基线：区间化与预计算不许动一个字节。"""

    def test_bytes_equal_pinned_baseline(self):
        for shape in SHAPES:
            with self.subTest(shape=shape):
                first = hashlib.sha256(build_shape(shape)).hexdigest()
                again = hashlib.sha256(
                    build_gage_summary_excel(datasets(shape))).hexdigest()
                # 判据自己先要可复现：同一输入、同进程内两次构建必须同串
                self.assertEqual(first, again, f'{shape} 两次构建字节不同')
                self.assertEqual(first, PIN_SHA256[shape],
                                 f'{shape} 产物偏离改前基线 ⇒ 版式真变了')


# ────────────────────────── ② 逐格读回 ──────────────────────────


class GageReadbackEquivalenceTests(SimpleTestCase):
    """逐格读回与基线一致：非空格样式序列、按行游程、列宽、合并区。"""

    def test_full_readback_digest(self):
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.assertEqual(readback(build_shape(shape))['digest'],
                                 PIN_READBACK_DIGEST[shape])

    def test_summary_row_style_runs_are_the_pinned_runs(self):
        rb = readback(build_shape('narrow'))
        runs = rb['body']['sheets'][SUMMARY_SHEET]['runs']
        for row in PIN_SUMMARY_RUNS:
            with self.subTest(row=row):
                self.assertEqual(runs[row], PIN_SUMMARY_RUNS[row])

    def test_file_sheet_row_style_runs_are_the_pinned_runs(self):
        """PIN_FILE_RUNS 从「只被自检扫过形状」变成真判据：逐行比对实测读回游程。"""
        sheet = datasets('narrow')[0]['sheet_name']
        runs = readback(build_shape('narrow'))['body']['sheets'][sheet]['runs']
        for row in PIN_FILE_RUNS:
            with self.subTest(row=row):
                self.assertEqual(runs[row], PIN_FILE_RUNS[row])

    def test_group_first_row_run_is_split_by_rr_pct(self):
        """组首行：A 粗左边 / 中间列粗顶边 / Y 是 R&R% 基样式 / Z 粗顶边 / AA 粗右边 = 5 段。

        这条钉住「按游程切段、别整行框」——把 A 或 AA 也框进区间会把粗边框覆盖掉。
        """
        rb = readback(build_shape('narrow'))
        runs = rb['body']['sheets'][SUMMARY_SHEET]['runs']
        starts, _ends, _middles = group_rows('narrow')
        first = str(min(starts))
        seg = runs[first]
        self.assertEqual(len(seg), 5, f'组首行 {first} 的游程 = {seg}')
        self.assertEqual(seg[0][:2], [1, 1])                     # A 单独一段
        self.assertEqual(seg[1][0], MID_COL_FROM)                 # 中间列起
        self.assertEqual(seg[2][0], COL_RR_PCT)                   # 被 R&R% 打断
        self.assertEqual(seg[3], [COL_RR_PCT + 1, COL_RR_PCT + 1, seg[1][2]])
        self.assertEqual(seg[4][:2], [LAST_COL_IDX, LAST_COL_IDX])
        self.assertNotEqual(seg[2][2], seg[1][2], 'R&R% 格的样式必须与中间列不同')

    def test_middle_group_row_runs_keep_side_borders_out_of_the_range(self):
        """组内中间行：A 粗左边 + 中间列一整段（数据带原色）+ AA 粗右边 = 3 段游程。"""
        rb = readback(build_shape('narrow'))
        runs = rb['body']['sheets'][SUMMARY_SHEET]['runs']
        _starts, _ends, middles = group_rows('narrow')
        for row in sorted(middles)[:3]:
            seg = runs[str(row)]
            self.assertEqual(len(seg), 3, f'第 {row} 行游程 = {seg}')
            self.assertEqual(seg[0][:2], [1, 1])
            self.assertEqual(seg[1][:2], [MID_COL_FROM, MID_COL_TO])
            self.assertEqual(seg[2][:2], [LAST_COL_IDX, LAST_COL_IDX])

    def test_summary_column_widths(self):
        rb = readback(build_shape('narrow'))
        self.assertEqual(rb['body']['sheets'][SUMMARY_SHEET]['widths'],
                         PIN_SUMMARY_WIDTHS)


# ────────────────────────── ③ 跨界调用上界 ──────────────────────────

#: 每一列被换算字母的次数上界：一张表 + 列头 + 统计行，全是**按列**的常数趟数。
#: 数据带最多 100 行 × 每列一次的那条通路绝不能进这个式子（它才是本次要消掉的）。
LETTER_CALL_BOUND_PER_COLUMN = 5


class GageColumnLetterBoundaryTests(SimpleTestCase):
    """列字母换算只随列数增长：只要它随行数×列数增长就必须红。"""

    def _count(self, shape, n_rows, n_params=None):
        f = excelize.new_file()
        seen = []
        origin = excelize.column_number_to_name

        def spy(col):
            seen.append(col)
            return origin(col)

        try:
            styles = create_file_sheet_styles(f)
            info = file_info(shape, n_rows=n_rows, n_params=n_params)
            with mock.patch.object(excelize, 'column_number_to_name', spy):
                write_file_sheet(f, info, False, NON_NUMERIC_KEYWORDS,
                                 styles, partial(write_cell, f))
            return len(info['df'].columns), len(seen)
        finally:
            f.close()

    def test_calls_are_bounded_by_column_count(self):
        ncols, _ = self._count('wide', 8)
        for n_rows in (8, SHAPES['wide']['n_rows'], 100):
            count_ncols, calls = self._count('wide', n_rows)
            self.assertEqual(count_ncols, ncols)
            with self.subTest(n_rows=n_rows, ncols=ncols):
                self.assertLessEqual(
                    calls, LETTER_CALL_BOUND_PER_COLUMN * ncols,
                    f'{n_rows} 行 × {ncols} 列换算了 {calls} 次字母 ⇒ 表没建在循环外')

    def test_row_count_does_not_add_calls(self):
        _ncols, few = self._count('wide', 8)
        _ncols2, many = self._count('wide', SHAPES['wide']['n_rows'])
        self.assertEqual(few, many, '行数从 8 涨到 100 就多算了列字母 ⇒ 仍是逐格换算')


# ────────────────────────── ④ 冗余逐格样式 ──────────────────────────


class GageStyleBatchingTests(SimpleTestCase):
    """同一行内同一样式的逐格重复下发必须收成区间调用（覆盖相对次序不变）。"""

    def _record(self, shape):
        """跑一次完整生成，录下所有 ``set_cell_style`` / ``set_col_style`` 下发。"""
        cell_calls, col_calls = [], []
        origin_cell = excelize.File.set_cell_style
        origin_col = excelize.File.set_col_style

        def spy_cell(self, sheet, top_left, bottom_right, style_id):
            cell_calls.append((sheet, top_left, bottom_right, style_id))
            return origin_cell(self, sheet, top_left, bottom_right, style_id)

        def spy_col(self, sheet, columns, style_id):
            col_calls.append((sheet, columns, style_id))
            return origin_col(self, sheet, columns, style_id)

        with mock.patch.object(excelize.File, 'set_cell_style', spy_cell), \
                mock.patch.object(excelize.File, 'set_col_style', spy_col):
            build_gage_summary_excel(datasets(shape))
        return cell_calls, col_calls

    @staticmethod
    def _span(calls, sheet, row):
        """该 sheet 上覆盖了 ``row`` 的调用，摊成 ``(首列, 末列)`` 列表。"""
        out = []
        for name, top, bottom, _style in calls:
            if name != sheet:
                continue
            col_top, row_top = excelize.cell_name_to_coordinates(top)
            col_bot, row_bot = excelize.cell_name_to_coordinates(bottom)
            if row_top <= row <= row_bot:
                out.append((col_top, col_bot))
        return out

    def test_whole_build_never_falls_back_to_whole_column_style(self):
        """``set_col_style`` 是整列语义（写 ``<col>`` 级样式），与区间下发不等价。"""
        _cells, cols = self._record('narrow')
        self.assertEqual(cols, [], f'出现了整列样式下发：{cols}')

    def test_summary_middle_rows_get_one_range_and_no_restamp(self):
        cell_calls, _ = self._record('narrow')
        _starts, _ends, middles = group_rows('narrow')
        self.assertTrue(middles, '形状里没有组内中间行，这条判据会是空的')
        for row in sorted(middles):
            span = self._span(cell_calls, SUMMARY_SHEET, row)
            with self.subTest(row=row):
                # 中间列（B..Z）恰好一次整段区间下发：既不是 25 次逐格，也不是删掉不写
                self.assertEqual([s for s in span if s == (MID_COL_FROM, MID_COL_TO)],
                                 [(MID_COL_FROM, MID_COL_TO)],
                                 f'第 {row} 行的中间列下发形状 = {span}')
                # 与数据带同 id 的逐格重复下发必须为 0（带本身是 1..27 的整行区间）
                self.assertEqual([s for s in span if s[0] == s[1]
                                  and MID_COL_FROM <= s[0] <= MID_COL_TO], [],
                                 f'第 {row} 行仍在逐格重刷数据带样式')
                # A / AA 保留逐格：它们的样式与中间列不同，框进区间会被覆盖
                self.assertIn((1, 1), span)
                self.assertIn((LAST_COL_IDX, LAST_COL_IDX), span)

    def test_summary_group_edge_rows_get_one_mid_range_delivery(self):
        """组首/组末行的中间列（B..Z）：一次区间下发覆盖，且除「整行带」与组首的 R&R%
        这两次既有合法覆盖外，这些格子在整张表里只被下发一次。

        这条补的是 A5 buyoff 段的复审缺口：那一轮把 gage 组首的中间列
        （``gage_summary_sheet.py`` 里 ``thick_top_mid`` 那一条）与组末的中间列
        （``thick_bottom_mid`` 那一条）各收成一次 B..Z 区间，但**没有任何判据钉住这个
        下发形状** —— 区间与逐格在 ``set_cell_style`` 覆盖写下是同一件事，所以把它退回逐格
        时产物字节 ①、逐格读回 ②、③ 与中间行那条判据全绿、digest 不变（M-e/M-f 实测零红）；
        而删掉这一整段会让组末掉回带原色（M-g 有连带红），证站点确在被测路径上、改写等价。
        ⇒ 只能对**下发调用本身的形状**下断言，与判据 ④「同行同 id 不许多次单格下发」同形。

        行域换成组首/组末（中间行由 ``test_summary_middle_rows_get_one_range_and_no_restamp``
        钉），断三件事：① B..Z 恰有一次整段区间（退回逐格 ⇒ 没有那条区间，红）；
        ② 除整行带与组首 R&R% 外，中间列内不许出现单格下发（退回逐格 ⇒ 25 个单格，红）；
        ③ 去掉整行带后每个中间列只被下发一次（删掉 ⇒ 少一次，红）。A / AA 保持逐格。
        """
        cell_calls, _ = self._record('narrow')
        starts, ends, _middles = group_rows('narrow')
        self.assertTrue(starts and ends, '形状里没有组首/组末行，判据会空转')
        self.assertTrue(starts.isdisjoint(ends), '窄表每组须 >1 行，否则首末重合判据失真')
        for row in sorted(starts | ends):
            is_first = row in starts
            span = self._span(cell_calls, SUMMARY_SHEET, row)
            band = (1, LAST_COL_IDX)               # 整行带：A..AA 一次覆盖，既有的合法写法
            rr_pct = (COL_RR_PCT, COL_RR_PCT)      # 组首 R&R% 基样式，同循环末尾再覆盖一次
            with self.subTest(row=row, kind='组首' if is_first else '组末'):
                # ① 中间列恰好一次整段区间（B..Z）：不是 25 次逐格（M-e/M-f），也不是删掉不写（M-g）
                self.assertEqual([s for s in span if s == (MID_COL_FROM, MID_COL_TO)],
                                 [(MID_COL_FROM, MID_COL_TO)],
                                 f'第 {row} 行中间列的区间下发形状 = {span}')
                # ② 除整行带与组首 R&R% 外，中间列内不许出现单格重刷
                singles = [s for s in span if s[0] == s[1]
                           and MID_COL_FROM <= s[0] <= MID_COL_TO and s != band]
                if is_first:
                    self.assertEqual(singles, [rr_pct],
                                     f'组首行 {row} 只应有一次 R&R% 单格覆盖，实得 {singles}')
                else:
                    self.assertEqual(singles, [], f'组末行 {row} 仍在逐格下发中间列：{singles}')
                # ③ 去掉整行带后，每个中间列被覆盖的次数（组首的 R&R% 那格另有既有的第二次）
                cover = {col: 0 for col in range(MID_COL_FROM, MID_COL_TO + 1)}
                for lo, hi in span:
                    if (lo, hi) == band:
                        continue
                    for col in range(max(lo, MID_COL_FROM), min(hi, MID_COL_TO) + 1):
                        cover[col] += 1
                for col, n in cover.items():
                    want = 2 if (is_first and col == COL_RR_PCT) else 1
                    self.assertEqual(n, want, f'第 {row} 行第 {col} 列去带后被下发 {n} 次（应 {want}）')
                # A / AA 各自样式与中间列不同（粗左边框 / 粗右边框），保持逐格、绝不框进区间
                self.assertIn((1, 1), span)
                self.assertIn((LAST_COL_IDX, LAST_COL_IDX), span)

    def test_file_sheet_style_bands_are_ranges(self):
        """表头带（8-12）、灰带（13）、统计带（115-128）都零逐格，且分段与读回游程同形。"""
        cell_calls, _ = self._record('narrow')
        sheet = datasets('narrow')[0]['sheet_name']
        last_col = len(datasets('narrow')[0]['df'].columns) + 8
        singles = []
        for row in list(range(8, 13)) + [13] + list(range(115, 129)):
            singles.extend([s for s in self._span(cell_calls, sheet, row)
                            if s[0] == s[1] and s[0] >= 2])
        self.assertEqual(singles, [], f'{sheet} 的表头带/灰带/统计带仍在逐格下发：{singles}')
        for row in range(8, 13):
            self.assertIn((8, last_col), self._span(cell_calls, sheet, row), row)
        self.assertIn((2, last_col), self._span(cell_calls, sheet, 13))
        # 统计带每行恰好两段：灰底 B..G、边框 H..last_col。两段的样式内容不同（读回
        # PIN_FILE_RUNS['115'] 的三个游程即证）⇒ 不许并成一段，并了就把灰底覆盖了。
        for row in range(115, 129):
            span = self._span(cell_calls, sheet, row)
            self.assertIn((2, 7), span, f'第 {row} 行的灰底段没收成区间：{span}')
            self.assertIn((8, last_col), span, f'第 {row} 行的边框段没收成区间：{span}')


# ────────────────────────── 钉值自检（防基线表退化成永真） ──────────────────────────


class GagePinsLookRealTests(SimpleTestCase):
    """基线常量表本身不许是空的或占位值 —— 否则上面几条判据全都恒绿。"""

    def test_pins_are_filled(self):
        for table in (PIN_SHA256, PIN_READBACK_DIGEST):
            self.assertNotIn('PLACEHOLDER', json.dumps(table))
            for shape in SHAPES:
                self.assertRegex(table[shape], r'^[0-9a-f]{64}$')
        self.assertGreaterEqual(len(PIN_SUMMARY_WIDTHS), LAST_COL_IDX - 5)
        self.assertTrue(all(v > 0 for v in PIN_SUMMARY_WIDTHS.values()))
        self.assertNotIn('PLACEHOLDER', json.dumps(PIN_SUMMARY_WIDTHS))
        for table in (PIN_SUMMARY_RUNS, PIN_FILE_RUNS):
            for row, segs in table.items():
                self.assertTrue(segs, f'第 {row} 行的游程基线是空的')
                for seg in segs:
                    self.assertLessEqual(seg[0], seg[1])
                    self.assertRegex(seg[2], r'^[0-9a-f]{12}$')
