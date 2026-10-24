"""部署整改批 2：SQLite 备份三件套（库 + secret.key + system_config.json）。

判据来自 2026-10-14 的部署结论：**只备库与两伴生文件，media 不备**（原始数据在另一台
服务器上且自带备份，本服务器 media 定性为缓存）。三条硬事实决定了这里的形状：

1. WAL 下未 checkpoint 的提交帧只在 ``-wal`` 侧文件里 —— 复制主库文件会拿到不完整库。
   故必须 ``VACUUM INTO``，且本文件用「子进程 ``os._exit`` 留下未 checkpoint 的 -wal」
   把这条钉住（手法沿用 ``test_sqlite_wal.py``，只在临时目录里做，不碰任何真实库）。
2. 走 **Django 连接**而非裸 ``sqlite3.connect``：pragma 接收器挂在 ``connection_created``
   上，裸连接拿不到放宽的 busy_timeout（``docs/tasks/todo.md:2769-2771`` 已记该边界）。
   因此被测函数只接受「有 ``cursor()`` 的连接」，生产传 ``django.db.connection``。
3. ``secret.key`` **不在 data_dir 里**（``config/settings/standalone.py:55-56`` 刻意锚在
   原目录）。整目录拷贝式备份恰好会漏掉它，而它派生 SFTP 存密 key —— 缺了必须报错，
   不允许静默跳过。

运行：``manage.py test test.backend.test_backup_db``
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# test/backend/ → 项目根
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.common.backup import (  # noqa: E402
    BackupError,
    check_backupable,
    collect_companions,
    list_backups,
    resolve_keep,
    rotate,
    vacuum_into,
    verify_backup,
)

# 子进程写 2000 行并提交，但关掉自动 checkpoint、再用 os._exit 跳过清理
# —— 提交帧因此确定性地留在 -wal 里，主库文件不含它们（见 subprocess_run_with_exit）。


class CursorAdapter:
    """镜像 Django ``CursorWrapper`` 的接口形状：它**支持**上下文管理器协议。

    生产传的是 ``django.db.connection``，被测代码用 ``with connection.cursor()`` ——
    裸 ``sqlite3.Cursor`` 不支持该协议，所以测试侧包一层，被验证的仍是同一条 SQL
    在真实 SQLite 文件上的结果。
    """

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        # Django 的原生 SQL 用 ``%s``，后端再翻译成各自的形式；这里直连裸 sqlite3，
        # 所以适配器替它做这一步翻译（被测代码保持 Django  idiomatic 的 ``%s``）。
        return self._cursor.execute(sql.replace('%s', '?'), params)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._cursor.close()
        return False


class ConnectionAdapter:
    """只提供 ``cursor()`` —— 被测函数依赖的是 DB-API 形状，不是 Django 专有接口。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def cursor(self):
        return CursorAdapter(self._conn.cursor())


class VendorAndSourceGuardTests(SimpleTestCase):
    """非 SQLite、或库是内存库时必须拒执，不能半路抛裸 sqlite3 错误。"""

    def test_sqlite_passes(self):
        check_backupable(str(Path('/x/db.sqlite3')), 'sqlite')

    def test_postgres_rejected(self):
        with self.assertRaises(BackupError):
            check_backupable('/tmp/whatever.sqlite3', 'postgresql')

    def test_in_memory_db_rejected(self):
        """VACUUM INTO 对 ``:memory:`` 无意义（测试运行器用的正是它）。"""
        with self.assertRaises(BackupError):
            check_backupable(':memory:', 'sqlite')


class ResolveKeepTests(SimpleTestCase):
    def test_default_is_14(self):
        self.assertEqual(resolve_keep(None), 14)

    def test_env_override_parsed(self):
        self.assertEqual(resolve_keep('3'), 3)

    def test_garbage_falls_back_to_default(self):
        """坏值不能变成「保留 0 份」—— 那等于把用户备份全删了。"""
        self.assertEqual(resolve_keep('abc'), 14)
        self.assertEqual(resolve_keep('0'), 14)
        self.assertEqual(resolve_keep('-5'), 14)


