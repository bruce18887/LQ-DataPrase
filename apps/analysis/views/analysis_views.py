"""Single-file analysis views."""

import io
import json
import os
from typing import Dict, Optional, Set

import pandas as pd
from django.http import FileResponse
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
    get_serial_candidates,
    get_coord_columns,
    get_columns_with_limits,
    get_1d_from,
    compute_qqplot,
    compute_uph,
    ensure_numeric,
    calculate_fail_test_item_statistics,
    filter_bin1_rows,
    filter_test_items,
    compute_low_cpk_test_items,
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
from apps.analysis.services.file_correlation import (
    FileCorrelationConfig,
    compute_file_correlation,
    list_common_serials,
    NoCommonParamsError,
)
from apps.analysis.services.limits import resolve_limits
from apps.datafiles.services import get_cached_parsed_file
from apps.common.params import get_param, get_param_float, get_param_list

from ._helpers import (
    clean_data,
    _filter_blank_params,
    _sanitize_numeric_params,
    _load_df_from_request,
    get_bool_param,
    get_cpk_b_threshold,
    parse_filter_flags,
    cached_low_cpk_items,
)

# 兼容既有调用名（低 CPK 缓存已上移 _helpers，多视图共享）
_cached_low_cpk_items = cached_low_cpk_items


class AnalysisViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get', 'post'])
    def histogram(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = get_param_list(request,'params')
        ignore_no_limit = get_bool_param(request, 'ignore_no_limit')
        # Chart-config switches: two filter test items (param list level),
        # one filters data rows (Bin1 only). Fail detection must run on the
        # FULL frame — fail rows are never Bin1 — so it is precomputed
        # before filter_bin1_rows narrows the frame.
        ignore_no_test_value = get_bool_param(request, 'ignore_no_test_value')
        data_only_bin1 = get_bool_param(request, 'data_only_bin1')
        only_fail_test_item = get_bool_param(request, 'only_fail_test_item')
        only_low_cpk = get_bool_param(request, 'only_low_cpk')
        cpk_threshold = get_cpk_b_threshold(request.user)
        # 低 CPK 判定跟随前端统计卡显示口径（有异常值即用 filtered CPK），
        # iqr_multiplier 影响异常值集合，须与直方图计算一致。
        iqr_multiplier = get_param_float(request, 'iqr_multiplier', 1.5)
        df_full = df

        if not params:
            # Fast path: fail set covers the full candidate list; the
            # low-CPK set is cached per file (re-evaluating every column on
            # each config toggle is the dominant filter-chain cost).
            fail_items = None
            if only_fail_test_item:
                fail_items = set(calculate_fail_test_item_statistics(df_full, metadata).keys())
            low_cpk_items = None
            if only_low_cpk:
                low_cpk_items = _cached_low_cpk_items(
                    datafile, request.user.pk, df, metadata,
                    cpk_threshold, iqr_multiplier, data_only_bin1)
            # data_only_bin1 narrows the frame before the base param list is
            # derived, so the list is consistent with the histogram stats.
            if data_only_bin1:
                df = filter_bin1_rows(df, metadata)
            # Exclude serial/site columns — they are metadata, not data params.
            # 排除全部候选列：Serial_No 与 Dut_No 并存时两者都不能当参数
            _meta_cols = set(get_serial_candidates(df))
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
            params = filter_test_items(
                df, metadata, params,
                ignore_no_test_value=ignore_no_test_value,
                only_fail_test_item=only_fail_test_item,
                only_low_cpk=only_low_cpk,
                cpk_threshold=cpk_threshold,
                fail_items=fail_items,
                iqr_multiplier=iqr_multiplier,
                low_cpk_items=low_cpk_items,
            )
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
        # Compute path: the fail set only needs the requested params (a
        # param switch must not re-scan every column of the file).
        fail_items = None
        if only_fail_test_item:
            fail_items = set(calculate_fail_test_item_statistics(
                df_full, metadata, columns=params).keys())
        # data_only_bin1 narrows the rows before any statistic is computed.
        if data_only_bin1:
            df = filter_bin1_rows(df, metadata)
        # Defensive replay of the test-item switches so stale params the
        # front end may still be holding (before the list refresh lands)
        # cannot produce charts outside the configured scope.
        params = filter_test_items(
            df, metadata, params,
            ignore_no_test_value=ignore_no_test_value,
            only_fail_test_item=only_fail_test_item,
            only_low_cpk=only_low_cpk,
            cpk_threshold=cpk_threshold,
            fail_items=fail_items,
            iqr_multiplier=iqr_multiplier,
        )

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
            # 计算路径不吞异常：任何意外内部错误直接 500 暴露（param 不在 df
            # 的情况已在上面作为 400 处理）
            result = compute_histogram_stats(
                df, metadata, param, site_col,
                range_type=range_type, custom_low=custom_low, custom_high=custom_high,
                iqr_multiplier=iqr_multiplier)
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
            # 400 而非 200：让前端 axios 错误路径弹出提示，避免晶圆图静默空白
            return Response({
                'error': 'no_coord_columns',
                'detail': '该文件没有坐标列（X_COORD/Y_COORD），无法绘制晶圆图',
            }, status=400)

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
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk, df_obj)
            if df is None:
                continue
            loaded.append((int(fid), df, metadata, df_obj.filename))

        if len(loaded) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        # No param → lightweight call: return the common test items + file names
        # so the front-end can populate the param selector before drawing.
        # 合并请求优化：文件已在本请求内加载（冷缓存 0.46s/个），顺带返回
        # 首个公共参数的分布——前端免去串行第二次请求再遍历一轮文件加载
        # （冷缓存 ~3.6s → ~2.2s）。
        if not param:
            flags = parse_filter_flags(request)
            cpk_threshold = get_cpk_b_threshold(request.user)
            iqr_multiplier = flags['iqr_multiplier']
            # data_only_bin1 先收窄行再派生基础候选列表（与单文件 fast-path 口径一致）
            loaded_work = loaded
            if flags['data_only_bin1']:
                loaded_work = [
                    (fid, filter_bin1_rows(df, metadata), metadata, fn)
                    for fid, df, metadata, fn in loaded
                ]
            common_params = compute_common_params(loaded_work, flags['ignore_no_limit'])
            # 其余筛选（忽略无测试值/仅Fail项/仅低CPK）：对交集按每个文件过滤后
            # 再取交集——fail 集合必须基于全量 df 预计算（bin1 过滤前，否则
            # fail 恒空）；低 CPK 走共享缓存（key 含 mtime+size 自动失效）。
            if flags['ignore_no_test_value'] or flags['only_fail_test_item'] or flags['only_low_cpk']:
                per_file = []
                for (fid, df, metadata, _fn), (_fid2, full_df, _, _) in zip(loaded_work, loaded):
                    fail_items = None
                    if flags['only_fail_test_item']:
                        fail_items = set(calculate_fail_test_item_statistics(full_df, metadata).keys())
                    low_cpk_items = None
                    if flags['only_low_cpk']:
                        df_obj = DataFile.objects.filter(pk=fid, owner=request.user).first()
                        low_cpk_items = _cached_low_cpk_items(
                            df_obj, request.user.pk, full_df, metadata,
                            cpk_threshold, iqr_multiplier, flags['data_only_bin1'])
                    per_file.append(set(filter_test_items(
                        df, metadata, common_params,
                        ignore_no_test_value=flags['ignore_no_test_value'],
                        only_fail_test_item=flags['only_fail_test_item'],
                        only_low_cpk=flags['only_low_cpk'],
                        cpk_threshold=cpk_threshold,
                        fail_items=fail_items,
                        iqr_multiplier=iqr_multiplier,
                        low_cpk_items=low_cpk_items,
                    )))
                common_params = [c for c in common_params if all(c in s for s in per_file)]
            response = {
                'common_params': common_params,
                'file_names': [
                    {'file_id': fid, 'filename': fn} for fid, _, _, fn in loaded
                ],
            }
            first = common_params[0] if common_params else None
            if first:
                range_type = get_param(request, 'range_type', 'S4')
                custom_low = get_param_float(request, 'custom_low')
                custom_high = get_param_float(request, 'custom_high')
                datasets = {}
                all_series = []
                # 分布用 loaded_work（bin1 已收窄）——与筛选后的 common_params 口径一致
                for fid, df, metadata, filename in loaded_work:
                    if first in df.columns:
                        s = get_1d_from(df, first).dropna()
                        s = s[abs(s) < float('inf')]
                        if len(s) > 0:
                            datasets[str(fid)] = {
                                'df': df, 'metadata': metadata, 'series': s,
                                'name': filename[:20], 'file_id': fid,
                            }
                            all_series.append(s)
                if all_series:
                    dist = compute_multi_lot_distribution(
                        datasets, all_series, first, range_type,
                        custom_low, custom_high)
                    if dist:
                        response['range_type'] = range_type
                        response.update(dist)  # param/global stats/bin/lot_data
            return Response(response)

        # With param → per-file distribution (no SITE split; one series/file).
        flags = parse_filter_flags(request)
        cpk_threshold = get_cpk_b_threshold(request.user)
        iqr_multiplier = flags['iqr_multiplier']
        range_type = get_param(request, 'range_type', 'S4')
        custom_low = get_param_float(request, 'custom_low')
        custom_high = get_param_float(request, 'custom_high')

        datasets = {}
        all_series = []
        for fid, df, metadata, filename in loaded:
            if param not in df.columns:
                continue
            fail_items = None
            if flags['only_fail_test_item']:
                # fail 集合基于全量 df（bin1 过滤前）
                fail_items = set(calculate_fail_test_item_statistics(
                    df, metadata, columns=[param]).keys())
            low_cpk_items = None
            if flags['only_low_cpk']:
                df_obj = DataFile.objects.filter(pk=fid, owner=request.user).first()
                low_cpk_items = _cached_low_cpk_items(
                    df_obj, request.user.pk, df, metadata,
                    cpk_threshold, iqr_multiplier, flags['data_only_bin1'])
            work_df = filter_bin1_rows(df, metadata) if flags['data_only_bin1'] else df
            # 防御性重放：参数在该文件被筛掉（非 fail 项/非低 CPK/无测试值）→
            # 跳过该文件（与 histogram compute-path 的 no_valid_params 同口径）
            keep = filter_test_items(
                work_df, metadata, [param],
                ignore_no_test_value=flags['ignore_no_test_value'],
                only_fail_test_item=flags['only_fail_test_item'],
                only_low_cpk=flags['only_low_cpk'],
                cpk_threshold=cpk_threshold,
                fail_items=fail_items,
                iqr_multiplier=iqr_multiplier,
                low_cpk_items=low_cpk_items,
            )
            if not keep:
                continue
            s = get_1d_from(work_df, param).dropna()
            s = s[abs(s) < float('inf')]
            if len(s) > 0:
                datasets[str(fid)] = {
                    'df': work_df, 'metadata': metadata, 'series': s,
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

        # 数据筛选（单文件口径，2026-08-20）：bin1 收窄行；其余开关对
        # param_x/param_y 防御性重放——任一被筛掉（非 fail 项等）→ 400，
        # 前端参数列表刷新后自愈。
        flags = parse_filter_flags(request)
        cpk_threshold = get_cpk_b_threshold(request.user)
        iqr_multiplier = flags['iqr_multiplier']
        fail_items = None
        if flags['only_fail_test_item']:
            fail_items = set(calculate_fail_test_item_statistics(
                df, metadata, columns=[param_x, param_y]).keys())
        low_cpk_items = None
        if flags['only_low_cpk']:
            low_cpk_items = _cached_low_cpk_items(
                datafile, request.user.pk, df, metadata,
                cpk_threshold, iqr_multiplier, flags['data_only_bin1'])
        if flags['data_only_bin1']:
            df = filter_bin1_rows(df, metadata)
        keep = filter_test_items(
            df, metadata, [param_x, param_y],
            ignore_no_test_value=flags['ignore_no_test_value'],
            only_fail_test_item=flags['only_fail_test_item'],
            only_low_cpk=flags['only_low_cpk'],
            cpk_threshold=cpk_threshold,
            fail_items=fail_items,
            iqr_multiplier=iqr_multiplier,
            low_cpk_items=low_cpk_items,
        )
        if len(keep) < 2:
            return Response({
                'error': 'no_valid_params',
                'detail': '参数在当前数据筛选下无效（如非 Fail 测试项），请调整筛选或参数',
            }, status=400)

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
        # serial_col 可选：前端选择器覆盖自动检测（Serial_No > Dut_No > PART_ID）
        serial_col_req = get_param(request, 'serial_col') or None
        if serial_col_req and serial_col_req not in df.columns:
            return Response({'error': 'serial_col_not_found',
                             'detail': f'指定的序列列 {serial_col_req} 不存在'}, status=400)
        serial_col = get_serial_column(df, preferred=serial_col_req)
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
        # data_only_bin1 narrows the rows after param validation, so the
        # per-unit serial series only contains pass-bin units.
        if get_bool_param(request, 'data_only_bin1'):
            df = filter_bin1_rows(df, metadata)

        try:
            result = compute_serial_distribution_data(
                df, metadata, param, range_type, chart_config,
                serial_col=serial_col)
        except TypeError:
            return Response({'error': 'serial_distribution_failed',
                             'detail': '数据列存在重复或格式异常'}, status=400)
        if result is None:
            # 400 而非 200：让前端 axios 错误路径弹出提示，避免序列图静默空白
            return Response({
                'error': 'no_serial_column',
                'detail': '该文件没有序列列（Serial_No / Dut_No / PART_ID），无法绘制序列分布图；可用 serial_col 参数显式指定',
            }, status=400)

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

        # data_only_bin1 narrows the rows before series extraction so the
        # QQ plot (n / outlier stats) only covers pass-bin rows; the
        # param_no_valid_data check below then covers the "all-NaN inside
        # Bin1" case with the existing 400 path.
        if get_bool_param(request, 'data_only_bin1'):
            df = filter_bin1_rows(df, metadata)

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
    def file_correlation_serials(self, request):
        """List the common serial numbers of two files (serial picker data).

        Request body: ``{file1_id, file2_id}``.
        Response: ``{serials: [int, ...], total: int}`` — ascending,
        same ``__serial__`` semantics as the full ``file_correlation``
        computation (交集、数值化), so the picker and the analysis agree.
        """
        payload, err = _load_file_correlation_pair(request)
        if err is not None:
            return Response(err[0], status=err[1])

        serials = list_common_serials(payload['ate_df'], payload['bench_df'])
        return Response({'serials': serials, 'total': len(serials)})

    @action(detail=False, methods=['post'])
    def file_correlation(self, request):
        """Compare two files by serial number and compute per-parameter correlation.

        Request body:
        {
            "file1_id": 123, "file2_id": 456,
            "threshold": 3.0, "diff_rule": "zero",
            "serials": [1, 2, 3],       # 可选：用户勾选的序列（优先）
            "max_serials": 30,          # 兜底：未传 serials 时取前 N
            "ignore_no_limit": true, "ignore_no_data": true
        }

        Response: 模板风格全量数据（每测试项一行的 limit 列 + 每序列
        ATE/Bench/Delta/%Diff 块 + totals 总结），面板直接渲染。
        防呆：无相同测试项 → 400 no_common_params；无相同序列 → limits_only。
        """
        payload, err = _load_file_correlation_pair(request)
        if err is not None:
            return Response(err[0], status=err[1])

        try:
            result = compute_file_correlation(
                payload['ate_df'], payload['metadata_a'],
                payload['bench_df'], payload['metadata_b'],
                _parse_fc_config(request),
                file1_name=payload['file1_name'], file2_name=payload['file2_name'])
        except NoCommonParamsError:
            return Response(
                {'error': 'no_common_params', 'detail': '两个文件没有相同的测试项'},
                status=400)

        return Response(clean_data(result))

    @action(detail=False, methods=['post'])
    def file_correlation_export(self, request):
        """Export the two-file correlation sheet in template layout.

        Layout mirrors Data/TemplateExport/Correlation_Excel/Correlation.xlsx:
        title row + two header rows (Corr Result group, per-serial
        ATE/Bench/Delta/%Diff blocks) + one row per test item in FILE 1
        column order.  Delta/%Diff cells are written as Excel formulas
        (``=K{r}-J{r}`` / ``=L{r}/J{r}``); red fills are decided statically
        from the same computed values as the JSON endpoint, so the two
        outputs always agree.

        Request body: 同 file_correlation（threshold / diff_rule /
        serials 或 max_serials / ignore_no_limit / ignore_no_data）。
        防呆：无相同测试项 → 400 no_common_params；无相同序列 → limits-only
        （只导 limit 列，无序列数据列）。
        """
        payload, err = _load_file_correlation_pair(request)
        if err is not None:
            return Response(err[0], status=err[1])

        try:
            result = compute_file_correlation(
                payload['ate_df'], payload['metadata_a'],
                payload['bench_df'], payload['metadata_b'],
                _parse_fc_config(request),
                file1_name=payload['file1_name'], file2_name=payload['file2_name'])
        except NoCommonParamsError:
            return Response(
                {'error': 'no_common_params', 'detail': '两个文件没有相同的测试项'},
                status=400)

        # 延迟导入：避免 analysis → export 顶层耦合（export 会 import
        # analysis.services.statistics，已加载无循环风险；但保持轻量）。
        import excelize
        from apps.export.excel_builders import build_file_correlation_workbook
        from apps.export.excelize_helpers import save_excelize
        from apps.common.export_naming import (
            base_export_context, render_export_filename,
        )

        f = excelize.new_file()
        build_file_correlation_workbook(f, result)
        buffer = save_excelize(f)

        fname = render_export_filename(
            request.user, 'file_correlation', 'xlsx',
            {**base_export_context(request.user),
             'file1': payload['file1_name'].rsplit('.', 1)[0],
             'file2': payload['file2_name'].rsplit('.', 1)[0]},
        )
        return FileResponse(
            io.BytesIO(buffer), as_attachment=True, filename=fname,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def _load_file_correlation_pair(request):
    """Load and align two files for file-correlation analysis.

    Returns ``(payload, err)`` where ``err`` is ``None`` on success or a
    ``(response_dict, http_status)`` tuple the caller returns as-is.
    ``payload`` keys:
        ate_df / bench_df   — DataFrames carrying the ``__serial__`` column
        metadata_a / metadata_b — parser metadata (mins/maxs/units)
        file1_name/file2_name — DataFile.filename for export naming
    """
    file1_id = request.data.get('file1_id')
    file2_id = request.data.get('file2_id')
    if not file1_id or not file2_id:
        return None, ({'error': 'need_two_files'}, 400)

    dfs = {}
    names = {}
    metas = {}
    for fid, label in [(file1_id, 'ATE'), (file2_id, 'Bench')]:
        df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
        df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk, df_obj)
        if df is None:
            continue
        serial_col = get_serial_column(df)
        if serial_col:
            # get_cached_parsed_file 返回 LRU 缓存对象（文档明示只读），
            # 必须 copy 后再加辅助列，否则污染缓存影响后续所有消费者
            df = df.copy()
            df['__serial__'] = pd.to_numeric(df[serial_col], errors='coerce')
        dfs[label] = df
        names[label] = df_obj.filename
        metas[label] = metadata or {}

    if len(dfs) < 2:
        return None, ({'error': 'parse_failed'}, 400)

    ate_df = dfs['ATE']
    bench_df = dfs['Bench']
    ate_ser = ate_df['__serial__'] if '__serial__' in ate_df.columns else None
    bench_ser = bench_df['__serial__'] if '__serial__' in bench_df.columns else None
    if ate_ser is None or bench_ser is None:
        return None, ({'error': 'no_serial_column'}, 400)

    return {
        'ate_df': ate_df, 'bench_df': bench_df,
        'metadata_a': metas['ATE'], 'metadata_b': metas['Bench'],
        'file1_name': names['ATE'], 'file2_name': names['Bench'],
    }, None


def _parse_fc_config(request) -> FileCorrelationConfig:
    """Parse the file-correlation options from a request body.

    All options default to the panel defaults (threshold 3.0, rule 'zero',
    serials 未指定 → max_serials 30 兜底, ignore_no_limit / ignore_no_data
    checked) so a minimal body keeps behaving like the old
    ``{file1_id, file2_id}`` request.
    """
    threshold = get_param_float(request, 'threshold', 3.0)
    if threshold is None or threshold < 0:
        threshold = 3.0
    diff_rule = get_param(request, 'diff_rule', 'zero')
    if diff_rule not in ('zero', 'wider'):
        diff_rule = 'zero'
    max_serials = get_param_float(request, 'max_serials', 30)
    try:
        max_serials = max(1, int(max_serials))
    except (TypeError, ValueError):
        max_serials = 30

    # 显式序列选择（用户勾选）：优先于 max_serials 兜底；非法值过滤。
    serials = None
    raw_serials = request.data.get('serials')
    if raw_serials is not None:
        valid = []
        for v in raw_serials if isinstance(raw_serials, (list, tuple)) else [raw_serials]:
            try:
                valid.append(int(v))
            except (TypeError, ValueError):
                continue
        serials = valid

    def _bool_param(key: str, default: bool) -> bool:
        raw = get_param(request, key, None)
        if raw is None:
            return default
        return str(raw).lower() in ('true', '1', 'yes')

    return FileCorrelationConfig(
        threshold=float(threshold),
        diff_rule=diff_rule,
        max_serials=max_serials,
        serials=serials,
        ignore_no_limit=_bool_param('ignore_no_limit', True),
        ignore_no_data=_bool_param('ignore_no_data', True),
    )
