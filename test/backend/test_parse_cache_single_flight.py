"""T1: 解析缓存单飞的**发布顺序**竞态（2026-10-28，本批次 A4 把它放大）。

根因（取证见 `tasks/perf-review-2026-10-27/A4-flake-probe-1.log` 与
`A4-affected.log:608`，不是猜的）：``_BytesLRUCache.get_or_compute`` 旧写法在
`compute()` 结束后，**锁内**先 ``_pending.discard(key)`` + ``notify_all()``，
却把发布 ``_store``（连 ``size_of(value)`` 的求值）留在**出锁之后**。
等待者被唤醒后重新拿锁时：条目还没进 ``_data``、key 已不在 ``_pending``
⇒ 它判定「没人正在算」，自己再算一遍。「每文件只算一次」这条承诺因此在并发下不成立。

A4 的放大是量级而非性质：``_parse_value_bytes`` 里新增了 ``_column_profile_bytes``，
合成夹具 2000×6 实测 0.294ms → 0.566ms，锁外窗口翻倍 ⇒
``apps.datafiles.tests_parse_cache.BytesLRUCacheTests`` 整类 12 轮连跑从红 2 次升到红 10 次
（红项逐字：``AssertionError: 2 != 1 : 两个 owner 并发 miss 应共用一次解析，实际 2 次``）。

本文件的判据**一律不靠 sleep 赌时序**，两种确定性编排各有分工（编排本身是前置，不是判据）：
★ 慢 ``size_of``（注入 0.2s）+ ``computed`` Event：把「compute 已结束、条目还没落缓存」
  这段窗口撑开，让后进者**确定性地**落在窗口里 —— ① 用它；
★ gate（owner 停在 compute 里）+ 记录 ``_cv.wait()`` 的 Condition：把「等待者真的在等」
  钉成事实 —— ③④⑤ 共用它（见 ``run_pair``；它那两个 ``assertTrue``/``is_alive`` 断言
  就是「编排成立」与「被测代码有问题」的分界线）。⑨ 用同族编排 ``put_wakes_parked_waiters``
  （同一只记录 Condition，只是把「唤醒来源」从 owner 的 notify 换成写透 ``put``）。

九条判据的编号与各 method/class docstring 前的序号对应（改实现前先对这张表，别照记忆写注释）。
各号**不要求逐一各占一个用例**：② 无独立用例（其可信性由 ``run_pair`` 承担），⑨ 由 ⑨a/⑨b 两例分担：
① 发布顺序本体（缺陷本体）：被判据钉住的**只是**一条不变量——唤醒后重新拿锁时不得出现
   「条目还没进 ``_data``、key 已离开 ``_pending``」的空窗。旧写法把发布整个留在锁外 ⇒
   撞上这个空窗，等待者判定「没人算」再算一遍。当前实现把「写条目 + 放开 pending + notify」收进
   一次加锁段、先条目后 pending，但**「同一次持锁」与「先条目后 notify」的步序本身不是判据**：
   实测「拆两次持锁但仍先 store 再 discard+notify」与「锁内先 notify 后 store」两种重排都仍绿，
   只有留下上面那个空窗（先 discard+notify、隔一段才 store）才转红（①⑥ 的变异账）。
② 编排的可信性由 ``run_pair`` 承担（见上 ★），本文件没有独立的 ② 号用例。
③ 异常路径：compute 抛错也要放开 pending 并 notify（失败不永久化、waiter 不死等）。
④ ``store_if`` 判 False：失败值不占位，但**仍然**必须 notify。③④ 是修发布顺序时最容易
   顺手丢掉的两条；既有 ``test_failed_parse_is_not_stuck_as_pending`` 只覆盖了 ③ 的
   「不卡死」，覆盖不到「拒绝发布也要唤醒」。
⑤ 发布段（``size_of``/``store_if``）自身抛错时也要走同一条释放路径。
⑥ 接线证明：真实链路 ``_cached_parse`` + 假 parser，两个 owner 同一内容坐标只解析一次。
   它把 publish 侧的 ``_frame_bytes`` 钉在 gate 上 —— **旧写法与新写法都是在锁外调它**
   （旧写法调完才 notify、新写法在 notify 之前把它调完），所以这条钉的**不是**锁内/锁外，
   而是「owner 还在这段窗口里时 ``key`` 必须仍挂在 ``_pending`` 上」：撞上 pending 的 waiter
   只会阻塞等结果，判定「没人算」的 waiter 才会多解析一次。
⑦ 发布段的**持锁窗口**内不得执行 ``size_of``/``store_if``（get 侧）：两者都是 value 的纯函数、
   不读共享状态 ⇒ 求值留锁外。而 ``_cv`` 是全站解析缓存的**读锁**——任何线程查任何 key 的
   命中都要拿它，于是「一个文件解析完」会阻塞「所有文件的首屏命中查询」（``_parse_value_bytes``
   在 1702 列那档是几十毫秒量级，不是 0.5ms）。判据取**次序**（命中探测必须早于当口那段慢钩子
   返回），不取绝对墙钟；实测毫秒数打到 stderr（量级与红账见 ``tasks/perf-review-2026-10-27/A4d-*.log``）。
⑧ 同一记次序判据打在**写透侧** ``put``：⑦ 播种 hot_key 用的是常量体积，恰好遮住 ``put`` 自己
   锁内求值的耗时 ⇒ 只测 get_or_compute 会漏掉写透路径，这条单独钉它。注意 ⑦⑧ 钉的是「体积量在
   锁内还是锁外」这半句，**撞不到**「put 写完忘了 notify」——后者由 ⑨ 单独承重。
⑨ 写透 ``put`` 的 ``notify_all`` 承重（复审补的缺口）：owner 卡在 compute（绝不 notify）时把
   waiter 真挂在同 key 的 ``_cv.wait()`` 上，再由 ``put`` 发布同 key 的值；断言 waiter 被 ``put``
   唤醒、拿到 put 那只值、pending 收尾归零。「put 不 notify」这条内存变异下 ⑨ 必红（其余全绿）。
   ⑨a 单 waiter（复审描述的形状）；⑨b 两 waiter，把「``notify_all`` 而非单个 ``notify``」也钉上。
"""
import os
import sys
import tempfile
import threading
import time
from unittest import mock

