"""Shared file-loading helpers used across multiple viewsets.

Eliminates the 5-line get_object_or_404 + get_cached_parsed_file + None-check
pattern repeated in export, dashboard, analysis, buyoff, gage, batch_report,
data_correlation, and datafiles views.
"""

from django.shortcuts import get_object_or_404
from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file


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

    file_id = int(file_id)
    datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)

    if check_exists:
        import os
        if not os.path.exists(datafile.file_path):
            raise FileLoadError('file_not_found')

    df, metadata, fmt = get_cached_parsed_file(file_id, request.user.pk)
    if df is None:
        raise FileLoadError('parse_failed')

    return df, datafile, metadata


def load_user_files(request, file_ids, *, only_bin1=False):
    """Load multiple files' DataFrames for the current user.

    Parameters
    ----------
    request : Request
        DRF request.
    file_ids : list[int | str]
        List of file IDs to load.
    only_bin1 : bool
        If True, filter each DataFrame to Bin1-only rows.

    Returns
    -------
    list[dict]
        Each dict has keys: df, metadata, file_id, filename, datafile.
        Files that fail to load are silently skipped.
    """
    results = []
    for fid in file_ids:
        try:
            datafile = get_object_or_404(DataFile, pk=int(fid), owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk)
            if df is None:
                continue

            if only_bin1:
                df = _apply_bin1_filter(df, datafile)

            results.append({
                'df': df,
                'metadata': metadata,
                'file_id': int(fid),
                'filename': datafile.filename,
                'datafile': datafile,
            })
        except Exception:
            continue
    return results


def _apply_bin1_filter(df, datafile):
    """Filter DataFrame to Bin1-only rows."""
    from apps.analysis.services.statistics import get_bin_column_name
    import pandas as pd

    bin_col = get_bin_column_name(datafile.format_type)
    if bin_col and bin_col in df.columns:
        bin_numeric = pd.to_numeric(df[bin_col], errors='coerce')
        return df[bin_numeric == 1].copy()
    return df


class FileLoadError(Exception):
    """Raised when a file cannot be loaded."""
    def __init__(self, error_code):
        self.error_code = error_code
        super().__init__(error_code)
