"""T1（G2）：低 CPK 集合缓存 —— 内容坐标键、真 LRU、单飞。

背景（2026-10-28 波次 G 的第二半）：``apps/analysis/views/_helpers.py`` 里那只
``_low_cpk_cache`` 原本是 **plain dict + 超 500 条全清**，键里带 ``user_id``。
三个问题各自有判据：

① **键是内容坐标**：低 CPK 集合是 ``(df, metadata, threshold, iqr_multiplier,
   data_only_bin1)`` 的纯函数 —— ``threshold`` 已经把「用户设置」这唯一一条用户输入
   折成了实参。同一只物理文件的两行（两个 owner）必须共用一次计算、拿到**同一只** set；
   真实路径族的键里既没有 ``user_id``（形参已删）也没有 ``datafile.id``（行号会把同一只
   文件拆成两条）。生产形状的判据是 ``LowCpkCacheCrossOwnerRealRowsTests``
   （两行真 DataFile + 解析计数）。
② **真 LRU**：超上限逐**最久未用的一条**，不是全清。500 条上限的生产实例上直接跑
   501 个 key ⇒ 剩 500 条、第一条不在（旧实现 501 条全留 —— 它只在「下一次插入」时
   才 wholesale clear，那条 red 是本文件的承重红）。
③ **单飞**：并发 miss 只计算一次（旧 plain dict 两个线程各算一遍）。

外加两条「改缓存不许弄丢」的守卫（旧实现就是绿的，先绿不假红）：
④ 空集也是合法结果，必须命中复用（不能用 truthiness 判「没缓存」）；
⑤ mtime/size 变 ⇒ 换 key ⇒ 重算（文件重解析自动失效，既有语义）。

键有两只族（见 ``_helpers._low_cpk_cache_key``）：真实路径族第一元是 ``str``；测试替身
没有可用 ``file_path`` 时退回 ``(datafile.id, 0, 0, ...)``。本文件的纯单元用例用退回族
（不需要建库），跨 owner 的共享用真实路径族（``LowCpkCacheCrossOwnerRealRowsTests``）。

隔离：``_low_cpk_cache`` 是进程级共享状态，每个用例前后各清一次（不换实例：红/绿差异
必须只来自语义，不能来自「测试换了一只缓存」）；容量那条用的就是这只生产实例。
"""
import inspect
import os
import shutil
import tempfile
import threading
import types
from unittest import mock

import pandas as pd
from django.test import SimpleTestCase, TestCase, override_settings

from apps.accounts.models import User
from apps.analysis.services.statistics import (
    compute_low_cpk_test_items,
    filter_bin1_rows,
)
from apps.analysis.views import _helpers
from apps.datafiles import services
from apps.datafiles.models import DataFile
from apps.datafiles.utils import store_file_path


def _frame():
    return pd.DataFrame({
        'SW_Bin': [1, 1, 2, 1],
        'P1': [1.0, 2.0, 3.0, 4.0],
        'P2': [10.0, 10.1, 10.2, 10.3],
    })


_METADATA = {
    'format': 'CTA8290D',
    'units': {'P1': 'V', 'P2': 'V'},
    'mins': {'P1': '0', 'P2': '9'},
    'maxs': {'P1': '5', 'P2': '11'},
}


def _fake_datafile(pk=7, file_path=''):
    """视图侧的真形状：只读 ``.id`` / ``.file_path`` / ``.format_type``。"""
    return types.SimpleNamespace(id=pk, file_path=file_path, format_type='CTA8290D')


class _LowCpkCacheCaseBase(SimpleTestCase):
    def setUp(self):
        # 用**生产实例**（不换）：旧形状是 plain dict、新形状是 KeyedLRU，
        # 两条路都能跑 ⇒ 红/绿差异只可能来自语义，不来自「测试换了一只缓存」。
        # 进程级共享 ⇒ 每个用例前后各清一次。
        self.cache = _helpers._low_cpk_cache
        self.cache.clear()
        self.addCleanup(self.cache.clear)
        self.df = _frame()
        self.metadata = dict(_METADATA)

    def call(self, threshold=1.33, iqr=1.5, bin1=False, datafile=None):
        return _helpers.cached_low_cpk_items(
            datafile or _fake_datafile(), self.df, self.metadata,
            threshold, iqr, bin1)

    def spy_compute(self, results=None):
        """patch 消费方绑定：``_helpers`` 是函数内 import，实际查的是包上的属性。"""
        if results is None:
            results = {'P1'}
        return mock.patch(
            'apps.analysis.services.statistics.compute_low_cpk_test_items',
            side_effect=lambda *a, **k: set(results))


