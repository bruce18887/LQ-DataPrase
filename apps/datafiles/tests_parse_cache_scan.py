"""共享缓存帧的静态护栏扫描（由 ``tests_parse_cache.py`` 整体搬来，为 600 行硬线腾地方）。

这个类自成一体：它不建缓存、不碰 ``services`` 的运行时行为，只按 ``CARRIERS``
清单扫消费者有没有在跨请求共享的缓存帧上原地写，用例 2026-10-26 起逐字未改
（含 ``DEFINITION_SITE`` 与 ``re`` / ``Path`` 两个专用 import）。

发现方式：Django ``DiscoverRunner`` 的默认 pattern ``test*.py`` 覆盖
``tests_parse_cache_scan.py``，按模块点号路径也能单独跑
（``python manage.py test apps.datafiles.tests_parse_cache_scan``）。
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

from apps.datafiles import services


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
        block, blocks = [], []
        for line in text.split('\n'):
            if re.match(r'^(async )?def ', line) and block:
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
