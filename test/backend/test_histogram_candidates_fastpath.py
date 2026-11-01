"""T1（A4b）：histogram fast path 消费「随解析写透缓存」的专用候选列。

被钉的契约：
① 有缓存 ⇒ 逐字采用（``build_histogram_param_candidates`` 现算 0 次）——marker 取的是
   **帧上真有、但现算口径必排**的 ``SW_Bin``（object 数字串列）：它能过「名单落在当前
   帧上」那道守卫，又只有缓存里可能存在，旧写法端不出来；
② 缺 profile / 缺该键 ⇒ **回落现算**，值与改动前 fast path 逐字相等，绝不因缺键返回空参数；
③ 空列表是合法值不是缺键：直接采用、不回落；
④ ``data_only_bin1=True``：行过滤不会让 object/bool 列变可测数值（不新增），但可能让
   原本非空的列过滤后全 NaN（要剔除）——必须以全帧候选为池、在过滤后帧上再跑一次向量化判空；
⑤ ``ignore_no_limit=True``：走 ``get_columns_with_limits``，不消费候选（旧实现算而不用，
   A4b 后干脆不算——结果不许变）；
⑥ 缓存列表是**跨请求共享对象**：交给下游 ``filter_test_items`` 的必须是副本，
   任何就地改写都不许落到缓存里（质量复审 Minor：那记 `list()` 拷贝原本无判据）；
⑦ profile 里**两只口径同框**时取的是 histogram 那只——browse 的 `numeric_columns`
   一旦被误当候选池，前端可选参数集就变了（M9 存活后补的判据）；
⑧ 缓存名单里有帧上不存在的列 ⇒ 该条目不描述当前帧，整只**回落现算**（质量复审
   Important：取名单列会 KeyError，缺席名单不该变成 500 也不该端给用户）；
⑨ ``data_only_bin1`` 与 ``ignore_no_limit`` **同时为真**：limits 口径优先，候选不参与
   （⑤只测了单开关，两开关的组合形态此前无人钉）。

视图侧基线 ``_old_fast_path_params`` 是改动前 ``analysis_views.py`` 的 histogram fast
path 那段（提交 8f78d10 那一版，测试项开关全关时的形状）的原样搬运——按行号引会随每次
改动腐掉，所以钉的是版本与形状。打桩用 ``apps.analysis.test_support.patch_df_loader``
（R6③：消费模块的绑定）；候选计数只 patch 口径模块一处绑定——取数规则已收进
``column_profile.resolve_histogram_candidates``，视图不再直接 import 那只函数。
"""

import types

import pandas as pd
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.analysis import test_support
from apps.analysis.services.statistics import (
    filter_bin1_rows,
    get_columns_with_limits,
    get_serial_candidates,
    get_site_column,
)
from apps.analysis.test_support import fake_datafile
from apps.analysis.views import AnalysisViewSet
from apps.analysis.views import analysis_views
from apps.analysis.views._helpers import _filter_blank_params
from apps.datafiles import column_profile

HIST_KEY = 'histogram_numeric_columns'


# ───────────────────────────── 基线（逐字搬运，不许优化） ─────────────────────────────

def _old_fast_path_params(df, metadata, *, data_only_bin1=False, ignore_no_limit=False):
    """改动前 histogram fast path（全帧派生候选那段）的原样搬运。

    与 ``_filter_blank_params`` 的收尾一起构成「旧实现在开关全关时返回什么」的对照物。
    """
    if data_only_bin1:
        df = filter_bin1_rows(df, metadata)
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
    if ignore_no_limit:
        params = get_columns_with_limits(df, metadata)
    else:
        params = numeric_cols
    return _filter_blank_params(params)


# ───────────────────────────── 夹具 ─────────────────────────────

def _hist_frame():
    """含序列/site/bool/全 NaN/object 数字串列的帧；旧口径候选 = ['CONST_V', 'PAR0001']。"""
    return pd.DataFrame({
        'Serial_No': pd.Series([11, 12, 13, 14, 15]),
        'Site_No': pd.Series(['1', 'nan', None, '2', '2'], dtype='object'),
        'Dut_No': pd.Series([1, 2, 3, 4, 5]),
        'Dut_Pass': pd.Series([True, False, True, True, False]),
        'SW_Bin': pd.Series(['1', '5', '7', '1', '5'], dtype='object'),
        'QR_Code': pd.Series([float('nan')] * 5),
        'TEXT': pd.Series(['a', 'b', 'c', 'd', 'e'], dtype='object'),
        'CONST_V': pd.Series([2.5] * 5),
        'PAR0001': pd.Series([1.0, 2.0, None, 4.0, 5.0]),
    })


