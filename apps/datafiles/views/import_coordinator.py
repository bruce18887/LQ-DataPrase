"""Cross-process import coordination and transactional path registration."""

import hashlib
import os
import time
from contextlib import contextmanager, nullcontext

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.datafiles.combination_service import resolve_batch_no
from apps.datafiles.models import DataFile
from apps.datafiles.serializers import normalize_tags
from apps.datafiles.utils import resolve_file_path


def import_path_key(file_path):
    """Canonical OS-aware key for matching disk and stored import paths."""
    return os.path.normcase(os.path.normpath(resolve_file_path(file_path)))


def import_lock_key(owner, target_path):
    """Stable owner + normalized target key, shared by file and batch imports."""
    target = os.path.normcase(os.path.normpath(target_path))
    digest = hashlib.sha256(f'{owner.pk}\0{target}'.encode('utf-8')).hexdigest()
    lock_dir = os.path.join(
        settings.MEDIA_ROOT, 'data', str(owner.username), '.import-locks',
    )
    os.makedirs(lock_dir, exist_ok=True)
    return os.path.join(lock_dir, digest + '.lock')


@contextmanager
def import_path_lock(owner, target_path):
    """Serialize an import target across threads and processes.

    Lock files deliberately persist: unlinking a locked file creates inode races
    where two waiters can hold locks on different files for the same target.
    """
    with open(import_lock_key(owner, target_path), 'a+b') as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b'0')
            lock_file.flush()
        lock_file.seek(0)
        while True:
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.02)
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


# Keep platform primitives separate so each OS imports only its own module.
if os.name == 'nt':
    import msvcrt
else:
    import fcntl

    @contextmanager
    def import_path_lock(owner, target_path):
        with open(import_lock_key(owner, target_path), 'a+b') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def find_existing_import_row(owner, file_path, file_type, batch_name=''):
    """Find an owner/type/batch row with the same normalized disk path."""
    target = import_path_key(file_path)
    rows = DataFile.objects.filter(
        owner=owner, file_type=file_type, batch_name=batch_name,
    )
    return next((row for row in rows if import_path_key(row.file_path) == target), None)


def _refresh_in_transaction(row, combination, batch_no_override, tags, parsed):
    """Refresh a freshly re-read row using conditional updates, never stale save."""
    updates = {}
    if combination is not None and row.combination_id != combination.id:
        updates['combination_id'] = combination.id
    resolved = resolve_batch_no(batch_no_override, parsed[2])
    if (batch_no_override or (resolved and not row.batch_no)) and row.batch_no != resolved:
        updates['batch_no'] = resolved
    if tags:
        existing = {str(tag).strip().lower() for tag in (row.tags or [])}
        merged = list(row.tags or [])
        for tag in normalize_tags(tags):
            if tag.lower() not in existing:
                merged.append(tag)
                existing.add(tag.lower())
        if merged != row.tags:
            updates['tags'] = normalize_tags(merged)
    if not updates:
        return row
    updates['updated_at'] = timezone.now()
    count = DataFile.objects.filter(pk=row.pk, owner=row.owner_id).update(**updates)
    if count != 1:
        return None
    row.refresh_from_db()
    return row


def refresh_existing_import_row(row, combination, batch_no_override, tags, parsed):
    """Re-read by owner/pk in a short transaction; deleted rows are skipped."""
    with transaction.atomic():
        current = DataFile.objects.filter(pk=row.pk, owner_id=row.owner_id).first()
        if current is None:
            return False
        return _refresh_in_transaction(
            current, combination, batch_no_override, tags, parsed,
        ) is not None


def import_or_refresh_file(user, file_path, file_type='single', batch_name='',
                           sub_batch='', source_mtime=None, parsed=None,
                           combination=None, batch_no_override='', tags=None,
                           register_file=None, lock_target=True):
    """Parse outside a transaction, then lock/re-read/create one normalized path."""
    from ._helpers import parse_file_meta, _register_file

    register_file = register_file or _register_file
    if parsed is None:
        parsed = parse_file_meta(file_path)
    with import_path_lock(user, file_path) if lock_target else nullcontext():
        with transaction.atomic():
            existing = find_existing_import_row(user, file_path, file_type, batch_name)
            if existing is not None:
                refreshed = _refresh_in_transaction(
                    existing, combination, batch_no_override, tags, parsed,
                )
                if refreshed is not None:
                    refreshed._import_created = False
                return refreshed
            created = register_file(
                user, file_path, file_type, batch_name, sub_batch,
                source_mtime=source_mtime, parsed=parsed, combination=combination,
                batch_no_override=batch_no_override, tags=tags,
            )
            created._import_created = True
            return created