class LowCpkCacheKeyTests(_LowCpkCacheCaseBase):
    """① 键去 user / 去行号；阈值/iqr/bin1 仍在键里（否则就是把「共享」做成「串味」）。"""

    def test_same_row_twice_computes_once(self):
        """对照组（旧实现也绿）：同一行第二次必须命中。"""
        with self.spy_compute() as spy:
            first = self.call()
            second = self.call()
        self.assertEqual(spy.call_count, 1)
        self.assertIs(first, second)

    def test_threshold_still_discriminates(self):
        """用户设置经 ``threshold`` 进来 ⇒ 它必须仍在键里，否则两阈值会互相串味。"""
        with self.spy_compute() as spy:
            loose = self.call(threshold=1.33)
            tight = self.call(threshold=2.0)
        self.assertEqual(spy.call_count, 2)
        self.assertIsNot(loose, tight)

    def test_iqr_and_bin1_still_discriminate(self):
        with self.spy_compute() as spy:
            self.call(iqr=1.5)
            self.call(iqr=2.0)
            self.call(bin1=True)
        self.assertEqual(spy.call_count, 3,
                         'iqr_multiplier 与 data_only_bin1 各是一个输入，必须各换一个 key')

    def test_result_is_a_pure_function_of_the_file_and_the_resolved_threshold(self):
        """行为面的「不靠用户」：同阈值连读两次 ⇒ 同一只 set，内容等于真算。"""
        real = compute_low_cpk_test_items
        expected = real(self.df, self.metadata, 100.0)
        self.assertTrue(expected, '前提：100.0 这档阈值下帧里确有低 CPK 列')
        with mock.patch('apps.analysis.services.statistics.compute_low_cpk_test_items',
                        side_effect=real) as spy:
            first = self.call(threshold=100.0)
            second = self.call(threshold=100.0)
        self.assertEqual(spy.call_count, 1)
        self.assertIs(first, second)
        self.assertEqual(first, expected)

    def test_fallback_key_family_is_the_row_id(self):
        """路径读不出来 ⇒ 退回 ``(id, 0, 0, format, ...)``，与真实路径族（第一元 str）不可能撞。"""
        fallback = _helpers._low_cpk_cache_key(_fake_datafile(pk=7), 1.33, 1.5, False)
        self.assertEqual(fallback, (7, 0, 0, 'CTA8290D', 1.33, 1.5, False))

        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        st = os.stat(path)
        real = _helpers._low_cpk_cache_key(
            _fake_datafile(pk=7, file_path=path), 1.33, 1.5, False)
        self.assertEqual(
            real, (path, st.st_mtime_ns, st.st_size, 'CTA8290D', 1.33, 1.5, False))
        self.assertIsInstance(real[0], str)
        self.assertIsInstance(fallback[0], int)
        self.assertNotEqual(real, fallback)

    def test_compute_signatures_have_no_user_shaped_parameters(self):
        """只证明**签名**：两条计算函数没有 user/owner/request/settings 形参。

        它抓不住函数体里读全局用户设置 —— 那由行为判据（同阈值只算一次 + 结果等于真算）
        兜；本条是机械下限，不是「不依赖用户」的完整证明。
        """
        user_shaped = ('user', 'owner', 'request', 'settings')
        for fn in (compute_low_cpk_test_items, filter_bin1_rows):
            params = list(inspect.signature(fn).parameters)
            self.assertFalse(
                [p for p in params if any(t in p.lower() for t in user_shaped)],
                f'{fn.__name__} 的参数里出现了用户相关输入 {params}；'
                '一旦它真依赖用户，低 CPK 缓存就不许跨用户共享')


class _CountingParser:
    def __init__(self, frame, metadata):
        self.frame = frame
        self.metadata = metadata
        self.calls = 0

    def parse(self, path):
        self.calls += 1
        return self.frame, dict(self.metadata)


