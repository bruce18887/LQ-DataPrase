"""管理员跨用户只读清单的作用域判据（唯一入口 ``scoped_files``）。

放开的只有「按用户看文件清单」这一件事：``DataFileViewSet.get_queryset`` 在
``action == 'list'`` 时调用本函数，其它动作（详情 / options / 写操作）一律拿回
``owner=request.user`` 的默认集 —— 详情对他人文件仍是 404，不在这里开口子。

权限不在这里抄角色名：``role_can`` + ``FEATURE_PERMISSIONS['data_view_all']``
是唯一事实来源，表里改角色集合这里自动跟随。
"""
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.permissions import role_can

SCOPE_FEATURE = 'data_view_all'


def _resolve_scope_owner_id(request, action):
    """把 ``?owner_id=`` 解析成「本次作用域的 owner id」；``None`` 表示不分作用域。

    ``scoped_files`` 与 ``scoped_owner_id`` 共用这一套判据（鉴权 → 解析），
    避免两处各写一遍角色/整数校验而漂移。
    """
    owner_id = (request.query_params.get('owner_id') or '').strip()
    if action != 'list' or not owner_id:
        return None
    # 先鉴权再解析：非管理员不该从「400 还是 403」反问出他人 id 的取值形状。
    if not role_can(request.user.role, SCOPE_FEATURE):
        raise PermissionDenied('没有权限查看其他用户的文件')
    try:
        return int(owner_id)
    except (TypeError, ValueError):
        raise ValidationError({'owner_id': '必须是整数'})


def scoped_files(request, action, default_qs):
    """按 ``?owner_id=`` 决定本次文件清单的作用域。

    * 非 ``list`` 动作、或没带 ``owner_id``（含空白值）⇒ 原样返回 ``default_qs``；
    * 带 ``owner_id`` 但没有 ``data_view_all`` ⇒ ``PermissionDenied``（403）；
    * ``owner_id`` 不是整数 ⇒ ``ValidationError({'owner_id': '必须是整数'})``（400）；
    * 否则整集换成目标用户的文件。注意这里是**替换**而不是叠加：调用方随后的
      search / tag / 列筛选都在目标用户的集合上继续收窄。

    空串按「没传」处理：前端把未选中序列化成 ``?owner_id=`` 时不应 400，
    更不能被 ``int('')`` 或 ``0`` 读成「0 号用户」而返回空集。
    """
    value = _resolve_scope_owner_id(request, action)
    if value is None:
        return default_qs
    return default_qs.model.objects.filter(owner_id=value)


def scoped_owner_id(request, action):
    """本次清单作用域的 owner id：跨用户取 ``owner_id``，否则取 ``request.user.pk``。

    供搜索标签兜底这类「需要在同一作用域里再查一次」的调用方取 owner，
    使它们与 ``scoped_files`` 落在同一个用户集上（否则并集会把本人行混进他人清单）。
    """
    value = _resolve_scope_owner_id(request, action)
    return request.user.pk if value is None else value
