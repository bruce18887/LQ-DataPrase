"""C2 · `prune_jobs` 的**行侧**判据：按 `jobs/<owner>/<id>` 目录名清理，异常作业不再永久泄漏。

钉住四件事（盘上的那一半 —— 形状、与 `result_dirs` 的布局同意、与别的行的归属 —— 在
`test/backend/test_prune_jobs_fence.py`；共享道具在 `test/backend/prune_jobs_fixtures.py`）：

1. **泄漏本体**：`result_path` 只有成功作业才会写，落到 `error` 的行它恒空 ⇒ 改动前删除
   目标推不出来，行删了、目录留下，而行一没就再没有任何东西来收它（`cancelled` 行按构造
   没有目录，见 `test_cancelled_row_is_reclaimed_only_if_a_directory_ever_existed`）。
   C1（超时看门狗与崩池丢弃都落 `error`）之后踩中这条通路的行只会变多。
2. **对照组**：`running`/`pending` 行的目录一个都不许动 —— worker 可能正在往里写。
3. **计数属实**：「删目录 N」只在目录**本来在、事后没了**时才 +1；本来不存在的不算回收，
   清不掉的报成「留盘 N」；dry-run 的「目录 N 个」与真跑同一个口径。
4. **清不掉就留着行**：一次失败本来下一轮还能重试，把行也删掉才是永久泄漏（这条取向的
   归属点是 `prune_jobs` 的模块 docstring，这里只报判据）。

跑法：`python -X utf8 manage.py test test.backend.test_prune_jobs_dir -v 2`
（label 必须是点号模块名或**目录**，文件路径会被拒 —— 本机 Django 6.0.5 实测，拒执点在
`django/test/runner.py::DiscoverRunner.load_tests_for_label`。）
"""

import io
import os
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.jobs.management.commands import prune_jobs
from apps.jobs.models import Job
from test.backend.prune_jobs_fixtures import (
    FRESH, PruneDirCaseMixin, prune_cases_without_the_mixin)


class PruneCaseHygieneTests(TestCase):
    """忘记接 `PruneDirCaseMixin` 的用例 = 在**真实 MEDIA_ROOT** 上跑删除。类层面拦住。"""

    def test_every_prune_case_takes_the_temp_media_root(self):
        naked = prune_cases_without_the_mixin(self.__class__)
        self.assertEqual(naked, [], f'这些用例没把 MEDIA_ROOT 换成临时目录：{naked}')


