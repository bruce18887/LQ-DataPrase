"""T1：定点淘汰与**在途发布 / 全站清空**这几条路的交错（2026-10-28 波次 G1）。

从 `test_parse_cache_eviction.py` 拆出来是因为那份越过 600 行闸（判据一条没缩、理由一句
没删，只是换个文件放；两层判据共用 `parse_cache_eviction_fixtures.py` 里同一套道具）。
本文件钉原表的 ③④⑤ 三层：

③ 定点淘汰与单飞发布的交错（**收不回在途发布 / 原子 / 不丢唤醒**）——承重判据。
   真正的结论是「定点淘汰不比全清弱」：两条方向相反的交错各钉一半，而全清自己也收不回
   在途那条发布（第 2 例钉这件既有事实）。
④ ``_cached_fail_data``（``functools.lru_cache``）**不**随定点淘汰清理 —— 设计决定而不是
   遗漏：lru_cache 没有按谓词丢弃的 API，而它的 key 同样带内容坐标，两半论证对它照样成立。
⑤ 全站清空那条路没被削弱：``clear_parse_cache()`` 仍一次清掉两只缓存，且 MemoryError
   分支走的是**真**清空（不是 mock）；管理命令那两条「仍然全清」的反向判据在
   ``test_parse_cache_scoped_invalidation.py::GlobalClearKeptForWholeTreeRewritesTests``。

「淘汰语义本体」（① ``evict_keys`` 的计费与谓词、② 路径 API 的归一化与淘汰半径、
⑥ 删盘之后换键）在 `test_parse_cache_eviction.py`；八个调用点（「八个」这个数目与它们的
归属文件由 `test_parse_cache_invariant_scan.py::EvictCallSiteScanTests` 钉着，不是靠数）
交出去的集合是否只覆盖它们真动过的那些路径，在 `test_parse_cache_scoped_invalidation.py`。
"""
import threading
from unittest import mock

from apps.datafiles import services

from test.backend.parse_cache_eviction_fixtures import (
    _CacheSwapBase,
    _frame,
    _Gate,
    _tmp_path,
    _value,
)


