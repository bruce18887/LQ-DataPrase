"""T1: 列级元信息随解析只算一次（A4，2026-10-28 性能整改波次 A）。

被钉的六条契约（⑤ 与那条「决策见证」在本目录的 `test_column_profile_caliber.py`，两文件
合计仍是 21 例——拆文件减压，不改判据）：

① ``column_profile.build_column_profile`` 的四件套与「改动前 ``browse_views.py:159-186``
   那段首屏现算」**逐字相等**（基线原样搬进本文件的 ``_baseline_profile``，不改一字）；
② 承重：同一内容坐标 ``(绝对路径, mtime_ns, format_type)`` 连续三次 ``page==1`` 首屏请求
   ⇒ 计数恰为 1；换 mtime ⇒ 恰为 2；两个 owner 读同一物理文件 ⇒ 恰为 1
   （键里不许把 user/file_id 放回去）；
③ 回落形状：缓存条目缺 ``column_profile``（算不出 / 写透未带）时视图必须现算补上，
   四件套照旧正确且**非空**，绝不下发空元信息；
④ 写透侧 ``put_cached_parsed_file`` 的条目 ``col_meta`` 与 ``column_profile`` **要么都有、
   要么都没有**（半吊子条目会让首屏每次都走回落，等于没做这一刀）；
⑤ 体积核算：``_parse_value_bytes`` 必须按这只 dict 的真实量级计入（1702 列那档是几十 KB，
   沿用「每键 64 字节」就是自欺，与 ``col_meta`` 的 J7 同因）——钉在 caliber 那份；
⑥ 搬进解析期的代价：算不出四件套的帧（重复列名）**不许**把整只文件带成 parse_failed，
   也不许把写透（上传）链路带崩——不挂键、让视图侧回落原样复现今天的形状。
   这一条不是设计出来的：A3 的 ``test_single_duplicate_columns_keep_first_without_mutating_cached_frame``
   在无外壳的版本上真的红了，才把它变成契约。
"""

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.analysis.services.statistics.helpers import (
    get_serial_column,
    get_site_column,
)
from apps.datafiles import column_profile, services
from apps.datafiles.models import DataFile
from apps.datafiles.parsers import SYSTEM_COLUMNS
from apps.datafiles.views import browse_views

FOUR_FORMATS = ('CTA8290D', 'CTA8280F', 'ETS88', 'STS8200')


# ───────────────────────────── 基线（逐字搬运，不许优化） ─────────────────────────────

def _baseline_profile(df, format_type):
    """改动前 ``browse_views.py:154-186`` 那段首屏现算的**逐字搬运**，作等价性对照。

    这份一旦「顺手改进」（改成向量化、换成纯 dtype 判定、把 ``''``/``'nan'`` 排除并掉），
    等价性断言就失去对照物、同时把下发给前端的集合悄悄改掉——所以它必须保持旧形状。
    """
    site_options: list = []
    numeric_columns: list = []
    system_columns: list = []
    serial_column = None
    site_col_full = get_site_column(df)
    if site_col_full:
        site_options = [
            str(v) for v in df[site_col_full].dropna().astype(str).unique()
            if str(v) not in ('', 'nan')
        ]
    for col in df.columns:
        if df[col].dtype == object:
            if pd.to_numeric(df[col], errors='coerce').notna().any():
                numeric_columns.append(col)
        elif (pd.api.types.is_numeric_dtype(df[col])
              and not pd.api.types.is_bool_dtype(df[col])
              and df[col].notna().any()):
            numeric_columns.append(col)
    sys_set = set(SYSTEM_COLUMNS.get(format_type, []))
    system_columns = [c for c in df.columns if c in sys_set]
    serial_column = get_serial_column(df)
    return {
        'site_options': site_options,
        'numeric_columns': numeric_columns,
        'system_columns': system_columns,
        'serial_column': serial_column,
    }


# ───────────────────────────── 夹具 ─────────────────────────────

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


def _no_meta_frame():
    """既无 site 也无序列候选、且没有任何可测数值列的帧 ⇒ 四件套合法地全空。"""
    return pd.DataFrame({
        'Dut_Pass': pd.Series([True, False]),
        'QR_Code': pd.Series([float('nan'), float('nan')]),
        'TEXT': pd.Series(['a', 'b'], dtype='object'),
    })