class PruneReclaimsJobDirTests(PruneDirCaseMixin, TestCase):
    """行驱动：终态 + 过保留期 ⇒ 行与 `jobs/<owner>/<id>/` 一起走。"""

    def test_error_row_without_result_path_loses_its_directory(self):
        job = self._job('error')
        job_dir = self._dir(job.pk)
        sibling = self._protected(os.path.dirname(job_dir))
        summary = self._run()
        self.assertFalse(os.path.exists(job_dir),
                         'error 行没有 result_path，目录必须仍随行一起消失（本次修复的本体）')
        self.assertFalse(Job.objects.filter(pk=job.pk).exists())
        self.assertTrue(os.path.exists(sibling),
                        '只许删 <owner>/<id> 两层，不许顺手清空整个 owner 目录')
        self.assertIn('删行 1、删目录 1', summary)

    def test_cancelled_row_is_reclaimed_only_if_a_directory_ever_existed(self):
        """`cancelled` 行**按构造没有目录**，会泄漏目录的只有 `error` 行（上一条）。

        判据链的正文在 `executor.py::cancel_queued` 与 `views.py::JobCancelView` 的 409 分支
        注释里（「已进 worker 就不许按排队取消」）；**取消成功 ⇒ 从未进过 worker ⇒
        `jobs/<owner>/<id>/` 压根没建过** —— 建目录的两处都在 worker 侧：
        `runner.py::write_progress`（进度侧车）与 `runner.py::_write_out`（产物）。
        别把这条读成「cancelled 也在泄漏」，那是 overstated。

        这里仍然手造一个目录，钉的是循环**不区分终态种类**：行是终态 + 过保留期，真实存在过
        的目标就照收（历史行、手工行都算），但不多删任何东西。
        """
        job = self._job('cancelled')
        job_dir = self._dir(job.pk)
        summary = self._run()
        self.assertFalse(os.path.exists(job_dir),
                         '终态判据不该对 cancelled 网开一面：目录真在就得收走')
        self.assertIn('删行 1、删目录 1', summary)

    def test_pending_row_directory_survives(self):
        """`pending` 与 `running` 一样点名（不是只钉 running）：还没收工的行目录不许动。

        真实库里 pending 行通常 `finished_at` 为空、连 filter 都过不去；这里故意给它一个
        旧时间戳，是要证明**状态**这一道就在拦，而不是「靠 finished_at 恰好为 NULL 蒙住」。
        """
        job = self._job('pending')
        job_dir = self._dir(job.pk)
        summary = self._run()
        self.assertTrue(os.path.isdir(job_dir), 'pending 行的目录被 prune 删了')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())
        self.assertIn('删行 0、删目录 0', summary)

    def test_running_row_directory_survives(self):
        """对照组：行是活的 ⇒ 目录不许动（worker 可能正在往里写）。"""
        job = self._job('running')
        job_dir = self._dir(job.pk)
        summary = self._run()
        self.assertTrue(os.path.isdir(job_dir), 'running 行的目录被 prune 删了')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())
        self.assertIn('删行 0、删目录 0', summary)

    def test_terminal_row_within_retention_keeps_everything(self):
        job = self._job('done', finished=FRESH)
        job_dir = self._dir(job.pk)
        summary = self._run()
        self.assertTrue(os.path.isdir(job_dir), '保留期内的产物被提前删了，下载会 404')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())
        self.assertIn('删行 0、删目录 0', summary)

    def test_done_row_with_result_path_counts_the_shared_directory_once(self):
        """两条分支命中**同一个**目录 ⇒ 只排队一次：dry-run 报 1 个、`_remove_dir` 只被问 1 次。

        两条断言各管一档，且都是**变异可证**的（摘掉 `dir_targets` 里那句
        `guarded not in targets` 才会红）：
        * dry-run 数「盘上真在的候选」⇒ 会变成 `目录 2 个`；
        * 真跑**只**断「删目录 1」测不到去重 —— 同一目录以两个候选进来时第一次报 `removed`、
          第二次报 `absent`，汇总照旧是 1，`rmtree` 也只实际执行一次（第二次已经不在盘上）。
          所以另起一行、桩掉 `_remove_dir` 去数**递到删除那一步的候选**，那才是去重的判据；
          桩返回 ABSENT = 什么都没删，只用于计数。
        """
        job = self._job('done')
        job_dir = self._dir(job.pk, canary=None)
        self._stuff(job_dir, 'export.xlsx')
        Job.objects.filter(pk=job.pk).update(
            result_path=os.path.join('jobs', str(self.user.pk), str(job.pk), 'export.xlsx'))
        dry = self._run(dry_run=True)
        self.assertIn('目录 1 个', dry)
        self.assertNotIn('目录 2 个', dry, '同一物理目录被两条分支数了两次')
        self.assertIn('删行 1、删目录 1', self._run())
        self.assertFalse(os.path.exists(job_dir))

        other = self._job('done')           # 同一形状的第二个用例，只用来数候选
        Job.objects.filter(pk=other.pk).update(
            result_path=os.path.join('jobs', str(self.user.pk), str(other.pk), 'export.xlsx'))
        queued = []

        def probe(target):
            queued.append(target)
            return prune_jobs.Outcome.ABSENT, ''

        with mock.patch.object(prune_jobs, '_remove_dir', probe):
            self._run()
        self.assertEqual(queued, [os.path.realpath(self._job_dir(other.pk))],
                         f'递到删除那一步的候选有 {len(queued)} 个：同一物理目录没去重')

    def test_missing_directory_is_not_counted_as_removed(self):
        self._job('error')                  # 目录本来就不在（早被人清了 / 从没产出）
        summary = self._run()
        self.assertIn('删行 1、删目录 0', summary,
                      '把「本来就没有」报成「我删掉了」等于给运维一个假的安全感')

    def test_dry_run_leaves_row_and_directory_alone(self):
        job = self._job('error')
        job_dir = self._dir(job.pk)
        out = self._run(dry_run=True)
        self.assertTrue(os.path.isdir(job_dir), 'dry-run 动了盘')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists(), 'dry-run 删了行')
        self.assertIn(f'would remove job {job.pk}', out)
        self.assertIn('目录 1', out,
                      'dry-run 只报 result_path（error 行恒空）会让运维以为没东西可清')
        self.assertIn('（dry-run，未改动）', out)


