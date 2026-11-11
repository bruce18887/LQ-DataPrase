"""`scripts/test_data_gc.py` 的判据（T1 层：纯函数 + 临时目录，不碰真实数据根）。

这个脚本默认 dry-run，真删要 `--apply`，所以**测试里绝不给它 `--apply` 去打真盘**：
被验的是「计划怎么形成」，不是「删得掉删不掉」。三条承重判据各挡一种变异：

  - 名字判据：只认 `HHMMSS-pid`（含 `-recheckN`），拼错的形状一律不认；
  - 路径判据：越界与「数据根落进真实目录」两种都得拒绝，且**合法路径必须放行**
    （否则判据可能永远返回 False，把脚本变成什么都不删的空壳还全绿）；
  - 年龄判据：正在跑的那轮 mtime 是新的，必须被跳过。

跑法：python manage.py test test.backend.test_test_data_gc
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]


def _load_gc():
    scripts = REPO / 'scripts'
    # importlib 不会把 scripts/ 放进 sys.path，而引擎要 import 同目录的 gc_categories。
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / 'test_data_gc.py'
    spec = importlib.util.spec_from_file_location('lqdp_test_data_gc', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GC = _load_gc()


class PathGuardTests(SimpleTestCase):
    def test_inside_accepts_child_and_refuses_escape(self):
        root = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, root, True)
        child = root / 'media' / 'data'
        self.assertTrue(GC.inside(root, child))
        self.assertFalse(GC.inside(root, root / '..' / 'elsewhere'))
        self.assertFalse(GC.inside(root, root), '树自己也不算「树内」，否则会把根删了')

    def test_protected_hits_the_real_data_dir_and_lets_test_roots_pass(self):
        real = Path(tempfile.mkdtemp(prefix='lqdp-gc-')) / 'LQ-DataPrase'
        real.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, real.parent, True)
        guard = [real.resolve()]
        self.assertTrue(GC.is_protected(real / 'media' / 'data' / 'x.csv', guard))
        self.assertTrue(GC.is_protected(real, guard), '禁区自己也必须拦住')
        self.assertFalse(GC.is_protected(REPO / 'test' / 'unit-data', guard))


class PlanTests(SimpleTestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.slots = self.base / 'slots'
        self.slots.mkdir()
        now = time.time()
        self.old_run = self._run_dir('021306-14928', now - 5 * 86400)
        self.live_run = self._run_dir('075407-43428', now)
        self.not_a_run = self._run_dir('template', now - 9 * 86400)

    def _run_dir(self, name, mtime):
        d = self.slots / name
        (d / 'slot0' / 'media').mkdir(parents=True)
        (d / 'slot0' / 'media' / 'a.csv').write_text('x' * 1024, encoding='utf-8')
        os.utime(d, (mtime, mtime))
        return d

    def _root(self):
        return GC.DataRoot('slots', self.slots, 'run_dir')

    def test_only_old_run_dirs_become_candidates(self):
        plan = GC.build_plan(self._root(), time.time(), 1.0, [])
        self.assertEqual([self.old_run], [p for p, _s, _m in plan.candidates])
        self.assertEqual(1, plan.skipped_newer, '正在跑的那轮得被龄限挡下')

    def test_protected_root_zeroes_the_plan(self):
        """数据根一旦落进真实目录，整棵树一项都不许进计划。"""
        plan = GC.build_plan(self._root(), time.time(), 1.0, [self.slots.resolve()])
        self.assertEqual([], plan.candidates)
        self.assertEqual(2, len(plan.refused_protected),
                         '两个 RUN_ID 形态的子目录都该被拒（template 不进候选判定）')

    def test_symlinked_root_is_refused_wholesale(self):
        if os.name != 'nt':
            link = self.base / 'slots-link'
            try:
                os.symlink(self.slots, link, target_is_directory=True)
            except OSError:
                self.skipTest('本机不允许建目录联接')
        else:
            self.skipTest('Windows 建目录联接需要特权，交真机验证')
        plan = GC.build_plan(GC.DataRoot('slots', link, 'run_dir'), time.time(), 1.0, [])
        self.assertEqual([], plan.candidates)
        self.assertEqual(1, len(plan.refused_outside))


class RootConfigTests(SimpleTestCase):
    def test_env_var_relocates_the_slot_root(self):
        tmp = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        old = os.environ.get('LQDP_E2E_ROOT')
        os.environ['LQDP_E2E_ROOT'] = str(tmp)
        self.addCleanup(lambda: os.environ.__setitem__('LQDP_E2E_ROOT', old)
                        if old is not None else os.environ.pop('LQDP_E2E_ROOT', None))
        roots = {r.name: r.path for r in GC.data_roots()}
        self.assertEqual(tmp / 'slots', roots['slots'])

    def test_in_repo_roots_stay_under_test_and_never_the_home_dir(self):
        roots = GC.data_roots()
        names = [r.name for r in roots]
        self.assertEqual(['slots', 'e2e-data', 'unit-data'], names)
        guards = GC.protected_roots()
        for r in roots:
            if r.name == 'slots':
                continue          # 槽根在盘外（C:/lqdp-e2e），由龄限与白名单管
            self.assertTrue(str(r.path).startswith(str(REPO / 'test')), r.path)
            self.assertFalse(GC.is_protected(r.path, guards),
                             f'{r.name} 落进了真实数据目录，护栏等于没装')


class HardlinkAccountingTests(SimpleTestCase):
    """体积必须按 inode 记账 —— 池就是靠硬链接喂夹具的（`e2e_pool.mjs:113`）。

    这一条是被真实数据逼出来的：按表观字节加总时 5.0GB 的槽根会报成 25.4GB，
    工具就从「帮你省盘」变成「骗你说省了」。
    """

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.slots = self.base / 'slots'
        self.slots.mkdir()
        try:
            self._link = os.link
        except AttributeError:
            self.skipTest('本机不支持硬链接')

    def _run(self, name, mtime, share_from=None, exclusive_mb=0):
        """造一轮目录：可选地从另一轮硬链过来，再放 exclusive_mb 的自有数据。"""
        d = self.slots / name
        (d / 'slot0').mkdir(parents=True)
        if share_from is not None:
            try:
                self._link(share_from, d / 'slot0' / 'fixture.csv')
            except OSError as exc:               # 跨卷 / 权限，本机做不到就跳过这条判据
                self.skipTest(f'本机建不了硬链接：{type(exc).__name__}')
        else:
            (d / 'slot0' / 'fixture.csv').write_bytes(b'x' * (1024 * 1024))
        for i in range(exclusive_mb):
            (d / 'slot0' / f'own{i}.bin').write_bytes(b'y' * (1024 * 1024))
        os.utime(d, (mtime, mtime))
        return d

    def _plan(self, now):
        return GC.build_plan(GC.DataRoot('slots', self.slots, 'run_dir'), now, 1.0, [])

    def test_shared_inode_counted_once(self):
        now = time.time()
        first = self._run('021306-14928', now - 5 * 86400)
        src = first / 'slot0' / 'fixture.csv'
        self._run('021400-14929', now - 4 * 86400, share_from=src)
        plan = self._plan(now)
        mb = 1024 * 1024
        self.assertEqual(2, len(plan.candidates))
        self.assertEqual(2 * mb, plan.apparent_bytes, '表观口径就是把同一份算两遍')
        self.assertEqual(1 * mb, plan.unique_bytes, '去重后只有一份')
        self.assertEqual(1, plan.multi_run_inodes, '那个夹具 inode 得被认成跨轮共享')

    def test_nothing_freeable_while_a_survivor_shares_it(self):
        """留着的那轮（太新）也硬链同一份夹具时，删旧轮**不会**掉空间。"""
        now = time.time()
        first = self._run('021306-14928', now - 5 * 86400)
        src = first / 'slot0' / 'fixture.csv'
        self._run('021400-14929', now - 4 * 86400, share_from=src)
        self._run('075407-43428', now, share_from=src)     # 幸存：太新
        plan = self._plan(now)
        mb = 1024 * 1024
        self.assertEqual(2, len(plan.candidates))
        self.assertEqual(1, plan.skipped_newer)
        self.assertEqual(1 * mb, plan.unique_bytes)
        self.assertEqual(0, plan.freeable_bytes, '夹具还被幸存轮引用着，一分都掉不了')

    def test_exclusive_bytes_are_freeable(self):
        now = time.time()
        first = self._run('021306-14928', now - 5 * 86400)
        src = first / 'slot0' / 'fixture.csv'
        self._run('021400-14929', now - 4 * 86400, share_from=src, exclusive_mb=2)
        self._run('075407-43428', now, share_from=src)
        plan = self._plan(now)
        mb = 1024 * 1024
        self.assertEqual(3 * mb, plan.unique_bytes)         # 夹具 1MB + 自有 2MB
        self.assertEqual(2 * mb, plan.freeable_bytes, '只有自有数据删得掉')


class ApplyPathTests(SimpleTestCase):
    """`--apply` 的删除分支本身也得有例 —— 只在**临时根**上跑，绝不指向真实槽目录。

    这条同时钉两件相反的事：龄限内的该删干净，禁区里的一个字节都不能动。
    """

    def _sandbox(self, tmp, run_names, ages_days):
        slots = tmp / 'slots'
        now = time.time()
        for name, age in zip(run_names, ages_days):
            d = slots / name / 'slot0'
            d.mkdir(parents=True)
            (d / 'a.csv').write_text('x' * 2048, encoding='utf-8')
            os.utime(slots / name, (now - age * 86400, now - age * 86400))
        return slots

    def test_apply_removes_only_older_than_the_limit(self):
        tmp = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        slots = self._sandbox(tmp, ['021306-14928', '075407-43428'], [5, 0.1])
        env_backup = os.environ.get('LQDP_E2E_ROOT')
        os.environ['LQDP_E2E_ROOT'] = str(tmp)
        self.addCleanup(lambda: (os.environ.__setitem__('LQDP_E2E_ROOT', env_backup)
                                 if env_backup is not None
                                 else os.environ.pop('LQDP_E2E_ROOT', None)))
        # 脚本的报告是给人看的，跑测试时别把它喷进套件输出（后端全量日志里混进表格会干扰判读）
        with contextlib.redirect_stdout(io.StringIO()):
            rc = GC.main(['--only', 'slots', '--apply'])
        self.assertEqual(0, rc)
        self.assertFalse((slots / '021306-14928').exists(), '超龄的孤儿轮该没了')
        self.assertTrue((slots / '075407-43428').is_dir(), '正在跑的那轮必须原样留着')

    def test_apply_refuses_a_root_inside_the_real_data_dir(self):
        """把槽根「伪造成」真实数据目录的样子：护栏必须在删除之前就把计划清零。"""
        tmp = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        real = tmp / 'LQ-DataPrase'
        slots = self._sandbox(real, ['021306-14928'], [5])
        plan = GC.build_plan(GC.DataRoot('slots', slots, 'run_dir'),
                             time.time(), 1.0, [real.resolve()])
        self.assertEqual([], plan.candidates)
        deleted, failed = GC.execute([plan], True)
        self.assertEqual((0, 0), (deleted, failed))
        self.assertTrue((slots / '021306-14928' / 'slot0' / 'a.csv').is_file(),
                        '护栏失守时这条会当场变红')


class CliGuardTests(SimpleTestCase):
    """这两条只验「拒绝启动」，不会走到删除。"""

    def test_unknown_root_name_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, GC.main(['--only', 'slots,typo']))

    def test_zero_age_limit_is_refused(self):
        """`--older-than-days 0` 等于关掉在跑守卫，`--apply` 会删掉别的会话正在用的槽。"""
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, GC.main(['--older-than-days', '0', '--apply']))


class SelfPatternTests(SimpleTestCase):
    """`self` 模式：整目录本身成一个候选（可再生构建产物用），复用同一套保护区护栏。

    与 run_dir/children 的区别：候选是「这棵树自己」而不是它的子项 —— 删 out/ 是整目录端掉，
    不是只删 out/ 里的子目录。`inside()` 对「树自己」返回 False，所以 self 走独立分支。
    """

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.artifact = self.base / 'out'
        (self.artifact / 'sub').mkdir(parents=True)
        (self.artifact / 'sub' / 'app.exe').write_bytes(b'x' * 2048)

    def test_self_yields_the_whole_dir_not_its_children(self):
        # 变异：若 build_plan 把 'self' 当 'children' 处理，候选会是 [out/sub] 而非 [out]。
        # 这条同时是「合法路径必须放行」的正对照（否则护栏恒 False，工具变空壳还全绿）。
        plan = GC.build_plan(GC.DataRoot('out', self.artifact, 'self'), time.time(), 1.0, [])
        self.assertEqual([self.artifact], [p for p, _s, _m in plan.candidates])
        self.assertEqual(2048, plan.unique_bytes)
        self.assertEqual(2048, plan.freeable_bytes, 'self 没有幸存树共享，删完即掉全部')

    def test_self_refuses_a_protected_path(self):
        # 变异：若 'self' 分支漏掉 is_protected，真实数据目录会被整目录端掉。
        plan = GC.build_plan(GC.DataRoot('out', self.artifact, 'self'),
                             time.time(), 1.0, [self.artifact.resolve()])
        self.assertEqual([], plan.candidates)
        self.assertEqual(1, len(plan.refused_protected))

    def test_self_missing_path_is_empty_not_error(self):
        # 变异：若 'self' 不判存在性就去 scandir/stat，缺失目录会抛 OSError 而非空计划。
        plan = GC.build_plan(GC.DataRoot('out', self.base / 'nope', 'self'),
                             time.time(), 1.0, [])
        self.assertEqual([], plan.candidates)


class PycacheDiscoveryTests(SimpleTestCase):
    """__pycache__ 递归发现：只收仓库自有代码的，依赖/工作树里的不算（也不是我们的垃圾）。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        (self.base / 'apps' / '__pycache__').mkdir(parents=True)
        (self.base / 'scripts' / '__pycache__').mkdir(parents=True)
        (self.base / 'node_modules' / 'pkg' / '__pycache__').mkdir(parents=True)
        (self.base / '.venv' / 'lib' / '__pycache__').mkdir(parents=True)
        (self.base / '.worktrees' / 'x' / '__pycache__').mkdir(parents=True)
        self.want = {self.base / 'apps' / '__pycache__',
                     self.base / 'scripts' / '__pycache__'}

    def test_find_pycache_skips_deps_and_worktrees(self):
        # 变异：若 os.walk 不剪 node_modules/.venv/.worktrees，依赖里的 __pycache__ 会混进来。
        self.assertEqual(self.want, set(GC.find_pycache_dirs(self.base)))

    def test_pycache_pattern_yields_each_pycache_dir(self):
        # 变异：若 'pycache' 分支只收第一个或当成 self，候选集合不等于两个目录。
        plan = GC.build_plan(GC.DataRoot('pycache', self.base, 'pycache',
                                         category='caches'), time.time(), 1.0, [])
        self.assertEqual(self.want, {p for p, _s, _m in plan.candidates})


