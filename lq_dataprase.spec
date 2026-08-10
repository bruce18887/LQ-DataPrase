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
# Only the amd64 DLL is needed: excelize.py selects it via platform.machine()
# at runtime and the build target is x64 Windows only (386/arm64 were ~18 MB
# of dead weight in the bundle).
for lib_name in [
    'libexcelize.amd64.windows.dll',
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
    'apps.datafiles.views.file_views',
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
    'django.core.management.commands.runserver',
    # Django 6+ moved these commands out of django.core.management.commands:
    #   collectstatic  -> django.contrib.staticfiles.management.commands
    #   createsuperuser -> django.contrib.auth.management.commands
    'django.contrib.staticfiles.management.commands.collectstatic',
    'django.contrib.auth.management.commands.createsuperuser',
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

    # Data processing (no scipy — gaussian_kde / probplot / t.cdf are
    # replaced by numpy implementations in statistics/kde.py + distributions.py)
    'pandas',
    'numpy',
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

# Set DJANGO_SETTINGS_MODULE so collect_all can properly introspect Django
# subpackages (rest_framework.schemas, django.contrib.gis.utils, etc.).
# Without this, collect_all emits ImproperlyConfigured warnings and skips
# modules that require settings to be loaded.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.standalone')
import django  # noqa: E402
django.setup()

# Critical packages that need full collection (templates, static, migrations)
# NOTE: Only list packages that genuinely need collect_all (i.e. ship data
# files or templates). For pure-Python packages, the hiddenimports list above
# is sufficient and much faster.
_full_collect = [
    'rest_framework',          # templates, static
    'rest_framework_simplejwt',
    'django_filters',
    'drf_spectacular',         # schemas, static
    'corsheaders',
    'whitenoise',
    'openpyxl',                # templates
    'lxml',                    # data files
    'pptx',                    # templates
    'py7zr',
    'excelize',
]

# Django needs special handling: collect_all('django') pulls in ALL database
# backends (mysql, postgres, oracle, gis) and contrib apps we don't use,
# adding ~35s to the build. Instead, collect only the subpackages we need.
_django_subpackages = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.auth.management',
    'django.contrib.auth.management.commands',
    'django.contrib.staticfiles.management',
    'django.contrib.staticfiles.management.commands',
    'django.template',
    'django.templatetags',
    'django.views',
    'django.views.generic',
    'django.db.backends.sqlite3',
]
for pkg in _django_subpackages:
    try:
        datas, binaries, hiddenimports = collect_all(pkg)
        _datas += datas
        _binaries += binaries
        _hiddenimports += hiddenimports
    except Exception:
        pass

# Scientific packages: collect_all on these is extremely slow (pandas ~10s,
# scipy ~15s, matplotlib ~10s) because they recursively scan thousands of
# submodules. We only need specific subpackages, so collect those directly.
_science_subpackages = [
    'pandas.core',
    'pandas.io',
    'pandas.compat',
    'pandas._libs',
    'pandas.api',
    'pandas.util',
    'pandas.tseries',
    'pandas.plotting',
    'numpy.core',
    'numpy._core',
    'numpy.lib',
    'numpy.linalg',
    'numpy.fft',
    'numpy.random',
    'numpy.ma',
    'numpy.polynomial',
    'numpy.ctypeslib',
    'matplotlib',
    'matplotlib.backends',
    'PIL',
    'cryptography',
    'paramiko',
    'nacl',
    'bcrypt',
]
for pkg in _science_subpackages:
    try:
        datas, binaries, hiddenimports = collect_all(pkg)
        _datas += datas
        _binaries += binaries
        _hiddenimports += hiddenimports
    except Exception:
        pass

# collect_all() recursively pulls in test subpackages (e.g. scipy.stats.tests,
# numpy.f2py.tests) as hidden imports. PyInstaller's `excludes` option does
# NOT filter entries already in `hiddenimports`, so we must strip them here.
# This cuts the Analysis phase from ~95s down to ~30s and shrinks the bundle.
_test_patterns = (
    '.tests.', '.tests',
    '.test_',  # some packages use test_<name> convention
)
def _is_test_module(name: str) -> bool:
    parts = name.split('.')
    # Match <pkg>.tests or <pkg>.tests.<anything>
    return any(p == 'tests' for p in parts[1:])  # skip leading part

_hiddenimports = [m for m in _hiddenimports if not _is_test_module(m)]

# ---------------------------------------------------------------------------
# Exclusions — save space by removing things we don't need
# ---------------------------------------------------------------------------
_excludes = [
    # scipy is replaced by numpy implementations (statistics/kde.py +
    # distributions.py); exclude it explicitly so any transitive import
    # cannot drag the ~91 MB tree back in.
    'scipy',
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
    # Django database backends we don't use (only sqlite3 is needed)
    'django.db.backends.mysql',
    'django.db.backends.postgresql',
    'django.db.backends.oracle',
    'django.db.backends.base',
    # Django contrib apps we don't use
    'django.contrib.gis',
    'django.contrib.postgres',
    'django.contrib.sitemaps',
    'django.contrib.sites',
    'django.contrib.flatpages',
    'django.contrib.redirects',
    'django.contrib.humanize',
    'django.contrib.webdesign',
    # Matplotlib backends we don't use (only backend_agg is needed)
    'matplotlib.backends.backend_tk',
    'matplotlib.backends.backend_qt',
    'matplotlib.backends.backend_gtk',
    'matplotlib.backends.backend_wx',
    'matplotlib.backends.backend_macosx',
    # Test subpackages of scientific libraries — pulled in by collect_all but
    # never needed at runtime. Excluding them speeds up the Analysis phase
    # and shrinks the bundle.
    'pandas.tests',
    'numpy.tests',
    'numpy.f2py.tests',
    'numpy.lib.tests',
    'numpy.ma.tests',
    'numpy.linalg.tests',
    'numpy.fft.tests',
    'numpy.random.tests',
    'numpy.typing.tests',
    'numpy.core.tests',
    'numpy.distutils.tests',
    'matplotlib.tests',
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
# UPX is enabled only on the bootloader EXE (~3 MB). The collection of
# 314 .pyd/.dll binaries (317 MB total) is left uncompressed because:
#   1. The NSIS installer re-compresses everything with LZMA/7z anyway.
#   2. Double-compression (UPX + 7z) wastes ~7s with negligible size gain.
#   3. Skipping UPX at COLLECT level avoids the runtime decompression step
#      when the .pyd/.dll is loaded by the OS (faster cold start).
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
    upx=False,
    name='LQ-DataPrase',
)