def _md_of(frame):
    """与真实解析产出同形的 metadata（每列带 unit/min/max），供 col_meta 与体积用例使用。"""
    return {
        'format': 'CTA8290D',
        'units': {c: 'um' for c in frame.columns},
        'mins': {c: '-999.9999' for c in frame.columns},
        'maxs': {c: '999.9999' for c in frame.columns},
    }


class _CountingParser:
    """假解析器：返回固定帧与 metadata 的副本（形状照 apps/datafiles/tests_parse_cache.py）。"""

    def __init__(self, frame, metadata):
        self.frame = frame
        self.metadata = metadata
        self.calls = 0

    def parse(self, path):
        self.calls += 1
        return self.frame, dict(self.metadata)


def _spy_column_profile(case):
    """把 ``build_column_profile`` 的**两个消费绑定**都换成同一个计数器（R6③）。

    patch 的是 `services` / `browse_views` 各自那份绑定（`from … import` 造独立绑定，只
    patch 口径本体等于没 patch），计数跨两侧 ⇒ 「视图又现算一次」也会红。`case` 只用来
    挂 `addCleanup`，故缓存侧基座与端到端基座共用这一份实现。
    """
    state = {'calls': 0}
    real = column_profile.build_column_profile

    def wrapper(df, format_type):
        state['calls'] += 1
        return real(df, format_type)

    for module in (services, browse_views):
        case.addCleanup(setattr, module, 'build_column_profile', real)
        module.build_column_profile = wrapper
    return state


class _CacheCaseBase(SimpleTestCase):
    """缓存侧用例基座：换掉进程级缓存 + 装假解析器 + 把口径函数换成计数器。"""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', self.original_cache)
        services._parse_cache = services._BytesLRUCache(
            services.PARSE_CACHE_BUDGET_BYTES)
        self.frame = _fragile_frame()
        self.metadata = _md_of(self.frame)
        self.parser = _CountingParser(self.frame, self.metadata)
        original = services.get_parser
        services.get_parser = lambda fmt: self.parser
        self.addCleanup(setattr, services, 'get_parser', original)

    def spy_profile(self):
        return _spy_column_profile(self)

    def cached_parse(self, file_id=1, owner_id=1, mtime=12345, path=None, fmt='CTA8290D'):
        return services._cached_parse(file_id, owner_id, mtime,
                                      path or self.path, fmt)


# ───────────────────────────── ① 等价性 ─────────────────────────────

class ColumnProfileEquivalenceTests(_CacheCaseBase):

    def test_profile_equals_the_inline_first_screen_computation(self):
        for fmt in FOUR_FORMATS + ('NOT_A_FORMAT',):
            with self.subTest(format_type=fmt):
                self.assertEqual(
                    column_profile.build_column_profile(self.frame, fmt),
                    _baseline_profile(self.frame, fmt))

    def test_profile_shape_is_exactly_the_four_keys(self):
        """四键：多一键就是往响应里塞新东西（契约变更），少一键则回落判定永远为真。

        顺手钉「归属点」这一刀：口径本体只有一份（`apps/datafiles.column_profile`，
        视图与 services 都从那里取），且该模块必须 **Django-free**——CPU worker 的 spawn
        子进程没有 `django.setup()`，多一个 `django.*`/models 依赖就让它 import 期直接炸
        （同 `apps/jobs/runner.py` 头注、`.claude/CLAUDE.md`「CPU worker 侧禁 Django」）。
        """
        profile = column_profile.build_column_profile(self.frame, 'CTA8290D')
        self.assertEqual(set(profile), set(column_profile.COLUMN_PROFILE_KEYS))
        self.assertEqual(len(column_profile.COLUMN_PROFILE_KEYS), 4)
        self.assertEqual(sorted(profile), sorted(
            ['site_options', 'numeric_columns', 'system_columns', 'serial_column']))
        tree = ast.parse(Path(column_profile.__file__).read_text(encoding='utf-8'))
        imported = {a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module or '' for n in tree.body if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(
            imported, {'typing', 'pandas',
                        'apps.analysis.services.statistics.helpers',
                        'apps.datafiles.parsers.base'},
            f'口径模块的 import 越界了（Django-free 前提）：{sorted(imported)}')
        # AST 只看得到顶层：函数内延迟 import、以及白名单里那两个包自己的 `__init__`
        # 日后若爬进 Django，上面那条一律不红。所以再按 worker 的真实形态跑一次子进程。
        probe = subprocess.run(
            [sys.executable, '-X', 'utf8', '-c',
             'import sys; import apps.datafiles.column_profile;'
             ' print([m for m in sys.modules if m.startswith("django")])'],
            cwd=str(Path(column_profile.__file__).resolve().parents[2]),
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), '[]',
                         '口径模块在没 django.setup() 的进程里必须 import 得干净')

    def test_caliber_pins_the_fragile_columns(self):
        """口径本身也要钉：只断「与基线相等」的话，两份一起被改错就会绿。"""
        profile = column_profile.build_column_profile(self.frame, 'CTA8290D')
        numeric = profile['numeric_columns']
        self.assertIn('SW_Bin', numeric, '数字字符串 object 列必须走值级判定进来')
        self.assertIn('CONST_V', numeric, '常量列仍是数值列（旧前端 Number.isFinite 判定）')
        self.assertIn('PAR0001', numeric, '含 NaN 的数值列不因个别缺失被剔除')
        self.assertNotIn('Dut_Pass', numeric, 'bool 列（TRUE/FALSE）非数值')
        self.assertNotIn('QR_Code', numeric, '全 NaN 列不算数值')
        self.assertNotIn('BLANK_OBJ', numeric, '全 None 的 object 列 coerce 后无值')
        self.assertNotIn('PART_ID', numeric, '非数字字符串 object 列不进数值集')
        self.assertEqual(profile['site_options'], ['1', '2'],
                         "dropna 后还要排除 ''与 'nan'")
        self.assertEqual(profile['serial_column'], 'Serial_No')
        self.assertEqual(
            profile['system_columns'],
            ['Site_No', 'Serial_No', 'Dut_No', 'Dut_Pass', 'SW_Bin', 'QR_Code'],
            '系统列 = 文件列序 ∩ 格式权威列表')

    def test_all_empty_profile_is_a_legitimate_value_not_a_missing_key(self):
        """无 site/序列/数值列的帧：四件套合法地全空，与「键缺失」是两件事。"""
        frame = _no_meta_frame()
        profile = column_profile.build_column_profile(frame, 'CTA8290D')
        self.assertEqual(profile, _baseline_profile(frame, 'CTA8290D'))
        self.assertEqual(profile['site_options'], [])
        self.assertEqual(profile['numeric_columns'], [])
        self.assertIsNone(profile['serial_column'])


