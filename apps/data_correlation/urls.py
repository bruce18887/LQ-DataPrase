from rest_framework.routers import DefaultRouter
from .views import CorrelationViewSet

router = DefaultRouter()
router.register(r'correlation', CorrelationViewSet, basename='correlation')

urlpatterns = router.urls
