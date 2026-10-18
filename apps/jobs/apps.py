"""`apps.jobs` 的 AppConfig。

进程重启（打包版被杀、部署重启、崩溃自恢复）后，`running` 的作业没有任何东西会再来改它
—— 前端会永远轮询一个已经死掉的作业。启动时统一判成 `error`，让重试按钮出现。
`pending` 不判死：它还没被领取，照常可执行。

为什么不在 `ready()` 里直接查库：Django 会对「app 初始化期访问数据库」发
`RuntimeWarning`，而且 `makemigrations` / `test` 这些离线命令根本没有僵尸要收。
所以 `ready()` 只在**服务启动路径**上调度它，判据取「默认执行、只跳过点名的离线命令」——
方向必须是 fail-safe：认不出来的命令也要清僵尸，宁可多做一次无害 UPDATE，
也不要留一个永远 running 的作业。
"""

import sys

from django.apps import AppConfig

# 这些命令跑在开发/CI 的批处理里，没有「进程重启留下的僵尸」这回事。
OFFLINE_COMMANDS = frozenset({
    'check', 'test', 'migrate', 'makemigrations', 'showmigrations', 'shell',
    'dbshell', 'collectstatic', 'createadmin', 'seed_test_data', 'backup_db',
    'prune_jobs', 'dumpdata', 'loaddata',
})


def mark_interrupted_jobs():
    """把所有 `running` 作业标为 `error`，返回受影响行数。

    刻意做成模块级函数（不内联进 `ready()`）：测试直接调它，不需要重启进程。
    """
    from django.db import OperationalError, ProgrammingError
    from django.utils import timezone

    from apps.jobs.models import Job

    try:
        # 首次启动（还没 migrate）时表不存在 —— 那不是错误，是还没建库。
        return Job.objects.filter(status='running').update(
            status='error', error='进程重启，作业中断，请重试',
            finished_at=timezone.now())
    except (OperationalError, ProgrammingError):
        return 0


def _is_offline_command(argv) -> bool:
    """`manage.py <cmd>` 取第二个词；直接跑脚本（standalone.py）时没有这个词 ⇒ 不算离线。"""
    return len(argv) > 1 and argv[1] in OFFLINE_COMMANDS


class JobsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.jobs'
    verbose_name = '重活作业化'

    def ready(self):
        if not _is_offline_command(sys.argv):
            mark_interrupted_jobs()
