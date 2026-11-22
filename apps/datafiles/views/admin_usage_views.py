"""GET /api/v1/admin/files/users/ —— 管理员视角的用户文件占用清单（只读）。

口径不在这里重算：每个账号的占用仍走 ``get_user_usage``（与 ``/files/usage/``
同一份实现、同一个 30s 分桶缓存），本视图只负责三件事：

* 出人名单：只列启用账号，按 ``id`` 升序（前端按这个顺序铺行，别让数据库的
  默认排序漂进契约）；
* 降级：用户名拼不成安全的数据目录（``''`` / ``'.'`` / ``'..'`` / 含分隔符）时
  ``_user_data_root`` 抛 ``ValueError`` ⇒ 该账号 ``usage: null``。既不要让一个
  坏账号把整份清单打成 500，也不要谎报成一串 0（「算不出来」≠「没占盘」）；
* 只读：没有任何写入口。
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import FeaturePermission
from apps.datafiles.storage_usage import get_user_usage


class AdminFileUserUsageView(APIView):
    """闸门在表里（``FEATURE_PERMISSIONS['data_view_all']``），视图不写角色名。"""

    permission_classes = [IsAuthenticated, FeaturePermission]
    required_feature = 'data_view_all'

    def get(self, request):
        results = []
        for user in User.objects.filter(is_active=True).order_by('id'):
            try:
                usage = get_user_usage(user)
            except ValueError:
                # 见模块 docstring 的「降级」：单个账号算不出来只影响它自己。
                usage = None
            results.append({
                'id': user.id,
                'username': user.username,
                'display_name': user.display_name,
                'role': user.role,
                'is_active': user.is_active,
                'usage': usage,
            })
        return Response({'results': results})
