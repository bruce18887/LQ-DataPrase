"""C2 · `prune_jobs` 的**盘侧**判据：什么形状、谁的目录才允许被 `rmtree`。

行侧那一半（泄漏本体、第二道判据、计数、留盘重试）在
`test/backend/test_prune_jobs_dir.py`，道具在 `test/backend/prune_jobs_fixtures.py`。
本文件钉两道闸，入口是 `prune_jobs.py::_deletable_dir`（形状那道闸本身是 `_guard_target`：
**生产走的就是判据探的那个函数**，所以「围栏有没有被绕过」这件事只有一份答案）：

1. **形状（围栏）**：目标必须正好是 `MEDIA_ROOT/jobs/<十进制 owner>/<十进制 id>`。拒掉的形状族
   是少一层的三种（`MEDIA_ROOT`、`MEDIA_ROOT/jobs`、整个 owner 目录）+ 两种撞名兄弟（前缀撞的
   `jobs-evil`、与 `jobs` 同长度的 `jobz`）+ 带 `..` 的两种逃逸 + `jobs/` 之外的任何路径。
   其中**同长度兄弟**（`jobz`）才是「`relpath` vs 长度切片」两种实现取向的判据点，前缀撞名那种
   只是越界家族的一员；**两种写法的差别与取向的理由只讲一遍，在 `prune_jobs.py::_guard_target`
   的 docstring（唯一归属点）**，本文件只指过去、不复述。**生产真实会踩的那一条**
   （done 的 `sftp_download` 行）与它的事实链归 `PruneSftpBatchShapeTests` 的类 docstring，
   本文件其余地方同样只指过去。
2. **与布局的同意**：围栏是自己拼的第二份 `jobs/<数字>/<数字>`，而布局的归属点是
   `executor.py::result_dirs` —— 两份说法一旦分家就是当年那个 bug 的成因，所以
   `PruneLayoutAgreementTests` 拿 `result_dirs` 的产出**原样**喂围栏，并派生「必须拒」。
3. **归属**：有行索引的目录只由它自己的行删。`result_path` 兼容分支只收**没有行索引它**的孤儿
   目录（取向的理由、以及「这条分支按计划 Step 3 的原文保留、只加归属闸门」那个读法，都归
   `prune_jobs` 的模块 docstring，本文件只留指针）。

跑法：`python -X utf8 manage.py test test.backend.test_prune_jobs_fence -v 2`
"""

import os
from unittest import mock

from django.test import TestCase

from apps.accounts.models import User
from apps.datafiles.utils import resolve_file_path
from apps.jobs.executor import result_dirs
from apps.jobs.management.commands import prune_jobs
from apps.jobs.models import Job
from test.backend.prune_jobs_fixtures import (
    FRESH, PASSWORD, STALE, PruneDirCaseMixin)

REFUSED = ('', ())        # `_guard_target` 的 fail-closed 返回值 = 拒删（判据独立写一份）


