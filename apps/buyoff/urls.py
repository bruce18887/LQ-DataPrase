from rest_framework.routers import DefaultRouter
from .views import BuyoffViewSet

router = DefaultRouter()
router.register(r'buyoff', BuyoffViewSet, basename='buyoff')

urlpatterns = router.urls
