"""`manage.py prune_jobs --days=7`：删掉超期的终态作业行与其结果目录。

作业产物落在 `MEDIA_ROOT/jobs/<owner>/<job>/`，不清会一直涨（一次批量图表几十 MB）。
目录布局的唯一归属点是 `apps/jobs/executor.py::result_dirs`，本命令 import 它用，不再自己
拼路径；围栏认的形状由判据拿 `result_dirs` 的产出**原样**反证（`PruneLayoutAgreementTests`）
—— 两处一旦分家就红，「两份对同一件事的说法」正是当年那个数据丢失 bug 的成因。
**只删 `TERMINAL_STATUSES`**（名单只有一份，定义在 `apps/jobs/models.py`，`executor.py` 的
`_write_back` 与这里共用）：`running`/`pending` 的行留着，它们还可能有产物要收。

**删除目标按 `owner_id + pk` 定位，不按 `result_path`**（本次修复的本体）：`result_path`
只有成功作业才会写 —— 写它的四处是 `executor.py::_write_back`、`sftp_job.py` 里那两条
update（全成功 / 部分失败）、`views.py::JobSubmitView` 的同步回落分支，`error` 行恒为空 ⇒
按它推目录对每个失败作业都推出空串，行删了、目录留下，而行一没就再没有任何东西来收它。
C1 之后落 `error` 的行只会更多（见 `executor.py::_timed_out` 与 `_reap_discarded` 的注释与
provenance），这条泄漏更常踩中。（`cancelled` 行不在这条账上：能取消成功的工作项从未进过
worker，而 `jobs/<owner>/<id>/` 是 worker 进来才建的 —— `runner.py::write_progress` 的进度
侧车目录与 `runner.py::_write_out` 的产物目录，见 `executor.py::cancel_queued` 与
`views.py::JobCancelView` 的 409 分支。目录泄漏只有 `error` 一种。）

**有行索引的目录只由它自己的行删**（本条取向在这里是唯一归属点，别处只留指针）。行是
`owner/pk → 路径` 的唯一索引，行一没就再也没有东西能推出那个目录，于是同一条理由管两件事：

* **清不掉的目录不删行** —— `rmtree` 失败时行**留着**，下一轮按同一个 owner/pk 再试一次，
  汇总报 `留盘 N`；执行体是 `handle()` 的 `stuck` 那一段，理由就是本节这一条，那里只留指针。
* **`result_path` 兼容分支只收没有行索引它的目录**（孤儿）—— 它是库里的自由字符串，围栏
  只验形状不验归属，少了这一道就能借一行畸形值端走**另一行还在用的**目录（判据
  `PruneForeignDirectoryTests`）。保留这条分支是计划 Step 3 的原文（「保留 `result_path`
  分支兼容旧行」）：本实现照原文保留，只在它前面加归属闸门，**不是**把它读成「删掉该分支」。
  它对「兼容旧行」能起的作用也只有孤儿那一档 —— 真实存在过的旧形状 `data/<user>/batch/...`
  本就由围栏挡下，所以这条分支从来不是为了「兼容指到别处的旧行」。

不在射程内：

* **收不回来的孤儿目录**：行先被 prune、worker 之后继续写出来的那种，以及本次修复之前已经
  泄漏在盘上的那些 —— 没有任何一行还留着 `result_path` 指得过去，兼容分支就够不着它，而
  没有行也推不出 owner/id，那要按盘扫，属独立工单。
* **`_timed_out` 留下的窗口**（`executor.py`，判据在 `test/backend/test_job_cancel.py`）：
  看门狗把行翻成 `error` 之后，RUNNING 的 future **取消不了**，worker 还在往那个目录里写，
  而行此刻已经是终态。今天只有 `--days=0` 够得着这种行（默认 7 天保留期把它冲掉了）。
  两个平台不对称，而且**POSIX 更糟**：Windows 上打开的句柄让 `os.unlink` 失败 ⇒ 目录清不掉
  ⇒ `KEPT` ⇒ 行留下、下一轮再试（自我止损）；POSIX 上 unlink 一个仍被写的文件**会成功**
  （目录项当场消失，worker 的句柄继续写进那个已脱链的 inode）⇒ 静默删掉写到一半的产物，
  随后 `runner._write_out` 的 `makedirs` 又把目录建回来 = 一个没有行索引的孤儿。围栏管不了
  它（形状合法），本命令也不解决它 —— 要解决得让 worker 与 prune 互相知情，独立工单。
"""

