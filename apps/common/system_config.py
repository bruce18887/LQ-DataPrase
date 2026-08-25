"""System-level storage path configuration (data dir + temp dir).

Persisted as ``system_config.json`` in the *fixed* anchor directory — the
original BASE_DIR (Electron userData / exe dir / project root), the same
place ``secret.key`` lives. Keys:

- ``data_dir`` (optional): holds ``db.sqlite3`` and ``media/``. When set, the
  next backend start migrates those from the old dir into the new one and
  uses it as the effective BASE_DIR.
- ``temp_dir`` (optional): export caches / matplotlib config land here.

**Built-in defaults (Storage Layout v2)**: when a key is absent, the
effective value is the built-in default instead of "wherever the OS puts
things" — ``data_dir`` defaults to ``~\\LQ-DataPrase`` (per-user app data
root; the same for dev and packaged builds) and ``temp_dir`` defaults to
the system temp dir plus an app-scoped ``LQ-DataPrase-Temp`` subfolder so
export intermediates never litter the bare temp root. ``system_config.json``
never records defaults; the API's ``configured`` section stays ``null`` and
the effective values are what settings actually resolved to.

Data-dir migration is fully automatic: on startup with no (or a different)
``data_dir``, ``db.sqlite3`` and ``media/`` are moved copy → verify → DB-row
rewrite → delete. Because ``DataFile.file_path`` / ``ParseHistory.filepath``
are stored as absolute legacy paths in old installs, the DB rows are
rewritten to relative-to-MEDIA_ROOT paths (or kept absolute when outside)
as part of the same migration — the next data-dir move then needs no row
rewrites at all.

Path changes take effect only after a backend restart (the DB connection is
fixed at settings-import time), so the API surface returns
``restart_required``.

This module MUST NOT import ``django.conf`` — it is called during settings
import, before Django is set up (circular-import hazard). Stdlib only.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

CONFIG_FILENAME = 'system_config.json'
_PROBE_FILENAME = '.lqdp_write_probe'


def _canonical(path: Path) -> Path:
    """Normalize a path without Windows 8.3 short-name expansion.

    ``Path.resolve()`` may return ``ADMINI~1``-style short names on Windows,
    which breaks comparisons against long-form paths (e.g. from
    ``tempfile.TemporaryDirectory``). ``abspath + normpath`` keeps the long
    form while normalizing separators and ``..`` components.
    """
    return Path(os.path.normpath(os.path.abspath(str(path))))


def _default_data_dir() -> Path:
    """Built-in default data dir: ``<user home>\\LQ-DataPrase``.

    ``Path.home()`` expands USERPROFILE on Windows (falling back to
    HOMEDRIVE+HOMEPATH), so dev and packaged builds converge on the same
    per-user location. ``_canonical`` keeps the long-form path for the
    equality check against the anchor dir.
    """
    return _canonical(Path.home() / 'LQ-DataPrase')


def _migration_disabled() -> bool:
    """True when ``LQDP_SKIP_STORAGE_MIGRATION`` is set (1/true/yes/on).

    Test runners (``manage.py test`` sets it in ``manage.py``) must never
    trigger the default data-dir migration — the anchor directory holds the
    developer's real DB and media, and a settings import during testing
    would silently move them to the user home. When disabled, an absent
    ``data_dir`` resolves to the anchor itself (no-op) instead of the
    built-in default.
    """
    return os.environ.get('LQDP_SKIP_STORAGE_MIGRATION', '').lower() in (
        '1', 'true', 'yes', 'on',
    )


def _default_temp_dir() -> Path:
    """Built-in default temp dir: system temp + app-scoped subfolder.

    Read before any redirect has run, so ``tempfile.gettempdir()`` is the
    bare OS temp dir here. Export intermediates (excelize xlsx round-trip,
    matplotlib config dirs) land under ``LQ-DataPrase-Temp`` and are
    reclaimed together with the rest of the OS temp.
    """
    return _canonical(Path(tempfile.gettempdir()) / 'LQ-DataPrase-Temp')


def config_file_path(original_base_dir: Path) -> Path:
    """Path of the config file.

    ``LQDP_SYSTEM_CONFIG_FILE`` overrides the location (used by tests / E2E
    so the project root stays clean).
    """
    override = os.environ.get('LQDP_SYSTEM_CONFIG_FILE')
    if override:
        return Path(override)
    return original_base_dir / CONFIG_FILENAME


def load_config(config_file: Path) -> dict:
    """Read the config file; missing file → ``{}``, corrupt JSON → backup to
    ``.bak`` and return ``{}`` (startup must never crash on a bad config)."""
    if not config_file.is_file():
        return {}
    try:
        data = json.loads(config_file.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        try:
            config_file.rename(str(config_file) + '.bak')
        except OSError:
            pass
        return {}


def validate_directory(raw: str) -> Path:
    """Normalize and validate a directory path.

    Rejects empty / NUL-containing / non-absolute / drive-relative paths
    (``C:foo`` is not absolute on win32), creates the directory if missing
    and verifies writability with a probe file. Raises ``ValueError`` with a
    Chinese message on any failure (surfaced as a 400 by the API).
    """
    value = (raw or '').strip().strip('\x00')
    if not value:
        raise ValueError('路径不能为空')
    if '\x00' in value:
        raise ValueError('路径包含非法字符')
    if not os.path.isabs(value):
        raise ValueError('必须使用绝对路径')
    path = Path(value)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / _PROBE_FILENAME
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
    except OSError as exc:
        raise ValueError(f'目录不可写或无法创建：{exc}') from exc
    return _canonical(path)


def save_config(config_file: Path, data_dir: str | None, temp_dir: str | None) -> dict:
    """Persist config. ``None`` removes the key (reset to default). Returns
    the payload written (the ``configured`` section of the API response)."""
    payload = {}
    if data_dir is not None:
        payload['data_dir'] = data_dir
    if temp_dir is not None:
        payload['temp_dir'] = temp_dir
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return payload


def _migrate(original: Path, target: Path) -> None:
    """Move ``db.sqlite3`` (plus WAL/journal siblings) and ``media/`` from
    ``original`` into ``target``: copy → verify → rewrite DB rows → delete old.

    - Target wins: if the target already contains an item, it is kept and
      the source copy is skipped (idempotent restarts).
    - A missing source item (fresh install) is not an error.
    - Any verification failure raises ``ImproperlyConfigured`` and leaves the
      originals untouched.

    DB-row rewrite: after the copied DB is verified, ``datafiles_datafile`` /
    ``datafiles_parsehistory`` rows whose absolute path points under the old
    ``media/`` are rewritten to relative-to-MEDIA_ROOT paths (Storage Layout
    v2). Runs unconditionally on ``db_dst`` (even when it already existed) so
    a partially-rewritten copy converges on the next start; rows outside the
    old media (cross-drive, sample dir) are left untouched.
    """
    target.mkdir(parents=True, exist_ok=True)

    # --- db.sqlite3 (+ -wal / -shm / -journal siblings) ---
    db_src = original / 'db.sqlite3'
    if db_src.is_file():
        db_dst = target / 'db.sqlite3'
        if not db_dst.exists():
            shutil.copy2(db_src, db_dst)
            for suffix in ('-wal', '-shm', '-journal'):
                sibling = original / f'db.sqlite3{suffix}'
                if sibling.is_file():
                    shutil.copy2(sibling, target / sibling.name)
            _verify_sqlite(db_src, db_dst)
            _rewrite_datafile_paths(db_dst, original, target)
            db_src.unlink()
            for suffix in ('-wal', '-shm', '-journal'):
                sibling = original / f'db.sqlite3{suffix}'
                if sibling.is_file():
                    sibling.unlink()
        else:
            # Target already had a DB — rewrite its stale absolute rows too.
            _rewrite_datafile_paths(db_dst, original, target)

    # --- media/ ---
    media_src = original / 'media'
    if media_src.is_dir():
        media_dst = target / 'media'
        if not media_dst.exists():
            shutil.copytree(media_src, media_dst)
            shutil.rmtree(media_src)


def _rewrite_datafile_paths(db_path: Path, original: Path, target: Path) -> None:
    """Rewrite absolute legacy file paths in the migrated DB to relative ones.

    Columns: ``datafiles_datafile.file_path`` and
    ``datafiles_parsehistory.filepath`` (coupled to apps.datafiles, same as
    the ``db.sqlite3`` / ``media`` names below — a fresh DB without these
    tables is skipped). A row is rewritten when its stored value is
    absolute and sits under the OLD ``media/`` directory; the new value is
    the path relative to the NEW ``media/``. Everything else (already
    relative, outside old media, empty) is left as-is — idempotent by
    construction, so a crash mid-rewrite converges on the next start.

    Any ``sqlite3`` error raises ``ImproperlyConfigured``; the source DB
    and files remain untouched.
    """
    from django.core.exceptions import ImproperlyConfigured

    old_media = os.path.normcase(str(original / 'media')) + os.sep
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table, column in (
                ('datafiles_datafile', 'file_path'),
                ('datafiles_parsehistory', 'filepath'),
            ):
                if table not in tables or column not in {
                    row[1] for row in conn.execute(f'PRAGMA table_info({table})')
                }:
                    continue
                rows = conn.execute(
                    f'SELECT rowid, {column} FROM {table}'
                ).fetchall()
                for rowid, stored in rows:
                    if not stored or not os.path.isabs(stored):
                        continue
                    norm = os.path.normcase(os.path.normpath(stored))
                    if not norm.startswith(old_media):
                        continue
                    # 迁移保持 media/ 内部结构不变（整树复制），因此相对新
                    # MEDIA_ROOT 的路径 = 去掉旧 media 前缀的剩余部分。
                    rel = norm[len(old_media):]
                    conn.execute(
                        f'UPDATE {table} SET {column} = ? WHERE rowid = ?',
                        (rel.replace(os.sep, '/'), rowid),
                    )
            conn.commit()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        raise ImproperlyConfigured(
            f'数据库迁移时重写数据文件路径失败（{db_path}）：{exc}'
        ) from exc


def _startup_lock(anchor: Path):
    """Advisory file lock around the settings-import migration window.

    Two instances (e.g. Electron double-launch + a dev server) must not
    migrate the same files concurrently. Windows: ``msvcrt.locking``;
    POSIX: ``fcntl.flock`` (try-import — if neither is available the lock
    is a no-op). Waits up to ~10s, then raises ``ImproperlyConfigured``
    with a Chinese message.

    Usage: ``with _startup_lock(anchor): ...``
    """
    import contextlib

    @contextlib.contextmanager
    def _unlocked():
        yield

    try:
        import msvcrt
    except ImportError:
        msvcrt = None
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if msvcrt is None and fcntl is None:
        return _unlocked()

    lock_path = anchor / '.lqdp_startup.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _locked():
        with open(str(lock_path), 'a+b') as fh:
            deadline = time.monotonic() + 10.0
            while True:
                try:
                    if msvcrt is not None:
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, IOError):
                    if time.monotonic() >= deadline:
                        from django.core.exceptions import ImproperlyConfigured
                        raise ImproperlyConfigured(
                            '另一个应用实例正在启动（数据目录迁移中），请稍后重试。'
                            '如确认无其他实例，请删除文件 '
                            f'{lock_path} 后重启。'
                        )
                    time.sleep(0.3)
            try:
                yield
            finally:
                if msvcrt is not None:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    return _locked()


def _verify_sqlite(src: Path, dst: Path) -> None:
    """Verify the copied DB: byte-size match + read-only ``integrity_check``.
    Raises ``ImproperlyConfigured`` on failure (originals stay intact)."""
    from django.core.exceptions import ImproperlyConfigured

    if src.stat().st_size != dst.stat().st_size:
        raise ImproperlyConfigured(
            f'数据库文件迁移校验失败（大小不一致）：{src} → {dst}'
        )
    try:
        conn = sqlite3.connect(f'file:{dst}?mode=ro', uri=True)
        try:
            row = conn.execute('PRAGMA integrity_check').fetchone()
        finally:
            conn.close()
        if not row or row[0] != 'ok':
            raise ImproperlyConfigured(
                f'数据库文件迁移校验失败（integrity_check={row[0] if row else "unknown"}）：{dst}'
            )
    except sqlite3.Error as exc:
        raise ImproperlyConfigured(
            f'数据库文件迁移校验失败（无法打开副本）：{dst}：{exc}'
        ) from exc


def apply_system_config(original_base_dir: Path) -> Path:
    """Apply the config (or built-in defaults) at settings-import time.

    - ``data_dir``: config value, else the built-in default
      ``~\\LQ-DataPrase``. When it differs from the anchor, files are
      migrated under a startup lock and the new base is returned.
    - ``temp_dir``: config value, else ``<system temp>\\LQ-DataPrase-Temp``.
      Redirects ``tempfile.tempdir`` and TMP/TEMP/TMPDIR (affects every
      ``tempfile`` consumer: excelize round-trips, matplotlib config dirs).

    Both keys are applied independently — configuring one never silences
    the other (historical bug: a set ``data_dir`` returned early and
    skipped ``temp_dir``).

    Failure semantics: a *configured* dir that cannot be created/written
    raises ``ImproperlyConfigured`` (hard dependency); a *default* temp dir
    that fails degrades silently back to the system temp dir so the app
    still starts.
    """
    cfg = load_config(config_file_path(original_base_dir))
    orig = _canonical(original_base_dir)

    # --- data_dir: config value > built-in default (or anchor when migrations disabled) ---
    if _migration_disabled():
        data_target = _canonical(Path(cfg['data_dir'])) if cfg.get('data_dir') else orig
    else:
        data_target = _canonical(Path(cfg.get('data_dir') or str(_default_data_dir())))
    if data_target != orig:
        with _startup_lock(original_base_dir):
            _migrate(original_base_dir, data_target)
    base_dir = data_target

    # --- temp_dir: config value > built-in default ---
    temp_raw = cfg.get('temp_dir') or str(_default_temp_dir())
    temp_path = _canonical(Path(temp_raw))
    try:
        temp_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if cfg.get('temp_dir'):
            from django.core.exceptions import ImproperlyConfigured
            raise ImproperlyConfigured(
                f'配置的临时目录不可创建或不可写：{temp_path}'
            )
        return base_dir  # 默认值失败降级为系统临时目录，不阻塞启动
    tempfile.tempdir = str(temp_path)
    os.environ['TMP'] = str(temp_path)
    os.environ['TEMP'] = str(temp_path)
    os.environ['TMPDIR'] = str(temp_path)

    return base_dir
