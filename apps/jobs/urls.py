from django.urls import path

from apps.jobs.views import (
    JobCancelView,
    JobDetailView,
    JobDownloadView,
    JobListView,
    JobSubmitView,
)

# 注意顺序：`<str:kind>/` 必须排在 `<int:pk>/…` 之后由类型区分开 ——
# job_id 是 int、kind 是 str，DRF 的转换器在这里正好把它们分得干净。
urlpatterns = [
    path('', JobListView.as_view(), name='job-list'),
    path('<int:pk>/', JobDetailView.as_view(), name='job-detail'),
    path('<int:pk>/download/', JobDownloadView.as_view(), name='job-download'),
    path('<int:pk>/cancel/', JobCancelView.as_view(), name='job-cancel'),
    path('<str:kind>/', JobSubmitView.as_view(), name='job-submit'),
]
