"""One-shot management command to migrate user upload directories from the
historical ``media/data/<user_id>/<file_type>/`` layout to the new
``media/data/<username>/<file_type>/`` layout introduced after 2026-06-07.

The earlier session on 2026-06-06 recorded the change in project memory but
the code change was lost on disk, leaving behind a hybrid state: some
DataFile rows already point at the username path (e.g. files downloaded via
SFTP while the refactor was being drafted), and others still point at the
old id-based path. This command rewrites the stale ones in place so the
filesystem and the database match.

Usage:
    python manage.py migrate_user_paths            # do it
    python manage.py migrate_user_paths --dry-run  # report only, no moves
"""
import os
import re
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.datafiles.models import DataFile


# Match ``\data\<id>\<file_type>\`` (or ``/data/<id>/<file_type>/``) where
# the segment between ``data`` and the file-type is purely digits.  Strict
# enough to avoid mis-identifying a username that happens to be all digits
# ("123") while still catching every historical id-based record.
_ID_SEGMENT_RE = re.compile(
    r'(?P<prefix>[/\\]data[/\\])(?P<id>\d+)(?P<suffix>[/\\](?:single|batch)([/\\]))'
)


def _merge_tree(src_root: str, dst_root: str) -> tuple[int, int, list[str]]:
    """Recursively move everything under ``src_root`` into ``dst_root``.

    * Files: moved with ``shutil.move``; if a same-named file already exists
      in ``dst_root`` it is reported as a conflict and left in place.
    * Directories: created if missing, recursed into.
    * Symlinks (rare): not handled specially — ``shutil.move`` will preserve
      them.

    Returns ``(moved, conflicts, conflict_paths)``.
    """
    moved = 0
    conflicts: list[str] = []
    for root, dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        target_dir = os.path.join(dst_root, rel) if rel != '.' else dst_root
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            src = os.path.join(root, name)
            dst = os.path.join(target_dir, name)
            if os.path.exists(dst):
                conflicts.append(src)
                continue
            shutil.move(src, dst)
            moved += 1
    return moved, len(conflicts), conflicts


class Command(BaseCommand):
    help = (
        'Rewrite DataFile.file_path and on-disk directory from '
        'media/data/<id>/<file_type>/ to media/data/<username>/<file_type>/.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without touching the database or disk.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        media_root = str(settings.MEDIA_ROOT)
        data_root = os.path.join(media_root, 'data')

        if not os.path.isdir(data_root):
            self.stdout.write(self.style.WARNING(
                f'No media/data directory at {data_root!r}; nothing to migrate.'
            ))
            return

        # Build a quick id→username map so we can resolve any number under
        # media/data/ to its rightful owner without iterating every record.
        id_to_username: dict[int, str] = {}
        for username, user_id in (
            DataFile.objects.values_list('owner__username', 'owner_id').distinct()
        ):
            id_to_username.setdefault(user_id, username)

        stats = {
            'records': 0, 'files_moved': 0, 'dirs_renamed': 0,
            'merge_moved': 0, 'conflicts': 0, 'skipped_missing_user': 0,
        }

        # --- 1. Disk: rename <id>/<file_type>/ to <username>/<file_type>/ ---
        for entry in os.scandir(data_root):
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            user_id = int(entry.name)
            username = id_to_username.get(user_id)
            if not username:
                self.stdout.write(self.style.WARNING(
                    f'  Skip disk dir {entry.path}: no user with id={user_id}'
                ))
                stats['skipped_missing_user'] += 1
                continue

            target_dir = os.path.join(data_root, username)
            if os.path.isdir(target_dir):
                # Merge file-by-file rather than refusing the rename. This
                # is the common case: the username dir was already created
                # by a SFTP download while some manual-upload files still
                # live under the legacy id dir.
                if dry_run:
                    file_count = sum(
                        len(files) for _r, _d, files in os.walk(entry.path)
                    )
                    self.stdout.write(
                        f'  [dry-run] merge {entry.path} -> {target_dir} '
                        f'({file_count} file(s))'
                    )
                    continue
                moved, conflicts, conflict_paths = _merge_tree(entry.path, target_dir)
                stats['merge_moved'] += moved
                stats['conflicts'] += conflicts
                for p in conflict_paths:
                    self.stdout.write(self.style.WARNING(f'  Conflict (kept in place): {p}'))
                # Best-effort cleanup of the (now empty) id dir.
                try:
                    os.rmdir(entry.path)
                except OSError:
                    pass
            else:
                if dry_run:
                    self.stdout.write(f'  [dry-run] rename {entry.path} -> {target_dir}')
                else:
                    os.rename(entry.path, target_dir)
                    stats['dirs_renamed'] += 1

        # --- 2. DB: rewrite DataFile.file_path from <id>/<file_type>/ to <username>/<file_type>/ ---
        # Only touch rows whose file_path still contains the legacy id segment.
        candidates = DataFile.objects.filter(
            file_path__regex=r'[/\\]data[/\\]\d+[/\\](?:single|batch)[/\\]'
        )
        for df in candidates.iterator():
            owner_username = df.owner.username if df.owner_id else None
            if not owner_username:
                stats['skipped_missing_user'] += 1
                continue
            new_path = _ID_SEGMENT_RE.sub(
                lambda m: f"{m.group('prefix')}{owner_username}{m.group('suffix')}",
                df.file_path,
            )
            if new_path == df.file_path:
                continue
            self.stdout.write(
                f'  {df.id:>4}  {df.filename}  -> ...{os.sep}data{os.sep}'
                f'{owner_username}{os.sep}...'
            )
            stats['records'] += 1
            if not dry_run:
                # Use update() to skip auto_now bookkeeping on updated_at
                # and avoid the cached-owner issue inside a transaction.
                DataFile.objects.filter(pk=df.pk).update(file_path=new_path)

        # --- 3. DB: confirm the rewritten paths actually point at a file ---
        if not dry_run:
            present = sum(
                1 for p in DataFile.objects.values_list('file_path', flat=True)
                if os.path.isfile(p)
            )
            stats['files_moved'] = present

        if dry_run:
            self.stdout.write(self.style.NOTICE(
                f'\n[dry-run] would rewrite {stats["records"]} record(s); '
                f'rename or merge disk dirs above.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nRewrote {stats["records"]} record(s); '
                f'renamed {stats["dirs_renamed"]} dir(s), '
                f'merged {stats["merge_moved"]} file(s) '
                f'with {stats["conflicts"]} conflict(s); '
                f'confirmed {stats["files_moved"]} file(s) on disk.'
            ))

        if stats['skipped_missing_user']:
            self.stdout.write(self.style.WARNING(
                f'Skipped {stats["skipped_missing_user"]} record(s)/dir(s) '
                'with no matching user.'
            ))
