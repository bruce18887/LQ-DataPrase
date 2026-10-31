"""T1：删/合并/拆批等调用点必须**只**淘汰它动过的那些路径（2026-10-28 波次 G1）。

`test/backend/test_parse_cache_eviction.py` 钉淘汰语义本身；本文件从 HTTP 侧钉
「调用点交出去的集合 == 它真的动过的那些路径」。判据形状每条都一样，两个方向都要断：
· A（本次操作真的动过的那只文件）的 key 消失 —— 否则这一刀白做，白占预算；
· B（**另一个用户**的文件）的 key 逐字还在，计费仍是 B 自己那份
  （``_data[kB][1]`` 未变、``bytes_cached()`` == 那一份）；
· 再读一次 B 不触发第二次解析 —— 这才是「其他用户不再重解析」这句收益的字面证据。
只断「B 还在」的话，把调用点改成「什么都不淘汰」也能全绿；所以每条都同时断 A 走。

除这个式子之外还有三条形状不同的判据，都在这份文件里：孤儿清理那个调用点上**同一 owner**
还活着的行（`ConsistencyScopingTests.test_delete_orphaned_db_keeps_a_live_row_of_the_same_owner`，
同目录同主人，是最容易被顺手多逐的一档）、「这次一行都没删 ⇒ 一条都不许淘汰」
（`..._with_nothing_orphaned_evicts_nothing`，HEAD 在这个分支上是无条件全清，正是 G1 要拆的那把清空）、
以及两行共享一只物理文件时留下的条目是**正确内容**而不是脏内容（`SharedPhysicalPathTests`，
`file_path` 上没有唯一约束，`consolidate_uploads` 的 db_only 分支就在造这个形状）。

管理命令那两条（``fix_moved_project_paths`` / ``consolidate_uploads``）**刻意仍是全站
清空**：它们成批整体改路径、跑在带外，定点淘汰省不下什么，而漏逐的代价**只是白占预算**
（键是内容坐标，脏不了 —— 两半论证见 ``SharedPhysicalPathTests`` 与
``test_parse_cache_eviction.py::RemovedFileRereadsUnderANewKeyTests``）。
本文件把那两条也钉成断言（动过的与没动过的**一起消失**），谁把它们改成定点淘汰就红，
反过来把 ``MemoryError`` 那条改成定点淘汰也红 —— 见
``test/backend/test_parse_cache_eviction_interleave.py::GlobalClearStillClearsEverythingTests``。
"""
import os
import shutil
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles import services
from apps.datafiles.models import DataFile
from apps.datafiles.utils import resolve_file_path, store_file_path

from test.backend.parse_cache_eviction_fixtures import _frame


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


class _PathFramesParser:
    """假解析器：按路径返回事先备好的帧，并按路径记录「真解析过几次」。

    ``_parse_file_uncached`` 只认 ``os.path.exists`` + ``parser.parse``，所以这里的
    帧能原样进缓存 —— 判据要的正是「缓存里那只帧是不是原来那只」。
    """

    def __init__(self):
        self.frames = {}
        self.parsed_paths = []

    def add(self, path, frame):
        self.frames[_norm(path)] = frame

    def parse(self, path):
        self.parsed_paths.append(_norm(path))
        return self.frames[_norm(path)], {'format': 'G1'}

    def count(self, path):
        return self.parsed_paths.count(_norm(path))


