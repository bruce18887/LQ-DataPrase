"""T1（A4 的契约⑤ + 那条「决策见证」）：column_profile 的体积核算与直方图口径差异。

本文件是 `test_column_profile_cache.py` 拆出来的另一半（2026-10-28 质量复审整改：主文件
598 行贴到 600 阈，把「体积核算」与「口径差异」两族连同它们专用的小夹具搬来）。
**断言一条没改、一条没弱化**，两文件合计仍是 21 例（`Ran N` 与拆分前相等）。

夹具（``_fragile_frame`` / ``_md_of``）是本文件内的**原样副本**，不与主文件共享对象：
测试基线宁可重复，也不许做成「另一个文件改一下这里就跟着变」的共享可变状态。
``_baseline_histogram_candidates`` 只有本文件的见证用例用，所以是搬来而非复制。
"""

import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.statistics.helpers import (
    get_serial_candidates,
    get_site_column,
)
from apps.datafiles import column_profile, services
from apps.datafiles import parse_cache_sizing as sizing


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
    """改动前 ``analysis_views.py:106-122`` 那段（``data_only_bin1`` 为假时的形状）的搬运。

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

    这就是 A4 选「不动 histogram」的证据：把 profile 直接喂给 ``analysis_views.py:113-122``
    会把序列/site 列和数字字符串 object 列塞进前端可选参数集，而那边还要在
    ``data_only_bin1`` 为真时先收窄行再派生——那才是契约变更。

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