class PruneLayoutAgreementTests(PruneDirCaseMixin, TestCase):
    """围栏认的形状必须**就是** `result_dirs()` 产出的形状 —— 两处一旦分家这条当场红。

    这里不复制第三份布局：把 `result_dirs` 的产出原样喂进围栏验「必须收」，再从同一个
    产出身上派生五个「必须拒」。
    """

    def test_fence_accepts_result_dirs_output_verbatim(self):
        rel, abs_dir = result_dirs(7, 3)
        # 连那两段数字一起验：归属判据吃的就是它们，只比路径等于没钉第二段
        accepted = (os.path.realpath(abs_dir), ('7', '3'))
        self.assertEqual(prune_jobs._guard_target(abs_dir), accepted,
                         'result_dirs 的产出被围栏判成非法目标 ⇒ prune 静默留下所有目录')
        # 兼容分支吃的是 `result_path`，所以同一布局的**相对**形状经 `resolve_file_path`
        # 绕一圈回来也必须过闸（否则围栏与布局只在绝对路径上勉强一致）
        self.assertEqual(prune_jobs._guard_target(
            os.path.dirname(resolve_file_path(os.path.join(rel, 'export.xlsx')))),
            accepted, '同一布局的相对形状与绝对形状在围栏两侧不一致')

    def test_fence_rejects_shapes_that_only_look_like_the_layout(self):
        """五种「长得像布局」的形状一律拒。取向的理由归 `prune_jobs::_guard_target`
        的 docstring（那里是唯一归属点），本表只保证每一种形状都真的被试过一次。

        `四字撞名兄弟` 是五种里**唯一区分两种实现取向的那一个**（两种写法各自切出什么，见
        `_guard_target`，这里不复述）：换成切片写法时这条必须红（变异自证 M7）。
        """
        _, abs_dir = result_dirs(7, 3)
        root = prune_jobs.jobs_root()
        rejected = {
            '末尾撞名的兄弟': abs_dir + '-evil',
            'jobs 撞前缀的兄弟': os.path.join(os.path.dirname(root), 'jobs-evil', '7', '3'),
            '四字撞名兄弟': os.path.join(os.path.dirname(root), 'jobz', '7', '3'),
            '少一层（整个 owner 目录）': os.path.join(abs_dir, '..'),
            '是 isdigit 但不是十进制': os.path.join(root, '7', '²'),
        }
        for why, candidate in rejected.items():
            with self.subTest(shape=why):
                self.assertEqual(prune_jobs._guard_target(candidate), REFUSED,
                                 f'围栏收下了「{why}」：{candidate}')

    def test_the_deletion_queue_is_exactly_what_result_dirs_builds(self):
        job = self._job('error')
        self.assertEqual(prune_jobs.dir_targets(job),
                         [os.path.realpath(result_dirs(job.owner_id, job.pk)[1])],
                         '删除目标与布局归属点分家了：本命令不再按 result_dirs 认目录')


