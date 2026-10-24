# -*- coding: utf-8 -*-
"""夹具形状断言：虚拟化后的素材必须仍具备解析测试依赖的全部结构特征。

T1（后端契约）档：只读文件、不碰 DB、不碰网络。跑本文件**不需要**本机存在任何真实样例
—— 所有断言的对象都是已入库的 `test/fixtures/weight/trim_weight_ci.csv` 那 11181 个字节。

数字来自对真实样例的实测（56 条声明 / 14 个名称 / 每名 4 次 / 长度集 {4,8,16,32,64} /
56 个 TAB / 112 个 CRLF / 1088 个恰好 5 位小数的值 / 结尾无换行），不是抄来的：见
scripts/make_weight_ci_fixture.py 的 EXPECTED_* 常量与 docstring 的 A 档（该 docstring
的 B 档专门列出了「只有重新生成时才跑、CI 够不着」的检查，别把两档混起来）。

为什么 TAB/CRLF 用**精确计数**而不是 `> 0`：`> 0` 挡不住部分规范化 —— 56 个 TAB 只换掉
30 个、112 个 CRLF 只转掉 100 个，文件依然「有 TAB 有 CRLF」而解析器（Task 2）要吃的正是
**每一条**声明里的那个分隔符。`test_tabs_and_crlf_survived_git` 依赖仓库根 `.gitattributes`
的 `test/fixtures/weight/*.csv -text` —— 本机 `core.autocrlf=true`，没有那条时 git 会把
CRLF 存成 LF，Linux runner 检出后每文件少 112 字节。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')
import django  # noqa: E402

django.setup()
from django.test import TestCase  # noqa: E402

PATH = os.path.join('test', 'fixtures', 'weight', 'trim_weight_ci.csv')
DECL_RE = re.compile(r'double\s+(\w+)\s*\[\s*(\d+)\s*\]\s*=\s*\{([^}]*)\}\s*;')
# 恰好 5 位小数：整数部分至少一位、必须有小数点、小数部分必须恰为 5 位（fullmatch 钉住两端）。
DECIMAL_RE = re.compile(r'-?\d+\.\d{5}')
EXPECTED_TABS = 56
EXPECTED_CRLFS = 112
EXPECTED_VALUES = 1088


class WeightFixtureShapeTests(TestCase):
    def setUp(self):
        with io.open(PATH, 'rb') as f:
            self.raw = f.read()
        self.text = self.raw.decode('utf-8')

    def test_counts_match_real_sample(self):
        decls = DECL_RE.findall(self.text)
        self.assertEqual(len(decls), 56)                      # 声明条数
        self.assertEqual(len({n for n, _, _ in decls}), 14)    # 不同名称数
        self.assertEqual(sorted({int(k) for _, k, _ in decls}), [4, 8, 16, 32, 64])

    def test_every_name_appears_four_times(self):
        counts = {}
        for name, _, _ in DECL_RE.findall(self.text):
            counts[name] = counts.get(name, 0) + 1
        self.assertEqual(set(counts.values()), {4})

    def test_tabs_and_crlf_survived_git(self):
        # 精确计数（不是 >0）：部分规范化 —— 换掉一部分 TAB、或把一部分 CRLF 转成裸 LF ——
        # 以前会带着「有 TAB / 有 CRLF」继续变绿，而解析器吃的是每条声明各自的分隔符。
        self.assertEqual(self.raw.count(b'\t'), EXPECTED_TABS,
                         'TAB 数不是 %d：`double` 与名称之间的分隔被动过（解析器要吃的就是它）'
                         % EXPECTED_TABS)
        self.assertEqual(self.raw.count(b'\r\n'), EXPECTED_CRLFS,
                         'CRLF 数不是 %d：autocrlf 或换行规范化把行尾改掉了' % EXPECTED_CRLFS)
        self.assertEqual(self.raw.count(b'\n'), EXPECTED_CRLFS,
                         'LF 总数 != CRLF 数：存在裸 LF，即 CRLF 被部分规范化')

    def test_no_trailing_newline(self):
        # 真实样例最后一个字符是 `;`、结尾没有换行；「结尾多一个换行」同样是形状漂移，
        # 而且正是按行切分的写法最容易受影响、却又不会让上面任何计数变红的一种。
        self.assertFalse(self.raw.endswith((b'\n', b'\r')), '文件结尾出现了换行')
        self.assertEqual(self.raw[-1:], b';', '夹具最后一个字符应当是 `;`')

    def test_every_value_has_exactly_five_decimals(self):
        # Task 2/4 的精度工作（容差、坐标轴自适应、格式化不吞精度）假设「每个值都是 5 位
        # 小数」。此前这一条只写在生成脚本的 docstring 里，谁都没查过 —— 连重新生成也不查。
        vals = [v.strip() for _, _, body in DECL_RE.findall(self.text)
                for v in body.split(',') if v.strip()]
        # 非空对照组：值总数本身先钉住，否则上面的推导一旦退化（例如花括号没捕获到内容），
        # 「每个值都合格」会在空列表上假绿。
        self.assertEqual(len(vals), EXPECTED_VALUES)
        bad = [v for v in vals if not DECIMAL_RE.fullmatch(v)]
        self.assertEqual(bad, [], '%d 个值不是「-?整数.恰好5位小数」，前 5 个：%r'
                                   % (len(bad), bad[:5]))

    def test_declared_length_equals_value_count(self):
        # 对照组：真实样例里「声明长度 != 实际值个数」的条数为 0，夹具必须还是 0。
        # 解析器（Task 2）拿 [] 里的数字当数组宽度，任何一条对不上都会让它静默截断或越界。
        bad = [(name, declared, len([v for v in values.split(',') if v.strip()]))
               for name, declared, values in DECL_RE.findall(self.text)
               if int(declared) != len([v for v in values.split(',') if v.strip()])]
        self.assertEqual(bad, [])

    def test_no_wiki_style_real_names(self):
        # 对照组：虚拟化后名称一律 WT####，任何非该形态的 5+ 字母名都说明漏替换
        bad = [n for n in re.findall(r'double\s+(\w+)\s*\[', self.text)
               if not re.fullmatch(r'WT\d{4}', n)]
        self.assertEqual(bad, [])
