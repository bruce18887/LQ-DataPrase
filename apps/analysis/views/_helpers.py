"""Shared helper functions for analysis views."""

import math

import pandas as pd

from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file


def clean_data(data):
    if isinstance(data, list):
        return [clean_data(item) for item in data]
    elif isinstance(data, dict):
        return {k: clean_data(v) for k, v in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    else:
        return data


def _filter_blank_params(params):
    """Drop fully-blank / empty / whitespace-only column names from a params list.

    Some parsers (CTA8280F trailing comma, etc.) yield an unnamed column
    whose empty-string name passes the dtype check (all-NaN is float64)
    but cannot be selected by users and would 400 the analysis endpoints
    with `param_not_found`. Stripping blanks here keeps the param
    selector honest and protects the QQ plot / histogram / wafer_map
    fast paths uniformly.
    """
    return [p for p in params if p and str(p).strip()]


def _sanitize_numeric_params(df, params):
    """Filter params to only those that are valid numeric columns with data.

    Removes: blank names, all-NaN columns, non-numeric columns, duplicate names.
    """
    # Deduplicate columns first
    df = df.loc[:, ~df.columns.duplicated()]
    valid = []
    for p in params:
        if not p or not str(p).strip():
            continue
        if p not in df.columns:
            continue
        col = df[p]
        # If duplicate columns were collapsed, get_1d_from style extraction
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        # Skip all-NaN columns
        if col.dropna().empty:
            continue
        # Skip non-numeric
        if not pd.api.types.is_numeric_dtype(col):
            continue
        valid.append(p)
    return valid


def _load_df_from_request(request):
    file_id = request.data.get('file_id') or request.query_params.get('file_id')
    if not file_id:
        return None, None, None, 'file_id_required'
    file_id = int(file_id)
    df, metadata, fmt = get_cached_parsed_file(file_id, request.user.pk)
    if df is None and fmt is not None:
        # file_id valid but file not on disk or parse failed
        return None, None, None, 'file_not_found_or_parse_failed'
    if df is None:
        return None, None, None, 'file_not_found'
    # Deduplicate columns to prevent DataFrame-vs-Series issues downstream
    df = df.loc[:, ~df.columns.duplicated()]
    # Reconstruct datafile for the return contract (callers access .id etc.)
    datafile = DataFile.objects.filter(pk=file_id, owner=request.user).first()
    if datafile is None:
        return None, None, None, 'file_not_found'
    return df, datafile, metadata, None


def _load_files_from_request(request, file_ids):
    """Load multiple files from request for cross-file analysis.

    Returns list of dicts with df, metadata, file_id, filename, timestamp.
    """
    file_data_list = []
    for file_id in file_ids:
        try:
            from django.shortcuts import get_object_or_404
            import os
            datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
            if not os.path.exists(datafile.file_path):
                continue

            df, metadata, fmt = get_cached_parsed_file(int(file_id), request.user.pk)
            if df is None:
                continue

            file_data_list.append({
                'df': df,
                'metadata': metadata,
                'file_id': datafile.id,
                'filename': datafile.filename,
                'timestamp': datafile.created_at.strftime('%Y-%m-%d %H:%M:%S') if datafile.created_at else ''
            })
        except Exception as e:
            continue
    return file_data_list
