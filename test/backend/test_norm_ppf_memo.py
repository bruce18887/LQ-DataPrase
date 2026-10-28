"""A6：QQ 图理论分位数（osm）按样本数记忆化的 T1 判据（无 DB）。

章节横幅与本文件头 ①–⑦ 一一对账（A6b 复审，2026-10-28）：7 节 / 22 例 =
① 逐位一致 5 例、② 只算一次 4 例、③ 只读共享 5 例、④ 形状回归 4 例、
⑤ 变异自证 1 例、⑥ 内存账 2 例、⑦ worker 侧可 import 1 例。
旁路阈值边界（``OSM_MEMO_MAX_N``）在 ① 的 ``test_memoized_osm_is_bit_identical_at_the_memo_boundary``、
② 的 ``test_oversized_n_bypasses_the_cache_without_being_wrong``、③ 的两条分支
（界内 50 / 界外 ``OSM_MEMO_MAX_N + 1``）各钉一次。被钉的实现都在
``apps/analysis/services/statistics/distributions.py``：

① **逐位一致** —— 记忆化通路必须与「逐元素 Python 循环」的改前写法全等（值/形状/dtype）。
   基线是本文件内**固定的一份改前原样副本**（``_baseline_*``），不依赖 git、网络或临时文件。
② **只算一次** —— 同一 n 的多次请求只跑 1 组（恰 n 次）``inv_cdf``，换 n 才再算一组。
   这条是「你触发且你坏」的承重判据，由 ⑤ 的运行时变异证明它去掉缓存就会转红。
③ **只读共享** —— 分两层钉，别把两层混在同一条里：
   **契约**（口径无关）＝ 同 n 连取两次都是 ``writeable False`` 的数组、就地写抛 ``ValueError``、
   强开 ``WRITEABLE`` 之后也改不动缓存里那份、且值逐位等于基线；界内缓存与界外旁路两条分支都覆盖
   （``test_returned_osm_is_read_only_on_both_branches`` / ``test_escape_hatch_cannot_reach_the_cached_value``）。
   **实现口径**（零拷贝）＝ 两次取用共享同一块 ``bytes`` 缓冲、``WRITEABLE`` 连打开都不允许，
   只由性能绊线 ``test_hot_path_returns_zero_copy_view_as_performance_tripwire`` 钉：合法把取数改成
   ``np.frombuffer(...).copy()`` 再冻结时，红的是绊线，按该条 docstring 改它自己，契约两条不动。
   缓存值形状由 ``test_cached_value_is_immutable_compact_bytes`` 钉成 ``bytes``（8B/元素、不可变）。
   （同仓对「跨请求共享的缓存值」的立场见 ``apps/datafiles/tests_parse_cache_scan.py``
   的 ``SharedFrameSafetyTests``。）
④ **形状回归** —— 空输入、n≤3、``sxx == 0``、端到端键集合与两条序列长度逐字段不变。
⑤ **变异自证** —— 只在内存里换实现（产品文件一行不动），证明 ② 的计数判据确实「你触发且你坏」。
⑥ **内存账** —— ``maxsize × n 上界 × 每元素字节`` 这笔账必须算得过来。
⑦ **worker 侧可 import** —— CPU worker 链路（``apps/jobs/runner.py:21``，无 ``django.setup()``）
   必须仍在**没有 Django 环境**的子进程里 import 干净 —— 判据是运行时子进程，
   不是 AST 扫顶层 import（AST 抓不到函数内延迟 import 与包 ``__init__`` 的传递依赖；照 A4 的先例）。

数值入口口径不变（lessons R4）：不改判据、不引入新的近似或舍入。
"""
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from django.test import SimpleTestCase

from apps.analysis.services.statistics import computations, distributions

# ---------------------------------------------------------------------------
# 改前实现的原样副本（逐字抄自 distributions.py 整改前，本文件内固定的基线）
# ---------------------------------------------------------------------------