class _CallSiteBase(TestCase):
    """两只用户、两只文件、缓存里两条都在 —— 每次操作后只看「A 走 B 留」。"""

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix='lqdp-g1-callsite-')
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.owner = User.objects.create_user(
            username='g1_owner', password='pw', role='user')
        self.stranger = User.objects.create_user(
            username='g1_stranger', password='pw', role='user')
        self.admin = User.objects.create_user(
            username='g1_admin', password='pw', role='administrator')

        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

        # 进程共享的模块级缓存：换一只空的，生产入口按全局名查它 ⇒ 打的就是这一只
        original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', original_cache)
        services._parse_cache = services._BytesLRUCache(
            services.PARSE_CACHE_BUDGET_BYTES)
        self.cache = services._parse_cache

        self.parser = _PathFramesParser()
        original_parser = services.get_parser
        self.addCleanup(setattr, services, 'get_parser', original_parser)
        services.get_parser = lambda fmt: self.parser

        fail_cache = services._cached_fail_data
        self.addCleanup(fail_cache.cache_clear)
        fail_cache.cache_clear()

    # --- 造盘上行 ---
    def make_row(self, user, name, file_type='single', batch_name='',
                 sub_batch='', rows=200):
        parts = ['data', user.username, file_type]
        if file_type == 'batch':
            parts.append(batch_name)
            if sub_batch:
                parts.append(sub_batch)
        target_dir = os.path.join(self.media_root, *parts)
        os.makedirs(target_dir, exist_ok=True)
        abs_path = os.path.join(target_dir, name)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write('[Data]\ncol1,col2\nu1,u2\n1,2\n2,1\n1,2\n')
        self.parser.add(abs_path, _frame(rows=rows))
        return DataFile.objects.create(
            owner=user, filename=name, file_path=store_file_path(abs_path),
            file_size=os.path.getsize(abs_path), format_type='CTA8290D',
            file_type=file_type, batch_name=batch_name, sub_batch=sub_batch,
            status='ready',
        )

    def make_legacy_abs_row(self, user, abs_path, name, rows=200):
        """管理命令要的那条形状：入库值是**绝对路径**（旧格式），不走 store_file_path。"""
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write('[Data]\ncol1,col2\nu1,u2\n1,2\n2,1\n1,2\n')
        self.parser.add(abs_path, _frame(rows=rows))
        return DataFile.objects.create(
            owner=user, filename=name, file_path=abs_path,
            file_size=os.path.getsize(abs_path), format_type='CTA8290D',
            file_type='single', status='ready',
        )

    # --- 缓存侧道具 ---
    def read(self, row):
        return services.get_cached_parsed_file(row.id, row.owner_id, row)[0]

    def prime(self, *row_list):
        """走**生产读路径**灌缓存（键由 ``get_cached_parsed_file`` 自己算），返回 row.id→key。"""
        keys = {}
        for row in row_list:
            self.assertIsNotNone(self.read(row), f'前提：{row.filename} 应解析成功')
            keys[row.id] = self.key_of(row)
        self.assertEqual(len(self.cache), len(row_list),
                         '前提：缓存里应该正好是这几条，多了说明被别的用例污染')
        return keys

    def key_of(self, row):
        want = _norm(resolve_file_path(row.file_path))
        hits = [k for k in self.cache._data if _norm(k[0]) == want]
        self.assertEqual(len(hits), 1, f'{row.filename} 在缓存里应有且只有一条：{hits}')
        return hits[0]

    def billed(self, key):
        return self.cache._data[key][1]

    def assert_scoped(self, key_a, key_b, keep_row, billed_b):
        """操作后一次性跑完的四件断言：A 走、B 逐字留、B 计费没被动、再读 B 不再解析。"""
        self.assertNotIn(key_a, self.cache._data,
                         'A 是本次真的动过的那条，必须被淘汰')
        self.assertIn(key_b, self.cache._data,
                      'B 没被这次操作碰到，它的条目必须逐字留着（全站清空就是死在这里）')
        entry = self.cache._data[key_b]
        self.assertEqual(entry[1], billed_b, 'B 的计费不得被动过')
        self.assertEqual(self.cache.bytes_cached(), billed_b,
                         '全站累计只扣掉了 A 的那一份')
        df = self.read(keep_row)
        self.assertIs(df, entry[0][0], '再读 B 必须命中留下的那只帧')
        self.assertEqual(self.parser.count(resolve_file_path(keep_row.file_path)), 1,
                         'B 一条都不该再解析（「其他用户不再重解析」的字面证据）')


