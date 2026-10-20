# apps/weight/urls.py
from django.urls import path

from .views import WeightExportView, WeightParseView

urlpatterns = [
    path('weight/parse/', WeightParseView.as_view(), name='weight-parse'),
    path('weight/export/', WeightExportView.as_view(), name='weight-export'),
]
