"""单文件分析中带视图层过滤链的四个端点（histogram / wafer_map / multi_lot /
correlation）。

四个「解析 → 校验 → 调 service → 序列化」的薄壳动作（serial_distribution / cpk /
qqplot / uph）在 ``param_actions`` 里，两文件序列相关性（file_correlation*）三端点
在 ``file_correlation_views`` 里，均以 mixin 形式合入本 ViewSet（600 行上限）——
路由、权限声明与 OpenAPI 分组均不变。
"""

import pandas as pd

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.datafiles.models import DataFile
from apps.analysis.services.statistics import (
    get_site_column,
    get_serial_candidates,
    get_coord_columns,
    get_columns_with_limits,
    resolve_spec_limits,
    get_1d_from,
    filter_finite,
    calculate_fail_test_item_statistics,
    filter_bin1_rows,
    filter_test_items,
)
from apps.analysis.services.data_services import (
    compute_histogram_stats,
    compute_wafer_map_data,
    compute_multi_lot_distribution,
    compute_common_params,
    compute_correlation_scatter,
)
from apps.datafiles.services import get_cached_parsed_file
from apps.common.params import get_param, get_param_float, get_param_list
from apps.common.errors import error_response

from .file_correlation_views import FileCorrelationActions
from .param_actions import ParamStatActions
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
from apps.common.user_settings import get_cpk_thresholds

# 兼容既有调用名（低 CPK 缓存已上移 _helpers，多视图共享）
_cached_low_cpk_items = cached_low_cpk_items


