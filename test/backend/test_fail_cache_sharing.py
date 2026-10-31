"""T1（G2，2026-10-28 波次 G）：整文件 fail/临界格检测缓存的内容坐标语义。

被钉的六条（红因写在各自的 docstring 里；③④ 是旧实现也绿的守卫，明确标注、不当收益）：

① **跨 owner 共享一次检测**：两行 DataFile 指向同一只物理文件、两个 owner 各读一次
   ⇒ ``detect_fail_data_with_borderline`` 只跑 1 次，两侧拿到**同一只** fail_cells/
   borderline_cells 对象。旧实现键里有 ``file_id``/``owner_id`` ⇒ 2 次（本文件的第一条红）。
   对照组：同一 owner 连读两次也必须只有 1 次（这条在旧实现上就是绿的 —— 不是新增收益，
   是「共享没有把命中弄丢」的下限）。
② **失败值也缓存、坏文件不重复解析**：解析失败（parser 抛错）那次得到的
   ``(None, None, None, None)`` 必须占位 —— 解析缓存拒收失败帧（``store_if=_parse_succeeded``），
   检测缓存若也拒收，坏文件每刷新一次都要重解析一遍；HEAD 的 ``@lru_cache(maxsize=32)``
   正是把失败值 memo 住的（本文件的承重红：旧「不缓存失败」写法第二次浏览会再解析）。
   代价如实钉住：盘上 mtime 不变时失败值一直命中（瞬时失败会被记住），直到预算淘汰或
   全局清空 —— 与 HEAD 的 memo 同一条，只是上界从 32 条换成预算 B 下的至多 64 条。
③ **替换文件自失效**：``mtime_ns`` 进键 ⇒ 盘上文件被替换后换 key、重新检测
   （旧实现同样成立，属于「改键不能把既有保护弄丢」的守卫，先绿）。
④ **删盘读回 mtime=0**：文件被删后组出的 key 不再是它，恢复后必然 miss ⇒ 重新检测
   （同③，守卫）。
⑤ **按字节淘汰、失败有非 0 固定成本**：``_fail_cache`` 是 ``_BytesLRUCache``，超预算时逐
   最久未用的那一条，而不是 ``maxsize=32`` 的按条封顶；失败值按 ``_FAILED_VALUE_BYTES``
   计费（0 字节条目永不淘汰 ⇒ 必须非 0），预算 B 下失败条数至多 64（算术见该常量）。
⑥ ``clear_parse_cache()`` 连同缓存里的失败值一起清，清完必须重新解析。

清理口径：``clear_parse_cache()`` 同时清两只缓存（⑤ 的 G1 契约由
``test_parse_cache_eviction_interleave.py`` 钉着）；本文件用它做用例隔离，
不直接摸 ``_fail_cache`` 的内部计数（例外是 ⑤ 的形状/上界判据，它们必须在**新**形状上跑）。
"""
import os
import shutil
import tempfile
from unittest import mock

import pandas as pd
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.datafiles import services
from apps.datafiles.models import DataFile
from apps.datafiles.utils import store_file_path

_FORMAT = 'ETS88'   # 该格式的 bin 列名是 ``Bin``（helpers.BIN_COLUMN_MAPPING）


def _frame(rows=40):
    """可判 fail 的小帧：偶数行 Bin=2（fail 行），P1 越上限一半。"""
    return pd.DataFrame({
        'Bin': [1 if i % 2 else 2 for i in range(rows)],
        'P1': [float(i) for i in range(rows)],
        'P2': [float(i % 7) for i in range(rows)],
    })


_METADATA = {
    'format': _FORMAT,
    'units': {'P1': 'V', 'P2': 'V'},
    'mins': {'P1': '5', 'P2': '0'},
    'maxs': {'P1': '34', 'P2': '6'},
}


class _CountingParser:
    """假解析器：只认 ``os.path.exists`` + ``parse``（与 ``_parse_file_uncached`` 同口径）。"""

    def __init__(self, frame, metadata):
        self.frame = frame
        self.metadata = metadata
        self.calls = 0

    def parse(self, path):
        self.calls += 1
        return self.frame, dict(self.metadata)


class _ExplodingParser:
    def __init__(self):
        self.calls = 0

    def parse(self, path):
        self.calls += 1
        raise RuntimeError('disk on fire')