class GlobPatternTests(SimpleTestCase):
    """glob 模式：按 glob 选子项（含散文件），keep 命名保护 + keep_newest 保最新 + 龄限。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.now = time.time()

    def _mk(self, rel, age_days, is_dir=True):
        p = self.base / rel
        if is_dir:
            p.mkdir(parents=True)
            (p / 'f.txt').write_text('x' * 1024, encoding='utf-8')
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('x' * 1024, encoding='utf-8')
        os.utime(p, (self.now - age_days * 86400, self.now - age_days * 86400))
        return p

    def test_glob_keeps_named_children_and_age_guards(self):
        # 变异：若 glob 不认 keep，e2e-nightly 会被删；若不龄限，fresh 也进候选。
        old = self._mk('perf-old', 5)
        self._mk('perf-fresh', 0.1)
        self._mk('e2e-nightly', 9)
        root = GC.DataRoot('tasks', self.base, 'glob', category='scratch',
                           glob='*', keep=frozenset({'e2e-nightly'}))
        plan = GC.build_plan(root, self.now, 1.0, [])
        self.assertEqual([old], [p for p, _s, _m in plan.candidates])
        self.assertEqual(1, plan.skipped_newer)

    def test_glob_keep_newest_protects_latest_round(self):
        # 变异：若 keep_newest 失效，最新一轮（虽超龄）会被删，LATEST.md 的本地明细引用就断。
        old = self._mk('2026-09-01', 30)
        newest = self._mk('2026-10-27', 15)
        self._mk('LATEST.md', 15, is_dir=False)
        root = GC.DataRoot('e2e-nightly', self.base, 'glob', category='scratch',
                           glob='*', keep=frozenset({'LATEST.md', 'latest.json'}),
                           keep_newest=True)
        plan = GC.build_plan(root, self.now, 1.0, [])
        self.assertEqual([old], [p for p, _s, _m in plan.candidates])
        self.assertTrue(newest.is_dir(), '最新一轮必须留着')

    def test_glob_candidates_include_files(self):
        # 变异：若 glob 沿用 children 的「只收目录」，db 备份散文件永远进不了候选。
        bak = self._mk('db.sqlite3.bak-old', 5, is_dir=False)
        root = GC.DataRoot('db-backups', self.base, 'glob', category='scratch',
                           glob='db.sqlite3.bak*')
        plan = GC.build_plan(root, self.now, 1.0, [])
        self.assertEqual([bak], [p for p, _s, _m in plan.candidates])
        self.assertEqual(1024, plan.unique_bytes)


class TrackedGuardTests(SimpleTestCase):
    """被 git 跟踪的文件绝不删：候选自身或内含跟踪文件则拒绝（与 keep 白名单相互独立）。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.now = time.time()

    def _mk(self, rel, age_days, is_dir=True):
        p = self.base / rel
        if is_dir:
            p.mkdir(parents=True)
            (p / 'f.txt').write_text('x' * 1024, encoding='utf-8')
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('x' * 1024, encoding='utf-8')
        os.utime(p, (self.now - age_days * 86400, self.now - age_days * 86400))
        return p

    def test_has_tracked_matches_self_and_descendant_not_sibling(self):
        # 变异：若只比相等不查后代，含跟踪文件的目录会被漏放；若前缀不带分隔符，
        # 'round' 会误命中 'round-clean'。空集必须放行（正对照，否则守卫恒 True 变空壳）。
        f = self._mk('round/a.txt', 5, is_dir=False)
        tracked = frozenset({f.resolve()})
        self.assertTrue(GC.has_tracked(self.base / 'round', tracked), '内含跟踪文件')
        self.assertTrue(GC.has_tracked(f, tracked), '候选自己就是跟踪文件')
        self.assertFalse(GC.has_tracked(self.base / 'round-clean', tracked), '兄弟目录不算')
        self.assertFalse(GC.has_tracked(self.base, frozenset()), '空跟踪集放行')

    def test_glob_refuses_candidate_containing_tracked_file(self):
        # 变异：若 glob 不查 tracked，含入库文件的轮次会被删；未跟踪的兄弟轮必须照常进候选。
        dirty = self._mk('round-tracked', 5)
        clean = self._mk('round-clean', 5)
        root = GC.DataRoot('tasks', self.base, 'glob', category='scratch', glob='*')
        plan = GC.build_plan(root, self.now, 1.0, [], frozenset({(dirty / 'f.txt').resolve()}))
        self.assertEqual([clean], [p for p, _s, _m in plan.candidates])
        self.assertEqual([str(dirty)], plan.refused_tracked)

    def test_apply_keeps_tracked_file_even_without_keep_whitelist(self):
        # 承重：LATEST.md 仅靠 tracked 守卫（故意不进 keep）也要在 --apply 后原样留着。
        nightly = self.base / 'e2e-nightly'
        old = self._mk('e2e-nightly/2026-09-01', 30)
        latest = self._mk('e2e-nightly/LATEST.md', 30, is_dir=False)
        root = GC.DataRoot('e2e-nightly', nightly, 'glob', category='scratch', glob='*')
        plan = GC.build_plan(root, self.now, 1.0, [], frozenset({latest.resolve()}))
        deleted, failed = GC.execute([plan], True)
        self.assertTrue(latest.is_file(), '跟踪文件 LATEST.md 必须在 --apply 后仍在')
        self.assertFalse(old.exists(), '未跟踪的旧轮该删掉（正对照）')
        self.assertEqual((1, 0), (deleted, failed))

    def test_tracked_files_lists_real_tracked_and_excludes_ignored(self):
        # 真实 git ls-files（只读）：manage.py 必在库，.venv 里的文件必不在（gitignored）。
        tracked = GC.tracked_files(REPO)
        self.assertIn((REPO / 'manage.py').resolve(), tracked)
        self.assertNotIn((REPO / '.venv' / 'pyvenv.cfg').resolve(), tracked)