class EvictionVsPublishInterleaveTests(_CacheSwapBase):
    """③ 定点淘汰与单飞发布的交错（承重判据）。

    要钉的东西有两面，方向相反：
    - **收不回**：已经开始算的那条，发布发生在淘汰之后 —— 淘汰挡不住它。
      ``clear()`` 同样挡不住（第 2 例钉这条既有事实），所以定点淘汰**没有**比全清更弱；
      这一层真正防脏的是键的内容坐标（见 ``_disk_mtime_ns`` 的 docstring）。
    - **原子**：顺序反过来就是「整条消失」（第 3 例）。两段各一次持锁、发布段把
      「写条目 + 放开 pending + notify」收在同一次持锁里 ⇒ 淘汰不可能看到半发布状态。
    - **不丢唤醒**：唤醒只来自那三处 ``notify_all``（发布段 / 异常释放段 / ``put`` 写透；
      「三处」的位置与数目由 `test_parse_cache_invariant_scan.py::NotifyAllSourceScanTests`
      钉着），``evict_keys`` 既不在其列也不碰 ``_pending``，所以它跑在中间也不会把挂在
      同 key 上的等待者丢下（第 4 例）。
    """

    def tearDown(self):
        # 编排失败时把 owner 放出去，别让下一个用例等 10s 超时才看清红在哪
        for gate in getattr(self, '_gates', []):
            gate.release.set()

    def _new_gate(self, value):
        gate = _Gate(value)
        self._gates = getattr(self, '_gates', [])
        self._gates.append(gate)
        return gate

    def test_evict_before_publish_cannot_retract_the_later_store(self):
        key = ('/proj/g1/inflight.csv', 1, 'CTA8290D')
        gate = self._new_gate(_value(_frame()))
        out = {}

        t = threading.Thread(target=lambda: out.setdefault(
            'r', self.cache.get_or_compute(key, gate.compute)))
        t.start()
        self.assertTrue(gate.entered.wait(5), '前提：owner 已经进入 compute')

        self.assertEqual(self.cache.evict_keys(lambda k: k == key), 0,
                         '还在算的时候条目没进缓存，逐出数为 0')

        gate.release.set()
        t.join(timeout=10)
        self.assertFalse(t.is_alive())
        self.assertIn(key, self.cache._data,
                      '发布发生在淘汰之后：条目照旧留下（淘汰收不回在途发布）')
        self.assertEqual(services.get_parse_cache_stats()['in_flight'], 0,
                         '收尾必须把 pending 放干净')

    def test_clear_also_cannot_retract_an_inflight_publish(self):
        """上一例的论据不是新说的：``clear()`` 一直如此 —— 全清不比定点更「安全」。"""
        key = ('/proj/g1/inflight-clear.csv', 1, 'CTA8290D')
        gate = self._new_gate(_value(_frame()))

        t = threading.Thread(target=lambda: self.cache.get_or_compute(
            key, gate.compute))
        t.start()
        self.assertTrue(gate.entered.wait(5), '前提：owner 已经进入 compute')
        services.clear_parse_cache()
        gate.release.set()
        t.join(timeout=10)

        self.assertFalse(t.is_alive())
        self.assertIn(key, self.cache._data,
                      '在途发布同样躲得过全清 —— 这条既有性质不是本刀引入的窗口')

    def test_evict_after_publish_removes_the_stored_entry(self):
        """第 1 例的镜像：顺序反过来就是「整条消失」，两例合起来才叫原子。"""
        key = ('/proj/g1/published.csv', 1, 'CTA8290D')
        self.cache.get_or_compute(key, lambda: _value(_frame()))
        self.assertIn(key, self.cache._data)

        self.assertEqual(self.cache.evict_keys(lambda k: k == key), 1)
        self.assertNotIn(key, self.cache._data)
        self.assertEqual(self.cache.bytes_cached(), 0)

    def test_parked_waiter_is_still_woken_when_eviction_runs(self):
        """唤醒只来自那三处 ``notify_all``（发布段 / 异常释放段 / ``put`` 写透），定点淘汰
        不在其列：中间插一次淘汰，等待者照样拿到同一只值（既不丢唤醒，也不因 pending 被清
        而多算一遍）。"""
        key = ('/proj/g1/waiter.csv', 1, 'CTA8290D')
        value = _value(_frame())
        gate = self._new_gate(value)
        results = {}

        owner = threading.Thread(target=lambda: results.update(
            o=self.cache.get_or_compute(key, gate.compute)))
        owner.start()
        self.assertTrue(gate.entered.wait(5), '前提：owner 已经进入 compute')
        waiter = threading.Thread(target=lambda: results.update(
            w=self.cache.get_or_compute(key, lambda: _value(_frame(rows=900)))))
        waiter.start()
        waiter.join(timeout=0.2)
        self.assertTrue(waiter.is_alive(), '前提：waiter 确实挂在同 key 上等发布')
        self.assertEqual(services.get_parse_cache_stats()['in_flight'], 1)

        self.cache.evict_keys(lambda k: k == key)   # 此刻什么都没有，但必须不破坏 pending
        self.assertEqual(services.get_parse_cache_stats()['in_flight'], 1,
                         '定点淘汰不碰 _pending：owner 仍挂在在途集合里 '
                         '（清了它，第三个线程会判定「没人算」而多解析一遍 —— A4 那个洞）')
        self.assertIn(key, list(self.cache._pending), '同上，直接看 pending 集合')
        gate.release.set()
        owner.join(timeout=10)
        waiter.join(timeout=10)

        self.assertFalse(owner.is_alive() or waiter.is_alive(), '谁都不许死等')
        self.assertIs(results['o'][0], results['w'][0],
                      '单飞承诺不变：waiter 复用 owner 的那只帧')
        self.assertEqual(services.get_parse_cache_stats()['in_flight'], 0)


