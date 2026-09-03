"""Settings for PyInstaller standalone packaging.

This module imports everything from ``base.py`` and overrides values that
are inappropriate for a self-contained executable:

- SQLite instead of PostgreSQL (no external DB server needed)
- Celery removed (no external broker needed)
- WhiteNoise configured to serve static files (no nginx needed)
- Frontend dist directory registered as a static source
- SECRET_KEY auto-generated from a file-persisted random value
"""

import os
from pathlib import Path

from config.settings.base import *  # noqa: F401,F403

# ---------------------------------------------------------------------------
# Runtime detection
# ---------------------------------------------------------------------------
# When running inside a PyInstaller bundle, ``sys._MEIPASS`` points to the
# temporary extraction directory.  ``FROZEN`` lets other code (e.g. the
# entry script) branch on this without importing ``sys`` everywhere.
import sys
FROZEN = getattr(sys, 'frozen', False)

# In a frozen build, BASE_DIR (from base.py) resolves to the PyInstaller
# temp dir which is read-only.  We redirect it to the directory that
# contains the executable so that db.sqlite3, media/ and staticfiles/ land
# next to the .exe and are user-visible / user-writable.
#
# When running as an Electron child process the main process sets
# ``LQDP_BASE_DIR`` to Electron's ``app.getPath('userData')`` so that
# all writable files land in the OS-standard application data directory
# instead of next to the (potentially read-only) installed executable.
_LQDP_BASE = os.environ.get('LQDP_BASE_DIR')
if _LQDP_BASE:
    BASE_DIR = Path(_LQDP_BASE)
elif FROZEN:
    BASE_DIR = Path(sys.executable).resolve().parent

# Patch the module-level reference that other code may have captured
# via ``from django.conf import settings``.
if _LQDP_BASE or FROZEN:
    import config.settings.base as _base
    _base.BASE_DIR = BASE_DIR

# ---------------------------------------------------------------------------
# System storage path config (system_config.json) — MUST run before DATABASES
# is defined below: a configured ``data_dir`` migrates db.sqlite3 + media/
# and becomes the effective BASE_DIR; a configured ``temp_dir`` redirects
# tempfile. ``secret.key`` and the config file stay anchored to the fixed
# original dir (regenerating the key would break SFTP password decryption).
# ---------------------------------------------------------------------------
_ORIG_BASE_DIR = BASE_DIR
SYSTEM_CONFIG_ANCHOR_DIR = _ORIG_BASE_DIR
from apps.common.system_config import apply_system_config  # noqa: E402
BASE_DIR = apply_system_config(_ORIG_BASE_DIR)
import config.settings.base as _base
_base.BASE_DIR = BASE_DIR

# ---------------------------------------------------------------------------
# Core overrides
# ---------------------------------------------------------------------------
DEBUG = False

# Loopback only. standalone.py now binds 127.0.0.1 by default and the Electron
# renderer calls http://localhost:<port>, so these three cover every legitimate
# Host header. Deliberate LAN exposure (``--host 0.0.0.0``) must opt in via
# DJANGO_ALLOWED_HOSTS -- and standalone._bootstrap refuses to start that way
# with the built-in default admin credential.
ALLOWED_HOSTS = os.environ.get(
    'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]'
).split(',')

# No anonymous Swagger/schema in the shipped product (config/urls.py gates the
# routes on this flag; drf-spectacular's views default to AllowAny).
API_DOCS_ENABLED = False

# ---------------------------------------------------------------------------
# Database — SQLite (no PostgreSQL required)
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ---------------------------------------------------------------------------
# Media & static files
# ---------------------------------------------------------------------------
MEDIA_ROOT = BASE_DIR / 'media'

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# The built Vue SPA lives in ``frontend_dist/``.
# In a frozen build, data files are extracted to sys._MEIPASS (_internal/),
# while user-writable files (db.sqlite3, media/) are next to the exe.
if FROZEN:
    _FRONTEND_DIST = Path(sys._MEIPASS) / 'frontend_dist'
else:
    _FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / 'frontend' / 'dist'
if _FRONTEND_DIST.is_dir():
    STATICFILES_DIRS = [_FRONTEND_DIST]
    # Add frontend_dist to template dirs so the SPA catch-all can find index.html.
    TEMPLATES[0]['DIRS'] = [_FRONTEND_DIST]

# WhiteNoise — serve static files directly from Django.
# Per WhiteNoise docs (https://whitenoise.readthedocs.io/en/latest/django.html),
# it must be placed DIRECTLY AFTER SecurityMiddleware (so security headers
# are set first and WhiteNoise can serve compressed static files correctly).
# Placing it at the top would let static file serving pre-empt the
# security middleware's header injection and break gzip/brotli responses.
if 'whitenoise.middleware.WhiteNoiseMiddleware' not in MIDDLEWARE:
    _sec_idx = MIDDLEWARE.index('django.middleware.security.SecurityMiddleware')
    MIDDLEWARE.insert(_sec_idx + 1, 'whitenoise.middleware.WhiteNoiseMiddleware')

# Use compressed but non-manifest storage. ManifestStaticFilesStorage computes
# content hashes for every file, which makes the first collectstatic very slow
# (tens of seconds) and can cause the Electron frontend to time out waiting for
# the backend on a fresh install. CompressedStaticFilesStorage still serves
# pre-compressed .gz files at runtime without the manifest overhead.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# In the standalone executable we serve static files directly from each app's
# static/ directory and from STATICFILES_DIRS (the bundled frontend_dist). This
# avoids an expensive ``collectstatic`` pass on every first run, which was the
# main cause of the "cannot connect to server" timeout in the packaged app.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = False

# ---------------------------------------------------------------------------
# Celery — disabled (no broker required)
# ---------------------------------------------------------------------------
# Remove ``celery`` from INSTALLED_APPS so Django doesn't try to import it.
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'celery']

# Clear broker URLs so any code that lazily references them gets empty strings
# instead of trying to connect to a non-existent Redis.
CELERY_BROKER_URL = ''
CELERY_RESULT_BACKEND = ''
CELERY_ACCEPT_CONTENT = []
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# Redis URL — empty; SFTP session cache will fall back to Django LocMemCache.
REDIS_URL = ''
SFTP_SESSION_REDIS_URL = ''

# ---------------------------------------------------------------------------
# Secret key — auto-generated and persisted to ``secret.key`` next to the exe.
# ---------------------------------------------------------------------------
_SECRET_FILE = _ORIG_BASE_DIR / 'secret.key'

if os.environ.get('SECRET_KEY'):
    SECRET_KEY = os.environ['SECRET_KEY']
elif _SECRET_FILE.is_file():
    SECRET_KEY = _SECRET_FILE.read_text(encoding='utf-8').strip()
else:
    from django.core.management.utils import get_random_secret_key
    SECRET_KEY = get_random_secret_key()
    try:
        _SECRET_FILE.write_text(SECRET_KEY, encoding='utf-8')
    except OSError:
        pass  # read-only filesystem; key will be regenerated each start

# SFTP config key — derive from SECRET_KEY when not explicitly set.
if not SFTP_CONFIG_KEY:
    import base64, hashlib
    _derived = hashlib.pbkdf2_hmac('sha256', SECRET_KEY.encode(), b'sftp-config', 100_000)
    SFTP_CONFIG_KEY = base64.urlsafe_b64encode(_derived).decode()
