"""G1 淘汰判据的共享道具（被 `test_parse_cache_eviction.py` 与
`test_parse_cache_eviction_interleave.py` 共用；文件名不匹配 ``test*.py``，
所以 DiscoverRunner 不会把它当测试模块收 —— 与仓里其它 ``*_fixtures.py`` 同形）。

拆出来不是为整洁：两份判据都要用**同一只** ``_CacheSwapBase`` 换掉进程共享的模块级
``_parse_cache``（换错实例就是「测的是假缓存、跑的是真缓存」的假绿），也要用**同一个**
``_value``/``_frame`` 的键形与计费口径 —— 两边各写一份的话，改生产键形时只会红一半。
"""
import os
import tempfile
import threading

import pandas as pd
from django.test import SimpleTestCase

from apps.datafiles import services

_BUDGET = 64 * 1024 * 1024


def _frame(rows=200, cols=4):
    """可测量大小的小帧：淘汰判据要的是**每条计费**，不是真实数据量。"""
    data = {f'P{i}': [float(r * i + r) for r in range(rows)] for i in range(cols)}
    return pd.DataFrame(data)


def _value(frame):
    """缓存里一条值的形状 ``(df, metadata, format_type)``（与 ``_cached_parse`` 同形）。"""
    return (frame, {'format': 'G1'}, 'CTA8290D')


def _tmp_path(name):
    """真实临时目录下的路径：``normpath`` 会拆 ``..``/``.``，所以别用假想的 ``/tmp``。"""
    return os.path.join(os.path.normpath(tempfile.gettempdir()), name)


class _CacheSwapBase(SimpleTestCase):
    """模块级 ``_parse_cache`` 是进程共享的：每例换成一只空的，收尾换回去。

    换的是模块属性，``services`` 里所有函数都在调用时按全局名查它 ⇒
    生产入口（``clear_parse_cache`` / ``evict_parse_cache_for_paths``）
    打到的是同一只实例，不存在「测的是假缓存、跑的是真缓存」的错位。
    """

    def setUp(self):
        self.original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', self.original_cache)
        services._parse_cache = services._BytesLRUCache(_BUDGET)
        self.cache = services._parse_cache

    def prime(self, path, frame, mtime=1, fmt='CTA8290D'):
        """按生产键形写入一条，返回它的 key。走 ``put``，计费与被测代码同源。"""
        key = (path, mtime, fmt)
        self.cache.put(key, _value(frame))
        return key

    def billed(self, key):
        return self.cache._data[key][1]


class _Gate:
    """确定性编排：owner 停在 compute 里，主线程**保证**在它期间做完淘汰。

    这段窗口由 ``entered``/``release`` 两个事件撑成「直到我说结束」，不靠 sleep 赌；
    waiter 那半步用的是 ``join(0.2) + is_alive()`` + ``in_flight == 1``，
    那是**编排的前置**而不是判据 —— 判据是「waiter 最后拿到的就是 owner 那只帧」，
    编排没成立（它没挂上、自己去算了）也照样落红，不会假绿。
    """

    def __init__(self, value):
        self.value = value
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def compute(self):
        self.calls += 1
        self.entered.set()
        self.release.wait(timeout=10)
        return self.value
