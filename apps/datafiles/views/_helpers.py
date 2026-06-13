"""Private helper functions for datafiles views."""

import os
import shutil
import zipfile

from django.conf import settings
from django.utils import timezone

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import BaseATEParser, get_parser
from apps.datafiles.utils import extract_product_code

ARCHIVE_EXTENSIONS = {'.zip', '.7z', '.rar'}


def _is_archive(filename):
    return os.path.splitext(filename)[1].lower() in ARCHIVE_EXTENSIONS


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


def _extract_archive(file_path, dest_dir):
    """Extract ZIP/7z/RAR to dest_dir. Returns list of extracted file paths."""
    ext = os.path.splitext(file_path)[1].lower()
    extracted = []

    if ext == '.zip':
        with zipfile.ZipFile(file_path, 'r') as zf:
            for info in zf.infolist():
                if info.is_dir() or info.filename.startswith('__MACOSX'):
                    continue
                # Flatten: use only the basename
                name = os.path.basename(info.filename)
                if not name:
                    continue
                out_path = os.path.join(dest_dir, name)
                with zf.open(info) as src, open(out_path, 'wb') as dst:
                    dst.write(src.read())
                extracted.append(out_path)

    elif ext == '.7z':
        import py7zr
        with py7zr.SevenZipFile(file_path, 'r') as sz:
            for name, bio in sz.readall().items():
                basename = os.path.basename(name)
                if not basename:
                    continue
                out_path = os.path.join(dest_dir, basename)
                with open(out_path, 'wb') as dst:
                    dst.write(bio.read())
                extracted.append(out_path)

    elif ext == '.rar':
        import rarfile
        with rarfile.RarFile(file_path) as rf:
            for info in rf.infolist():
                if info.is_dir():
                    continue
                basename = os.path.basename(info.filename)
                if not basename:
                    continue
                out_path = os.path.join(dest_dir, basename)
                with rf.open(info) as src, open(out_path, 'wb') as dst:
                    dst.write(src.read())
                extracted.append(out_path)

    return extracted


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
