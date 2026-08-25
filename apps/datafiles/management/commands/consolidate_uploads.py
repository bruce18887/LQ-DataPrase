"""One-shot management command to consolidate the legacy flat
``media/uploads/`` layout into the per-user ``media/data/<username>/`` layout
(Storage Layout v2).

History: ``media/uploads/`` was the pre-2026-06-07 destination for seed
data and manual copies, and existing ``DataFile`` rows still point at it
(``fix_moved_project_paths.py`` re-rooted rows there when the project
moved). The current layout is ``media/data/<username>/<single|batch>/``;
this command moves the leftovers in, rewrites the DB rows (relativizing
them via ``store_file_path``), reports orphaned files that no row
references, and removes the directory when it empties out.

Order-independence: whether the migration-time DB rewrite already
relativized the rows (absolute → ``uploads/...``) or not, ``resolve_file_path``
normalizes both forms before the on-disk move, so the command converges
either way. Idempotent: re-running is a no-op once ``uploads/`` is gone.

Usage:
    python manage.py consolidate_uploads            # do it
    python manage.py consolidate_uploads --dry-run  # report only, no moves
"""
import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.services import clear_parse_cache
from apps.datafiles.utils import resolve_file_path, store_file_path
from apps.datafiles.views._helpers import _user_upload_dir


class Command(BaseCommand):
    help = (
        'Move files + rows from the legacy media/uploads/ layout into '
        'media/data/<username>/<file_type>/ and relativize file_path.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without touching the database or disk.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        uploads_dir = os.path.join(str(settings.MEDIA_ROOT), 'uploads')

        if not os.path.isdir(uploads_dir):
            self.stdout.write(self.style.NOTICE(
                f'media/uploads/ 不存在（{uploads_dir}）；无需迁移。'
            ))
            return

        stats = {
            'moved': 0, 'db_only': 0, 'conflicts': 0, 'orphans': 0,
            'source_removed': 0, 'parse_cache_cleared': False,
        }

        # --- 1. DB rows pointing under media/uploads/ ---
        # 全量迭代 + resolve 后判断：迁移重写前是绝对路径（C:\...\uploads\...），
        # 重写后是相对路径（uploads/...），两种形态都必须命中。
        rows = DataFile.objects.select_related('owner').iterator()
        for df in rows:
            abs_path = resolve_file_path(df.file_path)
            norm = os.path.normpath(abs_path)
            uploads_norm = os.path.normpath(uploads_dir)
            if not (norm == uploads_norm or norm.startswith(uploads_norm + os.sep)):
                continue  # 不在 uploads/ 之下（跨盘等），跳过

            # 目标目录：按 owner/file_type（batch 保留 batch_name 子目录）
            owner = df.owner
            if df.file_type == 'batch' and df.batch_name:
                target_dir = os.path.join(
                    _user_upload_dir(owner, 'batch'), df.batch_name
                )
            elif df.file_type == 'batch':
                target_dir = _user_upload_dir(owner, 'batch')
            else:
                target_dir = _user_upload_dir(owner, 'single')
            target = os.path.join(target_dir, os.path.basename(norm))
            stored = store_file_path(target)

            if not os.path.isfile(norm):
                self.stdout.write(self.style.WARNING(
                    f'  [{df.id}] 源文件缺失（仅更新 DB）：{df.filename}'
                ))
                self._update_rows(df, stored, dry_run)
                stats['db_only'] += 1
                continue

            # 目标已存在：同 size 视为已迁移（只改 DB 不复制不删源），否则冲突保留源
            if os.path.exists(target):
                if os.path.getsize(target) == os.path.getsize(norm):
                    if dry_run:
                        self.stdout.write(
                            f'  [{df.id}] {df.filename} -> {target}（已存在，仅更新 DB）'
                        )
                        stats['db_only'] += 1
                        continue
                    self._update_rows(df, stored, dry_run=False)
                    stats['db_only'] += 1
                    self.stdout.write(
                        f'  [{df.id}] {df.filename} -> {target}（已存在，仅更新 DB）'
                    )
                    continue
                self.stdout.write(self.style.WARNING(
                    f'  [{df.id}] 目标同名但大小不同，跳过（保留源）：{norm}'
                ))
                stats['conflicts'] += 1
                continue

            if dry_run:
                self.stdout.write(
                    f'  [{df.id}] {df.filename} -> {target}'
                )
                stats['moved'] += 1
                continue

            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(norm, target)
            if os.path.getsize(target) != os.path.getsize(norm):
                self.stdout.write(self.style.ERROR(
                    f'  [{df.id}] 复制校验失败（size 不一致），回滚保留源：{norm}'
                ))
                try:
                    os.remove(target)
                except OSError:
                    pass
                stats['conflicts'] += 1
                continue
            self._update_rows(df, stored, dry_run=False)
            try:
                os.remove(norm)
                stats['source_removed'] += 1
            except OSError:
                pass
            stats['moved'] += 1
            self.stdout.write(f'  [{df.id}] {df.filename} -> {target}')

        # --- 2. Orphaned files with no DB row (warn only) ---
        registered = {
            os.path.normpath(resolve_file_path(p)) for p in
            DataFile.objects.values_list('file_path', flat=True)
        }
        orphans = []
        for root, _dirs, files in os.walk(uploads_dir):
            for name in files:
                fp = os.path.normpath(os.path.join(root, name))
                if fp not in registered:
                    orphans.append(fp)
        if orphans:
            stats['orphans'] = len(orphans)
            self.stdout.write(self.style.WARNING(
                f'\n{len(orphans)} 个孤儿文件无 DataFile 记录（不删除，请人工确认）：'
            ))
            for fp in sorted(orphans)[:20]:
                self.stdout.write(f'    {fp}')
            if len(orphans) > 20:
                self.stdout.write(f'    … 等共 {len(orphans)} 个')

        # --- 3. Cleanup: empty dirs bottom-up; remove uploads/ if empty ---
        if not dry_run:
            for root, dirs, files in os.walk(uploads_dir, topdown=False):
                if not dirs and not files:
                    try:
                        os.rmdir(root)
                    except OSError:
                        pass
            if os.path.isdir(uploads_dir) and not os.listdir(uploads_dir):
                os.rmdir(uploads_dir)
                self.stdout.write(self.style.SUCCESS('media/uploads/ 已清空并删除。'))

        if stats['moved'] or stats['db_only']:
            if not dry_run:
                clear_parse_cache()
                stats['parse_cache_cleared'] = True

        if dry_run:
            self.stdout.write(self.style.NOTICE(
                f'\n[dry-run] 将迁移 {stats["moved"]} 个文件，'
                f'{stats["db_only"]} 条仅更新 DB，'
                f'{stats["conflicts"]} 个冲突跳过，'
                f'{stats["orphans"]} 个孤儿文件待人工确认。'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\n迁移完成：移动 {stats["moved"]} 个文件，'
                f'仅更新 DB {stats["db_only"]} 条，'
                f'冲突跳过 {stats["conflicts"]} 个，'
                f'孤儿文件 {stats["orphans"]} 个，'
                f'解析缓存已清空。'
            ))

    def _update_rows(self, df, stored_path: str, dry_run: bool) -> None:
        """Update DataFile.file_path + ParseHistory.filepath in one tx."""
        if dry_run:
            return
        with transaction.atomic():
            DataFile.objects.filter(pk=df.pk).update(file_path=stored_path)
            ParseHistory.objects.filter(datafile_id=df.pk).update(
                filepath=stored_path
            )