# ───────────────────────────── ④ 写透与解析同址 ─────────────────────────────

class ColumnProfileWriteThroughTests(_CacheCaseBase):

    def test_parse_side_entry_carries_profile_next_to_col_meta(self):
        df, metadata, _fmt = self.cached_parse()
        self.assertIn('col_meta', metadata)
        self.assertIn('column_profile', metadata, '与 col_meta 同址：只挂一条就是半吊子')
        self.assertEqual(metadata['column_profile'],
                         _baseline_profile(df, 'CTA8290D'))

    def test_write_through_adds_both_keys_when_both_are_missing(self):
        fake = SimpleNamespace(file_path=self.path, format_type='CTA8290D')
        df, metadata = self.parser.parse(self.path)
        state = self.spy_profile()
        real_build = services.build_col_meta
        with _SpyBuild(real_build) as build_spy:
            services.put_cached_parsed_file(1, 1, fake, df, metadata, 'CTA8290D')
            _df, cached_meta, _fmt = services.get_cached_parsed_file(1, 1, fake)
            services.get_cached_parsed_file(2, 2, fake)

        self.assertIn('col_meta', cached_meta)
        self.assertIn('column_profile', cached_meta)
        self.assertEqual(cached_meta['column_profile'], _baseline_profile(df, 'CTA8290D'))
        self.assertEqual(state['calls'], 1,
                         f'写透 + 两次读取共现算 {state["calls"]} 次，应只随写透算一次')
        self.assertEqual(build_spy.calls, 1, 'col_meta 的既有「只算一次」不许被这次改动带回回落')
        self.assertNotIn('col_meta', metadata, '写透不得原地改调用方那份 metadata')
        self.assertNotIn('column_profile', metadata, '同上：上传链路还在读这一份')

    def test_write_through_on_entry_already_holding_col_meta_still_adds_profile(self):
        """「都有或都缺」的另一半：预置 col_meta 的入参也补齐 profile，且不得重算 col_meta。"""
        fake = SimpleNamespace(file_path=self.path, format_type='CTA8290D')
        df, metadata = self.parser.parse(self.path)
        metadata['col_meta'] = services.build_col_meta(df, metadata)
        state = self.spy_profile()
        real_build = services.build_col_meta
        with _SpyBuild(real_build) as build_spy:
            services.put_cached_parsed_file(1, 1, fake, df, metadata, 'CTA8290D')
            _df, cached_meta, _fmt = services.get_cached_parsed_file(1, 1, fake)

        self.assertIn('col_meta', cached_meta)
        self.assertIn('column_profile', cached_meta)
        self.assertEqual(build_spy.calls, 0, 'col_meta 已在 ⇒ 不许再算一遍')
        self.assertEqual(state['calls'], 1)
        self.assertEqual(cached_meta['column_profile'], _baseline_profile(df, 'CTA8290D'))

    def test_write_through_profile_uses_the_datafile_format_type(self):
        """口径参数取 ``datafile.format_type``——它与缓存键、与视图回落用的是同一个值。

        假 parser 的 fmt 传 CTA8290D、datafile 标 ETS88：若误用 ``fmt``，system_columns 会
        多出 CTA 那套列名，与「视图用 datafile.format_type 现算」不一致 ⇒ 首屏集合随
        「命中缓存还是回落」而变，那是最难查的一类红。
        """
        fake = SimpleNamespace(file_path=self.path, format_type='ETS88')
        df, metadata = self.parser.parse(self.path)
        services.put_cached_parsed_file(1, 1, fake, df, metadata, 'CTA8290D')
        _df, cached_meta, _fmt = services.get_cached_parsed_file(1, 1, fake)

        self.assertEqual(cached_meta['column_profile'], _baseline_profile(df, 'ETS88'))
        self.assertEqual(cached_meta['column_profile']['system_columns'], [],
                         '前提：ETS88 的权威列名与本夹具不相交')
        self.assertTrue(_baseline_profile(df, 'CTA8290D')['system_columns'],
                        '对照组：按 CTA8290D 算就非空 ⇒ 上一条确实在判格式来源')


