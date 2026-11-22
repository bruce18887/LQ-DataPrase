# test/backend/test_storage_usage_jobs.py
"""占用统计纳入作业产物（``jobs/``）的口径测试（T1）。

Run directly: .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_storage_usage_jobs

为什么单开一个文件：``test_storage_usage_scan.py`` 已 562 行，600 行硬约束
（``.claude/CLAUDE.md``「600 行约束的适用面」）不给它留新的判据；而这份判据的口径
（data 与 jobs 分开报、再给一个合计）不属于那份文件「同一棵树怎么分桶」的主题。

口径（不要和 ``bytes`` 混）：``bytes`` 仍是 ``MEDIA_ROOT/data/<username>/`` 那棵树的量，
``by_type`` / DB 两本账 / 差值恒等式全部不动；``jobs_bytes`` 是**另一棵树**
``MEDIA_ROOT/jobs/<user.id>/`` 的量，``total_bytes = bytes + jobs_bytes``。

jobs 根用**整数 PK**、不拼用户名 —— 与 ``apps/jobs/executor.py:245`` 的
``result_dirs()``（``os.path.join('jobs', str(owner_id), str(job_id))``）同源。
拼用户名的话产物目录与统计目录会是两个不同的地方（作业目录从来只按 owner_id 落），
这条由 ``test_jobs根按整数PK而不是用户名`` 钉住。
"""
import os
import shutil
import tempfile

from django.test import TestCase

from apps.accounts.models import User
from apps.datafiles import storage_usage
from apps.datafiles.models import DataFile

PASSWORD = 'x-pass-12345678'


