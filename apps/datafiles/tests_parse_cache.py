"""解析缓存的字节预算与并发单飞测试（2026-09-02 审计批次 2）。

原实现是 ``@lru_cache(maxsize=64)`` 按**条数**限流，但每个值是一整只
DataFrame（实测 10 万行 × 826 列 ≈ 667MB）——几张大表同时驻留就是数 GB
常驻内存；且 ``lru_cache`` 不合并并发 miss，首屏 3 个请求会把同一只文件
各解析一遍（单次解析实测约 4s）。
"""
import os
import re
import shutil
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest import mock

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from apps.datafiles import services
from apps.datafiles.views import _helpers


def _frame(rows=2000, cols=6):
    """造一只可测量大小的 DataFrame。"""
    data = {f'P{i}': [float(r * i + r) for r in range(rows)] for i in range(cols)}
    return pd.DataFrame(data)


class _CountingParser:
    """假解析器：统计被真正解析的次数，可注入耗时。"""

    def __init__(self, frame, delay=0.0, metadata=None):
        self.frame = frame
        self.delay = delay
        self.calls = 0
        # 默认沿用旧形状 {'format': 'CTA8290D'}（所有既有调用点行为不变）；
        # J7 用例需要一份带真实 units/mins/maxs 的 metadata 来体现 col_meta 的量级。
        self.metadata = metadata if metadata is not None else {'format': 'CTA8290D'}

    def parse(self, path):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return self.frame, dict(self.metadata)


