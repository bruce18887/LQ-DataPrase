from django.conf import settings
from django.db import models

from . import crypto


class SftpConfig(models.Model):
    """A user-owned, saved SFTP connection profile.

    The password is stored encrypted (Fernet token) in ``password_encrypted``;
    plaintext is never persisted. Access it via ``set_password`` /
    ``get_password`` which delegate to :mod:`apps.sftp.crypto`.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sftp_configs',
    )
    name = models.CharField(max_length=100)
    host = models.CharField(max_length=255)
    port = models.IntegerField(default=22)
    username = models.CharField(max_length=255)
    password_encrypted = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('owner', 'name'),)
        ordering = ['name']

    def set_password(self, raw: str) -> None:
        """Encrypt and store ``raw`` (plaintext) into ``password_encrypted``."""
        self.password_encrypted = crypto.encrypt(raw or '')

    def get_password(self) -> str:
        """Return the decrypted plaintext password (empty string if none)."""
        return crypto.decrypt(self.password_encrypted)

    def __str__(self):
        return f"{self.name} ({self.username}@{self.host})"


class SftpSearchPreset(models.Model):
    """一次搜索条件的快照（spec §3.10）。``spec`` 原样存 SearchSpec 的 JSON 形态。

    与 :class:`SftpConfig` 同构的 owner 作用域契约：``unique_together (owner, name)``
    让两个用户各存一个叫「找 RT」的预设互不干扰；每人条数上限
    （``contracts.PRESET_MAX_PER_USER``）是**视图层**规则，不在这里（模型层没有跨行的
    条件计数可表达，硬要约束就得靠触发器）。

    ``spec`` 不做归一化：写入前已由 ``parse_spec`` 校验过（见
    ``search_views.SftpSearchMixin.save_search_preset``），存原样是为了「载入预设」
    回填表单时不出现「我存的滑块值怎么变了」这类解释不清的差值。
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sftp_search_presets',
    )
    name = models.CharField(max_length=80)
    spec = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('owner', 'name'),)
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.owner}/{self.name}'
