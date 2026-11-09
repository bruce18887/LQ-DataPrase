from rest_framework.permissions import BasePermission

# 功能门禁的唯一判据表：视图里不许再硬编码角色字符串做门禁（spec §3.2），
# 未列出的功能名 ⇒ 一律拒绝（fail closed）。
# 已知例外，都不是门禁，留在原处：apps/accounts/views.py 的「最后一个启用管理员」校验、
# apps/common/views.py 下发给前端的 editable 提示。
FEATURE_PERMISSIONS = {
    'user_management': ['administrator'],
    'system_config': ['administrator'],
    'audit_log_view': ['administrator'],
    'data_delete': ['administrator'],
    'data_repair_mutate': ['administrator', 'user'],
}


def role_can(role, feature):
    """角色是否具备某功能。FeaturePermission 与自带判定的视图共用。"""
    return role in FEATURE_PERMISSIONS.get(feature, [])


class FeaturePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if hasattr(view, 'required_feature'):
            return role_can(request.user.role, view.required_feature)
        return True

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