class ElectronRootsTests(SimpleTestCase):
    """electron(opt-in)：只清白名单缓存子目录；media/secret.key/Local Storage 绝不动。

    Electron 的 userData 同时是 Django 的 LQDP_BASE_DIR（electron/backend-env.ts:37），
    里面住着 media/secret.key 等真实数据 —— 所以只能逐个注册缓存子目录，绝不注册 profile 根。
    """

    def setUp(self):
        self.profile = Path(tempfile.mkdtemp(prefix='lqdp-gc-'))
        self.addCleanup(shutil.rmtree, self.profile, True)
        (self.profile / 'Cache').mkdir()
        (self.profile / 'Cache' / 'junk.bin').write_bytes(b'x' * 2048)
        (self.profile / 'Code Cache').mkdir()
        (self.profile / 'Code Cache' / 'c.bin').write_bytes(b'y' * 1024)
        (self.profile / 'media').mkdir()
        (self.profile / 'media' / 'user.csv').write_text('precious', encoding='utf-8')
        (self.profile / 'secret.key').write_text('KEY', encoding='utf-8')
        (self.profile / 'Local Storage').mkdir()
        (self.profile / 'Local Storage' / 'leveldb').write_text('state', encoding='utf-8')

    def test_electron_roots_only_whitelisted_cache_subdirs(self):
        # 变异：若把 profile 根或 media/Network 注册成根，真实数据会被整目录端掉。
        roots = GC.electron_roots(self.profile)
        for r in roots:
            self.assertEqual('electron', r.category)
            self.assertEqual('self', r.pattern)
        paths = {r.path for r in roots}
        self.assertIn(self.profile / 'Cache', paths)
        self.assertIn(self.profile / 'Code Cache', paths)
        for forbidden in ('media', 'secret.key', 'Local Storage', 'Network',
                          'Session Storage', 'Preferences', ''):
            self.assertNotIn(self.profile / forbidden, paths, forbidden)

    def test_apply_cleans_cache_but_keeps_precious_data(self):
        # 承重：跑完 --apply，缓存没了，media/secret.key/Local Storage 一个字节都不动。
        roots = GC.electron_roots(self.profile)
        plans = [GC.build_plan(r, time.time(), 1.0, []) for r in roots]
        deleted, failed = GC.execute(plans, True)
        self.assertEqual((2, 0), (deleted, failed))
        self.assertFalse((self.profile / 'Cache').exists())
        self.assertFalse((self.profile / 'Code Cache').exists())
        self.assertEqual('precious',
                         (self.profile / 'media' / 'user.csv').read_text(encoding='utf-8'))
        self.assertEqual('KEY', (self.profile / 'secret.key').read_text(encoding='utf-8'))
        self.assertTrue((self.profile / 'Local Storage' / 'leveldb').is_file())

    def test_electron_profile_defaults_to_appdata_lowercase(self):
        # dev 档 userData 是小写 lq-dataprase（Windows 大小写不敏感，与打包档同目录）。
        old = os.environ.get('APPDATA')
        os.environ['APPDATA'] = str(self.profile.parent)
        self.addCleanup(lambda: os.environ.__setitem__('APPDATA', old)
                        if old is not None else os.environ.pop('APPDATA', None))
        self.assertEqual((self.profile.parent / 'lq-dataprase').resolve(),
                         GC.electron_profile())