class _FailCacheCaseBase(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix='lqdp-g2-fail-')
        self.addCleanup(shutil.rmtree, self.media_root, True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)

        self.user_a = User.objects.create_user(
            username='g2_owner_a', password='pw', role='user')
        self.user_b = User.objects.create_user(
            username='g2_owner_b', password='pw', role='user')

        # 进程共享的模块级缓存：换一只空帧缓存，生产入口按全局名查它 ⇒ 打的就是这一只
        self.original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', self.original_cache)
        services._parse_cache = services._BytesLRUCache(
            services.PARSE_CACHE_BUDGET_BYTES)
        # 两只缓存都清干净
        services.clear_parse_cache()
        self.addCleanup(services.clear_parse_cache)

        self.frame = _frame()
        self.parser = _CountingParser(self.frame, _METADATA)
        original_parser = services.get_parser
        self.addCleanup(setattr, services, 'get_parser', original_parser)
        services.get_parser = lambda fmt: self.parser

        self.path = os.path.join(self.media_root, 'data', 'shared', 'one.csv')
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.write_file()

    def write_file(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('[Data]\nBin,P1,P2\n2,1,2\n')

    def bump_mtime(self, seconds=2):
        st = os.stat(self.path)
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + seconds * 10 ** 9))

    def make_row(self, user, path=None, name='one.csv'):
        return DataFile.objects.create(
            owner=user, filename=name,
            file_path=store_file_path(path or self.path),
            file_size=os.path.getsize(path or self.path),
            format_type=_FORMAT, file_type='single', status='ready',
        )

    @staticmethod
    def detect_spy():
        """按 R6③ patch **消费方绑定**（``services`` 上的那个名字）。"""
        real = services.detect_fail_data_with_borderline
        return mock.patch.object(
            services, 'detect_fail_data_with_borderline', side_effect=real)


class FailDataSharingTests(_FailCacheCaseBase):
    """① 内容坐标键：两行一条物理文件只检测一次；两 owner 拿到同一只结果。"""

    def test_two_owners_of_one_physical_file_detect_once(self):
        row_a = self.make_row(self.user_a)
        row_b = self.make_row(self.user_b)

        with self.detect_spy() as spy:
            first = services.get_cached_fail_data(
                row_a.id, self.user_a.pk, row_a)
            second = services.get_cached_fail_data(
                row_b.id, self.user_b.pk, row_b)

        self.assertIsNotNone(first[2], '前提：检测返回了真实结果（不是失败四元组）')
        self.assertEqual(spy.call_count, 1,
                         f'两行同一物理文件应只检测 1 次，实际 {spy.call_count} 次')
        self.assertEqual(self.parser.calls, 1,
                         f'帧也只该解析 1 次，实际 {self.parser.calls} 次')
        self.assertIs(first[2], second[2], 'fail_cells 必须是同一只共享对象')
        self.assertIs(first[3], second[3], 'borderline_cells 必须是同一只共享对象')
        self.assertIs(first[0], second[0], 'fail_indices 必须是同一只共享对象')
        self.assertIs(first[1], second[1], 'fail_columns 必须是同一只共享对象')

    def test_single_owner_two_reads_detect_once(self):
        """对照组（下限）：同一 owner 连读两次也不许各检测一遍。"""
        row = self.make_row(self.user_a)

        with self.detect_spy() as spy:
            first = services.get_cached_fail_data(row.id, self.user_a.pk, row)
            second = services.get_cached_fail_data(row.id, self.user_a.pk, row)

        self.assertEqual(spy.call_count, 1)
        self.assertIs(first[2], second[2])

    def test_two_rows_on_one_path_share_one_object_and_only_read_it(self):
        """共享的前提是只读：两侧读到的是同一只 dict，且第二次没有重新检测。"""
        row_a = self.make_row(self.user_a)
        row_b = self.make_row(self.user_b)
        with self.detect_spy() as spy:
            first = services.get_cached_fail_data(row_a.id, self.user_a.pk, row_a)
            snapshot = dict(first[2])
            second = services.get_cached_fail_data(row_b.id, self.user_b.pk, row_b)

        self.assertEqual(spy.call_count, 1)
        self.assertIs(first[2], second[2])
        self.assertEqual(second[2], snapshot,
                         '第二次读取不得改变第一次看到的内容（共享只读）')