import pandas as pd
from django.test import SimpleTestCase

from apps.datafiles import services
from apps.datafiles import parse_cache_sizing

_WINDOW_SECONDS = 0.2   # 注入的慢 size_of/store_if：把「纯计算正在跑」这段窗口撑开（判据不靠它赌时序）
# 命中路径的时长上限**随注入窗口自缩放**（不是裸常数：CI 满载 / GC 抖动下裸 0.05 会假红）。
# 它只是兜住「探测自己跑飞」的次级判据，⑦⑧ 的承重判据是**次序**（探测早于慢钩子返回）。
_HIT_BUDGET_SECONDS = _WINDOW_SECONDS / 4
_TIMEOUT = 10           # join / Event 等待的上限：只用来把「死等」变成红，不用来放慢正常路径


class _WaitRecordingCondition(threading.Condition):
    """记录「确实有线程进到 ``_cv.wait()``」的 Condition。

    ``_BytesLRUCache`` 只在「别的线程正在算」这条分支上 ``wait()``，所以本事件被置位
    就等于证明等待者真的挂起了 —— 后续它能否醒来才由被测代码的 notify 决定。
    默认锁仍是 RLock（与生产实现同构：锁内的发布段会重入 ``_store_locked``）。

    ``park_target``（默认 1）给 ⑨ 用：``waiter_seen`` 只记「有没有人进来等」，而写透要钉的是
    「第 N 个 waiter 也都确实挂上了」，故另记 ``parked`` 计数、达到目标才置 ``all_parked``。
    ③④⑤ 走的 ``run_pair`` 仍只看 ``waiter_seen``，取默认 1 时两事件同时置位，行为不变。
    """

    def __init__(self, park_target=1):
        super().__init__()
        self.waiter_seen = threading.Event()
        self.park_target = park_target
        self.parked = 0
        self.all_parked = threading.Event()

    def wait(self, timeout=None):
        self.parked += 1
        self.waiter_seen.set()
        if self.parked >= self.park_target:
            self.all_parked.set()
        return super().wait(timeout)