def _baseline_norm_ppf(q):
    """Quantile function of the standard normal distribution (vectorised)."""
    arr = np.asarray(q, dtype=float)
    flat = arr.reshape(-1)
    if flat.size == 0:
        return arr.copy()
    inv = statistics.NormalDist().inv_cdf
    out = np.array([inv(float(p)) for p in flat], dtype=float)
    return out.reshape(arr.shape)


def _baseline_filliben_medians(n):
    v = np.empty(n, dtype=np.float64)
    v[-1] = 0.5 ** (1.0 / n)
    v[0] = 1 - v[-1]
    i = np.arange(2, n)
    v[1:-1] = (i - 0.3175) / (n + 0.365)
    return v


def _baseline_norm_probplot(x):
    values = np.asarray(x, dtype=float)
    if values.size == 0:
        return ((values, values), (np.nan, np.nan, 0.0))
    n = values.size
    osm = _baseline_norm_ppf(_baseline_filliben_medians(n))
    osr = np.sort(values)
    x_mean = osm.mean()
    y_mean = osr.mean()
    sxx = float(np.sum((osm - x_mean) ** 2))
    if sxx == 0:
        return ((osm, osr), (np.nan, np.nan, np.nan))
    sxy = float(np.sum((osm - x_mean) * (osr - y_mean)))
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    syy = float(np.sum((osr - y_mean) ** 2))
    r = sxy / np.sqrt(sxx * syy) if syy > 0 else np.nan
    return ((osm, osr), (slope, intercept, r))


# ---------------------------------------------------------------------------
# inv_cdf 计数代理
# ---------------------------------------------------------------------------

_REAL_NORMAL_DIST = statistics.NormalDist
_CALLS = []


class _CountingNormalDist(_REAL_NORMAL_DIST):
    """把每次 ``inv_cdf`` 记进 ``_CALLS``，数值原样委托给真实现（零数值影响）。

    替换的是 ``statistics`` 模块上的**名字**，不是 ``NormalDist.inv_cdf`` 本身——
    手里已攥着原类对象的别处不受牵连，还原只需一行赋值。
    """

    def inv_cdf(self, p):                      # noqa: D102
        _CALLS.append(p)
        return _REAL_NORMAL_DIST.inv_cdf(self, p)


_QQ_KEYS = {'theoretical_quantiles', 'observed_quantiles', 'r_squared', 'is_normal',
            'n', 'outlier_info', 'slope', 'intercept'}


def norm_probplot_fields(x, baseline=False):
    """把新旧两条 norm_probplot 摊成同一套字段，便于逐字段比。"""
    fn = _baseline_norm_probplot if baseline else distributions.norm_probplot
    (osm, osr), (slope, intercept, r) = fn(x)
    return (osm, osr), (slope, intercept, r)


class _MemoCaseBase(SimpleTestCase):
    """三把共用扳手：取记忆化通路、清缓存、装 inv_cdf 计数器。"""

    def memo(self, n):
        fn = getattr(distributions, '_theoretical_quantiles', None)
        self.assertIsNotNone(fn, 'A6 的取数入口 _theoretical_quantiles 不存在')
        return fn(n)

    def clear_memo(self):
        memo = getattr(distributions, '_osm_for_n', None)
        self.assertIsNotNone(memo, 'A6 的记忆化入口 _osm_for_n 不存在（缓存未实现）')
        cache_clear = getattr(memo, 'cache_clear', None)
        self.assertIsNotNone(cache_clear, '_osm_for_n 必须是 lru_cache 包装的（要能清账）')
        cache_clear()

    def spy_inv_cdf(self):
        original = statistics.NormalDist
        del _CALLS[:]
        statistics.NormalDist = _CountingNormalDist
        self.addCleanup(setattr, statistics, 'NormalDist', original)
        return _CALLS

    def setUp(self):                                       # noqa: D102
        self.clear_memo()

    @staticmethod
    def _assert_same_array(what, got, want):
        """值/形状/dtype 三项逐字相同；NaN 位置也算相同。"""
        if (got.shape, got.dtype) != (want.shape, want.dtype):
            raise AssertionError(
                f'{what} 形状/dtype 漂了：got {got.shape}/{got.dtype} vs {want.shape}/{want.dtype}')
        if not np.array_equal(got, want, equal_nan=True):
            bad = np.flatnonzero(~(got == want) & ~((got != got) & (want != want)))
            raise AssertionError(f'{what} 逐位不等，首个差异 @{int(bad[0]) if bad.size else -1}: '
                                 f'{got.ravel()[bad[:3]].tolist()} vs {want.ravel()[bad[:3]].tolist()}')


