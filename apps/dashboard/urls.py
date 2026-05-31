from django.urls import path
from .views import DashboardSummaryView, BatchReportView

urlpatterns = [
    path('summary/', DashboardSummaryView.as_view(), name='dashboard-summary'),
    path('batch-report/', BatchReportView.as_view(), name='batch-report'),
]