class _SingleFlightBase(SimpleTestCase):
    """直接打 ``_BytesLRUCache``：不碰 DB，也不依赖真实解析器。"""

    def new_cache(self, budget_bytes=64 * 1024 * 1024):
        cache = services._BytesLRUCache(budget_bytes)
        cache._cv = _WaitRecordingCondition()
        return cache

    def pending_count(self, cache):
        with cache._cv:
            return len(cache._pending)

    def run_pair(self, cache, key, first_compute, second_compute, **kwargs):
        """两个线程按「owner 先在 compute 里停住、waiter 确已在等」的次序发起。

        次序由 Event 定死：``release`` 只在 ``waiter_seen`` 置位后才放开，
        因此 waiter 一定走过 ``_cv.wait()``；返回 ``(结果表, 计数表)``。
        """
        entered = threading.Event()
        release = threading.Event()
        calls = []
        box = {}

        def make_compute(which):
            def compute():
                calls.append(which)
                entered.set()
                release.wait(_TIMEOUT)
                return first_compute() if which == 'owner' else second_compute()
            return compute

        def worker(name):
            try:
                box[name] = cache.get_or_compute(key, make_compute(name), **kwargs)
            except BaseException as exc:      # noqa: BLE001 - 异常本身就是要观察的结果
                box[name] = exc

        owner = threading.Thread(target=worker, args=('owner',))
        owner.start()
        self.assertTrue(entered.wait(_TIMEOUT), 'owner 没能进入 compute（前置失效）')
        waiter = threading.Thread(target=worker, args=('waiter',))
        waiter.start()
        # 放开之前先确认 waiter 真的挂在 _cv.wait() 上：这条 assertTrue 就是
        # 「异常/拒绝路径必须 notify」能被判红的前提。
        self.assertTrue(cache._cv.waiter_seen.wait(_TIMEOUT),
                        'waiter 没有进入等待分支（编排失效，不是被测代码的问题）')
        release.set()
        owner.join(_TIMEOUT)
        waiter.join(_TIMEOUT)
        self.assertFalse(owner.is_alive(), 'owner 线程未结束（被自己钉住的位置卡死）')
        self.assertFalse(waiter.is_alive(), 'waiter 被唤醒失败：notify 丢了 ⇒ 死等')
        return box, {'calls': calls}

    def put_wakes_parked_waiters(self, cache, key, published, n_waiters):
        """⑨ 的共用编排（``run_pair`` 同族，唤醒来源换成写透 ``put``）：owner 卡在 ``compute``
        里绝不放开 ⇒ 它绝不 notify，叫醒挂在同 key ``_cv.wait()`` 上 waiter 的唯一来源就是随后那句
        ``put``。判据是 happens-before（waiter 是否在放开 owner **之前**被 ``put`` 叫醒、拿到 ``put``
        那只值），不靠 sleep 赌时序。
        """
        cache._cv.park_target = n_waiters      # all_parked 只在第 n 个 waiter 进来时置位
        owner_entered, owner_gate = threading.Event(), threading.Event()  # owner 停在 gate，收尾才放
        waiter_calls, box, woke_ms = [], {}, {}
        t0 = time.perf_counter()

        def hung_compute():
            owner_entered.set()
            owner_gate.wait(_TIMEOUT)
            return ('owner-frame', {'format': 'CTA8290D'}, 'CTA8290D')

        def waiter_compute():
            waiter_calls.append(1)
            return ('waiter-frame', {'format': 'CTA8290D'}, 'CTA8290D')

        owner = threading.Thread(target=lambda: box.__setitem__(
            'owner', cache.get_or_compute(key, hung_compute)))
        owner.start()
        self.assertTrue(owner_entered.wait(_TIMEOUT), 'owner 没进入 compute（前置失效）')
        waiters = [threading.Thread(target=lambda i=i: box.__setitem__(
            'w%d' % i, cache.get_or_compute(key, waiter_compute))) for i in range(n_waiters)]
        for th in waiters:
            th.start()
        # 放开之前先钉死「n_waiters 个 waiter 都真挂进 _cv.wait()」——「put 丢 notify 会被判红」的前提。
        self.assertTrue(cache._cv.all_parked.wait(_TIMEOUT),
                        '不足 %d 个 waiter 进入 _cv.wait()（编排失效，不是被测代码的问题）' % n_waiters)
        cache.put(key, published, size_of=lambda _v: 128)   # owner 仍卡在 compute：唯一唤醒来源是这句
        try:
            for i, th in enumerate(waiters):
                th.join(_TIMEOUT)
                woke_ms[i] = (time.perf_counter() - t0) * 1000
                self.assertFalse(th.is_alive(),
                                 'w%d 没被 put 唤醒：put 丢了 notify_all ⇒ 死等、写透白做' % i)
        finally:
            owner_gate.set()                     # 收尾：放 owner 走完整条发布（覆盖 pending 归零）
            owner.join(_TIMEOUT)
        for i in range(n_waiters):
            self.assertIs(box['w%d' % i], published, 'w%d 必须拿到 put 发布的那只值（不是自己再算的）' % i)
        self.assertEqual(waiter_calls, [], 'waiter 命中了 put 发布的条目 ⇒ 不该再 compute')
        self.assertFalse(owner.is_alive(), 'owner 收尾失败（把自己钉在 compute 里了）')
        self.assertEqual(self.pending_count(cache), 0, '结束后 pending 必须清空')
        self.assertEqual(len(cache), 1, '同 key 只该有一条')
        print('[A4e] ⑨ put 唤醒 %d 个 waiter：唤醒耗时 %s'
              % (n_waiters, ', '.join('w%d=%.1fms' % (i, woke_ms[i]) for i in range(n_waiters))),
              file=sys.stderr, flush=True)


