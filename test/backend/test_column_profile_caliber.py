"""T1（A4 的契约⑤ + 那条「决策见证」；A4b 的 histogram 专用候选口径）：
column_profile 的体积核算与直方图口径差异。

本文件是 `test_column_profile_cache.py` 拆出来的另一半（2026-10-28 质量复审整改：主文件
598 行贴到 600 阈，把「体积核算」与「口径差异」两族连同它们专用的小夹具搬来）。
**拆分时断言一条没改、一条没弱化**（当时两文件合计 21 例）；A4b 波次在本文件追加
``HistogramCandidateCaliberTests`` / ``HistogramCandidatesSizingTests`` /
``EmptinessFilterSingleSourceTests`` 与见证用例里的
专用键条款（只增强，旧断言逐字未动），视图侧 fast path 判据在新文件
``test_histogram_candidates_fastpath.py``。

夹具（``_fragile_frame`` / ``_md_of``）是本文件内的**原样副本**，不与主文件共享对象：
测试基线宁可重复，也不许做成「另一个文件改一下这里就跟着变」的共享可变状态。
``_baseline_histogram_candidates`` 由本文件的见证用例与 ``HistogramCandidateCaliberTests``
共用（都是「改动前那段」的对照物），所以是搬来而非复制。
"""

import ast
from pathlib import Path

import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.statistics.helpers import (
    get_serial_candidates,
    get_site_column,
)
from apps.datafiles import column_profile, services
from apps.datafiles import parse_cache_sizing as sizing

APPS_DIR = Path(__file__).resolve().parents[2] / 'apps'
HIST_KEY = 'histogram_numeric_columns'


# ───────────────────────────── 夹具（与主文件同形的原样副本） ─────────────────────────────

def _fragile_frame():
    """脆弱帧（lessons R4②）：全 NaN 列、bool 列、数字字符串 object 列、常量列、全 None object 列。

    ``dtype='object'`` 是**显式**写的：pandas 3.0 下自然推出来的是 ``str`` dtype，
    而旧那段判定用的是 ``df[col].dtype == object``——口径必须按旧句复制，
    所以夹具也按旧句的形状给（否则值级判定这条路在测试里根本不会被走到）。
    """
    return pd.DataFrame({
        'Site_No': pd.Series(['1', 'nan', None, '2', '2'], dtype='object'),
        'Serial_No': pd.Series([11, 12, 13, 14, 15]),
        'Dut_No': pd.Series([1, 2, 3, 4, 5]),
        'Dut_Pass': pd.Series([True, False, True, True, False]),
        'SW_Bin': pd.Series(['1', '5', '7', '1', '5'], dtype='object'),
        'PART_ID': pd.Series(['a1', 'b2', None, 'c3', 'd4'], dtype='object'),
        'QR_Code': pd.Series([float('nan')] * 5),
        'BLANK_OBJ': pd.Series([None] * 5, dtype='object'),
        'CONST_V': pd.Series([2.5] * 5),
        'PAR0001': pd.Series([1.0, 2.0, None, 4.0, 5.0]),
    })


def _md_of(frame):
    """与真实解析产出同形的 metadata（每列带 unit/min/max），供 col_meta 与体积用例使用。"""
    return {
        'format': 'CTA8290D',
        'units': {c: 'um' for c in frame.columns},
        'mins': {c: '-999.9999' for c in frame.columns},
        'maxs': {c: '999.9999' for c in frame.columns},
    }


def _baseline_histogram_candidates(df):
    """改动前 histogram fast path 里那段候选现算的搬运（A4b 落地前的 `analysis_views.py`，
    即提交 8f78d10 那一版；按行号引会随每次改动腐掉，所以钉的是「哪一版的哪段」）。

    只用于那条「两套口径不等价」的见证用例，不参与 profile 的等价性判定。
    """
    _meta_cols = set(get_serial_candidates(df))
    _stc = get_site_column(df)
    if _stc:
        _meta_cols.add(_stc)
    numeric_cols = [c for c in df.columns
                    if pd.api.types.is_numeric_dtype(df[c])
                    and not pd.api.types.is_bool_dtype(df[c])
                    and c not in _meta_cols]
    if numeric_cols:
        _has_value = df[numeric_cols].notna().any().to_numpy()
        numeric_cols = [c for c, ok in zip(numeric_cols, _has_value) if ok]
    return numeric_cols


# ───────────────── 决策见证：histogram 那半条不在 A4 落地 ─────────────────

