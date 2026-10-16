"""单文件参数统计端点（serial_distribution / qqplot / uph / cpk）。

以 mixin 形式挂进 ``AnalysisViewSet`` 而不是独立 ViewSet：DRF 的
``get_extra_actions()`` 沿 MRO 收集 ``@action``，所以路由前缀
（``/api/v1/analysis/serial_distribution/`` 等）、OpenAPI 分组与权限声明全部不变。
拆分的唯一动机是 ``analysis_views.py`` 的 600 行上限（`.claude/CLAUDE.md:62`）。

2026-10-16 重构（架构评审 P1-1）：这四个动作都是「解析参数 → 校验 → 调 service → 序列化」的
薄壳，业务逻辑本来就在 service 里，所以整段搬移零风险。留下来的
``analysis_views.py`` 只留带有视图层过滤链的四个动作（histogram / wafer_map /
multi_lot / correlation）。

命名说明：``ParamStatActions`` 指「单个文件上的参数统计」。跨文件的
``file_correlation*`` 另在 ``file_correlation_views.FileCorrelationActions``。
"""

import json

import pandas as pd

from rest_framework.decorators import action
from rest_framework.response import Response

from apps.analysis.services.statistics import (
    get_serial_column,
    get_site_column,
    get_1d_from,
    filter_bin1_rows,
    compute_qqplot,
    compute_uph,
    get_columns_with_limits,
)
from apps.analysis.services.data_services import (
    compute_serial_distribution_data,
    compute_cpk_table_data,
)
from apps.common.params import get_param, get_param_float, get_param_list
from apps.common.user_settings import get_cpk_thresholds
from apps.common.errors import error_response

from ._helpers import (
    clean_data,
    _filter_blank_params,
    _load_df_from_request,
    get_bool_param,
)


class ParamStatActions:
    """``AnalysisViewSet`` 的四个单文件参数统计动作（无 self 状态依赖）。"""

    @action(detail=False, methods=['get', 'post'])
    def serial_distribution(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return error_response(err)

        param = get_param(request, 'param')
        if not param:
            return error_response('param_required')
        if param not in df.columns:
            return error_response('param_not_found')
        # Reject serial/site columns as data param — they are grouping keys, not values
        # serial_col 可选：前端选择器覆盖自动检测（Serial_No > Dut_No > PART_ID）
        serial_col_req = get_param(request, 'serial_col') or None
        if serial_col_req and serial_col_req not in df.columns:
            return error_response('serial_col_not_found',
                                  f'指定的序列列 {serial_col_req} 不存在')
        serial_col = get_serial_column(df, preferred=serial_col_req)
        site_col = get_site_column(df)
        if param == serial_col or param == site_col:
            return error_response('param_is_metadata',
                                  f'{param} 是分组列，不能作为数据参数')
        # Validate param has numeric data
        col = get_1d_from(df, param)
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        if col.dropna().empty:
            return error_response('param_no_valid_data')

        chart_config_raw = get_param(request, 'chart_config', '[]')
        # 客户端可控输入：非法 JSON（GET ?chart_config=limit）或非数组类型
        # （{"limit":true} / 123）曾直接 json.loads 抛异常 → 500
        try:
            chart_config = chart_config_raw if isinstance(chart_config_raw, list) else json.loads(chart_config_raw)
        except (TypeError, ValueError):
            chart_config = None
        if not isinstance(chart_config, list):
            return error_response(
                'invalid_chart_config',
                'chart_config 必须是 JSON 数组（如 ["limit","s3","s6"]）')
        range_type = get_param(request, 'range_type', 'RDL')
        # data_only_bin1 narrows the rows after param validation, so the
        # per-unit serial series only contains pass-bin units.
        if get_bool_param(request, 'data_only_bin1'):
            df = filter_bin1_rows(df, metadata)

        try:
            result = compute_serial_distribution_data(
                df, metadata, param, range_type, chart_config,
                serial_col=serial_col,
                # 本端点此前连 parse_filter_flags 都没调，敏感度写死 1.5
                iqr_multiplier=get_param_float(request, 'iqr_multiplier', 1.5),
                # CL 语义三端点统一为「用户自定义限」（与 histogram 同口径）
                custom_low=get_param_float(request, 'custom_low'),
                custom_high=get_param_float(request, 'custom_high'))
        except TypeError:
            return error_response('serial_distribution_failed', '数据列存在重复或格式异常')
        if result is None:
            # 400 而非 200：让前端 axios 错误路径弹出提示，避免序列图静默空白
            return error_response(
                'no_serial_column',
                '该文件没有序列列（Serial_No / Dut_No / PART_ID），无法绘制序列分布图；可用 serial_col 参数显式指定')

        return Response(clean_data(result))

    @action(detail=False, methods=['get', 'post'])
    def cpk(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return error_response(err)

        params = get_param_list(request, 'params')
        if not params:
            params = get_columns_with_limits(df, metadata)

        # 与 histogram 同形守卫：切文件后的 stale selectedParam 打到本端点曾是
        # `df[param]` KeyError → 500（histogram 加 param_not_found 守卫的注释里
        # 记载过同一场景）；CTA8280F 尾逗号空列名同样先滤掉。
        params = _filter_blank_params(params)
        valid_params = [p for p in params if p in df.columns]
        if params and not valid_params:
            return error_response(
                'param_not_found',
                '请求的参数均不在该文件中，请重新选择文件或参数',
                requested=params,
                missing=[p for p in params if p not in df.columns])
        params = valid_params

        result = compute_cpk_table_data(
            df, metadata, params,
            cpk_thresholds=get_cpk_thresholds(request.user))

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
            return error_response(err)

        param = get_param(request, 'param')
        if not param:
            return error_response('param_required')
        if param not in df.columns:
            return error_response('param_not_found', f'参数 {param!r} 不在该文件中')

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
            return error_response('param_no_valid_data')
        try:
            result = compute_qqplot(
                data_series, metadata, param,
                iqr_multiplier=get_param_float(request, 'iqr_multiplier', 1.5))
        except (TypeError, ValueError) as e:
            return error_response('qqplot_failed', str(e))

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
            return error_response(err)

        test_time_col = get_param(request, 'test_time_col')
        # 不在视图层做 float()：服务层 compute_uph 对无效的 manual_test_time_sec
        # 有 try/except 降级告警（"手动测试时间无效，已忽略"），视图层裸转换
        # 会让 {"manual_test_time_sec": "abc"} 在容错生效前就 500（防御写错了层）
        manual_test_time_sec = get_param(request, 'manual_test_time_sec')
        result = compute_uph(df, metadata, test_time_col=test_time_col,
                             manual_test_time_sec=manual_test_time_sec)

        return Response(clean_data(result))