class PruneLoopGuardTests(PruneDirCaseMixin, TestCase):
    """循环内那道「终态 + 过保留期」的第二道判据（`prune_jobs.py::_prunable`）。

    做法是把行**绕过** `handle()` 里的 filter 直接喂进循环 —— 看着别扭，但没有第二种办法
    能钉住一道「正常情况下够不着」的守卫：不这样测，删掉守卫没有任何用例会红，交出去的
    就是一条无人执行的检查。这条方法论的归属点在这里，`_prunable` 的注释只留指针。
    """

    def _feed(self, *rows):
        probe = mock.MagicMock()
        probe.objects.filter.return_value.iterator.return_value = iter(list(rows))
        out, err = io.StringIO(), io.StringIO()
        self._assert_media_root_is_temp()
        with mock.patch.object(prune_jobs, 'Job', probe):
            call_command('prune_jobs', days=7, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_guard_spares_a_non_terminal_row_handed_to_the_loop(self):
        job = self._job('running')
        job_dir = self._dir(job.pk)
        out = self._feed(job)
        self.assertTrue(os.path.isdir(job_dir), '护栏失效：非终态行的目录被删了')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists(), '护栏失效：非终态行被删了')
        self.assertIn('删行 0、删目录 0', out)

    def test_guard_spares_a_pending_row_handed_to_the_loop(self):
        """同一道护栏对 `pending` 也点名（`TERMINAL_STATUSES` 少写一个字的回归形状）。"""
        job = self._job('pending')
        job_dir = self._dir(job.pk)
        out = self._feed(job)
        self.assertTrue(os.path.isdir(job_dir), '护栏失效：pending 行的目录被删了')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists(), '护栏失效：pending 行被删了')
        self.assertIn('删行 0、删目录 0', out)

    def test_guard_spares_a_row_inside_retention_handed_to_the_loop(self):
        job = self._job('done', finished=FRESH)
        job_dir = self._dir(job.pk)
        out = self._feed(job)
        self.assertTrue(os.path.isdir(job_dir), '护栏失效：保留期内的目录被删了')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists(), '护栏失效：保留期内的行被删了')
        self.assertIn('删行 0、删目录 0', out)

    def test_guard_spares_a_terminal_row_that_never_recorded_finished_at(self):
        """`finished_at` 为空的终态行**不许**删：判据里那句 `is not None` 不是装饰。

        `handle()` 的 `finished_at__lt` 本就筛掉 NULL（SQL 语义），所以这条只能绕过 filter
        喂 —— 而那半句判据也正是**只有**绕过 filter 才测得到：少了它 `None < cutoff` 抛
        `TypeError`，整轮 prune 当场崩掉，没有任何用例会红（2026-10-29 本机变异自证：摘掉
        `is not None` ⇒ 恰好这一条红，其余全绿）。

        **定性：防御性判据，今天的生产路径够不到它**（2026-10-29 逐个写点核过，别再给它编出处）。
        落终态的每一处都在**同一条** UPDATE/save 里连 `finished_at` 一起写：`executor.py` 的
        `_write_back`（done / error 两条）、`_timed_out`、`cancel_queued`、`_reap_discarded`，
        `sftp_job.py` 的三条 update，`views.py` 的同步回落与取消。`apps/jobs/apps.py::
        mark_interrupted_jobs` 与此无关 —— 它只筛 `status='running'`、且时间写在同一条 UPDATE
        里（`apps.py:43-45`），**不回填**「已有终态、没终局时间」的行。所以那种行今天只可能
        来自手改库，或将来新增一个忘记写时间的终态写点；本条断言的就是那种行出现时护栏**留下
        它与它的目录**、而不是崩掉整轮。
        """
        job = self._job('error', finished=None)
        job_dir = self._dir(job.pk)
        out = self._feed(job)
        self.assertTrue(os.path.isdir(job_dir), 'finished_at 为空的行被当成「已过保留期」删了目录')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())
        self.assertIn('删行 0、删目录 0', out)


