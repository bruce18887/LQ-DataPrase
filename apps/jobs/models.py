"""重活作业化（P3）：`Job` 模型。

设计稿 `docs/specs/2026-10-17-heavy-job-offload-design.md` §3。
"""

from django.conf import settings
from django.db import models

KIND_CHOICES = [
    ('export_excel', '导出 Excel'),
    ('export_batch_charts', '批量图表'),
    ('export_html_report', 'HTML 报告'),
    ('sftp_download', 'SFTP 批量下载'),
]
STATUS_CHOICES = [
    ('pending', '排队中'),
    ('running', '执行中'),
    ('done', '已完成'),
    ('error', '失败'),
    ('cancelled', '已取消'),
]


class Job(models.Model):
    """一次「不该占请求线程」的活。

    `params` 存**提交那一刻**的请求参数快照，而不是外键引用：作业可能在用户
    改完设置、甚至换过筛选之后才被领取，语义必须钉死在提交时。
    `result_path` 相对 `MEDIA_ROOT`，落在 `jobs/<owner_id>/<job_id>/` —— 刻意与
    `media/data/<username>/`（用户数据）分开，否则 `migrate_user_paths` 会把
    数字目录名当遗留 user-id 目录去改写。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='jobs')
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES,
                              default='pending', db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    params = models.JSONField(default=dict)
    result_path = models.CharField(max_length=512, blank=True, default='')
    result_name = models.CharField(max_length=255, blank=True, default='')
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['owner', 'status', 'created_at'])]

    def __str__(self):
        return f'Job {self.pk} {self.kind} {self.status}'
