"""Single-file analysis views."""

import json

import pandas as pd
from django.shortcuts import get_object_or_404

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.datafiles.models import DataFile
from apps.analysis.services.statistics import (
    compute_correlation_matrix,
    compute_boxplot_stats,
    compute_range_statistics,
    compute_site_stats,
    get_site_column,
    get_serial_column,
    get_coord_columns,
    get_columns_with_limits,
    get_1d_from,
    compute_qqplot,
    compute_uph,
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

from ._helpers import (
    clean_data,
    _filter_blank_params,
    _sanitize_numeric_params,
    _load_df_from_request,
)


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
        iqr_multiplier = get_param_float(request, 'iqr_multiplier', 1.5)

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
                    range_type=range_type, custom_low=custom_low, custom_high=custom_high,
                    iqr_multiplier=iqr_multiplier)
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

        result = compute_correlation_scatter(df, param_x, param_y, metadata)

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
            result = compute_qqplot(data_series, metadata, param)
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

    @action(detail=False, methods=['post'])
    def file_correlation(self, request):
        """Compare two files by serial number and compute per-parameter correlation.

        Request body:
        {
            "file1_id": 123,
            "file2_id": 456,
            "threshold": 3.0,
            "ignore_no_limit": false
        }
        """
        file1_id = request.data.get('file1_id')
        file2_id = request.data.get('file2_id')
        threshold = float(request.data.get('threshold', 3.0))
        ignore_no_limit = request.data.get('ignore_no_limit', False)

        if not file1_id or not file2_id:
            return Response({'error': 'need_two_files'}, status=400)

        dfs = {}
        for fid, label in [(file1_id, 'ATE'), (file2_id, 'Bench')]:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk)
            if df is None:
                continue
            serial_col = get_serial_column(df)
            if serial_col:
                df['__serial__'] = pd.to_numeric(df[serial_col], errors='coerce')
            dfs[label] = {'df': df, 'metadata': metadata, 'serial': serial_col}

        if len(dfs) < 2:
            return Response({'error': 'parse_failed'}, status=400)

        ate_df = dfs['ATE']['df']
        bench_df = dfs['Bench']['df']
        ate_ser = ate_df['__serial__'] if '__serial__' in ate_df.columns else None
        bench_ser = bench_df['__serial__'] if '__serial__' in bench_df.columns else None

        if ate_ser is None or bench_ser is None:
            return Response({'error': 'no_serial_column'}, status=400)

        common_serials = set(ate_ser.dropna().astype(int)).intersection(set(bench_ser.dropna().astype(int)))
        numeric_cols_ate = [c for c in ate_df.columns if c not in ('__serial__',) and ate_df[c].dtype in ('int64', 'float64')]
        numeric_cols_bench = [c for c in bench_df.columns if c not in ('__serial__',) and bench_df[c].dtype in ('int64', 'float64')]
        common_params = sorted(set(numeric_cols_ate).intersection(numeric_cols_bench))

        summary = []
        for param in common_params[:100]:
            ate_vals = {}
            bench_vals = {}
            ate_idx = ate_df.set_index('__serial__')
            bench_idx = bench_df.set_index('__serial__')

            for ser in common_serials:
                if ser in ate_idx.index and ser in bench_idx.index:
                    try:
                        ate_vals[ser] = float(ate_idx.loc[ser, param].iloc[0] if isinstance(ate_idx.loc[ser, param], pd.Series) else ate_idx.loc[ser, param])
                        bench_vals[ser] = float(bench_idx.loc[ser, param].iloc[0] if isinstance(bench_idx.loc[ser, param], pd.Series) else bench_idx.loc[ser, param])
                    except:
                        pass

            diffs = []
            for ser in ate_vals:
                if ser in bench_vals:
                    try:
                        diff_pct = abs(ate_vals[ser] - bench_vals[ser]) / max(abs(ate_vals[ser]), 1e-9) * 100
                        diffs.append((ser, ate_vals[ser], bench_vals[ser], diff_pct))
                    except:
                        pass

            fail_count = sum(1 for d in diffs if d[3] > threshold)
            summary.append({
                'param': param,
                'compared': len(diffs),
                'fail_count': fail_count,
                'pass_rate': round((len(diffs) - fail_count) / len(diffs) * 100, 2) if diffs else 0,
                'max_diff': round(max(d[3] for d in diffs), 2) if diffs else 0,
            })

        return Response({
            'common_serials': len(common_serials),
            'common_params': len(common_params),
            'summary': summary,
            'params': common_params,
        })
