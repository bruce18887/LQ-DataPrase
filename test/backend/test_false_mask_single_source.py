"""全 False 掩码的单一来源（I 波 · 项 5）。

``pd.Series([False] * len(x), index=x.index)`` 曾在统计侧复制了 4 份
（``site_yield._no_mask``、``site_yield._limit_fail_mask``、
``site_yield.compute_wafer_fail_data``、``limits._scan_limit_cells``）。它们是同一个
东西：**与 x 同索引、全 False 的掩码**，下游一律只用 ``|`` / ``&`` / ``~`` /
布尔索引 / ``.sum()``。复制品的风险不是性能而是漂移：改一份（例如给空索引补 dtype）
另外三份不会跟着改，而它们出现在同一条良率链路上。

现在只有 ``helpers.false_mask(index)`` 一处，本用例扫描 ``apps/`` 钉住那个**表达式**
只出现一次（AST 匹配，注释/字符串里的同形文本不算），并用行为判据钉住契约：索引保留；
**非空索引**上 dtype 是 bool，**空索引**沿用旧内联写法的 object
（本机 pandas 3.0.3 实测，见 ``test_empty_index_keeps_the_legacy_object_dtype``）。
"""
import ast
from pathlib import Path

import pandas as pd
from django.test import SimpleTestCase

APPS_DIR = Path(__file__).resolve().parents[2] / 'apps'
HELPERS_REL = 'analysis/services/statistics/helpers.py'


def _is_false_list_times_len(node):
    """``[False] * len(<expr>)`` 的精确形状（空格/换行无关，注释字符串不参与）。"""
    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mult)
        and isinstance(node.left, ast.List)
        and len(node.left.elts) == 1
        and isinstance(node.left.elts[0], ast.Constant)
        and node.left.elts[0].value is False
        and isinstance(node.right, ast.Call)
        and isinstance(node.right.func, ast.Name)
        and node.right.func.id == 'len'
        and len(node.right.args) == 1
    )


def _false_mask():
    """延迟 import：helper 缺席时也要先看到**扫描**那条红（它报的是 4 处命中），
    而不是整模块 ImportError 把两条判据一起盖掉。"""
    from apps.analysis.services.statistics.helpers import false_mask
    return false_mask


class FalseMaskSingleSourceTests(SimpleTestCase):
    """``[False] * len(...)`` 只能出现在 ``statistics/helpers.py`` 里。"""

    def test_literal_appears_exactly_once_and_in_helpers(self):
        hits = []
        for path in sorted(APPS_DIR.rglob('*.py')):
            rel = path.relative_to(APPS_DIR).as_posix()
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=rel)
            for node in ast.walk(tree):
                if _is_false_list_times_len(node):
                    hits.append(f'{rel}:{node.lineno}')
        self.assertEqual(
            [hit.split(':')[0] for hit in hits], [HELPERS_REL],
            '全 False 掩码只能由 helpers.false_mask 构造（当前命中：%r）' % hits)

    def test_false_mask_keeps_the_index_and_is_bool(self):
        index = pd.Index([7, 3, 11], name='row')
        mask = _false_mask()(index)
        self.assertEqual(len(mask), 3)
        self.assertEqual(mask.index.tolist(), [7, 3, 11])
        self.assertEqual(mask.index.name, 'row')
        self.assertFalse(bool(mask.any()))
        self.assertEqual(str(mask.dtype), 'bool')

    def test_empty_index_keeps_the_legacy_object_dtype(self):
        """空索引上列表字面量得 object、``pd.Series(False, index=…, dtype=bool)`` 得 bool。

        这是**本机实测**的 pandas 3.x 事实（`.venv` 3.0.3），不是接口承诺：本函数是四处
        内联字面量的逐字替代品，空掩码的 dtype 也要逐字相同，所以函数体才保留列表写法。
        升级 pandas 时重测这一条，别把它当「dtype 永远是 object」的外推。
        """
        mask = _false_mask()(pd.Index([]))
        self.assertEqual(len(mask), 0)
        self.assertEqual(str(mask.dtype), 'object')

    def test_false_mask_accepts_a_non_default_index(self):
        """真实调用点传的是 ``df.index``（可能被 reset / 过滤成非 0..n-1）与
        ``data_series.index``；索引必须逐元素保留，否则掩码与数据错位。"""
        series = pd.Series([1.5, -2.0, 3.25], index=['r9', 'r4', 'r7'])
        mask = _false_mask()(series.index)
        self.assertEqual(mask.index.tolist(), ['r9', 'r4', 'r7'])
        self.assertFalse(bool(mask.any()))

    def test_false_mask_composes_like_the_inline_literals_it_replaced(self):
        series = pd.Series([1.0, 5.0, 9.0])
        combined = _false_mask()(series.index) | (series > 6.0)
        self.assertEqual(combined.tolist(), [False, False, True])
        self.assertEqual(int(combined.sum()), 1)
        self.assertEqual(series[~combined].tolist(), [1.0, 5.0])