class CliSelectionTests(SimpleTestCase):
    """C7：collect_roots 汇总五类；select_roots 默认剔 electron，--all/显式 --only 才收。"""

    def _roots(self):
        return [GC.DataRoot('slots', Path('x'), 'run_dir'),
                GC.DataRoot('vite', Path('z'), 'self', category='caches'),
                GC.DataRoot('electron-cache', Path('w'), 'self', category='electron')]

    def test_collect_roots_spans_all_five_categories(self):
        # 变异：漏接某一类注册表 ⇒ 类别集合不等。collect_roots 只造对象，不碰盘。
        cats = {r.category for r in GC.collect_roots()}
        self.assertEqual({'test-data', 'artifacts', 'caches', 'scratch', 'electron'}, cats)

    def test_default_excludes_electron(self):
        sel = GC.select_roots(self._roots(), set(), False)
        self.assertEqual({'slots', 'vite'}, {r.name for r in sel})

    def test_all_includes_electron(self):
        sel = GC.select_roots(self._roots(), set(), True)
        self.assertEqual({'slots', 'vite', 'electron-cache'}, {r.name for r in sel})

    def test_only_accepts_category_and_explicit_electron(self):
        # --only 认类别名（caches）；显式 --only electron 即 opt-in，无需 --all。
        self.assertEqual(['vite'],
                         [r.name for r in GC.select_roots(self._roots(), {'caches'}, False)])
        self.assertEqual(['electron-cache'],
                         [r.name for r in GC.select_roots(self._roots(), {'electron'}, False)])


class ReportGroupingTests(SimpleTestCase):
    def test_report_emits_a_subtotal_per_category(self):
        # 变异：若 report 平铺不分组，类别小计消失（count=0）⇒ 红；两类各一条小计。
        a = GC.Plan(root='out', category='artifacts')
        a.candidates.append((Path('out'), 2048, 0))
        a.unique_bytes = a.freeable_bytes = 2048
        c = GC.Plan(root='vite', category='caches')
        c.candidates.append((Path('vite'), 1024, 0))
        c.unique_bytes = c.freeable_bytes = 1024
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            GC.report([a, c], False, False, 0, 0)
        text = buf.getvalue()
        self.assertEqual(2, text.count('小计'))
        self.assertIn('artifacts', text)
        self.assertIn('caches', text)
