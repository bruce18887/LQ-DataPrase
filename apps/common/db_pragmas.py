"""SQLite 连接级 pragma —— 单进程多用户共用一个库的并发前提。

部署形态收敛为「一个进程 + 约 20 人读写同一个 SQLite 库」，而裸连接跑在
``journal_mode=delete``（回滚日志）下：一个写事务会挡下所有读，Django 默认的
busy_timeout 又只有 5 秒，并发稍高就直接 ``database is locked``。

WAL 让读不再被写阻塞，busy_timeout 把「撞锁即失败」换成「等锁」。两者都必须在
**每个新建连接**上设置——它们是连接属性，不是库属性，只在建库时执行一次是不够的。

``:memory:`` 库不支持 WAL（SQLite 直接回 ``memory``），测试运行器用的正是它，
所以这里只做「执行不抛」，不校验回写值。
"""

SQLITE_BUSY_TIMEOUT_MS = 30000

# journal_mode 的返回值就是生效后的模式（内存库回 'memory'，文件库回 'wal'）。
_SQLITE_STATEMENTS = (
    'PRAGMA journal_mode=WAL;',
    f'PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS};',
)


def configure_sqlite_connection(connection, **kwargs) -> None:
    """``connection_created`` 接收器：只对 SQLite 生效，其余 vendor 原样放过。"""
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        for statement in _SQLITE_STATEMENTS:
            cursor.execute(statement)
