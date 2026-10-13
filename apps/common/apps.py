from django.apps import AppConfig
from django.db.backends.signals import connection_created

from .db_pragmas import configure_sqlite_connection


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.common'
    label = 'common'

    def ready(self):
        # dispatch_uid：AppConfig.ready() 在部分部署下会被调用两次，避免重复注册。
        connection_created.connect(
            configure_sqlite_connection, dispatch_uid='lqdp_sqlite_pragmas'
        )
