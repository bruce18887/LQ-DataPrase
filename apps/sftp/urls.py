from rest_framework.routers import DefaultRouter
from .views import SftpViewSet

router = DefaultRouter()
router.register(r'sftp', SftpViewSet, basename='sftp')

urlpatterns = router.urls
