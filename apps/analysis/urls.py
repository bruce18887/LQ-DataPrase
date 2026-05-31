from rest_framework.routers import DefaultRouter
from .views import AnalysisViewSet, StatisticsViewSet

router = DefaultRouter()
router.register(r'analysis', AnalysisViewSet, basename='analysis')
router.register(r'statistics', StatisticsViewSet, basename='statistics')

urlpatterns = router.urls