class VacuumIntoTests(SimpleTestCase):
    """核心命题：未 checkpoint 的提交帧必须进得了备份，而裸复制主库文件做不到。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='backup_db_test_'))
        self.db = self.tmp / 'db.sqlite3'
        sqlite3.connect(self.db).close()
        subprocess_run_with_exit(self.db)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_side_wal_exists_before_backup(self):
        """前提自证：-wal 里确实有没进主库文件的已提交数据。"""
        self.assertTrue((self.tmp / 'db.sqlite3-wal').is_file(), '夹具应留下 -wal 侧文件')

    def test_vacuum_into_recovers_committed_rows_from_wal(self):
        out = self.tmp / 'lqdp-test.sqlite3'
        conn = sqlite3.connect(str(self.db))
        try:
            vacuum_into(ConnectionAdapter(conn), out)
        finally:
            conn.close()
        self.assertEqual(verify_backup(out), 'ok')
        check = sqlite3.connect(f'file:{out}?mode=ro', uri=True)
        try:
            self.assertEqual(check.execute('SELECT COUNT(*) FROM t').fetchone()[0], 2000)
        finally:
            check.close()

    def test_naive_file_copy_yields_an_unusable_db(self):
        """反证「为什么不能用 cp」：只拷主库文件，连表定义都还在 -wal 里。

        子进程把 DDL 与 2000 行放在同一个提交里，所以主库文件只有一个合法但空的头
        —— 裸复制得到的是「打不开业务表」的库。只在临时目录的合成库上比较，
        不读也不写任何真实数据目录。
        """
        import shutil
        naive = self.tmp / 'naive-copy.sqlite3'
        shutil.copyfile(self.db, naive)
        conn = sqlite3.connect(f'file:{naive}?mode=ro', uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('SELECT COUNT(*) FROM t').fetchone()
        finally:
            conn.close()


class VerifyBackupTests(SimpleTestCase):
    def test_good_file_returns_ok(self):
        p = self._make_db()
        self.assertEqual(verify_backup(p), 'ok')

    def test_garbage_file_raises(self):
        p = self._make_garbage()
        with self.assertRaises(BackupError):
            verify_backup(p)

    def _make_db(self):
        fd, path = tempfile.mkstemp(prefix='lqdp-good-', suffix='.sqlite3')
        os.close(fd)
        self.addCleanup(os.unlink, path)
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO t VALUES (1)')
        conn.commit()
        conn.close()
        return Path(path)

    def _make_garbage(self):
        fd, path = tempfile.mkstemp(prefix='lqdp-bad-', suffix='.sqlite3')
        with os.fdopen(fd, 'wb') as fh:
            fh.write(b'not a sqlite file at all' * 40)
        self.addCleanup(os.unlink, path)
        return Path(path)


class CompanionFilesTests(SimpleTestCase):
    """三件套齐备才算备份；缺 secret.key 必须报错而不是「只备了库」。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='backup_companions_'))
        self.anchor = self.tmp / 'anchor'
        self.dest = self.tmp / 'backups'
        self.anchor.mkdir()
        self.dest.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_companions(self):
        (self.anchor / 'secret.key').write_text('django-secret-material', encoding='utf-8')
        cfg = self.tmp / 'system_config.json'
        cfg.write_text(json.dumps({'data_dir': str(self.anchor)}), encoding='utf-8')
        return cfg

    def test_trio_collected(self):
        cfg = self._write_companions()
        got = collect_companions(self.anchor, cfg, self.dest)
        names = sorted(p.name for p in got)
        self.assertEqual(names, ['secret.key', 'system_config.json'])
        self.assertEqual(
            (self.dest / 'secret.key').read_text(encoding='utf-8'), 'django-secret-material')

    def test_missing_secret_key_raises(self):
        cfg = self._write_companions()
        (self.anchor / 'secret.key').unlink()
        with self.assertRaises(BackupError):
            collect_companions(self.anchor, cfg, self.dest)

    def test_missing_config_file_is_ok(self):
        """system_config.json 可以不存在（默认路径下本就没有），但 secret.key 不行。"""
        (self.anchor / 'secret.key').write_text('k', encoding='utf-8')
        got = collect_companions(self.anchor, self.tmp / 'absent.json', self.dest)
        self.assertEqual([p.name for p in got], ['secret.key'])


