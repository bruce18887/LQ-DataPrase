"""GET /api/v1/files/usage/ —— 当前用户的磁盘占用（批2 · 第 5 项，只读）。

视图里没有任何计算：口径全在 ``apps/datafiles/storage_usage.py``。
用户名只取 ``request.user``、不接受入参，**但这不等于没有穿越面**：它照样拼进扫描路径，
而 Django 默认校验器实测接受 ``..`` 作用户名 ⇒ 挡在 ``is_safe_username`` 那一层（见 get()）。
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.usernames import is_safe_username
from apps.datafiles.storage_usage import get_user_usage

# 白名单而不是黑名单：黑名单是 fail-open 的（实测 'no' / 'off' / 'TRUE' / 'abc' / ' '
# 全被当成真），而这里的「为真」代价不是多算一次自己的数，是把**所有人**的缓存清掉。
_FRESH_TRUE = ('1', 'true', 'yes')


class FileUsageView(APIView):
    """返回体字段与口径说明见 storage_usage 模块 docstring。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # 用户名拼不成一个安全的数据根目录（'' / '.' / '..' / 含分隔符）⇒ **204，不是 500**。
        # 三条理由：① 这不是「服务器坏了」，把它冒成异常会让前端每次进门都弹一条错误 toast
        # （占用是激活刷新，2026-11-14 终审 F3，用户拍板走 204）；② 返回一串 0 更糟——那是
        # 把「算不出来」谎报成「这个用户没占盘」；③ 204 没有返回体，前端的 falsy 分支
        # （utils/diskUsage.ts 里 `!usage ⇒ null`）本来就让 chip 自然缺席，不需要新代码。
        # 判据与 `_user_data_root` 共用 is_safe_username，两边不会各写一份而漂开。
        if not is_safe_username(request.user.username):
            return Response(status=204)
        # fresh=1 绕过 TTL 缓存：前端在每次本地写操作后带它（计划订正④），
        # 这样「上传完立刻看到新数」不必在服务端 8 个写路径各挂一次失效。
        raw = request.query_params.get('fresh', '')
        fresh = raw.strip().lower() in _FRESH_TRUE
        return Response(get_user_usage(request.user, fresh=fresh))