class FileDeleteScopingTests(_CallSiteBase):
    """单删 / 批量删：只交出被删行的路径。"""

    def test_destroy_evicts_only_the_deleted_file(self):
        a = self.make_row(self.owner, 'a.csv', rows=200)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)
        keys = self.prime(a, b)
        billed_b = self.billed(keys[b.id])

        resp = self.client.delete(f'/api/v1/files/{a.id}/')

        self.assertEqual(resp.status_code, 204, resp.data if hasattr(resp, 'data') else '')
        self.assert_scoped(keys[a.id], keys[b.id], b, billed_b)
        self.assertFalse(DataFile.objects.filter(pk=a.id).exists(), '前提：行确实删了')

    def test_bulk_delete_evicts_only_the_listed_ids(self):
        a = self.make_row(self.owner, 'a.csv', rows=200)
        kept_same_user = self.make_row(self.owner, 'c.csv', rows=400)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)
        keys = self.prime(a, kept_same_user, b)
        billed_others = (self.billed(keys[kept_same_user.id])
                         + self.billed(keys[b.id]))

        resp = self.client.post('/api/v1/files/bulk_delete/',
                                {'ids': [a.id]}, format='json')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['deleted'], 1)
        self.assertNotIn(keys[a.id], self.cache._data, '点名的 id 必须被淘汰')
        self.assertIn(keys[kept_same_user.id], self.cache._data,
                      '同一用户的另一只文件没被点名，条目不得消失')
        self.assertIn(keys[b.id], self.cache._data, '另一个用户的条目不得消失')
        self.assertEqual(self.cache.bytes_cached(), billed_others,
                         '计费只扣了被点名那一条')

    def test_destroy_of_a_batch_row_evicts_only_its_own_path(self):
        """批次行单删：动的是那一只文件，同批次的邻居必须留着（历史上会一起被清）。"""
        a = self.make_row(self.owner, 'a.csv', file_type='batch',
                          batch_name='LOT-G1', rows=200)
        neighbour = self.make_row(self.owner, 'z.csv', file_type='batch',
                                  batch_name='LOT-G1', rows=1000)
        keys = self.prime(a, neighbour)
        billed_neighbour = self.billed(keys[neighbour.id])

        resp = self.client.delete(f'/api/v1/files/{a.id}/')

        self.assertEqual(resp.status_code, 204)
        self.assertNotIn(keys[a.id], self.cache._data)
        self.assertIn(keys[neighbour.id], self.cache._data,
                      '只删批次里的一只文件时，同批次另一只的条目没理由跟着走')
        self.assertEqual(self.cache.bytes_cached(), billed_neighbour)


class MoveScopingTests(_CallSiteBase):
    """combine / uncombine：交出 plans 里的 src 与 target（移动的两端都是「动过的路径」）。"""

    def test_combine_keeps_untouched_users_entry(self):
        a = self.make_row(self.owner, 'a.csv', rows=200)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)
        keys = self.prime(a, b)
        billed_b = self.billed(keys[b.id])

        resp = self.client.post('/api/v1/files/combine/',
                                {'ids': [a.id], 'batch_name': 'LOT-G1'},
                                format='json')

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['combined'], 1)
        self.assert_scoped(keys[a.id], keys[b.id], b, billed_b)
        a.refresh_from_db()
        self.assertEqual(a.file_type, 'batch', '前提：这真的是一次改路径的移动')

    def test_uncombine_keeps_untouched_users_entry(self):
        a = self.make_row(self.owner, 'a.csv', file_type='batch',
                          batch_name='LOT-G1', rows=200)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)
        keys = self.prime(a, b)
        billed_b = self.billed(keys[b.id])

        resp = self.client.post('/api/v1/files/uncombine/',
                                {'ids': [a.id]}, format='json')

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['moved'], 1)
        self.assert_scoped(keys[a.id], keys[b.id], b, billed_b)
        a.refresh_from_db()
        self.assertEqual(a.file_type, 'single', '前提：这真的是一次改路径的移动')

    def test_combine_primes_the_new_path_key_for_the_next_read(self):
        """移动后新 key 不该预先存在，且新路径那一次读要**真的**重解析。

        定点淘汰把 src 与 target 两端都交出去，所以这条同时钉三件事：
        · target 端本来就没有条目 ⇒ 多交一份是无害的（逐出数不会因此虚增）；
        · 旧 key（src 端）确实被逐出 —— 留着就是白占预算的僵尸条目；
        · 新路径那一次读拿到的是**新解析**出来的帧（不是旧条目换了个门牌）。
        新路径由行本身反推（``resolve_file_path(刷新后的 file_path)``），不硬编码目录形状，
        免得判据与被测代码各写各的布局。
        """
        a = self.make_row(self.owner, 'a.csv', rows=200)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)
        keys = self.prime(a, b)
        old_key = keys[a.id]

        resp = self.client.post('/api/v1/files/combine/',
                                {'ids': [a.id], 'batch_name': 'LOT-G1'},
                                format='json')
        self.assertEqual(resp.status_code, 200)

        a.refresh_from_db()
        new_path = resolve_file_path(a.file_path)
        self.assertTrue(os.path.exists(new_path), '前提：文件真的移到了新路径')
        self.assertNotIn(_norm(new_path), {_norm(k[0]) for k in self.cache._data},
                         '移动后新路径在缓存里本来就没有条目')
        self.assertNotIn(old_key, self.cache._data, 'src 端那条必须被逐出')
        self.assertIn(keys[b.id], self.cache._data, '另一端：没动过的 B 照旧留着')

        moved_frame = _frame(rows=400)
        self.parser.add(new_path, moved_frame)
        df = self.read(a)
        self.assertIs(df, moved_frame, '新路径这一次读必须重解析出新的帧')
        self.assertEqual(self.parser.count(new_path), 1,
                         '新路径的解析来自读侧，不是被谁提前塞进去的')