import enum
import os
import shutil
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.datafiles.utils import resolve_file_path
from apps.jobs.executor import result_dirs
from apps.jobs.models import TERMINAL_STATUSES, Job

JOBS_DIR_NAME = 'jobs'


class Outcome(enum.Enum):
    """`_remove_dir` 的三种结局；只有 `REMOVED` 算回收，`KEPT` 会让调用方**把行留下**。

    为什么不是 bool：压成 bool 就只剩「删了 / 没删」两种说法，而「本来就不在」和「存在却
    清不掉」后果完全相反 —— 前者行照删，后者必须留着重试；把两者混成一个 False，要么造出
    永久孤儿目录，要么让正常行永远留在库里。判据 `PruneStuckDirectoryTests` 三种各一条。
    为什么是 Enum 而不是裸串：`handle()` 的分派是「点名 REMOVED / 点名 ABSENT / 其余一律
    留盘」，将来新增第四态忘了点名就保守地留下行（可回滚），而不是静默删行（不可逆）。
    """

    REMOVED = 'removed'
    ABSENT = 'absent'
    KEPT = 'kept'


def jobs_root() -> str:
    """`MEDIA_ROOT/jobs/` 的真实路径 —— 所有删除目标的唯一围栏基准。"""
    return os.path.realpath(os.path.join(str(settings.MEDIA_ROOT), JOBS_DIR_NAME))


def _guard_target(abs_dir: str) -> 'tuple[str, tuple[str, str]]':
    """形状闸（生产与判据同一个入口）：候选必须正好是 `<jobs_root>/<十进制 owner 段>/<十进制 id 段>`。

    合格返回 `(真实绝对路径, (owner 段, id 段))`，其余一律 `('', ())` —— 那两段是给
    `_indexed_by_another_row` 做归属判定用的，所以**判据探的就是生产走的那道闸**，形状判据没有
    第二个入口（`_deletable_dir` 只是把两道闸分派在一起，判据的危险对照组摘的也是它）。
    `owner_id`/`pk` 取自库里、本就是整数，第一条候选因此越不了界；围栏真正防的是 `result_path`
    那条分支吃到的库里的字符串，`os.path.dirname()` 给出的经常不是这一行的 scratch。
    **生产真实会踩的那一条**是 `kind='sftp_download'` 且 `status='done'` 的行：它的
    `result_path` 指向用户名下的一个批次目录，dirname 掉一层就落在**该用户全部批次的共同父
    目录**上，一次 `rmtree` 端掉的是已注册、不可重建的用户数据。那条事实链（谁写的路径、为什么
    不许下载、改动前那版怎么删的）连同它的两条判据只在
    `test/backend/test_prune_jobs_fence.py::PruneSftpBatchShapeTests` 的类 docstring 里讲一遍，
    这里不复制第二份。其余拒掉的形状族：整个 `MEDIA_ROOT`、整个 `MEDIA_ROOT/jobs`、某个用户的
    全部作业目录 `MEDIA_ROOT/jobs/<owner>`，以及几种「长得像布局」的兄弟/逃逸形状（形状表在
    `PruneLayoutAgreementTests` 与 `PrunePathSafetyTests`）。

    实现取向：`os.path.relpath` 之后**要求正好两段十进制**，不用「normcase 前缀 + 长度切片」。
    切片那个写法把「比 root 长」和「在 root 里」混成一件事（`norm[len(root) + 1:]`），它的
    漏网点是**与 `jobs` 同长度的兄弟目录** `<media>/jobz/7/3`：切片恰好落在 `7\\3` 上 =
    两段十进制 ⇒ 被当成合法目标，一次 `rmtree` 删到 `jobs/` 之外的树上；`relpath` 那里得到
    `..\\jobz\\7\\3`（三段、带 `..`）⇒ 拒。判据表里那条「四字撞名兄弟」钉的就是这个差别。
    对照一下前缀撞名的 `jobs-evil/7/3`：**两种写法都拒**（切片给 `evil\\7\\3` = 三段），所以它
    只是「越界形状」家族的一员，不是取向的判据点。`os.pardir in parts` 同理是**保险丝**而不是
    主判据 —— `realpath` 早把 `..` 折掉了，而 `'..'.isdecimal()` 本就是 False，段数判据已经挡住
    同一件事；留着是为了「将来放宽段判据时，逃逸仍然当场红」。跨盘（Windows）没有相对路径可言，
    `relpath` 抛 `ValueError` ⇒ 一并 fail-closed。`isdecimal` 而不是 `isdigit`：`'²'.isdigit()`
    在本机 Python 3.13 实测为 True，那种段绝不是 `result_dirs` 能产出的形状。

    取向是 fail-closed：宁可留一个没人收的目录（留给盘扫那次工单），不越界删盘 —— 尤其不删
    **用户的数据**。判据 `PrunePathSafetyTests`、`PruneLayoutAgreementTests` 与
    `PruneSftpBatchShapeTests`（后者带一条「摘掉围栏两个批次一起没」的危险对照组）。
    """
    if not abs_dir:
        return '', ()
    real = os.path.realpath(abs_dir)
    try:
        rel = os.path.relpath(os.path.normcase(real), os.path.normcase(jobs_root()))
    except ValueError:                      # 跨盘：不存在相对路径，拒
        return '', ()
    parts = tuple(rel.split(os.sep))
    if len(parts) != 2 or os.pardir in parts or not all(seg.isdecimal() for seg in parts):
        return '', ()
    return real, parts


