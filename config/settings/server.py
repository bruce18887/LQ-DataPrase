"""服务器形态档（局域网内约 20 人共用，无 nginx / 无反向代理）。

与桌面档 ``standalone.py`` 的区别就是本档存在的理由 —— 那几条桌面语义一条都不能给服务器用：

======================  =========================================  =================================
项                      桌面档（standalone）                       本档（server）
======================  =========================================  =================================
``BASE_DIR``            ``LQDP_BASE_DIR`` / exe 同级               ``LQDP_SERVER_BASE_DIR``，**必填**
``ALLOWED_HOSTS``       默认回环 ``localhost,127.0.0.1,[::1]``      ``DJANGO_ALLOWED_HOSTS``，**必填**，默认 ``*`` 被拒
``data_dir`` 搬迁       启用（``apply_system_config``）             不启用：那是设置页的桌面交互语义
``secret.key``          文件缺失时自动生成并落盘                    必须环境给定，不落盘副本
``SFTP_CONFIG_KEY``     从 secret.key 派生（salt ``sftp-config``）   **必须环境给定**，无派生回落
======================  =========================================  =================================

最后一条是 2026-10-14 批 2 恢复演练查出来的既有缺陷：``apps/sftp/crypto.py:32-33`` 的兜底
KDF 是 ``salt=b'dataphrase.sftp.config', iterations=390000``，而 ``standalone.py:170-173``
提前把 ``SFTP_CONFIG_KEY`` 设成 ``PBKDF2(SECRET_KEY, b'sftp-config', 100_000)`` —— 同一份库
换个档就解不开既有 token。本档不给任何回落，就是为了不让「换档即丢凭据」再发生一次。

同源服务 SPA（``config/urls.py`` 的 catch-all + ``assets/`` 挂载）与桌面档共用同一套实现：
没有 nginx，Django 自己就是对外进程，静态资源也必须由它发。

启动（源码形态）::

    DJANGO_SETTINGS_MODULE=config.settings.server \\
    LQDP_SERVER_BASE_DIR=/srv/lqdp DJANGO_ALLOWED_HOSTS=10.0.0.9,server01 \\
    SECRET_KEY=… SFTP_CONFIG_KEY=… LQDP_BOOTSTRAP_ADMIN_PASSWORD=… \\
    python manage.py runserver 0.0.0.0:8000 --noreload

首个管理员口令必须显式给：库是空的 → 首启现场建 superuser → 绑非回环又没设
``LQDP_BOOTSTRAP_ADMIN_PASSWORD`` 时 ``standalone._bootstrap`` 会直接拒绝启动。
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *  # noqa: F401,F403  (BASE_DIR, INSTALLED_APPS, REST_FRAMEWORK, ...)


def _require(env_name: str, hint: str) -> str:
    value = os.environ.get(env_name, '').strip()
    if not value:
        raise ImproperlyConfigured(
            f'{env_name} 是服务器形态的必填项，当前未设置。{hint}')
    return value


# ---------------------------------------------------------------------------
# 可写根目录 —— 库、media、静态产物全在这里，必须是**本地盘**
# ---------------------------------------------------------------------------
# WAL 依赖共享内存映射，把库放在网络盘/SMB 上不安全（docs/tasks/todo.md:2799-2801 已记）。
BASE_DIR = Path(_require(
    'LQDP_SERVER_BASE_DIR',
    '它决定 db.sqlite3 / media/ / staticfiles/ 的位置，必须是可写的本地盘，不能是映射盘。'
)).resolve()
import config.settings.base as _base  # noqa: E402
_base.BASE_DIR = BASE_DIR

# 桌面档用它做「改存储路径」的锚点；本档没有那个交互（那是设置页给单机用的），锚点即 BASE_DIR。
SYSTEM_CONFIG_ANCHOR_DIR = BASE_DIR
# 显式留痕：本档**不**调用 apps.common.system_config.apply_system_config。
SYSTEM_CONFIG_MIGRATION_ENABLED = False

DEBUG = False

# ---------------------------------------------------------------------------
# 对外暴露边界
# ---------------------------------------------------------------------------
# base.py:28 的默认值是 '*'，桌面档把它收窄成回环 —— 服务器档必须「显式给定才放行」，
# 忘记配置应当炸掉，而不是静默对全网卡开放。
_allowed_hosts = _require(
    'DJANGO_ALLOWED_HOSTS',
    '逗号分隔，例：10.0.0.9,server01。忘记设就不启动，免得静默继承 base.py 的 "*"。')
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(',') if h.strip()]

if '*' in ALLOWED_HOSTS and os.environ.get('LQDP_ALLOW_WILDCARD_HOSTS') != '1':
    raise ImproperlyConfigured(
        'ALLOWED_HOSTS 含 "*"：服务器形态拒绝通配。请改成具体 IP/主机名，'
        '确实要用通配就设 LQDP_ALLOW_WILDCARD_HOSTS=1（注意 Host 头校验随之失效）。')

# 匿名可读的端点面一律关掉（与桌面档同一判据：urls.py 按这个开关决定要不要挂 schema 路由）。
API_DOCS_ENABLED = False

# ---------------------------------------------------------------------------
# 密钥：两个都必须环境给定，不留任何「从别处派生」的暗道
# ---------------------------------------------------------------------------
# SECRET_KEY 走 base.py:33-38 的 fail-closed（DEBUG=False 时拒绝 django-insecure 默认值）。
if 'django-insecure' in SECRET_KEY:  # noqa: F405  (base 已导入)
    raise ImproperlyConfigured(
        'SECRET_KEY 不能是 base.py 的开发期默认值；它随源码分发，等同于没有密钥。')

# 见文件头那条缺陷说明：不给派生回落，缺了就别启动。
SFTP_CONFIG_KEY = _require(
    'SFTP_CONFIG_KEY',
    'Fernet 密钥（python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"）。'
    '它必须与 SECRET_KEY 相互独立，且此后所有档都用同一把，否则已存的 SFTP 口令解不开。')

# ---------------------------------------------------------------------------
# 数据库 / 媒体 / 静态
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        # busy_timeout=30000 由 apps/common/db_pragmas.py 在每个新连接上通过
        # connection_created 设置；这里不再写 OPTIONS，免得同一件事出现两处来源。
        'OPTIONS': {},
    }
}

MEDIA_ROOT = BASE_DIR / 'media'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# SPA 与桌面档同源：Vite 产物目录注册成模板目录 + 静态源，由 Django 直接发（无 nginx）。
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / 'frontend' / 'dist'
if _FRONTEND_DIST.is_dir():
    STATICFILES_DIRS = [_FRONTEND_DIST]
    TEMPLATES[0]['DIRS'] = [_FRONTEND_DIST]  # noqa: F405
else:
    # 没有前端产物时只跑 API；比「白屏且不报错」好，所以要留一行可见提示。
    import warnings
    warnings.warn(
        f'未找到前端产物 {_FRONTEND_DIST}：本档只服务 API，浏览器打开根路径会 404。'
        '先跑 npm run build。', RuntimeWarning, stacklevel=2)

if 'whitenoise.middleware.WhiteNoiseMiddleware' not in MIDDLEWARE:  # noqa: F405
    _sec_idx = MIDDLEWARE.index('django.middleware.security.SecurityMiddleware')  # noqa: F405
    MIDDLEWARE.insert(_sec_idx + 1, 'whitenoise.middleware.WhiteNoiseMiddleware')  # noqa: F405
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
# 服务器形态同样跳过首启 collectstatic（与桌面档同一理由：那正是「连不上服务器」超时的主因）。
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = False

# ---------------------------------------------------------------------------
# 无 broker / 无 Redis：与桌面档同样处理，装饰性的 Celery 不参与本形态
# ---------------------------------------------------------------------------
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'celery']  # noqa: F405
CELERY_BROKER_URL = ''
CELERY_RESULT_BACKEND = ''
REDIS_URL = ''
SFTP_SESSION_REDIS_URL = ''

# CORS 维持 base.py:83 的 True —— 只要 Electron 还用 file:// 加载本机档就收不掉。
# 收紧条件（本批不做）：Electron 全部改为 loadURL(http://服务器) 后 Origin 变同源，
# 届时另立 spec。见 docs/specs/2026-10-14-server-deployment-first-run-design.md §6.7。
