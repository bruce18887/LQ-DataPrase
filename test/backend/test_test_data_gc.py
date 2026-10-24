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
import tempfile
import time
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]


def _load_gc():
    path = REPO / 'scripts' / 'test_data_gc.py'
    spec = importlib.util.spec_from_file_location('lqdp_test_data_gc', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GC = _load_gc()


class RunDirNameTests(SimpleTestCase):
    def test_accepts_pool_run_ids(self):
        """池的 RUN_ID = `HHMMSS-<pid>`，复跑再带 `-recheckN`（e2e_pool.mjs:40,351）。"""
        self.assertTrue(GC.is_run_dir_name('075407-43428'))
        self.assertTrue(GC.is_run_dir_name('003042-29280-recheck0'))

    def test_rejects_everything_else(self):
        for name in ('template', 'slots', '.lock', 'slot0', '2026-10-24',
                     'abcd-1234', '7540-43428', '075407', 'notes'):
            self.assertFalse(GC.is_run_dir_name(name), name)


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