class FailDataFailureCachedTests(_FailCacheCaseBase):
    """② 失败四元组占位：坏文件第二次浏览不再解析，修复靠 mtime 换键。"""

    def test_broken_file_is_not_reparsed_on_the_next_browse(self):
        """承重红（旧「不缓存失败」写法）：第二次浏览从 1 次解析变成 2 次。"""
        row = self.make_row(self.user_a)
        boom = _ExplodingParser()
        services.get_parser = lambda fmt: boom

        first = services.get_cached_fail_data(row.id, self.user_a.pk, row)
        self.assertEqual(first, (None, None, None, None),
                         '前提：解析失败返回既有失败四元组')
        self.assertEqual(boom.calls, 1)

        second = services.get_cached_fail_data(row.id, self.user_a.pk, row)

        self.assertEqual(second, (None, None, None, None))
        self.assertIs(first, second, '失败值必须是同一只缓存对象（命中，不是重算）')
        self.assertEqual(boom.calls, 1,
                         '第二次浏览不得再解析（HEAD 的 lru_cache 也 memo 失败值）')

    def test_failed_value_is_charged_a_nonzero_footprint(self):
        row = self.make_row(self.user_a)
        services.get_parser = lambda fmt: _ExplodingParser()

        services.get_cached_fail_data(row.id, self.user_a.pk, row)

        self.assertGreater(services._FAILED_VALUE_BYTES, 0,
                           '失败值的成本必须非 0（0 字节条目永不淘汰）')
        self.assertEqual(len(services._fail_cache), 1)
        self.assertEqual(services._fail_cache.bytes_cached(),
                         services._FAILED_VALUE_BYTES)

    def test_fixing_the_file_via_mtime_reparses(self):
        row = self.make_row(self.user_a)
        boom = _ExplodingParser()
        services.get_parser = lambda fmt: boom
        services.get_cached_fail_data(row.id, self.user_a.pk, row)

        # 修复 = 盘上文件被替换（mtime 变），解析器同时恢复
        services.get_parser = lambda fmt: self.parser
        self.bump_mtime()
        with self.detect_spy() as spy:
            fixed = services.get_cached_fail_data(row.id, self.user_a.pk, row)

        self.assertEqual(boom.calls, 1)
        self.assertEqual(self.parser.calls, 1, 'mtime 变 ⇒ 新 key ⇒ 必须重新解析')
        self.assertEqual(spy.call_count, 1, '解析恢复后必须重新检测')
        self.assertIsNotNone(fixed[2])

    def test_unchanged_mtime_keeps_serving_the_cached_failure(self):
        """如实钉住代价（与 HEAD 的 memo 同一条，不是缺陷）：文件没动 ⇒ 失败值一直命中。

        清掉它的只有两条路：预算淘汰（``_FAILED_VALUE_BYTES`` 的上界）或
        ``clear_parse_cache()``。要重新解析，必须让 mtime 变（文件被替换/重写）。
        """
        row = self.make_row(self.user_a)
        boom = _ExplodingParser()
        services.get_parser = lambda fmt: boom
        services.get_cached_fail_data(row.id, self.user_a.pk, row)

        services.get_parser = lambda fmt: self.parser   # 只换解析器、不动盘上文件
        again = services.get_cached_fail_data(row.id, self.user_a.pk, row)

        self.assertEqual(again, (None, None, None, None))
        self.assertEqual(boom.calls, 1)
        self.assertEqual(self.parser.calls, 0,
                         'mtime 没变 ⇒ 失败值仍命中（诚实代价，见 docstring）')

    def test_clear_parse_cache_drops_cached_failures(self):
        row = self.make_row(self.user_a)
        boom = _ExplodingParser()
        services.get_parser = lambda fmt: boom
        services.get_cached_fail_data(row.id, self.user_a.pk, row)
        self.assertEqual(len(services._fail_cache), 1)

        services.clear_parse_cache()

        self.assertEqual(len(services._fail_cache), 0, '全清必须放掉失败值')
        services.get_cached_fail_data(row.id, self.user_a.pk, row)
        self.assertEqual(boom.calls, 2, '清完下一次浏览必须重新解析')


