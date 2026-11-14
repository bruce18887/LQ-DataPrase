# test/backend/test_storage_usage_cache.py
"""批2 磁盘占用的**缓存行为**测试（T1）。

从 ``test_storage_usage_scan.py`` 拆出来只有一个原因：那份文件按口径 + 两本账 +
装配层写完之后已经贴着 600 行硬闸，再加这一类就翻过。拆分的依据是判据本来就异源：
那份钉「扫出来是什么」，这份钉「扫了几次」。

端点契约在 ``test_files_usage_api.py``。
"""
import shutil
import tempfile
from unittest import mock

from django.test import TestCase

from apps.accounts.models import User
from apps.datafiles import storage_usage


class CacheBehaviourTests(TestCase):
    """缓存的**行为**判据：扫几次、什么时候必须重扫。

    判据打在「计算次数」而不是「返回内容」上 —— 内容与口径的等价性由前面的用例钉，
    这里只钉缓存有没有改变实际发生的扫描数（异源）。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-cache-')
        self.addCleanup(shutil.rmtree, self.base, True)
        storage_usage.clear_usage_cache()
        self.user = User.objects.create_user('cacheuser', 'c@localhost', 'x-pass-12345678')

    def tearDown(self):
        storage_usage.clear_usage_cache()

    def _counting_compute(self, sink):
        def compute(user):
            sink.append(user.username)
            return {'bytes': len(sink) * 10, 'scanned_at': ''}
        return compute

    def test_同一bucket内第二次调用不再算(self):
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            # 三次调用都要钉住同一个 bucket：不锁 monotonic 的话，落在 30s 桶边界上
            # 的第二次就会重算 —— 那是每 30 秒一次的定时 flaky，CI 上迟早自己冒出来。
            with mock.patch.object(storage_usage.time, 'monotonic', return_value=1_000.0), \
                    mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                first = storage_usage.get_user_usage(self.user)
                second = storage_usage.get_user_usage(self.user)
        self.assertEqual(first['bytes'], 10)
        self.assertEqual(second['bytes'], 10)
        self.assertEqual(sink, ['cacheuser'])          # 只算了一次

    def test_fresh为True时强制重算(self):
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            with mock.patch.object(storage_usage.time, 'monotonic', return_value=1_000.0), \
                    mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                storage_usage.get_user_usage(self.user)
                third = storage_usage.get_user_usage(self.user, fresh=True)
        self.assertEqual(sink, ['cacheuser', 'cacheuser'])
        self.assertEqual(third['bytes'], 20)

    def test_不同用户不共享缓存(self):
        other = User.objects.create_user('otheruser', 'o@localhost', 'x-pass-12345678')
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            with mock.patch.object(storage_usage.time, 'monotonic', return_value=1_000.0), \
                    mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                storage_usage.get_user_usage(self.user)
                storage_usage.get_user_usage(other)
        self.assertEqual(sink, ['cacheuser', 'otheruser'])

    def test_bucket随TTL变化_用假时钟证明换桶必重算(self):
        """钉的是「过期机制 = 换 key」这条形状，不是真的等 30 秒。"""
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            with mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                with mock.patch.object(storage_usage.time, 'monotonic', return_value=0.0):
                    storage_usage.get_user_usage(self.user)
                with mock.patch.object(storage_usage.time, 'monotonic',
                                       return_value=float(storage_usage.USAGE_CACHE_TTL_SECONDS)):
                    storage_usage.get_user_usage(self.user)
        self.assertEqual(len(sink), 2)