def _indexed_by_another_row(parts: 'tuple[str, str]', job) -> bool:
    """围栏后的目录是不是**另一行**的 owner/pk 名下（是 ⇒ 本行无权删它）。

    取向的归属点在模块 docstring「有行索引的目录只由它自己的行删」，这里只写机制：本行自己的
    目录短路返回 False（第一条候选就是它，不发查询），所以这次查询只在「形状合法但指到别人
    名下」时发生 —— 生产里四种 `result_path` 写法都推不出那个形状，它防的是库里的脏值/手改值。
    两段都取自**候选路径**（不是 `job` 身上），查询也按这两段**一起**认：owner 段一旦改从本行
    读，`jobs/<别人>/<他的行>` 就会因为「我名下没有这一 id」被放行；反之查询一旦不带
    `owner_id`，别人的同号行就会把**我名下**那个没人索引的目录永久挡住 —— 那正是本任务要修的
    泄漏，只是换了个方向（少收的目录再没有别的行能推出它）。两个方向各有一条判据钉住
    （`PruneForeignDirectoryTests` 的 `..._being_anothers_row_pk_...` 与
    `..._own_directory_is_never_touched`）。
    """
    owner_id, job_id = (int(seg) for seg in parts)
    if (owner_id, job_id) == (job.owner_id, job.pk):
        return False
    return Job.objects.filter(pk=job_id, owner_id=owner_id).exists()


def _deletable_dir(candidate: str, job) -> str:
    """候选 → **本行有权删掉**的那个绝对目录；否则 ''（= 拒删）。

    两道判据都在这里面（形状 → `_guard_target`，归属 → `_indexed_by_another_row`），
    `dir_targets` 只认这一个入口：判据要「摘掉围栏」时 patch 的也是它（`PruneSftpBatchShapeTests`
    的危险对照组 = 改动前那版，两道都没有）。
    """
    guarded, parts = _guard_target(candidate)
    if not guarded or _indexed_by_another_row(parts, job):
        return ''
    return guarded


def dir_targets(job) -> 'list[str]':
    """这一行对应的、可以删的绝对目录（去重、保序；可能为空）。

    **必须在 `job.delete()` 之前调用**：行一没，`owner_id`/`pk` 就再也推不出目录名了。
    这里只判形状与归属、**不判存在** —— 在不在盘上由 `_remove_dir` 报三态，别在这里预先
    filter 掉不存在的那一个（为什么只许它一处判，见 `_remove_dir`）。
    """
    candidates = [result_dirs(job.owner_id, job.pk)[1]]
    if job.result_path:
        candidates.append(os.path.dirname(resolve_file_path(job.result_path)))
    targets = []
    for candidate in candidates:
        guarded = _deletable_dir(candidate, job)
        if guarded and guarded not in targets:
            targets.append(guarded)
    return targets


def _prunable(job, cutoff) -> bool:
    """循环内的第二道「终态 + 已过保留期」判据；删目录与删行都只认它。

    选行本就由 `handle()` 的 filter 保证，这里的重复是刻意的：**行删错能回滚，目录删错
    不可逆**，所以落到盘上的那一步必须自己再确认一次。怎么测（以及为什么只能那么测）归
    `PruneLoopGuardTests` 的类 docstring，这条判据的三个分支各一条用例，这里不复制那份说法。
    """
    if job.status not in TERMINAL_STATUSES:
        return False
    return job.finished_at is not None and job.finished_at < cutoff


