"""批1 服务器形态调优回归：SQLite WAL + busy_timeout + 带 -wal 的目录迁移。

背景（2026-10-13 部署评估）：运行形态收敛为「单进程 + 约 20 人共用一个 SQLite 库」，
而实测当前库跑在 ``journal_mode=delete``（回滚日志）——写会整库挡读，Django 默认
busy_timeout 只有 5 秒，20 人并发下先撞 ``database is locked``。

判据走 ``connection_created`` 信号本身：pragma 只有在信号链路上打出去，服务器形态
里才真的生效。连接用真实 ``sqlite3`` 文件库，只把 Django 的接口形状（``vendor`` +
``cursor()``）包一层适配器——被验证的行为仍是 SQLite 的真实 pragma 结果。

运行：``manage.py test test.backend.test_sqlite_wal``
"""

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from django.db.backends.signals import connection_created
from django.test import SimpleTestCase

from apps.common import system_config

EXPECTED_BUSY_TIMEOUT_MS = 30000

# 子进程故意用 os._exit 收尾：跳过 sqlite3 的连接清理，让已提交的帧留在 -wal 里，
# 复现「进程崩溃/被强杀后 -wal 未 checkpoint」这一真实开机状态。
_CHILD_WRITE_WITHOUT_CHECKPOINT = r"""
import os
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
conn.execute("INSERT INTO t VALUES (1, 'committed-in-wal')")
conn.commit()
os._exit(7)
"""


class _CursorAdapter:
    """Django 的 cursor 是上下文管理器；sqlite3 原生不是，这里只补这一个形状。"""

    def __init__(self, raw):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._raw.close()
        return False

    def execute(self, sql, params=None):
        return self._raw.execute(sql) if params is None else self._raw.execute(sql, params)

    def fetchone(self):
        return self._raw.fetchone()


class _ConnectionAdapter:
    """只暴露 Django 接收器会读到的两个成员：``vendor`` 与 ``cursor()``。"""

    def __init__(self, raw, vendor='sqlite'):
        self._raw = raw
        self.vendor = vendor

    def cursor(self):
        return _CursorAdapter(self._raw.cursor())


def _pragma(raw, statement):
    return raw.execute(statement).fetchone()[0]


class SqliteConnectionPragmaTests(SimpleTestCase):
    """``connection_created`` 必须把 WAL + 放宽的 busy_timeout 打到每个新连接上。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _fire(self, raw, vendor='sqlite'):
        connection_created.send(sender=object(), connection=_ConnectionAdapter(raw, vendor))

    def test_file_backed_connection_gets_wal_and_busy_timeout(self):
        db = Path(self._tmp.name) / 'probe.sqlite3'
        raw = sqlite3.connect(str(db))
        self.addCleanup(raw.close)
        # 前置：裸连接默认既不是 WAL 也没放宽超时，否则本例空过
        self.assertEqual(_pragma(raw, 'PRAGMA journal_mode').lower(), 'delete')
        self.assertEqual(int(_pragma(raw, 'PRAGMA busy_timeout')), 5000)

        self._fire(raw)

        self.assertEqual(_pragma(raw, 'PRAGMA journal_mode').lower(), 'wal')
        self.assertGreaterEqual(int(_pragma(raw, 'PRAGMA busy_timeout')),
                                EXPECTED_BUSY_TIMEOUT_MS)

    def test_memory_connection_does_not_break(self):
        # :memory: 不支持 WAL（测试运行器用的就是它）：必须原样回 'memory' 且不抛。
        raw = sqlite3.connect(':memory:')
        self.addCleanup(raw.close)

        self._fire(raw)

        self.assertEqual(_pragma(raw, 'PRAGMA journal_mode').lower(), 'memory')
        self.assertGreaterEqual(int(_pragma(raw, 'PRAGMA busy_timeout')),
                                EXPECTED_BUSY_TIMEOUT_MS)

    def test_non_sqlite_vendor_is_skipped(self):
        # 别把 SQLite 的 pragma 打进 Postgres 连接。
        raw = sqlite3.connect(':memory:')
        self.addCleanup(raw.close)

        self._fire(raw, vendor='postgresql')

        self.assertEqual(int(_pragma(raw, 'PRAGMA busy_timeout')), 5000)


class MigrateWithLeftoverWalTests(SimpleTestCase):
    """崩溃残留 -wal 的源库迁移后，目标库必须可读且完整性通过。

    打开 WAL 之后，「主库 + 旁路文件」不再是一个自包含的整体：``_migrate`` 逐个
    ``copy2`` 三件套是非原子的，而 ``_verify_sqlite`` 用 ``mode=ro`` 打开副本——
    只读打开一个仍需恢复的 WAL 库是会失败的。这两条把行为钉住，防止 WAL 一开
    就把数据目录迁移链路变成静默丢数据。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._root = Path(self._tmp.name)
        self._src = self._root / 'anchor'
        self._dst = self._root / 'data'
        self._src.mkdir()
        self._dst.mkdir()

    def _make_db_with_leftover_wal(self) -> None:
        db = self._src / 'db.sqlite3'
        subprocess.run([sys.executable, '-c', _CHILD_WRITE_WITHOUT_CHECKPOINT, str(db)],
                       check=False)
        wal = self._src / 'db.sqlite3-wal'
        self.assertTrue(wal.is_file() and wal.stat().st_size > 0,
                        '前置条件不成立：没有复现出残留 -wal，本例会空过')

    def test_migrate_preserves_committed_rows_and_integrity(self):
        self._make_db_with_leftover_wal()
        system_config._migrate(self._src, self._dst)

        db_dst = self._dst / 'db.sqlite3'
        self.assertTrue(db_dst.is_file())
        conn = sqlite3.connect(str(db_dst))
        try:
            self.assertEqual(conn.execute('SELECT v FROM t').fetchone()[0],
                             'committed-in-wal')
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            conn.close()

    def test_migrate_leaves_no_dangling_source_siblings(self):
        self._make_db_with_leftover_wal()
        system_config._migrate(self._src, self._dst)
        for name in ('db.sqlite3', 'db.sqlite3-wal', 'db.sqlite3-shm', 'db.sqlite3-journal'):
            self.assertFalse((self._src / name).exists(), f'源侧仍残留 {name}')
