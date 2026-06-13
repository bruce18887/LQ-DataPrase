"""Statistics and cross-file analysis views."""

import os

import pandas as pd

from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.datafiles.models import DataFile
from apps.analysis.services.statistics import (
    detect_fail_data,
    calculate_fail_bin_statistics,
    compute_correlation_matrix,
    compute_bin_trend,
    compute_boxplot_stats,
    compute_param_trend,
    compute_range_statistics,
    compute_site_stats,
    get_site_column,
    get_columns_with_limits,
    get_1d_from,
    build_fail_mask,
    build_col_meta,
    ensure_numeric,
)
from apps.datafiles.services import get_cached_parsed_file
from apps.common.params import get_param, get_param_float, get_param_list
from apps.analysis.services.limits import resolve_limits

from ._helpers import (
    clean_data,
    _sanitize_numeric_params,
    _load_df_from_request,
    _load_files_from_request,
)


class StatisticsViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get', 'post'])
    def detect_fail(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata)
        unique_fail_rows = len(set(fail_indices))

        fail_mask = build_fail_mask(fail_cells)
        col_meta = build_col_meta(df, metadata)

        return Response(clean_data({
            'fail_row_count': unique_fail_rows,
            'total_rows': df.shape[0],
            'fail_col_summary': list(set(fail_columns))[:50],
            'fail_mask': fail_mask,
            'col_meta': col_meta,
        }))

    @action(detail=False, methods=['get', 'post'])
    def bin_stats(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        stats = calculate_fail_bin_statistics(df, metadata)
        result = []
        for bv, s in stats.items():
            result.append({
                'bin': str(bv),
                'count': s['count'],
                'percentage': s['percentage'],
            })
        return Response({'bin_stats': result})

    @action(detail=False, methods=['get', 'post'])
    def site_stats(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param = get_param(request, 'param')
        if not param:
            return Response({'error': 'param_required'}, status=400)

        range_type = get_param(request, 'range_type', 'RDL')

        data_series = get_1d_from(df, param).dropna()
        data_series = data_series[data_series.apply(lambda x: abs(x) < float('inf'))]
        site_col = get_site_column(df)

        if not site_col:
            return Response({
                'error': 'no_site_column',
                'site_data': [],
                'available_columns': list(df.columns),
            })

        stats = compute_range_statistics(data_series, metadata, param)
        lower_limit, upper_limit = resolve_limits(range_type, stats)

        site_idx = get_1d_from(df, site_col)
        site_result = compute_site_stats(
            data_series, site_idx, lower_limit, upper_limit,
            None, None, False
        )

        return Response(clean_data({
            'param': param,
            'site_data': site_result,
        }))

    @action(detail=False, methods=['get', 'post'])
    def correlation_matrix(self, request):
        """
        Compute correlation matrix for multiple parameters.

        Request body:
        {
            "file_id": 123,
            "params": ["Param1", "Param2", "Param3"],  // Optional, defaults to all numeric params with limits
            "method": "pearson"  // Optional: "pearson", "spearman", or "kendall"
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = get_param_list(request,'params')
        method = get_param(request, 'method', 'pearson')

        # Validate method
        if method not in ['pearson', 'spearman', 'kendall']:
            return Response({'error': 'invalid_method', 'valid_methods': ['pearson', 'spearman', 'kendall']}, status=400)

        # If no params specified, use all columns with limits
        if not params:
            params = get_columns_with_limits(df, metadata)

        # Filter to valid numeric params
        params = _sanitize_numeric_params(df, params)

        if not params or len(params) < 2:
            return Response({'error': 'need_at_least_2_params', 'available_params': get_columns_with_limits(df, metadata)}, status=400)

        try:
            result = compute_correlation_matrix(df, params, method)
        except (TypeError, ValueError) as e:
            return Response({'error': 'correlation_failed', 'detail': str(e)}, status=400)

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            **result
        }))

    @action(detail=False, methods=['get', 'post'])
    def bin_trend(self, request):
        """
        Compute bin distribution trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "group_by": "file"  // Optional: "file" or "date"
        }
        """
        file_ids = get_param_list(request,'file_ids')
        if not file_ids:
            return Response({'error': 'file_ids_required'}, status=400)

        # Load all files
        file_data_list = _load_files_from_request(request, file_ids)

        if not file_data_list:
            return Response({'error': 'no_valid_files'}, status=400)

        result = compute_bin_trend(file_data_list)

        return Response(clean_data(result))

    @action(detail=False, methods=['get', 'post'])
    def boxplot(self, request):
        """
        Compute box plot statistics for parameters.

        Request body:
        {
            "file_id": 123,
            "params": ["Param1", "Param2"],
            "group_by": "site"  // Optional: "site", "bin", or null for overall
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = get_param_list(request,'params')
        group_by = get_param(request, 'group_by')

        if not params:
            return Response({'error': 'params_required'}, status=400)

        # Filter out invalid params (blank, all-NaN, non-numeric)
        requested_params = list(params)
        params = _sanitize_numeric_params(df, params)
        if not params:
            # Surface the requested-but-missing list so the front end can
            # show a clear "param not in file" message (e.g. stale
            # `R_Kelvin_AGND` after switching from gage_m_S4.csv to an
            # ETS88 file). Mirrors the same shape as the histogram 400.
            missing = [p for p in requested_params if p and str(p).strip() and p not in df.columns]
            return Response({
                'error': 'no_valid_params',
                'detail': '请求的参数均不在该文件中，请重新选择文件或参数',
                'requested': requested_params,
                'missing': missing,
            }, status=400)

        results = {}

        for param in params:
            if param not in df.columns:
                continue

            data_series = ensure_numeric(df, param)
            if data_series.dropna().empty:
                continue
            param_result = {
                'overall': compute_boxplot_stats(data_series)
            }

            # Group by site or bin if requested
            if group_by == 'site':
                site_col = get_site_column(df)
                if site_col:
                    site_idx = get_1d_from(df, site_col)
                    by_group = {}
                    for site in site_idx.unique():
                        if pd.isna(site):
                            continue
                        mask = (site_idx == site)
                        if isinstance(mask, pd.Series):
                            mask = mask.values
                        site_data = data_series[mask]
                        by_group[str(site)] = compute_boxplot_stats(site_data)
                    param_result['by_site'] = by_group

            elif group_by == 'bin':
                bin_col = None
                for col in df.columns:
                    if 'bin' in col.lower():
                        bin_col = col
                        break
                if bin_col:
                    bin_idx = get_1d_from(df, bin_col)
                    by_group = {}
                    for bin_val in bin_idx.unique():
                        if pd.isna(bin_val):
                            continue
                        mask = (bin_idx == bin_val)
                        if isinstance(mask, pd.Series):
                            mask = mask.values
                        bin_data = data_series[mask]
                        by_group[str(bin_val)] = compute_boxplot_stats(bin_data)
                    param_result['by_bin'] = by_group

            results[param] = param_result

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'results': results
        }))

    @action(detail=False, methods=['get', 'post'])
    def param_trend(self, request):
        """
        Compute parameter statistics trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "param": "Param1",
            "group_by": "file"  // Optional: "file" or "date"
        }
        """
        file_ids = get_param_list(request,'file_ids')
        param = get_param(request, 'param')

        if not file_ids:
            return Response({'error': 'file_ids_required'}, status=400)

        if not param:
            return Response({'error': 'param_required'}, status=400)

        # Load all files
        file_data_list = _load_files_from_request(request, file_ids)

        if not file_data_list:
            return Response({'error': 'no_valid_files'}, status=400)

        result = compute_param_trend(file_data_list, param)

        return Response(clean_data(result))
