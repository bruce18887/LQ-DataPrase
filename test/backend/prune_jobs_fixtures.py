"""C2 判据的**共享道具**：临时 MEDIA_ROOT + 按布局造盘上目录。

消费者有两个文件，拆开的唯一原因是 600 行绊线（`scripts/line-limit.mjs`：被跟踪的 `*.py`
到 601 行即红；C1 批次的 `test/backend/job_cancel_fixtures.py` 是同一个先例）：

* `test/backend/test_prune_jobs_dir.py` —— 行驱动那一半：回收/泄漏本体、第二道判据、
  计数口径、留盘重试、`--days`；
* `test/backend/test_prune_jobs_fence.py` —— 盘上那一半：删除目标的形状（围栏）、与
  `result_dirs` 的布局同意、与「另一个行」的归属。

夹具只有这一份：**不许**复制 `PruneDirCaseMixin`。两份会各自漂，而「每个用例一份独立
`mkdtemp`」这条隔离正是判据可信的前提（理由写在 mixin 的 docstring 里，那里是唯一归属点）。
"""

import importlib
import io
import os
import shutil
import tempfile
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.jobs.models import Job

STALE = timedelta(days=30)      # 远超 --days=7 的保留期
FRESH = timedelta(minutes=5)    # 还在保留期内
PASSWORD = 'x-prune-12345678'
PRUNE_JUDGEMENT_MODULES = ('test_prune_jobs_dir', 'test_prune_jobs_fence')


class PruneDirCaseMixin:
    """临时 MEDIA_ROOT + 按**布局本身**（不是被测代码）造盘上目录。

    `_dir()` 里的路径是手拼的：判据要钉的就是「代码认 `jobs/<owner>/<id>` 这个布局」，
    若改用 `executor.result_dirs()` 造目录，等于让被测代码自己给自己出题（两处一旦分家，
    就是当年那个数据丢失 bug 的形状 —— 反过来由 `PruneLayoutAgreementTests` 钉住同意）。

    **每个用例一份独立 `mkdtemp`，回收都走 `addCleanup`**：`TestCase` 逐用例回滚 ⇒ 同一类里
    `owner.pk` 与 `job.pk` 恒是同一对数字，盘上 `jobs/<owner>/<id>` 因此在用例之间**同名**
    （C1 批次就是被这个形状咬过：共用一个被复用的 pk ⇒ 一个用例清掉的目录让另一个用例的
    断言假绿/假红）。隔离取向是「盘上不共享任何东西」，不是「给每行分配不重复的 pk」——
    后者要靠库里没被回滚的行号撑住，比临时目录更脆。共享的 `test/unit-data/media`
    本工单的判据一个字节都不写。
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='lqdp-prune-media-')
        override = override_settings(MEDIA_ROOT=self._tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self.media = self._tmp
        self.user = User.objects.create_user(username='prune-owner', password=PASSWORD)

    def _assert_media_root_is_temp(self):
        """绊线：MEDIA_ROOT 没被临时目录接管就**立刻**红，别去动真盘（本机
        `…\\LQ-DataPrase\\media` 里是用户真的作业产物）。"""
        self.assertEqual(str(settings.MEDIA_ROOT), self._tmp,
                         'prune 要跑在真实 MEDIA_ROOT 上了，先修用例再跑')

    def _job(self, status, *, result_path='', finished=STALE, kind='export_excel',
             owner=None):
        """造一行；`finished` 只给保留期判据用，与选行口径无关（None = 没记终局时间）。

        `owner` 默认本用例的 `self.user`；归属判据要造「另一个用户名下的同号行」，
        所以这里给一个口子，别在判据文件里再写一份 `Job.objects.create`。
        """
        return Job.objects.create(
            owner=owner or self.user, kind=kind, status=status,
            result_path=result_path,
            finished_at=timezone.now() - finished if finished is not None else None)

    def _job_dir(self, job_id, owner=None):
        """`jobs/<owner>/<job_id>` 的绝对路径 —— 不建目录，只算名字。"""
        return os.path.join(self.media, 'jobs', str((owner or self.user).pk), str(job_id))

    def _dir(self, job_id, *, canary='out.bin'):
        """按布局在盘上造作业目录（默认放一个 1KB 产物）。"""
        path = self._job_dir(job_id)
        os.makedirs(path, exist_ok=True)
        if canary:
            self._stuff(path, canary)
        return path

    def _stuff(self, path, name, size=1024):
        with open(os.path.join(path, name), 'wb') as fh:
            fh.write(b'x' * size)
        return os.path.join(path, name)

    def _protected(self, path, name='keep.txt'):
        """待保护目录里的哨兵：它还在 ⇒ 整个目录没被动过。"""
        os.makedirs(path, exist_ok=True)
        return self._stuff(path, name)

    def _batch_tree(self, *dir_names):
        """`MEDIA_ROOT/data/<username>/batch/<dir_name>/` 若干兄弟批次，返回 (父目录, [批次])。

        这是 `apps/jobs/sftp_job.py::run_sftp_download` 那条 `result_path =
        data/<user>/batch/<dir_name>` 在生产里对应的盘上形状：一个用户名下**多个**批次目录
        并存（下过几批就有几个）。
        """
        batch_root = os.path.join(self.media, 'data', self.user.username, 'batch')
        dirs = []
        for name in dir_names:
            path = os.path.join(batch_root, name)
            os.makedirs(path, exist_ok=True)
            self._stuff(path, f'{name}.csv')
            dirs.append(path)
        return batch_root, dirs

    def _run_streams(self, **options):
        """跑命令，返回 (stdout, stderr)。留盘告警走 stderr —— 运维在终端里看的是那一条。"""
        self._assert_media_root_is_temp()
        out, err = io.StringIO(), io.StringIO()
        options.setdefault('days', 7)
        call_command('prune_jobs', stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    def _run(self, **options):
        return '\n'.join(self._run_streams(**options))


def prune_cases_without_the_mixin(skip):
    """本工单两个判据文件里**没接** `PruneDirCaseMixin` 的 TestCase 类名（绊线的取证）。"""
    naked = []
    for name in PRUNE_JUDGEMENT_MODULES:
        module = importlib.import_module(f'test.backend.{name}')
        naked += [f'{name}.{obj.__name__}' for obj in vars(module).values()
                  if isinstance(obj, type) and issubclass(obj, TestCase)
                  and obj.__module__ == module.__name__ and obj is not skip
                  and not issubclass(obj, PruneDirCaseMixin)]
    return sorted(naked)
