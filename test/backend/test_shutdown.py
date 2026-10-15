"""契约测试：优雅关闭的 HTTP 通路与信号处理器。

为什么这条通路必须存在（2026-10-15 架构评审 P0-3）：``electron/backend.ts`` 早就有
``stopBackend()``（SIGTERM → 5s → 强杀），但**后端那一半根本不存在** —— Django 进程
既没有信号处理器也没有任何关闭路径，退出时从不关数据库连接。更关键的是，在主要交付
形态 Windows 上那个 SIGTERM 压根不会以信号形式到达：Node 的 ``child.kill('SIGTERM')``
是用 ``TerminateProcess`` 实现的，不触发任何 Python 层处理器。所以 5 秒「优雅窗口」
在打包版里纯属装饰。

本文件钉住四道闸门与两条不变量：

* 未配置令牌 → 404（与「路由不存在」不可区分，是开发/服务器档应有的姿态）
* 非回环来源 → 403（局域网客户端绝不能停掉服务器档的服务）
* 令牌缺失或不匹配 → 403（常数时间比较）
* 回环 + 正确令牌 → 200，且**恰好调度一次**关闭

两条不变量：``_cleanup`` 与 ``install_signal_handlers`` 都必须幂等 —— 信号可能在清理
进行到一半时再次到达，端点也可能被连点两次。

注意：``request_shutdown`` 会起线程并在 150ms 后 ``os._exit(0)``。测试里必须打桩，
否则跑测试的进程会直接消失。
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.common import shutdown

SHUTDOWN_URL = '/api/v1/system/shutdown/'
TOKEN = 'test-token-4f9c2a'
TOKEN_HEADER = 'HTTP_X_LQDP_SHUTDOWN_TOKEN'


class ShutdownEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # 模块级单次标志：上一个用例置过就得复位，否则本用例的清理会被跳过。
        shutdown._shutdown_started = False

    def _post(self, **extra):
        return self.client.post(SHUTDOWN_URL, **extra)

    # ------------------------------------------------------------------
    # 闸门
    # ------------------------------------------------------------------
    @override_settings(SHUTDOWN_TOKEN=None)
    def test_not_enabled_when_no_token_configured(self):
        """默认姿态：开发档与服务器档都不配令牌，端点应当像不存在一样。"""
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(SHUTDOWN_TOKEN=TOKEN)
    def test_refuses_non_loopback_source(self):
        """服务器档是局域网共用的，远端客户端绝不能停掉服务。"""
        resp = self._post(REMOTE_ADDR='10.0.0.5', **{TOKEN_HEADER: TOKEN})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(SHUTDOWN_TOKEN=TOKEN)
    def test_refuses_missing_token(self):
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(SHUTDOWN_TOKEN=TOKEN)
    def test_refuses_wrong_token(self):
        resp = self._post(**{TOKEN_HEADER: 'not-the-token'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(SHUTDOWN_TOKEN=TOKEN)
    def test_refuses_token_of_the_same_length_but_different_value(self):
        """常数时间比较的回归钉子：长度相同但内容不同也必须拒。"""
        resp = self._post(**{TOKEN_HEADER: 'x' * len(TOKEN)})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # ------------------------------------------------------------------
    # 放行
    # ------------------------------------------------------------------
    @override_settings(SHUTDOWN_TOKEN=TOKEN)
    def test_accepts_loopback_with_correct_token(self):
        with patch.object(shutdown, 'request_shutdown') as mock_request:
            resp = self._post(**{TOKEN_HEADER: TOKEN})

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'shutting_down')
        mock_request.assert_called_once()

    @override_settings(SHUTDOWN_TOKEN=TOKEN)
    def test_accepts_ipv4_mapped_ipv6_loopback(self):
        """双栈监听接受 IPv4 客户端时，REMOTE_ADDR 会是 ::ffff:127.0.0.1。
        Windows 上 Electron 连 127.0.0.1 走的正是这条路径 —— 漏掉它会让
        打包版的关闭请求被 403，而且只在真机上复现。"""
        with patch.object(shutdown, 'request_shutdown') as mock_request:
            resp = self._post(REMOTE_ADDR='::ffff:127.0.0.1', **{TOKEN_HEADER: TOKEN})

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_request.assert_called_once()

    @override_settings(SHUTDOWN_TOKEN=TOKEN)
    def test_shutdown_endpoint_is_not_throttled(self):
        """被限流挡住的关闭请求 = 进程杀不掉，只能等强杀。"""
        with patch.object(shutdown, 'request_shutdown'):
            for _ in range(5):
                resp = self._post(**{TOKEN_HEADER: TOKEN})
        self.assertNotEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    # ------------------------------------------------------------------
    # 幂等
    # ------------------------------------------------------------------
    def test_cleanup_is_idempotent(self):
        """信号可能在清理途中再次到达；第二次必须是空操作而不是炸。"""
        shutdown._cleanup('first')
        self.assertTrue(shutdown._shutdown_started)
        shutdown._cleanup('second')  # 不应抛异常

    def test_install_signal_handlers_is_idempotent(self):
        shutdown.install_signal_handlers()
        shutdown.install_signal_handlers()

    def test_signal_handler_exits_after_cleanup(self):
        """处理器必须先清理再退出 —— 顺序反了就回到「从不关数据库连接」。"""
        calls = []

        def fake_cleanup(reason):
            calls.append(reason)

        with patch.object(shutdown, '_cleanup', side_effect=fake_cleanup), \
                patch.object(shutdown.os, '_exit') as mock_exit:
            shutdown._signal_handler(15, None)  # 15 = SIGTERM

        self.assertEqual(len(calls), 1)
        self.assertIn('SIGTERM', calls[0])
        mock_exit.assert_called_once_with(0)
