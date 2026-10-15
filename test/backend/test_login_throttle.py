"""契约测试：登录端点的 IP 级限流。

背景（2026-10-15 架构评审 P0-4）。``apps/accounts/views.py`` 早就有**账号级**锁定
（连续 5 次失败 → ``423 LOCKED`` + 锁 15 分钟），所以「爆破一个已知用户名」这条路径
一直是堵着的。缺的是 **IP 维度**：

* 同一台机器拿一堆**不同**用户名试探 —— 每个用户名只失败一次，账号锁定永不触发。
* 反向的 DoS —— 攻击者反复打某个真实用户名，把该用户锁在门外 15 分钟。

``ScopedRateThrottle`` + ``throttle_scope = 'login'`` 补的就是这两条。它按
「已认证则用 user.pk，否则用客户端 IP」取键；登录请求恒为匿名
（``LoginView.authentication_classes`` 是空列表），所以这里是纯 IP 限流。

两条实现约束在本文件里被钉住：

1. ``SimpleRateThrottle.THROTTLE_RATES`` 是**类属性**，在 import 时就从
   ``api_settings`` 绑定好了 —— 所以 ``override_settings(REST_FRAMEWORK=...)``
   改不动它，必须 ``patch.object`` 打类属性。这是 DRF 的已知坑。
2. 限流历史存在 cache 里，会跨用例泄漏，故 ``setUp`` 里 ``cache.clear()``。
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

LOGIN_URL = '/api/v1/auth/login/'


class LoginThrottleTests(TestCase):
    def setUp(self):
        # 限流计数落在 Django cache（LocMemCache），不清会跨用例互相污染。
        cache.clear()
        self.client = APIClient()

    def _post(self, username='nosuchuser'):
        return self.client.post(
            LOGIN_URL, {'username': username, 'password': 'wrong'}, format='json',
        )

    # ------------------------------------------------------------------
    # 限流确实会触发
    # ------------------------------------------------------------------
    def test_ip_throttle_fires_after_the_budget_is_spent(self):
        with patch.object(SimpleRateThrottle, 'THROTTLE_RATES', {'login': '3/min'}):
            codes = [self._post().status_code for _ in range(4)]

        # 前 3 次放行（凭据错 → 401），第 4 次被限流挡下。
        self.assertEqual(codes[:3], [status.HTTP_401_UNAUTHORIZED] * 3)
        self.assertEqual(codes[3], status.HTTP_429_TOO_MANY_REQUESTS)

    def test_throttle_sprays_many_usernames_from_one_ip(self):
        """账号锁定拦不住这个 —— 每个用户名只失败一次。IP 限流能。"""
        with patch.object(SimpleRateThrottle, 'THROTTLE_RATES', {'login': '5/min'}):
            codes = [
                self._post(username=f'victim{i}').status_code
                for i in range(6)
            ]

        self.assertEqual(codes.count(status.HTTP_429_TOO_MANY_REQUESTS), 1)
        self.assertEqual(codes[-1], status.HTTP_429_TOO_MANY_REQUESTS)

    def test_throttled_response_uses_the_global_error_envelope(self):
        """429 由全局异常处理器（apps/common/exceptions.py）产出，
        不是 LoginView 自己的 ``_error()`` 信封 —— 前端 formatError 走
        ``data.message`` 分支就能显示中文，无需给 ERROR_CODE_MAP 加条目。"""
        with patch.object(SimpleRateThrottle, 'THROTTLE_RATES', {'login': '1/min'}):
            self._post()
            resp = self._post()

        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(resp.data['code'], 'throttled')
        self.assertIn('频繁', resp.data['message'])

    # ------------------------------------------------------------------
    # 但不会误伤正常流量
    # ------------------------------------------------------------------
    def test_configured_rate_survives_a_normal_burst(self):
        """守卫**开发/测试档的实际配置值**，而不是断言一个写死的数字。

        这个档（config.settings.development）是 Playwright 不带 slot 池时
        webServer 用的后端，几百条用例共用一个回环 IP。若有人把
        LQDP_LOGIN_THROTTLE_RATE 调回 base 的 20/min，e2e 会开始随机 429
        —— 那条故障很难归因到限流上，所以在这里先炸。
        """
        codes = [self._post().status_code for _ in range(30)]

        self.assertNotIn(status.HTTP_429_TOO_MANY_REQUESTS, codes)

    def test_health_probes_are_not_throttled(self):
        """启动门必须永远可达：探针一旦被 429，调用方分不清
        「后端没起来」与「被限流了」。"""
        with patch.object(SimpleRateThrottle, 'THROTTLE_RATES', {'login': '1/min'}):
            for _ in range(5):
                self._post()  # 先把 login 预算打光

        for url in ('/api/v1/health/', '/api/v1/ready/'):
            resp = self.client.get(url)
            self.assertNotEqual(
                resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS, url,
            )