class HistogramCaliberDivergenceTests(SimpleTestCase):
    """直方图候选 ≠ ``column_profile['numeric_columns']``，两套口径各自正确。

    这就是 A4 选「不动 histogram」的证据：把 profile 的 `numeric_columns` 直接喂给
    改动前那段候选现算（A4b 后是 ``column_profile.build_histogram_param_candidates``）
    会把序列/site 列和数字字符串 object 列塞进前端可选参数集，而那边还要在
    ``data_only_bin1`` 为真时先收窄行再派生——那才是契约变更。
    （A4b 的解法不是复用 `numeric_columns`，而是随解析多算一只**专用内部键**，
    见下方 ``HistogramCandidateCaliberTests``；本类钉的「两集合不等价」依旧成立。）

    基座从主文件的 ``_CacheCaseBase`` 换成 ``SimpleTestCase``：这一族比的是**两只纯函数**
    的输出，既不碰解析缓存也不数调用次数（那套换缓存/装假解析器的夹具在这里全用不上），
    断言逐条未改；``_fragile_frame`` 是本文件内的原样副本。
    """

    def setUp(self):
        self.frame = _fragile_frame()

    def test_browse_numeric_columns_are_not_histogram_candidates(self):
        browse_numeric = column_profile.build_column_profile(
            self.frame, 'CTA8290D')['numeric_columns']
        hist = _baseline_histogram_candidates(self.frame)

        for col in ('Site_No', 'Serial_No', 'Dut_No'):
            with self.subTest(meta_col=col):
                self.assertIn(col, browse_numeric, 'browse 不收窄、不排除元信息列')
                self.assertNotIn(col, hist, 'histogram 必须先排除序列/site 候选')
        self.assertIn('SW_Bin', browse_numeric, 'browse 走值级判定')
        self.assertNotIn('SW_Bin', hist, 'histogram 是纯 dtype 口径，object 数字串列不收')
        self.assertNotEqual(browse_numeric, hist,
                            '若哪天两者相等，才谈得上让 histogram 复用同一只 profile')
        # A4b 追加（不弱化上面任何一条）：专用键的值必须等于直方图基线，
        # 且它绝不等于 browse 的 numeric_columns —— 缓存的是「另一口径」，不是同一集合。
        stored = column_profile.build_column_profile(self.frame, 'CTA8290D')
        self.assertEqual(stored[HIST_KEY], hist)
        self.assertNotEqual(stored[HIST_KEY], browse_numeric)


# ───────────────── A4b：histogram 专用候选随解析写透缓存 ─────────────────

class HistogramCandidateCaliberTests(SimpleTestCase):
    """`build_histogram_param_candidates` 逐字复刻旧 histogram fast path 的候选口径。

    基线是本文件 ``_baseline_histogram_candidates``（改动前视图里那段候选现算的原样搬运，
    的原样搬运），这里只复用不弱化；夹具沿用 ``_fragile_frame`` 的原样副本。
    """

    def setUp(self):
        self.frame = _fragile_frame()

    def test_builder_equals_the_old_view_caliber(self):
        self.assertEqual(
            column_profile.build_histogram_param_candidates(self.frame),
            _baseline_histogram_candidates(self.frame))
        # 口径本身逐列钉（两份一起错就抓不住，同主文件 test_caliber_pins_the_fragile_columns）
        candidates = column_profile.build_histogram_param_candidates(self.frame)
        for meta in ('Site_No', 'Serial_No', 'Dut_No'):
            self.assertNotIn(meta, candidates, '序列/site 候选必须排除（元信息不是参数）')
        self.assertNotIn('Dut_Pass', candidates, 'bool 列必须排除')
        self.assertNotIn('QR_Code', candidates, '全 NaN 数值列必须排除')
        self.assertNotIn('SW_Bin', candidates, '纯 dtype 口径不收 object 数字串列')
        self.assertIn('CONST_V', candidates)
        self.assertIn('PAR0001', candidates)
        self.assertEqual(candidates, ['CONST_V', 'PAR0001'], '列序 = df.columns 序')

    def test_stored_profile_carries_the_internal_histogram_key(self):
        profile = column_profile.build_column_profile(self.frame, 'CTA8290D')
        self.assertEqual(profile[HIST_KEY],
                         _baseline_histogram_candidates(self.frame))

    def test_response_contract_stays_four_keys_storage_grows_to_five(self):
        """browse 响应四键不许动；存储 profile 比响应多的必须恰好是那只内部键。"""
        self.assertEqual(len(column_profile.COLUMN_PROFILE_KEYS), 4)
        self.assertEqual(column_profile.HISTOGRAM_PROFILE_KEY, HIST_KEY)
        profile = column_profile.build_column_profile(self.frame, 'CTA8290D')
        # 差集而不是「等于某个定义式」：定义式抄一遍就是同义反复，改两边也抓不住。
        self.assertEqual(set(profile) - set(column_profile.COLUMN_PROFILE_KEYS),
                         {HIST_KEY}, '存储侧只允许多出 histogram 这一只内部键')


