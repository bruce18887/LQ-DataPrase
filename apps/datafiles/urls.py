from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.datafiles.views import (
    AdminFileUserUsageView,
    AssignCombinationView,
    BatchDirDeleteView,
    BatchDirImportView,
    BatchDirListView,
    DataBrowserView,
    DataCombinationViewSet,
    DataConsistencyCheckView,
    DataFileViewSet,
    FileActivateView,
    FileUploadView,
    FileUsageView,
    ParseHistoryListView,
    SubBatchDeleteView,
)

router = DefaultRouter()
router.register(r'files', DataFileViewSet, basename='datafile')
router.register(r'combinations', DataCombinationViewSet, basename='combination')

urlpatterns = [
    path('files/assign_combination/', AssignCombinationView.as_view(), name='file-assign-combination'),
    # 必须排在 router include 之前：DefaultRouter 生成的详情路由是
    # `^files/(?P<pk>[^/.]+)/$`（lookup 是 `[^/.]+`，不是 <int>，见 routers.py:143），
    # 会把 `files/usage/` 当成 pk='usage' 的详情请求吞掉。
    path('files/usage/', FileUsageView.as_view(), name='file-usage'),
    # 管理员跨用户只读清单（Task 4）：与 router 的 `files/...` 前缀不重叠，
    # 不会被 `^files/(?P<pk>[^/.]+)/$` 吞掉。
    path('admin/files/users/', AdminFileUserUsageView.as_view(), name='admin-file-users'),
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