class LowCpkCacheCrossOwnerRealRowsTests(TestCase):
    """① 生产形状：两行（两个 owner）指向同一只物理文件 ⇒ 解析 1 次、低 CPK 算 1 次。"""

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix='lqdp-g2-lowcpk-')
        self.addCleanup(shutil.rmtree, self.media_root, True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)

        self.user_a = User.objects.create_user(
            username='g2_low_cpk_a', password='pw', role='user')
        self.user_b = User.objects.create_user(
            username='g2_low_cpk_b', password='pw', role='user')

        original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', original_cache)
        services._parse_cache = services._BytesLRUCache(
            services.PARSE_CACHE_BUDGET_BYTES)
        services.clear_parse_cache()
        self.addCleanup(services.clear_parse_cache)
        _helpers._low_cpk_cache.clear()
        self.addCleanup(_helpers._low_cpk_cache.clear)

        self.frame = _frame()
        self.parser = _CountingParser(self.frame, _METADATA)
        original_parser = services.get_parser
        self.addCleanup(setattr, services, 'get_parser', original_parser)
        services.get_parser = lambda fmt: self.parser

        self.path = os.path.join(self.media_root, 'data', 'shared', 'one.csv')
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('[Data]\nBin,P1,P2\n1,1,10\n')
        self.metadata = dict(_METADATA)

    def make_row(self, user, name='one.csv', fmt='CTA8290D'):
        return DataFile.objects.create(
            owner=user, filename=name,
            file_path=store_file_path(self.path),
            file_size=os.path.getsize(self.path),
            format_type=fmt, file_type='single', status='ready',
        )

    def load(self, row, user):
        return services.get_cached_parsed_file(row.id, user.pk, row)

    def test_two_owners_of_one_physical_file_compute_once(self):
        row_a = self.make_row(self.user_a)
        row_b = self.make_row(self.user_b)
        df_a, md_a, _ = self.load(row_a, self.user_a)
        df_b, md_b, _ = self.load(row_b, self.user_b)
        self.assertEqual(self.parser.calls, 1, '前提：两行同一物理文件只解析 1 次')

        with mock.patch(
                'apps.analysis.services.statistics.compute_low_cpk_test_items',
                side_effect=lambda *a, **k: {'P1'}) as spy:
            first = _helpers.cached_low_cpk_items(
                row_a, df_a, md_a, 1.33, 1.5, False)
            second = _helpers.cached_low_cpk_items(
                row_b, df_b, md_b, 1.33, 1.5, False)

        self.assertEqual(spy.call_count, 1,
                         f'两 owner 同阈值应只算 1 次，实际 {spy.call_count} 次')
        self.assertIs(first, second, '两 owner 必须拿到同一只共享 set')

    def test_same_owner_two_reads_compute_once(self):
        """对照组：同一行连读两次也只有 1 次解析、1 次计算。"""
        row = self.make_row(self.user_a)
        df, md, _ = self.load(row, self.user_a)
        with mock.patch(
                'apps.analysis.services.statistics.compute_low_cpk_test_items',
                side_effect=lambda *a, **k: {'P1'}) as spy:
            first = _helpers.cached_low_cpk_items(row, df, md, 1.33, 1.5, False)
            second = _helpers.cached_low_cpk_items(row, df, md, 1.33, 1.5, False)
        self.assertEqual(self.parser.calls, 1)
        self.assertEqual(spy.call_count, 1)
        self.assertIs(first, second)

    def test_same_path_two_format_types_compute_each_bin_column(self):
        """① 同一路径两行标成不同格式 ⇒ 两条 key，各按自己格式的 Bin 列算。

        漏掉 ``format_type`` 时第二行命中第一行的条目（键只剩路径/mtime/size/阈值等），
        拿到另一只 parser 那套列上的低 CPK 集合：ETS88 的 bin 列是 ``Bin``（全 pass），
        CTA8290D 的是 ``SW_Bin``（无 pass 行 ⇒ 空帧 ⇒ 空集），两者结果本就不同。
        """
        row_ets = self.make_row(self.user_a, fmt='ETS88')
        row_cta = self.make_row(self.user_b, fmt='CTA8290D')
        frame = pd.DataFrame({
            'Bin': [1, 1, 1, 1],        # ETS88：全部 pass ⇒ 全帧参与
            'SW_Bin': [2, 2, 2, 2],     # CTA8290D：无 pass 行 ⇒ 空帧
            'P1': [1.0, 2.0, 3.0, 4.0],
            'P2': [10.0, 10.1, 10.2, 10.3],
        })
        md_ets = dict(_METADATA, format='ETS88')
        md_cta = dict(_METADATA, format='CTA8290D')
        self.assertEqual(
            compute_low_cpk_test_items(filter_bin1_rows(frame, md_ets), md_ets, 1.0),
            {'P1'}, '前提：ETS88 全帧下只有 P1 低 CPK（P2 的 CPK≈2.5）')
        self.assertEqual(
            compute_low_cpk_test_items(filter_bin1_rows(frame, md_cta), md_cta, 1.0),
            set(), '前提：CTA8290D 的 bin 列无 pass 行，过滤后为空帧')

        real = compute_low_cpk_test_items
        with mock.patch('apps.analysis.services.statistics.compute_low_cpk_test_items',
                        side_effect=real) as spy:
            ets = _helpers.cached_low_cpk_items(
                row_ets, frame, md_ets, 1.0, 1.5, True)
            cta = _helpers.cached_low_cpk_items(
                row_cta, frame, md_cta, 1.0, 1.5, True)

        self.assertEqual(ets, {'P1'})
        self.assertEqual(cta, set(),
                         "CTA8290D 必须拿到自己的空集，不是 ETS88 的 {'P1'}")
        self.assertEqual(spy.call_count, 2, '两种格式必须各算一次')
        self.assertEqual(len(_helpers._low_cpk_cache), 2,
                         '同一路径的两种格式各占一条 key')


