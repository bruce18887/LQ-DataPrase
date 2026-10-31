"""T1：解析缓存的**按路径定点淘汰**——语义本体（2026-10-28 波次 G1）。

动机（这轮要修的东西）：删掉某一个用户的某一只文件，过去会把**全站**解析缓存一把
清空 —— 其他用户下一次请求全部从盘上重解析。于是这一刀把「淘汰」做成按内容坐标
定点的，而**全站清空只留给内存压力与整体改路径的管理命令**。
调用点是否真的只交出「它动过的那些路径」，由 `test/backend/test_parse_cache_scoped_invalidation.py`
从 HTTP 侧钉；与在途发布 / 全站清空交错的那三层（③④⑤）在
`test/backend/test_parse_cache_eviction_interleave.py`；两份共用
`test/backend/parse_cache_eviction_fixtures.py` 那套道具（拆的唯一理由是 600 行闸：
判据一条没缩、理由一句没删，只是换个文件放）。

本文件这几层（改实现前先对这张表，别照记忆写注释）：
① ``_BytesLRUCache.evict_keys(pred)``：只逐匹配项、计费逐字对称（**同键覆盖也先退旧账**——
   ``_store_locked`` 的双计费由两条新例钉，残量在定点淘汰之后没有任何常规动作能归零）、
   **可以清空到 0 条**（这一点与 ``evict_to`` 的「至少保留一条」刻意不同）、
   谓词抛错时整条缓存一格没动、入账进 ``_evictions`` 而不是 ``_clears``；
   谓词收到的是**整个键**（按 ``key[2]`` 收窄那种例子只说明这份通用性，不代表路径 API）。
② ``services.evict_parse_cache_for_paths(paths)``：键的第一元与传入路径**两边各过一次
   ``normcase(normpath(...))``** 再比 —— ``resolve_file_path`` 对绝对入库值是原样透传
   （不做 normpath），直接 ``==`` 会让同一只文件的不同写法各留一条。
   谓词只看 ``key[0]`` ⇒ 同一路径的**所有格式**一起走（生产语义；别读成按格式收窄）。
⑥ 「定点淘汰够用」的两半论证里属于本文件的那一半：**文件真被删**时 ``_disk_mtime_ns``
   走 OSError 分支读回 **0** ⇒ 下一次读算出的键与残留条目不是同一个键、必然 miss
   （另一半「同坐标还有存活行时留下的条目是**正确内容**」在
   ``test_parse_cache_scoped_invalidation.py::SharedPhysicalPathTests``）。
⑦ 调用点交出去的那条路径**必须是真 unlink 掉的那一条**：``_delete_datafile_file_only``
   的返回值就是三个调用点的淘汰集合来源（质量收口轮 finding 5），两个撒谎方向各钉一条。
"""
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from django.test import override_settings

from apps.datafiles import services

from test.backend.parse_cache_eviction_fixtures import (
    _CacheSwapBase,
    _frame,
    _tmp_path,
    _value,
)