class DuplicateColumnFrameGuardTests(_CacheCaseBase):
    """重复列名：解析期不许把整只文件判成失败（这条回归由 A3 的用例当场抓住）。

    旧写法这段现算在**视图里**跑 ⇒ 抛错只影响 page==1，page>1 照旧可用。搬进解析期而不设
    外壳的话，`_parse_file_uncached` 的兜底会把 df 变成 None（整只文件 parse_failed），
    写透侧更会把上传链路带崩——那是行为变更。钉住：条目照常可读、`col_meta` 照旧、
    只是**不挂** `column_profile`，于是视图侧回落照旧抛错，与今天逐字一致。
    """

    def _dup_frame(self):
        return pd.DataFrame([[1., 90., 3.], [2., 80., 4.]], columns=['P1', 'P1', 'P2'])

    def test_parse_keeps_the_frame_and_omits_the_profile_key(self):
        frame = self._dup_frame()
        self.parser.frame = frame
        self.parser.metadata = _md_of(frame)
        with self.assertLogs('apps.datafiles.services', level='WARNING') as logs:
            df, metadata, _fmt = self.cached_parse()
        self.assertIsNotNone(df, '重复列名不得让整只文件变成 parse_failed')
        self.assertIn('col_meta', metadata)
        self.assertNotIn('column_profile', metadata,
                         '算不出就不挂键：让消费侧回落原样复现今天的形状')
        self.assertTrue(any('column_profile' in line for line in logs.output),
                        '吞异常必须留痕，不许静默')
        # 留痕还得**可归因**（这条 WARNING 吞掉的是故意吞掉的异常）：挂载路径 / 文件 /
        # 格式 / 抛出点四样缺一，落到生产日志里就是一条查不到头的噪声。
        joined = '\n'.join(logs.output)
        self.assertIn('mount=parse(_parse_file_uncached)', joined, '得写明是哪条挂载路径')
        self.assertIn(self.path, joined, '得写明是哪只文件')
        self.assertIn('format_type=CTA8290D', joined, '得写明是哪种格式')
        self.assertIn('Traceback (most recent call last)', joined, 'exc_info=True ⇒ 留完整栈')
        with self.assertRaises(Exception):
            column_profile.build_column_profile(df, 'CTA8290D')

    def test_write_through_does_not_raise_on_duplicate_columns(self):
        frame = self._dup_frame()
        self.parser.frame = frame
        self.parser.metadata = _md_of(frame)
        fake = SimpleNamespace(file_path=self.path, format_type='CTA8290D')
        df, metadata = self.parser.parse(self.path)
        with self.assertLogs('apps.datafiles.services', level='WARNING') as logs:
            services.put_cached_parsed_file(1, 1, fake, df, metadata, 'CTA8290D')
        out_df, cached, _fmt = services.get_cached_parsed_file(1, 1, fake)
        self.assertIsNotNone(out_df, '写透侧抛错会直接把上传链路带崩')
        self.assertIn('col_meta', cached)
        self.assertNotIn('column_profile', cached)
        joined = '\n'.join(logs.output)
        self.assertIn('mount=write-through(put_cached_parsed_file)', joined,
                      '写透侧的失败要与解析侧分得开（上传链路是另一条命）')
        self.assertIn(self.path, joined, '同样要带 file_path 才能归因')


