from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('', RedirectView.as_view(url='/api/schema/swagger/', permanent=False)),
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
    path('api/v1/', include('apps.data_correlation.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