def _bin1_frame():
    """PAR_GONE 只在非 Bin1 行有值：全帧候选含它，行过滤后必须被剔除。"""
    return pd.DataFrame({
        'SW_Bin': pd.Series(['1', '1', '5'], dtype='object'),
        'P1': pd.Series([1.0, 2.0, 3.0]),
        'PAR_GONE': pd.Series([float('nan'), float('nan'), 3.0]),
    })


def _md_of(frame):
    return {
        'format': 'CTA8290D',
        'units': {c: 'um' for c in frame.columns},
        'mins': {c: '-999.9999' for c in frame.columns},
        'maxs': {c: '999.9999' for c in frame.columns},
    }


def _fake_user():
    return types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False, settings=None,
    )


def _spy_candidates(case):
    """候选口径现算计数。

    A4b 复审整改把取数规则从视图搬进了 `resolve_histogram_candidates`，所以
    `build_histogram_param_candidates` 的绑定**只剩一处**（口径模块自己）——原先
    「视图 `from x import y` 另建绑定、两处都要换」（R6③）是视图直连口径时的形状，
    现在视图不认识那只函数了。少 patch 一处就会把「回落」误记成「没回落」。
    """
    state = {'calls': 0}
    real = column_profile.build_histogram_param_candidates

    def wrapper(df):
        state['calls'] += 1
        return real(df)

    case.addCleanup(setattr, column_profile, 'build_histogram_param_candidates', real)
    column_profile.build_histogram_param_candidates = wrapper
    return state


