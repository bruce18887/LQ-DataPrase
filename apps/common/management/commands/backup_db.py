"""备份数据库与不可再生的伴生文件（三件套）。

    python manage.py backup_db                          # 备到 <BASE_DIR>/backups
    python manage.py backup_db --dest D:\\bak --keep 30  # 指定目录与保留份数

保留份数优先级：``--keep`` > 环境变量 ``LQDP_BACKUP_KEEP`` > 14。

为什么是这三样：``db.sqlite3`` 是唯一不可再生的事实源；``secret.key`` 派生 SFTP 存密
密钥（丢了就恢复出一个连不上数据源服务器的实例）；``system_config.json`` 记着 data_dir
指针。``media/`` 刻意**不备** —— 原始数据在另一台服务器上、且那边自带备份，本服务器的
media 只是缓存（2026-10-14 部署结论）。

备份走 ``VACUUM INTO`` 而不是复制文件：库跑在 WAL 下，未 checkpoint 的已提交帧只在
``-wal`` 侧文件里，复制主库文件会得到一个连表都没有的库（``test_backup_db.py`` 把这条
钉成了用例）。
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.common import backup
from apps.common.backup import BackupError
from apps.common.system_config import config_file_path


class Command(BaseCommand):
    help = '备份 SQLite 库 + secret.key + system_config.json，并校验备份可读'

    def add_arguments(self, parser):
        parser.add_argument('--dest', default=None,
                            help='备份目录，默认 <BASE_DIR>/backups（必须是本地盘，勿指网络盘）')
        parser.add_argument('--keep', default=None,
                            help='保留最近几份，默认 14（或 LQDP_BACKUP_KEEP）')

    def handle(self, *args, **options):
        db_name = str(settings.DATABASES['default']['NAME'])
        try:
            backup.check_backupable(db_name, connection.vendor)
        except BackupError as exc:
            raise CommandError(str(exc))

        # secret.key 与 system_config.json 都锚在「原始目录」，不随 data_dir 迁移 ——
        # 所以这里取 ANCHOR 而不是 BASE_DIR，否则改过存储路径的机器上会找不到 key。
        anchor = Path(getattr(settings, 'SYSTEM_CONFIG_ANCHOR_DIR', settings.BASE_DIR))
        cfg_file = config_file_path(anchor)
        dest_dir = Path(options['dest'] or (Path(settings.BASE_DIR) / 'backups'))
        keep = backup.resolve_keep(options['keep'] or os.environ.get('LQDP_BACKUP_KEEP'))

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CommandError(f'备份目录创建失败（{dest_dir}）：{exc}')

        stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        snapshot = backup.next_snapshot_path(dest_dir, stamp)

        # 密钥来源决定 secret.key 是不是必备伴生文件：桌面/打包档它是唯一副本，缺了要报错；
        # 服务器档（config.settings.server）要求 SECRET_KEY 由环境给定，压根没有这个文件。
        key_from_env = bool(os.environ.get('SECRET_KEY'))

        try:
            backup.vacuum_into(connection, snapshot)
            verdict = backup.verify_backup(snapshot)
            companions = backup.collect_companions(anchor, cfg_file, dest_dir,
                                                   secret_key_from_env=key_from_env)
            deleted = backup.rotate(dest_dir, keep)
        except (BackupError, sqlite3.Error, OSError) as exc:
            # 裸 sqlite3/OSError 也翻成 CommandError：管理员要的是一句话的原因，
            # 不是一屏 traceback（上一份备份此刻必然未被触碰）。
            raise CommandError(f'备份失败（上一份备份保持不动）：{exc}')

        self.stdout.write(self.style.SUCCESS(
            f'[backup] {verdict}  库快照={snapshot}（{snapshot.stat().st_size // 1024} KB）'))
        for path in companions:
            self.stdout.write(f'[backup] 伴生文件 {path.name} → {path}')
        if key_from_env and not (dest_dir / backup.SECRET_FILENAME).is_file():
            self.stdout.write(self.style.WARNING(
                '[backup] 未携带 secret.key：本次根密钥来自环境变量 SECRET_KEY。'
                '请把部署配置里的 SECRET_KEY 与 SFTP_CONFIG_KEY 一并纳入备份流程 —— '
                '库备份本身不含它们，缺任何一个都无法恢复出可用实例。'))
        self.stdout.write(f'[backup] 保留最近 {keep} 份，本次删除 {len(deleted)} 份')
        for path in deleted:
            self.stdout.write(f'[backup]   删 {path.name}')
