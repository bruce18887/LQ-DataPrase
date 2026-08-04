"""Private helper functions for datafiles views."""

import os
import shutil

from django.conf import settings
from django.utils import timezone

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import BaseATEParser, get_parser
from apps.datafiles.utils import extract_product_code


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
        pass

    datafile = DataFile.objects.create(
        owner=user,
        filename=filename,
        file_path=file_path,
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
        filepath=file_path,
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


def _delete_datafile_on_disk(datafile):
    """Remove the on-disk file(s) backing a DataFile (best-effort)."""
    file_path = datafile.file_path
    try:
        if datafile.file_type == 'batch' and datafile.batch_name:
            # Batch: delete the entire batch directory
            batch_dir = os.path.dirname(file_path)
            if os.path.isdir(batch_dir):
                shutil.rmtree(batch_dir, ignore_errors=True)
        else:
            # Single: delete just the file
            if os.path.exists(file_path):
                os.remove(file_path)
    except OSError:
        pass


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
        pass
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
        os.path.normpath(p) for p in
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