class HistogramFastPathCacheTests(SimpleTestCase):
    """fast path 的「用缓存 / 回落 / 空列表 / bin1 再筛 / ignore_no_limit / 交副本 / 取哪只口径」。"""

    def _call(self, df, metadata, payload=None):
        restore = test_support.patch_df_loader(df, fake_datafile(), metadata)
        try:
            request = APIRequestFactory().post(
                '/api/v1/analysis/histogram/', dict(payload or {}), format='json')
            force_authenticate(request, user=_fake_user())
            response = AnalysisViewSet.as_view({'post': 'histogram'})(request)
            response.render()
            return response
        finally:
            restore()

    def _params(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return list(response.data['results'])

    # ① 有缓存 ⇒ 逐字采用，一次都不现算
    def test_cached_candidates_are_used_verbatim_without_recompute(self):
        frame = _hist_frame()
        metadata = _md_of(frame)
        # marker 用的是**帧上真有、但纯 dtype 口径必排**的 `SW_Bin`（object 数字串列）：
        # 它既过得了「名单必须落在当前帧上」那道守卫（⑧ 要的就是那道），又不可能
        # 被任何一次现算端出来——响应里有它，才证明 fast path 吃的是缓存那只名单。
        metadata['column_profile'] = {HIST_KEY: ['PAR0001', 'SW_Bin']}
        state = self._spy()
        params = self._params(self._call(frame, metadata))
        self.assertEqual(params, ['PAR0001', 'SW_Bin'],
                         'SW_Bin 只存在于缓存名单：现算口径永远不收 object 列')
        self.assertEqual(state['calls'], 0, '有缓存候选还现算，这一刀等于没做')

    def _spy(self):
        return _spy_candidates(self)

    # ② 缺键/缺 profile ⇒ 回落现算，值与旧实现逐字相等
    def test_missing_profile_falls_back_to_inline_computation(self):
        frame = _hist_frame()
        for name, mutate in (
            ('no profile at all', lambda md: None),
            ('legacy 4-key profile', lambda md: md.update(
                {'column_profile': {k: [] for k in column_profile.COLUMN_PROFILE_KEYS
                                    if k != HIST_KEY}})),
        ):
            with self.subTest(case=name):
                metadata = _md_of(frame)
                mutate(metadata)
                state = self._spy()
                params = self._params(self._call(frame, metadata))
                self.assertEqual(
                    params, _old_fast_path_params(frame, metadata),
                    f'{name}：回落值必须等于改动前 fast path 逐字结果')
                self.assertTrue(params, '回落不许给出空参数集')
                self.assertEqual(state['calls'], 1, f'{name}：回落应现算恰一次')

    # ③ 空列表是合法值（帧里确实没有候选列）：采用，不回落
    def test_empty_candidates_list_is_adopted_not_recomputed(self):
        frame = _hist_frame()
        metadata = _md_of(frame)
        metadata['column_profile'] = {HIST_KEY: []}
        state = self._spy()
        params = self._params(self._call(frame, metadata))
        self.assertEqual(params, [])
        self.assertEqual(state['calls'], 0, '空列表≠缺键：按真值判断回落会每次请求白扫一遍帧')

    # ④ data_only_bin1：过滤后全 NaN 的候选列要剔除（缓存是全帧口径，行过滤只减不增）
    def test_data_only_bin1_drops_candidates_all_nan_after_filter(self):
        frame = _bin1_frame()
        metadata = _md_of(frame)
        cached = _old_fast_path_params(frame, metadata)  # 全帧候选：含 PAR_GONE
        self.assertIn('PAR_GONE', cached, '前提：全帧上 PAR_GONE 非空、是候选')
        metadata['column_profile'] = {HIST_KEY: cached}
        expected = _old_fast_path_params(frame, metadata, data_only_bin1=True)
        self.assertEqual(expected, ['P1'], '前提：旧实现过滤后把 PAR_GONE 剔了')
        params = self._params(self._call(frame, metadata, {'data_only_bin1': 'true'}))
        self.assertEqual(
            params, expected,
            '直接吃全帧候选不再筛会把过滤后已全空的列留在参数集里（改结果）')

    def test_data_only_bin1_without_profile_matches_old_path(self):
        frame = _bin1_frame()
        metadata = _md_of(frame)
        state = self._spy()
        params = self._params(self._call(frame, metadata, {'data_only_bin1': 'true'}))
        self.assertEqual(params, _old_fast_path_params(frame, metadata, data_only_bin1=True))
        self.assertEqual(state['calls'], 1, '缺 profile 时回落现算（对过滤后帧），恰一次')

    # ⑤ ignore_no_limit：最终参数走 limits 口径，候选既不消费也不必先算（结果不许变）
    def test_ignore_no_limit_uses_limits_and_does_not_consume_candidates(self):
        frame = _hist_frame()
        metadata = _md_of(frame)
        metadata['column_profile'] = {HIST_KEY: ['PHANTOM_MARK_9999']}
        state = self._spy()
        params = self._params(
            self._call(frame, metadata, {'ignore_no_limit': 'true'}))
        self.assertEqual(params, _old_fast_path_params(
            frame, metadata, ignore_no_limit=True))
        self.assertNotIn('PHANTOM_MARK_9999', params, '候选不得渗入 limits 分支')
        self.assertEqual(state['calls'], 0,
                         '旧实现算了不用；A4b 允许不算，但结果必须仍是 limits 口径')

    # ⑥ 下游拿到的必须是副本：缓存列表是跨请求共享对象，就地改会污染后续请求
    def test_downstream_receives_a_copy_not_the_cached_list_itself(self):
        frame = _hist_frame()
        metadata = _md_of(frame)
        cached = ['PAR0001', 'CONST_V']
        metadata['column_profile'] = {HIST_KEY: cached}
        seen = {}
        real = analysis_views.filter_test_items

        def mutating(df, md, params, **kwargs):
            seen['obj'] = params
            params.append('MUTATED_IN_PLACE')   # 模拟将来某个就地改的消费者
            return real(df, md, params, **kwargs)

        self.addCleanup(setattr, analysis_views, 'filter_test_items', real)
        analysis_views.filter_test_items = mutating
        self._params(self._call(frame, metadata))
        self.assertIsNot(seen['obj'], cached,
                         '把缓存里那只列表直接交下去了：下游一改就跨请求传染')
        self.assertEqual(cached, ['PAR0001', 'CONST_V'],
                         '缓存列表被下游就地改写了（解析缓存被写脏）')

    # ⑦ 两只口径同时在 profile 里时，fast path 必须吃 histogram 那只
    def test_profile_with_both_calibers_consumes_the_histogram_key(self):
        """browse 的 `numeric_columns` 与 A4b 的内部键**同框**时的取谁判据。

        上面几条的假 profile 只写直方图那一只键，所以「视图误用 browse 集合」这种
        改法在当时一条都不红（M9 存活实测）——而恰恰是那种误用会把序列/site 列与
        数字字符串列塞进前端可选参数，那是契约变更，不是性能问题。
        """
        frame = _hist_frame()
        metadata = _md_of(frame)
        browse_numeric = column_profile.build_column_profile(frame, 'CTA8290D')['numeric_columns']
        hist = column_profile.build_histogram_param_candidates(frame)
        self.assertNotEqual(browse_numeric, hist, '前提：两套口径确实不等价')
        for col in ('Serial_No', 'SW_Bin'):
            self.assertIn(col, browse_numeric, f'前提：browse 口径收 {col}')
            self.assertNotIn(col, hist, f'前提：直方图口径不收 {col}')
        metadata['column_profile'] = {
            'numeric_columns': browse_numeric,
            HIST_KEY: hist,
        }
        params = self._params(self._call(frame, metadata))
        self.assertEqual(params, hist,
                         'fast path 吃了 browse 的 numeric_columns：可选参数集被换掉')
        for col in ('Serial_No', 'SW_Bin'):
            self.assertNotIn(col, params, f'{col} 只属于 browse 口径，不许进参数集')

    # ⑧ 缓存里出现了帧上没有的列名 ⇒ 这只条目不描述当前帧，整只回落现算（不许 500）
    def test_cached_names_absent_from_frame_fall_back_to_recompute(self):
        frame = _hist_frame()
        metadata = _md_of(frame)
        metadata['column_profile'] = {
            HIST_KEY: ['PAR0001', 'PHANTOM_MARK_9999'],
        }
        state = self._spy()
        # data_only_bin1 为真时 fast path 要在过滤后帧上按名单取列：名单里有帧上没有的
        # 名字，`df[cols]` 直接 KeyError ⇒ 500。回落路径没有这个洞，缓存路径必须有。
        params = self._params(self._call(frame, metadata, {'data_only_bin1': 'true'}))
        self.assertEqual(
            params, _old_fast_path_params(frame, metadata, data_only_bin1=True),
            '名单不匹配当前帧时必须重算，而不是把脏名单端给用户或报错')
        self.assertNotIn('PHANTOM_MARK_9999', params)
        self.assertEqual(state['calls'], 1, '名单不匹配=按缺席处理，回落恰一次')

    # ⑨ 两个开关同时为真：limits 口径优先，候选既不消费也不参与
    def test_bin1_and_ignore_no_limit_together_use_limits_caliber(self):
        frame = _bin1_frame()
        metadata = _md_of(frame)
        metadata['column_profile'] = {HIST_KEY: ['PHANTOM_MARK_9999']}
        state = self._spy()
        params = self._params(self._call(
            frame, metadata, {'data_only_bin1': 'true', 'ignore_no_limit': 'true'}))
        self.assertEqual(params, _old_fast_path_params(
            frame, metadata, data_only_bin1=True, ignore_no_limit=True))
        self.assertNotIn('PHANTOM_MARK_9999', params)
        self.assertEqual(state['calls'], 0)

    # 等价性总闸：缓存值本来就应等于现算值时，两条路响应逐字一致
    def test_cached_and_inline_paths_agree_with_the_old_computation(self):
        for name, build in (('hist frame', _hist_frame), ('bin1 frame', _bin1_frame)):
            frame = build()
            metadata = _md_of(frame)
            fresh = column_profile.build_histogram_param_candidates(frame)
            metadata['column_profile'] = {HIST_KEY: fresh}
            for bin1 in (False, True):
                with self.subTest(frame=name, data_only_bin1=bin1):
                    payload = {'data_only_bin1': 'true'} if bin1 else {}
                    self.assertEqual(
                        self._params(self._call(frame, metadata, payload)),
                        _old_fast_path_params(frame, metadata, data_only_bin1=bin1))