# ─────────────────────────── ① 逐位一致 ───────────────────────────

class MemoBitEquivalenceTests(_MemoCaseBase):

    def test_memoized_osm_is_bit_identical_to_the_elementwise_baseline(self):
        """n ∈ {1..200 全部, 999, 1000, 5000}：记忆化 == 现逐元素算，逐位。"""
        for n in list(range(1, 201)) + [999, 1000, 5000]:
            with self.subTest(n=n):
                self._assert_same_array(f'osm n={n}', self.memo(n),
                                        _baseline_norm_ppf(_baseline_filliben_medians(n)))

    def test_memoized_osm_is_bit_identical_at_the_memo_boundary(self):
        """旁路阈值与 n 上界是**同一颗旋钮**（OSM_MEMO_MAX_N），故从两侧各钉一格：
        界内走缓存、界外现算，两侧都必须与基线逐位相同、且形状/dtype 一致。
        """
        bound = distributions.OSM_MEMO_MAX_N
        for n in (bound - 1, bound, bound + 1, bound + 2):
            with self.subTest(n=n):
                self._assert_same_array(f'osm n={n}', self.memo(n),
                                        _baseline_norm_ppf(_baseline_filliben_medians(n)))

    def test_norm_probplot_fields_are_bit_identical_to_the_baseline(self):
        """整条 norm_probplot（含最小二乘那三个数）与改前逐字段全等。"""
        rng = np.random.default_rng(20261028)
        for n in (1, 2, 3, 12, 97, 512, 1000, 5000, distributions.OSM_MEMO_MAX_N + 1):
            with self.subTest(n=n):
                x = rng.normal(3.0, 0.7, n)
                (g_osm, g_osr), (g_s, g_i, g_r) = norm_probplot_fields(x)
                (b_osm, b_osr), (b_s, b_i, b_r) = norm_probplot_fields(
                    x, baseline=True)
                self._assert_same_array(f'probplot osm n={n}', g_osm, b_osm)
                self._assert_same_array(f'probplot osr n={n}', g_osr, b_osr)
                for name, got, want in (('slope', g_s, b_s), ('intercept', g_i, b_i),
                                        ('r', g_r, b_r)):
                    self.assertEqual(repr(float(got)), repr(float(want)),
                                     f'n={n} 的 {name} 变了')

    def test_norm_ppf_public_signature_and_semantics_are_unchanged(self):
        """norm_ppf 仍是「任意 q、逐元素算」：标量/列表/二维/空数组一格没动，
        也没有被顺手 memoize 成按 q 键（那会把缓存键从 n 换成 q，内存账整个作废）。
        """
        cases = {
            'scalar': 0.025,
            'pair': [0.025, 0.975],
            '2d': np.linspace(0.01, 0.99, 12).reshape(3, 4),
            'empty': np.empty((0,)),
            'empty-2d': np.empty((2, 0)),
        }
        for name, q in cases.items():
            with self.subTest(case=name):
                self._assert_same_array(f'norm_ppf {name}', distributions.norm_ppf(q),
                                        _baseline_norm_ppf(q))
        self.assertEqual(distributions.norm_ppf(np.linspace(0.01, 0.99, 12).reshape(3, 4)).shape,
                         (3, 4), 'reshape 形状必须按输入形状还原')

    def test_norm_ppf_is_not_memoized_on_q(self):
        """norm_ppf 本身不许进缓存：否则键从 n 变成 q，元素数与内存账都不是 OSM_MEMO_MAX_N 那笔。"""
        self.assertFalse(hasattr(distributions.norm_ppf, 'cache_info'),
                         'norm_ppf 被 memoize 了 —— A6 只允许按 n 记忆化')
        self.assertTrue(hasattr(distributions._osm_for_n, 'cache_info'))
        self.assertFalse(hasattr(distributions, '_filliben_medians_cache'))


