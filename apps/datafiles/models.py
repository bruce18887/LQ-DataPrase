from django.conf import settings
from django.db import models


class DataFile(models.Model):
    FORMAT_CHOICES = [
        ('CTA8290D', 'CTA8290D'),
        ('CTA8280F', 'CTA8280F'),
        ('ETS88', 'ETS88'),
        ('STS8200', 'STS8200'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('parsing', 'Parsing'),
        ('ready', 'Ready'),
        ('error', 'Error'),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='datafiles',
    )
    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512)
    file_size = models.BigIntegerField()
    format_type = models.CharField(max_length=20, choices=FORMAT_CHOICES)
    row_count = models.IntegerField(null=True, blank=True)
    col_count = models.IntegerField(null=True, blank=True)
    program_name = models.CharField(max_length=255, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Data File'
        verbose_name_plural = 'Data Files'

    def __str__(self):
        return self.filename


class ParseHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='parse_histories',
    )
    datafile = models.ForeignKey(
        DataFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parse_histories',
    )
    filename = models.CharField(max_length=255)
    filepath = models.CharField(max_length=512)
    format_type = models.CharField(max_length=20, choices=DataFile.FORMAT_CHOICES)
    rows = models.IntegerField()
    cols = models.IntegerField()
    parsed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-parsed_at']
        verbose_name = 'Parse History'
        verbose_name_plural = 'Parse Histories'

    def __str__(self):
        return f"{self.filename} - {self.parsed_at}"