class PruneStuckDirectoryTests(PruneDirCaseMixin, TestCase):
    """`rmtree` 没把目录收掉时，行必须留下（否则「下次再来」永远来不了）。

    这里的 rmtree 是**注入的**、不是真盘的锁：本机能稳定复现「目录清不掉」的唯一办法。
    patch 的是 `prune_jobs` 模块里那个 `shutil` 绑定（R6-③：patch 实际消费处），不去动全局
    `shutil` —— 那会连累同一窗口里别的组件（含本工单夹具的 addCleanup）。两种注入各钉一边：
    抛 `OSError`（真盘上最常见）与**既不抛也没删掉**（最容易被当成成功的那种）。
    """

    def _swallowing_shutil(self, log):
        def rmtree(path, *args, **kwargs):
            log.append(path)
        return mock.Mock(rmtree=rmtree)

    def _raising_shutil(self, log, error):
        def rmtree(path, *args, **kwargs):
            log.append(path)
            raise error
        return mock.Mock(rmtree=rmtree)

    def test_row_is_kept_and_the_real_reason_reaches_stderr(self):
        job = self._job('error')
        job_dir = self._dir(job.pk)
        log = []
        with mock.patch.object(prune_jobs, 'shutil', self._raising_shutil(
                log, PermissionError(13, 'Permission denied', job_dir))):
            out, err = self._run_streams()
        self.assertEqual(len(log), 1, '一次失败都没发生，这条用例就没测到东西')
        self.assertTrue(os.path.isdir(job_dir))
        self.assertTrue(Job.objects.filter(pk=job.pk).exists(),
                        '目录没回收却把行删了 ⇒ 这个目录从此再没有任何东西能推出来 —— 永久孤儿')
        self.assertIn('删行 0、删目录 0', out)
        self.assertIn('留盘 1', out, '失败必须报得出来，不许算成「删目录 0」的沉默')
        self.assertIn('PermissionError', err,
                      '留盘告警必须带**真实原因**：旧的「多半还被占着」在 POSIX 上是错的'
                      '（那边 unlink 开着句柄也能成，真失败的是权限/EBUSY）—— 猜不如报')
        self.assertNotIn('多半', out + err, '猜成因的文案不许留在生产里')
        self.assertNotIn('没收掉', out, '告警走 stderr：别混进 stdout 的汇总里')

    def test_next_run_reclaims_it_once_the_directory_is_free(self):
        """留行的全部意义：下一轮真的能再来一次并收干净（把注释里的承诺钉成判据）。"""
        job = self._job('error')
        job_dir = self._dir(job.pk)
        with mock.patch.object(prune_jobs, 'shutil', self._swallowing_shutil([])):
            summary = self._run()
        self.assertIn('留盘 1', summary,
                      '没抛异常的失败就不算留盘了？「目录居然还在」只有事后 isdir 看得见')
        summary = self._run()                       # 第二轮：没人占着了
        self.assertFalse(os.path.exists(job_dir), '第二轮没能把留盘的目录收走')
        self.assertFalse(Job.objects.filter(pk=job.pk).exists())
        self.assertIn('删行 1、删目录 1', summary)
        self.assertNotIn('留盘', summary, '上一轮的留盘计数不许漏到这一轮（每轮自己算）')

    def test_absent_directory_is_not_reported_as_stuck(self):
        """三态分不开就等于骗人：本来不存在的目录既不是回收、也不是留盘，行照删。"""
        self._job('error')
        summary = self._run()
        self.assertIn('删行 1、删目录 0', summary)
        self.assertNotIn('留盘', summary)

    def test_an_outcome_nobody_named_keeps_the_row(self):
        """第四种结局（将来新增的）一律按「留盘」处理：兜底只能朝保守侧。

        `handle()` 的分派是「点名 REMOVED / 点名 ABSENT / 其余留盘」，所以新增一态忘了点名
        就红在下面这条断言上，而不是静默把行删掉、把目录变成永久孤儿。
        """
        job = self._job('error')
        job_dir = self._dir(job.pk)
        with mock.patch.object(prune_jobs, '_remove_dir',
                               lambda target: (prune_jobs.Outcome, '没这回事')):
            out, err = self._run_streams()
        self.assertTrue(os.path.isdir(job_dir), '陌生结局却动了盘')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists(),
                        '陌生结局被当成「不算留盘」⇒ 行删了、目录还在 = 永久孤儿')
        self.assertIn('留盘 1', out)
        self.assertIn('没这回事', err)
        self.assertIn('删行 0、删目录 0', out)