class BatchDirScopingTests(_CallSiteBase):
    """整批 / 子批删除：交出的是**这些行**的路径集合，不是别的用户的。"""

    def test_batch_dir_delete_keeps_other_users_and_other_batches(self):
        doomed = self.make_row(self.owner, 'a.csv', file_type='batch',
                               batch_name='LOT-A', rows=200)
        other_batch = self.make_row(self.owner, 'z.csv', file_type='batch',
                                    batch_name='LOT-B', rows=400)
        b = self.make_row(self.stranger, 'b.csv', file_type='batch',
                          batch_name='LOT-A', rows=1000)
        keys = self.prime(doomed, other_batch, b)
        billed_left = (self.billed(keys[other_batch.id]) + self.billed(keys[b.id]))

        resp = self.client.delete('/api/v1/batch-dirs/LOT-A/')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['deleted_files'], 1, '前提：只删掉了 LOT-A 里主人那一行')
        self.assertNotIn(keys[doomed.id], self.cache._data)
        self.assertIn(keys[other_batch.id], self.cache._data,
                      '同用户的另一个批次不是「动过的路径」')
        self.assertIn(keys[b.id], self.cache._data,
                      '另一个用户的同名批次目录（owner-scoped 删除碰不到它）')
        self.assertEqual(self.cache.bytes_cached(), billed_left)

    def test_sub_batch_delete_keeps_the_sibling_sub_batch(self):
        doomed = self.make_row(self.owner, 'a.csv', file_type='batch',
                               batch_name='LOT-A', sub_batch='SUB-1', rows=200)
        sibling = self.make_row(self.owner, 'z.csv', file_type='batch',
                               batch_name='LOT-A', sub_batch='SUB-2', rows=1000)
        keys = self.prime(doomed, sibling)
        billed_sibling = self.billed(keys[sibling.id])

        resp = self.client.delete('/api/v1/batch-dirs/LOT-A/sub/SUB-1/')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['deleted_files'], 1)
        self.assertNotIn(keys[doomed.id], self.cache._data)
        self.assertIn(keys[sibling.id], self.cache._data,
                      'rmtree 只吃掉 SUB-1 目录，兄弟子批的条目没理由走')
        self.assertEqual(self.cache.bytes_cached(), billed_sibling)


