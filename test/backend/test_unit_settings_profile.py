"""后端测试档（config.settings.unit）的落盘面契约。

为什么用**子进程**：本档的全部价值就在「导入期把库 / MEDIA_ROOT / 临时区指到 test/ 下」，
``override_settings`` 只改已加载的 globals，测不到 ``django.setup()`` 那一刻的解析结果。
形状照 ``test_e2e_slot_settings.py``（同一取向）。

它要堵的历史缺陷（2026-10-16 实测）：后端套件跟着 ``development`` 档跑，而 ``development``
导入期会按仓库根 ``system_config.json`` 里的存储目录配置重定向 BASE_DIR，那份配置写着
**用户主目录** ⇒ ``settings.MEDIA_ROOT`` 落在真实数据目录下，7 个测试文件往里写了合成 CSV。
``Path.home()`` 是机器级的，连隔离工作树都挡不住。

运行：``manage.py test test.backend.test_unit_settings_profile``
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]

CHILD = (
    "import json,tempfile,django;"
    "django.setup();"
    "from django.conf import settings as s;"
    "from django.db import connection;"
    "connection.ensure_connection();"        # 真的建一次连接：只覆盖 NAME 而留别家 ENGINE 会在这里炸
    "print(json.dumps({'vendor':connection.vendor,"
    "'db':str(s.DATABASES['default']['NAME']),"
    "'media':str(s.MEDIA_ROOT),'temp':str(tempfile.tempdir)}))"
)


def nc(p: str) -> str:
    """Windows 的 TEMP 常是 8.3 短名，两侧都 realpath + normcase 才能比。"""
    return os.path.normcase(os.path.realpath(p))


def base_env(**overrides):
    """以 ``os.environ`` 为底（子进程要能 import django 与项目包），用例只改自己要验的那项。

    ``None`` 表示删掉该变量 —— 默认数据根那条判据必须建立在「变量确实没设」上，
    而不是「假设本机没设」。
    """
    env = dict(os.environ)
    env.update({
        'PYTHONPATH': str(REPO),
        'PYTHONUNBUFFERED': '1',
        # 子进程 stdio 编码在这里钉死：不给 encoding 的 `text=True` 会按本机 cp936 去解
        # 子进程的 UTF-8 中文报错，异常被读取线程吞掉后 stderr 变成 None（同轮实测的假红根因）。
        'PYTHONIOENCODING': 'utf-8',
        'DJANGO_SETTINGS_MODULE': 'config.settings.unit',
    })
    # 这两个是别的档的隔离面，留在环境里只会让人误判是本档解析出来的。
    env.pop('LQDP_E2E_SLOT_DIR', None)
    env.pop('LQDP_UNIT_DATA_DIR', None)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_settings(extra_env: dict):
    out = subprocess.run([sys.executable, '-c', CHILD], capture_output=True, text=True,
                         encoding='utf-8', errors='replace',
                         env=base_env(**extra_env), cwd=str(REPO))
    if out.returncode != 0:
        raise AssertionError(f'子进程加载 unit 档失败（rc={out.returncode}）\n{out.stderr}')
    return json.loads(out.stdout.strip().splitlines()[-1])


class UnitSettingsProfileTests(SimpleTestCase):
    def test_default_data_root_is_test_unit_data(self):
        """没给变量 ⇒ 三份落盘面必须都在 ``test/unit-data`` 下，一处都不能在用户真实数据目录。

        注意反例基线是 ``~\\LQ-DataPrase``（那个档存着用户真实的库与 media），
        **不是** ``Path.home()`` —— 仓库根本身就在家目录下，拿 home 比前缀会永远假红。
        """
        parsed = run_settings({'LQDP_UNIT_DATA_DIR': None})
        real_data_dir = nc(str(Path.home() / 'LQ-DataPrase'))
        expected = nc(str(REPO / 'test' / 'unit-data'))
        for key in ('db', 'media', 'temp'):
            self.assertTrue(nc(parsed[key]).startswith(expected),
                            f'{key}={parsed[key]} 没落在 {expected} 下')
            self.assertFalse(nc(parsed[key]).startswith(real_data_dir),
                             f'{key}={parsed[key]} 落进了用户真实数据目录 —— 就是这次要堵的泄漏')
        self.assertEqual(parsed['vendor'], 'sqlite', '必须真的用 sqlite，而不是继承到别家的形状')

    def test_env_var_relocates_all_three(self):
        """并行/CI 想换地方只能靠这一个变量，且库/media/临时区要一起走。"""
        unit = Path(tempfile.mkdtemp(prefix='lqdp-unit-settings-'))
        parsed = run_settings({'LQDP_UNIT_DATA_DIR': str(unit)})
        self.assertEqual(nc(parsed['db']), nc(str(unit / 'db.sqlite3')), parsed['db'])
        self.assertEqual(nc(parsed['media']), nc(str(unit / 'media')), parsed['media'])
        self.assertEqual(nc(parsed['temp']), nc(str(unit / 'temp')), parsed['temp'])

    def test_temp_dir_created_even_when_data_root_absent(self):
        """数据根不存在也要自己建出来，否则 tempfile 静默回落系统临时区。"""
        unit = Path(tempfile.mkdtemp(prefix='lqdp-unit-settings-')) / 'not-yet-created'
        parsed = run_settings({'LQDP_UNIT_DATA_DIR': str(unit)})
        self.assertTrue((unit / 'temp').is_dir(), parsed['temp'])

    def test_profile_does_not_use_the_storage_redirect(self):
        """源码扫描：那条导入期重定向（``apply_system_config``）出现在本档就是设计缺陷 ——
        它是 move 语义（copy → verify → 删源），见 e2e_slot 文件头与 lessons 2026-10-14。
        """
        src = (REPO / 'config' / 'settings' / 'unit.py').read_text(encoding='utf-8')
        self.assertNotIn('apply_system_config', src)
        self.assertNotIn('data_dir', src)                      # 那个键的小写形式也不许出现
        self.assertNotIn('config.settings.development', src)   # 导入它 = 把重定向请回来

    def test_direct_run_files_do_not_select_the_development_profile(self):
        """源码扫描：``test/`` 下每个 ``setdefault(DJANGO_SETTINGS_MODULE, ...)`` 都不许指向 development。

        这行在经 runner 跑时是惰性的（``manage.py`` 已设过档），只在**直跑单个文件**时生效。
        而 development 导入期会按系统存储路径解析 BASE_DIR，``MEDIA_ROOT`` 跟着走 ——
        2026-10-16 实测：隔离工作树里直跑会把合成 CSV 写进 ``~/LQ-DataPrase/media/data/``
        （``Path.home()`` 是机器级的，工作树隔离不了它）。落盘面因此必须留在 ``test/unit-data``。

        只匹配那一行的完整形态，不匹配注释/文档里的提及 —— 本文件自己就写着那个模块名。
        """
        needle = ("os.environ.setdefault('DJANGO_SETTINGS_MODULE', "
                  "'config.settings.development')")
        offenders = [
            str(p.relative_to(REPO).as_posix())
            for p in sorted((REPO / 'test').rglob('*.py'))
            if '__pycache__' not in p.parts and needle in p.read_text(encoding='utf-8')
        ]
        self.assertEqual([], offenders, '这些文件直跑时会写用户真实数据目录')

    def test_standalone_is_only_selected_by_the_asset_regression_it_needs_it_for(self):
        """``config.settings.standalone`` 在白名单里：它把 ``frontend/dist`` 注册进
        ``TEMPLATES[0]['DIRS']``，换档会让资产视图 404、回归测不出来。
        新增文件想用这一档必须先说清为什么不是 ``unit``。
        """
        needle = ("os.environ.setdefault('DJANGO_SETTINGS_MODULE', "
                  "'config.settings.standalone')")
        users = [
            str(p.relative_to(REPO).as_posix())
            for p in sorted((REPO / 'test').rglob('*.py'))
            if '__pycache__' not in p.parts and needle in p.read_text(encoding='utf-8')
        ]
        self.assertEqual(['test/backend/test_static_assets.py'], users)


class ManagePyProfileRoutingTests(SimpleTestCase):
    """``manage.py`` 的位置判断：只有 ``test`` 命令换档，其余命令行为不变。"""

    def setUp(self):
        sys.path.insert(0, str(REPO))
        self.addCleanup(sys.path.remove, str(REPO))
        self.manage = importlib.import_module('manage')

    def test_only_the_test_command_selects_unit_profile(self):
        cases = {
            ('manage.py', 'test'): 'config.settings.unit',
            ('manage.py', 'test', 'test.backend'): 'config.settings.unit',
            ('manage.py', 'runserver', '8000'): 'config.settings.development',
            ('manage.py', 'migrate'): 'config.settings.development',
            ('manage.py', 'shell', '-c', 'x'): 'config.settings.development',
            ('manage.py',): 'config.settings.development',
        }
        for argv, expected in cases.items():
            self.assertEqual(self.manage.default_settings_module(list(argv)), expected, argv)

    def test_every_profile_it_can_pick_is_importable(self):
        """判据不能只比字符串 —— 写错的模块名一样能过前一条。"""
        for argv in (['manage.py', 'test'], ['manage.py', 'runserver']):
            importlib.import_module(self.manage.default_settings_module(argv))
