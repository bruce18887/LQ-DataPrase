import io
import logging
import tempfile

from django.http import FileResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
import excelize

from apps.common.errors import error_response
from apps.common.file_loading import load_user_file, FileLoadError
from apps.common.export_naming import base_export_context, render_export_filename
from apps.analysis.services.statistics import filter_bin1_rows
from .filters import apply_export_filters
from .excelize_helpers import save_excelize
from .excel_builders import (
    build_sigma_limit_sheet,
)
from .user_prefs import get_export_dpi
from apps.common.user_settings import get_cpk_thresholds
from .export_csv import export_to_csv_file
from apps.dashboard.services import compute_dashboard_summary
from apps.analysis.services.statistics import compute_uph
from django.utils import timezone
from .html_report import build_single_html_report
# HTML 报告样式已移到 html_report/styles.py；此处 re-export 保持
# `apps.export.views.ATE_REPORT_CSS` 的历史导入路径（test_export_fonts 依赖）。
from .html_report.styles import REPORT_CSS as ATE_REPORT_CSS  # noqa: F401

# σ 档位合法区间：前端只提供 3/4/6，给个宽裕的上下界拦住 0 / 负数 / 99
MIN_SIGMA_LEVEL = 1
MAX_SIGMA_LEVEL = 10
DEFAULT_SIGMA_LEVEL = 3

logger = logging.getLogger(__name__)

# to_csv 的临时文件前缀：便于测试与运维识别残留（正常路径由 OS 在句柄关闭时删除）
CSV_TEMP_PREFIX = 'lqdp_export_'


def parse_sigma_level(raw):
    """请求里的 σ 档位 → ``int``；缺失/非法 → ``None``（调用方据此返回 400）。

    缺陷 #7：旧代码 ``request.data.get('sigma', 3)`` 不做类型转换，表单编码
    把 ``6`` 变成 ``'6'``，下游 ``mean_val - sigma_level * std_val`` 抛
    ``TypeError: can only concatenate str`` → 500。bool 是 int 的子类，但
    ``True`` 不是合法档位，显式排除；``3.5`` / ``'abc'`` / ``[3]`` 同样非法。
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        as_float = float(raw)
    except (TypeError, ValueError):
        return None
    if not as_float.is_integer():
        return None
    level = int(as_float)
    return level if MIN_SIGMA_LEVEL <= level <= MAX_SIGMA_LEVEL else None


class ExportViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    # ── to_csv ──────────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def to_csv(self, request):
        file_id = request.data.get('file_id')

        try:
            df, datafile, metadata = load_user_file(request, file_id)
        except FileLoadError as e:
            return error_response(e.error_code)

        # 与表格一致：passfail/site/sort/filter_model 全量应用
        # （此前走 bin==1 语义，与表格 detect_fail_data 不一致，一并对齐）。
        export_df = apply_export_filters(df, metadata, request.data)

        fname = render_export_filename(
            request.user, 'to_csv', 'csv',
            {**base_export_context(request.user),
             'filename': datafile.filename.rsplit('.', 1)[0]},
        )
        # 直下改临时文件：旧实现 to_csv().encode() + BytesIO 会让整份 CSV
        # 以 str / bytes / BytesIO 三份同时驻留。文件名模板先渲染，避免它抛错
        # 时临时文件已创建却没人清理。
        #
        # Windows 事实：TemporaryFile 用 O_TEMPORARY 打开，句柄一关就由 OS
        # 删除（进程崩溃同样回收），所以既没有「先关句柄再 unlink」的竞态，
        # 也不需要记录/清理路径；FileResponse 把 close 登记为 resource closer。
        handle = tempfile.TemporaryFile(prefix=CSV_TEMP_PREFIX, suffix='.csv')
        try:
            export_to_csv_file(export_df, metadata, handle)
            handle.seek(0)
            return FileResponse(handle, as_attachment=True, filename=fname,
                                content_type='text/csv')
        except BaseException:
            # 关闭失败只记 warning，绝不让它盖住原始异常。
            try:
                handle.close()
            except Exception:
                logger.warning('临时 CSV 句柄关闭失败', exc_info=True)
            raise

    # ── sigma_limit ─────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def sigma_limit(self, request):
        file_id = request.data.get('file_id')
        # 缺陷 #7：必须转 int 并校验范围——非法值返回 400，而不是让下游
        # 算 sigma 区间时抛 TypeError 变成 500
        sigma_level = parse_sigma_level(request.data.get('sigma', DEFAULT_SIGMA_LEVEL))
        if sigma_level is None:
            return error_response(
                'invalid_sigma',
                f'sigma 必须是 {MIN_SIGMA_LEVEL}~{MAX_SIGMA_LEVEL} 的整数')
        only_valid = request.data.get('only_valid_limits', False)

        try:
            df, datafile, metadata = load_user_file(request, file_id)
        except FileLoadError as e:
            return error_response(e.error_code)

        # data_only_bin1: export only pass-bin rows (chart-config switch)
        if request.data.get('data_only_bin1', False):
            df = filter_bin1_rows(df, metadata)

        f = excelize.new_file()
        build_sigma_limit_sheet(f, df, metadata, sigma_level, only_valid)
        buffer = save_excelize(f)

        fname = render_export_filename(
            request.user, 'sigma_limit', 'xlsx',
            {**base_export_context(request.user),
             'filename': datafile.filename.rsplit('.', 1)[0],
             'sigma': sigma_level},
        )
        return FileResponse(io.BytesIO(buffer), as_attachment=True,
                            filename=fname,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── html_report ─────────────────────────────────────────────────

    @action(detail=False, methods=['post'])
    def html_report(self, request):
        file_id = request.data.get('file_id')
        try:
            df, datafile, metadata = load_user_file(request, file_id)
        except FileLoadError as e:
            return error_response(e.error_code)

        # data_only_bin1：与 sigma_limit / batch_charts 分支同口径（缺陷 #8）。
        # 此前 HTML 报告不应用该开关，良率与 xlsx 图表对不上。
        if request.data.get('data_only_bin1', False):
            df = filter_bin1_rows(df, metadata)

        # 报表 = 仪表板单文件 Tab 的静态快照：复用同一份 compute_dashboard_summary
        # （与 /summary/ 同源，杜绝数字漂移），并内联 base64 图表成自包含单文件。
        fmt = datafile.format_type
        thresholds = get_cpk_thresholds(request.user)
        payload = compute_dashboard_summary(df, datafile, fmt, metadata, thresholds=thresholds)
        uph = compute_uph(df, metadata)
        html = build_single_html_report(
            payload, metadata, uph,
            dpi=get_export_dpi(request.user),
            generated_at=timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S'),
        )
        # FileResponse (not Response + hand-written header): Django wsgi response
        # headers are latin-1 only — a hand-written Content-Disposition with a
        # Chinese source filename raises UnicodeEncodeError. FileResponse emits
        # RFC 5987 filename*=UTF-8''... encoding automatically.
        fname = render_export_filename(
            request.user, 'html_report', 'html',
            {**base_export_context(request.user),
             'filename': datafile.filename.rsplit('.', 1)[0]},
        )
        return FileResponse(io.BytesIO(html.encode('utf-8')), as_attachment=True,
                            filename=fname, content_type='text/html; charset=utf-8')
