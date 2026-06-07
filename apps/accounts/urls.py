from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
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
    path('settings/', UserSettingsView.as_view(), name='settings'),
    path('', include(router.urls)),
]
