"""URLs for apps.common system-level endpoints."""

from django.urls import path

from apps.common.views import SystemPathsView

urlpatterns = [
    path('system/paths/', SystemPathsView.as_view(), name='system-paths'),
]