class PruneCountAgreementTests(PruneDirCaseMixin, TestCase):
    """dry-run 报的「目录 N 个」与真跑报的「删目录 N」必须同一个口径：**盘上真在的**。

    旧写法数的是**候选**（没过 `os.path.isdir`）⇒ 目录早就不在的一行会打印 `→ 目录 1 个`，
    真跑却说 `删目录 0`，运维读到的是「prune 有时真会删、有时不删」。两档现在各有各的判据
    （dry-run 数 `would`，真跑由 `_remove_dir` 回报 absent）。
    """

    def test_dry_run_and_real_run_report_the_same_count_for_a_missing_directory(self):
        job = self._job('error')          # 候选目录本来就不在
        dry = self._run(dry_run=True)
        self.assertIn(f'would remove job {job.pk}', dry)
        self.assertIn('目录 0 个', dry, 'dry-run 把不存在的目录数成了要删的目录')
        self.assertNotIn('目录 1 个', dry)
        self.assertIn('删行 1、删目录 0', self._run(), '真跑的数与上面那个必须一致')

    def test_dry_run_and_real_run_report_the_same_count_for_an_existing_directory(self):
        """对照组：目录真在 ⇒ 两处都报 1（否则上面那条靠「永远报 0」就能恒绿）。"""
        job = self._job('error')
        job_dir = self._dir(job.pk)
        self.assertIn('目录 1 个', self._run(dry_run=True))
        self.assertTrue(os.path.isdir(job_dir), 'dry-run 动了盘')
        self.assertIn('删行 1、删目录 1', self._run())


class PruneDaysArgumentTests(PruneDirCaseMixin, TestCase):
    """`--days` 的两端：0 = 「凡是结束了的都算超期」，负数 = 直接拒。

    `--days=0` 够得着「刚结束几秒、worker 还在写」那一档，`prune_jobs` 关不掉那个窗口
    （`executor.py::_timed_out` 之后 RUNNING 的 future 取消不了）—— 平台差异与为什么
    不在射程内，归 `prune_jobs` 模块 docstring 的「不在射程内」那节。
    """

    def test_days_zero_prunes_rows_that_finished_minutes_ago(self):
        job = self._job('done', finished=FRESH)     # 5 分钟前结束，正常保留期内
        job_dir = self._dir(job.pk)
        summary = self._run(days=0)
        self.assertFalse(os.path.exists(job_dir), '--days=0 没把刚结束的产物清掉')
        self.assertFalse(Job.objects.filter(pk=job.pk).exists())
        self.assertIn('0 天前的已结束作业 → 删行 1、删目录 1', summary)

    def test_days_zero_still_spares_a_running_row(self):
        """0 只是把保留期压到零，不是把状态判据一起关掉。"""
        job = self._job('running', finished=FRESH)
        job_dir = self._dir(job.pk)
        summary = self._run(days=0)
        self.assertTrue(os.path.isdir(job_dir))
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())
        self.assertIn('删行 0、删目录 0', summary)

    def test_negative_days_raises_before_touching_the_disk(self):
        job = self._job('error')
        job_dir = self._dir(job.pk)
        with self.assertRaises(CommandError) as ctx:
            self._run(days=-1)
        self.assertIn('不能为负', str(ctx.exception))
        self.assertTrue(os.path.isdir(job_dir), 'CommandError 之前已经动过盘了')
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())
