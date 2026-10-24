"""T1：Django 的 console 日志必须落 **stdout**，且中文按 UTF-8 到达。

根因链（2026-10-24 复核）：``config/settings/base.py`` 以 Django 的 ``DEFAULT_LOGGING``
为底改配置，而里面两个 handler 都是裸 ``logging.StreamHandler`` —— 默认流是 **stderr**。
打包版里 Electron 对子进程 stderr 一律记 ERROR（``electron/backend.ts:345-347``），于是
runserver 的请求行与 ``apps.*`` 的 INFO/WARNING 全被标成 ERROR，真崩溃混在里面看不出来。
同时 Windows 上 stderr 的默认编码是本机 cp936，Electron 用 ``data.toString()``（UTF-8）解 ⇒ 中文乱码。

判据形状：在**子进程**里真的发日志、看它落到哪条流（`redirect_stdout` 没用 ——
handler 在 dictConfig 那一刻就绑定了流对象）。三条各拒一种变异：
① handler 的 ``stream`` 配置被删；② 只改了 ``console`` 忘了 ``memory_console``；
③ 编码没钉住（中文哨兵到不了 stdout）。

跑法：python manage.py test test.backend.test_logging_streams
"""
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]

CHILD = r'''
import os, sys, django
django.setup()
import logging
logging.getLogger("django").warning("SENTINEL-DJANGO")
logging.getLogger("apps.common.memory").info("SENTINEL-MEMORY \u4e2d\u6587\u54e8\u5175-\u5185\u5b58\u9884\u7b97")
logging.getLogger("lqdp.sentinel.unconfigured").warning("SENTINEL-LASTRESORT")
sys.stdout.flush(); sys.stderr.flush()
'''


class LoggingStreamConfigTests(SimpleTestCase):
    def test_both_console_handlers_declare_stdout(self):
        """配置层：两个 handler 都得显式给 stream —— 只改一个是本批最容易犯的错。"""
        handlers = settings.LOGGING['handlers']
        for name in ('console', 'memory_console'):
            self.assertIn('stream', handlers[name], f'{name} 没给 stream，默认就是 stderr')
            self.assertEqual('ext://sys.stdout', handlers[name]['stream'], name)

    def test_the_default_would_have_been_stderr_without_the_override(self):
        """对照组：证明「显式 stdout」确实在改变行为，而不是 Django 本来就用 stdout。

        少了这条，上一断言可能只是在为一个本来就成立的事实记功。
        """
        import copy
        from django.utils.log import DEFAULT_LOGGING
        raw = copy.deepcopy(DEFAULT_LOGGING)['handlers']['console']
        self.assertNotIn('stream', raw)
        import logging
        probe = logging.StreamHandler()          # 不指定 stream 的那个默认
        try:
            self.assertIs(probe.stream, sys.stderr)
        finally:
            probe.close()


class LoggingStreamRuntimeTests(SimpleTestCase):
    """运行时层：真的发一条，看它出现在哪条流上。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = {**os.environ,
               'DJANGO_SETTINGS_MODULE': 'config.settings.unit',
               # 与 Electron 侧 buildBackendEnv 同一口径；不钉住的话本用例在
               # 中文 Windows 上会随父环境漂（testing-gates §4 那条同族坑）
               'PYTHONIOENCODING': 'utf-8'}
        cls.result = subprocess.run(
            [sys.executable, '-c', CHILD], cwd=str(REPO), env=env,
            capture_output=True, text=True, encoding='utf-8', errors='replace')

    def test_sentinels_land_on_stdout_not_stderr(self):
        self.assertEqual(0, self.result.returncode, self.result.stderr[-800:])
        out, err = self.result.stdout, self.result.stderr
        for tag in ('SENTINEL-DJANGO', 'SENTINEL-MEMORY'):
            self.assertIn(tag, out, f'{tag} 没出现在 stdout')
            self.assertNotIn(tag, err, f'{tag} 仍在 stderr —— Electron 会把它记成 ERROR')

    def test_chinese_reaches_stdout_intact(self):
        """乱码的可见结果就是这条：编码没钉住时这里拿到的是替换字符或问号。"""
        self.assertIn('中文哨兵-内存预算', self.result.stdout)
        self.assertNotIn('内存预算', self.result.stderr)

    def test_unconfigured_logger_falls_to_stderr_via_lastresort(self):
        """⚠ 本批**没修**的残留，钉成明账而不是留成意外。

        Django 的 ``DEFAULT_LOGGING`` 不配置 ``root``，所以除 ``django*`` 与
        ``apps.common.memory`` 之外的 logger（含其余 ``apps.*``）在 WARNING+ 时走
        logging 的 ``lastResort`` handler —— 它直写 **stderr**，于是仍会被 Electron
        记成 ERROR。要不要给 ``root``/``apps`` 挂 stdout handler 是日志噪声取向，
        待拍板（本仓 :55-57 那段注释说明「apps.* 的 INFO 被丢弃」当初是有意的）。
        """
        self.assertIn('SENTINEL-LASTRESORT', self.result.stderr)
        self.assertNotIn('SENTINEL-LASTRESORT', self.result.stdout)