class EvictKeysSemanticsTests(_CacheSwapBase):
    """① ``evict_keys`` 本体：只逐匹配项、计费对称、允许清空。"""

    def test_evicts_only_matching_keys_and_debits_exactly_those_bytes(self):
        frame_a = _frame(rows=200)
        frame_b = _frame(rows=1000)   # 与 A 不同量级，才能证明「扣的是 A 的那一份」
        key_a = self.prime('/proj/g1/a.csv', frame_a)
        key_b = self.prime('/proj/g1/b.csv', frame_b)
        bytes_a = self.billed(key_a)
        bytes_b = self.billed(key_b)
        self.assertNotEqual(bytes_a, bytes_b, '前提：两条计费不同，否则本例无从分辨')
        before = self.cache.bytes_cached()
        self.assertEqual(before, bytes_a + bytes_b)

        evicted = self.cache.evict_keys(lambda key: key == key_a)

        self.assertEqual(evicted, 1)
        self.assertNotIn(key_a, self.cache._data)
        self.assertIn(key_b, self.cache._data, '未匹配的条目必须原地留着')
        self.assertIs(self.cache._data[key_b][0][0], frame_b, '留下的那条值不得换过')
        self.assertEqual(self.cache.bytes_cached(), before - bytes_a,
                         '计费只扣被逐出那一条的钱')
        self.assertEqual(self.billed(key_b), bytes_b, 'B 的计费不得被动过')

    def test_same_key_overwrite_debits_the_previous_entry(self):
        """同键第二次写入是**覆盖**：累计计费换成新值，不是新旧相加。

        ``_store_locked`` 用 ``self._data[key] = (value, nbytes)`` 落条目后把 ``nbytes``
        直接累进 ``_total``；OrderedDict 的同键覆盖不会替旧那份钱退账 ⇒ 一只条目占两笔预算
        （本例那两只值的实测计费 32932 与 64932，退账之前的旧写法把 ``bytes_cached()`` 报成
        97864，而缓存里只有 1 条）。仓内可复现的反证（不依赖任何日志）：把 ``_store_locked``
        里「同键覆盖先退旧账」那两行删掉再跑本例，最后那条断言当场红。
        判据取「条目只有一条」这个恒等式：``bytes_cached()`` 必须等于那一条自己的计费。
        """
        small, big = _frame(rows=1023), _frame(rows=2023)
        key_small = self.prime('/proj/g1/overwrite.csv', small)
        bytes_small = self.billed(key_small)
        key_big = self.prime('/proj/g1/overwrite.csv', big)
        bytes_big = self.billed(key_big)
        self.assertEqual(key_small, key_big, '前提：同 (路径, mtime_ns, 格式) ⇒ 同一个键')
        self.assertNotEqual(bytes_small, bytes_big,
                            '前提：两只值计费不同，否则本例分辨不出双计')
        self.assertEqual(len(self.cache), 1, '前提：覆盖不产生第二条条目')

        self.assertEqual(self.cache.bytes_cached(), bytes_big,
                         '同键覆盖后的累计计费只能是那一条自己的钱')

    def test_evicting_an_overwritten_key_returns_all_the_money(self):
        """淘汰一条被覆盖过的键，钱必须一次还清 —— 残量在此后**没有任何常规动作能归零**。

        G1 之前每删一次文件都 ``clear()`` 一遍，把多计的钱顺手抹平；改成定点淘汰之后，
        ``_total`` 只剩「逐出时扣自己那份」这一条归还路径 ⇒ 双计的那半笔变成永久虚占预算，
        后续每次写入都按虚高的总量提前逐掉别的条目。``evict_parse_cache_for_paths`` 的
        「定点淘汰就是立刻把它还回去」也只有在还不虚账时才是事实。
        """
        key = self.prime('/proj/g1/overwrite.csv', _frame(rows=1023))
        self.prime('/proj/g1/overwrite.csv', _frame(rows=2023))
        self.assertEqual(len(self.cache), 1, '前提：两只值同键，已覆盖成一条')

        self.assertEqual(self.cache.evict_keys(lambda k: k == key), 1)

        self.assertEqual(len(self.cache), 0)
        self.assertEqual(self.cache.bytes_cached(), 0,
                         '逐出最后一条后计费必须归零（残量就是无主记账）')

    def test_can_remove_every_entry_unlike_evict_to(self):
        """定点淘汰允许清零；``evict_to`` 的「至少留一条」在这里是错的语义。

        两者的驱动源不同：``evict_to``/``_store_locked`` 按**预算**淘汰，留一条是防热点
        文件刚存就自逐；本例逐的是**这次操作点名**的那条（删掉的、或移走的旧位置）。
        点名的理由**不是**「没人再能命中它」—— 那句在本仓站不住：``file_path`` 上没有唯一
        约束，同一坐标还可以有别的行（两半真论证见 ``services.evict_parse_cache_for_paths``
        的 docstring 与下面 ``RemovedFileRereadsUnderANewKeyTests``）。点是「留着不欠谁」：
        没有行读它时它只是白占预算，有别的行读它时它给的也是同一份正确内容，逐掉最多
        重解析一次 —— 两种情况都不脏，所以清零是安全的。
        """
        key_a = self.prime('/proj/g1/a.csv', _frame())
        key_b = self.prime('/proj/g1/b.csv', _frame(rows=400))
        self.assertEqual(len(self.cache), 2)

        self.cache.evict_keys(lambda key: key in (key_a, key_b))

        self.assertEqual(len(self.cache), 0, '点名全逐时必须能清空到 0 条')
        self.assertEqual(self.cache.bytes_cached(), 0, '清零时计费也必须归零')
        # 同一只缓存上 evict_to(0) 的既有语义不变（对照，不是本刀改的东西）
        self.prime('/proj/g1/c.csv', _frame())
        self.prime('/proj/g1/d.csv', _frame(rows=400))
        self.cache.evict_to(0)
        self.assertEqual(len(self.cache), 1, 'evict_to 仍是「至少保留一条」')

    def test_predicate_exception_leaves_the_cache_untouched(self):
        """谓词在扫描阶段抛错时**一条都不能已经弹出**，否则计费与条目会错开。"""
        key_a = self.prime('/proj/g1/a.csv', _frame())
        key_b = self.prime('/proj/g1/b.csv', _frame(rows=400))
        bytes_before = self.cache.bytes_cached()

        def boom(key):
            if key == key_b:
                raise RuntimeError('predicate exploded')
            return False

        with self.assertRaises(RuntimeError):
            self.cache.evict_keys(boom)

        self.assertEqual(set(self.cache._data), {key_a, key_b},
                         '谓词抛错后两条都必须还在')
        self.assertEqual(self.cache.bytes_cached(), bytes_before,
                         '计费不得部分扣减')

    def test_counts_into_evictions_not_clears(self):
        """/metrics 里「预算淘汰」与「定点淘汰」同账，``clears`` 只算显式全清。"""
        key_a = self.prime('/proj/g1/a.csv', _frame())
        before = services.get_parse_cache_stats()

        self.assertEqual(self.cache.evict_keys(lambda key: key == key_a), 1)

        after = services.get_parse_cache_stats()
        self.assertEqual(after['evictions'] - before['evictions'], 1)
        self.assertEqual(after['clears'], before['clears'],
                         '定点淘汰不得计入 clears（会把「删一个文件」读成「全站清空」）')

    def test_predicate_receives_the_whole_key_tuple(self):
        """``evict_keys`` 交给谓词的是**整个键** —— 这是它自己的契约面，不是路径 API 的语义。

        本例只钉「谓词收到 ``(路径, mtime_ns, 格式)`` 三元组，可以按任意一元收窄」。
        **别把它读成「删文件时只会走一种格式」**：生产里 ``evict_parse_cache_for_paths``
        的谓词只看 ``key[0]``，同一路径的所有格式一起走 —— 那条生产语义由
        ``EvictForPathsTests.test_evicting_a_path_removes_every_format_entry_for_it`` 钉。
        这里用的 ``key[2]`` 谓词没有任何调用点会构造，它的价值只在「谓词参数是完整键」。
        """
        same_path = '/proj/g1/dual.csv'
        key_cta = self.prime(same_path, _frame(), mtime=7, fmt='CTA8290D')
        key_ets = self.prime(same_path, _frame(rows=400), mtime=7, fmt='ETS88')

        self.cache.evict_keys(lambda key: key[0] == same_path
                              and key[2] == 'CTA8290D')

        self.assertNotIn(key_cta, self.cache._data)
        self.assertIn(key_ets, self.cache._data,
                      '谓词按 key[2] 收窄时另一种格式留着（仅说明 evict_keys 的通用性）')

    def test_no_match_and_empty_cache_change_nothing(self):
        key_a = self.prime('/proj/g1/a.csv', _frame())
        before = services.get_parse_cache_stats()

        self.assertEqual(self.cache.evict_keys(lambda key: False), 0)
        self.assertEqual(self.cache.evict_keys(lambda key: key[0] == '/proj/none.csv'), 0)

        self.assertEqual(set(self.cache._data), {key_a})
        self.assertEqual(self.cache.bytes_cached(), self.billed(key_a))
        after = services.get_parse_cache_stats()
        self.assertEqual((after['evictions'], after['clears']),
                         (before['evictions'], before['clears']),
                         '没逐出任何东西时不得虚增计数')


