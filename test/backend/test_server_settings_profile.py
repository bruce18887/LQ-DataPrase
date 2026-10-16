"""服务器 settings 档（config.settings.server）的启动期契约。

为什么用**子进程**而不是 ``override_settings``：本档的全部价值就在「导入期按环境
拒绝启动」——``override_settings`` 只改已加载的 globals，测不到 ``django.setup()``
那一刻的 fail-closed 判定。这与 ``test_sqlite_wal.py`` 用子进程造 -wal 残留同一取向：
判据必须走真实执行通路。

档存在的理由（spec §6.1）：``standalone.py`` 是**桌面档** —— ``ALLOWED_HOSTS`` 默认回环
（`:72-74`）、``BASE_DIR`` 取 ``LQDP_BASE_DIR``/exe 同级（`:36-40`）、``secret.key`` 与
``system_config.json`` 锚在 exe 旁（`:55-56`）、``SFTP_CONFIG_KEY`` 从 secret.key 派生
（`:170-173`）。这几条没有一条适合给局域网里 20 人共用的服务器用。

批 2 的恢复演练另外查出一条必须在本档堵死的坑：存密的 KDF 参数会随 profile 变
（crypto 兜底 ``dataphrase.sftp.config``/390k vs standalone 的 ``sftp-config``/100k）
→ **换档即解不开既有 token**。所以本档要求显式提供 ``SFTP_CONFIG_KEY``，不给任何派生回落。

运行：``manage.py test test.backend.test_server_settings_profile``
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON_BIN = os.path.join(REPO, '.venv', 'Scripts', 'python.exe')
if not os.path.isfile(PYTHON_BIN):  # 非 Windows 开发机
    PYTHON_BIN = os.path.join(REPO, '.venv', 'bin', 'python')

SECRET_KEY_MATERIAL = 'server-profile-test-key-not-for-production-0000000000'
FERNET_TEST_KEY = 'M' * 43 + '='  # 长度合法的 url-safe base64 Fernet key


def base_env(**overrides):
    """一份「配齐」的环境；用例只改掉自己要验的那一项（None 表示删掉该变量）。

    以 ``os.environ`` 为底而不是凭空造一份：``standalone`` 档会走
    ``system_config._default_data_dir`` → ``Path.home()``，没有 HOME/USERPROFILE 就炸
    （第一轮红就是这个原因，与被测行为无关）。
    """
    env = dict(os.environ)
    env.update({
        'PYTHONPATH': REPO,
        'PYTHONUNBUFFERED': '1',
        # 子进程的 stdio 编码必须**由本测试钉死**，不能跟着父进程或本机 locale 走：
        # 本档的报错消息是中文，父进程若带 PYTHONIOENCODING=utf-8（`scripts/e2e_nightly.mjs`
        # 就注入）而这里用 locale(cp936) 解码，subprocess 的读取线程会抛 UnicodeDecodeError
        # 并**被线程吞掉**，`result.stderr` 变成 None ⇒ 断言收到空串，稳定假红（2026-10-16 实测）。
        'PYTHONIOENCODING': 'utf-8',
        'DJANGO_SETTINGS_MODULE': 'config.settings.server',
        'LQDP_SERVER_BASE_DIR': tempfile.mkdtemp(prefix='lqdp_server_profile_'),
        'SECRET_KEY': SECRET_KEY_MATERIAL,
        'SFTP_CONFIG_KEY': FERNET_TEST_KEY,
        'DJANGO_ALLOWED_HOSTS': '10.0.0.9,server01',
    })
    # 桌面档的 LQDP_BASE_DIR 与本档的 server 目录是两条语义，探针里必须互不干扰。
    env.pop('LQDP_BASE_DIR', None)
    env.pop('LQDP_SYSTEM_CONFIG_FILE', None)
    env.pop('LQDP_BOOTSTRAP_ADMIN_PASSWORD', None)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_manage(argv_tail, **overrides):
    result = subprocess.run([PYTHON_BIN, 'manage.py'] + argv_tail,
                            cwd=REPO, env=base_env(**overrides),
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    return result.returncode, (result.stdout or '') + (result.stderr or '')


def run_python(code, env=None):
    result = subprocess.run([PYTHON_BIN, '-c', code], cwd=REPO,
                            env=env or base_env(), capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    return result.returncode, (result.stdout or '') + (result.stderr or '')


class ServerProfileRequiredEnvTests(unittest.TestCase):
    """缺关键环境时必须**拒启**，且报错要指名是哪个变量。"""

    def test_loads_when_fully_configured(self):
        code, out = run_manage(['check'])
        self.assertEqual(code, 0, f'配齐时必须能通过 check：\n{out}')

    def test_missing_base_dir_rejected(self):
        code, out = run_manage(['check'], LQDP_SERVER_BASE_DIR=None)
        self.assertNotEqual(code, 0)
        self.assertIn('LQDP_SERVER_BASE_DIR', out)

    def test_missing_allowed_hosts_rejected(self):
        """桌面档可以「默认回环」，服务器档不行 —— 忘记设就该炸，而不是静默只对回环开放
        （或更糟：继承 base.py:28 的 '*'）。"""
        code, out = run_manage(['check'], DJANGO_ALLOWED_HOSTS=None)
        self.assertNotEqual(code, 0)
        self.assertIn('DJANGO_ALLOWED_HOSTS', out)

    def test_wildcard_allowed_hosts_rejected(self):
        code, out = run_manage(['check'], DJANGO_ALLOWED_HOSTS='*')
        self.assertNotEqual(code, 0)
        self.assertIn('*', out)

    def test_wildcard_allowed_with_explicit_opt_in(self):
        code, out = run_manage(['check'], DJANGO_ALLOWED_HOSTS='*',
                               LQDP_ALLOW_WILDCARD_HOSTS='1')
        self.assertEqual(code, 0, f'显式 opt-in 后应放行：\n{out}')

    def test_missing_sftp_key_rejected(self):
        """存密密钥必须由环境给定：任何「从 SECRET_KEY 派生」的回落都会随 profile 变化，
        导致同一份库换档后解不开既有 token（批 2 实测到的缺陷）。"""
        code, out = run_manage(['check'], SFTP_CONFIG_KEY=None)
        self.assertNotEqual(code, 0)
        self.assertIn('SFTP_CONFIG_KEY', out)

    def test_insecure_secret_key_still_rejected(self):
        """base.py:33-38「DEBUG=False 时不许用 django-insecure 默认值」在本档同样生效。"""
        code, out = run_manage(['check'], SECRET_KEY='django-insecure-abc123')
        self.assertNotEqual(code, 0)
        self.assertIn('SECRET_KEY', out)


class ServerProfileValuesTests(unittest.TestCase):
    """配齐时的实际取值（探针自证打印，不只靠断言）。"""

    PROBE = (
        'import django; django.setup();'
        'from django.conf import settings as s;'
        'print("DB", s.DATABASES["default"]["NAME"]);'
        'print("HOSTS", s.ALLOWED_HOSTS);'
        'print("DEBUG", s.DEBUG);'
        'print("DOCS", s.API_DOCS_ENABLED);'
        'print("MEDIA", s.MEDIA_ROOT);'
        'print("ANCHOR", s.SYSTEM_CONFIG_ANCHOR_DIR);'
        'print("SFTP_SET", bool(s.SFTP_CONFIG_KEY));'
        'print("CORS_ALL", s.CORS_ALLOW_ALL_ORIGINS);'
        # 直接取属性（不用 getattr）：旗标被删掉时本探针会 AttributeError 而不是静默通过
        'print("MIGRATION", s.SYSTEM_CONFIG_MIGRATION_ENABLED);'
        'print("PATHS_VISIBLE", s.SYSTEM_PATHS_VISIBLE_TO_ALL)'
    )

    @classmethod
    def setUpClass(cls):
        cls.base_dir = tempfile.mkdtemp(prefix='lqdp_server_values_')
        # Windows 的 tempfile 常给出 8.3 短名（C:\Users\ADMINI~1\…），而档里用了
        # Path.resolve()（会把短名展平）—— 比较两侧都取 realpath，否则断言会被
        # 命名形式而非实际行为判红。
        cls.root = os.path.realpath(cls.base_dir).lower().rstrip(os.sep)
        cls.code, cls.out = run_python(cls.PROBE, env=base_env(LQDP_SERVER_BASE_DIR=cls.base_dir))
        assert cls.code == 0, cls.out

    def _under_root(self, value: str) -> bool:
        return os.path.realpath(value).lower().startswith(self.root)

    def _value(self, prefix):
        for line in self.out.splitlines():
            if line.startswith(prefix + ' '):
                return line.split(' ', 1)[1].strip()
        self.fail(f'探针未输出 {prefix}：\n{self.out}')

    def test_debug_off_and_docs_off(self):
        self.assertEqual(self._value('DEBUG'), 'False')
        self.assertEqual(self._value('DOCS'), 'False')

    def test_db_and_media_under_server_base_dir(self):
        for prefix in ('DB', 'MEDIA'):
            self.assertTrue(self._under_root(self._value(prefix)),
                            f'{prefix} 必须落在 LQDP_SERVER_BASE_DIR 内（实测值见 {self._value(prefix)}）')

    def test_hosts_come_from_env_verbatim(self):
        self.assertEqual(self._value('HOSTS'), "['10.0.0.9', 'server01']")

    def test_sftp_key_is_the_env_value(self):
        self.assertEqual(self._value('SFTP_SET'), 'True')

    def test_desktop_system_config_migration_not_applied(self):
        """本档不启用 data_dir 交互搬迁（那是桌面语义）；锚点即 BASE_DIR。"""
        self.assertEqual(self._value('MIGRATION'), 'False')
        self.assertTrue(self._under_root(self._value('ANCHOR')))

    def test_storage_paths_hidden_from_non_admins(self):
        """``GET /api/v1/system/paths/`` 在服务器形态只对管理员披露。

        桌面形态下这五个字段是用户自己的磁盘（viewer 看了不构成秘密，且界面要给他
        看「数据在哪」）；同一份代码跑在局域网服务器上时，它们披露的是服务器的
        目录结构、数据库文件与配置文件位置 —— 与使用者是谁无关。默认值留在
        base.py=True，所以必须由本档显式关掉，本用例就是钉住这一步。
        """
        self.assertEqual(self._value('PATHS_VISIBLE'), 'False')

    def test_cors_still_open_while_electron_file_protocol_exists(self):
        """D5：本批不收 CORS。这条断言是「现状留痕」而非认可 —— 收紧条件见 spec §6.7。"""
        self.assertEqual(self._value('CORS_ALL'), 'True')


class BootstrapInterlockTests(unittest.TestCase):
    """首个管理员口令的互锁在这条形态下必须真的咬人（spec §6.2）。"""

    PROBE = (
        'import django, sys\n'
        'django.setup()\n'
        'from django.conf import settings as s\n'
        'print("DBPATH", s.DATABASES["default"]["NAME"])\n'
        'import standalone\n'
        'try:\n'
        "    standalone._bootstrap('0.0.0.0')\n"
        "except SystemExit as exc:\n"
        "    print('REFUSED', exc)\n"
        "    sys.exit(0)\n"
        "print('BOOTSTRAPPED')\n"
    )

    def _run(self, **extra):
        """在**独立数据目录**里跑 ``_bootstrap``，并自证读的就是那份库。

        为什么必须显式钉 data_dir（2026-10-14 全量跑实测抓到的）：互锁只在「库里还没有
        superuser」时才触发，而 ``apply_system_config`` 在没有配置文件时会回落到默认数据目录
        （``~/LQ-DataPrase``，本机那份有 3 个账号）—— 于是本类既可能跳过互锁（红/绿随跑测顺序变），
        又在读真实库。判据取自 lessons「取证必须自证读的是哪份库」：探针打印解析后的 NAME，
        本方法断言它落在临时目录内，否则直接把测试判失败。
        """
        base_dir = tempfile.mkdtemp(prefix='lqdp_interlock_')
        cfg = os.path.join(base_dir, 'system_config.json')
        with open(cfg, 'w', encoding='utf-8') as fh:
            json.dump({'data_dir': base_dir.replace('\\', '\\\\')}, fh)
        env = base_env(DJANGO_SETTINGS_MODULE='config.settings.standalone',
                       LQDP_BASE_DIR=base_dir,
                       DJANGO_ALLOWED_HOSTS='0.0.0.0',
                       LQDP_SYSTEM_CONFIG_FILE=cfg,
                       **extra)
        env.pop('LQDP_SERVER_BASE_DIR', None)
        code, out = run_python(self.PROBE, env=env)
        for line in out.splitlines():
            if line.startswith('DBPATH '):
                resolved = line.split(' ', 1)[1].strip()
                self.assertTrue(
                    os.path.realpath(resolved).lower()
                    .startswith(os.path.realpath(base_dir).lower()),
                    f'探针跑到了临时目录之外的库上：{resolved} —— 会污染真实数据目录')
        return code, out

    def test_refuses_default_password_when_not_loopback(self):
        """只调 ``_bootstrap('0.0.0.0')``，不实际监听 —— 避免在这台局域网机器上真开一个对外端口。"""
        code, out = self._run()
        self.assertEqual(code, 0, f'互锁未触发：\n{out}')
        self.assertIn('REFUSED', out)
        self.assertIn('LQDP_BOOTSTRAP_ADMIN_PASSWORD', out)

    def test_allows_non_loopback_when_password_is_set(self):
        code, out = self._run(LQDP_BOOTSTRAP_ADMIN_PASSWORD='a-real-password-for-this-install')
        self.assertEqual(code, 0, f'设了口令就该放行：\n{out}')
        self.assertIn('BOOTSTRAPPED', out)
        self.assertNotIn('REFUSED', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