def _write(path, size):
    """写一个恰好 size 字节的文件（内容全 'a'，体积可预测）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(b'a' * size)
    return path


class JobsUsageTests(TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-jobs-')
        self.addCleanup(shutil.rmtree, self.base, True)
        # 缓存键只有 (username, bucket)、**不含 MEDIA_ROOT**：不清的话同一个用户名在
        # 同一个 30s 桶里会读到上一棵临时树的量（同 test_files_usage_api.py 的 tearDown）。
        storage_usage.clear_usage_cache()
        self.user = User.objects.create_user('jobs_a', 'ja@localhost', PASSWORD)
        self.other = User.objects.create_user('jobs_b', 'jb@localhost', PASSWORD)

    def tearDown(self):
        storage_usage.clear_usage_cache()

    def _write_data(self, username, rel, size):
        return _write(os.path.join(self.base, 'data', username, *rel.split('/')), size)

    def _write_job(self, user, job_id, rel, size):
        return _write(
            os.path.join(self.base, 'jobs', str(user.id), str(job_id), *rel.split('/')), size
        )

    def _usage(self):
        """必须在 ``self.settings(MEDIA_ROOT=self.base)`` **里面**调。

        ``manage.py test`` 跑的是 ``config.settings.unit``，其 MEDIA_ROOT 是
        ``test/unit-data/media``（不是 tempdir）⇒ 漏了 override 时写入侧与扫描侧不同源，
        表现为 jobs 那三项恒为 0（假绿），还会在共享沙箱里留残留。
        """
        with self.settings(MEDIA_ROOT=self.base):
            return storage_usage._compute_usage(self.user)

    def test_jobs体积与文件数独立于data口径(self):
        """三个新字段各自成话：jobs 的量**不许**被并进 ``bytes`` / ``by_type``。

        变异判据：把 jobs 扫出来的量加进 ``bytes``（或并进 ``by_type`` 的空串桶）⇒ 本条红。
        """
        self._write_data('jobs_a', 'single/a.csv', 1000)
        self._write_job(self.user, 11, 'out.xlsx', 3000)
        self._write_job(self.user, 11, 'tmp/sheet.csv', 5000)
        usage = self._usage()
        # data 侧照旧
        self.assertEqual(usage['bytes'], 1000)
        self.assertEqual(usage['file_count'], 1)
        self.assertEqual(usage['by_type'], {'single': {'bytes': 1000, 'count': 1}})
        # jobs 侧：两笔 st_size 之和、文件数 2（第二颗在 job 目录的子目录里 ⇒
        # 平铺 scandir 的实现会漏掉它，本条同时钉住「走的是树遍历」）
        self.assertEqual(usage['jobs_bytes'], 3000 + 5000)
        self.assertEqual(usage['jobs_file_count'], 2)
        self.assertEqual(usage['total_bytes'], usage['bytes'] + usage['jobs_bytes'])
        self.assertEqual(usage['total_bytes'], 9000)

    def test_jobs根不存在时三项为0(self):
        """没有作业产物时不许报成 None 或漏字段：前端 chip 求和不能碰上 NoneType。"""
        self._write_data('jobs_a', 'single/a.csv', 700)
        usage = self._usage()
        self.assertFalse(os.path.exists(os.path.join(self.base, 'jobs')))
        self.assertEqual(usage['jobs_bytes'], 0)
        self.assertEqual(usage['jobs_file_count'], 0)
        self.assertEqual(usage['total_bytes'], 700)

    def test_别人的jobs目录不计入(self):
        """``jobs/<id>`` 按 owner_id 分家 ⇒ A 的统计只能读 A 自己那个目录。

        变异判据：把 jobs 根写成 ``MEDIA_ROOT/jobs``（忘了拼 user.id）或按用户名拼 ⇒
        本条红（读到 B 的 9000，或读到 0）。
        """
        self._write_data('jobs_a', 'single/a.csv', 1000)
        self._write_job(self.user, 11, 'out.xlsx', 200)
        self._write_job(self.other, 12, 'out.xlsx', 9000)
        usage = self._usage()
        self.assertEqual(usage['jobs_bytes'], 200)
        self.assertEqual(usage['jobs_file_count'], 1)
        self.assertEqual(usage['total_bytes'], 1200)

    def test_jobs根按整数PK而不是用户名(self):
        """作业目录从来只按 ``owner_id`` 落（``apps/jobs/executor.py:245``）。
        统计侧若拼用户名，两处会指向不同目录 ⇒ 真实产物永远扫不到，而本用例会红。

        裸断言 ``jobs_bytes == 200`` 也能被「按用户名拼」的坏实现骗过（username 与 id
        恰好都在树里时），所以同时铺一棵 ``jobs/<username>/`` 的诱饵树把 900 摆在那里。
        """
        self._write_data('jobs_a', 'single/a.csv', 100)
        self._write_job(self.user, 11, 'out.xlsx', 200)
        _write(os.path.join(self.base, 'jobs', 'jobs_a', '11', 'out.xlsx'), 900)
        usage = self._usage()
        self.assertEqual(usage['jobs_bytes'], 200)
        self.assertNotEqual(self.user.username, str(self.user.id))

    def test_jobs体积不进差值恒等式的分母(self):
        """``mismatch`` 的分母是**用户看得见的 data 量**（``bytes``），不是合计。

        变异判据：把分母换成 ``total_bytes`` ⇒ 本条从 True/100 变成 False/100。
        这也顺带钉住「jobs 里的文件不进清单交集」：它们没有 DataFile 行，一旦被塞进
        ``registered`` 的比较就会凭空冒出差值。
        """
        self._write_data('jobs_a', 'single/a.csv', 1000)
        DataFile.objects.create(
            owner=self.user, filename='a.csv',
            file_path='data/jobs_a/single/a.csv', file_size=1100,
            format_type='CTA8290D', status='ready',
        )
        self._write_job(self.user, 11, 'big.bin', 100000)
        usage = self._usage()
        self.assertEqual(usage['jobs_bytes'], 100000)
        self.assertEqual(usage['mismatch_diff_bytes'], 100)      # 只算交集里那一笔
        self.assertTrue(usage['mismatch_over_threshold'])         # 100 / 1000 = 10%
