from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = [
        ('administrator', 'Administrator'),
        ('user', 'User'),
        ('viewer', 'Viewer'),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='user',
    )
    display_name = models.CharField(max_length=150, blank=True)
    login_attempts = models.IntegerField(default=0)
    lockout_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'accounts_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.username


class UserSetting(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='settings',
    )
    page_size = models.IntegerField(default=100)
    chart_height = models.IntegerField(default=500)
    table_height = models.IntegerField(default=700)
    chart_dpi = models.IntegerField(default=150)
    cpk_a_threshold = models.FloatField(default=1.67)
    cpk_b_threshold = models.FloatField(default=1.33)
    cpk_c_threshold = models.FloatField(default=1.0)
    chart_engine = models.CharField(max_length=50, default='echarts')
    aggrid_header_font_size = models.IntegerField(default=11)
    recent_files = models.JSONField(default=list)
    max_recent_files = models.IntegerField(default=10)
    histogram_label_offset = models.IntegerField(default=4)
    # Per-export-type filename templates: {export_type: template}
    # (keys/defaults in apps.common.export_naming.EXPORT_TEMPLATE_DEFAULTS)
    export_filename_templates = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'accounts_user_setting'
        verbose_name = 'User Setting'
        verbose_name_plural = 'User Settings'

    def __str__(self):
        return f'Settings for {self.user.username}'