class ConsistencyScopingTests(_CallSiteBase):
    """修复中心两条删除动作：交出「这次真删掉的那些行」的路径。"""

    def test_delete_orphaned_db_keeps_the_live_file_entry(self):
        a = self.make_row(self.admin, 'a.csv', rows=200)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)
        keys = self.prime(a, b)          # 先灌缓存（文件此刻还在盘上）
        billed_b = self.billed(keys[b.id])
        os.remove(resolve_file_path(a.file_path))   # 再让它变成「盘上没了的孤儿」
        self.client.force_authenticate(user=self.admin)   # 删除类动作仅管理员

        resp = self.client.post('/api/v1/consistency-check/',
                                {'action': 'delete_orphaned_db'}, format='json')

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted_count'], 1, '前提：确实删掉了那一行')
        self.assert_scoped(keys[a.id], keys[b.id], b, billed_b)

    def test_delete_orphaned_db_keeps_a_live_row_of_the_same_owner(self):
        """孤儿清理扫的是**这个 owner** 的全部行，但淘汰集合只该有「盘上真没了」的那些。

        与 ``test_delete_orphaned_db_keeps_the_live_file_entry``（钉别的用户）成对照：
        同一用户名下还活着的行才是这条调用点最容易顺手多逐的一档 —— 它和孤儿行同一个
        owner、同一个 ``_user_upload_dir`` 树，只有「文件还在不在」这一列把它们分开。
        """
        doomed = self.make_row(self.admin, 'a.csv', rows=200)
        kept_same_owner = self.make_row(self.admin, 'keep.csv', rows=1000)
        keys = self.prime(doomed, kept_same_owner)
        billed_kept = self.billed(keys[kept_same_owner.id])
        os.remove(resolve_file_path(doomed.file_path))
        self.client.force_authenticate(user=self.admin)

        resp = self.client.post('/api/v1/consistency-check/',
                                {'action': 'delete_orphaned_db'}, format='json')

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted_count'], 1, '前提：只删掉盘上没了的那一行')
        self.assertNotIn(keys[doomed.id], self.cache._data, '孤儿行那条必须被淘汰')
        self.assertIn(keys[kept_same_owner.id], self.cache._data,
                      '同一用户里文件还在的行不是「动过的路径」，条目不得消失')
        self.assertEqual(self.cache.bytes_cached(), billed_kept,
                         '计费只扣孤儿行那一份')
        df = self.read(kept_same_owner)
        self.assertIs(df, self.cache._data[keys[kept_same_owner.id]][0][0],
                      '存活行再读要命中留下的那只帧')
        self.assertEqual(
            self.parser.count(resolve_file_path(kept_same_owner.file_path)), 1,
            '同一用户的存活文件一条都不该被重解析（HEAD 的全清正是把它也打回去了）')

    def test_delete_orphaned_db_with_nothing_orphaned_evicts_nothing(self):
        """删了 0 行 ⇒ 淘汰 0 条，两只计数都得不动。

        这是 G1 存在的理由最纯粹的一档：HEAD 在这个分支上是**无条件** ``clear_parse_cache()``，
        于是「跑了一次一致性检查、什么都没删」也要让全站重解析。
        仓内可复现的反证（不依赖任何日志）：把 ``browse_views._delete_orphaned_db`` 末尾那句
        ``evict_parse_cache_for_paths(deleted_paths)`` 换回 ``clear_parse_cache()`` 再跑本例，
        ``len(self.cache)`` 与 ``clears`` 两条当场红。
        """
        live = self.make_row(self.admin, 'live.csv', rows=200)
        other = self.make_row(self.stranger, 'b.csv', rows=1000)
        keys = self.prime(live, other)
        billed_before = self.cache.bytes_cached()
        stats_before = services.get_parse_cache_stats()
        self.client.force_authenticate(user=self.admin)

        resp = self.client.post('/api/v1/consistency-check/',
                                {'action': 'delete_orphaned_db'}, format='json')

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted_count'], 0, '前提：盘上都在 ⇒ 一行都没删')
        self.assertEqual(self.cache.bytes_cached(), billed_before)
        for key in keys.values():
            self.assertIn(key, self.cache._data, '没删任何行时缓存一条都不能少')
        self.assertEqual(len(self.cache), 2, '缓存长度不得因为一次空操作而变')
        stats_after = services.get_parse_cache_stats()
        self.assertEqual(stats_after['evictions'] - stats_before['evictions'], 0,
                         '「一次淘汰都没做」不许动 evictions 账')
        self.assertEqual(stats_after['clears'] - stats_before['clears'], 0,
                         '也不许动 clears 账（全清会把「什么都没删」读成「全站清空过」）')

    def test_delete_duplicates_keeps_the_canonical_and_other_users(self):
        """重复文件只删「每组非最低 id」，被淘汰集合就该只有那几条。

        两行**同 filename 同 size 但不同目录**（``_group_duplicates`` 就按这两列分组）：
        放同一目录会同名覆盖成一只物理文件，两条 key 塌成一条，判据就无从分辨了。
        """
        kept = self.make_row(self.admin, 'dup.csv', rows=400)
        doomed = self.make_row(self.admin, 'dup.csv', file_type='batch',
                               batch_name='LOT-DUP', rows=400)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)
        self.assertEqual(os.path.getsize(resolve_file_path(kept.file_path)),
                         os.path.getsize(resolve_file_path(doomed.file_path)),
                         '前提：两行真的同 (filename, file_size)，会被归进同一组')
        keys = self.prime(kept, doomed, b)
        billed_left = self.billed(keys[kept.id]) + self.billed(keys[b.id])
        self.client.force_authenticate(user=self.admin)

        resp = self.client.post('/api/v1/consistency-check/',
                                {'action': 'delete_duplicates'}, format='json')

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted_count'], 1, '前提：只删掉每组非最低 id 那条')
        self.assertFalse(DataFile.objects.filter(pk=doomed.id).exists())
        self.assertNotIn(keys[doomed.id], self.cache._data,
                         '被删的重复行必须被淘汰')
        self.assertIn(keys[kept.id], self.cache._data,
                      '同组保留的那一行没被删，条目必须留着')
        self.assertIn(keys[b.id], self.cache._data, '另一个用户的条目不得消失')
        self.assertEqual(self.cache.bytes_cached(), billed_left)


