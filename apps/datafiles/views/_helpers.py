"""Private helper functions for datafiles views."""

import logging
import os
import re
import shutil
import zipfile

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import BaseATEParser, get_parser
from apps.datafiles.services import clear_parse_cache
from apps.datafiles.utils import extract_product_code, resolve_file_path, store_file_path

logger = logging.getLogger(__name__)


# Windows-illegal + path-separator + control characters. Mirrors the blacklist
# already used by ``FileViewSet.combine`` (``file_views.py``) and
# ``_zip_base_name`` below, so every name that becomes a directory goes
# through the same character rule.
_UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_batch_dir(base, name):
    """Resolve ``name`` under ``base``, refusing anything that escapes it.

    Returns the resolved absolute path, or ``None`` when ``name`` is not a
    safe single path segment or resolves outside ``base``.

    ``BatchDirDeleteView`` / ``SubBatchDeleteView`` feed the result straight
    into ``shutil.rmtree``, and ``BatchDirImportView`` takes ``dir_name`` from
    the *request body* — where no ``<str:>`` URL converter strips slashes. A
    bare ``..`` therefore used to resolve to the parent (wiping the whole
    upload root, batch and single dirs alike), and ``../../<other-user>`` on
    the import path walked another user's tree and registered their CSVs as
    the caller's own. Same guard shape as ``_safe_extract_zip`` (Zip-Slip).
    """
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or name in ('.', '..'):
        return None
    if _UNSAFE_NAME_CHARS.search(name):
        return None
    try:
        real_base = os.path.realpath(base)
        target = os.path.realpath(os.path.join(base, name))
        # Reject the base itself: rmtree(base) would delete every batch.
        if target == real_base:
            return None
        if os.path.commonpath([real_base, target]) != real_base:
            return None
    except (OSError, ValueError):
        return None  # different drive / unreadable → treat as outside
    return target


def _is_summary_csv(filename):
    """Return True for tester summary/aggregate dumps (``Sum_093518.csv``).

    These files sit alongside the per-unit test data in a lot directory but
    parse to zero data rows — they carry no test-program name and pollute the
    dashboard's "latest ready file" pick. We never register or count them as
    batch data. Single-file uploads/downloads are unaffected (an explicit
    user action), so this predicate is only consulted on batch flows.
    """
    return os.path.basename(filename).lower().startswith('sum_')


def _is_data_csv(filename):
    """A CSV that holds real ATE data (i.e. a non-summary ``.csv``)."""
    return filename.lower().endswith('.csv') and not _is_summary_csv(filename)


def _register_file(user, file_path, file_type='single', batch_name='', sub_batch='', source_mtime=None):
    """Parse a file and create DataFile + ParseHistory records.

    source_mtime: optional aware datetime of the original source file's
    modification time. When None for archive-extracted/disk files, the
    on-disk mtime is used; for direct uploads it stays None unless provided.
    sub_batch: optional sub-batch name (subdirectory name within the batch).
    """
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    format_type = 'Unknown'
    program_name = ''
    row_count, col_count = 0, 0

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(4096)
        format_type = BaseATEParser.identify_format(head)
        if format_type != 'Unknown':
            parser = get_parser(format_type)
            df, metadata = parser.parse(file_path)
            if df is not None:
                row_count = df.shape[0]
                col_count = df.shape[1]
                program_name = metadata.get('program_name', '')
    except Exception:
        logger.warning(
            '_register_file: parse failed for %s, recording as error',
            file_path, exc_info=True,
        )

    # 相对化存储：MEDIA_ROOT 之下存相对路径，数据目录迁移时无需重写 DB。
    stored_path = store_file_path(file_path)

    datafile = DataFile.objects.create(
        owner=user,
        filename=filename,
        file_path=stored_path,
        file_size=file_size,
        format_type=format_type if format_type != 'Unknown' else 'CTA8290D',
        file_type=file_type,
        batch_name=batch_name,
        sub_batch=sub_batch,
        row_count=row_count,
        col_count=col_count,
        program_name=program_name,
        # Prefer the CSV test-program name (PTS/PGS/PDS) over filename regex
        # for product_code: the same product always reuses the same program,
        # while data filenames may carry unrelated prefixes.
        product_code=extract_product_code(filename, program_name),
        source_mtime=source_mtime,
        status='ready' if format_type != 'Unknown' else 'error',
    )

    ParseHistory.objects.create(
        user=user,
        datafile=datafile,
        filename=filename,
        filepath=stored_path,
        format_type=datafile.format_type,
        rows=row_count,
        cols=col_count,
    )

    return datafile


