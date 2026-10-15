"""契约测试：/api/v1/health/ 与 /api/v1/ready/ 探针。

为什么需要这两个端点（2026-10-15 架构评审 P0-2）：打包版原先没有专用探活通路 ——
Electron 轮询 ``/api/v1/``（契约竟是「任何响应都算活着」，404 也算），Playwright 的
``webServer`` 就绪门则轮询 ``/api/schema/``，而那条路由由 ``API_DOCS_ENABLED`` 控制，
两个交付档（standalone / server）都关掉了它。于是「后端是否就绪」被绑死在
「要不要暴露 API 文档」这个完全无关的开关上。

本文件钉住的四件事：

1. 两个探针都**无需鉴权**可达 —— Electron 必须在任何用户登录之前就能轮询，
   这是它们存在的全部意义；一旦被 ``IsAuthenticated`` 拦住，启动门就永远过不去。
2. ``/health/`` 是纯 liveness：不碰 DB、不碰磁盘，恒 200。
3. ``/ready/`` 在检查项失败时返回 503 且逐项给出 ok 标记（而不是 500 或抛异常）。
4. ``/ready/`` 在 ``DEBUG=False``（即打包版）下不泄露路径与驱动报错文本。
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

HEALTH_URL = '/api/v1/health/'
READY_URL = '/api/v1/ready/'


class HealthProbeTests(TestCase):
    def setUp(self):
        # 刻意不 force_authenticate：匿名可达正是被测契约本身。
        self.client = APIClient()
        # 把 MEDIA_ROOT 钉到一个临时目录再测。默认档的 MEDIA_ROOT 指向用户**真实**
        # 数据目录（仓库根的 system_config.json 决定的），在那里做写探针等于让测试
        # 往用户数据里扔文件 —— 同 lessons 2026-09-19 那条「e2e 复用了真实数据目录的
        # 后端」是同一类污染。check 的**逻辑**不需要真实目录才能验。
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=Path(media.name))
        override.enable()
        self.addCleanup(override.disable)

    # ------------------------------------------------------------------
    # liveness
    # ------------------------------------------------------------------
    def test_health_is_reachable_anonymously(self):
        resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, {'status': 'ok'})

    def test_health_does_not_touch_the_database(self):
        """liveness 必须是廉价的：它答的是「进程在不在服务 HTTP」，
        不是「依赖好不好」。用 ``assertNumQueries(0)`` 把这条钉死，
        免得以后有人「顺手」给它加一个 DB 检查。"""
        with self.assertNumQueries(0):
            resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # readiness —— 正常路径
    # ------------------------------------------------------------------
    def test_ready_passes_when_everything_is_healthy(self):
        resp = self.client.get(READY_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'ok')
        self.assertEqual(
            set(resp.data['checks']),
            {'database', 'data_dir_writable', 'migrations_applied'},
        )
        for name, item in resp.data['checks'].items():
            self.assertTrue(item['ok'], f'{name} 应通过，实际 {item}')

    def test_ready_is_reachable_anonymously(self):
        resp = self.client.get(READY_URL)
        self.assertNotIn(
            resp.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    # ------------------------------------------------------------------
    # readiness —— 失败路径
    # ------------------------------------------------------------------
    def test_ready_reports_503_and_names_the_failing_check(self):
        missing = Path(tempfile.gettempdir()) / 'lqdp-does-not-exist-9f3a'
        with override_settings(MEDIA_ROOT=missing):
            resp = self.client.get(READY_URL)

        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(resp.data['status'], 'degraded')
        self.assertFalse(resp.data['checks']['data_dir_writable']['ok'])
        # 其它检查不受影响 —— 503 要能指出是哪一项坏了，而不是一锅端。
        self.assertTrue(resp.data['checks']['database']['ok'])
        self.assertTrue(resp.data['checks']['migrations_applied']['ok'])

    def test_ready_never_raises_even_if_a_check_blows_up(self):
        """探针自己不能 500：任何异常都要被吸收成该项 ok=False。
        否则「后端坏了」与「探针坏了」在调用方看来毫无区别。"""
        with patch('apps.common.health.connection') as mock_conn:
            mock_conn.cursor.side_effect = RuntimeError('simulated probe failure')
            resp = self.client.get(READY_URL)

        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(resp.data['checks']['database']['ok'])

    def test_writable_check_survives_a_failing_cleanup(self):
        """写探针的**写**才是判据；**删**只是打扫卫生。

        外部守卫（EDR、沙箱 shim、信号处理器）完全可能从删除调用里抛出
        **不是 Exception 子类**的东西 —— ``SystemExit`` 就不继承 Exception。
        若让清理失败把「目录可写」变成 500，探针就比没有探针更不可信。
        本条是那个场景的回归钉子（2026-10-15 在沙箱里真实触发过）。
        """
        with patch.object(Path, 'unlink', side_effect=SystemExit(1)):
            resp = self.client.get(READY_URL)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['checks']['data_dir_writable']['ok'])

    # ------------------------------------------------------------------
    # 生产态不泄露
    # ------------------------------------------------------------------
    def test_ready_hides_host_details_when_debug_is_off(self):
        """打包版是 DEBUG=False。检查项的 detail 里带着 media 目录的绝对路径，
        以及驱动/OS 的报错文本 —— 那是宿主机文件系统布局，探针只需要 ok 标记。"""
        missing = Path(tempfile.gettempdir()) / 'lqdp-does-not-exist-9f3a'
        with override_settings(MEDIA_ROOT=missing, DEBUG=False):
            resp = self.client.get(READY_URL)

        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIsNone(resp.data['checks']['data_dir_writable']['detail'])
        self.assertFalse(resp.data['checks']['data_dir_writable']['ok'])