class PublishOrderTests(_SingleFlightBase):
    """承重：compute 结束后、条目落缓存之前的那段窗口必须不存在。"""

    def test_waiter_arriving_right_after_compute_reuses_the_published_value(self):
        """① 确定性复现：旧写法这里必红（compute 跑 2 次），修完转绿。

        钉的是**哪条不变量**（复审口径）：唤醒后重新拿锁时不得出现「条目还没进 ``_data``、key 已离开
        ``_pending``」的空窗；**不**钉「同一次加锁段」也**不**钉「先条目后 notify」的步序（拆两次持锁、
        锁内先 notify 后 store 都仍绿）。编排：``size_of`` 注入成慢函数（0.2s），旧写法里它在**锁外**求值，
        于是「已放开 pending + 已 notify、条目未落」这段窗口被撑到肉眼可进；waiter 在 owner 的 compute
        结束后（``computed`` Event 为准）才发起，落进窗口的概率不依赖调度运气。
        """
        cache = self.new_cache()
        key = ('/tmp/single-flight-publish.csv', 1, 'CTA8290D')
        value = ('sentinel-frame', {'format': 'CTA8290D'}, 'CTA8290D')
        computed = threading.Event()
        compute_calls, size_calls = [], []

        def compute():
            time.sleep(0.05)          # 让「两个 owner 并发 miss」的形状贴近真实解析
            compute_calls.append(1)
            computed.set()            # compute 已结束：此刻起进入被测的发布阶段
            return value

        def slow_size_of(_ignored):
            size_calls.append(1)
            time.sleep(_WINDOW_SECONDS)   # 旧写法停在这 0.2s：全程在锁外
            return 128

        def worker(name, box):
            box[name] = cache.get_or_compute(key, compute, size_of=slow_size_of)

        box = {}
        t1 = threading.Thread(target=worker, args=('a', box))
        t1.start()
        self.assertTrue(computed.wait(_TIMEOUT), 'owner 没有开始 compute（前置失效）')
        t2 = threading.Thread(target=worker, args=('b', box))
        t2.start()
        t1.join(_TIMEOUT)
        t2.join(_TIMEOUT)
        self.assertFalse(t1.is_alive() or t2.is_alive(), '有线程没结束')

        self.assertEqual(len(compute_calls), 1,
                         f'两个 owner 并发 miss 应共用一次 compute，实际 {len(compute_calls)} 次'
                         '（发布落在锁外 ⇒ 等待者醒来时既无条目也无 pending，只能自己再算）')
        self.assertEqual(len(size_calls), 1, '发布只该发生一次')
        self.assertIs(box['a'], box['b'], '两个调用方必须拿到同一个对象')
        self.assertEqual(self.pending_count(cache), 0, '结束后 pending 必须清空')
        self.assertEqual(len(cache), 1, '缓存里只该有一条')