class EvictForPathsTests(_CacheSwapBase):
    """② ``evict_parse_cache_for_paths``：按路径集合淘汰，比对前两边归一化。"""

    def test_untouched_path_keeps_its_entry_and_its_billing(self):
        frame_b = _frame(rows=1000)
        key_a = self.prime('/proj/g1/a.csv', _frame())
        key_b = self.prime('/proj/g1/b.csv', frame_b)
        bytes_b = self.billed(key_b)

        self.assertEqual(
            services.evict_parse_cache_for_paths([key_a[0]]), 1)

        self.assertIn(key_b, self.cache._data)
        self.assertIs(self.cache._data[key_b][0][0], frame_b)
        self.assertEqual(self.cache.bytes_cached(), bytes_b)

    def test_evicting_a_path_removes_every_format_entry_for_it(self):
        """生产语义：路径 API 的谓词只看 ``key[0]`` ⇒ 同一路径的**所有**格式一起走。

        键里留 ``format_type`` 是为了**读**的正确性（同一路径被两行标成不同格式时用的是
        不同 parser，见 ``_cached_parse`` 的 docstring）；淘汰侧刻意不做同规格的收窄：
        一次删除/移动之后「这只路径还该按哪种格式解析」已经不可信，宁可多逐一条
        （最多多付一次重解析），也不能出现「按路径点名却逐不掉的条目」。
        本例断的是两条都走 —— 不是「该留的那条留下」，生产不给那个保证。
        """
        same_path = '/proj/g1/dual.csv'
        key_cta = self.prime(same_path, _frame(), mtime=7, fmt='CTA8290D')
        key_ets = self.prime(same_path, _frame(rows=400), mtime=7, fmt='ETS88')
        self.assertNotEqual(key_cta, key_ets, '前提：同路径不同格式是两条独立条目')

        self.assertEqual(services.evict_parse_cache_for_paths([same_path]), 2,
                         '两种格式的条目都要被这一次点名收走')

        self.assertNotIn(key_cta, self.cache._data)
        self.assertNotIn(key_ets, self.cache._data)
        self.assertEqual(self.cache.bytes_cached(), 0, '两条的钱也都得退回来')

    def test_variant_spellings_of_one_path_evict_together(self):
        """键的第一元来自 ``resolve_file_path``，它对**绝对**入库值原样透传、
        对相对值才做 ``normpath`` ⇒ 同一只文件在缓存里可以有不同写法。
        比对前两边各过一次归一化，否则「写法规格不同」的那条永远逐不掉
        （逐不掉不脏 —— 同一只文件的同一份内容 —— 但白占预算，对这些条目这一刀就没兑现）。
        """
        base = os.path.normpath(tempfile.gettempdir())
        real = os.path.join(base, 'g1-variant.csv')
        spelled = base + os.sep + '.' + os.sep + 'g1-variant.csv'
        key = self.prime(real, _frame())
        self.assertNotEqual(key[0], spelled, '前提：两种写法逐字不同，才测得到归一化')

        self.assertEqual(services.evict_parse_cache_for_paths([spelled]), 1,
                         '同一只文件的另一种写法必须同样逐出')
        self.assertNotIn(key, self.cache._data)

    def test_other_paths_in_the_same_directory_survive(self):
        base = os.path.normpath(tempfile.gettempdir())
        doomed = self.prime(os.path.join(base, 'g1-a.csv'), _frame())
        kept = self.prime(os.path.join(base, 'g1-b.csv'), _frame(rows=1000))

        services.evict_parse_cache_for_paths([os.path.join(base, 'g1-a.csv')])

        self.assertNotIn(doomed, self.cache._data)
        self.assertIn(kept, self.cache._data,
                      '同目录的邻居不是「动过的路径」，不得顺手逐掉')

    @unittest.skipUnless(os.path.normcase('A') == 'a',
                         'normcase 折大小写只在 nt 语义下成立')
    def test_case_variant_spelling_evicts_on_windows_semantics(self):
        """Windows（唯一出货平台）盘上大小写不敏感：两条大小写写法是同一只文件。

        逐出两条只会多付一次重解析，**少**逐出才可能留脏 —— 归一化折大小写是往安全
        那一侧偏。POSIX 上 ``normcase`` 是恒等、两条写法是两只不同文件，所以这条在
        POSIX 上 skip 而不是假绿。
        """
        base = os.path.normpath(tempfile.gettempdir())
        upper = os.path.join(base, 'G1-UPPER.csv')
        key = self.prime(upper, _frame())

        services.evict_parse_cache_for_paths([os.path.join(base, 'g1-upper.csv')])

        self.assertNotIn(key, self.cache._data)

    def test_empty_and_falsy_path_set_is_a_noop(self):
        key_a = self.prime('/proj/g1/a.csv', _frame())
        before = services.get_parse_cache_stats()

        for paths in ([], (), [None, ''], {''}):
            self.assertEqual(services.evict_parse_cache_for_paths(paths), 0,
                             f'空集合不该逐出任何东西：{paths!r}')

        self.assertIn(key_a, self.cache._data, '传空集合绝不等于「全清」')
        self.assertEqual(services.get_parse_cache_stats()['evictions'],
                         before['evictions'])

    def test_relative_row_spelling_evicts_the_read_side_key(self):
        """生产形状：读侧 key 是 ``resolve_file_path(相对入库值)`` 的结果，
        调用点交出来的也是同一个函数的结果 ⇒ 必须逐字命中（本例走真实 resolve，
        不是手写字符串，免得判据与被测代码各写各的）。
        """
        from apps.datafiles.utils import resolve_file_path, store_file_path
        base = _tmp_path('g1-media-root')
        os.makedirs(base, exist_ok=True)
        self.addCleanup(shutil.rmtree, base, True)
        abs_path = os.path.join(base, 'data', 'u1', 'single', 'x.csv')
        with override_settings(MEDIA_ROOT=base):
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write('a,b\n1,2\n')
            row_value = store_file_path(abs_path)
            key = self.prime(resolve_file_path(row_value), _frame())

            services.evict_parse_cache_for_paths([resolve_file_path(row_value)])

            self.assertNotIn(key, self.cache._data,
                             '相对入库的行删掉后，它的缓存条目必须真的消失')


