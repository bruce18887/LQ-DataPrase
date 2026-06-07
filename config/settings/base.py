from datetime import timedelta
from pathlib import Path
import os

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
    'celery',
    'apps.accounts',
    'apps.datafiles',
    'apps.analysis',
    'apps.dashboard',
    'apps.batch_report',
    'apps.buyoff',
    'apps.gage',
    'apps.export',
    'apps.sftp',
    'apps.data_correlation',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOW_ALL_ORIGINS = True

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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'ate_analysis',
        'USER': 'ate_user',
        'PASSWORD': 'ate_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
# SQLite fallback (for local development without PostgreSQL):
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

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
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
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

CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Shanghai'

SPECTACULAR_SETTINGS = {
    'TITLE': 'DataPhrase API',
    'DESCRIPTION': 'DataPhrase 数据分析平台 API 文档',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

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
# SFTP session cache resolves REDIS_URL, then CELERY_BROKER_URL.
SFTP_SESSION_REDIS_URL = os.environ.get('SFTP_SESSION_REDIS_URL') or None

# Project-wide Redis URL (used by Celery, the SFTP session cache, and
# any other shared-Redis consumers). Setting it here keeps Celery and the
# SFTP cache pointing at the same backend by default, but each consumer
# can be redirected independently via its own override.
REDIS_URL = os.environ.get('REDIS_URL') or CELERY_BROKER_URL