class PublishLockWindowTests(_SingleFlightBase):
    """承重（⑦⑧）：发布段与写透段的**持锁窗口**只含「写条目 + 放开 pending + notify」。

    两条的判据都是**次序**而非绝对墙钟：慢钩子返回的那一刻单独记时间戳，命中探测必须
    早于它结束。阻塞形状（钩子在锁内）下探测只能等锁释放，而锁必然在钩子返回之后才放
    ⇒ 变异照样转红，且不受 CI 满载 / GC 抖动摆布（时长上限只作次级兜底，取窗口/4）。
    """

    def test_hit_path_is_not_blocked_by_the_publishing_size_of(self):
        """⑦ 慢 ``size_of``/``store_if`` 正在跑的当口，另一线程命中**另一个 key** 不许等它。

        两者都是 value 的纯函数、不读共享状态 ⇒ 求值留锁外；上一版把它们一起搬进了锁内，
        于是这一段探测必然排到注入窗口跑满（红账见 ``A4d-mutation-red.log`` 的 G1/G2：
        G1 只搬 ``size_of`` ⇒ 红在第二段，G2 两段都搬 ⇒ 红在第一段）。
        两条钩子谁先求值是实现内部的短路次序（⑦ 不钉它，实现改了这里也不该假红），
        所以按「先进入的那一段」探测、「再进入的那一段」再探测，不写死先后。
        """
        cache = self.new_cache()
        hot_key = ('/tmp/single-flight-hot-hit.csv', 1, 'CTA8290D')
        cold_key = ('/tmp/single-flight-cold-publish.csv', 1, 'CTA8290D')
        hot_value = ('hot-frame', {'format': 'CTA8290D'}, 'CTA8290D')
        cold_value = ('cold-frame', {'format': 'CTA8290D'}, 'CTA8290D')
        cache.put(hot_key, hot_value, size_of=lambda _v: 64)

        order, entered, done_at, entry_at = [], [threading.Event(), threading.Event()], {}, {}
        size_calls, store_if_calls, compute_calls, miss_computes = [], [], [], []

        def slow(name, ret, counter):
            def fn(_ignored):
                counter.append(1)
                order.append(name)
                entry_at[name] = time.perf_counter()   # 进入时刻（探测的相对基准）
                entered[len(order) - 1].set()          # 只有 owner 线程顺序进来，无竞争
                time.sleep(_WINDOW_SECONDS)            # 注入的慢钩子：本条判它是否持锁
                done_at[name] = time.perf_counter()    # 返回时刻：探测必须早于它
                return ret
            return fn

        def compute():
            compute_calls.append(1)
            return cold_value

        def probe(hook, stage):
            """命中 hot_key（与正在发布的 cold key 无关），回报读到的值与结束时刻。"""
            start = time.perf_counter()
            value = cache.get_or_compute(hot_key, lambda: miss_computes.append(1))
            finish = time.perf_counter()
            print(f'[A4d] {stage}（{hook}）期间的命中耗时 {(finish - start) * 1000:6.1f} ms'
                  f' / 距钩子进入 {(finish - entry_at[hook]) * 1000:6.1f} ms'
                  f'（注入窗口 {_WINDOW_SECONDS * 1000:.0f} ms / 自缩放上限'
                  f' {_HIT_BUDGET_SECONDS * 1000:.0f} ms）', file=sys.stderr, flush=True)
            return value, finish

        box = {}

        def owner_call():
            box['owner'] = cache.get_or_compute(
                cold_key, compute,
                size_of=slow('size_of', 128, size_calls),
                store_if=slow('store_if', True, store_if_calls))

        owner = threading.Thread(target=owner_call)
        owner.start()

        self.assertTrue(entered[0].wait(_TIMEOUT), 'owner 没进入任何慢钩子（前置失效）')
        first = order[0]
        value_first, finish_first = probe(first, '第一段')
        self.assertTrue(entered[1].wait(_TIMEOUT), 'owner 没进入第二个慢钩子（前置失效）')
        second = order[1]
        value_second, finish_second = probe(second, '第二段')

        owner.join(_TIMEOUT)
        self.assertFalse(owner.is_alive(), 'owner 未结束（发布段把自己钉住了）')

        self.assertIs(value_first, hot_value, '探测读到的就是那条已存在条目')
        self.assertIs(value_second, hot_value)
        self.assertEqual(miss_computes, [], '前置：两次探测走的都是命中分支，不是又算一遍')
        self.assertEqual(sorted(order), ['size_of', 'store_if'], '两段慢钩子都要被走到')
        for stage, hook, finish in (('第一段', first, finish_first),
                                    ('第二段', second, finish_second)):
            hit_first = finish < done_at[hook]
            print(f'[A4d] {stage}（{hook}）次序账：命中结束于钩子进入后'
                  f' {(finish - entry_at[hook]) * 1000:6.1f} ms，'
                  f'该钩子返回于 {(done_at[hook] - entry_at[hook]) * 1000:6.1f} ms'
                  f' ⇒ 命中{"早于" if hit_first else "晚于"}钩子返回',
                  file=sys.stderr, flush=True)
            # ★承重：命中在当口那段慢钩子**返回之前**就结束了 ⇒ 它没被那段持锁挡住。
            self.assertLess(finish, done_at[hook],
                            f'发布段持锁期间仍在执行 {hook}：{stage}的命中结束于钩子进入后'
                            f' {(finish - entry_at[hook]) * 1000:6.1f} ms，而该钩子返回于'
                            f' {(done_at[hook] - entry_at[hook]) * 1000:6.1f} ms'
                            '⇒「一个文件解析完」正在阻塞「所有文件的首屏命中查询」')
            self.assertLess(finish - entry_at[hook], _HIT_BUDGET_SECONDS,
                            f'{stage}（{hook}）的命中超出随窗口自缩放的上位预算')

        # 事后账：把纯计算搬出锁不许动掉发布原子性与单飞。
        self.assertIs(box['owner'], cold_value, 'owner 仍原样拿到自己算的值')
        self.assertEqual(len(compute_calls), 1, 'cold key 只该 compute 一次')
        self.assertEqual(len(size_calls), 1, 'size_of 只该求一次（不许因重来一轮而重复）')
        self.assertEqual(len(store_if_calls), 1, 'store_if 只该判一次')
        self.assertEqual(self.pending_count(cache), 0, '结束后 pending 必须清空')
        self.assertEqual(len(cache), 2, '两条 key 都该在缓存里')

    def test_hit_path_is_not_blocked_by_the_write_through_put_size_of(self):
        """⑧ 同一记次序判据打在**写透侧** ``put`` —— 第 1 条整改（体积提到锁外）的判据。

        ⑦ 播种 hot_key 用的是常量 ``size_of``，那次播种走的正是 ``put``：如果只测
        ``get_or_compute``，``put`` 把 ``size_of`` 留在锁内这件事会被这条便宜播种完全遮住。
        形态取真实写透链路：``put_cached_parsed_file`` 结尾就是这一句
        ``_parse_cache.put(key, value)``（默认体积函数 ``_parse_value_bytes``；A4 之后它在
        同形夹具上约 14.5ms，进锁就是把「一次上传」变成「全站首屏命中查询等它」）。
        """
        cache = self.new_cache()
        hot_key = ('/tmp/single-flight-hot-put.csv', 1, 'CTA8290D')
        cold_key = ('/tmp/single-flight-cold-put.csv', 1, 'CTA8290D')
        hot_value = ('hot-frame', {'format': 'CTA8290D'}, 'CTA8290D')
        cold_value = ('cold-frame', {'format': 'CTA8290D'}, 'CTA8290D')
        cache.put(hot_key, hot_value, size_of=lambda _v: 64)

        entered = threading.Event()
        entry_at, box, miss_computes = {}, {}, []

        def slow_size_of(_ignored):
            entered.set()
            entry_at['t0'] = time.perf_counter()
            time.sleep(_WINDOW_SECONDS)              # 旧写法停在这 0.2s：全程持锁
            box['size_done'] = time.perf_counter()
            return 128

        writer = threading.Thread(target=lambda: box.setdefault(
            'put', cache.put(cold_key, cold_value, size_of=slow_size_of)))
        writer.start()
        self.assertTrue(entered.wait(_TIMEOUT), 'put 没进入 size_of（前置失效）')
        start = time.perf_counter()
        value = cache.get_or_compute(hot_key, lambda: miss_computes.append(1))
        finish = time.perf_counter()
        writer.join(_TIMEOUT)
        self.assertFalse(writer.is_alive(), 'put 线程未结束（把自己钉在锁里了）')

        print(f'[A4d] 写透 put 的 size_of 求值期间的命中耗时 {(finish - start) * 1000:6.1f} ms'
              f' / 距钩子进入 {(finish - entry_at["t0"]) * 1000:6.1f} ms，钩子返回于'
              f' {(box["size_done"] - entry_at["t0"]) * 1000:6.1f} ms'
              f'（注入窗口 {_WINDOW_SECONDS * 1000:.0f} ms / 自缩放上限'
              f' {_HIT_BUDGET_SECONDS * 1000:.0f} ms）', file=sys.stderr, flush=True)

        self.assertIs(value, hot_value, '探测读到的就是那条已存在条目')
        self.assertEqual(miss_computes, [], '前置：探测走的确实是命中分支，不是又算一遍')
        # ★承重：命中在 size_of 返回之前就结束了 ⇒ 写透没在锁内量体积。
        self.assertLess(finish, box['size_done'],
                        f'写透段持锁期间仍在执行 size_of：命中结束于钩子进入后'
                        f' {(finish - entry_at["t0"]) * 1000:6.1f} ms，而 size_of 返回于'
                        f' {(box["size_done"] - entry_at["t0"]) * 1000:6.1f} ms'
                        '⇒「一次上传」正在阻塞「所有文件的首屏命中查询」')
        self.assertLess(finish - entry_at['t0'], _HIT_BUDGET_SECONDS,
                        '写透侧命中超出随窗口自缩放的上位预算')
        # 事后账：体积搬出锁不许动掉写透本身与「先存后 notify」。
        self.assertEqual(len(cache), 2, '写透那条要真的落进缓存')
        self.assertIs(cache.get_or_compute(cold_key, lambda: miss_computes.append(1)),
                      cold_value, '写透落的就是那条值（命中它，不再算第二遍）')
        self.assertEqual(self.pending_count(cache), 0, '结束后 pending 必须清空')


