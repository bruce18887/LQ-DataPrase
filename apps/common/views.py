"""System-level endpoints — storage path configuration.

``GET/PUT /api/v1/system/paths/`` exposes the effective storage paths
(db file, data dir, media dir, temp dir) and lets administrators reconfigure
them via ``system_config.json``. Path changes take effect only after a
backend restart (the DB connection is fixed at settings-import time), which
the response signals via ``restart_required``.
"""

import os
import tempfile
from pathlib import Path

from django.conf import settings
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import FeaturePermission
from apps.common import system_config


class MetricsView(APIView):
    """`GET /api/v1/metrics/` —— 运维可见性（方案 §9-4）。

    **无条件管理员**：不像 `SystemPathsView` 那样按 `SYSTEM_PATHS_VISIBLE_TO_ALL` 放宽。
    理由是这个载荷会说出接口耗时、路径形态、作业量与内存占用 —— 桌面单机形态下这些信息
    对普通账号也没有收益，只有泄漏面。闸门仍然在 API 上（`FeaturePermission` +
    `required_feature='system_config'`，复用现有权限键，不新造一个只有它用的 feature）。

    端点自身不进延迟采样池（`apps/common/metrics.is_worth_recording`），
    否则运维页开久了最慢路径 Top-1 永远是它自己。
    """

    permission_classes = [IsAuthenticated, FeaturePermission]
    required_feature = 'system_config'

    def get(self, request):
        from apps.common import metrics
        return Response(metrics.snapshot())


def _validate_or_error(value: str | None) -> str | None:
    """None passes through (means 'clear the key'); bad paths become DRF
    validation errors (400 with a Chinese message)."""
    if value is None:
        return None
    try:
        return str(system_config.validate_directory(value))
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc


class SystemPathsSerializer(serializers.Serializer):
    data_dir = serializers.CharField(required=False, allow_null=True, allow_blank=False)
    temp_dir = serializers.CharField(required=False, allow_null=True, allow_blank=False)

    def validate_data_dir(self, value: str | None) -> str | None:
        return _validate_or_error(value)

    def validate_temp_dir(self, value: str | None) -> str | None:
        return _validate_or_error(value)


class SystemPathsView(APIView):
    """Storage paths.

    PUT is administrator-only everywhere (``system_config`` feature). GET is for
    any authenticated user **on the desktop profile**; when
    ``SYSTEM_PATHS_VISIBLE_TO_ALL`` is False (server profile) it is admin-only
    too — the payload describes the server's own filesystem then, and a plain
    account has no reason to see it.
    """

    permission_classes = [IsAuthenticated]
    required_feature = 'system_config'

    def get_permissions(self):
        # 闸门在 API 上，不靠前端隐藏（服务器形态下界面根本请求不到这份数据）。
        if self.request.method == 'PUT' or not settings.SYSTEM_PATHS_VISIBLE_TO_ALL:
            return [IsAuthenticated(), FeaturePermission()]
        return super().get_permissions()

    def get(self, request):
        return Response(self._payload(request.user, restart_required=False))

    def put(self, request):
        serializer = SystemPathsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data_dir = serializer.validated_data.get('data_dir')
        temp_dir = serializer.validated_data.get('temp_dir')

        config_file = self._config_file()
        before = system_config.load_config(config_file)
        system_config.save_config(config_file, data_dir, temp_dir)
        after = system_config.load_config(config_file)
        return Response(
            self._payload(request.user, restart_required=before != after)
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _anchor_dir(self) -> Path:
        """The fixed anchor directory (userData / exe dir / project root)
        where system_config.json and secret.key live — set by the settings
        hooks as ``SYSTEM_CONFIG_ANCHOR_DIR``."""
        anchor = getattr(settings, 'SYSTEM_CONFIG_ANCHOR_DIR', None)
        return Path(anchor) if anchor else Path(settings.BASE_DIR)

    def _config_file(self) -> Path:
        return system_config.config_file_path(self._anchor_dir())

    def _payload(self, user, restart_required: bool) -> dict:
        config_file = self._config_file()
        configured = system_config.load_config(config_file)
        return {
            'data_dir': str(settings.BASE_DIR),
            'db_path': str(settings.DATABASES['default']['NAME']),
            'media_path': str(settings.MEDIA_ROOT),
            'temp_dir': tempfile.gettempdir(),
            'config_file': str(config_file),
            'configured': {
                'data_dir': configured.get('data_dir'),
                'temp_dir': configured.get('temp_dir'),
            },
            'editable': user.role == 'administrator',
            'restart_required': restart_required,
        }
