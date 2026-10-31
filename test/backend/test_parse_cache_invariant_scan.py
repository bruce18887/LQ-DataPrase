"""T1：把 G1 散文里的两个**数目**做成机械判据（2026-10-28 质量收口轮）。

动机：``services.py`` 的 ``evict_keys`` docstring 说「唤醒等待者的只有三处 ``notify_all``」，
本波三份判据文件说「八个调用点」。两句今天都成立，但**没有任何后续编辑有义务维持它们** ——
散文只能由人记住，判据才会替人守着。形状照仓里既有的先例
``apps/datafiles/tests_parse_cache_scan.py`` 的 ``CARRIERS``：载体读不到就**当场红**，
绝不让「空集合 == 空集合」变成假绿。

① ``_BytesLRUCache`` 里 ``notify_all`` 的**来源**只有 ``get_or_compute``（发布段 + 异常释放段）
   与 ``put``（写透），``evict_keys`` 一处都没有 ⇒ 「定点淘汰不丢唤醒」是结构事实，
   不是 ``evict_keys`` docstring 第 3 条里那句口头承诺。
② ``evict_parse_cache_for_paths`` 的**调用点集合**逐文件钉死 ⇒ 长出第 9 个调用点、
   某个调用点悄悄改回 ``clear_parse_cache()``、或者函数被改名，都会红。

两条都走 **AST** 而不是正则：``services.py`` 的 docstring 里就写着「三处 ``notify_all``」，
``clear_parse_cache`` 的 docstring 里也写着 ``evict_parse_cache_for_paths(...)``，正则会把这些
**提及**数成调用（假红）；AST 只认真出现的 ``Call`` 节点。
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

from apps.datafiles import services


def _call_target_name(node):
    """Call 节点的被调名：``f(...)`` 取 ``f``，``a.f(...)`` 取 ``f``。"""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class NotifyAllSourceScanTests(SimpleTestCase):
    """① 「三处 notify_all」是结构事实：只有发布段、异常释放段、写透那三处。"""

    CLASS = '_BytesLRUCache'
    EXPECTED = {'get_or_compute': 2, 'put': 1}
    TOTAL = 3

    def _notify_counts(self):
        source = Path(services.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        classes = [n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == self.CLASS]
        # 载体读不到就红（先例是「十个载体全被误判」，这里是「一只类找不到 ⇒ 空 dict 照样相等」）
        self.assertEqual(
            len(classes), 1,
            f'{self.CLASS} 必须在 services.py 里定义且只定义一次，找到 {len(classes)} 处 '
            f'—— 搬家/改名了就先改这条判据，别让它空跑')
        counts = {}
        for func in classes[0].body:
            if not isinstance(func, ast.FunctionDef):
                continue
            hits = sum(1 for node in ast.walk(func)
                       if isinstance(node, ast.Call)
                       and _call_target_name(node) == 'notify_all')
            if hits:
                counts[func.name] = hits
        return counts

    def test_notify_all_only_comes_from_publish_and_put(self):
        """唤醒等待者的只有 ``get_or_compute`` 的两处与 ``put`` 的一处。"""
        self.assertEqual(
            self._notify_counts(), self.EXPECTED,
            '``evict_keys`` 的 docstring 第 3 条说「唤醒等待者的只有三处 notify_all」：'
            '发布段两处 + 写透一处。多一处/少一处/换方法都得先改那句散文')

    def test_evict_keys_never_notifies_and_total_is_the_proven_three(self):
        counts = self._notify_counts()
        self.assertEqual(counts.get('evict_keys', 0), 0,
                         '定点淘汰一旦开始 notify，「它插在中间也不会把挂在同一 key 上等待的'
                         '人丢下」这条论证就换了前提（interleave 第 4 例钉的是行为，'
                         '本条钉的是结构）')
        self.assertEqual(sum(counts.values()), self.TOTAL,
                         '「三处」这个数目本身就是 services.py:192 那句的承诺')


class EvictCallSiteScanTests(SimpleTestCase):
    """② 八个调用点：数量、归属文件、每个文件几处，全部钉住。"""

    CALL = 'evict_parse_cache_for_paths'
    DEFINITION_SITE = 'apps/datafiles/services.py'
    EXPECTED_SITES = {
        'apps/datafiles/views/_helpers.py': 1,       # _delete_duplicate_files
        'apps/datafiles/views/file_views.py': 4,     # destroy / bulk_delete / combine / uncombine
        'apps/datafiles/views/browse_views.py': 1,   # _delete_orphaned_db
        'apps/datafiles/views/batch_views.py': 2,    # 批次目录 / 子批目录
    }
    TOTAL = 8

    @staticmethod
    def _root():
        return Path(services.__file__).resolve().parents[2]

    def _call_counts(self):
        root = self._root()
        counts = {}
        for path in sorted(root.glob('apps/**/*.py')):
            rel = path.relative_to(root).as_posix()
            # 只跳「测试模块命名法」（``test*.py``，本仓的 apps 测试一律叫 tests*.py）：
            # 比先例的「名字里含 test」更窄 —— 像 ``seed_test_data.py`` 那种生产命令
            # 照样进扫描，免得将来有人在它里面长出一个调用点却扫不到。
            if '__pycache__' in rel or path.name.startswith('test'):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
            hits = sum(1 for node in ast.walk(tree)
                       if isinstance(node, ast.Call)
                       and _call_target_name(node) == self.CALL)
            if hits:
                counts[rel] = hits
        return counts

    def test_definition_site_is_the_only_definition(self):
        """函数还在、还在 ``services.py``：改名/搬家先红这里，别让下面的扫描空跑。"""
        self.assertTrue(callable(getattr(services, self.CALL, None)),
                        f'{self.CALL} 已经不是 services 的可调用成员了')
        self.assertTrue((self._root() / self.DEFINITION_SITE).is_file(),
                        '定义处读不到')

    def test_carrier_files_are_readable(self):
        root = self._root()
        for rel in self.EXPECTED_SITES:
            self.assertTrue((root / rel).is_file(), f'载体清单过期：{rel} 读不到')

    def test_call_sites_are_exactly_the_pinned_set(self):
        """第 9 个调用点、改回 ``clear_parse_cache()``、改名 —— 三种走法都会红在这里。"""
        got = self._call_counts()
        extra = sorted(set(got) - set(self.EXPECTED_SITES))
        missing = sorted(set(self.EXPECTED_SITES) - set(got))
        count_diff = [(rel, got.get(rel), want) for rel, want
                      in self.EXPECTED_SITES.items() if got.get(rel) != want]
        self.assertEqual(
            got, self.EXPECTED_SITES,
            f'调用点集合与清单不符：多出来 {extra}，少了 {missing}，'
            f'同文件处数不同 {count_diff}。新调用点要连着判据一起进清单'
            '（并且必须是**按路径**淘汰，不是把 ``clear_parse_cache()`` 请回来）')
        self.assertEqual(sum(got.values()), self.TOTAL,
                         '「八个调用点」是本波三份判据文件里的说法，数目由这条守着')
