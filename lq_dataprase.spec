# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LQ-DataPrase standalone build.

Build command (from project root, using the .venv Python):
    .venv\\Scripts\\python.exe -m PyInstaller lq_dataprase.spec --clean

Output: dist\\LQ-DataPrase\\LQ-DataPrase.exe
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = SPEC_DIR
VENV_SITE = os.path.join(PROJECT_ROOT, '.venv', 'Lib', 'site-packages')

_datas = []
_binaries = []
_hiddenimports = []

# ---------------------------------------------------------------------------
# Data files — only non-Python assets
# ---------------------------------------------------------------------------

# Frontend dist (built Vue SPA) — WhiteNoise will serve these as static files
_frontend_dist = os.path.join(PROJECT_ROOT, 'frontend', 'dist')
if os.path.isdir(_frontend_dist):
    _datas.append((_frontend_dist, 'frontend_dist'))

# excelize ships Go shared libraries (.dll) at the site-packages root.
# collect_all may miss them because they are standalone files, not in a subdir.
for lib_name in [
    'libexcelize.amd64.windows.dll',
    'libexcelize.386.windows.dll',
    'libexcelize.arm64.windows.dll',
]:
    lib_path = os.path.join(VENV_SITE, lib_name)
    if os.path.isfile(lib_path):
        _datas.append((lib_path, '.'))

# ---------------------------------------------------------------------------
# Hidden imports — modules that PyInstaller's static analysis misses
# ---------------------------------------------------------------------------
_hiddenimports += [
    # Django apps (resolved at runtime via INSTALLED_APPS strings, not imports)
    'apps',
    'apps.accounts',
    'apps.accounts.models',
    'apps.accounts.views',
    'apps.accounts.urls',
    'apps.accounts.serializers',
    'apps.accounts.admin',
    'apps.accounts.permissions',
    'apps.accounts.apps',
    'apps.datafiles',
    'apps.datafiles.models',
    'apps.datafiles.views',
    'apps.datafiles.views.__init__',
    'apps.datafiles.views._helpers',
    'apps.datafiles.views.browse_views',
    'apps.datafiles.views.upload_views',
    'apps.datafiles.views.batch_views',
    'apps.datafiles.urls',
    'apps.datafiles.serializers',
    'apps.datafiles.admin',
    'apps.datafiles.apps',
    'apps.datafiles.parsers',
    'apps.datafiles.utils',
    'apps.analysis',
    'apps.analysis.models',
    'apps.analysis.views',
    'apps.analysis.urls',
    'apps.analysis.serializers',
    'apps.analysis.apps',
    'apps.analysis.services',
    'apps.analysis.services.statistics',
    'apps.analysis.services.statistics.computations',
    'apps.analysis.services.statistics.trends',
    'apps.analysis.services.statistics.site_yield',
    'apps.analysis.services.statistics.uph',
    'apps.dashboard',
    'apps.dashboard.views',
    'apps.dashboard.urls',
    'apps.dashboard.apps',
    'apps.batch_report',
    'apps.batch_report.views',
    'apps.batch_report.urls',
    'apps.batch_report.apps',
    'apps.buyoff',
    'apps.buyoff.views',
    'apps.buyoff.urls',
    'apps.buyoff.apps',
    'apps.buyoff.services',
    'apps.gage',
    'apps.gage.views',
    'apps.gage.urls',
    'apps.gage.apps',
    'apps.gage.services',
    'apps.export',
    'apps.export.views',
    'apps.export.urls',
    'apps.export.apps',
    'apps.sftp',
    'apps.sftp.views',
    'apps.sftp.urls',
    'apps.sftp.apps',
    'apps.sftp.models',
    'apps.sftp.serializers',
    'apps.sftp.pool',
    'apps.sftp.cache',
    'apps.sftp.crypto',
    'apps.data_correlation',
    'apps.data_correlation.views',
    'apps.data_correlation.urls',
    'apps.data_correlation.apps',
    'apps.common',
    'apps.common.file_loading',
    'apps.common.params',

    # Config package
    'config',
    'config.settings',
    'config.settings.standalone',
    'config.settings.base',
    'config.urls',
    'config.wsgi',

    # Django internals
    'django.contrib.admin',
    'django.contrib.admin.apps',
    'django.contrib.auth',
    'django.contrib.auth.backends',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.template.backends.django',
    'django.db.backends.sqlite3',
    'django.db.backends.sqlite3.base',
    'django.db.backends.sqlite3.operations',
    'django.db.backends.sqlite3.introspection',
    'django.db.backends.sqlite3.creation',
    'django.db.migrations',
    'django.core.management',
    'django.core.management.commands.migrate',
    'django.core.management.commands.collectstatic',
    'django.core.management.commands.runserver',
    'django.core.management.commands.createsuperuser',
    'django.core.handlers.wsgi',
    'django.core.servers.basehttp',
    'django.middleware.security',
    'django.middleware.common',
    'django.middleware.csrf',
    'django.contrib.sessions.backends.db',
    'django.contrib.auth.hashers',

    # DRF
    'rest_framework',
    'rest_framework.parsers',
    'rest_framework.renderers',
    'rest_framework.permissions',
    'rest_framework.response',
    'rest_framework.decorators',
    'rest_framework.routers',
    'rest_framework.schemas',
    'rest_framework.pagination',
    'rest_framework.filters',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.authentication',
    'rest_framework_simplejwt.tokens',
    'rest_framework_simplejwt.token_blacklist',
    'django_filters',
    'django_filters.rest_framework',
    'drf_spectacular',
    'drf_spectacular.views',
    'drf_spectacular.generators',
    'drf_spectacular.utils',

    # CORS
    'corsheaders',
    'corsheaders.middleware',
    'corsheaders.checks',

    # WhiteNoise
    'whitenoise',
    'whitenoise.middleware',
    'whitenoise.storage',

    # Data processing
    'pandas',
    'numpy',
    'scipy',
    'scipy.stats',
    'scipy.special',
    'scipy.interpolate',
    'scipy.optimize',
    'openpyxl',
    'matplotlib',
    'matplotlib.pyplot',
    'matplotlib.backends',
    'matplotlib.backends.backend_agg',
    'PIL',
    'PIL.Image',

    # SFTP / crypto
    'paramiko',
    'paramiko.transport',
    'paramiko.sftp_client',
    'paramiko.sftp',
    'cryptography',
    'cryptography.fernet',
    'nacl',
    'bcrypt',

    # Archive
    'py7zr',
    'rarfile',
    'zipfile',

    # XML / Excel helpers
    'lxml',
    'lxml.etree',
    'pptx',

    # Other
    'json',
    'csv',
    'logging',
    'threading',
    'socket',
    'email.mime.text',
]

