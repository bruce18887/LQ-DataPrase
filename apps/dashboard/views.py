import logging
import os

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.datafiles.models import DataFile
from apps.datafiles.services import get_cached_parsed_file
from apps.datafiles.utils import resolve_file_path
from apps.common.user_settings import get_cpk_thresholds

# 计算逻辑已抽到 services.py（供 HTML 报告共用，单一数据源）。这里 re-import
# 既有名字，保持 `apps.dashboard.views.compute_*` 的历史导入路径不破。
from .services import (  # noqa: F401
    compute_bin_site_table,
    compute_test_item_overview,
    _derive_param_stats,
    compute_quality_alerts,
    compute_dashboard_summary,
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

            if not datafile:
                return Response({'error': 'no_data'})

            file_path = resolve_file_path(datafile.file_path)
            if not os.path.exists(file_path):
                return Response({'error': 'file_not_found'})

            df, metadata, fmt = get_cached_parsed_file(datafile.id, request.user.pk, datafile)
            if df is None:
                return Response({'error': 'parse_failed'})

            cpk_thresholds = get_cpk_thresholds(request.user)
            return Response(compute_dashboard_summary(
                df, datafile, fmt, metadata, thresholds=cpk_thresholds))
        except Http404:
            # get_object_or_404 的 404 语义不能被兜底吞掉
            raise
        except Exception as e:
            logger.exception(f"DashboardSummaryView error: {e}")
            body = {'error': 'internal_error'}
            if settings.DEBUG:
                body['detail'] = str(e)
            return Response(body, status=500)