class PrunePathSafetyTests(PruneDirCaseMixin, TestCase):
    """围栏：越界、层数不对、撞前缀或带 `..` 的候选目录一律拒删。

    这一类钉的是**形状族**（少一层的三种 + 撞名的两种 + 逃逸的两种），全都经生产的
    `result_path` 通路真跑一遍；生产真的会产生
    的那一条（done 的 `sftp_download` 行，dirname 落在批次容器上）单独放在
    `PruneSftpBatchShapeTests`，因为它丢的东西不一样 —— 那是已注册的用户数据，不是 scratch。
    与 `jobs` **同长度**的兄弟（`jobz`）在这里也有一条：形状表只探 `_guard_target` 这个函数，
    本类这条探的是「命令真跑时用的闸是不是同一个函数」（变异自证 M10 红在这里，不红在表里）。
    """

    def test_refuses_artifact_directory_outside_jobs(self):
        """`data/<user>/...` 这一**类**形状在 `jobs/` 之外 —— 那不是我该删的东西。

        generic 替身（dirname = 用户目录）；生产真踩的那一条由 `PruneSftpBatchShapeTests`
        独立钉住 —— 两者丢的东西不同，别只留这一条。
        """
        legacy = self._protected(os.path.join(self.media, 'data', 'prune-owner'))
        job = self._job('done')
        Job.objects.filter(pk=job.pk).update(
            result_path=os.path.join('data', 'prune-owner', 'export.xlsx'))
        summary = self._run()
        self.assertTrue(os.path.exists(legacy), 'prune 删掉了 jobs/ 之外的目录')
        self.assertFalse(Job.objects.filter(pk=job.pk).exists(),
                         '选行口径不变：行照删，只是不越界删盘')
        self.assertIn('删行 1、删目录 0', summary)

    def test_refuses_root_jobs_and_whole_owner_targets(self):
        """三个「绝不能删」的形状各验一次：MEDIA_ROOT、MEDIA_ROOT/jobs、整个 owner 目录。"""
        shapes = [
            ('jobs', self.media),                                        # dirname=MEDIA_ROOT
            (os.path.join('jobs', 'x.xlsx'), os.path.join(self.media, 'jobs')),
            (os.path.join('jobs', str(self.user.pk), 'x.xlsx'),
             os.path.join(self.media, 'jobs', str(self.user.pk))),
        ]
        for rel, protected in shapes:
            with self.subTest(result_path=rel):
                keep = self._protected(protected)
                job = self._job('error')
                Job.objects.filter(pk=job.pk).update(result_path=rel)
                summary = self._run()
                self.assertTrue(os.path.exists(keep),
                                f'围栏漏掉了形状 {rel!r}：一次 rmtree 会端掉整层目录')
                self.assertIn('删目录 0', summary)

    def test_refuses_prefix_colliding_sibling_of_jobs(self):
        """`jobs-evil` 这种**前缀撞名**的兄弟目录不是 `jobs/` 下的东西。

        `MEDIA_ROOT/jobs-evil/<owner>/<id>` 也是「两层数字」，一次 `rmtree` 删到 `jobs/`
        之外的树上。形状本身走生产同一条 `result_path` 通路（真跑 + 汇总计数）；围栏用哪种
        写法判归属层、为什么那么选，只在 `prune_jobs::_guard_target` 的 docstring 讲一遍。
        **诚实记一句**：这条**不是**「relpath vs 长度切片」的判据点（两种写法在这里都拒）；
        钉住那个差别的形状在
        `PruneLayoutAgreementTests.test_fence_rejects_shapes_that_only_look_like_the_layout`。
        """
        evil = self._protected(os.path.join(self.media, 'jobs-evil',
                                           str(self.user.pk), '1'))
        job = self._job('done')
        Job.objects.filter(pk=job.pk).update(
            result_path=os.path.join('jobs-evil', str(self.user.pk), '1', 'x.xlsx'))
        summary = self._run()
        self.assertTrue(os.path.exists(evil), 'prune 删掉了 jobs/ 之外、只是名字撞前缀的目录')
        self.assertIn('删行 1、删目录 0', summary)

    def test_refuses_same_length_sibling_via_the_production_result_path_route(self):
        """同长度兄弟这一形状，换**生产通路**（`result_path` → 真跑）再验一次。

        形状表钉的是 `_guard_target` 这个函数，这条钉的是「命令真跑起来时那道闸就是它」：
        把 `_deletable_dir` 改成自带一份实现（变异自证 M10，自带那份用的是切片写法——两种
        写法的差别只在 `_guard_target` 的 docstring 讲），红的是这一条而不是形状表 ——
        也就是说「生产与判据走同一个函数」这件事本身有判据。
        """
        sibling = self._protected(os.path.join(self.media, 'jobz', str(self.user.pk), '1'))
        job = self._job('done')
        Job.objects.filter(pk=job.pk).update(
            result_path=os.path.join('jobz', str(self.user.pk), '1', 'x.xlsx'))
        self.assertEqual(
            prune_jobs._guard_target(os.path.dirname(resolve_file_path(job.result_path))),
            REFUSED, '同长度兄弟目录经 resolve_file_path 绕回来仍然被判成合法目标')
        summary = self._run()
        self.assertTrue(os.path.exists(sibling),
                        'prune 删掉了 jobs/ 之外、与 jobs 同长度的兄弟目录（一次 rmtree 端掉整棵）')
        self.assertIn('删行 1、删目录 0', summary)

    def test_refuses_result_path_that_walks_out_with_double_dot(self):
        """带 `..` 的 `result_path`：规范化之后不在 `jobs/` 之下就拒。

        两种 `..` 都验。落在本树内的那种（`jobs/../evil/...`）建了哨兵，直接验它还在；
        `jobs/../../evil/...` 规范化后在**整棵临时 MEDIA_ROOT 之外**（`%TEMP%` 的父级），
        那里**故意不建目录**：用例的 scratch 只有 `self._tmp`，往父级写东西就是给下一轮
        留残骸（也是本族最容易变成 flaky 的写法）。它靠 `_guard_target` 返回拒绝哨兵 +
        真跑「删目录 0」两件事一起钉。
        """
        inside = self._protected(os.path.join(self.media, 'evil', '1'))
        job = self._job('done')
        Job.objects.filter(pk=job.pk).update(
            result_path=os.path.join('jobs', '..', 'evil', '1', 'x.xlsx'))
        self.assertEqual(
            prune_jobs._guard_target(os.path.dirname(resolve_file_path(job.result_path))),
            REFUSED, 'jobs/../evil 规范化后仍在 jobs/ 之外，必须拒删')
        summary = self._run()
        self.assertTrue(os.path.exists(inside), '一次 `..` 逃逸的 result_path 被当成合法目标删了')
        self.assertIn('删行 1、删目录 0', summary)

        escaping = os.path.join('jobs', '..', '..', 'evil', 'x.xlsx')
        abs_target = os.path.dirname(resolve_file_path(escaping))
        self.assertEqual(prune_jobs._guard_target(abs_target), REFUSED)
        self.assertFalse(os.path.normcase(os.path.realpath(abs_target)).startswith(
            os.path.normcase(prune_jobs.jobs_root())))


