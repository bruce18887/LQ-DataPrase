# apps/datafiles/views/usage_views.py
"""GET /api/v1/files/usage/ —— 当前用户的磁盘占用（批2 · 第 5 项，只读）。

视图里没有任何计算：口径全在 ``apps/datafiles/storage_usage.py``。
用户名只取 ``request.user``，不接受路径/用户名入参 ⇒ 没有目录穿越面。
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.datafiles.storage_usage import get_user_usage

_FALSY = ('', '0', 'false', 'False', 'null', 'undefined')


class FileUsageView(APIView):
    """返回体字段与口径说明见 storage_usage 模块 docstring。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # fresh=1 绕过 TTL 缓存：前端在每次本地写操作后带它（计划订正④），
        # 这样「上传完立刻看到新数」不必在服务端 8 个写路径各挂一次失效。
        raw = request.query_params.get('fresh', '')
        fresh = raw not in _FALSY
        return Response(get_user_usage(request.user, fresh=fresh))