class LowCpkCacheEvictionTests(_LowCpkCacheCaseBase):
    """② 真 LRU：逐最久未用的一条，不是 wholesale clear。"""

    def test_production_cache_keeps_500_and_drops_only_the_oldest(self):
        cache = self.cache
        df, md = _frame(), dict(_METADATA)
        datafile = _fake_datafile(pk=99)
        with mock.patch(
                'apps.analysis.services.statistics.compute_low_cpk_test_items',
                side_effect=lambda *a, **k: {'P1'}):
            for i in range(501):
                _helpers.cached_low_cpk_items(
                    datafile, df, md, 1.0 + i / 1000.0, 1.5, False)

        self.assertEqual(len(cache), 500,
                         '旧实现没有上限：501 条会全留着（下一次插入才 wholesale clear 剩 1 条）')
        self.assertEqual(_helpers._LOW_CPK_CACHE_MAX_ENTRIES, 500,
                         '容量口径变了就要连同本条一起改')
        keys = _cache_keys(cache)
        self.assertNotIn((99, 0, 0, 'CTA8290D', 1.0, 1.5, False), keys,
                         '第一条（最久未用）必须已被逐出')
        self.assertIn((99, 0, 0, 'CTA8290D', 1.5, 1.5, False), keys,
                      '最新一条必须在')

    def test_eviction_is_lru_not_just_capacity(self):
        """超上限时被逐的是**最久未用**那条：先命中过的最老条目必须留下。

        旧实现没有「命中刷新顺序」这回事，第 501 次插入时也**不清**（清空发生在
        「下一次插入」那一刻）⇒ 本用例在长度断言上先红（501 != 500），LRU 顺序
        那三条只有在长度口径对上之后才轮得到判。
        """
        cache = self.cache
        df, md = _frame(), dict(_METADATA)
        datafile = _fake_datafile(pk=98)
        with mock.patch(
                'apps.analysis.services.statistics.compute_low_cpk_test_items',
                side_effect=lambda *a, **k: {'P1'}):
            for i in range(500):
                _helpers.cached_low_cpk_items(
                    datafile, df, md, 1.0 + i / 1000.0, 1.5, False)
            _helpers.cached_low_cpk_items(datafile, df, md, 1.0, 1.5, False)
            _helpers.cached_low_cpk_items(datafile, df, md, 9.9, 1.5, False)

        keys = _cache_keys(cache)
        self.assertEqual(len(keys), 500)
        self.assertIn((98, 0, 0, 'CTA8290D', 1.0, 1.5, False), keys, '刚命中过，不许逐')
        self.assertNotIn((98, 0, 0, 'CTA8290D', 1.001, 1.5, False), keys,
                         '最久未用的那条才该走')
        self.assertIn((98, 0, 0, 'CTA8290D', 9.9, 1.5, False), keys)