class PruneForeignDirectoryTests(PruneDirCaseMixin, TestCase):
    """兼容分支只收**没有行索引它**的目录：有行索引的目录只由它自己的行删。

    `result_path` 是库里的自由字符串，形状围栏不验**归属**；少了这一道，一行畸形（或被手改过）
    的 `result_path` 就能把另一行**还在用**的 `jobs/<owner>/<id>/` 端走。四种写 `result_path`
    的通路都推不出这个形状（归属点在 `prune_jobs` 的模块 docstring），所以这条判据钉的是
    「防越权」而不是「兼容旧行」。

    归属判据吃 `(owner 段, id 段)` **两段**，两段各钉一侧：只按 id 段查 ⇒ 我名下的孤儿被
    别人的同号行挡住、永远收不回（`test_the_id_segment_being_anothers_row_pk_...`）；owner
    段一旦从本行读、而不是从候选路径读 ⇒ 别人名下有主的目录被当成孤儿删掉
    （`test_another_users_own_directory_is_never_touched`）。反过来的「有行就必须挡住」由
    `test_compat_branch_never_touches_a_directory_a_surviving_row_indexes` 与
    `test_my_own_surviving_row_with_that_id_blocks_the_candidate` 两条钉住。
    """

    def _point_at(self, job, target_id, owner_id=None):
        Job.objects.filter(pk=job.pk).update(
            result_path=os.path.join('jobs', str(owner_id or self.user.pk),
                                     str(target_id), 'export.xlsx'))

    def test_orphan_directory_no_row_indexes_is_still_cleaned(self):
        """产物挂在**没有对应行**的 id 名下（孤儿）⇒ 照收：没别的行能再来收它。"""
        job = self._job('done')
        stray = self._dir(job.pk + 1000)
        self._point_at(job, job.pk + 1000)
        summary = self._run()
        self.assertFalse(os.path.exists(stray), '无主目录没被收走：兼容分支失效')
        self.assertIn('删行 1、删目录 1', summary)

    def test_the_id_segment_being_anothers_row_pk_still_leaves_it_my_orphan(self):
        """id 段撞上**别人那行**的 pk、但 `(这个 owner, 这个 id)` 没有行 ⇒ 仍是孤儿，照收。

        钉的是归属判据的 owner 那一半：`filter(pk=id 段)` 那种写法会把 B 的行当成
        `jobs/<A>/<同一数字>` 的主人 ⇒ 我的孤儿永远收不回（变异自证 M8 摘掉 `owner_id`
        那一项，红在这里）。少收还能被下一轮再试，**错删**才是不可逆的那一侧，所以两段
        各自都有一条用例守着，方向相反。
        """
        mine = self._job('done')                                  # A 的行，pk=1
        other_user = User.objects.create_user(username='prune-other', password=PASSWORD)
        foreign = self._job('done', owner=other_user, finished=FRESH)   # B 的行，pk=2
        self.assertEqual(Job.objects.filter(pk=foreign.pk, owner=self.user).count(), 0,
                         '用例前提没了：我名下真有了这一 pk 的行，那它就不是孤儿')
        stray = self._dir(foreign.pk)                             # `jobs/<A>/<2>`：没行索引它
        self._point_at(mine, foreign.pk)
        summary = self._run()
        self.assertFalse(os.path.exists(stray),
                         'id 段撞上别人的行就放弃回收：这个孤儿再没有任何东西能收')
        self.assertFalse(Job.objects.filter(pk=mine.pk).exists(), '选行口径不变：行照删')
        self.assertIn('删行 1、删目录 1', summary)

    def test_my_own_surviving_row_with_that_id_blocks_the_candidate(self):
        """上一条件的另一侧：我名下**有**这一 pk 的行 ⇒ 目录归它，兼容分支一律不碰。

        同一轮里那一行自己也会被 prune（`Meta.ordering=['-created_at']` ⇒ 本行先、它后），
        所以「挡住」判的是**删除队列**里没有它，而不是跑完之后目录还在不在 —— 它最后由自己
        的行收走，一次 `rmtree`，汇总 `删目录 1`（不是 2 ⇒ 没有重复回收，也没有越权回收）。
        """
        other = self._job('error')                    # pk=1，A 名下 ⇒ `jobs/<A>/<1>` 归它
        mine = self._job('done')                      # pk=2，本行（排在前面）
        other_dir = self._dir(other.pk)
        self._point_at(mine, other.pk)
        self.assertEqual([os.path.normcase(t) for t in prune_jobs.dir_targets(mine)],
                         [os.path.normcase(os.path.realpath(self._job_dir(mine.pk)))],
                         '兼容分支把另一行还索引着的目录排进了删除队列')
        summary = self._run()
        self.assertIn('删行 2、删目录 1', summary)
        self.assertFalse(os.path.exists(other_dir),
                         '闸门把该收的孤儿也一起挡了：这一目录本该由 other 自己的行收走')

    def test_another_users_own_directory_is_never_touched(self):
        """owner 段读的是**候选路径**、不是本行：`jobs/<别人>/<他的行>` 永远轮不到我删。

        把 owner 段换成 `job.owner_id` 的写法（变异自证 M9）等于去查「我名下有没有这一 id」⇒
        别人名下有主的目录被当成孤儿删掉，丢的是**另一个用户**的作业产物。
        """
        other_user = User.objects.create_user(username='prune-other', password=PASSWORD)
        foreign = self._job('done', owner=other_user, finished=FRESH)   # B 的行 pk=1
        mine = self._job('done')                                        # A 的行 pk=2
        theirs = self._protected(os.path.join(self.media, 'jobs',
                                             str(other_user.pk), str(foreign.pk)))
        self._point_at(mine, foreign.pk, owner_id=other_user.pk)
        summary = self._run()
        self.assertTrue(os.path.exists(theirs), '兼容分支删掉了别人名下的作业目录')
        self.assertTrue(Job.objects.filter(pk=foreign.pk).exists())
        self.assertIn('删行 1、删目录 0', summary)

    def test_compat_branch_never_touches_a_directory_a_surviving_row_indexes(self):
        """另一行的目录不论状态都不许动：活着的正在往里写，保留期内的还要给用户下载。"""
        for status, finished in [('running', STALE), ('pending', STALE), ('done', FRESH)]:
            with self.subTest(other_row=status):
                other = self._job(status, finished=finished)
                other_dir = self._dir(other.pk)
                mine = self._job('done')
                self._point_at(mine, other.pk)
                summary = self._run()
                self.assertTrue(os.path.isdir(other_dir),
                                f'兼容分支删掉了 {status} 行 {other.pk} 的目录')
                self.assertTrue(Job.objects.filter(pk=other.pk).exists())
                self.assertFalse(Job.objects.filter(pk=mine.pk).exists(),
                                 '归属判据只管目录，本行照删')
                self.assertIn('删行 1、删目录 0', summary)


