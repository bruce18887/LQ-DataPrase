from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.datafiles.views import (
    BatchDirDeleteView,
    BatchDirImportView,
    BatchDirListView,
    DataBrowserView,
    DataFileViewSet,
    FileActivateView,
    FileUploadView,
    ParseHistoryListView,
)

router = DefaultRouter()
router.register(r'files', DataFileViewSet, basename='datafile')

urlpatterns = [
    path('', include(router.urls)),
    path('upload/', FileUploadView.as_view(), name='file-upload'),
    path('activate/<int:pk>/', FileActivateView.as_view(), name='file-activate'),
    path('history/', ParseHistoryListView.as_view(), name='parse-history'),
    path('browse/', DataBrowserView.as_view(), name='data-browse'),
    path('batch-dirs/', BatchDirListView.as_view(), name='batch-dir-list'),
    path('batch-dirs/import/', BatchDirImportView.as_view(), name='batch-dir-import'),
    path('batch-dirs/<str:dir_name>/', BatchDirDeleteView.as_view(), name='batch-dir-delete'),
]