class FailurePathTests(_SingleFlightBase):
    """把发布收进锁内时，最容易顺手丢的两条：异常与 ``store_if`` 拒绝都必须放开 pending。"""

    def test_failed_compute_notifies_the_waiter_and_caches_nothing(self):
        """③ 异常路径：等待者不死等、pending 清空、失败不入缓存（对齐既有 pending 钉）。"""
        class Boom(RuntimeError):
            pass

        cache = self.new_cache()
        key = ('/tmp/single-flight-boom.csv', 1, 'CTA8290D')

        def raise_boom():
            raise Boom('disk on fire')

        box, stats = self.run_pair(cache, key, raise_boom, raise_boom)

        self.assertIsInstance(box['owner'], Boom, f'owner 该原样抛出，实际 {box["owner"]!r}')
        self.assertIsInstance(box['waiter'], Boom, f'waiter 该重试后抛出，实际 {box["waiter"]!r}')
        self.assertEqual(len(stats['calls']), 2,
                         '瞬时失败不得永久化：waiter 醒来后必须真的重算一次')
        self.assertEqual(self.pending_count(cache), 0, '抛错后 pending 必须清空')
        self.assertEqual(len(cache), 0, '抛错时没有任何值可缓存')
        self.assertEqual(cache.bytes_cached(), 0)

    def test_store_if_rejection_publishes_nothing_but_still_notifies(self):
        """④ ``store_if`` 判 False：失败值仍不入缓存，但必须 notify（「瞬时失败不永久化」）。"""
        cache = self.new_cache()
        key = ('/tmp/single-flight-failure.csv', 1, 'CTA8290D')
        failure = (None, None, 'CTA8290D')
        self.assertFalse(services._parse_succeeded(failure), '前提：这是 store_if 会拒绝的值')

        box, stats = self.run_pair(cache, key,
                                   lambda: failure, lambda: failure,
                                   store_if=services._parse_succeeded)

        self.assertIs(box['owner'], failure)
        self.assertIs(box['waiter'], failure, 'waiter 必须拿到结果并返回，而不是挂住')
        self.assertEqual(len(stats['calls']), 2, '失败值没占位 ⇒ waiter 该重算一次')
        self.assertEqual(len(cache), 0, '失败值不许进缓存（否则 0 字节条目永久化）')
        self.assertEqual(self.pending_count(cache), 0, '拒绝发布后 pending 也要清空')

    def test_publish_side_exception_still_releases_pending(self):
        """⑤ 发布段（``store_if``/``size_of``）抛错时 pending 也必须放开 —— 那条释放路径的判据。

        发布段的代码（``size_of``/``store_if`` 求值 + 锁内写条目）与 ``compute`` 同在一段
        ``try`` 里，靠那句 ``except BaseException`` 统一释放 pending 并 notify；少了它，
        一次体积估算异常就把该 key 永久挂在 ``_pending`` 上，之后每一个调用者都走进等待分支
        死等（``self._cv.wait()`` 没有超时，唤醒只能靠 notify）。

        判据取「两个线程都带着原异常返回、而不是有一个挂死」，
        ``run_pair`` 的 ``join``/``is_alive`` 那两条就是这件事的承重断言。
        """
        cache = self.new_cache()
        key = ('/tmp/single-flight-publish-boom.csv', 1, 'CTA8290D')

        def boom_size(_value):
            raise RuntimeError('memory_usage blew up')

        box, stats = self.run_pair(cache, key,
                                   lambda: ('sentinel-frame', {}, 'CTA8290D'),
                                   lambda: ('sentinel-frame', {}, 'CTA8290D'),
                                   size_of=boom_size)

        self.assertIsInstance(box['owner'], RuntimeError,
                              f'owner 该把发布期的异常原样抛出，实际 {box["owner"]!r}')
        self.assertIsInstance(box['waiter'], RuntimeError,
                              f'waiter 醒来后重算并同样抛出，实际 {box["waiter"]!r}')
        self.assertEqual(len(stats['calls']), 2, '发布失败没留条目 ⇒ waiter 该重算一次')
        self.assertEqual(self.pending_count(cache), 0,
                         '发布段抛错后 pending 也要清空（否则该 key 永久死锁）')
        self.assertEqual(len(cache), 0, '发布失败时不得留下半成品条目')


