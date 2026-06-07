"""SFTP saved-config endpoints, extracted into a mixin to keep views.py small.

All queries are owner-scoped (``filter(owner=request.user)``) — a user must
never read, modify, or delete another user's config. Passwords are never
returned in any response.
"""

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import SftpConfig
from .serializers import SftpConfigSerializer


class SftpConfigMixin:
    """Mixin providing configs / save_config / delete_config actions."""

    @action(detail=False, methods=['get'])
    def configs(self, request):
        """GET /sftp/configs/ → {'configs': [...]} for the current user."""
        qs = SftpConfig.objects.filter(owner=request.user)
        data = SftpConfigSerializer(qs, many=True).data
        return Response({'configs': data})

    @action(detail=False, methods=['post'])
    def save_config(self, request):
        """POST /sftp/save_config/ — create or update by (owner, name).

        Body: {name, host, port, username, password}. Updates in place if a
        config with that name already exists for this user; password is only
        changed when a non-empty one is supplied.
        """
        name = request.data.get('name')
        if not name:
            return Response({'name': ['此字段是必填项。']}, status=status.HTTP_400_BAD_REQUEST)

        instance = SftpConfig.objects.filter(owner=request.user, name=name).first()
        serializer = SftpConfigSerializer(instance, data=request.data, partial=bool(instance))
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save(owner=request.user)
        code = status.HTTP_200_OK if instance else status.HTTP_201_CREATED
        return Response(serializer.data, status=code)

    @action(detail=False, methods=['post', 'delete'])
    def delete_config(self, request):
        """POST or DELETE /sftp/delete_config/ — owner-scoped delete.

        Body: {name} or {id}. Returns {'deleted': True} or 404 if not found.
        """
        config_id = request.data.get('id')
        name = request.data.get('name')

        qs = SftpConfig.objects.filter(owner=request.user)
        if config_id is not None:
            qs = qs.filter(id=config_id)
        elif name:
            qs = qs.filter(name=name)
        else:
            return Response(
                {'error': '需要 name 或 id 参数'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance = qs.first()
        if not instance:
            return Response({'error': '未找到配置'}, status=status.HTTP_404_NOT_FOUND)

        instance.delete()
        return Response({'deleted': True})
