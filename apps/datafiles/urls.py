from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.datafiles.views import (
    BatchDirDeleteView,
    BatchDirImportView,
    BatchDirListView,
    DataBrowserView,
    DataConsistencyCheckView,
    DataFileViewSet,
    FileActivateView,
    FileUploadView,
    ParseHistoryListView,
    SubBatchDeleteView,
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
    path('batch-dirs/<str:batch_name>/sub/<str:sub_batch_name>/', SubBatchDeleteView.as_view(), name='sub-batch-delete'),
    path('consistency-check/', DataConsistencyCheckView.as_view(), name='consistency-check'),
]
