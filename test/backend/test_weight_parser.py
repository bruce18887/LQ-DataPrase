"""apps/weight/parser.py 契约：解析 / 分组 / 命名 / 逐点均值 / 报错带行号。

夹具 `test/fixtures/weight/trim_weight_ci.csv`（Task 1）**不含任何错误形态**——56 条声明的
声明长度与实际个数全部相符、值全部是合法 5 位小数，所以错误/边界类用例一律用合成文本。
"""
import builtins
import importlib.util
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.test import TestCase  # noqa: E402

from apps.weight.parser import (  # noqa: E402
    DECLARATION_LIMIT, LENGTH_LIMIT, MEAN_DECIMALS, TEXT_LIMIT,
    WeightDoc, WeightError, WeightGroup, WeightSeries,
    compute_mean, doc_to_payload, parse_weight_text,
)

FIXTURE = os.path.join(ROOT, 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')
SINGLE = 'double A[3] = {1.5, 2.5, 3.5};\n'

# 夹具形状（Task 1 钉住：14 个名字 × 各 4 次 = 56 条声明、1088 个值、长度集合 {4,8,16,32,64}）
EXPECTED_SERIES = 56
EXPECTED_VALUES = 1088


def _read_fixture():
    with io.open(FIXTURE, encoding='utf-8', newline='') as f:
        return f.read()


def _all_series(doc):
    return [s for g in doc.groups for s in g.series]


def _mean_series(*rows):
    """按 members 构造一条用于均值断言的组（绕过解析，隔离测试点）。"""
    return [WeightSeries(n, i + 1, len(v), 5, tuple(v)) for i, (n, v) in enumerate(rows)]


class ParseRealFixtureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()          # Django TestCase 的类级原子事务要在 super 里建，缺了就 tearDownClass 炸
        cls.text = _read_fixture()
        cls.doc = parse_weight_text(cls.text, filename_hint='trim_weight_ci')

    def test_shape(self):
        self.assertEqual(self.doc.group_count, 14)
        self.assertEqual(self.doc.series_count, EXPECTED_SERIES)
        self.assertEqual(self.doc.code_max, 63)          # 最大数组长度 64 → 轴上界 63
        self.assertEqual(len(self.doc.groups[0].series), 4)
        self.assertEqual(self.doc.filename_hint, 'trim_weight_ci')

    def test_group_order_is_first_appearance(self):
        names = [g.name for g in self.doc.groups]
        self.assertEqual(len(names), len(set(names)))
        first_seen = re.findall(r'double\s+(\w+)\s*\[', self.text)
        self.assertEqual(names, list(dict.fromkeys(first_seen)))  # 组序 == 首次出现序
        self.assertEqual(self.doc.groups[0].series[0].name, 'WT0001_1')
        self.assertEqual(self.doc.groups[0].series[3].name, 'WT0001_4')

    def test_mean_present_and_pointwise(self):
        g = self.doc.groups[0]
        self.assertEqual(len(g.series), 4)                # 前置：均值确实是「4 个成员求平均」
        self.assertEqual(g.mean.name, 'WT0001_Avg')
        first_col = [s.values[0] for s in g.series]
        self.assertAlmostEqual(g.mean.values[0], sum(first_col) / 4, places=12)
        # 逐点：最后一个 code 也得是那一列的平均（防「整条抄第一个成员」的实现）
        last = len(g.mean.values) - 1
        self.assertAlmostEqual(g.mean.values[last], sum(s.values[last] for s in g.series) / 4, places=12)
        # 均值宽度 = 组内最大声明长度，不是第一条的长度
        self.assertEqual(len(g.mean.values), max(len(s.values) for s in g.series))
        self.assertEqual(len(g.mean.values), 16)
        # 全精度承重（spec §7.4）：上面两点（index 0 = -4.5e-05、index 15 = 0.003405）在
        # `round(x, MEAN_DECIMALS)` 下**不变值**，所以「均值一律四舍五入到 5 位」的实现照样能过前三条
        # —— 必须再挑一个「5 位小数会改值」的点做精确 assertEqual。候选点由成员自己算出来，
        # 不写死下标：夹具重排也不会静默失焦。
        tight = None
        for i in range(len(g.mean.values)):
            col = [s.values[i] for s in g.series if i < len(s.values) and s.values[i] is not None]
            if not col:
                continue                                       # 该 code 全组无值 ⇒ 均值留 None
            expect = sum(col) / len(col)
            if expect != round(expect, MEAN_DECIMALS):     # 该点被四舍五入会改值
                tight = (i, expect, len(col))
                break
        self.assertIsNotNone(tight, '本组没有任何 5 位小数敏感点 ⇒ 这条判据空转，先查夹具')
        i, expect, n = tight
        self.assertEqual(n, 4)                            # 前置：仍是 4 个成员共同求平均
        self.assertEqual(g.mean.values[i], expect)         # 未 round 的全精度

    def test_declared_length_equals_value_count_for_all_56(self):
        series = _all_series(self.doc)
        self.assertEqual(len(series), EXPECTED_SERIES)    # 前置：下面那个循环不是空转
        for s in series:
            self.assertEqual(len(s.values), s.declared_length, s.name)
        self.assertEqual(sum(len(s.values) for s in series), EXPECTED_VALUES)

    def test_decimals_follow_source_text_across_fixture(self):
        series = _all_series(self.doc)
        self.assertEqual(len(series), EXPECTED_SERIES)    # 前置
        self.assertEqual({s.decimals for s in series}, {5})   # 夹具 1088 值一律 5 位小数

    def test_source_index_is_global_declaration_order(self):
        # 组内编号必须是「全局第几条声明」，不是「组内第几个」——夹具的名字是每 14 条轮换一次的
        self.assertEqual(sorted(s.source_index for s in _all_series(self.doc)),
                         list(range(1, EXPECTED_SERIES + 1)))
        self.assertEqual([s.source_index for s in self.doc.groups[0].series], [1, 15, 29, 43])

    def test_first_row_is_declaration_ordinal_not_line_number(self):
        # 夹具条目之间夹空行 ⇒ 第 k 条声明落在文件第 2k+1 行；first_row 的契约是「组内第一条的全局
        # 声明序号」（Task 5 的表行序按 组序 × 组内序 排，跟这个值不是一回事，别拿它当行号用）
        self.assertEqual([g.first_row for g in self.doc.groups], list(range(1, 15)))
        self.assertEqual(self.doc.groups[3].first_row, 4)
        self.assertEqual(self.text.count('\n', 0, self.text.index('WT0004')) + 1, 9)


class NamingAndMeanTests(TestCase):
    def test_single_occurrence_keeps_original_name(self):
        doc = parse_weight_text(SINGLE)
        self.assertEqual(doc.groups[0].series[0].name, 'A')
        self.assertEqual(doc.groups[0].series[0].source_index, 1)

    def test_repeated_name_gets_suffix_for_all_members(self):
        doc = parse_weight_text(SINGLE + SINGLE)
        self.assertEqual([s.name for s in doc.groups[0].series], ['A_1', 'A_2'])
        self.assertEqual(doc.groups[0].name, 'A')         # 组名保持基名，均值才叫 A_Avg

    def test_case_sensitive_names_split_groups(self):
        doc = parse_weight_text('double A[1] = {1.0};\ndouble a[1] = {2.0};\n')
        self.assertEqual(doc.group_count, 2)

    def test_duplicate_names_are_not_deduped_and_never_raise(self):
        # 撞名口径钉在 parser.py 模块 docstring：后缀可与文件里本来就在的字面量重名，
        # 本模块不去重、不报错（要报错就得新增错误码，而新码必须同时进前端 ERROR_CODE_MAP ⇒ 那是改 spec）。
        # ⇒ 消费方只能用 `(group.index, series 下标)` 或 `source_index` 作键，不能用 `series.name`。
        doc = parse_weight_text('double A[1]={1.0}; double A[1]={2.0}; double A_1[1]={3.0};')
        self.assertEqual([s.name for g in doc.groups for s in g.series], ['A_1', 'A_2', 'A_1'])
        self.assertEqual([(g.name, [s.name for s in g.series]) for g in doc.groups],
                         [('A', ['A_1', 'A_2']), ('A_1', ['A_1'])])   # 组 1 基名 = 组 0 成员名
        self.assertEqual((doc.group_count, doc.series_count), (2, 3))
        self.assertEqual(sorted(s.source_index for g in doc.groups for s in g.series), [1, 2, 3])
        # 字面量 `A_Avg` 与组 `A` 的均值名同样撞车
        other = parse_weight_text('double A[1]={1.0}; double A_Avg[1]={2.0};')
        self.assertEqual([g.mean.name for g in other.groups], ['A_Avg', 'A_Avg_Avg'])
        self.assertIn('A_Avg', [s.name for g in other.groups for s in g.series])

    def test_mean_of_unequal_lengths_only_over_available_values(self):
        m = compute_mean(_mean_series(('A_1', [1.0, 2.0]), ('A_2', [3.0])), 'A_Avg')
        self.assertEqual(m.values, (2.0, 2.0))     # code0=(1+3)/2, code1=2/1
        self.assertEqual(m.declared_length, 2)     # 长度取组内最大

    def test_mean_length_uses_group_maximum_and_gaps_stay_none(self):
        m = compute_mean(_mean_series(('A_1', [1.0]), ('A_2', [2.0, 4.0, 6.0])), 'A_Avg')
        self.assertEqual(m.values, (1.5, 4.0, 6.0))
        self.assertEqual(m.declared_length, 3)

    def test_mean_is_computed_during_parse_not_lazily(self):
        # spec §3.2：逐点均值在解析期就算好，前端只切可见性（「惰性算」的实现这里就红了）
        doc = parse_weight_text('double A[1] = {1.0};\ndouble A[1] = {3.0};\n')
        self.assertEqual(doc.groups[0].mean.values, (2.0,))
        self.assertEqual([s.name for s in doc.groups[0].series], ['A_1', 'A_2'])

    def test_mean_carries_mean_decimals_and_zero_source_index(self):
        members = [WeightSeries('A_1', 1, 2, 3, (1.0, 3.0)),
                   WeightSeries('A_2', 2, 2, 4, (5.0, 7.0))]
        m = compute_mean(members, 'A_Avg')
        self.assertEqual(MEAN_DECIMALS, 5)                # 2026-10-20 用户点定：页面与导出统一 5 位
        self.assertEqual(m.decimals, MEAN_DECIMALS)       # Task 4 靠它挑 '0.00000' 格式
        self.assertNotEqual(m.decimals, max(x.decimals for x in members))   # 对照：不是继承来的
        self.assertEqual(m.source_index, 0)               # 0 = 不是真声明，Task 5 用它区分均值行
        self.assertEqual(m.values, (3.0, 5.0))

    def test_mean_rounding_is_display_only_values_stay_full_precision(self):
        # spec §7.4：MEAN_DECIMALS 是显示口径，单元格/载荷里的 float 不得被四舍五入截断。
        # 操作数得选「均值在 5 位小数上会变值」的一对：原先用 1.0 与 2.0（均值 1.5）时，
        # `round(1.5, 5) == 1.5`，任何「一律 round(..., MEAN_DECIMALS)」的实现这条也是绿的 ——
        # 也就是说不承重。换 1/3 与 0 之后均值 0.16666666666666666 ≠ round(…, 5)=0.16667。
        a, b = 1.0 / 3.0, 0.0
        expect = (a + b) / 2
        self.assertNotEqual(expect, round(expect, MEAN_DECIMALS))   # 前置：操作数真有区分度
        self.assertEqual(round(expect, MEAN_DECIMALS), 0.16667)     # 对照：坏实现会交出的值
        m = compute_mean(_mean_series(('A_1', [a]), ('A_2', [b])), 'A_Avg')
        self.assertEqual(m.values, (expect,))
        self.assertEqual(m.decimals, MEAN_DECIMALS)


class ErrorAndLimitTests(TestCase):
    def assert_code(self, text, code, **fields):
        with self.assertRaises(WeightError) as cm:
            parse_weight_text(text)
        self.assertEqual(cm.exception.code, code)
        for k, v in fields.items():
            self.assertEqual(cm.exception.fields.get(k), v, f'字段 {k} 不符')

    def test_no_declaration(self):
        self.assert_code('print("hi")\n\n', 'no_declaration')

    def test_length_mismatch_carries_line_and_counts(self):
        self.assert_code('double A[3] = {1.0, 2.0};\n', 'weight_length_mismatch',
                         line=1, name='A', declared=3, actual=2)

    def test_length_mismatch_line_counts_prior_newlines(self):
        self.assert_code(SINGLE + 'double B[2] = {1.0};\n', 'weight_length_mismatch', line=2)

    def test_bad_number_carries_line_and_token(self):
        self.assert_code('double A[2] = {1.0, x};\n', 'weight_bad_number', line=1, token='x')

    def test_nan_and_inf_literals_are_rejected(self):
        for tok in ('nan', 'inf', '-inf', 'NaN'):
            self.assert_code(f'double A[1] = {{{tok}}};\n', 'weight_bad_number', token=tok)

    def test_underscore_digit_separators_are_rejected(self):
        # 唯一的拦阻者现在是 NUMBER_RE 的形状本身（`_` 不在字符类里 ⇒ `float('1_000')` 合法但过不了
        # fullmatch）。原先实现里还并联了一条 `'_' in token` 冗余子句，摘掉子句这条照样绿 ——
        # 变异反证正是据此把那条子句删干净的（见 parser.py 同处注释）
        self.assert_code('double A[1] = {1_000};\n', 'weight_bad_number', token='1_000')

    def test_scientific_notation_is_accepted(self):
        doc = parse_weight_text('double A[2] = {1.5e-3, 2E2};\n')
        self.assertEqual(doc.groups[0].series[0].values, (0.0015, 200.0))

    def test_overflowing_exponent_is_rejected_by_isfinite_not_by_shape(self):
        # `1e999` 合正则形状，但 float() 出来是 inf —— 这条是 math.isfinite 分支唯一的承重用例
        # （形状守卫与 isfinite 缺一不可：去掉前者 `1_000` 会放行，去掉后者这条会放行）
        self.assert_code('double A[1] = {1e999};\n', 'weight_bad_number', line=1, token='1e999')

    def test_tab_between_keyword_and_name_is_accepted(self):
        doc = parse_weight_text('double\tA[2] = {1.0, 2.0};\n')
        self.assertEqual(doc.group_count, 1)

    def test_lf_only_and_crlf_both_accepted(self):
        a = parse_weight_text('double A[2] = {1.0, 2.0};\ndouble B[1] = {3.0};\n')
        b = parse_weight_text('double A[2] = {1.0, 2.0};\r\ndouble B[1] = {3.0};\r\n')
        self.assertEqual([g.name for g in a.groups], [g.name for g in b.groups])
        self.assertEqual([g.name for g in a.groups], ['A', 'B'])   # 前置：两边都真解析出了两条

    def test_trailing_comma_is_tolerated(self):
        doc = parse_weight_text('double A[2] = {1.0, 2.0,};\n')
        self.assertEqual(len(doc.groups[0].series[0].values), 2)

    def test_declaration_spanning_newlines_matches_whole_text(self):
        # spec §3.1「允许换行与空白」：值列表里换行 ⇒ 一条声明跨行，行号取声明**起始**行
        doc = parse_weight_text('double A[3] = {1.0,\n   2.0,\n   3.0};\ndouble B[1] = {4.0};\n')
        self.assertEqual(doc.group_count, 2)
        self.assertEqual(doc.groups[0].series[0].values, (1.0, 2.0, 3.0))
        self.assertEqual(doc.groups[1].first_row, 2)
        self.assert_code('double A[3] = {1.0,\n   2.0,\n   x};\n', 'weight_bad_number', line=1, token='x')

    def test_non_matching_and_foreign_keyword_lines_are_ignored(self):
        doc = parse_weight_text('float Skip[2] = {1.0, 2.0};\n\ndouble A[1] = {3.0};\n// note\n')
        self.assertEqual(doc.group_count, 1)
        self.assertEqual(doc.series_count, 1)
        self.assertEqual(doc.groups[0].name, 'A')

    def test_declaration_without_semicolon_is_not_a_declaration(self):
        self.assert_code('double A[1] = {1.0}', 'no_declaration')

    def test_text_limit(self):
        unit = 'double A[1] = {1.0};\n'
        big = unit * (TEXT_LIMIT // len(unit) + 1)
        self.assert_code(big, 'weight_too_large', which='text', limit=TEXT_LIMIT)

    def test_text_limit_is_checked_before_parsing(self):
        # 顺序判据（spec §3.4）：超限文本先看字符数，哪怕它一条声明都没有，也必须报 too_large
        # 而不是 no_declaration —— 「先扫声明再查长度」的实现只在这条上露馅
        big = 'not a declaration\n' * (TEXT_LIMIT // len('not a declaration\n') + 1)
        self.assertGreater(len(big), TEXT_LIMIT)                          # 前置：确实超限
        self.assert_code(big, 'weight_too_large', which='text', limit=TEXT_LIMIT)

    def test_declaration_limit(self):
        many = '\n'.join(f'double N{i}[1] = {{1.0}};' for i in range(DECLARATION_LIMIT + 1))
        self.assert_code(many, 'weight_too_large', which='declarations', limit=DECLARATION_LIMIT,
                         actual=DECLARATION_LIMIT + 1)

    def test_length_limit(self):
        declared = LENGTH_LIMIT + 1
        self.assert_code('double A[%d] = {%s};\n' % (declared, ','.join(['1.0'] * declared)),
                         'weight_too_large', which='length', limit=LENGTH_LIMIT, actual=declared)

    def test_zero_length_declaration_is_legal_but_axis_floor_stays_non_negative(self):
        # 声明 0 == 实际 0，`LENGTH_LIMIT` 只是上界 ⇒ `double A[0] = {};` 合法、不开新错误码。
        # 但 `max(声明长度) - 1` 会给 -1 ⇒ X 轴成了 `0..-1`，而 Task 3/4/6 都不设防。
        # 口径：钳到 0（「钳到 0」的实现改回裸减一，这条就红）。
        doc = parse_weight_text('double A[0] = {};')
        self.assertEqual(doc.groups[0].mean.values, ())        # 均值宽度 0
        self.assertEqual(doc.groups[0].mean.declared_length, 0)
        self.assertEqual(doc.code_max, 0)
        self.assertEqual(doc_to_payload(doc)['code_max'], 0)   # 载荷里也是非负上界

    def test_limits_reject_only_above_the_boundary(self):
        # 对照三条 off-by-one：`>=` 写成守卫会让「恰好等于上限」的合法文件也被拒
        at_decl = '\n'.join(f'double C{i}[1] = {{1.0}};' for i in range(DECLARATION_LIMIT))
        self.assertEqual(parse_weight_text(at_decl).group_count, DECLARATION_LIMIT)
        at_len = parse_weight_text('double D[%d] = {%s};\n' % (LENGTH_LIMIT, ','.join(['1.0'] * LENGTH_LIMIT)))
        self.assertEqual(at_len.groups[0].series[0].declared_length, LENGTH_LIMIT)
        body = '\n'.join(f'double B{i}[1] = {{1.0}};' for i in range(DECLARATION_LIMIT - 1))
        at_text = body + '\n' * (TEXT_LIMIT - len(body))                 # 空行不是声明，只用来补长度
        self.assertEqual(len(at_text), TEXT_LIMIT)                       # 前置：恰好等于上限
        self.assertEqual(parse_weight_text(at_text).group_count, DECLARATION_LIMIT - 1)
        self.assert_code(at_text + ' ', 'weight_too_large', which='text', limit=TEXT_LIMIT,
                         actual=TEXT_LIMIT + 1)


class PayloadShapeTests(TestCase):
    def test_payload_keys_and_nan(self):
        doc = parse_weight_text(SINGLE)
        p = doc_to_payload(doc)
        self.assertEqual(sorted(p), ['code_max', 'group_count', 'groups', 'series_count'])
        g = p['groups'][0]
        self.assertEqual(sorted(g), ['first_row', 'index', 'mean', 'name', 'series'])
        s = g['series'][0]
        self.assertEqual(sorted(s), ['decimals', 'declared_length', 'name', 'source_index', 'values'])
        self.assertEqual(g['mean']['name'], 'A_Avg')
        self.assertEqual(sorted(g['mean']), sorted(s))                   # 均值与成员同构，前端一套渲染

    def test_payload_values_are_lists_not_tuples(self):
        p = doc_to_payload(parse_weight_text(SINGLE))
        self.assertIsInstance(p['groups'][0]['series'][0]['values'], list)

    def test_missing_mean_point_serializes_as_json_null(self):
        # 两个成员在该 code 都缺值 ⇒ 均值得 None；载荷必须写 null 而不是 NaN
        # （float('nan') 会让 json 写出非法的 NaN 字面量，前端 JSON.parse 直接抛）
        members = [WeightSeries('A_1', 1, 2, 5, (1.0, None)), WeightSeries('A_2', 2, 2, 5, (3.0, None))]
        mean = compute_mean(members, 'A_Avg')
        self.assertIsNone(mean.values[1])                                # 前置：确实算出空缺
        doc = WeightDoc('x', (WeightGroup(0, 'A', 1, tuple(members), mean),), 1, 2, 1)
        p = doc_to_payload(doc)
        self.assertIsNone(p['groups'][0]['mean']['values'][1])
        self.assertEqual(json.loads(json.dumps(p, allow_nan=False)), p)

    def test_real_fixture_payload_is_strict_json(self):
        # NaN/Inf 逃进载荷的唯一通路就是解析器没拦住，所以拿真夹具再走一遍严格 JSON
        doc = parse_weight_text(_read_fixture(), filename_hint='trim_weight_ci')
        p = doc_to_payload(doc)
        self.assertEqual((p['group_count'], p['series_count'], p['code_max']), (14, EXPECTED_SERIES, 63))
        self.assertEqual(json.loads(json.dumps(p, allow_nan=False)), p)

    def test_decimals_recorded_from_source_text(self):
        doc = parse_weight_text('double A[2] = {1.50, 2.5};\n')
        self.assertEqual(doc.groups[0].series[0].decimals, 2)            # 取组内最大，不是第一条

    def test_payload_series_order_matches_doc(self):
        # 名字故意选成「到达序 ≠ 字典序」，否则排序过的实现也能过
        doc = parse_weight_text('double B[1] = {1.0};\ndouble A[1] = {2.0};\ndouble B[1] = {3.0};\n')
        p = doc_to_payload(doc)
        self.assertEqual([g['name'] for g in p['groups']], ['B', 'A'])
        self.assertEqual([s['name'] for s in p['groups'][0]['series']], ['B_1', 'B_2'])
        self.assertEqual([s['source_index'] for s in p['groups'][0]['series']], [1, 3])
        self.assertEqual([g['index'] for g in p['groups']], [0, 1])


class _NoDependencySandbox:
    """把「禁依赖」变成行为判据，而不是 grep 源码文本（lessons 2026-10-18①）。

    为什么不用 `sys.meta_path` 钩子：本项目里 django/pandas 早就在 `sys.modules` 里，import 语句
    先查缓存、根本不会走到 finder，钩子会**静默不咬** —— 那正是「全绿但缺陷还活着」的形状。
    所以改成替换这一次模块执行的 `__import__` 与 `open`：只作用于传给它的那个 globals 字典，
    不碰 builtins 本体、也不碰 sys.meta_path，别的测试不受影响。
    """

    FORBIDDEN = ('django', 'openpyxl', 'pandas', 'numpy', 'rest_framework',
                 'builtins', 'io', 'os', 'pathlib', 'subprocess')

    def __init__(self):
        self.blocked = []
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.split('.')[0] in self.FORBIDDEN:
                self.blocked.append(name)
                raise ImportError(f'权重解析器不得依赖 {name}')
            return real_import(name, *args, **kwargs)

        def guarded_open(file=None, *args, **kwargs):
            self.blocked.append(f'open({file!r})')
            raise OSError('权重解析器不得读写文件（文本一律由调用方给）')

        ns = dict(vars(builtins))
        ns['__import__'] = guarded_import
        ns['open'] = guarded_open
        self.builtins = ns

    def run_dirty(self, source):
        """对照组：证明这个沙箱真的会咬，否则「blocked == []」可能只是判据没生效。"""
        return exec(compile(source, '<dirty>', 'exec'), {'__builtins__': self.builtins})


class ParserPurityTests(TestCase):
    def test_parser_runs_without_django_excel_or_file_io(self):
        sandbox = _NoDependencySandbox()
        path = os.path.join(ROOT, 'apps', 'weight', 'parser.py')
        self.assertTrue(os.path.isfile(path))                            # 前置：文件确实在那儿
        alias = '_weight_parser_purity'
        spec = importlib.util.spec_from_file_location(alias, path)
        module = importlib.util.module_from_spec(spec)
        module.__dict__['__builtins__'] = sandbox.builtins               # exec 只在缺失时才注入
        # @dataclass 靠 sys.modules[cls.__module__] 解析注解，所以这份独立模块得登记；
        # 用独立别名、用完即摘，绝不覆盖真实的 apps.weight.parser（否则同批其它测试类身份错位）
        sys.modules[alias] = module
        try:
            spec.loader.exec_module(module)                              # 干净 ⇒ 一次都不该触发
            doc = module.parse_weight_text(SINGLE)                       # 对照组：正常路径没被废掉
        finally:
            sys.modules.pop(alias, None)
        self.assertEqual(doc.groups[0].series[0].name, 'A')
        self.assertEqual(doc.groups[0].mean.values, (1.5, 2.5, 3.5))     # 纯文本进、纯数据出
        self.assertEqual(sandbox.blocked, [])
        self.assertIsNot(module.parse_weight_text, parse_weight_text)     # 前置：确实是另起的一份
        with self.assertRaises(ImportError):
            sandbox.run_dirty('import django')
        with self.assertRaises(ImportError):
            sandbox.run_dirty('import openpyxl')
        with self.assertRaises(OSError):
            sandbox.run_dirty("open('whatever.csv')")
        self.assertEqual(sandbox.blocked[-3:], ['django', 'openpyxl', "open('whatever.csv')"])


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    sys.exit(1 if DiscoverRunner(verbosity=1).run_tests(
        ['test.backend.test_weight_parser']) else 0)
