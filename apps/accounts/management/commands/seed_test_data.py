"""
预植入 SampleData 目录下所有 CSV 文件到数据库。
运行方式: python manage.py seed_test_data [--clear] [--owner=admin]
"""
import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers.base import BaseATEParser
from apps.datafiles.parsers import get_parser

SAMPLE_DATA_DIR = os.path.join(settings.BASE_DIR, 'Data', 'SampleData')


def iter_csv_files(root: str):
    """递归遍历所有 CSV 文件（排除目录）"""
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith('.csv'):
                yield os.path.join(dirpath, fn)


class Command(BaseCommand):
    help = '将 Data/SampleData 下所有 CSV 文件预导入到 DataFile 表（开发/测试用）'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='先清空所有已注册文件（不包括 media 磁盘文件）')
        parser.add_argument('--refresh', action='store_true', help='增量刷新：清理 e2e_* 测试残留，仅处理变化的 SampleData 文件（e2e globalSetup 用）')
        parser.add_argument('--owner', default='admin', help='文件归属用户名（默认 admin）')

    @staticmethod
    def _media_file_unchanged(src_path: str, dest_path: str) -> bool:
        """media/uploads 目标与 SampleData 源文件一致（size + mtime 都相同）"""
        try:
            return (
                os.path.exists(dest_path)
                and os.path.getsize(dest_path) == os.path.getsize(src_path)
                and os.path.getmtime(dest_path) == os.path.getmtime(src_path)
            )
        except OSError:
            return False

    def _register_file(self, user, src_path: str, dest_path: str, datafile: DataFile | None) -> bool:
        """复制 + 解析 + 建/更新 DataFile 记录。返回 True 表示数据有变化。"""
        # 复制到 media/uploads（不依赖 SampleData 的绝对路径语义）
        shutil.copy2(src_path, dest_path)
        file_size = os.path.getsize(dest_path)

        # 识别格式 & 解析
        format_type = 'Unknown'
        program_name = ''
        row_count, col_count = 0, 0
        metadata = {}

        try:
            with open(dest_path, 'r', encoding='utf-8', errors='ignore') as f:
                head = f.read(4096)
            format_type = BaseATEParser.identify_format(head)

            if format_type != 'Unknown':
                parser = get_parser(format_type)
                df, meta = parser.parse(dest_path)
                if df is not None:
                    row_count = df.shape[0]
                    col_count = df.shape[1]
                    metadata = meta or {}
                    program_name = metadata.get('program_name', '')
        except Exception as e:
            self.stderr.write(f'  解析 {os.path.basename(dest_path)} 失败: {e}')

        if datafile is None:
            datafile = DataFile.objects.create(
                owner=user,
                filename=os.path.basename(src_path),
                file_path=dest_path,
                file_size=file_size,
                format_type=format_type if format_type != 'Unknown' else 'CTA8290D',
                row_count=row_count,
                col_count=col_count,
                program_name=program_name,
                metadata=metadata,
                status='ready' if format_type != 'Unknown' else 'error',
            )
        else:
            datafile.file_size = file_size
            datafile.format_type = format_type if format_type != 'Unknown' else 'CTA8290D'
            datafile.row_count = row_count
            datafile.col_count = col_count
            datafile.program_name = program_name
            datafile.metadata = metadata
            datafile.status = 'ready' if format_type != 'Unknown' else 'error'
            datafile.save(update_fields=['file_size', 'format_type', 'row_count', 'col_count',
                                         'program_name', 'metadata', 'status'])

        ParseHistory.objects.create(
            user=user,
            datafile=datafile,
            filename=datafile.filename,
            filepath=dest_path,
            format_type=datafile.format_type,
            rows=row_count,
            cols=col_count,
        )
        return datafile

    def handle(self, *args, **options):
        # Windows GBK 控制台兼容
        import sys
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

        username = options['owner']
        user = User.objects.filter(username=username).first()
        if not user:
            self.stderr.write(self.style.ERROR(f'用户 "{username}" 不存在，请先 seed_users'))
            return

        if options['clear']:
            deleted, _ = DataFile.objects.filter(owner=user).delete()
            self.stdout.write(self.style.WARNING(f'已清空 {deleted} 条 DataFile 记录'))

        upload_dir = os.path.join(settings.BASE_DIR, 'media', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)

        if options['refresh']:
            # 清理 e2e 测试上传残留（e2e_* 唯一前缀），保持与 --clear 相同的"干净列表"语义
            stale = DataFile.objects.filter(owner=user, filename__startswith='e2e_')
            for df in stale:
                try:
                    if os.path.exists(df.file_path):
                        os.unlink(df.file_path)
                except OSError:
                    pass
            deleted, _ = stale.delete()
            if deleted:
                self.stdout.write(self.style.WARNING(f'已清理 {deleted} 条 e2e 测试残留记录'))

        created = 0
        skipped = 0

        for src_path in iter_csv_files(SAMPLE_DATA_DIR):
            filename = os.path.basename(src_path)

            # 目标路径：media/uploads/<filename>，避免复制整棵 SampleData 树
            dest_path = os.path.join(upload_dir, filename)

            datafile = DataFile.objects.filter(
                owner=user, filename=filename, file_path=dest_path
            ).first()

            # 幂等快路径：记录存在且 media 文件与 SampleData 一致 → 跳过
            # （--clear 清掉记录后这里自然全部重建；SampleData 文件 mtime/size 变化则重解析）
            if datafile is not None and self._media_file_unchanged(src_path, dest_path):
                skipped += 1
                continue

            datafile = self._register_file(user, src_path, dest_path, datafile)
            created += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f'  [OK] {filename} -> '
                    f'{datafile.format_type} ({datafile.row_count}x{datafile.col_count})'
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n完成: 处理 {created} 个文件，跳过 {skipped} 个（已存在且未变化）'
            )
        )
