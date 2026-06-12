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

        # Bust the in-process parse cache so the next /analysis/* call
        # re-reads the new file_path instead of returning a cached
        # ``(None, None, fmt)`` tuple from the previous (broken) path.
        if updated and not dry_run:
            clear_parse_cache()
            self.stdout.write(self.style.SUCCESS('Cleared the in-process parse cache.'))