class LowCpkCacheSingleFlightTests(_LowCpkCacheCaseBase):
    """③ 并发 miss 只算一次。"""

    def test_concurrent_misses_compute_once(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow_compute(*a, **k):
            calls.append(1)
            entered.set()
            release.wait(timeout=10)
            return {'P1'}

        results = {}
        with mock.patch('apps.analysis.services.statistics.compute_low_cpk_test_items',
                        side_effect=slow_compute):
            t1 = threading.Thread(
                target=lambda: results.setdefault('a', self.call()))
            t1.start()
            self.assertTrue(entered.wait(5), '前提：第一个线程已进入 compute')
            t2 = threading.Thread(
                target=lambda: results.setdefault('b', self.call()))
            t2.start()
            t2.join(timeout=0.2)
            self.assertTrue(t2.is_alive(), '前提：第二个线程挂在同 key 上等发布')
            release.set()
            t1.join(timeout=10)
            t2.join(timeout=10)

        self.assertFalse(t1.is_alive() or t2.is_alive(), '谁都不许死等')
        self.assertEqual(len(calls), 1,
                         f'并发 miss 应单飞，实际计算 {len(calls)} 次')
        self.assertIs(results['a'], results['b'])

    def test_failed_compute_wakes_the_waiter_and_recomputes(self):
        """③ 失败路径：owner 的 compute 抛错 ⇒ 异常回给 owner，等待者被唤醒后自己重算。

        漏掉失败段的 ``notify_all`` ⇒ 等待者永远挂在 Condition 上；漏掉
        ``pending.discard`` ⇒ 等待者醒来看到 key 还在 pending，继续等一个没有主人
        的条目。两种都表现为本用例的 join 超时 / 结果缺失。
        """
        entered = threading.Event()
        release = threading.Event()
        calls = []
        results = {}

        def compute_impl(*a, **k):
            calls.append(1)
            if len(calls) == 1:            # 只有 owner 那次失败
                entered.set()
                release.wait(timeout=10)
                raise RuntimeError('boom')
            return {'P1'}

        def owner_call():
            try:
                self.call()
            except RuntimeError as exc:
                results['owner'] = exc

        with mock.patch('apps.analysis.services.statistics.compute_low_cpk_test_items',
                        side_effect=compute_impl):
            t1 = threading.Thread(target=owner_call, daemon=True)
            t1.start()
            self.assertTrue(entered.wait(5), '前提：owner 已进入 compute')
            t2 = threading.Thread(
                target=lambda: results.setdefault('waiter', self.call()),
                daemon=True)
            t2.start()
            t2.join(timeout=0.2)
            self.assertTrue(t2.is_alive(), '前提：等待者挂在同 key 上等发布')
            release.set()
            t1.join(timeout=10)
            t2.join(timeout=10)

            self.assertFalse(t1.is_alive() or t2.is_alive(),
                             '失败不许把等待者挂死（notify 丢了就是这样）')
            self.assertIsInstance(results.get('owner'), RuntimeError,
                                  '异常必须原样回给 owner')
            self.assertEqual(results.get('waiter'), {'P1'},
                             '等待者被唤醒后自己重算并成功（失败不永久化）')
            third = self.call()

        self.assertEqual(third, {'P1'}, '后续调用同样可用')
        self.assertEqual(len(calls), 2,
                         f'失败 1 次 + 等待者重算 1 次 = 2；第三次必须命中，实际 {len(calls)}')


class LowCpkCacheGuardsTests(_LowCpkCacheCaseBase):
    """④⑤ 改缓存不许弄丢的两条既有语义（旧实现同样绿 —— 明确记为守卫，不当收益）。"""

    def test_empty_set_is_a_valid_cached_result(self):
        with self.spy_compute(results=set()) as spy:
            first = self.call()
            second = self.call()
        self.assertEqual(spy.call_count, 1,
                         '空集也必须命中：用 truthiness 判缓存会把每次请求都重算')
        self.assertIs(first, second)
        self.assertEqual(first, set())

    def test_mtime_or_size_change_recomputes(self):
        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        datafile = types.SimpleNamespace(
            id=42, file_path=path, format_type='CTA8290D')
        with self.spy_compute() as spy:
            self.call(datafile=datafile)
            st = os.stat(path)
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2 * 10 ** 9))
            self.call(datafile=datafile)
        self.assertEqual(spy.call_count, 2,
                         'mtime 变 ⇒ 内容坐标换 key ⇒ 必须重算')


def _cache_keys(cache):
    """取缓存里现存 key 的顺序快照（``KeyedLRU._data`` 的键序即 LRU 序）。"""
    return list(cache._data.keys())
