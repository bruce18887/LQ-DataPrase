from rest_framework.permissions import BasePermission

FEATURE_PERMISSIONS = {
    'dashboard_view': ['administrator', 'user', 'viewer'],
    'dashboard_edit': ['administrator', 'user'],
    'data_upload': ['administrator', 'user'],
    'data_delete': ['administrator'],
    'data_export': ['administrator', 'user', 'viewer'],
    'analysis_view': ['administrator', 'user', 'viewer'],
    'analysis_create': ['administrator', 'user'],
    'analysis_delete': ['administrator'],
    'report_view': ['administrator', 'user', 'viewer'],
    'report_create': ['administrator', 'user'],
    'report_delete': ['administrator'],
    'user_management': ['administrator'],
    'system_config': ['administrator'],
    'audit_log_view': ['administrator'],
}


class FeaturePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if hasattr(view, 'required_feature'):
            allowed_roles = FEATURE_PERMISSIONS.get(view.required_feature, [])
            return request.user.role in allowed_roles
        return True

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
