from rest_framework.routers import DefaultRouter
from .views import BatchReportViewSet

router = DefaultRouter()
router.register(r'batch-report', BatchReportViewSet, basename='batch-report')

urlpatterns = router.urls