class _CacheCaseBase(SimpleTestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', self.original_cache)
        # 每个用例都必须从空缓存开始：模块级 _parse_cache 是进程共享的，
        # 不换掉的话别的用例（甚至其他 test module）留下的条目会污染断言。
        self.use_budget(services.PARSE_CACHE_BUDGET_BYTES)

    def use_budget(self, budget_bytes):
        services._parse_cache = services._BytesLRUCache(budget_bytes)
        return services._parse_cache

    def patch_parser(self, frame, delay=0.0, metadata=None):
        parser = _CountingParser(frame, delay, metadata)
        original = services.get_parser
        services.get_parser = lambda fmt: parser
        self.addCleanup(setattr, services, 'get_parser', original)
        return parser

    def cached_parse(self, file_id=1, owner_id=1):
        return services._cached_parse(file_id, owner_id, 12345, self.path, 'CTA8290D')

    def second_path(self):
        """坐标化之后，**换 key 的唯一手段是换内容坐标**（路径/mtime/格式），
        `file_id` 与 `owner_id` 都不再进键 —— 造第二只物理文件供需要两个 key 的用例使用。"""
        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path


class BytesLRUCacheTests(_CacheCaseBase):
    def test_second_request_for_same_file_is_not_reparsed(self):
        frame = _frame()
        parser = self.patch_parser(frame)

        first = self.cached_parse()
        second = self.cached_parse()

        self.assertEqual(parser.calls, 1, f'解析被调用 {parser.calls} 次，应命中缓存')
        self.assertIs(second[0], first[0])

    def test_two_owners_of_one_physical_file_share_one_entry(self):
        """J1：键去 owner 化之后，同一路径的第二个调用方必须复用同一只帧。

        旧代码在这里必然红（键含 owner_id ⇒ 两个 key ⇒ parser 解析两次），
        所以这条先红后绿本身就是对照组。
        """
        frame = _frame()
        parser = self.patch_parser(frame)

        first = services._cached_parse(11, 1, 12345, self.path, 'CTA8290D')
        second = services._cached_parse(22, 2, 12345, self.path, 'CTA8290D')

        self.assertIs(first[0], second[0])
        self.assertEqual(len(services._parse_cache), 1, '同一路径只该有一条缓存')
        self.assertEqual(parser.calls, 1, f'实际解析 {parser.calls} 次')

    def test_get_or_compute_without_store_if_stores_unconditionally(self):
        """`store_if` 缺省（None）＝无条件存——钉住 spec §2.2「与今天逐字一致」那条承诺。

        这条不走 `_cached_parse`，直接打 `get_or_compute`：今天「不传就照存」只是读代码
        得到的担保，没有任何断言。用一只 `_parse_succeeded` 会判 False 的失败值来存，
        这样一旦缺省分支被改成「默认套用成功判据」，条目数就会从 1 掉到 0、当场红。
        """
        cache = self.use_budget(services.PARSE_CACHE_BUDGET_BYTES)
        failure = (None, None, 'CTA8290D')
        self.assertFalse(services._parse_succeeded(failure), '前提：这是 store_if 会拒绝的值')

        key = ('/tmp/unconditional.csv', 1, 'CTA8290D')
        out = cache.get_or_compute(key, lambda: failure)

        self.assertIs(out, failure)
        self.assertEqual(len(cache), 1, '不传 store_if 时条目必须照存（无条件）')
        self.assertIs(cache.get_or_compute(key, lambda: _frame())[0], None,
                      '第二次必须命中第一条存下的值，而不是重新计算')

    def test_entries_evict_by_byte_budget_not_by_count(self):
        frame = _frame()
        one = services._frame_bytes(frame)
        budget = int(one * 1.6)   # 只装得下一只
        self.use_budget(budget)
        parser = self.patch_parser(frame)

        self.cached_parse()
        services._cached_parse(2, 2, 12345, self.second_path(), 'CTA8290D')

        cache = services._parse_cache
        self.assertLessEqual(cache.bytes_cached(), budget,
                             '缓存总量必须始终不超过预算')
        self.assertEqual(len(cache), 1)
        self.cached_parse()   # 旧条目已被挤掉 → 重新解析
        self.assertEqual(parser.calls, 3)

    def test_single_oversized_value_is_returned_but_not_cached(self):
        frame = _frame()
        self.use_budget(int(services._frame_bytes(frame) * 0.5))
        parser = self.patch_parser(frame)

        df_a, _meta_a, _fmt_a = self.cached_parse()
        df_b, _meta_b, _fmt_b = self.cached_parse()

        self.assertEqual(len(services._parse_cache), 0,
                         '单只超预算的帧不该塞进缓存（否则会立刻自逐）')
        self.assertEqual(parser.calls, 2, '超预算时仍要每次返回正确数据')
        self.assertIs(df_a, df_b)

    def test_clear_drops_everything(self):
        self.patch_parser(_frame())
        self.cached_parse()
        self.assertEqual(len(services._parse_cache), 1)

        services.clear_parse_cache()

        self.assertEqual(len(services._parse_cache), 0)
        self.assertEqual(services._parse_cache.bytes_cached(), 0)
        self.cached_parse()   # 清完再取仍可正常工作

    def test_concurrent_miss_for_same_key_parses_once(self):
        parser = self.patch_parser(_frame(), delay=0.3)
        results = {}

        def worker(name):
            results[name] = self.cached_parse()

        t1 = threading.Thread(target=worker, args=('a',))
        t2 = threading.Thread(target=worker, args=('b',))
        t1.start()
        time.sleep(0.05)      # 让 t1 进入「解析中」状态
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(parser.calls, 1,
                         f'并发 miss 应单飞，实际解析 {parser.calls} 次')
        self.assertIs(results['a'][0], results['b'][0])

    def test_concurrent_miss_from_two_owners_parses_once(self):
        """J3：跨 owner 的单飞才是这一刀的收益——20 人首开同一文件该只解析一次。"""
        parser = self.patch_parser(_frame(), delay=0.3)
        results = {}

        def worker(name, file_id, owner_id):
            results[name] = services._cached_parse(file_id, owner_id, 12345,
                                                   self.path, 'CTA8290D')

        t1 = threading.Thread(target=worker, args=('a', 11, 1))
        t2 = threading.Thread(target=worker, args=('b', 22, 2))
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(parser.calls, 1,
                         f'两个 owner 并发 miss 应共用一次解析，实际 {parser.calls} 次')
        self.assertIs(results['a'][0], results['b'][0])

    def test_failed_parse_is_not_stuck_as_pending(self):
        """解析抛错后等待者必须能继续，而不是被永久挂住的 pending 拖死。"""
        class Boom:
            def parse(self, path):
                raise RuntimeError('disk on fire')

        original = services.get_parser
        services.get_parser = lambda fmt: Boom()
        self.addCleanup(setattr, services, 'get_parser', original)
        self.use_budget(64 * 1024 * 1024)

        df, meta, fmt = services._cached_parse(1, 1, 1, self.path, 'CTA8290D')
        self.assertIsNone(df)
        # pending 必须已释放：再来一次不会卡死
        df2, _m2, _f2 = services._cached_parse(1, 1, 1, self.path, 'CTA8290D')
        self.assertIsNone(df2)

    def test_failed_parse_does_not_occupy_a_cache_entry(self):
        """失败结果不许占位：它算出 0 字节，而 0 字节条目连 LRU 都淘汰不动。

        旧行为是「永久化到那只文件 mtime 变化为止」；坐标化之后爆炸半径会从
        一个人放大到同一路径的所有人，所以这条必须在改键之前就绿。
        """
        class Boom:
            def parse(self, path):
                raise RuntimeError('disk on fire')

        original = services.get_parser
        services.get_parser = lambda fmt: Boom()
        self.addCleanup(setattr, services, 'get_parser', original)
        self.use_budget(64 * 1024 * 1024)

        first = services._cached_parse(1, 1, 1, self.path, 'CTA8290D')
        second = services._cached_parse(1, 1, 1, self.path, 'CTA8290D')

        self.assertIsNone(first[0])
        self.assertIsNone(second[0])
        self.assertEqual(len(services._parse_cache), 0, '失败结果不许进缓存')
        self.assertEqual(services.get_parse_cache_stats()['misses'], 2,
                         '第二次必须真的重试，而不是命中那条 0 字节的失败记录')

    def test_missing_file_hint_preserved(self):
        """文件不在磁盘上时返回 (None, None, format_type) 的既有契约不变，且不占缓存。"""
        parser = self.patch_parser(_frame())
        missing = os.path.join(tempfile.gettempdir(), 'nope_does_not_exist.csv')

        out = services._cached_parse(9, 1, 1, missing, 'CTA8290D')
        again = services._cached_parse(9, 1, 1, missing, 'CTA8290D')

        self.assertEqual(out, (None, None, 'CTA8290D'))
        self.assertEqual(parser.calls, 0)
        self.assertEqual(len(services._parse_cache), 0,
                         '缺文件的失败同样不许入缓存')
        self.assertEqual(again, (None, None, 'CTA8290D'),
                         '重试必须返回同一条契约，而不是被缓存改写成别的形状')

    def test_hits_misses_and_clears_are_counted(self):
        self.patch_parser(_frame())
        self.cached_parse()
        self.cached_parse()
        stats = services.get_parse_cache_stats()
        self.assertEqual((stats['misses'], stats['hits'], stats['clears']),
                         (1, 1, 0))
        services.clear_parse_cache()
        self.assertEqual(services.get_parse_cache_stats()['clears'], 1)

    def test_evict_to_zero_keeps_last_entry_and_counts(self):
        frame = _frame()
        self.use_budget(services._frame_bytes(frame) * 10)
        self.patch_parser(frame)
        self.cached_parse()
        services._cached_parse(2, 2, 12345, self.second_path(), 'CTA8290D')
        self.assertEqual(len(services._parse_cache), 2)
        services._parse_cache.evict_to(0)
        self.assertEqual(len(services._parse_cache), 1,
                         'evict_to 保留最后一条，与 _store 的 len>1 语义一致')
        self.assertGreaterEqual(
            services.get_parse_cache_stats()['evictions'], 1)

    def test_evict_parse_cache_to_fraction(self):
        frame = _frame()
        one = services._frame_bytes(frame)
        # 3 条 ≈ 3×one，预算必须 < 6×one 才会让「淘汰到预算一半」真的发生
        # （10×one 时 3 条连一半预算都不到，evict_to 无事可做）。
        self.use_budget(one * 4)
        self.patch_parser(frame)
        paths = [self.path, self.second_path(), self.second_path()]
        for idx, path in enumerate(paths):
            services._cached_parse(idx + 1, 1, 12345, path, 'CTA8290D')
        before = services._parse_cache.bytes_cached()
        services.evict_parse_cache_to(0.5)
        self.assertLessEqual(services._parse_cache.bytes_cached(), before / 2)

    def test_col_meta_is_built_once_per_file_not_per_request(self):
        """J4：翻页不该再付每请求的 O(列) 循环（1702 列那档实测 260ms）。"""
        frame = _frame()
        parser = self.patch_parser(frame)
        real = services.build_col_meta
        with mock.patch('apps.datafiles.services.build_col_meta',
                        wraps=real) as spy:
            first = services._cached_parse(11, 1, 12345, self.path, 'CTA8290D')
            second = services._cached_parse(22, 2, 12345, self.path, 'CTA8290D')

        self.assertEqual(spy.call_count, 1,
                         f'build_col_meta 被调 {spy.call_count} 次，应随解析只算一次')
        self.assertEqual(first[1]['col_meta'], second[1]['col_meta'])

    def test_col_meta_value_matches_the_per_request_builder(self):
        """缓存里那份必须与「每请求现场算」逐字段相等——响应形状不许动。"""
        frame = _frame()
        parser = self.patch_parser(frame)
        df, metadata, _fmt = services._cached_parse(1, 1, 12345, self.path, 'CTA8290D')
        cached_meta = metadata['col_meta']

        fresh_input = {k: v for k, v in metadata.items() if k != 'col_meta'}
        self.assertEqual(cached_meta, services.build_col_meta(df, fresh_input))
        self.assertEqual(sorted(cached_meta), sorted(df.columns))

    def test_budget_counts_col_meta_real_bytes(self):
        """J7：`64 × len(metadata)` 会把几十 KB 的 col_meta 估成 64 字节。"""
        frame = _frame(rows=200, cols=8)
        # 真实解析的 metadata 每列都带 unit/min/max 字符串；col_meta 由这些值拼出。
        # 夹具若返回空 units（值全是 ''），col_meta 只剩列名那点长度，量级到不了
        # 「几十 KB」，J7 断言也就无从体现——这里喂一份与真实文件同形的 metadata。
        md = {
            'format': 'CTA8290D',
            'units': {c: 'um' for c in frame.columns},
            'mins': {c: '-999.9999' for c in frame.columns},
            'maxs': {c: '999.9999' for c in frame.columns},
        }
        parser = self.patch_parser(frame, metadata=md)
        df, metadata, fmt = services._cached_parse(1, 1, 12345, self.path, 'CTA8290D')

        value_bytes = services._parse_value_bytes((df, metadata, fmt))
        self.assertGreaterEqual(
            value_bytes,
            services._frame_bytes(df) + services._col_meta_bytes(metadata),
            '体积估算必须包含 col_meta 的真实量级')
        self.assertGreater(
            value_bytes,
            services._frame_bytes(df) + 64 * len(metadata),
            '沿用「metadata 一律按 64 字节/键」会低估')


class PutCachedParsedFileTests(_CacheCaseBase):
    """上传写透：put 之后读侧必须直接命中，不能再解析一次。"""

    def test_put_then_get_does_not_reparse(self):
        frame = _frame()
        parser = self.patch_parser(frame)

        # 模拟上传链路的那次解析（df/metadata/fmt 由此得到）
        df, metadata, fmt = self.cached_parse()
        self.assertEqual(parser.calls, 1)

        # 换一只空缓存，确保是 put 而不是刚才的 _cached_parse 填的条目
        self.use_budget(services.PARSE_CACHE_BUDGET_BYTES)
        fake = types.SimpleNamespace(file_path=self.path, format_type='CTA8290D')
        services.put_cached_parsed_file(1, 1, fake, df, metadata, fmt)

        out_df, _out_meta, out_fmt = services.get_cached_parsed_file(1, 1, fake)

        self.assertIs(out_df, df, '写透后首次读取必须拿到同一只 DataFrame')
        self.assertEqual(out_fmt, fmt)
        self.assertEqual(parser.calls, 1, '写透后首次读取不应再解析')


class RegisterFileWriteThroughTests(TestCase):
    """_register_file 上传时的解析结果要写进缓存（需要真实 User 与 DB）。"""

    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        # 模块级缓存是进程共享的，换掉以免被其它用例的条目污染
        self.original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', self.original_cache)
        services._parse_cache = services._BytesLRUCache(
            services.PARSE_CACHE_BUDGET_BYTES)

    def test_register_file_writes_through_cache(self):
        user = get_user_model().objects.create_user(
            username='cache_user', password='x')
        parser = _CountingParser(_frame())
        # _register_file 消费的是 _helpers 上的 get_parser；services 上的同名
        # 函数只在缓存未命中的兜底解析时才会用到。两处都打桩，任何一次真实
        # 解析都会记到 parser.calls 上。
        for module in (services, _helpers):
            original = module.get_parser
            module.get_parser = lambda fmt: parser
            self.addCleanup(setattr, module, 'get_parser', original)

        abs_path = os.path.join(
            self.media_root, 'data', user.username, 'single', 'demo.csv')
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write('CTA8290D\nA,B\n1,2\n')

        datafile = _helpers._register_file(user, abs_path)
        self.assertEqual(parser.calls, 1, '上传链路应只解析一次')

        df, _metadata, fmt = services.get_cached_parsed_file(
            datafile.id, user.pk, datafile)

        self.assertIsNotNone(df, '写透后首次读取应命中缓存')
        self.assertEqual(fmt, datafile.format_type)
        self.assertEqual(parser.calls, 1, '首次读取不应再解析')


class FrameBytesTests(SimpleTestCase):
    def test_byte_estimate_grows_with_size(self):
        small = services._frame_bytes(_frame(rows=100))
        big = services._frame_bytes(_frame(rows=5000))
        self.assertGreater(big, small)

    def test_none_frame_costs_nothing(self):
        self.assertEqual(services._frame_bytes(None), 0)

    def test_object_columns_counted_deeply(self):
        """object 列必须按真实字符串大小计入，否则预算形同虚设。"""
        numeric = services._frame_bytes(
            pd.DataFrame({'P': [1.0] * 2000}))
        strings = services._frame_bytes(
            pd.DataFrame({'P': ['x' * 200] * 2000}))
        self.assertGreater(strings, numeric * 5)


class ParseSucceededTests(SimpleTestCase):
    """`_parse_succeeded` 是「什么值值得进缓存」的唯一判据，三种失败形状都得判 False。"""

    def test_only_a_real_frame_is_worth_caching(self):
        frame = _frame(rows=10)
        self.assertTrue(services._parse_succeeded((frame, {'format': 'CTA8290D'}, 'CTA8290D')))
        self.assertFalse(services._parse_succeeded((None, None, 'CTA8290D')))
        self.assertFalse(services._parse_succeeded((None, {'format': 'CTA8290D'}, 'CTA8290D')))
        self.assertFalse(services._parse_succeeded((None, None, None)))


class ModuleShapeTests(SimpleTestCase):
    """缓存函数签名/公开入口不能被这次重构改坏（大量调用点依赖它）。"""

    def test_public_wrapper_signature_keeps_datafile_shortcut(self):
        import inspect
        params = list(inspect.signature(services.get_cached_parsed_file).parameters)
        self.assertEqual(params, ['file_id', 'owner_id', 'datafile'])

    def test_fake_datafile_objects_still_supported(self):
        """调用方常传 SimpleNamespace 假对象（测试/脚本），需继续可用。"""
        self.assertTrue(callable(services.get_cached_parsed_file))
        fake = types.SimpleNamespace(file_path='x.csv', format_type='CTA8290D')
        self.assertIsNotNone(fake)


class CacheBudgetWiringTests(SimpleTestCase):
    def setUp(self):
        from apps.common import memory
        memory.reset_budget_for_tests()

    def tearDown(self):
        from apps.common import memory
        memory.reset_budget_for_tests()

    def test_module_budget_matches_memory_plan(self):
        from apps.common import memory
        self.assertEqual(services.PARSE_CACHE_BUDGET_BYTES,
                         memory.get_budget().cache_budget_bytes)

    def test_resolver_reads_cache_budget_from_consuming_binding(self):
        """预算必须来自 get_budget()，而不是本模块里另写死的 1536MB。"""
        from apps.common.memory import MemoryBudget
        plan = MemoryBudget(
            total_ram_bytes=16 * 1024 ** 3,
            budget_bytes=8 * 1024 ** 3,
            jobs_budget_bytes=2 * 1024 ** 3,
            web_budget_bytes=6 * 1024 ** 3,
            cache_budget_bytes=123456,
        )
        with mock.patch('apps.datafiles.services.get_budget',
                        return_value=plan) as get_budget:
            self.assertEqual(services._resolve_cache_budget_bytes(), 123456)
        get_budget.assert_called_once_with()

    def test_stats_expose_counters(self):
        stats = services.get_parse_cache_stats()
        self.assertEqual(set(stats), {
            'entries', 'bytes', 'budget_bytes', 'in_flight',
            'hits', 'misses', 'evictions', 'clears',
        })


class SharedFrameSafetyTests(SimpleTestCase):
    """缓存帧跨请求共享 ⇒ 消费者要改它必须先 copy。这条扫描把口头约定钉住。

    三个刻意的形状：
    ① **只在含 `get_cached_parsed_file` 的函数块里找原地写**，且写之前出现过
       `df = df.<method>(...)` 这种重新绑定（copy/astype/head…）就放行。朴素正则会在
       `apps/analysis/views/file_correlation_views.py:169-170` 那处「先 copy 再加辅助列」的
       **合规写法**上假红 —— 2026-10-26 预检实测就是这样，而假红的护栏最后没人看。
    ② 按**载体并集**扫，且「某个载体读不到」直接判红：2026-10-23 那次常量搬家后单文件扫描
       零命中、空集反而"相等"，就是假绿（见 docs/tasks/todo.md:5325-5329）。
    ③ 模式串用拼接构造，否则这条测试文件自己含住模式，会被自己抓到。

    已知局限（别当成完整防线）：放行规则是"同一函数块里先前有过重新绑定"，所以一个函数
    先 copy、之后再往**原对象**上写会漏；把缓存帧当参数传给别处去改也扫不到。
    这两类由 J1/J3 的行为断言兜（共享身份 + 并发同源），静态扫描只是第一道。
    """

    CARRIERS = [
        'apps/analysis/views/_helpers.py',
        'apps/analysis/views/analysis_views.py',
        'apps/analysis/views/file_correlation_views.py',
        'apps/batch_report/services.py',
        'apps/batch_report/views.py',
        'apps/buyoff/views.py',
        'apps/common/file_loading.py',
        'apps/dashboard/views.py',
        'apps/datafiles/views/browse_views.py',
        'apps/gage/views.py',
    ]
    CALL = 'get_cached_parsed_file'
    DEFINITION_SITE = 'apps/datafiles/services.py'   # 定义处，不是调用处
    WRITE = re.compile('(' + r'\bdf\[[^\]]+\]\s*=[^=]'
                       + '|' + r'\bdf\.(?:loc|iloc)\[[^\]]+\]\s*=[^=]'
                       + '|' + r'\bdf\.drop\([^)]*inplace=True'
                       + '|' + r'del df\[)')
    REBIND = re.compile(r'\bdf\s*=\s*df\.\w+\(')

    @staticmethod
    def _func_blocks(text):
        block, blocks = [], []
        for line in text.split('\n'):
            if re.match(r'^(async )?def ', line) and block:
                blocks.append(block)
                block = []
            block.append(line)
        if block:
            blocks.append(block)
        return blocks

    def test_no_caller_mutates_the_shared_frame(self):
        root = Path(services.__file__).resolve().parents[2]
        scanned = 0
        for rel in self.CARRIERS:
            path = root / rel
            self.assertTrue(path.is_file(), f'载体清单过期：{rel} 读不到（假绿源头）')
            for block in self._func_blocks(path.read_text(encoding='utf-8')):
                if self.CALL not in '\n'.join(block):
                    continue
                rebound = False
                for line in block:
                    if self.REBIND.search(line):
                        rebound = True
                        continue
                    hit = self.WRITE.search(line)
                    if hit and not rebound:
                        self.fail(f'{rel} 在共享的缓存帧上原地写：{hit.group(0)}')
            scanned += 1
        self.assertEqual(scanned, len(self.CARRIERS),
                         '每个载体都必须真的被扫到，扫描数与清单数必须相等')

    def test_carriers_actually_contain_call_sites(self):
        """每个载体都必须真的有调用点，否则上面那条扫描是空跑。"""
        root = Path(services.__file__).resolve().parents[2]
        for rel in self.CARRIERS:
            text = (root / rel).read_text(encoding='utf-8')
            hits = [ln for ln in text.split('\n')
                    if self.CALL in ln and not ln.strip().startswith('#')]
            self.assertTrue(hits, f'{rel} 里一个 {self.CALL} 调用点都没有 —— 清单该更新了')

    def test_no_call_site_lives_outside_the_carrier_list(self):
        """新调用点必须显式进清单，不能悄悄长在扫描之外。"""
        root = Path(services.__file__).resolve().parents[2]
        listed = set(self.CARRIERS) | {self.DEFINITION_SITE}
        # 与 CARRIERS/DEFINITION_SITE 一样用「相对 root 的 posix 路径」比较：
        # root.glob 返回的是绝对路径（services.__file__ 已 resolve），直接
        # p.as_posix() 与相对清单永不相等 ⇒ 十个载体全被误判为「stray」。
        # 断言本体（stray==[]）不变：真长出清单外的调用点仍会以其相对路径出现并判红。
        stray = sorted(
            p.relative_to(root).as_posix() for p in root.glob('apps/**/*.py')
            if '__pycache__' not in p.as_posix()
            and 'test' not in p.name.lower()
            and self.CALL in p.read_text(encoding='utf-8', errors='ignore')
            and p.relative_to(root).as_posix() not in listed)
        self.assertEqual(stray, [], f'这些文件有调用点却不在 CARRIERS 里：{stray}')