class RemovedFileRereadsUnderANewKeyTests(_CacheSwapBase):
    """⑥ 「文件真被删」这一半论证：``_disk_mtime_ns`` 读回 0 ⇒ 下一次读换键、必然 miss。

    ``evict_parse_cache_for_paths`` 的 docstring 说「定点淘汰足够」靠的是两半论证；
    另一半（同坐标还有存活行时，留下的条目是**正确内容**而不是脏内容）由
    ``test_parse_cache_scoped_invalidation.py::SharedPhysicalPathTests`` 从 HTTP 侧钉。
    本类钉这一半，全部走**真** ``os.stat``：先按生产键形（路径 + 真实 mtime_ns + 格式）
    灌一条，再把盘上文件删掉，然后走 ``_cached_parse`` 读一次 —— 读侧自己算出的
    ``path_key`` 已经是 0，与残留条目的键不是同一个键。
    """

    def test_disk_mtime_ns_reads_zero_once_the_file_is_gone(self):
        path = _tmp_path('g1-mtime-zero.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('a,b\n1,2\n')
        alive = services._disk_mtime_ns(path)
        self.assertNotEqual(alive, 0, '前提：文件在盘上时 mtime_ns 非 0')

        os.remove(path)

        self.assertEqual(services._disk_mtime_ns(path), 0,
                         '文件没了走 OSError 分支读回 0 —— 「换键」论证靠的就是这个 0')

    def test_read_after_the_file_is_removed_does_not_serve_the_stale_entry(self):
        path = _tmp_path('g1-stale-serve.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('a,b\n1,2\n')
        frame = _frame()
        stale_key = (path, services._disk_mtime_ns(path), 'CTA8290D')
        self.assertNotEqual(stale_key[1], 0, '前提：条目是按**真实 mtime** 灌进去的')
        self.cache.put(stale_key, _value(frame))

        os.remove(path)
        df, _meta, _fmt = services._cached_parse(1, 1, services._disk_mtime_ns(path),
                                                 path, 'CTA8290D')

        self.assertIsNone(df, '删盘后读一次必须 miss（把留下的旧帧递出去就是 serve 脏）')
        self.assertIn(stale_key, self.cache._data,
                      '残留条目还在，只是没有读会再命中它 —— 等定点淘汰或预算回收')
        self.assertEqual(len(self.cache), 1,
                         '失败值不入缓存：mtime=0 那条新键没有挂进缓存')


class UnlinkedPathReturnContractTests(_CacheSwapBase):
    """⑦ 调用点交出去的「动过的路径」必须是**真 unlink 掉的那一条**（finding 5）。

    ``_delete_datafile_file_only`` 把「这次到底删掉了什么」作为返回值交出来，三个调用点
    （``file_views`` 的 destroy / bulk_delete 与 ``_helpers._delete_duplicate_files``）
    直接 append 它、不再各自重算一遍路径 ⇒ 这根线两个方向都会撒谎：
    没删也报路径 = 淘汰集合声称删过一只其实还在盘上的文件（而且把「重算」与「真删」两份
    路径变成两个事实来源，早晚对不上）；删了却报 ``None`` = 白占预算的条目留在原地。
    最后一例钉的是接线本身：交出去的那个值**逐字**命中读侧的键，而 ``None`` 是空操作。
    """

    def _media(self):
        base = _tmp_path('g1-unlink-contract')
        os.makedirs(base, exist_ok=True)
        self.addCleanup(shutil.rmtree, base, True)
        override = override_settings(MEDIA_ROOT=base)
        override.enable()
        self.addCleanup(override.disable)
        return base

    @staticmethod
    def _row(file_path_value):
        """助手只读 ``datafile.file_path`` 这一列（其余字段一个都不碰）⇒ 给它那只形状就够。"""
        return types.SimpleNamespace(file_path=file_path_value)

    def test_returns_the_path_it_actually_unlinked(self):
        from apps.datafiles.utils import store_file_path
        from apps.datafiles.views._helpers import _delete_datafile_file_only
        base = self._media()
        abs_path = os.path.join(base, 'data', 'u1', 'single', 'x.csv')
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write('a,b\n1,2\n')

        returned = _delete_datafile_file_only(self._row(store_file_path(abs_path)))

        self.assertIsNotNone(returned, '真删掉了就必须报出路径（报 None 就是漏逐）')
        self.assertEqual(os.path.normpath(returned), os.path.normpath(abs_path),
                         '交出去的必须就是它 unlink 掉的那条绝对路径')
        self.assertFalse(os.path.exists(abs_path), '前提：盘上确实没了')

    def test_returns_none_when_there_was_nothing_to_unlink(self):
        """盘上本来没文件 ⇒ 不许报出一条「我删了它」的路径，淘汰集合据它说话。"""
        from apps.datafiles.utils import store_file_path
        from apps.datafiles.views._helpers import _delete_datafile_file_only
        base = self._media()
        abs_path = os.path.join(base, 'data', 'u1', 'single', 'gone.csv')
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        self.assertIsNone(
            _delete_datafile_file_only(self._row(store_file_path(abs_path))),
            '没 unlink 却报路径 = 让淘汰集合声称删过一只它没碰过的文件')

    def test_returns_none_when_the_unlink_fails(self):
        """``os.remove`` 抛错被吞掉那一支同样不许报路径：docstring 承诺的是「真删掉」，
        不是「试过」。"""
        from apps.datafiles.utils import store_file_path
        from apps.datafiles.views._helpers import _delete_datafile_file_only
        base = self._media()
        abs_path = os.path.join(base, 'data', 'u1', 'single', 'locked.csv')
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write('a,b\n1,2\n')

        with mock.patch('apps.datafiles.views._helpers.os.remove',
                        side_effect=OSError('locked')):
            returned = _delete_datafile_file_only(self._row(store_file_path(abs_path)))

        self.assertIsNone(returned, 'unlink 失败时返回的必须还是 None')
        self.assertTrue(os.path.exists(abs_path), '前提：remove 被拦下，文件还在盘上')

    def test_returned_path_hits_the_read_side_key_and_none_is_a_noop(self):
        """就是三个调用点那句写法：``evict_parse_cache_for_paths([<助手返回值>])``。

        条目按**读侧真正会算出来的那只键**灌进去（``resolve_file_path`` 的结果 +
        盘上的真实 ``mtime_ns`` + 格式），否则「逐字命中」这句就只是断言谓词只看
        ``key[0]`` 的另一种写法。
        """
        from apps.datafiles.utils import resolve_file_path, store_file_path
        from apps.datafiles.views._helpers import _delete_datafile_file_only
        base = self._media()
        doomed = os.path.join(base, 'data', 'u1', 'single', 'wired.csv')
        kept_path = os.path.join(base, 'data', 'u1', 'single', 'other.csv')
        os.makedirs(os.path.dirname(doomed), exist_ok=True)
        for p in (doomed, kept_path):
            with open(p, 'w', encoding='utf-8') as f:
                f.write('a,b\n1,2\n')
        doomed_key = resolve_file_path(store_file_path(doomed))
        key = self.prime(doomed_key, _frame(),
                        mtime=services._disk_mtime_ns(doomed_key))
        kept_path_key = resolve_file_path(store_file_path(kept_path))
        kept = self.prime(kept_path_key, _frame(rows=400),
                          mtime=services._disk_mtime_ns(kept_path_key))

        self.assertEqual(
            services.evict_parse_cache_for_paths(
                [_delete_datafile_file_only(self._row(store_file_path(doomed)))]), 1,
            '真删掉的那条必须逐字命中读侧的键（否则 finding 5 这根线就是接错的）')
        self.assertNotIn(key, self.cache._data)

        # 同一路径再来一次：盘上已无文件 ⇒ 助手返回 None ⇒ 淘汰集合是空操作（不是全清）
        self.assertEqual(
            services.evict_parse_cache_for_paths(
                [_delete_datafile_file_only(self._row(store_file_path(doomed)))]), 0,
            'None 被 `if p` 滤掉后剩下的就是「空集合 ⇒ 一条都不逐」这条真行为')
        self.assertEqual(set(self.cache._data), {kept}, '留下的那条不受影响')
