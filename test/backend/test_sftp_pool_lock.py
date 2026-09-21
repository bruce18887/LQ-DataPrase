"""pool 必须容忍 threaded runserver 下同 user 并发访问（spec §2.5）。

跑法：python manage.py test test.backend.test_sftp_pool_lock
     或 python test/backend/test_sftp_pool_lock.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp import host_keys, pool  # noqa: E402


class _FakeTransport:
    builds = []

    def __init__(self):
        _FakeTransport.builds.append(1)
        self.active = True

    def is_active(self):
        return self.active

    def close(self):
        self.active = False


class _FakeSFTP:
    def close(self):
        pass


# 握手前的等待：让无锁时 8 个线程真正在临界区内重叠。
# 不能省——mock 的握手是微秒级的纯 Python 调用，GIL 不会在其中切换线程，
# 于是「未加锁」也能 8/8 次只建 1 条连接，测试假绿（本计划自审发现的弱点）。
BUILD_DELAY = 0.05


def _fake_open(*args, **kwargs):
    time.sleep(BUILD_DELAY)
    return _FakeTransport()


class PoolLockTests(SimpleTestCase):
    N = 8

    def setUp(self):
        pool._pool.clear()
        _FakeTransport.builds = []
        self._orig_open = host_keys.open_verified_transport
        self._orig_session = pool.get_session
        host_keys.open_verified_transport = _fake_open
        pool.get_session = lambda uid: {'host': 'h', 'port': 22,
                                        'username': 'u', 'password': 'p'}
        import paramiko
        self._orig_from = paramiko.SFTPClient.from_transport
        paramiko.SFTPClient.from_transport = staticmethod(lambda tr: _FakeSFTP())

    def tearDown(self):
        pool._pool.clear()
        host_keys.open_verified_transport = self._orig_open
        pool.get_session = self._orig_session
        import paramiko
        paramiko.SFTPClient.from_transport = self._orig_from

    def test_concurrent_get_connection_builds_once(self):
        """8 线程同时取连接：只允许一次握手，且全部拿到同一个对象。"""
        results, barrier = [], threading.Barrier(self.N)

        def worker():
            barrier.wait()
            results.append(pool.get_connection(42))

        threads = [threading.Thread(target=worker) for _ in range(self.N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(results), self.N)
        self.assertEqual(
            len(_FakeTransport.builds), 1,
            f'并发下建立了 {len(_FakeTransport.builds)} 条连接，锁未生效')
        self.assertTrue(all(r is results[0] for r in results))
        self.assertEqual(len(pool._pool), 1)

    def test_different_users_do_not_share_a_lock(self):
        """锁按 user 分，否则一个用户的慢握手会挡住别的用户。"""
        pool.get_connection(1)
        pool.get_connection(2)
        self.assertIsNot(pool._locks[1], pool._locks[2])


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)