# ─────────────────────────── ② 只算一次 ───────────────────────────

class MemoHitAccountingTests(_MemoCaseBase):

    def test_repeated_same_n_computes_exactly_one_group_of_inv_cdf(self):
        n, requests = 97, 5
        calls = self.spy_inv_cdf()
        for _ in range(requests):
            distributions.norm_probplot(np.arange(1, n + 1, dtype=float))
        self.assertEqual(len(calls), n,
                         f'{requests} 次同 n 请求共调了 {len(calls)} 次 inv_cdf，'
                         f'记忆化只应算 1 组（{n} 次）')
        info = distributions._osm_for_n.cache_info()
        self.assertEqual((info.misses, info.hits), (1, requests - 1))

    def test_changing_n_computes_a_second_group(self):
        n1, n2 = 40, 60
        calls = self.spy_inv_cdf()
        distributions.norm_probplot(np.zeros(n1))
        distributions.norm_probplot(np.zeros(n1))
        distributions.norm_probplot(np.zeros(n2))
        self.assertEqual(len(calls), n1 + n2,
                         '换 n 必须再算一组；同 n 不许重算')

    def test_cache_key_is_the_bare_int_n(self):
        """键必须是裸 ``int n``——用同一个 n 直接命中缓存，而不是重新构造某个包装键。"""
        n = 23
        calls = self.spy_inv_cdf()
        distributions.norm_probplot(np.zeros(n))
        self.assertEqual(len(calls), n)
        distributions._osm_for_n(n)                       # 与 norm_probplot 同一个键
        self.assertEqual(distributions._osm_for_n.cache_info().hits, 1,
                         'norm_probplot 用的键不是裸 int n（外部用 n 取不到同一份）')
        self.assertEqual(distributions._osm_for_n.cache_info().misses, 1)

    def test_oversized_n_bypasses_the_cache_without_being_wrong(self):
        """界外现算：值仍逐位正确，但**不占缓存槽**（否则单只超大 n 会挤掉热小 n 的条目）。"""
        bound = distributions.OSM_MEMO_MAX_N
        n = bound + 1
        # 基线先算完再装计数器：否则「现算基线」的那 n 次会被记进 bypass 的账上。
        want = _baseline_norm_ppf(_baseline_filliben_medians(n))
        calls = self.spy_inv_cdf()
        got = self.memo(n)
        self._assert_same_array('bypass osm', got, want)
        self.assertEqual(len(calls), n)
        info = distributions._osm_for_n.cache_info()
        self.assertEqual((info.misses, info.currsize), (0, 0),
                         '界外 n 进了缓存 —— 大 n 会把 maxsize 的槽位挤空')
        got2 = self.memo(n)
        self.assertEqual(len(calls), 2 * n, '界外第二次仍应现算（既然没缓存）')
        self._assert_same_array('bypass osm 第二次', got2, got)


# ─────────────────────────── ③ 只读共享 ───────────────────────────

