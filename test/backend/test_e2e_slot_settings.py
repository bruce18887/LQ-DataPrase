"""slot settings 覆写档的契约测试。

判据来自 docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md §4.1：
slot 的库/媒体/临时区只能由 `LQDP_E2E_SLOT_DIR` 决定，**绝不通过 `data_dir` 重定向**
（`_migrate` 是 move 语义，`LQDP_SKIP_STORAGE_MIGRATION` 挡不住它 —— 见 lessons 2026-10-14 条目）。

每个用例都在子进程里加载 settings 档：同进程加载会污染主测试的 settings 与环境变量。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]

CHILD = (
    "import json,tempfile,django;"
    "django.setup();"
    "from django.conf import settings as s;"
    "from django.db import connection;"
    "connection.ensure_connection();"        # 真的建一次连接：只有覆盖 NAME 而留 postgres ENGINE 会在这里炸
    "print(json.dumps({'vendor':connection.vendor,"
    "'db':str(s.DATABASES['default']['NAME']),"
    "'media':str(s.MEDIA_ROOT),'temp':str(tempfile.tempdir)}))"
)


def nc(p: str) -> str:
    """Windows 的 TEMP 常是 8.3 短名，两侧都 realpath + normcase 才能比。"""
    return os.path.normcase(os.path.realpath(p))


def run_settings(settings_module: str, extra_env: dict):
    # 子进程 stdio 编码由这里钉死，父进程的 PYTHONIOENCODING / 本机 locale 都别想参与：
    # 用 text=True 而不给 encoding 时会按 cp936 解 UTF-8 中文报错，读取线程的
    # UnicodeDecodeError 被吞、stderr 变 None ⇒ 下面那些断言收到空值（2026-10-16 实测 6 条假红）。
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8',
           'DJANGO_SETTINGS_MODULE': settings_module, **extra_env}
    return subprocess.run([sys.executable, '-c', CHILD], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', env=env, cwd=str(ROOT))


class E2eSlotSettingsTests(SimpleTestCase):
    def test_db_media_and_temp_all_point_into_the_slot(self):
        slot = Path(tempfile.mkdtemp(prefix='lqdp-slot-settings-'))
        (slot / 'temp').mkdir(parents=True, exist_ok=True)
        out = run_settings('config.settings.e2e_slot', {'LQDP_E2E_SLOT_DIR': str(slot)})
        self.assertEqual(out.returncode, 0, out.stderr)
        parsed = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(parsed['vendor'], 'sqlite', 'slot 档必须真的用 sqlite，而不是继承 base 的 postgres')
        self.assertEqual(nc(parsed['db']), nc(str(slot / 'db.sqlite3')), parsed['db'])
        self.assertEqual(nc(parsed['media']), nc(str(slot / 'media')), parsed['media'])
        self.assertEqual(nc(parsed['temp']), nc(str(slot / 'temp')), parsed['temp'])

    def test_missing_slot_dir_fails_fast(self):
        """缺变量必须硬失败：静默回落到仓库根就等于让多个 e2e 进程共用同一份库。"""
        out = run_settings('config.settings.e2e_slot', {'LQDP_E2E_SLOT_DIR': ''})
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('LQDP_E2E_SLOT_DIR', out.stderr)

    def test_slot_dir_is_created_if_absent(self):
        slot = Path(tempfile.mkdtemp(prefix='lqdp-slot-settings-')) / 'not-yet-created'
        out = run_settings('config.settings.e2e_slot', {'LQDP_E2E_SLOT_DIR': str(slot)})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue((slot / 'temp').is_dir(), '临时区必须自己建出来，否则 tempfile 回落全局')

    def test_module_does_not_use_the_data_dir_redirect(self):
        """源码扫描：apply_system_config / data_dir 出现在这个档里就是设计缺陷。"""
        src = (ROOT / 'config' / 'settings' / 'e2e_slot.py').read_text(encoding='utf-8')
        self.assertNotIn('apply_system_config', src)
        self.assertNotIn('data_dir', src)

    def test_development_settings_still_resolve_to_repo_root(self):
        """非 slot 档不受影响：仓库根仍是 DB/MEDIA 的家（target==orig ⇒ 迁移分支不进入）。"""
        cfg_dir = Path(tempfile.mkdtemp(prefix='lqdp-dev-cfg-'))
        cfg = cfg_dir / 'system-config.json'
        cfg.write_text(json.dumps({'data_dir': str(ROOT).replace('\\', '/')}), encoding='utf-8')
        out = run_settings('config.settings.development', {'LQDP_SYSTEM_CONFIG_FILE': str(cfg)})
        self.assertEqual(out.returncode, 0, out.stderr)
        parsed = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(parsed['vendor'], 'sqlite')
        self.assertEqual(nc(parsed['db']), nc(str(ROOT / 'db.sqlite3')), parsed['db'])
        self.assertEqual(nc(parsed['media']), nc(str(ROOT / 'media')), parsed['media'])