class FailDataCacheIsNotPathScopedTests(_CacheSwapBase):
    """④ 设计决定：定点淘汰**不**顺手 ``cache_clear()`` 那只 ``_cached_fail_data``。

    ``functools.lru_cache`` 没有按谓词丢弃的 API，而它的 key 里同样带
    ``(file_id, owner_id, mtime_ns, 绝对路径, 格式)`` ⇒ ⑥ 那两半对它同样成立：还在按这组
    坐标读它的行拿到的是**同一份内容**的检测结果（不脏），文件真被删则 ``mtime_ns`` 读回 0、
    下一次组出的 key 不再是它 ⇒ 留着的代价只有 ``maxsize=32`` 之内的内存。
    本例钉的是「没把定点淘汰写成又一次全清」。
    """

    def setUp(self):
        super().setUp()
        fail_cache = services._cached_fail_data
        self.addCleanup(fail_cache.cache_clear)
        fail_cache.cache_clear()

    def test_path_eviction_leaves_fail_data_cache_entries_in_place(self):
        frame = _frame()
        path = _tmp_path('g1-faildata.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('a,b\n1,2\n')
        # 先把整条链走一遍：帧缓存命中（已 prime）→ 失败检测真算一次并挂进 lru_cache
        self.prime(path, frame, mtime=5)
        services._cached_fail_data(1, 1, 5, path, 'CTA8290D')
        before = services._cached_fail_data.cache_info().currsize
        self.assertGreaterEqual(before, 1, '前提：整文件失败检测已占过位')

        self.assertEqual(services.evict_parse_cache_for_paths([path]), 1)

        self.assertEqual(services._cached_fail_data.cache_info().currsize, before,
                         '定点淘汰不得把那只 lru_cache 一把清空')
        self.assertEqual(len(self.cache), 0, '而帧缓存那一条确实走了')


class GlobalClearStillClearsEverythingTests(_CacheSwapBase):
    """⑤ 全站清空那条路没被削弱（MemoryError 分支走真清空，不是 mock）。"""

    def setUp(self):
        super().setUp()
        fail_cache = services._cached_fail_data
        self.addCleanup(fail_cache.cache_clear)
        fail_cache.cache_clear()

    def test_clear_parse_cache_drops_both_caches(self):
        frame = _frame()
        path = _tmp_path('g1-clearall.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('a,b\n1,2\n')
        self.prime(path, frame)
        self.prime(_tmp_path('g1-other.csv'), frame)
        services._cached_fail_data(2, 1, 9, path, 'CTA8290D')
        self.assertEqual(len(self.cache), 2)
        self.assertGreaterEqual(services._cached_fail_data.cache_info().currsize, 1)

        services.clear_parse_cache()

        self.assertEqual(len(self.cache), 0)
        self.assertEqual(self.cache.bytes_cached(), 0)
        self.assertEqual(services._cached_fail_data.cache_info().currsize, 0,
                         '全清仍然一并清掉 _cached_fail_data（与今天逐字一致）')

    def test_memory_error_handler_clears_every_path_not_just_the_offending_one(self):
        """内存压力下没有「哪些路径安全」这回事：一条都不留。"""
        from apps.common.exceptions import custom_exception_handler

        frame = _frame()
        keys = [self.prime(f'/proj/g1/mem{i}.csv', frame, mtime=i) for i in (1, 2, 3)]
        self.assertEqual(len(self.cache), 3)

        with mock.patch('apps.common.memory.record_oom'), \
                self.assertLogs('apps.common.exceptions', level='ERROR'):
            response = custom_exception_handler(MemoryError('boom'), {'request': None})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(self.cache), 0, 'MemoryError 分支必须仍是全清')
        self.assertEqual(self.cache.bytes_cached(), 0)
        self.assertTrue(all(k not in self.cache._data for k in keys))
        self.assertEqual(services.get_parse_cache_stats()['clears'], 1)
