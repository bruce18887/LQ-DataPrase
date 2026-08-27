from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models

# 默认隐藏的记录级列（来自 CTA8290D/CTA8280F 等格式 [Data] 表头记录块）。
# 导出 Excel 与查看数据 ag-grid 共用；仅为默认值，用户可在系统设置中调整。
DEFAULT_HIDDEN_COLUMNS = [
    'Part_No', 'Dut_Pass', 'X_COORD', 'Y_COORD', 'QR_Code',
    'Start_T', 'Alarm', 'Data_Cnt',
]


class UserManager(DjangoUserManager):
    """Keep the custom ``role`` field in sync with superuser status.

    Django's default ``create_superuser`` only sets is_superuser/is_staff;
    the app's permission system (FeaturePermission, JWT ``role`` claim,
    frontend admin checks) reads ``role`` exclusively, so a superuser left
    at the model default 'user' silently loses administrator privileges —
    exactly what the packaged-app bootstrap hit on fresh installs.
    """

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # A superuser is an administrator by definition; force the role so a
        # caller-supplied value can't create a superuser that the app's
        # role-based checks treat as a regular user.
        extra_fields['role'] = 'administrator'
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    objects = UserManager()
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
    # 导出请求超时（秒）。前端所有 /export/ 调用统一读取此值设置 axios
    # timeout（默认 600 与 DataBrowser 此前硬编码的 600000ms 一致）。
    export_timeout = models.IntegerField(default=600)
    # SFTP 浏览器单文件下载超时（秒）。SSE 下载流服务端按此值设 channel
    # socket 超时并作为整体 deadline；前端下载请求也读取此值设置 axios
    # timeout（批量下载）。(默认 600，用户可在 SFTP 工具栏自由调整)
    sftp_download_timeout = models.IntegerField(default=600)
    # 默认隐藏列（记录级列名单）：同时作用于「查看数据」ag-grid 与「导出 Excel」
    # （导出中保留列但标记为 Excel 隐藏列）。空列表 = 未设置，由序列化层回退
    # 到 DEFAULT_HIDDEN_COLUMNS（用户主动清空全部选项时同样回退，语义：这些
    # 列始终保持默认隐藏）。
    default_hidden_columns = models.JSONField(default=list, blank=True)
    # ECharts 渲染器：'svg' | 'canvas'（前端 echarts-theme.ts 启动时读取）。
    # 曾缺失该字段——保存时 DRF 静默丢弃未知键，刷新后回退默认值。
    chart_renderer = models.CharField(max_length=20, default='svg')
    # SFTP 浏览器断线续连：上次访问路径 + 上次连接凭据（手动连接记录 host/port/username，
    # 保存配置连接记录 config_name 用于服务端自动重连）。不在 UserSettingSerializer 白名单内，
    # 由 apps.sftp 直接 ORM 读写，settings 页 GET/PUT 不受影响。
    sftp_last_path = models.CharField(max_length=1024, default='/')
    sftp_last_config = models.CharField(max_length=100, blank=True, default='')
    sftp_last_host = models.CharField(max_length=255, blank=True, default='')
    sftp_last_port = models.IntegerField(default=22)
    sftp_last_username = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        db_table = 'accounts_user_setting'
        verbose_name = 'User Setting'
        verbose_name_plural = 'User Settings'

    def __str__(self):
        return f'Settings for {self.user.username}'
