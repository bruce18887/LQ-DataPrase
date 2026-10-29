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
# 终态名单的唯一归属点。**终态三元组的生产消费者有两处**，各自硬编码过同一个三元组
# （`prune_jobs` 的选行与 `executor.py::_write_back` 的 exclude），加状态时漏一处就是「行永远
# prune 不掉」或「回填把别人写的终态覆盖掉」—— 2026-10-29 评审点的名，两处现在都 import 这个常量。
# 名单之外还有两份**同一份词表**的手抄，都是**刻意**保留的：`test/backend/test_job_cancel.py::
# test_cancel_still_rejects_every_terminal_row` 自己写一份同样的词表，判据硬编码期望值才是
# 独立对照（让它 import 常量 = 加错状态时两处一起错、互相圆场）；`scripts/perf_load20.py:290`
# 只走 HTTP、不 import 本应用，让压测脚本挂上 Django 依赖属另一条账。**都不许「去重」。**
# 这两份账**不含** `views.py::_sync_fallback` 里那个 `('done', 'error')` 二元组：它不是终态词表
# 的消费者，问的是另一件事 ——「entry 自己有没有把这一行结算掉并写好那道人话」（只有下载类会，
# 见 `sftp_job.py` 那三条 update）。换成 import 本常量会把 `cancelled` 也认成「entry 已结算」，
# 那是语义变更，不是去重；grep 手抄时别把它算进上面这两份账。
# 回收侧的判据在 `test/backend/test_prune_jobs_dir.py`（`pending`/`running` 各钉了一条
# 「不许 prune」）。
TERMINAL_STATUSES = ('done', 'error', 'cancelled')


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
