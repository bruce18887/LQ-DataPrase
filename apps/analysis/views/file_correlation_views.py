"""两文件序列相关性（file correlation）端点。

以 mixin 形式挂进 ``AnalysisViewSet`` 而不是独立 ViewSet：DRF 的
``get_extra_actions()`` 用 ``inspect.getmembers`` 沿 MRO 收集 ``@action``，
所以路由前缀（``/api/v1/analysis/file_correlation*/``）、OpenAPI 分组与
权限声明全部不变，拆分的唯一动机是 ``analysis_views.py`` 的 600 行上限。
"""

import io

import pandas as pd
from django.http import FileResponse
from django.shortcuts import get_object_or_404

from rest_framework.decorators import action
from rest_framework.response import Response

from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.analysis.services.statistics import get_serial_column
from apps.analysis.services.file_correlation import (
    FileCorrelationConfig,
    compute_file_correlation,
    list_common_serials,
    NoCommonParamsError,
)
from apps.common.params import get_param, get_param_float

from ._helpers import clean_data


class FileCorrelationActions:
    """``AnalysisViewSet`` 的三个 file_correlation 动作（无 self 状态依赖）。"""

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