class WriteThroughNotifyTests(_SingleFlightBase):
    """⑨ 写透 ``put`` 的 ``notify_all`` 承重（复审补的缺口）。

    ``put`` 的 docstring 一直宣称「别的线程挂在同 key 上等结果时，只写不唤醒就是死等」，但复审实测
    「写完不 notify」下本模块原 7 例 + ``BytesLRUCacheTests`` 全绿 ⇒ 该宣称当时没有判据承重：⑦⑧ 只测
    「体积量在锁内还是锁外」（次序判据），压根不让 waiter 挂在 put 正写的 key 上，撞不到「唤醒丢了」。
    ⑨ 用 ``put_wakes_parked_waiters`` 把 waiter 真挂上同 key、只让 put 叫醒它 ——「put 不 notify」这条
    内存变异下必红（owner 卡在 compute 绝不 notify）。⑨a 单 waiter（复审描述的形状）；⑨b 两 waiter，
    把「``notify_all`` 而非单个 ``notify``」也钉上（单个只叫醒一个，余下死等）。
    """

    def test_write_through_put_notifies_a_waiter_parked_on_the_same_key(self):
        """⑨a 单 waiter：owner 卡在 compute，由 put 发布同 key 的值唤醒 waiter。"""
        cache = self.new_cache()
        key = ('/tmp/single-flight-put-notify.csv', 1, 'CTA8290D')
        published = ('put-frame', {'format': 'CTA8290D'}, 'CTA8290D')
        self.put_wakes_parked_waiters(cache, key, published, n_waiters=1)

    def test_write_through_put_notifies_all_waiters_parked_on_the_same_key(self):
        """⑨b 两 waiter：一次 put 必须用 ``notify_all`` 把两个都叫醒（不是只 notify 一个）。"""
        cache = self.new_cache()
        key = ('/tmp/single-flight-put-notify-all.csv', 1, 'CTA8290D')
        published = ('put-frame-all', {'format': 'CTA8290D'}, 'CTA8290D')
        self.put_wakes_parked_waiters(cache, key, published, n_waiters=2)


