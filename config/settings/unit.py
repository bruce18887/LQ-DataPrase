"""后端测试套件（T1 层）专用配置覆写档。

一个变量决定全部隔离面：``LQDP_UNIT_DATA_DIR`` —— SQLite 库、``MEDIA_ROOT``、进程临时区
都落在它下面；缺该变量时回落到 ``<仓库根>/test/unit-data``（单元跑只该有一份共享数据根，
所以这里**允许**默认值，与 ``e2e_slot`` 「缺变量就硬失败」相反 —— 那个档要并行开 N 个 slot，
静默回落等于让 N 个进程读写同一份库）。

为什么需要这一档：这些测试历史上跑在 ``development``，而 development 导入期会按系统存储路径
配置解析 BASE_DIR，``MEDIA_ROOT`` 跟着一起走。仓库根那份配置写着**用户主目录**时，测试就写进了
真实数据目录。2026-10-16 实测：在隔离工作树跑后端全量后，``~/LQ-DataPrase/media/data/<测试用户名>/``
多出 4 个合成 CSV —— ``Path.home()`` 是机器级的，工作树隔离不了它。
本档刻意**只**导入 ``base``，不经那条重定向通路（它是 move 语义，见 e2e_slot 文件头与
docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md §4.1），落盘面因此恒定留在 ``test/`` 下。

e2e 浏览器档不用本档：串行与 slot 都复用 ``config.settings.e2e_slot``（数据根 ``test/e2e-data``
或各 slot 自己的目录）。
"""
import os
import tempfile
from pathlib import Path

from config.settings.base import *  # noqa: F401,F403  (BASE_DIR, REST_FRAMEWORK, DATABASES, ...)

import config.settings.base as _base

# apps/common/system_config.py 里那个键的小写形式刻意不出现在本文件 ——
# test/backend/test_unit_settings_profile.py 有条源码扫描钉「本档不得使用该重定向」。
_REPO_ROOT = Path(__file__).resolve().parents[2]

_unit_raw = os.environ.get('LQDP_UNIT_DATA_DIR', '').strip()
_unit = Path(_unit_raw).resolve() if _unit_raw else _REPO_ROOT / 'test' / 'unit-data'

# 与 development 逐项对齐，本档唯一的差异面应该只有「库/media/临时区落在哪」。
DEBUG = True
API_DOCS_ENABLED = True

# 与 development 同值同理由：几百条用例共用一个回环 IP，base 的 20/min 会让它们互相踩。
# 重建而非原地改，免得 base.py 的 dict 被改掉。
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_THROTTLE_RATES': {
        **REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {}),  # noqa: F405
        'login': os.environ.get('LQDP_LOGIN_THROTTLE_RATE', '200/min'),
    },
}

# 整体给出 DATABASES，不只覆盖 NAME：与 e2e_slot 同一条理由 —— 避免任何
# 「继承到别人档的形状」的可能（历史上 base 曾是 PostgreSQL 形状，只覆盖 NAME 会去连 5432）。
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(_unit / 'db.sqlite3'),
    }
}

MEDIA_ROOT = _unit / 'media'
_base.MEDIA_ROOT = MEDIA_ROOT  # 有人直接读 base.MEDIA_ROOT

_unit_temp = _unit / 'temp'
_unit_temp.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_unit_temp)
for _key in ('TMP', 'TEMP', 'TMPDIR'):
    os.environ[_key] = tempfile.tempdir
