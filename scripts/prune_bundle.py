"""Post-PyInstaller bundle pruning — removes dead weight from dist/LQ-DataPrase/_internal.

Run right after ``PyInstaller lq_dataprase.spec`` (wired into the
``pyinstaller`` npm script) and before electron-builder packages the
result.  Everything removed here is verified dead at runtime:

  - ``db.sqlite3``  — bundled automatically by PyInstaller's hook-django
    (globs ``db.*`` next to manage.py); the frozen app redirects
    BASE_DIR to the exe dir / %APPDATA% and never opens this copy.
  - django contrib apps not in INSTALLED_APPS (data files only — the
    modules are already excluded from the PYZ).
  - django locale translations outside zh_Hans + en (LANGUAGE_CODE is
    zh-hans and en is the Django fallback).
  - matplotlib assets never used by PNG-only output: afm/pdfcorefonts
    (ps/pdf backends), sample_data, STIX/cm fonts (mathtext fontsets)
    and the *Display DejaVu faces.

Idempotent: missing paths are skipped silently, so the script is safe to
re-run or to run on a partially pruned bundle.
"""
import shutil
from pathlib import Path

_INTERNAL = Path('dist') / 'LQ-DataPrase' / '_internal'

# django.contrib apps not in INSTALLED_APPS (base.py) — data-only removal.
# NOTE: 'sites' must NOT be dropped: django.contrib.auth.forms imports
# django.contrib.sites.shortcuts at module level (auth.admin is loaded by
# admin autodiscover at startup), so the sites MODULE files are needed even
# though the app itself is not installed. Everything else here is never
# imported by bundled modules (verified at runtime by tasks/smoke_frozen.sh).
_CONTRIB_DROP = [
    'admindocs', 'flatpages', 'gis', 'humanize',
    'postgres', 'redirects', 'sitemaps', 'syndication',
]

_KEEP_LOCALES = ('zh_Hans', 'en')

_MPL_DROP_DIRS = ['fonts/afm', 'fonts/pdfcorefonts', 'sample_data']
_MPL_DROP_TTF_PREFIXES = ('STIX', 'cm')
_MPL_DROP_TTF_SUFFIXES = ('Display.ttf',)


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())


def _rmtree(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _prune_locales(locale_dir: Path) -> None:
    """Keep only zh_Hans + en inside a Django ``locale/`` directory."""
    if not locale_dir.is_dir():
        return
    for lang in locale_dir.iterdir():
        if lang.name not in _KEEP_LOCALES:
            _rmtree(lang)


def main() -> int:
    if not _INTERNAL.is_dir():
        print(f'[prune] {_INTERNAL} not found — skipping')
        return 0

    before = _dir_size(_INTERNAL)

    # 1. PyInstaller hook-django bundles the dev database — dead in the bundle.
    db = _INTERNAL / 'db.sqlite3'
    if db.is_file():
        size = db.stat().st_size
        db.unlink()
        print(f'[prune] removed db.sqlite3 ({size / 1e6:.1f} MB)')

    # 2. django.contrib data files for apps that are not installed.
    for name in _CONTRIB_DROP:
        _rmtree(_INTERNAL / 'django' / 'contrib' / name)

    # 3. Locale translations — zh-hans + en fallback only.
    _prune_locales(_INTERNAL / 'django' / 'conf' / 'locale')
    contrib = _INTERNAL / 'django' / 'contrib'
    if contrib.is_dir():
        for app in contrib.iterdir():
            _prune_locales(app / 'locale')

    # 4. matplotlib assets unused by PNG-only export rendering.
    mpl_data = _INTERNAL / 'matplotlib' / 'mpl-data'
    for rel in _MPL_DROP_DIRS:
        _rmtree(mpl_data / rel)
    ttf = mpl_data / 'fonts' / 'ttf'
    if ttf.is_dir():
        for font in ttf.iterdir():
            if font.name.startswith(_MPL_DROP_TTF_PREFIXES) or \
                    font.name.endswith(_MPL_DROP_TTF_SUFFIXES):
                font.unlink(missing_ok=True)

    after = _dir_size(_INTERNAL)
    print(f'[prune] _internal: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB '
          f'({(before - after) / 1e6:.1f} MB removed)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
