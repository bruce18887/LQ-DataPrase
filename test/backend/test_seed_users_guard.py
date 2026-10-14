"""seed_users 的弱口令互锁：生产档必须拒绝，除非显式 opt-in。

为什么需要这条钉子（2026-10-14 部署整改批 2）：`standalone.py:104-111` 已经有一道互锁
—— 非回环绑定 + 内置默认口令 = 拒绝启动。但它只管 `_bootstrap` 建 superuser 那一条路。
`seed_users` 是**第二条**能落地弱口令的通路：它硬编码 `admin/admin123`、`user/user123`、
`viewer/viewer123`，无参数，且实测不检查任何条件。在服务器形态上跑一次它，就等于把三个
已知口令挂到内网端口上，而上面那道互锁完全看不见这件事。

判据落在「一个用户都没被创建」上，而不是只断言抛错 —— 半路抛错但已经建了 admin 是最坏形态。

**读这份文件前要先知道的一件事**：Django 测试运行器会强制 ``DEBUG=False``
（``django.test.utils.setup_test_environment``），所以在测试里 ``settings.DEBUG`` 永远不是
开发档的真实值。本文件因此一律用 ``override_settings`` 显式设定三种情形，
而 ``test.backend.test_accounts_bootstrap.SeedUsersRepairTests`` 那组「只测修复语义」的
用例必须显式设 ``LQDP_ALLOW_WEAK_SEED=1`` 才能继续跑 —— 那是闸门的必然代价，不是回归。

运行：``manage.py test test.backend.test_seed_users_guard``
"""
import os
import sys
from unittest import mock

# test/backend/ → 项目根
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402
from django.test import TestCase, override_settings  # noqa: E402

User = get_user_model()


class SeedUsersGuardTests(TestCase):
    """生产档（DEBUG=False）默认拒执；dev 档行为逐字不变。"""

    def _run(self):
        call_command('seed_users')

    @override_settings(DEBUG=False)
    def test_refused_in_production_profile(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop('LQDP_ALLOW_WEAK_SEED', None)
            with self.assertRaises(CommandError) as ctx:
                self._run()
        self.assertIn('LQDP_ALLOW_WEAK_SEED', str(ctx.exception),
                      '报错要说清怎么放行，否则运维只能猜')

    @override_settings(DEBUG=False)
    def test_refusal_creates_no_users(self):
        """半路抛错却已经建了 admin 是最坏形态 —— 拒执必须是「一个都没动」。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop('LQDP_ALLOW_WEAK_SEED', None)
            with self.assertRaises(CommandError):
                self._run()
        self.assertEqual(User.objects.filter(username__in=('admin', 'user', 'viewer')).count(), 0)

    @override_settings(DEBUG=False)
    def test_explicit_opt_in_allows(self):
        with mock.patch.dict(os.environ, {'LQDP_ALLOW_WEAK_SEED': '1'}):
            self._run()
        self.assertTrue(User.objects.filter(username='admin').exists())

    @override_settings(DEBUG=True)
    def test_dev_profile_unchanged(self):
        """开发/e2e 依赖这三个种子账号，默认必须照旧放行。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop('LQDP_ALLOW_WEAK_SEED', None)
            self._run()
        self.assertEqual(User.objects.filter(username__in=('admin', 'user', 'viewer')).count(), 3)


if __name__ == '__main__':
    from django.conf import settings as dj_settings
    from django.test.utils import get_runner

    runner = get_runner(dj_settings)(['test.backend.test_seed_users_guard'], verbosity=2)
    sys.exit(runner.run_tests())
