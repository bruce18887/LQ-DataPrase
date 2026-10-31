"""One-shot management command to rewrite DataFile.file_path when the
project is moved/renamed on disk.

Scenario: the project root was previously at
``C:\\Users\\Administrator\\Desktop\\DataPrase\\DataPhrase_Django`` and
later moved to ``C:\\Users\\Administrator\\Desktop\\DataPrase\\LQ-DataPrase``.
DataFile rows still carry the absolute path under the old root, so
loading any of them 400s the analysis endpoints with
``file_not_found_or_parse_failed`` because the file is no longer where
the DB says it is. The actual files were copied to
``<new_root>\\media\\uploads\\`` already; only the DB column is stale.

The command rewrites ``file_path`` for every row whose path is rooted
at the old project location and points at an existing file under the
new project location. It is idempotent: re-running it is a no-op once
all rows are aligned.

Usage:
    python manage.py fix_moved_project_paths
    python manage.py fix_moved_project_paths --old-root "<abs old path>" --new-root "<abs new path>"
    python manage.py fix_moved_project_paths --dry-run
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.datafiles.models import DataFile
from apps.datafiles.services import clear_parse_cache


class Command(BaseCommand):
    help = (
        'Rewrite DataFile.file_path entries that point at a stale project '
        'root to the corresponding path under the current MEDIA_ROOT.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--old-root',
            default=r'C:\Users\Administrator\Desktop\DataPrase\DataPhrase_Django',
            help='Absolute path of the project root that DataFile rows used to live under.',
        )
        parser.add_argument(
            '--new-root',
            default=str(settings.BASE_DIR),
            help='Absolute path of the current project root (defaults to settings.BASE_DIR).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without touching the database.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        old_root = os.path.normpath(options['old_root'])
        new_root = os.path.normpath(options['new_root'])
        dry_run = options['dry_run']

        if old_root == new_root:
            raise CommandError('--old-root and --new-root are identical; nothing to do.')

        if not os.path.isdir(new_root):
            raise CommandError(f'new-root does not exist: {new_root!r}')

        old_prefix = old_root.rstrip(os.sep) + os.sep
        updated = 0
        missing_after = 0
        unchanged = 0
        skipped = 0

        # Only scan rows whose path is still under the old root to avoid
        # touching the many rows that already point at the new root.
        candidates = DataFile.objects.filter(file_path__startswith=old_prefix)
        total = candidates.count()
        if total == 0:
            self.stdout.write(self.style.NOTICE(
                f'No DataFile rows under {old_root!r}; nothing to migrate.'
            ))
            return

        for df in candidates.iterator():
            rel = os.path.relpath(df.file_path, old_root)
            new_path = os.path.normpath(os.path.join(new_root, rel))

            if new_path == df.file_path:
                unchanged += 1
                continue

            # Sanity-check: refuse to rewrite to a path whose target file
            # is missing. Better to leave the row alone (and surface the
            # orphan via the consistency checker) than to silently point
            # it at another empty file slot.
            if not os.path.isfile(new_path):
                missing_after += 1
                self.stdout.write(self.style.WARNING(
                    f'  Skip {df.id} {df.filename}: target not on disk ({new_path})'
                ))
                continue

            self.stdout.write(
                f'  {df.id:>5}  {df.filename}\n'
                f'         - {df.file_path}\n'
                f'         + {new_path}'
            )
            updated += 1
            if not dry_run:
                DataFile.objects.filter(pk=df.pk).update(file_path=new_path)

        if dry_run:
            self.stdout.write(self.style.NOTICE(
                f'\n[dry-run] scanned {total} row(s); '
                f'would rewrite {updated}, leave {unchanged}, '
                f'skip {missing_after} (target missing on disk).'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nScanned {total} row(s) under {old_root!r}; '
                f'rewrote {updated}, left {unchanged}, '
                f'skipped {missing_after} (target missing on disk).'
            ))

        # 全站清空——**刻意不**跟着「删文件 / 移动文件」那条路改成定点淘汰。两条理由：
        # 1. 收益≈0：本命令的输入面就是「旧项目根之下的全部行」，迁移场景里那≈整个
        #    数据集，定点淘汰逐到的也就是几乎整只缓存；而它跑在带外（人工迁移/修路径），
        #    此刻没别人热着帧，全清的代价同样≈0。
        # 2. 判据成本 > 收益：三类分支的「动过」并不同形 —— 重写分支换了行（旧 key
        #    **通常**就此没人指向它，但那不是结构保证：file_path 上没有唯一约束，同一个
        #    坐标可以有别的行还在读 —— 判据见 test_parse_cache_scoped_invalidation.py
        #    ::SharedPhysicalPathTests；新 key 那侧本来就还没有条目）、skip 分支（target
        #    不在盘上）**行与盘都不动**、unchanged 分支压根没进 update。要定点就得逐分支
        #    算准集合，算漏的方向是白占预算（条目脏不了，理由同上那两条判据）；
        #    全清把三类一次性兜住，而代价只是「下一次读重解析」——带外没人付这个。
        # 顺带删掉旧注释那句失效论证（「否则会返回上一次坏路径的 ``(None, None, fmt)``」）：
        # 2026-10-25 载荷去重之后失败值根本不入缓存（``store_if=_parse_succeeded``）。
        # 如今真正挡脏的是键的内容坐标 ``(绝对路径, mtime_ns, 格式)``，这一步全清是保险带。
        # 反向判据（谁改成定点淘汰谁红）：
        #   test/backend/test_parse_cache_scoped_invalidation.py
        #     ::GlobalClearKeptForWholeTreeRewritesTests
        if updated and not dry_run:
            clear_parse_cache()
            self.stdout.write(self.style.SUCCESS('Cleared the in-process parse cache.'))
