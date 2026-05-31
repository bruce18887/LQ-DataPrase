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


def clean_data(data):
    if isinstance(data, list):
        return [clean_data(item) for item in data]
    elif isinstance(data, dict):
        return {k: clean_data(v) for k, v in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return 0.0
        return data
    else:
        return data


def _load_df_from_request(request):
    file_id = request.data.get('file_id') or request.query_params.get('file_id')
    if not file_id:
        return None, None, None, 'file_id_required'
    datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
    if not os.path.exists(datafile.file_path):
        return None, datafile, None, 'file_not_found'

    parser = get_parser(datafile.format_type)
    df, metadata = parser.parse(datafile.file_path)
    if df is None:
        return None, datafile, None, 'parse_failed'
    return df, datafile, metadata, None


class AnalysisViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def histogram(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params')
        ignore_no_limit = request.data.get('ignore_no_limit', False)

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

        results = {}
        site_col = get_site_column(df)
        for param in params:
            result = compute_histogram_stats(df, metadata, param, site_col)
            if result is not None:
                results[param] = result

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'format_type': datafile.format_type,
            'results': results,
        }))

    @action(detail=False, methods=['post'])
    def wafer_map(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        x_col, y_col = get_coord_columns(df)
        if not x_col or not y_col:
            return Response({'error': 'no_coord_columns'})

        param = request.data.get('param')
        color_by = request.data.get('color_by', 'result')

        wm = compute_wafer_map_data(df, metadata, param, color_by, x_col, y_col)

        return Response(clean_data({
            'file_id': datafile.id,
            'x_col': x_col,
            'y_col': y_col,
            'points': wm['points'],
            'stats': wm['stats'],
            'wafer': wm['wafer'],
        }))

    @action(detail=False, methods=['post'])
    def multi_lot(self, request):
        file_ids = request.data.get('file_ids', [])
        param = request.data.get('param')
        if not file_ids or len(file_ids) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        datasets = {}
        all_series = []
        for fid in file_ids:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            parser = get_parser(df_obj.format_type)
            df, metadata = parser.parse(df_obj.file_path)
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

    @action(detail=False, methods=['post'])
    def correlation(self, request):
        """Return raw data for two selected parameters, organized by Site for scatter plot."""
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param_x = request.data.get('param_x')
        param_y = request.data.get('param_y')
        if not param_x or not param_y:
            return Response({'error': 'param_x_and_param_y_required'}, status=400)

        if param_x not in df.columns or param_y not in df.columns:
            return Response({'error': 'param_not_found'}, status=400)

        result = compute_correlation_scatter(df, param_x, param_y)

        return Response(clean_data(result))

    @action(detail=False, methods=['post'])
    def serial_distribution(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param = request.data.get('param')
        if not param:
            return Response({'error': 'param_required'}, status=400)

        chart_config = request.data.get('chart_config', [])
        range_type = request.data.get('range_type', 'RDL')

        result = compute_serial_distribution_data(
            df, metadata, param, range_type, chart_config)
        if result is None:
            return Response({'error': 'no_serial_column'})

        return Response(clean_data(result))

    @action(detail=False, methods=['post'])
    def cpk(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params')
        if not params:
            params = get_columns_with_limits(df, metadata)

        result = compute_cpk_table_data(df, metadata, params)

        return Response(clean_data(result))

    @action(detail=False, methods=['post'])
    def correlation_matrix(self, request):
        """
        Compute correlation matrix for multiple parameters.

        Request body:
        {
            "file_id": 123,
            "params": ["Param1", "Param2", "Param3"],  // Optional, defaults to all numeric params with limits
            "method": "pearson"  // or "spearman", default is "pearson"
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params', [])
        method = request.data.get('method', 'pearson')

        # Validate method
        if method not in ['pearson', 'spearman']:
            return Response({'error': 'invalid_method'}, status=400)

        # If no params specified, use all numeric columns with limits
        if not params:
            params = get_columns_with_limits(df, metadata)

        # Compute correlation matrix
        result = compute_correlation_matrix(df, params, method)

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'params': result['params'],
            'matrix': result['matrix'],
            'sample_size': result['sample_size'],
            'method': method
        }))

    @action(detail=False, methods=['post'])
    def bin_trend(self, request):
        """
        Compute bin distribution trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "group_by": "file"  // Currently only "file" is supported
        }
        """
        file_ids = request.data.get('file_ids', [])
        if not file_ids or not isinstance(file_ids, list):
            return Response({'error': 'file_ids_required'}, status=400)

        # Load all files
        dfs = []
        metadatas = []
        file_info = []

        for file_id in file_ids:
            try:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)

                if not os.path.exists(datafile.file_path):
                    continue

                parser = get_parser(datafile.format_type)
                df, metadata = parser.parse(datafile.file_path)

                dfs.append(df)
                metadatas.append(metadata)
                file_info.append({
                    'file_id': datafile.id,
                    'filename': datafile.filename,
                    'timestamp': datafile.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception:
                continue

        if len(dfs) == 0:
            return Response({'error': 'no_valid_files'}, status=400)

        # Compute bin trend
        result = compute_bin_trend(dfs, metadatas)

        return Response(clean_data({
            'files': file_info,
            'bins': result['bins'],
            'trend_data': result['trend_data'],
            'yield_trend': result['yield_trend']
        }))

    @action(detail=False, methods=['post'])
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

        params = request.data.get('params', [])
        group_by = request.data.get('group_by', None)

        if not params:
            return Response({'error': 'params_required'}, status=400)

        results = {}
        site_col = get_site_column(df) if group_by == 'site' else None

        for param in params:
            if param not in df.columns:
                continue

            data_series = get_1d_from(df, param)

            # Overall statistics
            overall_stats = compute_boxplot_stats(data_series)

            param_result = {
                'overall': overall_stats
            }

            # Group by site if requested
            if group_by == 'site' and site_col:
                site_idx = get_1d_from(df, site_col)
                by_site = {}

                for site in sorted(site_idx.unique(), key=str):
                    mask = (site_idx == site)
                    if isinstance(mask, pd.Series):
                        mask = mask.values
                    site_data = data_series[mask]
                    by_site[str(site)] = compute_boxplot_stats(site_data)

                param_result['by_site'] = by_site

            results[param] = param_result

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'results': results
        }))

    @action(detail=False, methods=['post'])
    def param_trend(self, request):
        """
        Compute parameter statistics trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "param": "Param1",
            "group_by": "file"  // Currently only "file" is supported
        }
        """
        file_ids = request.data.get('file_ids', [])
        param = request.data.get('param', '')

        if not file_ids or not isinstance(file_ids, list):
            return Response({'error': 'file_ids_required'}, status=400)

        if not param:
            return Response({'error': 'param_required'}, status=400)

        # Load all files
        dfs = []
        metadatas = []
        file_info = []

        for file_id in file_ids:
            try:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)

                if not os.path.exists(datafile.file_path):
                    continue

                parser = get_parser(datafile.format_type)
                df, metadata = parser.parse(datafile.file_path)

                dfs.append(df)
                metadatas.append(metadata)
                file_info.append({
                    'file_id': datafile.id,
                    'filename': datafile.filename,
                    'timestamp': datafile.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception:
                continue

        if len(dfs) == 0:
            return Response({'error': 'no_valid_files'}, status=400)

        # Compute parameter trend
        result = compute_param_trend(dfs, param, metadatas)

        return Response(clean_data({
            'files': file_info,
            'param': result['param'],
            'trend_data': result['trend_data'],
            'limits': result['limits']
        }))


class StatisticsViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def detect_fail(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata)
        unique_fail_rows = len(set(fail_indices))

        fail_mask = {}
        for idx, cols in fail_cells.items():
            fail_mask[str(idx)] = cols

        col_meta = {}
        units = metadata.get('units', {})
        mins = metadata.get('mins', {})
        maxs = metadata.get('maxs', {})
        for col in df.columns:
            col_meta[col] = {
                'unit': units.get(col, '') if isinstance(units, dict) else '',
                'min': mins.get(col, '') if isinstance(mins, dict) else '',
                'max': maxs.get(col, '') if isinstance(maxs, dict) else '',
            }

        return Response(clean_data({
            'fail_row_count': unique_fail_rows,
            'total_rows': df.shape[0],
            'fail_col_summary': list(set(fail_columns))[:50],
            'fail_mask': fail_mask,
            'col_meta': col_meta,
        }))

    @action(detail=False, methods=['post'])
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

    @action(detail=False, methods=['post'])
    def site_stats(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param = request.data.get('param')
        if not param:
            return Response({'error': 'param_required'}, status=400)

        range_type = request.data.get('range_type', 'RDL')

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

    @action(detail=False, methods=['post'])
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

        params = request.data.get('params')
        method = request.data.get('method', 'pearson')

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

    @action(detail=False, methods=['post'])
    def bin_trend(self, request):
        """
        Compute bin distribution trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "group_by": "file"  // Optional: "file" or "date"
        }
        """
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({'error': 'file_ids_required'}, status=400)

        # Load all files
        file_data_list = []
        for file_id in file_ids:
            try:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
                if not os.path.exists(datafile.file_path):
                    continue

                parser = get_parser(datafile.format_type)
                df, metadata = parser.parse(datafile.file_path)

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

    @action(detail=False, methods=['post'])
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

        params = request.data.get('params')
        group_by = request.data.get('group_by')

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

    @action(detail=False, methods=['post'])
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
        file_ids = request.data.get('file_ids', [])
        param = request.data.get('param')

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

                parser = get_parser(datafile.format_type)
                df, metadata = parser.parse(datafile.file_path)

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
