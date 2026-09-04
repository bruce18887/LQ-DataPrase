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
    calculate_fail_test_item_statistics,
    compute_correlation_matrix,
    compute_bin_trend,
    compute_boxplot_stats,
    compute_param_trend,
    compute_range_statistics,
    compute_site_stats,
    get_site_column,
    get_columns_with_limits,
    get_bin_column_name,
    resolve_spec_limits,
    get_1d_from,
    filter_finite,
    build_fail_mask,
    build_col_meta,
    ensure_numeric,
    filter_bin1_rows,
    filter_test_items,
    get_coord_columns,
    compute_wafer_fail_data,
)
from apps.analysis.services.data_services import (
    compute_wafer_geometry,
    compute_wafer_zone_stats,
)
from apps.datafiles.services import get_cached_parsed_file
from apps.common.params import get_param, get_param_float, get_param_list
from apps.analysis.services.limits import resolve_limits

from ._helpers import (
    clean_data,
    _sanitize_numeric_params,
    _load_df_from_request,
    _load_files_from_request,
    get_bool_param,
    get_cpk_b_threshold,
    parse_filter_flags,
    cached_low_cpk_items,
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
        if param not in df.columns:
            return Response({
                'error': 'param_not_found',
                'detail': f'参数 {param!r} 不在该文件中',
            }, status=400)

        range_type = get_param(request, 'range_type', 'RDL')
        # data_only_bin1 narrows the rows before series/site extraction so
        # the site table matches the histogram's Bin1-filtered stats.
        if get_bool_param(request, 'data_only_bin1'):
            df = filter_bin1_rows(df, metadata)

        data_series = filter_finite(get_1d_from(df, param))
        site_col = get_site_column(df)

        if not site_col:
            return Response({
                'error': 'no_site_column',
                'detail': '该文件没有 Site 列，无法进行站点统计',
            }, status=400)

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
    def zonal_yield(self, request):
        """晶圆分区良率：按半径 1/3、2/3 切中心/中间/边缘三区。

        Pass/Fail 判定复用 :func:`compute_wafer_fail_data`，与晶圆图同一口径；
        几何复用 :func:`compute_wafer_geometry`，与前端画出的圆环同源。
        ``param`` 缺省时按全部有 Limit 的测试项做全局判定（同 wafer_map）。
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param = get_param(request, 'param')
        if param and param not in df.columns:
            return Response({
                'error': 'param_not_found',
                'detail': f'参数 {param!r} 不在该文件中',
            }, status=400)

        x_col, y_col = get_coord_columns(df)
        if not x_col or not y_col:
            return Response({
                'error': 'no_coord_columns',
                'detail': '该文件没有坐标列（X_COORD/Y_COORD），无法分区统计',
            }, status=400)

        xs = pd.to_numeric(get_1d_from(df, x_col), errors='coerce')
        ys = pd.to_numeric(get_1d_from(df, y_col), errors='coerce')
        finite = xs.notna() & ys.notna()
        geometry = compute_wafer_geometry(xs[finite].tolist(), ys[finite].tolist())
        fail_mask, _stats = compute_wafer_fail_data(df, metadata, param)

        return Response(clean_data({
            'file_id': datafile.id,
            'param': param or '',
            'wafer': geometry,
            'zones': compute_wafer_zone_stats(
                xs.tolist(), ys.tolist(), fail_mask.tolist(), geometry),
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

        # 数据筛选（单文件口径，2026-08-20）：fail 集合基于全量 df 预计算
        #（bin1 过滤前），bin1 收窄行，其余开关对 params 列表防御性重放。
        flags = parse_filter_flags(request)
        cpk_threshold = get_cpk_b_threshold(request.user)
        iqr_multiplier = flags['iqr_multiplier']
        fail_items = None
        if flags['only_fail_test_item']:
            fail_items = set(calculate_fail_test_item_statistics(df, metadata).keys())
        low_cpk_items = None
        if flags['only_low_cpk']:
            low_cpk_items = cached_low_cpk_items(
                datafile, request.user.pk, df, metadata,
                cpk_threshold, iqr_multiplier, flags['data_only_bin1'])
        if flags['data_only_bin1']:
            df = filter_bin1_rows(df, metadata)

        # Filter to valid numeric params
        params = _sanitize_numeric_params(df, params)
        if flags['ignore_no_test_value'] or flags['only_fail_test_item'] or flags['only_low_cpk']:
            params = filter_test_items(
                df, metadata, params,
                ignore_no_test_value=flags['ignore_no_test_value'],
                only_fail_test_item=flags['only_fail_test_item'],
                only_low_cpk=flags['only_low_cpk'],
                cpk_threshold=cpk_threshold,
                fail_items=fail_items,
                iqr_multiplier=iqr_multiplier,
                low_cpk_items=low_cpk_items,
            )

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

        # data_only_bin1 narrows the rows before the per-param series
        # extraction so overall / by_site / by_bin stats only cover
        # pass-bin rows. Params that are all-NaN inside Bin1 are silently
        # skipped by the dropna().empty check in the loop (same semantics
        # as the histogram Bin1 mode hiding such params).
        if get_bool_param(request, 'data_only_bin1'):
            df = filter_bin1_rows(df, metadata)

        results = {}
        # 敏感度（IQR 倍数）与规格限一并传给箱线图：此前 compute_boxplot_stats
        # 的 whisker 写死 1.5*iqr 且完全不看规格限，导致① 调敏感度后同屏
        # 其他四图变了、箱线图没变；② 规格限内的合法数据被当异常值
        #（outliers.py 早已修好的同一个缺陷，箱线图没跟上）。
        iqr_multiplier = get_param_float(request, 'iqr_multiplier', 1.5)

        for param in params:
            if param not in df.columns:
                continue

            data_series = ensure_numeric(df, param)
            if data_series.dropna().empty:
                continue
            spec_limits = resolve_spec_limits(metadata, param)
            param_result = {
                'overall': compute_boxplot_stats(
                    data_series, spec_limits, iqr_multiplier)
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
                        by_group[str(site)] = compute_boxplot_stats(
                            site_data, spec_limits, iqr_multiplier)
                    param_result['by_site'] = by_group

            elif group_by == 'bin':
                # 优先用按格式映射的 bin 列（与 limits.calculate_fail_bin_statistics
                # 同源）。旧写法扫「第一个列名含 bin 的列」，依赖列序，可能取到
                # 硬件 bin 而不是软件 bin → 箱线图分组与良率统计分组不是同一个 bin。
                bin_col = get_bin_column_name(metadata.get('format', ''))
                if bin_col not in df.columns:
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
                        by_group[str(bin_val)] = compute_boxplot_stats(
                            bin_data, spec_limits, iqr_multiplier)
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
