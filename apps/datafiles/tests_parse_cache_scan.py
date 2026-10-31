"""共享缓存帧 / 共享 fail 格结果的静态护栏扫描（由 ``tests_parse_cache.py`` 整体搬来，
为 600 行硬线腾地方）。

两个扫描类各自自成一体：它们不建缓存、不碰 ``services`` 的运行时行为，只按各自的
``CARRIERS`` 清单扫消费者有没有在跨请求共享的对象上原地写。``SharedFrameSafetyTests``
的用例 2026-10-26 起逐字未改（含 ``DEFINITION_SITE`` 与 ``re`` / ``Path`` 两个专用 import）；
``SharedFailCellsSafetyTests`` 是 G2（2026-10-28）加的：fail 缓存去掉 owner 键之后，
``fail_cells`` / ``borderline_cells`` 从「一个 owner 的几个请求共享」变成「同一路径的所有
请求共享」（两个 dict 是同一只对象），只读约定必须同样有机械 owner。
``FailWritePatternShapeTests`` 自检扫描模式本身（嵌套写必须命中、浅拷贝不算豁免）。

发现方式：Django ``DiscoverRunner`` 的默认 pattern ``test*.py`` 覆盖
``tests_parse_cache_scan.py``，按模块点号路径也能单独跑
（``python manage.py test apps.datafiles.tests_parse_cache_scan``）。
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

from apps.datafiles import services

_FAIL_NAMES = ('fail_indices', 'fail_columns', 'fail_cells', 'borderline_cells')
_FAIL_MUTATORS = ('append', 'extend', 'insert', 'pop', 'remove', 'clear',
                  'update', 'setdefault', 'sort', 'reverse')


def _fail_write_pattern(names, mutators):
    """共享 fail 结果的原地写模式（拼接构造，见类 docstring ③）。

    三层都要覆盖：顶层改名（``fail_cells[1] = ...``）、**嵌套**改名
    （``fail_cells[1]['P1'] = ...``）、以及挂在名字或某一格上的 mutator
    （``fail_cells.append(...)`` / ``fail_cells[1].append(...)``）。
    旧的「名字后面直接跟 mutator」只抓得到第一层形状，``fail_cells[1].append(...)``
    整类漏扫 —— 由 ``FailWritePatternShapeTests`` 机械钉住。
    """
    alternation = '|'.join(mutators)
    return re.compile(
        '(?:' + '|'.join(
            r'\b' + n + r'\[[^\]]*\]\s*=[^=]' for n in names) + '|'
        + '|'.join(
            r'\b' + n + r'\[[^\]]*\]\[[^\]]*\]\s*=[^=]' for n in names) + '|'
        + '|'.join(
            r'\b' + n + r'\.(?:' + alternation + r')\(' for n in names) + '|'
        + '|'.join(
            r'\b' + n + r'\[[^\]]*\]\.(?:' + alternation + r')\(' for n in names) + '|'
        + '|'.join(r'\bdel\s+' + n + r'\[' for n in names) + ')')


class SharedFrameSafetyTests(SimpleTestCase):
    """缓存帧跨请求共享 ⇒ 消费者要改它必须先 copy。这条扫描把口头约定钉住。

    三个刻意的形状：
    ① **只在含 `get_cached_parsed_file` 的函数块里找原地写**，且写之前出现过
       `df = df.<method>(...)` 这种重新绑定（copy/astype/head…）就放行。朴素正则会在
       `apps/analysis/views/file_correlation_views.py:169-170` 那处「先 copy 再加辅助列」的
       **合规写法**上假红 —— 2026-10-26 预检实测就是这样，而假红的护栏最后没人看。
    ② 按**载体并集**扫，且「某个载体读不到」直接判红：2026-10-23 那次常量搬家后单文件扫描
       零命中、空集反而"相等"，就是假绿（见 docs/tasks/todo.md:5325-5329）。
    ③ 模式串用拼接构造，否则这条测试文件自己含住模式，会被自己抓到。

    已知局限（别当成完整防线）：放行规则是"同一函数块里先前有过重新绑定"，所以一个函数
    先 copy、之后再往**原对象**上写会漏；把缓存帧当参数传给别处去改也扫不到。
    这两类由 J1/J3 的行为断言兜（共享身份 + 并发同源），静态扫描只是第一道。
    """

    CARRIERS = [
        'apps/analysis/views/_helpers.py',
        'apps/analysis/views/analysis_views.py',
        'apps/analysis/views/file_correlation_views.py',
        'apps/batch_report/services.py',
        'apps/batch_report/views.py',
        'apps/buyoff/views.py',
        'apps/common/file_loading.py',
        'apps/dashboard/views.py',
        'apps/datafiles/views/browse_views.py',
        'apps/gage/views.py',
    ]
    CALL = 'get_cached_parsed_file'
    DEFINITION_SITE = 'apps/datafiles/services.py'   # 定义处，不是调用处
    WRITE = re.compile('(' + r'\bdf\[[^\]]+\]\s*=[^=]'
                       + '|' + r'\bdf\.(?:loc|iloc)\[[^\]]+\]\s*=[^=]'
                       + '|' + r'\bdf\.drop\([^)]*inplace=True'
                       + '|' + r'del df\[)')
    REBIND = re.compile(r'\bdf\s*=\s*df\.\w+\(')

    @staticmethod
    def _func_blocks(text):
        """按 def 切块（顶格与方法都切）：整类一块会把前一个方法的 copy 豁免漏给后一个。"""
        block, blocks = [], []
        for line in text.split('\n'):
            if re.match(r'^\s*(async )?def ', line) and block:
                blocks.append(block)
                block = []
            block.append(line)
        if block:
            blocks.append(block)
        return blocks

    def test_no_caller_mutates_the_shared_frame(self):
        root = Path(services.__file__).resolve().parents[2]
        scanned = 0
        for rel in self.CARRIERS:
            path = root / rel
            self.assertTrue(path.is_file(), f'载体清单过期：{rel} 读不到（假绿源头）')
            for block in self._func_blocks(path.read_text(encoding='utf-8')):
                if self.CALL not in '\n'.join(block):
                    continue
                rebound = False
                for line in block:
                    if self.REBIND.search(line):
                        rebound = True
                        continue
                    hit = self.WRITE.search(line)
                    if hit and not rebound:
                        self.fail(f'{rel} 在共享的缓存帧上原地写：{hit.group(0)}')
            scanned += 1
        self.assertEqual(scanned, len(self.CARRIERS),
                         '每个载体都必须真的被扫到，扫描数与清单数必须相等')

    def test_carriers_actually_contain_call_sites(self):
        """每个载体都必须真的有调用点，否则上面那条扫描是空跑。"""
        root = Path(services.__file__).resolve().parents[2]
        for rel in self.CARRIERS:
            text = (root / rel).read_text(encoding='utf-8')
            hits = [ln for ln in text.split('\n')
                    if self.CALL in ln and not ln.strip().startswith('#')]
            self.assertTrue(hits, f'{rel} 里一个 {self.CALL} 调用点都没有 —— 清单该更新了')

    def test_no_call_site_lives_outside_the_carrier_list(self):
        """新调用点必须显式进清单，不能悄悄长在扫描之外。"""
        root = Path(services.__file__).resolve().parents[2]
        listed = set(self.CARRIERS) | {self.DEFINITION_SITE}
        # 与 CARRIERS/DEFINITION_SITE 一样用「相对 root 的 posix 路径」比较：
        # root.glob 返回的是绝对路径（services.__file__ 已 resolve），直接
        # p.as_posix() 与相对清单永不相等 ⇒ 十个载体全被误判为「stray」。
        # 断言本体（stray==[]）不变：真长出清单外的调用点仍会以其相对路径出现并判红。
        stray = sorted(
            p.relative_to(root).as_posix() for p in root.glob('apps/**/*.py')
            if '__pycache__' not in p.as_posix()
            and 'test' not in p.name.lower()
            and self.CALL in p.read_text(encoding='utf-8', errors='ignore')
            and p.relative_to(root).as_posix() not in listed)
        self.assertEqual(stray, [], f'这些文件有调用点却不在 CARRIERS 里：{stray}')


class SharedFailCellsSafetyTests(SimpleTestCase):
    """``get_cached_fail_data`` 的四只返回值跨请求共享 ⇒ 消费者只许读。

    形状与 ``SharedFrameSafetyTests`` 逐条对齐（同一套理由，别在这里重写一遍）：

    ① 只有含 ``get_cached_fail_data`` 的函数块才查原地写；块内先出现过
       ``fail_cells = copy.deepcopy(fail_cells)`` 这类**深拷贝重绑定**就放行。
       ``dict(fail_cells)`` / ``{...}`` 不算：dict 的浅拷贝共享内层 list，
       ``copy = dict(fail_cells); copy[1].append(...)`` 改的仍是共享对象
       （反例由 ``FailWritePatternShapeTests`` 钉住）。
    ② 载体读不到直接判红（常量搬家后单文件扫描零命中 = 假绿）。
    ③ 模式串拼接构造：类属性里写死完整模式会被本文件自己命中（同族事故的成因）。

    已知局限与帧那份相同：把四只对象当参数传给别处去改扫不到；静态扫描只是第一道，
    共享身份由 ``test/backend/test_fail_cache_sharing.py`` 的行为判据兜。
    """

    CARRIERS = ['apps/datafiles/views/browse_views.py']
    CALL = 'get_cached_fail_data'
    DEFINITION_SITE = 'apps/datafiles/services.py'
    NAMES = _FAIL_NAMES
    MUTATORS = _FAIL_MUTATORS
    # 生成器表达式在类体里看不到 **同一个类体** 定义的 MUTATORS（Python 作用域规则），
    # 所以模式在模块级 _fail_write_pattern 里拼；类属性只做转发。
    WRITE = _fail_write_pattern(_FAIL_NAMES, _FAIL_MUTATORS)
    REBIND = re.compile(
        r'\b(?:' + '|'.join(_FAIL_NAMES) + r')\s*=\s*(?:copy\.)?deepcopy\(')

    @staticmethod
    def _func_blocks(text):
        """按 def 切块（顶格与方法都切）：整类一块会把前一个方法的 copy 豁免漏给后一个。"""
        block, blocks = [], []
        for line in text.split('\n'):
            if re.match(r'^\s*(async )?def ', line) and block:
                blocks.append(block)
                block = []
            block.append(line)
        if block:
            blocks.append(block)
        return blocks

    def test_no_caller_mutates_the_shared_fail_cells(self):
        root = Path(services.__file__).resolve().parents[2]
        scanned = 0
        for rel in self.CARRIERS:
            path = root / rel
            self.assertTrue(path.is_file(), f'载体清单过期：{rel} 读不到（假绿源头）')
            for block in self._func_blocks(path.read_text(encoding='utf-8')):
                if self.CALL not in '\n'.join(block):
                    continue
                rebound = False
                for line in block:
                    if self.REBIND.search(line):
                        rebound = True
                        continue
                    hit = self.WRITE.search(line)
                    if hit and not rebound:
                        self.fail(f'{rel} 在共享的 fail 结果上原地写：{hit.group(0)}')
            scanned += 1
        self.assertEqual(scanned, len(self.CARRIERS),
                         '每个载体都必须真的被扫到，扫描数与清单数必须相等')

    def test_carriers_actually_contain_call_sites(self):
        root = Path(services.__file__).resolve().parents[2]
        for rel in self.CARRIERS:
            text = (root / rel).read_text(encoding='utf-8')
            hits = [ln for ln in text.split('\n')
                    if self.CALL in ln and not ln.strip().startswith('#')]
            self.assertTrue(hits, f'{rel} 里一个 {self.CALL} 调用点都没有 —— 清单该更新了')

    def test_no_fail_call_site_lives_outside_the_carrier_list(self):
        """新调用点必须显式进清单，不能悄悄长在扫描之外（同帧那份的理由）。"""
        root = Path(services.__file__).resolve().parents[2]
        listed = set(self.CARRIERS) | {self.DEFINITION_SITE}
        stray = sorted(
            p.relative_to(root).as_posix() for p in root.glob('apps/**/*.py')
            if '__pycache__' not in p.as_posix()
            and 'test' not in p.name.lower()
            and self.CALL in p.read_text(encoding='utf-8', errors='ignore')
            and p.relative_to(root).as_posix() not in listed)
        self.assertEqual(stray, [], f'这些文件有调用点却不在 CARRIERS 里：{stray}')


class FailWritePatternShapeTests(SimpleTestCase):
    """扫描模式本身的自检：嵌套写必须命中，浅拷贝不许当豁免（见类 docstring ①）。"""

    def test_nested_and_top_level_writes_are_matched(self):
        for line in ("fail_cells[0] = ['P1']",
                     "fail_cells[0]['P1'] = 'X'",
                     "fail_cells[0].append('X')",
                     "borderline_cells[0].pop('P1')",
                     "del fail_cells[0]['P1']"):
            self.assertTrue(SharedFailCellsSafetyTests.WRITE.search(line),
                            f'漏扫的共享写形状：{line}')

    def test_shallow_copy_is_not_an_exemption(self):
        line = 'fail_cells = dict(fail_cells)'
        self.assertIsNone(SharedFailCellsSafetyTests.REBIND.search(line),
                          'dict(...) 共享内层 list，不是「复制一份再改」')
        self.assertTrue(SharedFailCellsSafetyTests.REBIND.search(
            'fail_cells = copy.deepcopy(fail_cells)'))

    def test_a_class_is_split_into_one_block_per_method(self):
        """方法 a 的 deepcopy 不许给方法 b 当豁免（整类一块时 b 的写会漏扫）。

        旧切块只认**顶格** ``def``：一个类、乃至整个没有顶层 def 的文件
        （``browse_views.py`` 就是类方法形状）都成了单块，于是 a 里的
        ``deepcopy`` 重绑定让 b 里的原地写不再被判红 —— 正是本用例的合成形状。
        """
        text = ('class C:\n'
                '    def a(self):\n'
                '        get_cached_fail_data(...)\n'
                '        fail_cells = copy.deepcopy(fail_cells)\n'
                '    def b(self):\n'
                '        get_cached_fail_data(...)\n'
                "        fail_cells[0] = ['P1']\n")
        for scanner in (SharedFrameSafetyTests, SharedFailCellsSafetyTests):
            blocks = scanner._func_blocks(text)
            b_blocks = [b for b in blocks
                        if any('def b' in line for line in b)]
            self.assertEqual(len(b_blocks), 1,
                             f'{scanner.__name__}: 方法 b 必须自成一块（旧切法整类一块）')
            b_block = b_blocks[0]
            self.assertFalse(any('deepcopy' in line for line in b_block),
                             f'{scanner.__name__}: a 的重绑定不许漏进 b 的块')
            self.assertTrue(SharedFailCellsSafetyTests.WRITE.search('\n'.join(b_block)),
                            '前提：b 块里确有要抓的原地写')
            self.assertTrue(
                any(any('deepcopy' in line for line in b) for b in blocks if b is not b_block),
                f'{scanner.__name__}: 前提：deepcopy 必须落在 a 那一块里')
