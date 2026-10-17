"""解析缓存的字节预算与并发单飞测试（2026-09-02 审计批次 2）。

原实现是 ``@lru_cache(maxsize=64)`` 按**条数**限流，但每个值是一整只
DataFrame（实测 10 万行 × 826 列 ≈ 667MB）——几张大表同时驻留就是数 GB
常驻内存；且 ``lru_cache`` 不合并并发 miss，首屏 3 个请求会把同一只文件
各解析一遍（单次解析实测约 4s）。
"""
import os
import shutil
import tempfile
import threading
import time
import types

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


class CacheBudgetPolicyTests(SimpleTestCase):
    """预算取值：默认仍是 1536MB（**这次不改常驻内存策略**），env 覆盖优先且非法值不炸。

    自适应方案（clamp(RAM×0.25, 1536, 4096)）实测后撤回，理由写在 services.py 顶部注释：
    它的前提「一个批次目录 9 只同量级大文件互相洗掉」被测量否证——那只目录只有 1 只 275MB，
    而 460MB 的帧本来就住得下 1536MB 预算。这里保留的判据因此只钉两件事：
    默认值没被动过、以及 env 写错时后端还能起来。
    """

    MB = 1024 * 1024
    _NO_ENV = object()

    def _budget(self, env=_NO_ENV):
        """清掉 env 后跑公式，保证「有没有 LQDP_PARSE_CACHE_MB」由参数决定而不是继承本机。"""
        import unittest.mock as mock
        with mock.patch.dict('os.environ', {}, clear=True):
            if env is not self._NO_ENV:
                os.environ['LQDP_PARSE_CACHE_MB'] = str(env)
            return services._resolve_cache_budget_bytes() // self.MB

    def test_default_is_the_pre_change_fixed_value(self):
        self.assertEqual(self._budget(), 1536)
        self.assertEqual(services.PARSE_CACHE_DEFAULT_MB, 1536)

    def test_env_override_wins(self):
        self.assertEqual(self._budget(700), 700)
        self.assertEqual(self._budget(0), 0, '0 = 显式关掉缓存，这条逃生口要留着')

    def test_illegal_env_falls_back_instead_of_raising(self):
        """模块级常量在 import 时求值：这里抛异常等于后端起不来、用户只看到「双击没反应」。"""
        self.assertEqual(self._budget('big'), 1536)
        self.assertEqual(self._budget(''), 1536, '空值走「未设置」那条，同样取默认')

    def test_negative_env_clamped_to_zero(self):
        self.assertEqual(self._budget(-5), 0)

    def test_module_level_budget_matches_resolver(self):
        """常量必须由这条函数算出（缓存用的是常量，两处不一致就等于覆盖没生效）。"""
        import unittest.mock as mock
        with mock.patch.dict('os.environ', {}, clear=True):
            expected = services._resolve_cache_budget_bytes()
        self.assertEqual(services.PARSE_CACHE_BUDGET_BYTES, expected)
