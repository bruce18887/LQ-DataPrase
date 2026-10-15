"""Development settings — SQLite, DEBUG on.

Applies the system storage path config (system_config.json) before DATABASES
is defined so a configured ``data_dir`` migrates db.sqlite3 + media/ and
redirects BASE_DIR (and therefore MEDIA_ROOT, which base.py already computed
from the project-root BASE_DIR — it must be re-derived when redirected).
"""

import os

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

# Swagger/schema stay routed in development. The packaged build turns this off
# (config.settings.standalone) so the API surface is not anonymously readable.
# The e2e readiness gate does NOT depend on this flag — it probes
# /api/v1/health/ (apps/common/health.py), which is routed in every profile.
API_DOCS_ENABLED = True

# Relax the login IP throttle. This profile is what ``manage.py runserver``
# uses, so it is also the backend Playwright's webServer starts when e2e is run
# without the slot pool — and ~376 cases share one loopback IP. base.py's
# 20/min would flake them for no security benefit (they are all the same
# machine). The standalone and server profiles keep the tight value.
# Rebuilt rather than mutated in place so base.py's dict is not modified.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_THROTTLE_RATES': {
        **REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {}),  # noqa: F405
        'login': os.environ.get('LQDP_LOGIN_THROTTLE_RATE', '200/min'),
    },
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
