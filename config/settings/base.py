import copy
from datetime import timedelta
from pathlib import Path
import os

from django.utils.log import DEFAULT_LOGGING

BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Security-critical settings
# ---------------------------------------------------------------------------
# ``SECRET_KEY`` and ``SFTP_CONFIG_KEY`` are read from the environment so the
# same code can run in development, CI, and production without leaking
# real keys into the repo. In production (DEBUG=False) both MUST be set —
# the dev fallback below is intentionally insecure (django-insecure prefix)
# to make accidental deployment loud and obvious.
_SECRET_KEY_DEFAULT = 'django-insecure-b&@*da(*2$=ac%q!!96zhi%=64@$j7u#$vu0qfv34@%no50=)q'
SECRET_KEY = os.environ.get('SECRET_KEY') or _SECRET_KEY_DEFAULT

# NOTE: the default stays True on purpose. This module is a *mixin* imported by
# development.py / standalone.py (both of which set DEBUG explicitly), and the
# SECRET_KEY guard below runs at import time -- defaulting to False here would
# make ``from config.settings.base import *`` raise ImproperlyConfigured before
# development.py ever gets to set DEBUG=True, breaking every ``manage.py``
# invocation that has no SECRET_KEY in the environment. The shipped product uses
# config.settings.standalone, which hard-codes DEBUG=False.
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes', 'on')

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',')

# In production, refuse to start with the default secret key — it is signed
# ``django-insecure-`` and is publicly known. CI/dev set ``DJANGO_DEBUG=True``
# so the fallback is fine for those.
if not DEBUG and (SECRET_KEY == _SECRET_KEY_DEFAULT or 'django-insecure' in SECRET_KEY):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        'SECRET_KEY must be set to a real value in production '
        '(DJANGO_DEBUG=False). Generate one with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`.'
    )

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# ``apps.common.memory`` 在首次取预算时打一行 INFO（``内存预算: ...``），这是运维
# 判断「本机预算是否已被别的进程压住」的唯一入口。Django 默认配置只给 ``django``
# 命名空间挂了控制台 handler，``apps.*`` 的 INFO 会被直接丢弃 —— 不显式配置，
# 这行日志在开发档与服务器档都看不见。
#
# 以 Django 的 DEFAULT_LOGGING 为底再挂一个 scoped logger（而不是整份重写）：
# 保留 runserver 的请求日志与 mail_admins 行为。memory 用独立的 handler，刻意
# 不带 ``require_debug_true`` —— 生产档（DEBUG=False）同样要看到预算行。
LOGGING = copy.deepcopy(DEFAULT_LOGGING)
LOGGING['disable_existing_loggers'] = False
LOGGING['formatters']['memory'] = {
    'format': '{asctime} {levelname} {name}: {message}',
    'style': '{',
}
LOGGING['handlers']['memory_console'] = {
    'class': 'logging.StreamHandler',
    'formatter': 'memory',
}
LOGGING['loggers']['apps.common.memory'] = {
    'handlers': ['memory_console'],
    'level': 'INFO',
    'propagate': False,
}

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    # Required for BLACKLIST_AFTER_ROTATION=True (token rotation in
    # /auth/refresh/). Without it the blacklist() call is silently
    # swallowed and old refresh tokens keep working forever.
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'apps.common',
    'apps.accounts',
    'apps.datafiles',
    'apps.analysis',
    'apps.dashboard',
    'apps.batch_report',
    'apps.buyoff',
    'apps.gage',
    'apps.export',
    'apps.sftp',
    'apps.jobs',
    'apps.weight',
]

