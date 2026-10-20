import logging
import os

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.analysis.views._helpers import clean_data
from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.datafiles.utils import resolve_file_path
from apps.common.errors import error_response
from apps.common.user_settings import get_cpk_thresholds

# 计算逻辑已抽到 services.py（供 HTML 报告共用，单一数据源）。这里 re-import
# 既有名字，保持 `apps.dashboard.views.compute_*` 的历史导入路径不破。
from .services import (  # noqa: F401
    compute_bin_site_table,
    compute_test_item_overview,
    _derive_param_stats,
    compute_quality_alerts,
    compute_dashboard_summary,
    get_dashboard_summary,
)

logger = logging.getLogger(__name__)


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            file_id = request.query_params.get('file_id')
            if not file_id:
                datafile = DataFile.objects.filter(
                    owner=request.user, status='ready'
                ).order_by('-created_at').first()
            else:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)

            # 这三处刻意保持 **HTTP 200**（只统一响应体形状）：DashboardPage 是在
            # then 分支里按 code 判「部分失败」渲染已有数据的，改成 4xx 会把它推进
            # catch 路径（整页错误态），属于行为变更，不在 P1-5 形状统一范围内。
            if not datafile:
                return error_response('no_data', status=200)

            file_path = resolve_file_path(datafile.file_path)
            if not os.path.exists(file_path):
                return error_response('file_not_found', status=200)

            df, metadata, fmt = get_cached_parsed_file(datafile.id, request.user.pk, datafile)
            if df is None:
                return error_response('parse_failed', status=200)

            cpk_thresholds = get_cpk_thresholds(request.user)
            # 走缓存层：同一文件 + 同一阈值 + 未变更的 mtime 时直接返回上次结果，
            # 避免切 Tab 重复付出 ~600ms 的整表计算。
            # clean_data 是出口兜底（与 analysis 侧 23 个端点同写法）：非有限值一旦
            # 漏进 payload，DRF 严格渲染器是在 handler 层抛 ValueError 的（视图自己的
            # except 接不到），整页 500；过一遍则退化成前端本就按 N/A 渲染的 null。
            return Response(clean_data(get_dashboard_summary(
                datafile, df, fmt, metadata, cpk_thresholds)))
        except Http404:
            # get_object_or_404 的 404 语义不能被兜底吞掉
            raise
        except Exception as e:
            logger.exception(f"DashboardSummaryView error: {e}")
            # 只有 DEBUG 模式才外泄异常文本；统一形状下 detail 键恒在，
            # 非 DEBUG 时为 null（test_dashboard_error_detail 守这条）。
            return error_response(
                'internal_error', str(e) if settings.DEBUG else None, 500)