class CompanionKeySourceTests(SimpleTestCase):
    """服务器档下密钥本来就来环境变量、没有 secret.key 文件 —— 此时不许把备份判成失败。

    实测踩过：`backup_db` 在 `config.settings.server` 下 CommandError
    「找不到 …/secret.key」，也就是它唯一跑不动的形态恰恰是它被写出来要服务的那个。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='backup_keysource_'))
        self.anchor = self.tmp / 'anchor'
        self.dest = self.tmp / 'backups'
        self.anchor.mkdir()
        self.dest.mkdir()
        self.addCleanup(shutil_rmtree, self.tmp)

    def test_env_sourced_key_without_file_does_not_raise(self):
        got = collect_companions(self.anchor, self.tmp / 'absent.json', self.dest,
                                 secret_key_from_env=True)
        self.assertEqual(got, [], '环境给密钥时没有文件可带，应返回空清单而不是报错')

    def test_env_sourced_key_still_copies_file_if_present(self):
        """有文件就照带（多一道保险），但缺了不算失败。"""
        (self.anchor / 'secret.key').write_text('material', encoding='utf-8')
        got = collect_companions(self.anchor, self.tmp / 'absent.json', self.dest,
                                 secret_key_from_env=True)
        self.assertEqual([p.name for p in got], ['secret.key'])

    def test_file_sourced_key_is_still_mandatory(self):
        """默认（桌面/打包档）语义不变：缺文件必须报错，否则恢复出来的根密钥对不上。"""
        with self.assertRaises(BackupError):
            collect_companions(self.anchor, self.tmp / 'absent.json', self.dest)


class RotateTests(SimpleTestCase):
    def test_keeps_newest_n_and_ignores_foreign_files(self):
        tmp = Path(tempfile.mkdtemp(prefix='backup_rotate_'))
        self.addCleanup(shutil_rmtree, tmp)
        for i in range(1, 16):
            p = tmp / f'lqdp-2026101{i:02d}000000.sqlite3'
            p.write_text('x', encoding='utf-8')
            os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        keep_me = tmp / 'README.md'
        keep_me.write_text('not a backup', encoding='utf-8')

        deleted = rotate(tmp, keep=14)

        self.assertEqual(len(deleted), 1)
        self.assertEqual(deleted[0].name, 'lqdp-202610101000000.sqlite3')  # i=1，最旧的一份
        remaining = sorted(p.name for p in tmp.glob('lqdp-*.sqlite3'))
        self.assertEqual(len(remaining), 14)
        self.assertTrue(keep_me.is_file(), '轮转不得动非备份文件')

    def test_keep_larger_than_count_deletes_nothing(self):
        tmp = Path(tempfile.mkdtemp(prefix='backup_rotate2_'))
        self.addCleanup(shutil_rmtree, tmp)
        (tmp / 'lqdp-a.sqlite3').write_text('x', encoding='utf-8')
        self.assertEqual(rotate(tmp, keep=14), [])


def subprocess_run_with_exit(db_path: Path) -> None:
    """跑子进程写库并用 os._exit 收尾，留下未 checkpoint 的 -wal。

    刻意**不调** ``close()``：关连接会 checkpoint 并删掉 -wal，夹具就没意义了。
    """
    import subprocess
    code = 'import os,sqlite3,sys;c=sqlite3.connect(sys.argv[1]);' \
           "c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA wal_autocheckpoint=0');" \
           'c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)");' \
           "c.executemany('INSERT INTO t (v) VALUES (?)',[('row-%d'%i,) for i in range(2000)]);" \
           'c.commit();os._exit(7)'
    # 退出码 7 是**故意的**：os._exit 跳过 SQLite 的关闭清理，已提交帧才会留在 -wal 里。
    # 所以不能用 check=True —— 那等于把这个夹具判成失败。
    result = subprocess.run([sys.executable, '-c', code, str(db_path)])
    if result.returncode != 7:
        raise AssertionError(f'子进程未按预期以 7 退出（实得 {result.returncode}）')


def shutil_rmtree(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class SnapshotNamingTests(SimpleTestCase):
    """快照名只精确到秒 —— 同一秒跑两次（cron 与人工撞上）会**静默覆盖掉一份备份**。

    备份最怕的不是失败出声，而是以为有两份其实只有一份，所以撞名必须避让而不是覆盖。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='backup_naming_'))
        self.addCleanup(shutil_rmtree, self.tmp)

    def test_first_name_is_plain_stamp(self):
        from apps.common.backup import next_snapshot_path
        got = next_snapshot_path(self.tmp, '20261014043256')
        self.assertEqual(got.name, 'lqdp-20261014043256.sqlite3')
        self.assertEqual(len(next_snapshot_path(self.tmp, '20261014043257').name),
                         len('lqdp-20261014043257.sqlite3'))

    def test_taken_name_gets_a_suffix_instead_of_overwriting(self):
        from apps.common.backup import next_snapshot_path
        first = next_snapshot_path(self.tmp, '20261014043256')
        first.write_text('real-backup', encoding='utf-8')

        second = next_snapshot_path(self.tmp, '20261014043256')
        self.assertNotEqual(second, first, '同秒必须让开，不能指向同一文件')
        self.assertEqual(second.name, 'lqdp-20261014043256-1.sqlite3')
        self.assertEqual(first.read_text(encoding='utf-8'), 'real-backup', '已有那份不得被动过')

        # 再撞一次继续让位（先把上一份让出来的名字真的占住），
        # 且轮转仍然认得这些文件（同属 lqdp-*.sqlite3 模式）
        second.write_text('second', encoding='utf-8')
        third = next_snapshot_path(self.tmp, '20261014043256')
        self.assertEqual(third.name, 'lqdp-20261014043256-2.sqlite3')
        third.write_text('x', encoding='utf-8')
        self.assertEqual(len(list_backups(self.tmp)), 3)


if __name__ == '__main__':
    from django.conf import settings as dj_settings
    from django.test.utils import get_runner

    runner = get_runner(dj_settings)(['test.backend.test_backup_db'], verbosity=2)
    sys.exit(runner.run_tests())
