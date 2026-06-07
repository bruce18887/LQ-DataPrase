"""One-shot management command to backfill ``DataFile.product_code`` using
the current ``extract_product_code`` logic.

Use after changing the extraction rules so existing rows pick up the new
product code without having to delete + re-upload the data files.

Usage:
    python manage.py backfill_product_code            # do it
    python manage.py backfill_product_code --dry-run  # report only, no writes
"""
from django.core.management.base import BaseCommand

from apps.datafiles.models import DataFile
from apps.datafiles.utils import extract_product_code


class Command(BaseCommand):
    help = (
        'Recompute DataFile.product_code for every row using '
        'extract_product_code(filename, program_name).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only print what would change; do not write to the DB.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verb = 'Would update' if dry_run else 'Updated'

        changed = 0
        unchanged = 0
        empty = 0
        for df in DataFile.objects.all().iterator():
            new_code = extract_product_code(df.filename, df.program_name or '')
            if not new_code:
                empty += 1
                self.stdout.write(
                    f'  [empty] id={df.id} filename={df.filename!r} '
                    f'program_name={df.program_name!r}'
                )
                continue
            if df.product_code == new_code:
                unchanged += 1
                continue
            self.stdout.write(
                f'  {verb} id={df.id} filename={df.filename!r}: '
                f'{df.product_code!r} -> {new_code!r}'
            )
            if not dry_run:
                df.product_code = new_code
                df.save(update_fields=['product_code'])
            changed += 1

        self.stdout.write(self.style.SUCCESS(
            f'Backfill summary: changed={changed} unchanged={unchanged} '
            f'empty_source={empty} dry_run={dry_run}'
        ))