def _remove_dir(target: str) -> 'tuple[Outcome, str]':
    """删掉一个目录并回报 `(结局, 原因)`；原因只在 `KEPT` 时非空。

    **不再用 `ignore_errors=True`**：它把「为什么没清掉」连同异常一起丢掉，剩下的只有一句
    猜测，而那句猜测在 POSIX 上是错的（平台差异见模块 docstring「不在射程内」）。现在
    `try/except OSError`：异常照样不许崩掉整轮 prune，但**原因留着报出去**。
    「本来就不在」与「清不掉」的区分只在本函数里做，调用方不预先 filter `isdir` —— 那样
    `ABSENT` 就成了一条没人走的分支，判据会绿在 unreachable 代码上（这条取向与三态各一条
    用例都在 `PruneStuckDirectoryTests` / `PruneCountAgreementTests`）。
    """
    if not os.path.isdir(target):
        return Outcome.ABSENT, ''
    reason = ''
    try:
        shutil.rmtree(target)
    except OSError as exc:
        reason = f'{type(exc).__name__}: {exc}'
    if not os.path.isdir(target):
        return Outcome.REMOVED, ''          # 半路抛错但已经删干净了，仍算回收
    return Outcome.KEPT, reason or 'rmtree 没报错、目录却还在（失败被吞掉了）'


class Command(BaseCommand):
    help = '删除超过 N 天的已结束作业行及其结果目录'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--dry-run', action='store_true',
                            help='只打印要删什么，不动盘')

    def handle(self, *args, **options):
        days = options['days']
        if days < 0:
            raise CommandError('--days 不能为负')
        cutoff = timezone.now() - timedelta(days=days)
        stale = Job.objects.filter(
            status__in=TERMINAL_STATUSES,
            finished_at__lt=cutoff)

        removed_rows = 0
        removed_dirs = 0
        kept_dirs = 0
        for job in stale.iterator():
            if not _prunable(job, cutoff):
                continue
            targets = dir_targets(job)
            if options['dry_run']:
                # 原样保留 `would remove job <id> (<result_path>)` 这条前缀（运维在 grep
                # 它），后面补目录数：error 行的 result_path 是空的，只报它等于让运维以为
                # 「一行里没东西可清」，而真跑起来要删掉一整个几百 MB 的目录。
                # 数的是**真在盘上的**（`os.path.isdir` 过一遍），因为下面真跑报的「删目录
                # N」也只会数真正 reclaimed 掉的那些 —— 数候选就会一边说 1 个、一边说删 0
                # 个（判据 `PruneCountAgreementTests` 两条各钉一边，两处一起动才不红）。
                would = [t for t in targets if os.path.isdir(t)]
                self.stdout.write(f'would remove job {job.id} ({job.result_path})'
                                  + (f' → 目录 {len(would)} 个' if targets else ''))
                continue
            stuck = 0
            for target in targets:
                outcome, why = _remove_dir(target)
                if outcome == Outcome.REMOVED:
                    removed_dirs += 1
                elif outcome == Outcome.ABSENT:
                    continue        # 本来就不在：既不是回收，也不是留盘
                else:
                    # 只有点名的两种「可以删行」的结局才允许往下走；没点名的（将来新增的）
                    # 一律按留盘处理 —— 行留着可回滚，目录孤儿不可逆。
                    stuck += 1
                    kept_dirs += 1
                    self.stderr.write(f'job {job.id} 目录没收掉（{why}），'
                                      f'行保留、下一轮再试：{target}')
            if stuck:
                # 有一个目录没清掉就**不删行**：这里是执行体，取向的理由只在模块 docstring
                # 「有行索引的目录只由它自己的行删」那一节讲一遍；代价（被占住的行一直留着）
                # 由下面汇总里的 `留盘 N` 报出来。
                continue
            job.delete()
            removed_rows += 1

        self.stdout.write(self.style.SUCCESS(
            f'prune_jobs: {days} 天前的已结束作业 → 删行 {removed_rows}、'
            f'删目录 {removed_dirs}'
            + (f'、留盘 {kept_dirs}' if kept_dirs else '')
            + ('（dry-run，未改动）' if options['dry_run'] else '')))