def _user_upload_dir(user, file_type='single'):
    """Return per-user upload directory: media/data/<username>/<file_type>/

    The directory is named after the user's login name (not the numeric id) so
    that paths are stable across id changes and human-readable in shell
    listings. Django's UnicodeUsernameValidator guarantees the username only
    contains characters that are safe in filesystem paths on every supported
    platform (POSIX + Windows), so no further sanitization is performed.
    """
    if user is None:
        raise ValueError('_user_upload_dir requires a user instance')
    path = os.path.join(settings.MEDIA_ROOT, 'data', str(user.username), file_type)
    os.makedirs(path, exist_ok=True)
    return path


def _disk_mtime(file_path):
    """Return the on-disk modification time as an aware datetime (or None)."""
    try:
        return timezone.make_aware(
            timezone.datetime.fromtimestamp(os.path.getmtime(file_path)),
            timezone.get_current_timezone(),
        )
    except (OSError, ValueError):
        return None


def _parse_last_modified(value):
    """Parse a browser-provided last_modified epoch-ms value into a datetime.

    Returns an aware datetime, or None if the value is absent/invalid.
    """
    if value in (None, ''):
        return None
    try:
        seconds = float(value) / 1000.0
        return timezone.make_aware(
            timezone.datetime.fromtimestamp(seconds),
            timezone.get_current_timezone(),
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _delete_datafile_file_only(datafile):
    """Remove only the file backing a DataFile — never the batch directory.

    This is the single-file delete path for BOTH single and batch rows (the
    historical ``_delete_datafile_on_disk`` rmtree'd the whole batch dir for
    batch rows, which would mistakenly wipe non-duplicate files sharing the
    same batch). Whole-batch deletion goes through ``BatchDirDeleteView``
    (``/batch-dirs/<name>/``) which owns the rmtree semantics. Empty parent
    directories are cleaned upward, stopping at MEDIA_ROOT; ``_user_upload_dir``
    recreates its own dirs on demand, so this is safe.
    """
    file_path = resolve_file_path(datafile.file_path)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        parent = os.path.dirname(file_path)
        root = os.path.normpath(settings.MEDIA_ROOT)
        while parent and os.path.normpath(parent) != root:
            try:
                if os.path.isdir(parent) and not os.listdir(parent):
                    os.rmdir(parent)
                else:
                    break
            except OSError:
                break
            parent = os.path.dirname(parent)
    except OSError:
        pass


def _remove_empty_dirs_up_to(start_dir, root):
    """Best-effort remove empty dirs from ``start_dir`` upward (root exclusive).

    Used after moving files out of a batch (uncombine): the sub-batch dir, and
    the batch dir itself when emptied, are removed so an emptied batch
    disappears from the batch listing instead of lingering as a husk.
    """
    parent = os.path.normpath(start_dir)
    root_n = os.path.normpath(root)
    while parent and parent != root_n:
        try:
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
            else:
                break
        except OSError:
            break
        parent = os.path.dirname(parent)


def _group_duplicates(user):
    """Group the user's files by exact (filename, file_size) match.

    Returns a list of groups, each ``{'filename', 'file_size', 'files': [...]}``
    where ``files`` is ordered by id ascending (the first entry is the
    canonical file kept when duplicates are cleaned). Groups with fewer than
    two files are dropped. Works across single and batch files.
    """
    grouped = {}
    rows = DataFile.objects.filter(owner=user).order_by('id').values(
        'id', 'filename', 'file_size', 'file_type', 'batch_name', 'sub_batch',
        'created_at',
    )
    for r in rows:
        key = (r['filename'], r['file_size'])
        group = grouped.setdefault(key, {
            'filename': r['filename'],
            'file_size': r['file_size'],
            'files': [],
        })
        group['files'].append({
            'id': r['id'],
            'filename': r['filename'],
            'file_size': r['file_size'],
            'file_type': r['file_type'],
            'batch_name': r['batch_name'] or '',
            'sub_batch': r['sub_batch'] or '',
            'created_at': r['created_at'].isoformat() if r['created_at'] else '',
        })
    groups = [g for g in grouped.values() if len(g['files']) >= 2]
    groups.sort(key=lambda g: (g['filename'].lower(), g['file_size']))
    return groups


def _find_duplicate_groups(user, limit=50):
    """Duplicate groups for the repair center: ``(groups, total_group_count)``.

    ``groups`` is capped at ``limit`` for display; the count reflects all.
    """
    groups = _group_duplicates(user)
    return groups[:limit], len(groups)


def _delete_duplicate_files(user):
    """Delete duplicate files (same filename+size), keeping the lowest id per
    group (the earliest registered). Returns the number of deleted rows.

    Per-file transaction so a mid-way failure never rolls back completed
    deletions; the action is idempotent. Only the duplicate file is removed —
    an existing batch directory and its remaining files are untouched.
    """
    deleted_count = 0
    for group in _group_duplicates(user):
        for item in group['files'][1:]:
            df = DataFile.objects.filter(owner=user, pk=item['id']).first()
            if df is None:
                continue
            with transaction.atomic():
                _delete_datafile_file_only(df)
                df.delete()
            deleted_count += 1
    clear_parse_cache()
    return deleted_count


def _batch_ctx(file_path, batch_base):
    """Derive (batch_name, sub_batch) for a file under the batch base dir.

    Semantics match ``BatchDirImportView.post``: batch_name is the first path
    segment below ``batch_base``, sub_batch is everything in between (multi-level
    subdirectories joined with os.sep). A file sitting directly in ``batch_base``
    yields an empty batch_name (edge case, tolerated by the UI as "—").
    """
    rel = os.path.relpath(file_path, batch_base)
    parts = rel.split(os.sep)
    batch_name = parts[0] if len(parts) >= 2 else ''
    sub_batch = os.sep.join(parts[1:-1]) if len(parts) >= 3 else ''
    return batch_name, sub_batch


def _zip_base_name(filename):
    """Strip a trailing ``.zip`` (case-insensitive) and clean Windows-illegal
    filename characters so the name is safe as a batch directory name.
    """
    base = re.sub(r'\.zip$', '', filename, flags=re.IGNORECASE)
    base = re.sub(r'[<>:"/\\|?*]', '_', base).strip()
    return base or 'archive'


def _safe_extract_zip(zip_file, dest_dir):
    """Extract a zip archive into ``dest_dir`` with Zip-Slip protection.

    Returns the list of successfully extracted file paths. Archive members
    that would escape ``dest_dir`` (absolute paths, ``..`` segments, drive
    letters) and members that fail to write (bad encoding, IO errors) are
    skipped individually rather than failing the whole archive.

    ``zip_file`` may be a file-like object (e.g. Django's UploadedFile)
    or a path; the archive is streamed, never written to disk first.
    """
    extracted = []
    with zipfile.ZipFile(zip_file) as zf:
        for member in zf.infolist():
            if member.is_dir() or not member.filename:
                continue
            # Normalize separators, strip leading slashes, reject drive letters
            # and any ``..`` path segment (Zip-Slip).
            name = member.filename.replace('\\', '/')
            name = name.lstrip('/')
            if re.match(r'^[a-zA-Z]:', name) or any(seg == '..' for seg in name.split('/')):
                continue
            target = os.path.join(dest_dir, name)
            real_dest = os.path.realpath(dest_dir)
            try:
                if os.path.commonpath([real_dest, os.path.realpath(target)]) != real_dest:
                    continue
            except ValueError:
                continue  # different drive → outside dest_dir
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(target)
            except (OSError, ValueError, RuntimeError):
                continue
    return extracted


def _register_zip_batch(user, zip_file, filename):
    """Extract ``filename``'s zip and register every CSV inside as batch data.

    Returns ``(created, error_message)``:
    - success: ``(list[DataFile], None)`` — CSVs registered under the batch
      named after the zip (minus ``.zip``), sub-batches from zip sub-directories;
    - corrupt archive: ``([], '压缩包 {filename} 已损坏，无法解压')``;
    - no CSV found: ``([], '压缩包 {filename} 内未找到 CSV 数据文件')`` —
      only a freshly-created destination directory is removed, never an
      existing batch directory.

    Mirrors ``BatchDirImportView.post`` registration semantics: already
    registered paths are skipped, ``Sum_*`` summary dumps are ignored.
    """
    batch_name = _zip_base_name(filename)
    dest_dir = os.path.join(_user_upload_dir(user, 'batch'), batch_name)
    dir_existed = os.path.isdir(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)

    try:
        extracted = _safe_extract_zip(zip_file, dest_dir)
    except zipfile.BadZipFile:
        return [], f'压缩包 {filename} 已损坏，无法解压'

    csv_paths = [p for p in extracted if _is_data_csv(os.path.basename(p))]
    if not csv_paths:
        if not dir_existed:
            shutil.rmtree(dest_dir, ignore_errors=True)
        return [], f'压缩包 {filename} 内未找到 CSV 数据文件'

    existing_paths = set(
        os.path.normpath(resolve_file_path(p)) for p in
        DataFile.objects.filter(owner=user, file_type='batch', batch_name=batch_name)
        .values_list('file_path', flat=True)
    )
    batch_base = _user_upload_dir(user, 'batch')
    created = []
    with transaction.atomic():
        for fp in csv_paths:
            if os.path.normpath(fp) in existing_paths:
                continue  # already registered (re-upload of the same zip)
            _, sub_batch = _batch_ctx(fp, batch_base)
            try:
                created.append(_register_file(user, fp, 'batch', batch_name, sub_batch))
            except Exception:
                logger.warning(
                    '_register_zip_batch: failed to register %s', fp,
                    exc_info=True,
                )
                continue
    return created, None


def _resolve_product_code(filename, file_path, program_name):
    """Full product-code extraction chain: DB program_name first, reparse fallback.

    Returns ``(code, refreshed_program_name)``. ``code`` is ``''`` when neither
    source yields a match. ``refreshed_program_name`` is the program name
    recovered by reparsing the file header (``''`` when not reparsed or nothing
    found) — callers may persist it so future fixes start from a warmer cache.
    """
    code = extract_product_code(filename, program_name)
    if code:
        return code, ''
    if not os.path.exists(file_path):
        return '', ''
    # Reparse the file header for its test-program name (mirrors _register_file).
    refreshed = ''
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(4096)
        format_type = BaseATEParser.identify_format(head)
        if format_type != 'Unknown':
            df, metadata = get_parser(format_type).parse(file_path)
            if df is not None:
                refreshed = metadata.get('program_name', '')
    except Exception:
        logger.warning(
            '_resolve_product_code: reparse failed for %s', file_path,
            exc_info=True,
        )
    return extract_product_code(filename, refreshed), refreshed


def _scan_orphaned_disk(user):
    """Scan the user's batch dir for disk CSVs with no registered DataFile.

    Returns a sorted list of ``(file_path, batch_name, sub_batch)`` tuples —
    the single source of truth for the "orphaned disk file" set, shared by the
    consistency check's GET (listing) and POST (import / delete) actions so the
    set definition cannot drift.
    """
    batch_base = _user_upload_dir(user, 'batch')
    registered_paths = set(
        os.path.normpath(resolve_file_path(p)) for p in
        DataFile.objects.filter(
            owner=user, file_type='batch'
        ).values_list('file_path', flat=True)
    )
    orphans = []
    if os.path.isdir(batch_base):
        for root, _dirs, files in os.walk(batch_base):
            for f in files:
                if not _is_data_csv(f):
                    continue
                fp = os.path.normpath(os.path.join(root, f))
                if fp in registered_paths:
                    continue
                batch_name, sub_batch = _batch_ctx(fp, batch_base)
                orphans.append((fp, batch_name, sub_batch))
    orphans.sort(key=lambda item: (item[1], item[0]))
    return orphans