MIDDLEWARE = [
    # 放最外层：Django 对请求方向自上而下执行，所以这一层量到的是「整个请求」的耗时，
    # 与其它中间件的开销无关 —— 运维要归因的正是用户感知的那段时间。
    # 纯内存采样（有界环形 + 一把锁），不写盘不打库；见 apps/common/metrics.py。
    'apps.common.metrics.MetricsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    # GZipMiddleware 已于 2026-08-11 移除：大 JSON（browse 68MB）压缩 CPU
    # 实测 3.6s，而打包版/开发版 Django 直连 localhost 传输仅 ~0.2s，净损失。
    # 若未来部署到 LAN/WAN，改用 nginx gzip 或定向压缩（勿全局恢复）。
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOW_ALL_ORIGINS = True
# ^ Deliberately still permissive. The packaged Electron app loads the SPA via
# ``win.loadFile()`` (a ``file://`` document, whose Origin header is ``null``)
# while the API lives on ``http://localhost:<port>`` -- so every production
# request is cross-origin and narrowing this list would break the shipped app.
# In browser/dev mode the Vite server *proxies* ``/api`` to :8000, so no CORS
# is involved there either. The proper fix is to serve the SPA over http:// from
# Django (same origin) and then turn CORS off entirely; that changes how the
# packaged app loads and must be validated against a real installer build.
# Mitigations that ARE in place: the backend binds 127.0.0.1 by default, and
# ``standalone._bootstrap`` refuses a non-loopback bind with the default
# credential. Residual risk: a malicious web page can still reach the loopback
# API -- it just cannot authenticate without a token.

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------------------
# Database — SQLite
# ---------------------------------------------------------------------------
# This used to default to PostgreSQL (with a hardcoded ``ate_password``), but
# every profile that actually ships overrode it: development.py, standalone.py,
# server.py and e2e_slot.py all define SQLite. So the PG branch was unreachable
# dead code carrying a plaintext credential, and ``psycopg2-binary`` was a
# dependency that was never even installed in the venv. Removed 2026-10-15
# (architecture review P0-1b). SQLite is the real engine for both shipped
# profiles — see docs/reference/architecture-review-2026-10-15.md.
#
# ``busy_timeout`` is applied per-connection by ``apps/common/db_pragmas.py``
# via the ``connection_created`` signal, so it is deliberately not duplicated
# in OPTIONS here.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

AUTH_USER_MODEL = 'accounts.User'

REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'apps.common.exceptions.custom_exception_handler',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    # Fail-closed default. All 23 existing DRF views declare permission_classes
    # explicitly (LoginView uses AllowAny), so this changes no current behaviour
    # -- it only stops a *future* view that forgets the declaration from being
    # anonymously reachable, which is what DRF's own AllowAny fallback would do.
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    # 全局分页只对「有 list() 的三个视图」生效：/files/（自带 DataFilePagination）、
    # /auth/users/、/files/history/；其余端点都是 @action，不经过 paginate_queryset。
    # 别删 PAGE_SIZE：PageNumberPagination.page_size 在类定义时绑定 api_settings.PAGE_SIZE，
    # 置空会让「显式声明了 pagination_class」的 DataFilePagination 也一起退化成裸数组。
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # 刻意不设 DEFAULT_FILTER_BACKENDS：全仓只有 DataFileViewSet 用到过滤，
    # 挂在全局只会让读者以为「所有列表都能过滤/搜索」。声明见该视图的 filter_backends。
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Rate table only — deliberately NO ``DEFAULT_THROTTLE_CLASSES``.
    #
    # Scoping the throttle to the login endpoint (via ``ScopedRateThrottle`` +
    # ``throttle_scope``) rather than globally is intentional: this app has
    # several high-frequency polling paths (chart dock, SFTP search progress)
    # and a 376-case e2e suite that hammers the API from a single IP. A global
    # throttle would start returning 429 to legitimate traffic long before it
    # inconvenienced an attacker.
    #
    # What this complements (not replaces): ``apps/accounts/views.py`` already
    # locks an ACCOUNT after 5 failures (423 + 15 min). That defends a known
    # username; it does nothing against one host spraying many usernames, and it
    # is itself a DoS vector (an attacker can lock real users out). The IP
    # dimension below closes both.
    'DEFAULT_THROTTLE_RATES': {
        'login': os.environ.get('LQDP_LOGIN_THROTTLE_RATE', '20/min'),
    },
}