class _CountingGateParser:
    """假解析器：只统计真实解析次数（成功路径），不注入 sleep —— 时序全由 gate 控制。"""

    def __init__(self, frame):
        self.frame = frame
        self.calls = 0

    def parse(self, path):
        self.calls += 1
        return self.frame, {'format': 'CTA8290D'}


class CachedParseChainTests(SimpleTestCase):
    """⑥ 接线证明：真实 ``_cached_parse`` 链路上，publish 窗口已经消失。

    把 ``parse_cache_sizing._frame_bytes``（``_parse_value_bytes`` 消费的那只；G2 搬家后按 R6③ 改打新 binding）
    钉在 gate 上：它正好落在被测窗口里 —— **旧写法与新写法都是在锁外调它**（旧写法调完才
    放开 pending + notify，新写法在进锁发布之前调完），所以这条钉的**不是**锁内/锁外，而是
    「owner 还在这段窗口里时 ``key`` 必须仍挂在 ``_pending`` 上」：waiter 在「owner 已进
    publish」之后才发起，旧写法里它看到「无条目、无 pending」⇒ 自己再解析一次；新写法里它
    撞上 pending ⇒ 阻塞在 ``_cv.wait()``，等发布段醒来直接命中同一只帧。
    「体积/谓词不许在锁内跑」那一半由 ⑦⑧ 的次序判据负责，两条判据互不替代。
    """

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', self.original_cache)
        services._parse_cache = services._BytesLRUCache(services.PARSE_CACHE_BUDGET_BYTES)

    def patch_parser(self, frame):
        parser = _CountingGateParser(frame)
        original = services.get_parser
        services.get_parser = lambda fmt: parser
        self.addCleanup(setattr, services, 'get_parser', original)
        return parser

    def test_two_owners_of_one_content_coordinate_parse_once(self):
        """⑥ 接线证明：与 ① 钉同一条不变量（窗口里 key 仍挂在 _pending 上），打在真实 _cached_parse 链路上；拆锁留空窗时与 ① 一起转红。"""
        frame = pd.DataFrame({f'P{i}': [float(r * i + r) for r in range(500)]
                              for i in range(4)})
        parser = self.patch_parser(frame)
        original_frame_bytes = parse_cache_sizing._frame_bytes
        publish_entered = threading.Event()
        release = threading.Event()
        publish_calls = []

        def gated_frame_bytes(df):
            # 只在 owner 的第一次调用上停住：此刻 publish 已经开始、还没落条目。
            if not publish_calls:
                publish_calls.append(1)
                publish_entered.set()
                release.wait(_TIMEOUT)
            return original_frame_bytes(df)

        box = {}

        def worker(name):
            box[name] = services._cached_parse(
                11 if name == 'a' else 22, 1 if name == 'a' else 2,
                12345, self.path, 'CTA8290D')

        with mock.patch.object(parse_cache_sizing, '_frame_bytes', gated_frame_bytes):
            t1 = threading.Thread(target=worker, args=('a',))
            t1.start()
            self.assertTrue(publish_entered.wait(_TIMEOUT),
                            'owner 没有进入 publish（前置失效：_frame_bytes 没被调用）')
            t2 = threading.Thread(target=worker, args=('b',))
            t2.start()
            release.set()          # 无论 waiter 排在锁上还是窗口里，都必须放开，否则本测试自锁
            t1.join(_TIMEOUT)
            t2.join(_TIMEOUT)

        self.assertFalse(t1.is_alive() or t2.is_alive(), '有线程没结束')
        self.assertEqual(parser.calls, 1,
                         f'两个 owner 并发同一内容坐标应只解析一次，实际 {parser.calls} 次')
        self.assertIs(box['a'][0], box['b'][0], '两侧必须命中同一只帧')
        self.assertEqual(len(services._parse_cache), 1, '一条内容坐标只该有一条缓存')
        self.assertEqual(box['a'][2], 'CTA8290D', '返回形状仍是 (df, metadata, format_type)')
        self.assertIs(box['a'][0], frame, '缓存里那条就是解析出来的那只帧')
