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
