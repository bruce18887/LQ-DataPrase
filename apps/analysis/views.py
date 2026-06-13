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
    get_serial_column,
    get_coord_columns,
    get_columns_with_limits,
    get_1d_from,
    compute_qqplot,
    compute_uph,
    build_fail_mask,
    build_col_meta,
    ensure_numeric,
)
from apps.analysis.services.data_services import (
    compute_histogram_stats,
    compute_wafer_map_data,
    compute_multi_lot_distribution,
    compute_common_params,
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
            # Exclude serial/site columns — they are metadata, not data params
            _meta_cols = set()
            _sc = get_serial_column(df)
            if _sc: _meta_cols.add(_sc)
            _stc = get_site_column(df)
            if _stc: _meta_cols.add(_stc)
            numeric_cols = [c for c in df.columns
                           if df[c].dtype in ('int64', 'float64')
                           and not df[c].dropna().empty
                           and c not in _meta_cols]
            if ignore_no_limit:
                params = get_columns_with_limits(df, metadata)
            else:
                params = numeric_cols
            # Some parsers (CTA8280F trailing comma) yield an unnamed column
            # whose empty string name passes the dtype check (all-NaN is float64)
            # but cannot be selected by users and would 400 the analysis endpoints.
            # Drop blanks so the param selector never offers a phantom option.
            params = _filter_blank_params(params)
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
        # Guard: drop requested params that don't exist in this file's
        # DataFrame. The frontend param selector is built from the same
        # /analysis/histogram/ fast path, but a stale `selectedParam` from
        # a previous file can still be sent across (e.g. switching from
        # `gage_m_S4.csv` → `BPD93204_FT1_ETS163550_12252024.csv` after
        # picking `R_Kelvin_AGND`). Returning 400 with a structured
        # payload lets the front end render a clear "param not in file"
        # message instead of a 500 from `df[param]` KeyError inside
        # `compute_histogram_stats`.
        valid_params = [p for p in params if p in df.columns]
        missing_params = [p for p in params if p not in df.columns]
        if not valid_params:
            return Response({
                'error': 'no_valid_params',
                'detail': '请求的参数均不在该文件中，请重新选择文件或参数',
                'requested': params,
                'missing': missing_params,
            }, status=400)
        params = valid_params
        for param in params:
            try:
                result = compute_histogram_stats(
                    df, metadata, param, site_col,
                    range_type=range_type, custom_low=custom_low, custom_high=custom_high)
                if result is not None:
                    results[param] = result
            except Exception:
                # Re-raise so the 500 surfaces for any unexpected internal
                # error (out-of-memory, division-by-zero, etc.). The
                # param-not-in-df case is handled above as 400.
                raise

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
        file_ids = get_param_list(request, 'file_ids')
        param = get_param(request, 'param')
        if len(file_ids) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        # Load each selected file once (cached parse + DB row for filename).
        loaded = []  # (file_id, df, metadata, filename)
        for fid in file_ids:
            df_obj = DataFile.objects.filter(pk=fid, owner=request.user).first()
            if df_obj is None:
                continue
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk)
            if df is None:
                continue
            loaded.append((int(fid), df, metadata, df_obj.filename))

        if len(loaded) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        # No param → lightweight call: return the common test items + file names
        # so the front-end can populate the param selector before drawing.
        if not param:
            ignore_no_limit = str(
                get_param(request, 'ignore_no_limit', '')
            ).lower() in ('true', '1', 'yes')
            return Response({
                'common_params': compute_common_params(loaded, ignore_no_limit),
                'file_names': [
                    {'file_id': fid, 'filename': fn} for fid, _, _, fn in loaded
                ],
            })

        # With param → per-file distribution (no SITE split; one series/file).
        range_type = get_param(request, 'range_type', 'S4')
        custom_low = get_param_float(request, 'custom_low')
        custom_high = get_param_float(request, 'custom_high')

        datasets = {}
        all_series = []
        for fid, df, metadata, filename in loaded:
            if param in df.columns:
                s = get_1d_from(df, param).dropna()
                s = s[abs(s) < float('inf')]
                if len(s) > 0:
                    datasets[str(fid)] = {
                        'df': df, 'metadata': metadata, 'series': s,
                        'name': filename[:20], 'file_id': fid,
                    }
                    all_series.append(s)

        if not all_series:
            return Response({
                'param': param,
                'global_mean': None,
                'global_std': None,
                'chart_min': 0,
                'chart_max': 1,
                'bin_centers': [],
                'lot_data': [],
                'global_lsl': None,
                'global_usl': None,
            })

        result = compute_multi_lot_distribution(
            datasets, all_series, param,
            range_type=range_type, custom_low=custom_low, custom_high=custom_high,
        )

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
        if param not in df.columns:
            return Response({'error': 'param_not_found'}, status=400)
        # Reject serial/site columns as data param — they are grouping keys, not values
        serial_col = get_serial_column(df)
        site_col = get_site_column(df)
        if param == serial_col or param == site_col:
            return Response({'error': 'param_is_metadata',
                             'detail': f'{param} 是分组列，不能作为数据参数'}, status=400)
        # Validate param has numeric data
        col = get_1d_from(df, param)
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        if col.dropna().empty:
            return Response({'error': 'param_no_valid_data'}, status=400)

        chart_config_raw = get_param(request, 'chart_config', '[]')
        chart_config = chart_config_raw if isinstance(chart_config_raw, list) else json.loads(chart_config_raw)
        range_type = get_param(request, 'range_type', 'RDL')

        try:
            result = compute_serial_distribution_data(
                df, metadata, param, range_type, chart_config)
        except TypeError:
            return Response({'error': 'serial_distribution_failed',
                             'detail': '数据列存在重复或格式异常'}, status=400)
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
            return Response({
                'error': 'param_not_found',
                'detail': f'参数 {param!r} 不在该文件中',
            }, status=400)

        data_series = get_1d_from(df, param)
        if isinstance(data_series, pd.DataFrame):
            data_series = data_series.iloc[:, 0]
        # Skip if column is all-NaN or non-numeric
        if data_series.dropna().empty:
            return Response({'error': 'param_no_valid_data'}, status=400)
        try:
            result = compute_qqplot(data_series)
        except (TypeError, ValueError) as e:
            return Response({'error': 'qqplot_failed', 'detail': str(e)}, status=400)

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