class FailDataContentCoordinateTests(_FailCacheCaseBase):
    """③④ 内容坐标的两条既有保护：替换文件换 key、删盘读回 mtime=0。"""

    def test_replaced_file_invalidates_via_mtime(self):
        row = self.make_row(self.user_a)
        with self.detect_spy() as spy:
            services.get_cached_fail_data(row.id, self.user_a.pk, row)
            self.assertEqual(spy.call_count, 1)
            self.bump_mtime()
            services.get_cached_fail_data(row.id, self.user_a.pk, row)
        self.assertEqual(spy.call_count, 2, 'mtime 变 ⇒ 换 key ⇒ 重新检测')

    def test_removed_file_rereads_under_a_new_key_after_it_returns(self):
        row = self.make_row(self.user_a)
        services.get_cached_fail_data(row.id, self.user_a.pk, row)

        os.remove(self.path)
        self.assertEqual(services._disk_mtime_ns(self.path), 0,
                         '删盘必须读回 mtime_ns=0（换 key 的依据）')
        gone = services.get_cached_fail_data(row.id, self.user_a.pk, row)
        self.assertEqual(gone, (None, None, None, None),
                         '文件没了 ⇒ 失败四元组（既有契约）')

        self.write_file()
        self.bump_mtime()
        with self.detect_spy() as spy:
            back = services.get_cached_fail_data(row.id, self.user_a.pk, row)
        self.assertEqual(spy.call_count, 1, '文件恢复 ⇒ 必然 miss ⇒ 重新检测')
        self.assertIsNotNone(back[2])


class FailCacheBudgetTests(_FailCacheCaseBase):
    """⑤ 新缓存按字节淘汰；失败值有非 0 固定成本且条数上界与 HEAD 同量级。"""

    def test_fail_cache_is_a_bytes_lru_with_a_nonzero_budget(self):
        self.assertTrue(hasattr(services, '_fail_cache'),
                        'G2：_fail_cache 必须是 _BytesLRUCache 实例')
        self.assertIsInstance(services._fail_cache, services._BytesLRUCache)
        self.assertGreater(services.FAIL_CACHE_BUDGET_BYTES, 0,
                           '默认内存预算下失败检测缓存必须有正的字节预算')

    def test_entries_evict_by_byte_budget_not_by_count(self):
        frame = self.frame
        one = services._fail_value_bytes(
            services.detect_fail_data_with_borderline(frame, _METADATA))
        self.assertGreater(one, 0, '前提：一条检测值的计费必须非 0（0 字节条目永不逐出）')
        original = services._fail_cache
        self.addCleanup(setattr, services, '_fail_cache', original)
        services._fail_cache = services._BytesLRUCache(int(one * 1.6))
        self.addCleanup(services.clear_parse_cache)

        other = os.path.join(self.media_root, 'data', 'shared', 'two.csv')
        with open(other, 'w', encoding='utf-8') as f:
            f.write('[Data]\nBin,P1,P2\n2,1,2\n')
        row_a = self.make_row(self.user_a)
        row_b = self.make_row(self.user_a, path=other, name='two.csv')

        key_a = self._fail_key(row_a)
        services.get_cached_fail_data(row_a.id, self.user_a.pk, row_a)
        self.assertEqual(len(services._fail_cache), 1)
        services.get_cached_fail_data(row_b.id, self.user_a.pk, row_b)

        self.assertEqual(len(services._fail_cache), 1,
                         '预算只装得下一条：第二条必须把第一条挤掉（按字节，不按条数）')
        self.assertNotIn(key_a, services._fail_cache._data)

    def test_production_budget_evicts_the_oldest_failure(self):
        """行为面上界：插满 65 条失败，最旧的一条必须已被逐出。"""
        if services.FAIL_CACHE_BUDGET_BYTES == 0:
            self.skipTest('LQDP_PARSE_CACHE_MB=0：缓存关闭，失败值不占位（见常量注释）')
        keys = [('/nonexistent/g2-fail-%02d.csv' % i, 0, _FORMAT)
                for i in range(65)]
        for key in keys:
            services._cached_fail_data(0, 0, key[1], key[0], key[2])

        fit = services.FAIL_CACHE_BUDGET_BYTES // services._FAILED_VALUE_BYTES
        self.assertLess(fit, 65, '前提：65 条失败装不进这份预算（否则本用例证明不了淘汰）')
        self.assertEqual(len(services._fail_cache), fit,
                         f'预算只装得下 {fit} 条失败，实际留下 {len(services._fail_cache)} 条')
        self.assertNotIn(keys[0], services._fail_cache._data,
                         '最旧的一条必须已被逐出')
        self.assertEqual(services._fail_cache.bytes_cached(),
                         fit * services._FAILED_VALUE_BYTES,
                         '留下的字节必须恰好是 fit 条固定成本')

    def _fail_key(self, row):
        """生产同源的内容坐标键：解析后的绝对路径 + 盘上 mtime_ns + 格式。"""
        path = services.resolve_file_path(row.file_path)
        return (path, services._disk_mtime_ns(path), row.format_type)
