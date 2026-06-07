import json
import math
import os

import pandas as pd
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser
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
    get_coord_columns,
    get_columns_with_limits,
    get_1d_from,
    compute_qqplot,
    compute_uph,
    build_fail_mask,
    build_col_meta,
)
from apps.analysis.services.data_services import (
    compute_histogram_stats,
    compute_wafer_map_data,
    compute_multi_lot_distribution,
    compute_correlation_scatter,
    compute_serial_distribution_data,
    compute_cpk_table_data,
)
from apps.analysis.services.limits import resolve_limits
from apps.datafiles.services import get_cached_parsed_file
from apps.common.params import get_param, get_param_float, get_param_list


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
    # Reconstruct datafile for the return contract (callers access .id etc.)
    datafile = DataFile.objects.filter(pk=file_id, owner=request.user).first()
    if datafile is None:
        return None, None, None, 'file_not_found'
    return df, datafile, metadata, None


class AnalysisViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get', 'post'])
    def histogram(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = get_param_list(request,'params')
        ignore_no_limit = str(get_param(request, 'ignore_no_limit', '')).lower() in ('true', '1', 'yes')

        if not params:
            numeric_cols = [c for c in df.columns if df[c].dtype in ('int64', 'float64')]
            if ignore_no_limit:
                params = get_columns_with_limits(df, metadata)
            else:
                params = numeric_cols
            # Fast path: only return param names, no heavy computation
            return Response({
                'file_id': datafile.id,
                'filename': datafile.filename,
                'format_type': datafile.format_type,
                'results': {p: {} for p in params},
            })

        if ignore_no_limit:
            cols_with_limits = set(get_columns_with_limits(df, metadata))
            params = [p for p in params if p in cols_with_limits]

        range_type = get_param(request, 'range_type', 'RDL')
        custom_low = get_param_float(request, 'custom_low')
        custom_high = get_param_float(request, 'custom_high')

        results = {}
        site_col = get_site_column(df)
        for param in params:
            result = compute_histogram_stats(
                df, metadata, param, site_col,
                range_type=range_type, custom_low=custom_low, custom_high=custom_high)
            if result is not None:
                results[param] = result

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'format_type': datafile.format_type,
            'results': results,
        }))

    @action(detail=False, methods=['get', 'post'])
    def wafer_map(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        x_col, y_col = get_coord_columns(df)
        if not x_col or not y_col:
            return Response({'error': 'no_coord_columns'})

        param = get_param(request, 'param')
        color_by = get_param(request, 'color_by', 'result')

        wm = compute_wafer_map_data(df, metadata, param, color_by, x_col, y_col)

        return Response(clean_data({
            'file_id': datafile.id,
            'x_col': x_col,
            'y_col': y_col,
            'points': wm['points'],
            'stats': wm['stats'],
            'wafer': wm['wafer'],
        }))

    @action(detail=False, methods=['get', 'post'])
    def multi_lot(self, request):
        file_ids = get_param_list(request,'file_ids')
        param = get_param(request, 'param')
        if len(file_ids) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        datasets = {}
        all_series = []
        for fid in file_ids:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            use_cache = False
            # Can use cache only when we don't need the DB object for other fields
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk)
            if df is None:
                continue
            if param and param in df.columns:
                s = get_1d_from(df, param).dropna()
                s = s[abs(s) < float('inf')]
                if len(s) > 0:
                    datasets[str(fid)] = {
                        'df': df, 'metadata': metadata, 'series': s,
                        'name': df_obj.filename[:20],
                    }
                    all_series.append(s)

        if not all_series:
            return Response({'error': 'no_data'}, status=400)

        result = compute_multi_lot_distribution(datasets, all_series, param)

        return Response(clean_data(result))

    @action(detail=False, methods=['get', 'post'])
    def correlation(self, request):
        """Return raw data for two selected parameters, organized by Site for scatter plot."""
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param_x = get_param(request, 'param_x')
        param_y = get_param(request, 'param_y')
        if not param_x or not param_y:
            return Response({'error': 'param_x_and_param_y_required'}, status=400)

        if param_x not in df.columns or param_y not in df.columns:
            return Response({'error': 'param_not_found'}, status=400)

        result = compute_correlation_scatter(df, param_x, param_y)

        return Response(clean_data(result))

    @action(detail=False, methods=['get', 'post'])
    def serial_distribution(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param = get_param(request, 'param')
        if not param:
            return Response({'error': 'param_required'}, status=400)

        chart_config = json.loads(get_param(request, 'chart_config', '[]'))
        range_type = get_param(request, 'range_type', 'RDL')

        result = compute_serial_distribution_data(
            df, metadata, param, range_type, chart_config)
        if result is None:
            return Response({'error': 'no_serial_column'})

        return Response(clean_data(result))

    @action(detail=False, methods=['get', 'post'])
    def cpk(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = get_param_list(request,'params')
        if not params:
            params = get_columns_with_limits(df, metadata)

        result = compute_cpk_table_data(df, metadata, params)

        return Response(clean_data(result))


    @action(detail=False, methods=['get', 'post'])
    def qqplot(self, request):
        """
        Compute QQ plot data for normality testing of a single parameter.

        Request body:
        {
            "file_id": 123,
            "param": "Param1"
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param = get_param(request, 'param')
        if not param:
            return Response({'error': 'param_required'}, status=400)
        if param not in df.columns:
            return Response({'error': 'param_not_found'}, status=400)

        data_series = get_1d_from(df, param)
        result = compute_qqplot(data_series)

        return Response(clean_data(result))

    @action(detail=False, methods=['get', 'post'])
    def uph(self, request):
        """
        Compute UPH (Units Per Hour) using the parallel-site throughput model.

        Request body:
        {
            "file_id": 123,
            "test_time_col": "Test_Time",      # optional override
            "manual_test_time_sec": 8.5         # optional per-unit time (seconds)
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        test_time_col = get_param(request, 'test_time_col')
        manual_test_time_sec = get_param(request, 'manual_test_time_sec')
        if manual_test_time_sec is not None:
            manual_test_time_sec = float(manual_test_time_sec)
        result = compute_uph(df, metadata, test_time_col=test_time_col,
                             manual_test_time_sec=manual_test_time_sec)

        return Response(clean_data(result))




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

        if not params or len(params) < 2:
            return Response({'error': 'need_at_least_2_params', 'available_params': get_columns_with_limits(df, metadata)}, status=400)

        result = compute_correlation_matrix(df, params, method)

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
        file_data_list = []
        for file_id in file_ids:
            try:
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

        results = {}

        for param in params:
            if param not in df.columns:
                continue

            data_series = get_1d_from(df, param)
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
        file_data_list = []
        for file_id in file_ids:
            try:
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

        if not file_data_list:
            return Response({'error': 'no_valid_files'}, status=400)

        result = compute_param_trend(file_data_list, param)

        return Response(clean_data(result))