# ---------------------------------------------------------------------------
# Collect entire packages (data + binaries + hidden imports)
# ---------------------------------------------------------------------------
from PyInstaller.utils.hooks import collect_all

# Critical packages that need full collection (templates, static, migrations)
_full_collect = [
    'django',
    'rest_framework',
    'rest_framework_simplejwt',
    'django_filters',
    'drf_spectacular',
    'corsheaders',
    'whitenoise',
    'pandas',
    'numpy',
    'scipy',
    'matplotlib',
    'PIL',
    'cryptography',
    'paramiko',
    'nacl',
    'bcrypt',
    'openpyxl',
    'lxml',
    'pptx',
    'py7zr',
    'rarfile',
    'excelize',
]

for pkg in _full_collect:
    try:
        datas, binaries, hiddenimports = collect_all(pkg)
        _datas += datas
        _binaries += binaries
        _hiddenimports += hiddenimports
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Exclusions — save space by removing things we don't need
# ---------------------------------------------------------------------------
_excludes = [
    # Celery (not used in standalone)
    'celery',
    'kombu',
    'billiard',
    'vine',
    'amqp',
    # Redis Python client (not used)
    'redis',
    'redis.asyncio',
    # Tkinter (not needed)
    'tkinter',
    'tkinter.filedialog',
    # Development / test tools
    'IPython',
    'ipykernel',
    'jupyter',
    'notebook',
    'pytest',
    'playwright',
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['standalone.py'],
    pathex=[PROJECT_ROOT, os.path.join(PROJECT_ROOT, 'apps')],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# Executable
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LQ-DataPrase',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)

# ---------------------------------------------------------------------------
# Directory collection (not single-file — faster startup)
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LQ-DataPrase',
)