class ReadOnlySharedOsmTests(_MemoCaseBase):

    def test_cached_value_is_immutable_compact_bytes(self):
        """缓存值形状钉死：bytes（8B/元素、不可变），不是 ndarray、不是 tuple of float。"""
        value = distributions._osm_for_n(9)
        self.assertIs(type(value), bytes,
                      '缓存值必须是 bytes —— ndarray 会被就地改写，tuple 每元素 ~32B')
        self.assertEqual(len(value), 9 * np.dtype(np.float64).itemsize)

    def test_returned_osm_is_read_only_on_both_branches(self):
        """契约（口径无关）：界内缓存与界外旁路两条分支、同 n 连取两次，每次都必须
        ``writeable False``、就地写抛 ``ValueError``、且值仍逐位等于基线。

        本条不数缓冲、不看 ``base``、不判共享：取数口径合法改成
        ``np.frombuffer(...).copy()`` 再冻结 ``writeable=False``（仍只读、仍只算一次、值仍逐位
        相等）时，本条必须**仍绿**——它只问「拿到手的东西能不能改、值对不对」，不问「拷没拷」。
        """
        for n in (1, 50, distributions.OSM_MEMO_MAX_N + 1):      # 界内 / 界内 / 界外旁路
            want = _baseline_norm_ppf(_baseline_filliben_medians(n))
            with self.subTest(n=n):
                for k in ('第一次', '第二次'):
                    osm = self.memo(n)
                    self.assertFalse(osm.flags.writeable,
                                     f'n={n} {k} 取回的 osm 可写 = 把可就地改写的共享数组交给调用方')
                    with self.assertRaises(ValueError):
                        osm[0] = 123.0
                    self._assert_same_array(f'n={n} {k} 仍是基线值', osm, want)

    def test_escape_hatch_cannot_reach_the_cached_value(self):
        """契约的另一半，同样口径无关：强开 ``WRITEABLE`` 允不允许是**口径**（``bytes`` 视图关；
        ``.copy()`` 冻结副本按 numpy 2.4.4 实测打得开），**改不动缓存**才是契约。
        于是两种口径都只判同一件事：逃逸被拒绝就照旧，被放行也只许写进自己攥着的那份，
        重新取用必须仍是只读的基线值。「视图连打开都不允许」这条口径由下面的绊线钉。
        """
        for n in (50, distributions.OSM_MEMO_MAX_N + 1):
            want = _baseline_norm_ppf(_baseline_filliben_medians(n))
            with self.subTest(n=n):
                osm = self.memo(n)
                try:
                    osm.flags.writeable = True
                except ValueError:
                    pass                                   # 现口径：这条路是关的
                else:
                    osm[0] = 123.0                         # 合法的 .copy() 口径：只写到自己那份副本
                fresh = self.memo(n)
                self.assertFalse(fresh.flags.writeable, f'n={n} 逃逸后重新取用拿到可写数组')
                self._assert_same_array(f'n={n} 逃逸后重新取用仍是基线值', fresh, want)

    def test_hot_path_returns_zero_copy_view_as_performance_tripwire(self):
        """这条钉的是**实现口径**而非契约（性能绊线，红了只该改本条）：界内取数必须是缓存
        ``bytes`` 上的**零拷贝只读视图**——同 n 两次取用共享同一块缓冲（``np.shares_memory``），
        且 ``WRITEABLE`` 连打开都不允许（只有不可变缓冲的视图才有的性质）。

        为什么它不算契约：把取数合法改成 ``np.frombuffer(...).copy()`` 再冻结，值仍逐位相等、
        仍只读、仍只算一次，契约两条全绿，唯独这里红——那是一次**合法重构的必然红**，
        所以应当**连同本条一起改掉**（改成断 ``.copy()`` 口径，或直接删掉本条），
        别去动 ``test_returned_osm_is_read_only_on_both_branches`` /
        ``test_escape_hatch_cannot_reach_the_cached_value``。
        界外（``n > OSM_MEMO_MAX_N``）本来就每次现算、从不共享，所以只在界内取 n。
        """
        n = 64
        first = self.memo(n)
        self.assertTrue(np.shares_memory(first, self.memo(n)),
                        '界内取数不再是零拷贝视图：若这是有意的口径变更（如 .copy() 后冻结），'
                        '按本条 docstring 只改本条，上面两条契约判据不必动')
        with self.assertRaises(ValueError):
            first.flags.writeable = True                   # 同一口径的另一面：视图逃逸也是关的

    def test_product_consumer_still_reads_the_same_values(self):
        """只读化的真实代价由唯一消费者验：computations 只读 osm（mean/平方/取索引）。"""
        x = pd.Series(np.linspace(-2.0, 2.0, 300))
        out = computations.compute_qqplot(x)
        self.assertEqual(set(out), _QQ_KEYS)
        self.assertEqual(len(out['theoretical_quantiles']), 300)
        self.assertGreater(out['r_squared'], 0.9)
        self.assertFalse(out['is_normal'] is False and out['r_squared'] == 0.0,
                         '消费者走进了 except 兜底分支（osm 只读化把活儿撞坏了）')