class PruneSftpBatchShapeTests(PruneDirCaseMixin, TestCase):
    """生产**真的会产生**的危险形状：done 的 `sftp_download` 行 ⇒ dirname 是用户全部批次的
    父目录。`test_refuses_artifact_directory_outside_jobs` 那条是 generic 替身（dirname =
    用户目录），它证明不了这一条：这里 dirname 落在一个**装着别的批次目录的容器**上，
    删掉的是一整棵已注册的数据树。

    事实链（读代码得来的，不是推的）：
    * `apps/jobs/sftp_job.py::run_sftp_download` 给成功作业写
      `rel = data/<username>/batch/<dir_name>`，两条 update（全成功 / 部分失败）都把它原样
      写进 `result_path` —— 部分失败那条也是 `status='done'`，踩中这条通路的行比「全成功」还多。
    * 产物**当场注册进用户库**（`sftp_job.py` 头注释 + `views.py::JobDownloadView` 对
      `kind='sftp_download'` 回 409）⇒ 那个批次目录不是作业 scratch，而是用户的数据，
      删了不可逆、也没有任何地方能重建。
    * 改动前那版 prune 对 `os.path.dirname(resolve_file_path(rel))` 直接
      `shutil.rmtree(..., ignore_errors=True)` ⇒ 一行超期的 SFTP 作业删掉时把该用户
      **所有**批次一起端走，而行照删（连重试的机会都不留）。
    """

    def _row_and_two_batches(self):
        batch_root, (first, second) = self._batch_tree('batch-keep-1', 'batch-keep-2')
        rel = os.path.join('data', self.user.username, 'batch', 'batch-keep-1')
        job = self._job('done', kind='sftp_download', result_path=rel)
        return job, batch_root, [first, second]

    def test_sftp_done_row_leaves_every_sibling_batch_directory_alone(self):
        """真跑一遍：行删掉，两个批次目录**一个字节都不许少**，汇总额外报「删目录 0」。

        断言顺序是刻意的：先把命令跑完、先验盘上的数据还在，最后才碰 `_guard_target` 这类
        内部函数 —— 退回改动前那版时这条要红在「用户批次没了」这句话上，而不是红在一个
        `AttributeError` 上（变异自证 M1 第一版就是后一种，看不出丢了数据）。
        """
        job, batch_root, batches = self._row_and_two_batches()
        summary = self._run()
        for path in batches:
            self.assertTrue(os.path.isdir(path),
                            f'一行超期 SFTP 作业端掉了用户批次 {path}')
            self.assertTrue(os.listdir(path), '批次目录被清空了（只剩空壳也算数据丢失）')
        self.assertFalse(Job.objects.filter(pk=job.pk).exists(), '选行口径不变：行照删')
        self.assertIn('删行 1、删目录 0', summary)
        self.assertEqual(prune_jobs._guard_target(batch_root), REFUSED,
                         'SFTP 的 result_path 推出来的是批次父目录，必须拒删')
        targets = [os.path.normcase(t) for t in prune_jobs.dir_targets(job)]
        self.assertNotIn(os.path.normcase(os.path.realpath(batch_root)), targets,
                         '围栏漏在删除队列之前，兼容分支仍会把批次父目录送进去')

    def test_without_the_deletability_guards_this_shape_takes_both_sibling_batches(self):
        """危险对照组：摘掉 `_deletable_dir`（形状 + 归属两道一起没 = 改动前那版），
        两个批次目录一起没了。

        上面那条「两棵都在」如果没有这条，就只是一句没被反证过的许愿 —— 这条必须绿在
        「确实会丢数据」上，才说明上面那条绿不是「目录本来就不存在」蒙出来的。
        """
        _, _, batches = self._row_and_two_batches()
        with mock.patch.object(prune_jobs, '_deletable_dir', lambda d, job: d):
            summary = self._run()
        for path in batches:
            self.assertFalse(os.path.exists(path),
                             '两道闸都摘了却两个批次都还活着 —— 那这条用例就没在测危险形状')
        self.assertIn('删行 1、删目录 1', summary,
                      '改动前还会自称「删目录 1」：删掉的是一整棵批次树，不是作业 scratch')
