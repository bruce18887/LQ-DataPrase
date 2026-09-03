"""Shared file-loading helpers used across multiple viewsets.

Eliminates the 5-line get_object_or_404 + get_cached_parsed_file + None-check
pattern repeated in export, dashboard, analysis, buyoff, gage, batch_report,
data_correlation, and datafiles views.
"""

import os

from django.shortcuts import get_object_or_404
from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.datafiles.utils import resolve_file_path


def load_user_file(request, file_id=None, *, check_exists=False):
    """Load a single file's DataFrame + metadata for the current user.

    Parameters
    ----------
    request : Request
        DRF request (used for request.user).
    file_id : int | str | None
        File ID. If None, taken from request.data or request.query_params.
    check_exists : bool
        If True, verify datafile.file_path exists on disk before parsing.

    Returns
    -------
    (df, datafile, metadata) on success.
    Raises FileLoadError on any failure.
    """
    if file_id is None:
        file_id = request.data.get('file_id') or request.query_params.get('file_id')
    if not file_id:
        raise FileLoadError('file_id_required')

    try:
        file_id = int(file_id)
    except (ValueError, TypeError):
        raise FileLoadError('file_id_invalid')
    datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)

    if check_exists:
        if not os.path.exists(resolve_file_path(datafile.file_path)):
            raise FileLoadError('file_not_found')

    df, metadata, fmt = get_cached_parsed_file(file_id, request.user.pk, datafile)
    if df is None:
        raise FileLoadError('parse_failed')

    return df, datafile, metadata


class FileLoadError(Exception):
    """Raised when a file cannot be loaded."""
    def __init__(self, error_code):
        self.error_code = error_code
        super().__init__(error_code)
