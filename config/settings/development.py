"""Development settings — SQLite, DEBUG on.

Applies the system storage path config (system_config.json) before DATABASES
is defined so a configured ``data_dir`` migrates db.sqlite3 + media/ and
redirects BASE_DIR (and therefore MEDIA_ROOT, which base.py already computed
from the project-root BASE_DIR — it must be re-derived when redirected).
"""

from config.settings.base import *  # noqa: F401,F403  (BASE_DIR, MEDIA_ROOT, ...)

import config.settings.base as _base
from apps.common.system_config import apply_system_config

SYSTEM_CONFIG_ANCHOR_DIR = BASE_DIR
_base_dir = apply_system_config(BASE_DIR)
if _base_dir != BASE_DIR:
    BASE_DIR = _base_dir
    _base.BASE_DIR = BASE_DIR
    MEDIA_ROOT = BASE_DIR / 'media'
    _base.MEDIA_ROOT = MEDIA_ROOT

DEBUG = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