class _SpyBuild:
    """给 ``build_col_meta`` 计数的上下文（不 patch 模块属性，只在 with 块内替换）。"""

    def __init__(self, real):
        self.real = real
        self.calls = 0

    def __enter__(self):
        services.build_col_meta = self._wrap
        return self

    def _wrap(self, df, metadata):
        self.calls += 1
        return self.real(df, metadata)

    def __exit__(self, *exc):
        services.build_col_meta = self.real
        return False


# ───────────────────────────── ②③ 端到端：只算一次 / 回落 ─────────────────────────────

CTA8290D_CSV = (
    'CTA8290D\n'
    '[Data]\n'
    'Serial_No,Part_No,Dut_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,'
    'Start_T,Test_Time,Alarm,Data_Cnt,PAR0001,PAR0002\n'
    'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,uf\n'
    'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,0\n'
    'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,2\n'
    '1001,9,1,1,TRUE,1,0,0,None,1.0,1.0,None,1,1.0,1.5\n'
    '1002,9,2,1,TRUE,5,0,1,None,1.0,1.0,None,2,1.2,1.6\n'
    '1003,8,3,2,FALSE,7,1,0,None,1.0,1.0,None,3,,1.7\n'
    '1004,8,4,3,TRUE,1,1,1,None,1.0,1.0,None,4,0.5,1.8\n'
)