# ─────────────────────────── ④ 形状回归 ───────────────────────────

class ProbplotShapeRegressionTests(_MemoCaseBase):

    def test_empty_input_returns_the_identical_tuple(self):
        for x in (np.array([]), np.empty((0,)), pd.Series([], dtype=float)):
            with self.subTest(kind=type(x).__name__):
                got = distributions.norm_probplot(x)
                want = _baseline_norm_probplot(x)
                self.assertEqual(len(got), 2)
                self.assertEqual(len(got), len(want))
                for i in (0, 1):
                    self.assertEqual(len(got[i]), len(want[i]))
                self._assert_same_array('empty osm', got[0][0], want[0][0])
                self._assert_same_array('empty osr', got[0][1], want[0][1])
                self.assertEqual([repr(float(v)) for v in got[1]],
                                 [repr(float(v)) for v in want[1]])

    def test_tiny_n_branches_are_unchanged(self):
        """n=1（v[-1] 与 v[0] 是同一元素）、n=2（arange(2,2) 空切片）、n<3 各钉一格。"""
        for n in (1, 2, 3):
            with self.subTest(n=n):
                x = np.asarray([5.0] * n) if n == 1 else np.arange(1.0, n + 1.0)
                got = distributions.norm_probplot(x)
                want = _baseline_norm_probplot(x)
                self._assert_same_array(f'n={n} osm', got[0][0], want[0][0])
                self._assert_same_array(f'n={n} osr', got[0][1], want[0][1])
                self.assertEqual([repr(float(v)) for v in got[1]],
                                 [repr(float(v)) for v in want[1]],
                                 f'n={n} 的拟合三元组变了')

    def test_constant_data_sxx_zero_branch_is_unchanged(self):
        for n in (3, 40):
            with self.subTest(n=n):
                got = distributions.norm_probplot(np.full(n, 7.0))
                want = _baseline_norm_probplot(np.full(n, 7.0))
                self._assert_same_array(f'const n={n} osm', got[0][0], want[0][0])
                self.assertEqual([repr(float(v)) for v in got[1]],
                                 [repr(float(v)) for v in want[1]])

    def test_compute_qqplot_end_to_end_shape_is_unchanged(self):
        """小夹具端到端：键集合与两条序列长度不变；阈值上下各一条（降采样通路也吃 osm）。"""
        cases = {'small': 40, 'over-threshold': computations.DOWN_SAMPLE_THRESHOLD + 1}
        for name, n in cases.items():
            with self.subTest(case=name):
                x = pd.Series(np.linspace(-3.0, 3.0, n))
                out = computations.compute_qqplot(x)
                self.assertEqual(set(out), _QQ_KEYS, f'{name} 的键集合变了')
                self.assertEqual(out['n'], n)
                self.assertEqual(len(out['theoretical_quantiles']),
                                 len(out['observed_quantiles']))
                self.assertTrue(out['theoretical_quantiles'], f'{name} 返回了空分位数')
                self.assertIsInstance(out['theoretical_quantiles'][0], float)
                self.assertIsInstance(out['outlier_info'], dict)


# ─────────────────────────── ⑤ 变异自证 ───────────────────────────

