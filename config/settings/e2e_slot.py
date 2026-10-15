"""e2e slot 专用配置覆写层。

一个变量决定全部隔离面：``LQDP_E2E_SLOT_DIR`` —— SQLite 库、``MEDIA_ROOT``、进程临时区
都落在它下面。缺这个变量就拒绝启动，绝不静默回落到共享目录。

刻意**只**导入 ``base``：``config.settings.development`` 在导入期会执行一次存储目录重定向
（move 语义：copy → verify → 删源），那正是 2026-10-14 毁掉仓库根 ``media/`` 与 ``db.sqlite3``
的那条通路。详见 docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md §4.1
与 docs/tasks/lessons.md 同日条目。
"""
import os
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *  # noqa: F401,F403
import config.settings.base as _base

_slot = os.environ.get('LQDP_E2E_SLOT_DIR', '').strip()
if not _slot:
    raise ImproperlyConfigured(
        'config.settings.e2e_slot 必须由 LQDP_E2E_SLOT_DIR 指定 slot 目录。'
        '缺该变量时回落到共享目录会让多个 e2e 进程读写同一份库与媒体，故直接拒绝启动。'
    )
_slot = Path(_slot).resolve()

# development 档里属于「开发态」的那三样，逐条显式给出 —— 不导入它，就不触发它的导入期重定向。
DEBUG = True
API_DOCS_ENABLED = True  # Playwright 的 webServer readiness 打 /api/schema/，靠这个开关放行

DATABASES = {
    **DATABASES,  # noqa: F405
    'default': {**DATABASES['default'], 'NAME': str(_slot / 'db.sqlite3')},  # noqa: F405
}

MEDIA_ROOT = _slot / 'media'
_base.MEDIA_ROOT = MEDIA_ROOT  # 有人直接读 base.MEDIA_ROOT

_slot_temp = _slot / 'temp'
_slot_temp.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_slot_temp)
for _key in ('TMP', 'TEMP', 'TMPDIR'):
    os.environ[_key] = tempfile.tempdir