class ColumnProfileFirstScreenTests(TestCase):
    """真走 ``/api/v1/browse/``：判据是「整条链上 ``build_column_profile`` 被调了几次」与响应体形状。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='a4_owner')
        cls.owner2 = get_user_model().objects.create_user(username='a4_owner2')

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='a4-profile-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, 'a4_cta8290d.csv')
        self._write(CTA8290D_CSV)
        self.datafile = self._make_row(self.user, 'a4_one')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        services.clear_parse_cache()
        self.addCleanup(services.clear_parse_cache)

    def _write(self, table):
        with open(self.path, 'w', encoding='utf-8') as handle:
            handle.write(table)

    def _make_row(self, owner, filename):
        return DataFile.objects.create(
            owner=owner, filename=filename, file_path=self.path,
            file_size=os.path.getsize(self.path),
            format_type='CTA8290D', status='ready')

    def _browse(self, page=1, page_size=100, datafile=None, user=None):
        if user is not None and user != self.user:
            self.client.force_authenticate(user=user)
        return self.client.get('/api/v1/browse/', {
            'datafile_id': (datafile or self.datafile).id,
            'page': page, 'page_size': page_size})

    def spy_profile(self):
        return _spy_column_profile(self)

    def test_three_page1_requests_compute_the_profile_once(self):
        """承重：首屏三次（同一内容坐标）只算一次——这一刀的全部收益就在这条。"""
        state = self.spy_profile()
        bodies = [self._browse(page=1).json() for _ in range(3)]
        self.assertEqual(state['calls'], 1,
                         f'三次 page==1 首屏把列级元信息算了 {state["calls"]} 次，应随解析只算 1 次')
        first = bodies[0]
        self.assertEqual([b['numeric_columns'] for b in bodies], [first['numeric_columns']] * 3)
        self.assertEqual(sorted(first['site_options']), ['1', '2', '3'])
        self.assertEqual(first['serial_column'], 'Serial_No')
        self.assertTrue(first['numeric_columns'], '非空 ⇒ 不是回落出来的空壳')

    def test_profile_is_stored_in_the_cached_entry_not_recomputed_per_request(self):
        df, metadata, _fmt = services.get_cached_parsed_file(
            self.datafile.id, self.user.pk, self.datafile)
        self.assertIn('column_profile', metadata)
        self.assertEqual(metadata['column_profile'],
                         _baseline_profile(df, self.datafile.format_type))
        body = self._browse(page=1).json()
        for key in ('site_options', 'numeric_columns', 'system_columns', 'serial_column'):
            self.assertEqual(body[key], metadata['column_profile'][key],
                             f'{key} 必须逐字来自缓存条目里那份')

    def test_mtime_change_recomputes_exactly_once_more(self):
        state = self.spy_profile()
        self._browse(page=1)
        self._browse(page=1)
        self.assertEqual(state['calls'], 1)
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        self.assertNotEqual(stat.st_mtime_ns, os.stat(self.path).st_mtime_ns,
                            '前提：mtime 真的变了（键是内容坐标，没变就等于没测）')
        body = self._browse(page=1).json()
        self.assertEqual(state['calls'], 2, '换 mtime ⇒ 新内容坐标 ⇒ 恰好多算一次')
        self.assertEqual(sorted(body['site_options']), ['1', '2', '3'])

    def test_two_owners_of_one_physical_file_compute_the_profile_once(self):
        """键是内容坐标：把 user/file_id 放回键里，这条立刻红（20 人各算一遍）。"""
        row2 = self._make_row(self.owner2, 'a4_two')
        state = self.spy_profile()
        first = self._browse(page=1).json()
        second = self._browse(page=1, datafile=row2, user=self.owner2).json()
        self.assertEqual(state['calls'], 1,
                         f'两个 owner 读同一物理文件算了 {state["calls"]} 次，应恰为 1')
        self.assertEqual(first['numeric_columns'], second['numeric_columns'])
        self.assertEqual(first['system_columns'], second['system_columns'])

    def test_legacy_entry_without_profile_falls_back_and_stays_non_empty(self):
        """老缓存条目（没挂过该键）⇒ 视图现算补上：一次解析 + 一次回落，四件套照旧正确。"""
        state = self.spy_profile()
        df, metadata, _fmt = services.get_cached_parsed_file(
            self.datafile.id, self.user.pk, self.datafile)
        self.assertIn('column_profile', metadata, '前提：解析侧确实挂了键')
        metadata.pop('column_profile')

        body = self._browse(page=1).json()
        self.assertEqual(state['calls'], 2,
                         '缺键必须回落现算一次（解析一次 + 视图一次），不许下发空元信息')
        expected = _baseline_profile(df, 'CTA8290D')
        for key, value in expected.items():
            self.assertEqual(body[key], value, f'{key} 回落值必须等于现算基线')
        self.assertTrue(body['site_options'])
        self.assertTrue(body['numeric_columns'])
        self.assertTrue(body['system_columns'])
        self.assertEqual(body['serial_column'], 'Serial_No')

    def test_empty_but_complete_profile_is_adopted_not_recomputed(self):
        """视图层承重（契约③的反面）：四键齐全但值合法为空 ⇒ 直接采用、不回落、下发空值。"""
        state = self.spy_profile()
        _df, metadata, _fmt = services.get_cached_parsed_file(
            self.datafile.id, self.user.pk, self.datafile)
        metadata['column_profile'] = {'site_options': [], 'numeric_columns': [],
                                      'system_columns': [], 'serial_column': None}
        self.assertEqual(state['calls'], 1, '前提：这一算只来自解析，不含视图')
        bodies = [self._browse(page=1).json() for _ in range(3)]
        self.assertEqual(state['calls'], 1, '空值≠缺键：判据若改成按值真值判断，每次首屏白算一遍')
        for key in ('site_options', 'numeric_columns', 'system_columns'):
            self.assertEqual([b[key] for b in bodies], [[]] * 3, f'{key} 原样下发空集')
        self.assertEqual([b['serial_column'] for b in bodies], [None] * 3, '下发 null 非缺键')
        self.assertEqual(set(bodies[0]) - set(self._browse(page=2, page_size=2).json()),
                         set(column_profile.COLUMN_PROFILE_KEYS), '首屏键集合与既有一致')

    def test_page_gt1_shape_and_cost_unchanged(self):
        """page!=1 不带这四键（现状），也不许因为这次改动多算一次。"""
        state = self.spy_profile()
        body = self._browse(page=2, page_size=2).json()
        for key in column_profile.COLUMN_PROFILE_KEYS:
            self.assertNotIn(key, body, f'page!=1 时不得下发 {key}（现状）')
        self.assertEqual(state['calls'], 1, '只有解析那一次；视图侧不得为 page>1 现算')
        self.assertEqual(body['total'], 4)


# ⑤ 体积核算（`_parse_value_bytes` 按真实量级计入）与「直方图口径不等价」那条决策见证
# 在 test/backend/test_column_profile_caliber.py —— 同一批契约，拆文件减压本文件的行数。