class EmptinessFilterSingleSourceTests(SimpleTestCase):
    """`…notna().any().to_numpy()` 这条链在 `apps/` 里只能有一处。

    A4b 前 histogram 的候选口径长在视图里，抽取时同一份两行判空被复制成了
    「口径函数 + 视图消费侧」两份（质量复审的 Important）。漂移风险是真实的：
    有人给口径函数补了重复列名/空列表守卫，视图那份不会跟着改。
    现在两处都走 `column_profile.keep_columns_with_values`。

    **这条判据的半径要说清楚，别当成「全仓判空只有一处」**：它匹配的是「多列选择后
    一次向量化判空并落成 numpy 数组」这一具体形状。全仓还有形态不同的判空——
    `column_profile.build_column_profile` 里 browse 那份是逐列循环中的单列判定，
    `analysis/views/_helpers.py` 的 `_sanitize_numeric_params` 停在
    `…notna().any()`（没有 `.to_numpy()`，它要把结果留成 Series 继续逐列查）。
    三者语义同源、形状不同，合并属于 I 波「重复实现合并」的面，不在本刀；
    所以这里钉的是「本刀抽出来的那份不许多处」，不是「判空只许存在一种写法」。
    扫的是 AST（注释/字符串里的同形文本不算），测试基线副本不在 `apps/` 下不受影响。
    """

    OWNER = 'datafiles/column_profile.py'

    def _is_notna_any_to_numpy(self, node):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'to_numpy'):
            return False
        inner = node.func.value
        if not (isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == 'any'):
            return False
        deepest = inner.func.value
        return (isinstance(deepest, ast.Call)
                and isinstance(deepest.func, ast.Attribute)
                and deepest.func.attr == 'notna')

    def test_vectorized_emptiness_filter_lives_only_in_column_profile(self):
        hits = []
        for path in sorted(APPS_DIR.rglob('*.py')):
            rel = path.relative_to(APPS_DIR).as_posix()
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=rel)
            hits.extend(f'{rel}:{node.lineno}' for node in ast.walk(tree)
                        if self._is_notna_any_to_numpy(node))
        self.assertEqual(
            [hit.split(':')[0] for hit in hits], [self.OWNER],
            '候选池判空只许写在 column_profile.keep_columns_with_values（当前命中：%r）' % hits)


class HistogramCandidatesSizingTests(SimpleTestCase):
    """新键进体积账：`_column_profile_bytes` 遍历 items() 必须把它按真实量级计。"""

    def test_histogram_candidates_enter_the_size_ledger(self):
        cols = [f'PAR{i:04d}' for i in range(1702)]
        frame = pd.DataFrame({c: [1.0, 2.0, 3.0] for c in cols})
        profile = column_profile.build_column_profile(frame, 'CTA8290D')
        four_only = {k: v for k, v in profile.items()
                    if k in column_profile.COLUMN_PROFILE_KEYS}
        delta = (sizing._column_profile_bytes(profile)
                 - sizing._column_profile_bytes(four_only))
        self.assertEqual(
            delta,
            len(HIST_KEY) + sum(len(c) for c in profile[HIST_KEY]),
            '新键的列名清单必须逐字符进账，不许被当成 64 字节')


# ───────────────────────────── ⑤ 体积核算 ─────────────────────────────

class ColumnProfileBytesTests(SimpleTestCase):
    """这只 dict 必须计入缓存体积——1702 列那档它是几十 KB，不是 64 字节。"""

    def test_profile_bytes_are_the_real_magnitude_not_64_per_key(self):
        cols = [f'PAR{i:04d}' for i in range(1702)]
        frame = pd.DataFrame({c: [1.0, 2.0, 3.0] for c in cols})
        metadata = _md_of(frame)
        col_meta = services.build_col_meta(frame, metadata)
        profile = column_profile.build_column_profile(frame, 'CTA8290D')
        profile_bytes = sizing._column_profile_bytes(profile)

        self.assertEqual(len(profile['numeric_columns']), 1702)
        self.assertGreater(profile_bytes, 8 * 1024,
                           f'1702 个列名的真实量级是十几 KB，实测只算出 {profile_bytes}')
        entry = dict(metadata, col_meta=col_meta, column_profile=profile)
        value_bytes = sizing._parse_value_bytes((frame, entry, 'CTA8290D'))
        self.assertGreaterEqual(
            value_bytes,
            sizing._frame_bytes(frame) + sizing._col_meta_bytes(entry) + profile_bytes,
            '体积账必须同时覆盖帧、col_meta 与 column_profile 三块真实量级')
        self.assertGreater(
            value_bytes, sizing._frame_bytes(frame) + 64 * len(entry),
            '沿用「metadata 每键 64 字节」会低估')

    def test_absent_or_malformed_profile_counts_as_zero(self):
        self.assertEqual(sizing._column_profile_bytes(None), 0)
        self.assertEqual(sizing._column_profile_bytes('x'), 0)
        self.assertEqual(sizing._column_profile_bytes({}), 0)

    def test_parse_without_profile_key_still_accounts_for_frame_and_col_meta(self):
        frame = pd.DataFrame({'P1': [1.0, 2.0], 'P2': [3.0, 4.0]})
        metadata = _md_of(frame)
        without = (frame, dict(metadata, col_meta=services.build_col_meta(frame, metadata)),
                   'CTA8290D')
        self.assertGreaterEqual(
            sizing._parse_value_bytes(without),
            sizing._frame_bytes(without[0]) + sizing._col_meta_bytes(without[1]))