SIMPLE_JWT = {
    # 默认仍是 30 min；只有 Playwright 的 webServer 会把它设大（LQDP_ACCESS_TOKEN_MINUTES）。
    # 原因：夜间全量轮在 CI=1 下强制 workers=1，一轮要跑 40–100 min，而 storageState 是
    # 开跑时铸的**一份** token —— 每条新用例都从同一个文件重取它，刷新后的新值只活在该
    # context 里。30 min 之后才被调度的用例会一律被路由守卫踢回 /login（2026-10-13 三次
    # 真跑实测：30min 前红率 1%，30min 后 90%）。开发态 workers=6 全程 6 min，所以撞不到。
    'ACCESS_TOKEN_LIFETIME': timedelta(
        minutes=int(os.environ.get('LQDP_ACCESS_TOKEN_MINUTES', '30'))
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

LANGUAGE_CODE = 'zh-hans'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_TZ = True

STATIC_URL = 'static/'

MEDIA_URL = 'media/'

MEDIA_ROOT = BASE_DIR / 'media'

# NOTE: there is deliberately no CELERY_* block here. Celery was removed on
# 2026-10-15 (architecture review P0-1): the repo never had a single
# ``@shared_task``, and both shipped profiles already stripped the app from
# INSTALLED_APPS, so the settings were pure dead weight that made every reader
# believe a broker was part of the runtime. The real async story is
# **in-process** pools — ProcessPoolExecutor for export chart rendering
# (apps/export/export_batch_charts_xlsx.py) and ThreadPoolExecutor for SFTP
# search (apps/sftp/search/runner.py). See apps/CLAUDE.md.

SPECTACULAR_SETTINGS = {
    'TITLE': 'LQ-DataPrase API',
    'DESCRIPTION': 'LQ-DataPrase 数据分析平台 API 文档',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# Whether /api/schema/ and its Swagger UI are routed at all. drf-spectacular's
# views default to AllowAny, so the shipped build turns the routes off rather
# than exposing the whole endpoint surface anonymously. See config/urls.py.
# development.py keeps it on. Note this is purely an API-docs decision — the
# e2e readiness probe uses /api/v1/health/ (apps/common/health.py), not the
# schema route, precisely so the two concerns stop being coupled.
API_DOCS_ENABLED = True

# Whether a non-administrator may read ``GET /api/v1/system/paths/`` — the
# effective data dir / db file / media dir / temp dir / config file of *this*
# install. On a desktop these are the user's own paths (the settings page shows
# them to every role on purpose). ``config/settings/server.py`` turns it off:
# there the same fields describe the server's filesystem, which no ordinary
# account has a reason to see. Enforcement is in the API, not in the UI.
SYSTEM_PATHS_VISIBLE_TO_ALL = True

SESSION_COOKIE_AGE = 1800
SESSION_SAVE_EVERY_REQUEST = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# SFTP session encryption & transient connection cache
# ---------------------------------------------------------------------------
# ``SFTP_CONFIG_KEY`` is the Fernet key that protects saved SftpConfig
# passwords and SFTP session passwords at rest. It is a separate secret
# from ``SECRET_KEY`` so it can be rotated without invalidating sessions
# (and vice versa). Generate one with:
#     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Leave unset in development; the ``apps.sftp.crypto`` helper falls back to
# a PBKDF2 derivation from SECRET_KEY in that case. In production (DEBUG=False)
# a real SFTP_CONFIG_KEY is REQUIRED — the PBKDF2 derivation from SECRET_KEY
# is acceptable but loses key-rotation independence, so we warn.
SFTP_CONFIG_KEY = os.environ.get('SFTP_CONFIG_KEY') or None

if not DEBUG and not SFTP_CONFIG_KEY:
    # Fall back to PBKDF2(SECRET_KEY) is technically allowed in production,
    # but operators should explicitly opt in via this env var to make the
    # intent clear and to enable independent key rotation. We do not hard-
    # fail here — the crypto helper handles both cases — but we surface the
    # warning so it shows up in deployment logs.
    import warnings
    warnings.warn(
        'SFTP_CONFIG_KEY is not set in production. The SFTP password '
        'encryption key will be derived from SECRET_KEY via PBKDF2. '
        'Set SFTP_CONFIG_KEY to a real Fernet key for independent rotation.',
        RuntimeWarning,
        stacklevel=2,
    )

# TTL (in seconds) for the shared-Redis SFTP session cache. The session
# password is encrypted at rest (Fernet) and only readable with the
# SFTP_CONFIG_KEY (or derived from SECRET_KEY in dev).
SFTP_SESSION_TTL = int(os.environ.get('SFTP_SESSION_TTL', '3600'))

# Optional explicit Redis URL for the SFTP session cache. When unset, the
# SFTP session cache falls back to REDIS_URL, then to Django's default cache.
SFTP_SESSION_REDIS_URL = os.environ.get('SFTP_SESSION_REDIS_URL') or None

# Project-wide Redis URL — the **only** shared-Redis consumer left is the SFTP
# session cache (``apps/sftp/cache.py``), which probes it lazily and silently
# falls back to LocMemCache when it is unreachable. It is therefore optional
# everywhere: the desktop profile blanks it (standalone.py), and a missing
# server needs nothing installed. (Celery used to share this setting; it was
# removed 2026-10-15.)
REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'

# Per-launch token that unlocks POST /api/v1/system/shutdown/ (apps/common/shutdown.py).
# Electron generates it on every start and never persists it, so it is not a
# durable credential — it exists so that a local process which happens to reach
# the loopback API cannot kill the backend. Unset means the endpoint is not
# enabled (the view 404s), which is correct for dev and server installs where
# nothing stops the backend programmatically.
SHUTDOWN_TOKEN = os.environ.get('LQDP_SHUTDOWN_TOKEN') or None
