"""SQLite 备份三件套：库快照 + ``secret.key`` + ``system_config.json``。

形状由 2026-10-14 的部署结论决定（``docs/specs/2026-10-14-server-deployment-first-run-design.md``）：
**只备库与两伴生文件，media 不备** —— 原始数据在另一台服务器上且自带备份，本服务器的
``media/`` 定性为可重取的缓存。三条硬事实对应下面三个函数：

* :func:`vacuum_into` —— WAL 下未 checkpoint 的提交帧只在 ``-wal`` 侧文件里，复制主库
  文件会得到「连表都没有」的库。所以必须 ``VACUUM INTO``，且走 **Django 连接**：
  pragma 接收器挂在 ``connection_created`` 上，裸 ``sqlite3.connect`` 拿不到放宽的
  busy_timeout（``docs/tasks/todo.md:2769-2771`` 已记该边界）。参数只要求「有
  ``cursor()`` 的连接」，生产传 ``django.db.connection``。
* :func:`verify_backup` —— 备份只有被验证过才算存在；用只读连接打
  ``PRAGMA integrity_check``（同 ``system_config._verify_sqlite`` 的判据）。
* :func:`collect_companions` —— ``secret.key`` **不在 data_dir 里**
  （``config/settings/standalone.py:50-56`` 刻意把它与配置文件锚在原目录），整目录
  拷贝式备份恰好会漏掉它；而它派生 SFTP 存密 key，缺了恢复出来的实例连不上源服务器。
  所以缺 ``secret.key`` 是**报错**，不是静默跳过。

本模块不 import Django，好让上面三条都能拿真实 SQLite 文件直接测。
"""

import os
import shutil
import sqlite3
from pathlib import Path

BACKUP_PREFIX = 'lqdp-'
BACKUP_SUFFIX = '.sqlite3'
SECRET_FILENAME = 'secret.key'
CONFIG_FILENAME = 'system_config.json'

#: 保留最近几份。0/负数/坏值一律回落到它 —— 那否则等于把用户的备份全删了。
DEFAULT_KEEP = 14


class BackupError(Exception):
    """备份链路上的可预期失败；调用方（管理命令）翻成 CommandError。"""


def resolve_keep(value) -> int:
    """把 ``--keep`` / ``LQDP_BACKUP_KEEP`` 解析成 >=1 的整数，坏值回落默认。"""
    try:
        keep = int(value)
    except (TypeError, ValueError):
        return DEFAULT_KEEP
    return keep if keep >= 1 else DEFAULT_KEEP


def check_backupable(db_name: str, vendor: str) -> None:
    """只备份文件型的 SQLite 库。

    ``:memory:`` 是测试运行器用的库，对它 ``VACUUM INTO`` 没有意义（且会失败）；
    非 SQLite 档（Postgres）由外部工具负责，不在本命令射程内。
    """
    if vendor != 'sqlite':
        raise BackupError(
            f'本命令只支持 SQLite 文件库，当前 vendor={vendor!r}。'
            'PostgreSQL 请用 pg_dump，MySQL 请用 mysqldump。')
    if not db_name or str(db_name).startswith(':memory:'):
        raise BackupError(f'内存库（{db_name!r}）无可备份内容，需指向真实库文件。')


def vacuum_into(connection, dest: Path) -> Path:
    """用 ``VACUUM INTO`` 生成一致性快照，落盘是「写临时名 + rename」的原子动作。

    ``VACUUM INTO`` 拒绝已存在的目标文件，所以先写 ``<dest>.tmp`` 再改名；中途失败不会
    留下半份备份顶掉上一份，失败时临时文件会被清掉（否则会一天堆一个，且轮转看不见它们）。

    占位符写 ``%s`` 而不是 ``?``：Django 的原生 SQL 一律用 ``%s``，由各后端翻译成自己的
    形式。写 ``?`` 会在 DEBUG 档炸于 ``last_executed_query`` 的 ``sql % params``
    （2026-10-14 实跑抓到：``TypeError: not all arguments converted``）。
    """
    dest = Path(dest)
    tmp = dest.parent / (dest.name + '.tmp')
    if tmp.exists():
        tmp.unlink()
    try:
        with connection.cursor() as cursor:
            cursor.execute('VACUUM INTO %s', [str(tmp).replace('\\', '/')])
        os.replace(tmp, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def verify_backup(path: Path) -> str:
    """只读打开备份文件跑 ``PRAGMA integrity_check``，非 ``ok`` 即失败。"""
    path = Path(path)
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f'备份文件无法打开（{path}）：{exc}') from exc
    try:
        row = conn.execute('PRAGMA integrity_check').fetchone()
    except sqlite3.Error as exc:
        raise BackupError(f'备份文件校验出错（{path}）：{exc}') from exc
    finally:
        conn.close()
    if not row or row[0] != 'ok':
        raise BackupError(
            f'备份未通过 integrity_check（结果={row[0] if row else "unknown"}）：{path}')
    return 'ok'


def collect_companions(anchor_dir: Path, config_file: Path, dest_dir: Path) -> list[Path]:
    """把两样不可再生的伴生文件复制到备份目录。

    ``secret.key`` 缺失必须报错；``system_config.json`` 可以不存在（默认安装就没配
    data_dir），此时只带 key。
    """
    dest_dir = Path(dest_dir)
    secret = Path(anchor_dir) / SECRET_FILENAME
    if not secret.is_file():
        raise BackupError(
            f'找不到 {secret}。它是 SFTP 存密密钥的派生来源（见 standalone 档的 PBKDF2），'
            '缺了它恢复出来的实例连不上数据源服务器，因此不允许只备库就宣布成功。')

    copied = []
    shutil.copy2(secret, dest_dir / SECRET_FILENAME)
    copied.append(dest_dir / SECRET_FILENAME)

    config_file = Path(config_file)
    if config_file.is_file():
        shutil.copy2(config_file, dest_dir / CONFIG_FILENAME)
        copied.append(dest_dir / CONFIG_FILENAME)
    return copied


def next_snapshot_path(backup_dir: Path, stamp: str) -> Path:
    """给这一轮的快照挑一个**没被占用**的文件名。

    名字精确到秒，cron 与人工撞上、或一小时里跑多次都可能出现同一秒。
    直接写同名文件 = 静默吃掉上一份备份，而「以为有两份其实只有一份」是备份最坏的失败，
    所以这里让位（``-1``/``-2``…），不覆盖。让出来的名字仍属 ``lqdp-*.sqlite3``，轮转认得。
    """
    backup_dir = Path(backup_dir)
    candidate = backup_dir / f'{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}'
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = backup_dir / f'{BACKUP_PREFIX}{stamp}-{suffix}{BACKUP_SUFFIX}'
    return candidate


def list_backups(backup_dir: Path) -> list[Path]:
    """按生成时间排序（最旧在前）的备份文件，忽略 ``.tmp`` 与外来文件。"""
    files = [p for p in Path(backup_dir).glob(BACKUP_PREFIX + '*' + BACKUP_SUFFIX)
             if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def rotate(backup_dir: Path, keep: int) -> list[Path]:
    """只保留最近 ``keep`` 份，返回被删掉的路径。非 ``lqdp-*.sqlite3`` 一律不碰。"""
    backups = list_backups(backup_dir)
    if keep >= len(backups):
        return []
    deleted = []
    for path in backups[:len(backups) - keep]:
        path.unlink()
        deleted.append(path)
    return deleted
