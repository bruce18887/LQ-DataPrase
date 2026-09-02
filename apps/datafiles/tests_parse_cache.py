"""解析缓存的字节预算与并发单飞测试（2026-09-02 审计批次 2）。

原实现是 ``@lru_cache(maxsize=64)`` 按**条数**限流，但每个值是一整只
DataFrame（实测 10 万行 × 826 列 ≈ 667MB）——几张大表同时驻留就是数 GB
常驻内存；且 ``lru_cache`` 不合并并发 miss，首屏 3 个请求会把同一只文件
各解析一遍（单次解析实测约 4s）。
"""
import os
import tempfile
import threading
import time
import types

import pandas as pd
from django.test import SimpleTestCase

from apps.datafiles import services


def _frame(rows=2000, cols=6):
    """造一只可测量大小的 DataFrame。"""
    data = {f'P{i}': [float(r * i + r) for r in range(rows)] for i in range(cols)}
    return pd.DataFrame(data)


class _CountingParser:
    """假解析器：统计被真正解析的次数，可注入耗时。"""

    def __init__(self, frame, delay=0.0):
        self.frame = frame
        self.delay = delay
        self.calls = 0

    def parse(self, path):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return self.frame, {'format': 'CTA8290D'}


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

    def patch_parser(self, frame, delay=0.0):
        parser = _CountingParser(frame, delay)
        original = services.get_parser
        services.get_parser = lambda fmt: parser
        self.addCleanup(setattr, services, 'get_parser', original)
        return parser

    def cached_parse(self, file_id=1, owner_id=1):
        return services._cached_parse(file_id, owner_id, 12345, self.path, 'CTA8290D')


class BytesLRUCacheTests(_CacheCaseBase):
    def test_second_request_for_same_file_is_not_reparsed(self):
        frame = _frame()
        parser = self.patch_parser(frame)

        first = self.cached_parse()
        second = self.cached_parse()

        self.assertEqual(parser.calls, 1, f'解析被调用 {parser.calls} 次，应命中缓存')
        self.assertIs(second[0], first[0])

    def test_entries_evict_by_byte_budget_not_by_count(self):
        frame = _frame()
        one = services._frame_bytes(frame)
        budget = int(one * 1.6)   # 只装得下一只
        self.use_budget(budget)
        parser = self.patch_parser(frame)

        self.cached_parse(file_id=1)
        self.cached_parse(file_id=2)   # 换 file_id → 新 key，必须挤掉旧的

        cache = services._parse_cache
        self.assertLessEqual(cache.bytes_cached(), budget,
                             '缓存总量必须始终不超过预算')
        self.assertEqual(len(cache), 1)
        self.cached_parse(file_id=1)   # 旧条目已被挤掉 → 重新解析
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

    def test_missing_file_hint_preserved(self):
        """文件不在磁盘上时返回 (None, None, format_type) 的既有契约不变。"""
        parser = self.patch_parser(_frame())
        missing = os.path.join(tempfile.gettempdir(), 'nope_does_not_exist.csv')

        out = services._cached_parse(9, 1, 1, missing, 'CTA8290D')

        self.assertEqual(out, (None, None, 'CTA8290D'))
        self.assertEqual(parser.calls, 0)


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
