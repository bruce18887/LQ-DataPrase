"""URLs for apps.common system-level endpoints."""

from django.urls import path

from apps.common.health import HealthView, ReadyView
from apps.common.shutdown import ShutdownView
from apps.common.views import SystemPathsView

urlpatterns = [
    path('system/paths/', SystemPathsView.as_view(), name='system-paths'),
    # Deliberately always routed, and 404s when no token is configured: the
    # gate lives in the view so it is testable without reloading the URLconf.
    # "Not enabled" and "not mounted" are indistinguishable to a client, which
    # is the posture we want.
    path('system/shutdown/', ShutdownView.as_view(), name='system-shutdown'),
    # Probes. Deliberately outside /system/ — they are infrastructure, not
    # user-facing API surface, and clients must reach them before login.
    path('health/', HealthView.as_view(), name='health'),
    path('ready/', ReadyView.as_view(), name='ready'),
]