class MutationSelfCheckTests(_MemoCaseBase):

    def test_runtime_no_cache_mutation_reddens_the_count_criterion(self):
        """「你触发且你坏」：只在内存里把 _osm_for_n 换成**不带缓存**的等价实现
        （保留 cache_clear/cache_info，好让红只落在计数判据上），计数必须翻倍。
        产品文件一行未动（前后 sha256 一致记在 tasks/perf-review-2026-10-27/A6-mutation-red.log）。
        """
        n = 50
        original = distributions._osm_for_n

        def mutated(k):                       # 与 _osm_for_n 同值，只是每次现算
            return _baseline_norm_ppf(_baseline_filliben_medians(k)).tobytes()

        mutated.cache_clear = lambda: None
        mutated.cache_info = original.cache_info
        mutated.cache_parameters = original.cache_parameters
        distributions._osm_for_n = mutated
        self.addCleanup(setattr, distributions, '_osm_for_n', original)

        calls = self.spy_inv_cdf()
        for _ in range(3):
            distributions.norm_probplot(np.arange(1, n + 1, dtype=float))
        self.assertEqual(len(calls), 3 * n,
                         '变异没生效：计数判据对「去掉缓存」不敏感，那条 ② 是假绿')


# ─────────────────────────── ⑥ 内存账 ───────────────────────────

class MemoMemoryBudgetTests(_MemoCaseBase):

    def test_cache_footprint_arithmetic_stays_within_the_written_budget(self):
        """maxsize × n 上界 × 每元素字节 ≤ 预算。**这笔账是活的**：
        把 OSM_MEMO_MAXSIZE 从 32 抬到 512 会在这里当场红，而不是悄悄涨到 409.6MB。
        """
        itemsize = np.dtype(np.float64).itemsize
        maxsize = distributions._osm_for_n.cache_parameters()['maxsize']
        self.assertEqual(maxsize, distributions.OSM_MEMO_MAXSIZE,
                         '装饰器用的 maxsize 与文档常量不是同一个数（账就白算了）')
        worst = maxsize * distributions.OSM_MEMO_MAX_N * itemsize
        self.assertLessEqual(worst, distributions.OSM_MEMO_BUDGET_BYTES,
                             f'最坏情况 {worst:,}B 超预算 '
                             f'{distributions.OSM_MEMO_BUDGET_BYTES:,}B —— 重算这笔账再改常量')
        self.assertEqual(maxsize, 32, 'maxsize 的可变性就钉在这里：动它必须同时动预算')
        self.assertLessEqual(distributions.OSM_MEMO_MAX_N, 100_000,
                            'n 上界抬高同样要重算预算')

    def test_budget_constants_are_stated_in_bytes_per_element_not_per_object(self):
        """缓存值必须按**字节**记账（8B/元素），计划正文的 tuple 形状是 ~32B/元素。"""
        self.assertEqual(np.dtype(np.float64).itemsize, 8)
        self.assertGreater(distributions.OSM_MEMO_MAX_N, 68_000,
                           '上界必须盖住本仓实测最大单参数列行数（68k）')


# ─────────────────────────── ⑦ worker 侧可 import ───────────────────────────

class WorkerDjangoFreeImportTests(_MemoCaseBase):

    def test_module_imports_cleanly_in_a_django_free_subprocess(self):
        """运行时判据（照 A4 先例）：CPU worker 链路（apps/jobs/runner.py:21）没有
        ``django.setup()``。AST 扫顶层 import 抓不到函数内延迟 import 与包 __init__ 的
        传递依赖，所以按 worker 的真实形态跑一次子进程：``sys.modules`` 里必须零个 django。
        """
        # ROOT/apps/analysis/services/statistics/distributions.py ⇒ parents[4] 才是仓根
        root = Path(distributions.__file__).resolve().parents[4]
        self.assertTrue((root / 'manage.py').is_file(),
                        f'子进程的 cwd 算错了（{root} 不是仓根）——空 cwd 下这条永远红/永远假绿')
        probe = subprocess.run(
            [sys.executable, '-X', 'utf8', '-c',
             'import sys; import apps.analysis.services.statistics.distributions;'
             ' print([m for m in sys.modules if m.startswith("django")])'],
            cwd=str(root), capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=120)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), '[]',
                         'distributions 在没 django.setup() 的进程里必须 import 得干净')