class SharedPhysicalPathTests(_CallSiteBase):
    """「两行指向同一只物理文件」这一档：留下的条目是**正确内容**，不是脏内容。

    键是内容坐标 ``(绝对路径, mtime_ns, 格式)``，``file_id`` 与 ``owner_id`` 都不进键，
    而 ``DataFile.file_path`` 上**没有任何唯一约束**：``apps/datafiles/models.py:31`` 就是一根
    光秃秃的 ``CharField(max_length=512)``（没有 ``unique=``），而 ``DataFile.Meta``（同文件
    57-60 行）只有 ``ordering``/``verbose_name``，既没有 ``constraints`` 也没有
    ``unique_together`` —— 本例下面那次 ``DataFile.objects.create`` 真能落成第二行、
    且两行 ``resolve_file_path`` 逐字相等，就是这条的判据（有约束的话它先 ``IntegrityError``）。
    所以两行指向同一只文件是本仓允许的常规形状：
    ``consolidate_uploads.py`` 的 db_only 分支就在造它（把行改写到**已存在**的同名目标上，
    同 basename、同 owner、同 file_path）。
    ⇒ 「删行后没有任何一行还能解析到那个路径，所以那条条目不可达」这句论证站不住；
    能站住的是两半：① 本类 —— 同坐标还有存活行时，那条条目给的就是它正在读的内容；
    ② ``test_parse_cache_eviction.py::RemovedFileRereadsUnderANewKeyTests`` ——
    文件真被删时 ``_disk_mtime_ns`` 读回 0，下一次读换键、必然 miss。
    """

    def test_two_rows_on_one_physical_file_share_one_correct_entry(self):
        path_row = self.make_row(self.admin, 'shared.csv', rows=200)
        twin = DataFile.objects.create(
            owner=self.admin, filename='shared.csv', file_path=path_row.file_path,
            file_size=path_row.file_size, format_type='CTA8290D',
            file_type='batch', batch_name='LOT-SHARED', status='ready')
        self.assertEqual(resolve_file_path(twin.file_path),
                         resolve_file_path(path_row.file_path),
                         '前提：两行解析到同一只物理文件（没有约束拦它）')

        frame = self.read(path_row)
        self.assertIsNotNone(frame, '前提：owner 那行先读成功并灌进缓存')
        self.assertIs(self.read(twin), frame,
                      '两行共用同一条条目 ⇒ 键里不含 file_id（内容坐标的直接后果）')
        self.assertEqual(len(self.cache), 1, '前提：两行在缓存里塌成一条')
        shared_key = self.key_of(twin)
        self.assertEqual(self.parser.count(resolve_file_path(twin.file_path)), 1,
                         '共用就是一次解析，不是各解析一遍')

        DataFile.objects.filter(pk=path_row.id).delete()   # 只删行、不碰盘：本例测的就是「行没了」

        self.assertIn(shared_key, self.cache._data,
                      '行没了而条目还在 —— 「不可达」就是在这里站不住的')
        self.assertIs(self.read(twin), frame,
                      '存活行命中的仍是同一条条目，而它给的就是这只文件的内容：正确，不是脏')
        self.assertEqual(self.parser.count(resolve_file_path(twin.file_path)), 1,
                         '一次都没重解析：这条条目没有任何「该失效」的东西')
        self.assertEqual(len(self.cache), 1, '条目数不变（没有别的键被顺手带出来）')


