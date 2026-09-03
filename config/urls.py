from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import include, path, re_path
from django.views.generic import RedirectView, TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/', include('apps.datafiles.urls')),
    path('api/v1/', include('apps.analysis.urls')),
    path('api/v1/', include('apps.dashboard.urls')),
    path('api/v1/', include('apps.batch_report.urls')),
    path('api/v1/', include('apps.buyoff.urls')),
    path('api/v1/', include('apps.gage.urls')),
    path('api/v1/', include('apps.export.urls')),
    path('api/v1/', include('apps.sftp.urls')),
    path('api/v1/', include('apps.common.urls')),
]

# API 文档只是开发期便利。drf-spectacular 的两个视图默认 AllowAny，而
# SPECTACULAR_SETTINGS 未设 SERVE_PERMISSIONS —— 打包版一旦暴露，外人
# 可匿名下载完整端点/参数结构。故用开关控制：开发态（config.settings.
# development）保留，standalone 关闭。注意 playwright.config.ts 用
# /api/schema/ 做后端健康检查，而它跑的是 development 配置，不受影响。
if getattr(settings, 'API_DOCS_ENABLED', True):
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/schema/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    ]

# ---------------------------------------------------------------------------
# Frontend SPA static assets
# ---------------------------------------------------------------------------
# Vite builds index.html with absolute URLs (``/assets/...``, ``/favicon.svg``,
# ``/icons.svg``) — NOT prefixed with ``STATIC_URL``.  In dev mode the Vite
# dev server serves them; in standalone/production mode we must serve them
# ourselves.  WhiteNoise only serves files under ``STATIC_URL`` (``/static/``),
# so we mount explicit views that stream the files directly from the
# ``frontend_dist`` directory (registered as a template dir in standalone.py).
#
# These patterns MUST come before the SPA catch-all below, otherwise the
# catch-all would return index.html for every asset request and the Vue app
# would never mount (browser receives HTML where it expects JS/CSS).


def _frontend_dist() -> Path | None:
    """Return the frontend_dist directory if configured, else None."""
    dirs = getattr(settings, 'TEMPLATES', [{}])[0].get('DIRS', [])
    return Path(dirs[0]) if dirs else None


def _serve_frontend_file(rel_path: str):
    """Return a view that serves a file from frontend_dist/<rel_path>.

    For directory mounts (e.g. ``assets/``), the trailing portion of the URL
    path is appended to ``rel_path`` so that ``/assets/foo.js`` resolves to
    ``frontend_dist/assets/foo.js``.
    """

    def view(request, path: str = ''):
        dist = _frontend_dist()
        if not dist:
            raise Http404('frontend_dist not configured')
        # Combine the mount-relative path with the captured sub-path.
        target_rel = f'{rel_path}/{path}' if path else rel_path
        dist_root = dist.resolve()
        file_path = (dist / target_rel).resolve()
        # Prevent path traversal: ensure the resolved path stays inside dist.
        # ``str.startswith`` was too weak -- a sibling directory sharing the
        # prefix (``frontend_dist_evil``) would pass the check.
        if not file_path.is_relative_to(dist_root):
            raise Http404('invalid path')
        if not file_path.is_file():
            raise Http404('file not found')
        return FileResponse(open(file_path, 'rb'))

    return view


# Serve the Vite-built assets (JS/CSS chunks) and top-level static files
# referenced by index.html with absolute paths.
urlpatterns += [
    re_path(r'^assets/(?P<path>.+)$', _serve_frontend_file('assets')),
    path('favicon.svg', _serve_frontend_file('favicon.svg')),
    path('icons.svg', _serve_frontend_file('icons.svg')),
]

# SPA catch-all: serve index.html for any non-API, non-static route so that
# Vue Router handles client-side navigation (e.g. /login, /dashboard).
# This only takes effect when the ``frontend_dist`` template directory is
# registered (i.e. in standalone mode); in dev mode the Vite dev server
# handles routing.
urlpatterns += [
    re_path(r'^(?!api/|assets/|favicon\.svg|icons\.svg).*$', TemplateView.as_view(template_name='index.html')),
]
