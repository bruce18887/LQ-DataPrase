from rest_framework.routers import DefaultRouter
from .views import ExportViewSet

router = DefaultRouter()
router.register(r'export', ExportViewSet, basename='export')

urlpatterns = router.urls