class AnalysisViewSet(FileCorrelationActions, ParamStatActions,
                      viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get', 'post'])
    def histogram(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return error_response(err)

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
        # 一次读账号阈值：B 阈 = 「仅低 CPK 项」判定线，三值 = cpk_level/cpk_color 分级线
        cpk_thresholds = get_cpk_thresholds(request.user)
        cpk_threshold = cpk_thresholds.cpk_b
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
            # dtype 白名单 ('int64','float64') 漏掉 int32/float32/UInt8，且
            # pandas 3.0 下字符串列是 str dtype 而不是 object（== object 恒 False）。
            # 改用 is_numeric_dtype 后 bool（真实数据的 Dut_Pass）**会被纳入**，
            # 所以必须显式排除 —— pass/fail 标志不是可测量的参数。
            numeric_cols = [c for c in df.columns
                           if pd.api.types.is_numeric_dtype(df[c])
                           and not pd.api.types.is_bool_dtype(df[c])
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
        # CL 模式的自定义区间必须有效：下限 > 上限会产出退化 bin 网格
        if range_type == 'CL' and custom_low is not None and custom_high is not None \
                and custom_low > custom_high:
            return error_response('invalid_custom_limits', '自定义下限不能大于上限')

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
            return error_response(
                'no_valid_params',
                '请求的参数均不在该文件中，请重新选择文件或参数',
                requested=params, missing=missing_params)
        params = valid_params
        skipped_params = []
        for param in params:
            # 计算路径不吞异常：任何意外内部错误直接 500 暴露（param 不在 df
            # 的情况已在上面作为 400 处理）
            result = compute_histogram_stats(
                df, metadata, param, site_col,
                range_type=range_type, custom_low=custom_low, custom_high=custom_high,
                iqr_multiplier=iqr_multiplier, cpk_thresholds=cpk_thresholds)
            if result is not None:
                results[param] = result
            else:
                # str 列 / 筛选后全 NaN：此前 200 但缺 key，前端「图表区域空白
                # 但无任何提示」——部分无效随响应带 skipped_params 提示，全部
                # 无效对齐 boxplot 的 400 no_valid_params
                skipped_params.append(param)
        if not results:
            return error_response(
                'no_valid_params', '请求的参数均无有效数值数据',
                requested=params, skipped=skipped_params)

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'format_type': datafile.format_type,
            'results': results,
            'skipped_params': skipped_params,
        }))

    @action(detail=False, methods=['get', 'post'])
    def wafer_map(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return error_response(err)

        x_col, y_col = get_coord_columns(df)
        if not x_col or not y_col:
            # 400 而非 200：让前端 axios 错误路径弹出提示，避免晶圆图静默空白
            return error_response(
                'no_coord_columns',
                '该文件没有坐标列（X_COORD/Y_COORD），无法绘制晶圆图')

        param = get_param(request, 'param')
        # 与 zonal_yield 同源同守卫（同一份 compute_wafer_fail_data）：stale
        # 参数不得静默按「全局判定」返回一张着色完全错误的晶圆图——zonal 是
        # 400 param_not_found，这里曾是 200 + 全局判定着色（R3① 守卫不一致）。
        # 空 param 保留「全局判定」语义。
        if param and param not in df.columns:
            return error_response('param_not_found', f'参数 {param!r} 不在该文件中')
        color_by = get_param(request, 'color_by', 'result')

        wm = compute_wafer_map_data(df, metadata, param, color_by, x_col, y_col)

        # 参数值着色的归一口径由前端做（有真规格限按 LSL→USL、否则按数据范围），
        # 这里只下发原始规格限：'Min'/'Max' 占位等「无规格限」语义经
        # resolve_spec_limits 统一为 None（JSON null），前端不用再判占位符。
        spec_low, spec_high = resolve_spec_limits(metadata, param) if param else (None, None)

        return Response(clean_data({
            'file_id': datafile.id,
            'x_col': x_col,
            'y_col': y_col,
            'points': wm['points'],
            'stats': wm['stats'],
            'wafer': wm['wafer'],
            'spec_low': spec_low,
            'spec_high': spec_high,
        }))

    @action(detail=False, methods=['get', 'post'])
    def multi_lot(self, request):
        file_ids = get_param_list(request, 'file_ids')
        param = get_param(request, 'param')
        if len(file_ids) < 2:
            return error_response('need_at_least_2_files')

        # Load each selected file once (cached parse + DB row for filename).
        # 一次 in_bulk 取回全部行：逐 fid 查询在 8 个文件时就是 8 次 SELECT，
        # 而下游低 CPK 缓存还要用同一批 DataFile 行（mtime+size 作缓存键）。
        # owner=request.user 是权限防线，不是冗余 —— 别人的 file_id 混进请求必须查不到。
        owned = DataFile.objects.filter(
            pk__in=file_ids, owner=request.user).in_bulk()
        loaded = []  # (file_id, df, metadata, DataFile)
        for fid in file_ids:
            df_obj = owned.get(int(fid))
            if df_obj is None:
                continue
            df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk, df_obj)
            if df is None:
                continue
            loaded.append((int(fid), df, metadata, df_obj))

        if len(loaded) < 2:
            return error_response('need_at_least_2_files')

        # No param → lightweight call: return the common test items + file names
        # so the front-end can populate the param selector before drawing.
        # 合并请求优化：文件已在本请求内加载（冷缓存 0.46s/个），顺带返回
        # 首个公共参数的分布——前端免去串行第二次请求再遍历一轮文件加载
        # （冷缓存 ~3.6s → ~2.2s）。
        if not param:
            flags = parse_filter_flags(request)
            cpk_thresholds = get_cpk_thresholds(request.user)
            cpk_threshold = cpk_thresholds.cpk_b
            iqr_multiplier = flags['iqr_multiplier']
            # data_only_bin1 先收窄行再派生基础候选列表（与单文件 fast-path 口径一致）
            loaded_work = loaded
            if flags['data_only_bin1']:
                loaded_work = [
                    (fid, filter_bin1_rows(df, metadata), metadata, datafile)
                    for fid, df, metadata, datafile in loaded
                ]
            common_params = compute_common_params(loaded_work, flags['ignore_no_limit'])
            # 其余筛选（忽略无测试值/仅Fail项/仅低CPK）：对交集按每个文件过滤后
            # 再取交集——fail 集合必须基于全量 df 预计算（bin1 过滤前，否则
            # fail 恒空）；低 CPK 走共享缓存（key 含 mtime+size 自动失效）。
            if flags['ignore_no_test_value'] or flags['only_fail_test_item'] or flags['only_low_cpk']:
                per_file = []
                for (_fid, df, metadata, _datafile), (_fid2, full_df, _, full_datafile) in zip(loaded_work, loaded):
                    fail_items = None
                    if flags['only_fail_test_item']:
                        fail_items = set(calculate_fail_test_item_statistics(full_df, metadata).keys())
                    low_cpk_items = None
                    if flags['only_low_cpk']:
                        # datafile 行随 loaded 一起带回来，不再第二轮按 fid 重查
                        low_cpk_items = _cached_low_cpk_items(
                            full_datafile, request.user.pk, full_df, metadata,
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
                    {'file_id': fid, 'filename': datafile.filename}
                    for fid, _, _, datafile in loaded
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
                for fid, df, metadata, datafile in loaded_work:
                    if first in df.columns:
                        # filter_finite 而非 ``abs(s) < inf``：实测真实 CTA8290D
                        # 文件的 Start_T 是 pandas 3.0 str dtype，``abs()`` 直接抛
                        # ``TypeError: bad operand type for abs(): 'str'``——
                        # 一个非数值列就能把整个多文件请求打断，而正确行为是
                        # 把它 coerce 成空集后跳过。
                        s = filter_finite(get_1d_from(df, first))
                        if len(s) > 0:
                            datasets[str(fid)] = {
                                'df': df, 'metadata': metadata, 'series': s,
                                'name': datafile.filename[:20], 'file_id': fid,
                            }
                            all_series.append(s)
                if all_series:
                    include_kde = get_bool_param(request, 'include_kde')
                    dist = compute_multi_lot_distribution(
                        datasets, all_series, first, range_type,
                        custom_low, custom_high, include_kde=include_kde,
                        cpk_thresholds=cpk_thresholds)
                    if dist:
                        response['range_type'] = range_type
                        response.update(dist)  # param/global stats/bin/lot_data
            # 与带 param 分支（clean_data(result)）同一序列化防线：任何 service
            # 改动引入 NaN/Inf 时该分支不再直接吐非法 JSON（DRF strict JSON
            # 下表现为 500）
            return Response(clean_data(response))

        # With param → per-file distribution (no SITE split; one series/file).
        flags = parse_filter_flags(request)
        cpk_thresholds = get_cpk_thresholds(request.user)
        cpk_threshold = cpk_thresholds.cpk_b
        iqr_multiplier = flags['iqr_multiplier']
        range_type = get_param(request, 'range_type', 'S4')
        custom_low = get_param_float(request, 'custom_low')
        custom_high = get_param_float(request, 'custom_high')

        datasets = {}
        all_series = []
        for fid, df, metadata, datafile in loaded:
            if param not in df.columns:
                continue
            fail_items = None
            if flags['only_fail_test_item']:
                # fail 集合基于全量 df（bin1 过滤前）
                fail_items = set(calculate_fail_test_item_statistics(
                    df, metadata, columns=[param]).keys())
            low_cpk_items = None
            if flags['only_low_cpk']:
                low_cpk_items = _cached_low_cpk_items(
                    datafile, request.user.pk, df, metadata,
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
            s = filter_finite(get_1d_from(work_df, param))
            if len(s) > 0:
                datasets[str(fid)] = {
                    'df': work_df, 'metadata': metadata, 'series': s,
                    'name': datafile.filename[:20], 'file_id': fid,
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

        include_kde = get_bool_param(request, 'include_kde')
        result = compute_multi_lot_distribution(
            datasets, all_series, param,
            range_type=range_type, custom_low=custom_low, custom_high=custom_high,
            include_kde=include_kde,
            cpk_thresholds=cpk_thresholds,
        )

        return Response(clean_data(result))

    @action(detail=False, methods=['get', 'post'])
    def correlation(self, request):
        """Return raw data for two selected parameters, organized by Site for scatter plot."""
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return error_response(err)

        param_x = get_param(request, 'param_x')
        param_y = get_param(request, 'param_y')
        if not param_x or not param_y:
            return error_response('param_x_and_param_y_required')

        if param_x not in df.columns or param_y not in df.columns:
            return error_response('param_not_found')

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
        # 非数值列（str/bool/全 NaN）与兄弟端点（boxplot/correlation_matrix）同形
        # 守卫 → 400 no_valid_params：此前服务层 `.astype(float)` 对 str 列直接
        # ValueError → 500，同类入参一个 400 一个 500 的守卫不一致（R3①）。
        # x==y 时 _sanitize 不去重，仍返回两元素，不会误伤同参数自相关。
        if len(_sanitize_numeric_params(df, [param_x, param_y])) < 2:
            return error_response(
                'no_valid_params', '请求的参数不是有效数值列，请重新选择参数',
                requested=[param_x, param_y])
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
            return error_response(
                'no_valid_params',
                '参数在当前数据筛选下无效（如非 Fail 测试项），请调整筛选或参数')

        # iqr_multiplier 已在上方 flags 里读出（此前只喂给 low_cpk_items），
        # 现在一并贯穿到散点两轴的异常值判定，与直方图同口径。
        result = compute_correlation_scatter(
            df, param_x, param_y, metadata, iqr_multiplier=iqr_multiplier)

        return Response(clean_data(result))
