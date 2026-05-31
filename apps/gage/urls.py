from rest_framework.routers import DefaultRouter
from .views import GageViewSet

router = DefaultRouter()
router.register(r'gage', GageViewSet, basename='gage')

urlpatterns = router.urls
