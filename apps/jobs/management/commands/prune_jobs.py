"""`manage.py prune_jobs --days=7`：删掉超期的已完成/失败作业行与其结果文件。

作业产物落在 `MEDIA_ROOT/jobs/<owner>/<job>/`，不清会一直涨（一次批量图表几十 MB）。
只删 `done`/`error`/`cancelled`：`running`/`pending` 的行留着，它们还可能有产物要收。
"""

import os
import shutil
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.datafiles.utils import resolve_file_path
from apps.jobs.models import Job


class Command(BaseCommand):
    help = '删除超过 N 天的已结束作业行及其结果目录'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--dry-run', action='store_true',
                            help='只打印要删什么，不动盘')

    def handle(self, *args, **options):
        days = options['days']
        if days < 0:
            raise CommandError('--days 不能为负')
        cutoff = timezone.now() - timedelta(days=days)
        stale = Job.objects.filter(
            status__in=('done', 'error', 'cancelled'),
            finished_at__lt=cutoff)

        removed_rows = 0
        removed_dirs = 0
        for job in stale.iterator():
            if options['dry_run']:
                self.stdout.write(f'would remove job {job.id} ({job.result_path})')
                continue
            # 结果目录按 job 分，整目录删比逐文件删可靠：worker 可能落了临时件
            job_dir = os.path.dirname(resolve_file_path(job.result_path)) \
                if job.result_path else ''
            if job_dir and os.path.isdir(job_dir):
                shutil.rmtree(job_dir, ignore_errors=True)
                removed_dirs += 1
            job.delete()
            removed_rows += 1

        self.stdout.write(self.style.SUCCESS(
            f'prune_jobs: {days} 天前的已结束作业 → 删行 {removed_rows}、'
            f'删目录 {removed_dirs}'
            + ('（dry-run，未改动）' if options['dry_run'] else '')))
