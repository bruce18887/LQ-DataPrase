"""按条数封顶的进程内 LRU + 每 key 单飞（**唯一一份**，别在各 app 里再写第二份）。

两个调用点形状本来就一样：``key -> 一个共享只读值``、超过 N 条逐最久未用的一条、
同一个 key 的并发 miss 只算一次。它们各自抄过一份（``apps/dashboard/services.py`` 的
``_summary_cache`` 与 ``apps/analysis/views/_helpers.py`` 的 ``_low_cpk_cache``），
G2（2026-10-28）把**共同形状**收到这里：

* 为什么不把 `apps/dashboard/services.py` 那份直接 import 进来：那会造出
  ``analysis -> dashboard`` 的 app 依赖（低 CPK 在分析视图里，汇总在仪表板里，
  两者本不该互相知道）。这个模块只依赖标准库。
* 为什么不与 ``apps/datafiles/services.py`` 的 ``_BytesLRUCache`` 合一：那个的淘汰依据是
  **累计字节**且要跟解析预算联动（含 ``evict_keys`` 按内容坐标定点逐出）；这里两个
  调用点的值都是几十 KB 级的 payload / 集合，按**条数**封顶就够，硬并会逼着这里实现
  一套永远用不到的字节记账。

语义（两个调用点都依赖，改之前先看判据）：
1. **值可以是任何对象，包括空集**：命中判定是 ``key in self._data``，不用 truthiness ——
   低 CPK 集合为空是常态，用真假判会把它当成 miss，每次请求重算。
2. **命中即刷新为最近使用**（``move_to_end``），超上限逐 ``popitem(last=False)``。
   **不是** wholesale clear：那会把所有活着的文件一起打回冷启动。
3. **单飞**：同 key 的并发 miss 里只有一个线程执行 ``compute``，其余挂在 Condition 上等
   它发布；``compute`` 抛错时释放 pending 并唤醒等待者（失败不永久化、不死等）。
4. ``compute`` 在**锁外**跑：锁只保护容器与 pending 集合，计算本身再慢也不阻塞别人的命中。
5. ``__len__`` / ``clear`` 是给既有调用方与测试的读面（dashboard 的
   ``summary_cache_stats`` 读 ``len(...)``、清空入口调 ``.clear()``，测试也拿它们做隔离）；
   ``values`` 只有 dashboard 的一条测试在用（``next(iter(...))`` 取唯一值），返回快照列表、
   不泄漏内部 OrderedDict。
"""
import threading
from collections import OrderedDict


class KeyedLRU:
    def __init__(self, max_entries: int):
        self._max_entries = int(max_entries)
        self._data = OrderedDict()
        self._pending = set()
        self._cv = threading.Condition()

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def __len__(self) -> int:
        with self._cv:
            return len(self._data)

    def values(self):
        """当前值的快照列表（按 LRU 顺序，最旧在前）。"""
        with self._cv:
            return list(self._data.values())

    def clear(self) -> None:
        """清空所有条目。**不 fence 在途的 ``compute``**：清空前已开始的计算结束后仍会
        把那条值发布回来（本方法不碰 pending、不换代）。两个调用点都只在测试隔离里清，
        生产路径没有「边算边清」的需求；真需要时给条目加 epoch，别在这里顺手加。
        """
        with self._cv:
            self._data.clear()

    def get_or_compute(self, key, compute):
        """返回 key 对应的值；未命中时由当前线程算一次并发布。

        并发 miss 的单飞承诺与 ``_BytesLRUCache.get_or_compute`` 同一条：``compute``
        结束后，写条目与放开 pending、``notify_all`` 收在**同一次持锁**段里 ——
        否则等待者被唤醒后重新拿锁时可能看到「条目还没进、key 已离开 pending」的空窗，
        判定「没人算」而自己再算一遍。
        """
        while True:
            with self._cv:
                if key in self._data:
                    self._data.move_to_end(key)
                    return self._data[key]
                if key in self._pending:
                    self._cv.wait()
                    continue
                self._pending.add(key)
            try:
                value = compute()
                with self._cv:
                    self._data[key] = value
                    self._data.move_to_end(key)
                    while len(self._data) > self._max_entries:
                        self._data.popitem(last=False)
                    self._pending.discard(key)
                    self._cv.notify_all()
            except BaseException:
                # 算不出来：只放开 pending，没有任何值已发布，等待者醒来自己重算
                # （绝不把该 key 永久挂在 pending 上，也绝不让等待者死等）。
                with self._cv:
                    self._pending.discard(key)
                    self._cv.notify_all()
                raise
            return value
