"""Unit tests for the SFTP connection pool (apps/sftp/pool.py).

Verifies that connections are reused across calls (eliminating the per-click
SSH handshake), and that dead / idle connections are rebuilt, invalidation
works, and users are isolated. paramiko and the credential cache are mocked,
so no real SFTP server or DB is required.

Run directly:  python test/test_sftp_pool.py
Or via pytest:  pytest test/test_sftp_pool.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from apps.sftp import pool  # noqa: E402

SESSION = {'host': 'h', 'port': 22, 'username': 'u', 'password': 'p'}


def _make_transport(active=True):
    t = mock.MagicMock(name='Transport')
    t.is_active.return_value = active
    return t


class SftpPoolTests(unittest.TestCase):
    def setUp(self):
        # Each test starts with an empty pool.
        for uid in list(pool._pool.keys()):
            pool._pool.pop(uid, None)

    def tearDown(self):
        for uid in list(pool._pool.keys()):
            pool._pool.pop(uid, None)

    def _patch_paramiko(self, transports):
        """Patch paramiko so each Transport(...) call returns the next mock.

        Returns the Transport constructor mock for call-count assertions.
        """
        transport_ctor = mock.MagicMock(side_effect=transports)
        sftp_from = mock.MagicMock(
            side_effect=lambda *a, **k: mock.MagicMock(name='SFTPClient'))
        p = mock.patch.object(pool.paramiko, 'Transport', transport_ctor)
        p2 = mock.patch.object(pool.paramiko, 'SFTPClient')
        p.start()
        m2 = p2.start()
        m2.from_transport = sftp_from
        self.addCleanup(p.stop)
        self.addCleanup(p2.stop)
        return transport_ctor

    def test_reuse_same_user_builds_connection_once(self):
        ctor = self._patch_paramiko([_make_transport()])
        with mock.patch.object(pool, 'get_session', return_value=SESSION):
            first = pool.get_connection(1)
            second = pool.get_connection(1)
        self.assertIs(first, second)
        self.assertEqual(ctor.call_count, 1)  # second call reused, no handshake

    def test_dead_connection_is_rebuilt(self):
        ctor = self._patch_paramiko([_make_transport(active=False),
                                     _make_transport(active=True)])
        with mock.patch.object(pool, 'get_session', return_value=SESSION):
            pool.get_connection(1)
            # Stored transport reports inactive -> next call must rebuild.
            pool.get_connection(1)
        self.assertEqual(ctor.call_count, 2)

    def test_idle_connection_is_rebuilt(self):
        ctor = self._patch_paramiko([_make_transport(), _make_transport()])
        with mock.patch.object(pool, 'get_session', return_value=SESSION), \
                mock.patch.object(pool, '_idle_ttl', return_value=300):
            pool.get_connection(1)
            # Force the entry to look idle beyond TTL.
            pool._pool[1].last_used -= 1000
            pool.get_connection(1)
        self.assertEqual(ctor.call_count, 2)

    def test_invalidate_drops_connection(self):
        ctor = self._patch_paramiko([_make_transport(), _make_transport()])
        with mock.patch.object(pool, 'get_session', return_value=SESSION):
            pool.get_connection(1)
            pool.invalidate(1)
            self.assertNotIn(1, pool._pool)
            pool.get_connection(1)  # rebuilds
        self.assertEqual(ctor.call_count, 2)

    def test_close_drops_connection(self):
        self._patch_paramiko([_make_transport()])
        with mock.patch.object(pool, 'get_session', return_value=SESSION):
            pool.get_connection(1)
            pool.close(1)
        self.assertNotIn(1, pool._pool)

    def test_no_session_raises_pool_error(self):
        self._patch_paramiko([_make_transport()])
        with mock.patch.object(pool, 'get_session', return_value=None):
            with self.assertRaises(pool.SftpPoolError):
                pool.get_connection(1)

    def test_users_are_isolated(self):
        t_a, t_b = _make_transport(), _make_transport()
        ctor = self._patch_paramiko([t_a, t_b])
        with mock.patch.object(pool, 'get_session', return_value=SESSION):
            conn_a = pool.get_connection(1)
            conn_b = pool.get_connection(2)
        self.assertIsNot(conn_a, conn_b)
        self.assertEqual(ctor.call_count, 2)
        self.assertIn(1, pool._pool)
        self.assertIn(2, pool._pool)


if __name__ == '__main__':
    unittest.main(verbosity=2)
