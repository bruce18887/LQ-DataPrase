from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AuditEventListView,
    ChangePasswordView,
    LoginView,
    LogoutView,
    UserManagementViewSet,
    UserProfileView,
    UserSettingsView,
)

router = DefaultRouter()
router.register(r'users', UserManagementViewSet, basename='user-management')

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    # POST { "refresh": "<token>" } -> { "access": "<new>", "refresh": "<new>" }.
    # Token rotation + blacklist are governed by SIMPLE_JWT in
    # config/settings/base.py (ROTATE_REFRESH_TOKENS / BLACKLIST_AFTER_ROTATION).
    path('refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('settings/', UserSettingsView.as_view(), name='settings'),
    # 只读端点：没有 detail 路由、没有任何写方法（spec §6「该端点只读」）。
    path('audit-events/', AuditEventListView.as_view(), name='audit-events'),
    path('', include(router.urls)),
]
