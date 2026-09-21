"""SearchSession 的借还、降级与关闭（spec §3.7）。

这里用假 transport，测的是借还/降级/无泄漏三件真服务器不便制造的事；
真 paramiko 并行正确性在 Task 11 的集成测试里，两者不可互替。

跑法：python manage.py test test.backend.test_sftp_search_connect
"""
import os
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp import host_keys  # noqa: E402
from apps.sftp.search import connect  # noqa: E402

CREDS = {'host': 'sftp.example', 'port': 22, 'username': 'u', 'password': 'p'}


class _FakeTransport:
    def __init__(self, serial):
        self.serial = serial
        self.closed = False

    def close(self):
        self.closed = True

    def is_active(self):
        return not self.closed

    def open_session(self, timeout=None):
        return object()


class _FakeSFTP:
    def close(self):
        pass


class ConnectTests(SimpleTestCase):
    def setUp(self):
        self.built = []
        self.fail_after = None
        self._orig_open = host_keys.open_verified_transport
        self._orig_session = connect.cache.get_session

        def fake_open(host, port, username, password):
            if self.fail_after is not None and len(self.built) >= self.fail_after:
                raise OSError('server refused: MaxSessions exceeded')
            tr = _FakeTransport(len(self.built))
            self.built.append(tr)
            return tr

        host_keys.open_verified_transport = fake_open
        connect.cache.get_session = lambda uid: dict(CREDS)
        import paramiko
        self._orig_from = paramiko.SFTPClient.from_transport
        paramiko.SFTPClient.from_transport = staticmethod(
            lambda tr: _FakeSFTP())

    def tearDown(self):
        host_keys.open_verified_transport = self._orig_open
        connect.cache.get_session = self._orig_session
        import paramiko
        paramiko.SFTPClient.from_transport = self._orig_from

    def test_no_session_raises_not_connected(self):
        connect.cache.get_session = lambda uid: None
        with self.assertRaises(connect.SearchSessionError) as ctx:
            connect.SearchSession(1, 2).open_all()
        self.assertIn('not connected', str(ctx.exception).lower())

    def test_opens_requested_number(self):
        s = connect.SearchSession(1, 4)
        self.assertEqual(s.open_all(), 4)
        self.assertEqual(s.size, 4)

    def test_degrades_when_server_refuses_extra(self):
        """开不出来必须降级继续跑，而不是整次搜索失败。"""
        self.fail_after = 2
        self.assertEqual(connect.SearchSession(1, 4).open_all(), 2)

    def test_host_key_mismatch_propagates(self):
        """安全边界：不降级、不吞异常。"""
        def boom(*a, **k):
            raise host_keys.HostKeyMismatchError('mismatch')
        host_keys.open_verified_transport = boom
        with self.assertRaises(host_keys.HostKeyMismatchError):
            connect.SearchSession(1, 2).open_all()

    def test_borrow_reuses_idle_item(self):
        s = connect.SearchSession(1, 1)
        s.open_all()
        item = s.borrow()
        s.give_back(item)
        self.assertIs(s.borrow(), item)
        s.close_all()

    def test_borrow_blocks_until_returned(self):
        s = connect.SearchSession(1, 1)
        s.open_all()
        held = s.borrow()
        got = []

        def waiter():
            got.append(s.borrow())
            s.give_back(got[0])

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        self.assertEqual(got, [], '唯一连接被占着，borrow 不该立刻返回')
        s.give_back(held)
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertEqual(got, [held])
        s.close_all()

    def test_broken_connection_closed_and_replaced(self):
        s = connect.SearchSession(1, 1)
        s.open_all()
        item = s.borrow()
        s.give_back(item, broken=True)
        self.assertTrue(item[0].closed, '坏连接必须关掉，不能放回队列')
        fresh = s.borrow(timeout=5)
        self.assertIsNot(fresh, item)
        s.close_all()

    def test_broken_when_reopen_fails_does_not_deadlock(self):
        """补不上新连接也要让队列保持可消费，否则 borrow 永久阻塞。"""
        self.fail_after = 1
        s = connect.SearchSession(1, 1)
        s.open_all()
        item = s.borrow()
        s.give_back(item, broken=True)
        s.close_all()
        self.assertTrue(all(tr.closed for tr in self.built))

    def test_close_all_closes_everything_and_is_idempotent(self):
        s = connect.SearchSession(1, 3)
        s.open_all()
        s.close_all()
        s.close_all()
        self.assertEqual(s.closed, s.opened)
        self.assertTrue(all(tr.closed for tr in self.built))

    def test_close_all_drives_out_a_blocked_borrow(self):
        """取消路径依赖这条：close_all 之后 borrow 必须立刻失败而非永挂。"""
        s = connect.SearchSession(1, 1)
        s.open_all()
        s.borrow()                      # 占住唯一一条
        errors = []

        def waiter():
            try:
                s.borrow()
            except Exception as exc:     # noqa: BLE001 - 断言异常类型由下面做
                errors.append(exc)

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        s.close_all()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), 'close_all 后 borrow 仍挂着')
        self.assertTrue(errors)
        self.assertIsInstance(errors[0], connect.SearchSessionError)

    def test_context_manager_closes_on_exception(self):
        with self.assertRaises(RuntimeError):
            with connect.SearchSession(1, 2) as s:
                s.open_all()
                raise RuntimeError('boom')
        self.assertTrue(all(tr.closed for tr in self.built))

    def test_exec_transport_borrows_and_hands_it_back(self):
        """grep 档只要 transport：借出→立刻归还，不能把 SFTP channel 占住。"""
        s = connect.SearchSession(1, 1)
        s.open_all()
        tr = s.exec_transport()
        self.assertIs(tr, s.borrow()[0])
        s.close_all()

    def test_every_connection_goes_through_host_key_verification(self):
        """参考工具用 AutoAddPolicy，会破坏本项目 TOFU 契约。"""
        s = connect.SearchSession(1, 3)
        s.open_all()
        self.assertEqual(len(self.built), 3)   # built 只在 fake_open 里追加
        s.close_all()
