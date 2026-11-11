"""`scripts/gc_categories.py` 的判据（T1 层：注册表 + 选择器，纯函数，不碰真实数据根）。

与引擎判据（`test_test_data_gc.py`）按同一道接缝分开：这里只验「注册了哪些树、名字/缓存
发现选择器认不认」，不验 build_plan/execute。注册表函数无 IO 副作用（除 find_pycache 走临时目录），
所以直接 importlib 加载 gc_categories 即可，它不依赖 sibling import。

跑法：python manage.py test test.backend.test_gc_categories
"""
import importlib.util
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]


def _load_categories():
    path = REPO / 'scripts' / 'gc_categories.py'
    spec = importlib.util.spec_from_file_location('lqdp_gc_categories', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GC = _load_categories()


class RunDirNameTests(SimpleTestCase):
    def test_accepts_pool_run_ids(self):
        """池的 RUN_ID = `HHMMSS-<pid>`，复跑再带 `-recheckN`（e2e_pool.mjs:40,351）。"""
        self.assertTrue(GC.is_run_dir_name('075407-43428'))
        self.assertTrue(GC.is_run_dir_name('003042-29280-recheck0'))

    def test_rejects_everything_else(self):
        for name in ('template', 'slots', '.lock', 'slot0', '2026-10-24',
                     'abcd-1234', '7540-43428', '075407', 'notes'):
            self.assertFalse(GC.is_run_dir_name(name), name)


class ArtifactRootsTests(SimpleTestCase):
    """artifacts 注册表：可再生构建产物，整目录回收（删了下一轮 build 重建）。"""

    def test_artifact_roots_cover_the_regenerable_build_dirs(self):
        # 变异：漏注册某个产物目录（如 out/ 755M 大头）⇒ 集合不等；
        # 路径拼错（frontend/dist 写成根 dist）⇒ 路径断言红。
        roots = GC.artifact_roots()
        by_name = {r.name: r for r in roots}
        self.assertEqual({'out', 'dist', 'build', 'frontend-dist', 'electron-dist'},
                         set(by_name))
        for r in roots:
            self.assertEqual('self', r.pattern)
            self.assertEqual('artifacts', r.category)
        self.assertEqual(REPO / 'out', by_name['out'].path)
        self.assertEqual(REPO / 'dist', by_name['dist'].path)
        self.assertEqual(REPO / 'build', by_name['build'].path)
        self.assertEqual(REPO / 'frontend' / 'dist', by_name['frontend-dist'].path)
        self.assertEqual(REPO / 'frontend' / 'electron-dist',
                         by_name['electron-dist'].path)


class CacheRootsTests(SimpleTestCase):
    """caches 注册表：显式缓存目录（self）+ 一个 pycache 发现根。"""

    def test_cache_roots_cover_explicit_caches_plus_pycache(self):
        # 变异：漏注册 .vite（27M）或把 pycache 根写成 self ⇒ 集合/模式断言红。
        roots = GC.cache_roots()
        by_name = {r.name: r for r in roots}
        self.assertEqual({'vite', 'pytest-cache', 'superpowers', 'playwright-report',
                          'frontend-test-results', 'test-results', 'pycache'},
                         set(by_name))
        for r in roots:
            self.assertEqual('caches', r.category)
        self.assertEqual('pycache', by_name['pycache'].pattern)
        self.assertEqual('self', by_name['vite'].pattern)
        self.assertEqual(REPO / 'frontend' / 'node_modules' / '.vite',
                         by_name['vite'].path)
        self.assertEqual(REPO / '.pytest_cache', by_name['pytest-cache'].path)


class ScratchRootsTests(SimpleTestCase):
    """scratch 注册表：tasks 草稿（保 e2e-nightly）+ 夜跑轮次（保 LATEST.md/最新轮）+ 根 db 备份 + probe.local。"""

    def test_scratch_roots_registry(self):
        # 变异：漏注册或 keep 配错（如 tasks 不保 e2e-nightly）⇒ 断言红。
        roots = GC.scratch_roots()
        by_name = {r.name: r for r in roots}
        self.assertEqual({'tasks', 'e2e-nightly', 'db-backups', 'probe-local'},
                         set(by_name))
        for r in roots:
            self.assertEqual('scratch', r.category)
        self.assertEqual('glob', by_name['tasks'].pattern)
        self.assertIn('e2e-nightly', by_name['tasks'].keep)
        self.assertTrue(by_name['e2e-nightly'].keep_newest)
        self.assertIn('LATEST.md', by_name['e2e-nightly'].keep)
        self.assertIn('latest.json', by_name['e2e-nightly'].keep)
        self.assertEqual(REPO / 'tasks', by_name['tasks'].path)
        self.assertEqual(REPO / 'tasks' / 'e2e-nightly', by_name['e2e-nightly'].path)