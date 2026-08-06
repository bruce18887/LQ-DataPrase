"""System-level storage path configuration (data dir + temp dir).

Persisted as ``system_config.json`` in the *fixed* anchor directory — the
original BASE_DIR (Electron userData / exe dir / project root), the same
place ``secret.key`` lives. Keys:

- ``data_dir`` (optional): holds ``db.sqlite3`` and ``media/``. When set, the
  next backend start migrates those from the old dir into the new one and
  uses it as the effective BASE_DIR.
- ``temp_dir`` (optional): export caches / matplotlib config land here.

Absent key = current default. Path changes take effect only after a backend
restart (the DB connection is fixed at settings-import time), so the API
surface returns ``restart_required``.

This module MUST NOT import ``django.conf`` — it is called during settings
import, before Django is set up (circular-import hazard). Stdlib only.
"""

import json
import os
import shutil
import sqlite3
import tempfile
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
    ``original`` into ``target``: copy → verify → delete old.

    - Target wins: if the target already contains an item, it is kept and
      the source copy is skipped (idempotent restarts).
    - A missing source item (fresh install) is not an error.
    - Any verification failure raises ``ImproperlyConfigured`` and leaves the
      originals untouched.
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
            db_src.unlink()
            for suffix in ('-wal', '-shm', '-journal'):
                sibling = original / f'db.sqlite3{suffix}'
                if sibling.is_file():
                    sibling.unlink()

    # --- media/ ---
    media_src = original / 'media'
    if media_src.is_dir():
        media_dst = target / 'media'
        if not media_dst.exists():
            shutil.copytree(media_src, media_dst)
            shutil.rmtree(media_src)


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
    """Apply the config at settings-import time.

    - ``data_dir`` set and different → migrate files, return the new base.
    - ``temp_dir`` set → point ``tempfile.tempdir`` and TMP/TEMP/TMPDIR there.
    - Otherwise return ``original_base_dir`` unchanged.
    """
    cfg = load_config(config_file_path(original_base_dir))

    data_dir = cfg.get('data_dir')
    if data_dir:
        target = _canonical(Path(data_dir))
        if target != _canonical(original_base_dir):
            _migrate(original_base_dir, target)
            return target

    temp_dir = cfg.get('temp_dir')
    if temp_dir:
        temp_path = _canonical(Path(temp_dir))
        temp_path.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(temp_path)
        os.environ['TMP'] = str(temp_path)
        os.environ['TEMP'] = str(temp_path)
        os.environ['TMPDIR'] = str(temp_path)

    return original_base_dir