class GlobalClearKeptForWholeTreeRewritesTests(_CallSiteBase):
    """管理命令**仍是全站清空**（决定，不是遗漏；同一份理由也写在那两个命令的调用点）。

    为什么这两条不跟进定点淘汰：
    1. 收益≈0：两条都是**成批**改路径（``fix_moved_project_paths`` 扫旧根下的全部行、
       ``consolidate_uploads`` 扫 ``uploads/`` 下的全部行），又跑在带外（人工迁移或启动期），
       此刻没别人的热帧要为这次清理重解析，定点淘汰省不下什么。
    2. 判据成本 > 收益：分支之间「动过」并不同形，逐分支算准集合要读的分支比上面各条多 ——
       ``fix_moved``：重写分支把行换到新 path（旧 key **通常**就此没人指向它，但那不是结构
       保证：``file_path`` 上没有唯一约束，同一坐标可以有别的行还在读，见
       ``SharedPhysicalPathTests``）、target-missing 分支**行与盘都不动**、
       unchanged 分支压根没进 update；``consolidate``：moved 同时动盘与行、db_only 只改行
       不动盘（它正是「两行共享同一只物理文件」的制造者）、conflicts 里**只有尺寸不符**那条
       什么都不改（复制校验失败那条已经 ``copy2`` 出 target 再 ``os.remove`` 删掉，
       净效果为零但确实动过盘）。定点淘汰算漏的那条只是「白占预算的条目」
       （同 ``SharedPhysicalPathTests``：不脏，但只有人 review 才看得准），
       全清一次兜住全部分支，代价只是下一次读重解析，而带外几乎没人付这个代价。
    ⇒ 所以判据形状与上面各条**相反**：动过的与没动过的**一起**消失。
      可复现的反证（不依赖任何 log）：把命令里那句 ``clear_parse_cache()`` 换成任意
      定点淘汰（哪怕交出去的是空集合），那条**没动过的 B** 就会留在缓存里 ⇒
      本类的 ``assertEqual(len(self.cache), 0)`` 当场红。
    """

    def test_fix_moved_project_paths_still_clears_untouched_entries(self):
        old_root = os.path.join(self.media_root, 'OldProject')
        new_root = os.path.join(self.media_root, 'NewProject')
        old_uploads = os.path.join(old_root, 'media', 'uploads')
        new_uploads = os.path.join(new_root, 'media', 'uploads')
        a = self.make_legacy_abs_row(
            self.owner, os.path.join(old_uploads, 'moved.csv'), 'moved.csv', rows=200)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)   # 命令根本不扫这棵树
        keys = self.prime(a, b)
        # 命令要求 target 在盘上存在才改行（否则 skip，也就不会触发清空）
        os.makedirs(new_uploads, exist_ok=True)
        with open(os.path.join(new_uploads, 'moved.csv'), 'w', encoding='utf-8') as f:
            f.write('[Data]\ncol1,col2\nu1,u2\n1,2\n2,1\n1,2\n')

        out = StringIO()
        call_command('fix_moved_project_paths',
                     '--old-root', old_root, '--new-root', new_root, stdout=out)

        self.assertIn('rewrote 1', out.getvalue(), '前提：这一行真的被重写了')
        a.refresh_from_db()
        self.assertEqual(_norm(a.file_path), _norm(os.path.join(new_uploads, 'moved.csv')))
        self.assertEqual(len(self.cache), 0,
                         '整体改路径的管理命令仍走全站清空（连没动过的 B 一起清）')
        self.assertEqual(self.cache.bytes_cached(), 0)

    def test_consolidate_uploads_still_clears_untouched_entries(self):
        uploads = os.path.join(self.media_root, 'uploads')
        a = self.make_legacy_abs_row(
            self.owner, os.path.join(uploads, 'legacy.csv'), 'legacy.csv', rows=200)
        b = self.make_row(self.stranger, 'b.csv', rows=1000)   # 不在 uploads/ 之下
        keys = self.prime(a, b)

        out = StringIO()
        call_command('consolidate_uploads', stdout=out)

        a.refresh_from_db()
        self.assertEqual(a.file_path,
                         os.path.join('data', 'g1_owner', 'single', 'legacy.csv'),
                         '前提：这一行确实被迁移并重写')
        self.assertNotIn(keys[a.id], self.cache._data)
        self.assertNotIn(keys[b.id], self.cache._data,
                         '没动过的 B 也被清掉 —— 全站清空这条语义在这里保留（判据反向：'
                         '改成定点淘汰就红）')
        self.assertEqual(len(self.cache), 0)
        self.assertEqual(self.cache.bytes_cached(), 0)
