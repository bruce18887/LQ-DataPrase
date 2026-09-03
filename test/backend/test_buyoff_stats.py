"""Buyoff 统计计算缺陷回归测试（缺陷 #3）。

``apps.buyoff.services.compute_buyoff_stats`` 原实现：
- ``float(metadata['mins'].get(param, 0))`` 对 ``'Min'`` / ``'N/A'`` / ``''``
  抛 ValueError 被吞 → ``lower = upper = 0.0``（**upper 的兜底也是 0**）；
- ``cp`` 有 ``tol > 0`` 守卫，``cpu`` / ``cpl`` / ``cpk`` 没有 → tol=0 时
  ``cpk = -|μ| / (3σ)``，报表出现巨大负 CPK；
- ``ca`` 在 tol==0 时返回 0.0（语义「完美居中」）——与事实相反。

修复口径：limit 不可解析 → ``None``；``ca`` / ``cp`` / ``cpk`` 一律 ``'N/A'``
（与 ``apps/export/excel_builders.py`` 的 None + 'N/A' 写法对齐）。

runner: ``manage.py test test.backend.test_buyoff_stats``
"""

import pandas as pd
from django.test import SimpleTestCase

from apps.buyoff.services import NA, compute_buyoff_stats, parse_limit


def _df(values, param='V_R'):
    return pd.DataFrame({param: values, 'SW_Bin': [1] * len(values)})


def _meta(min_raw, max_raw, param='V_R'):
    return {
        'format': 'CTA8290D',
        'units': {param: 'mV'},
        'mins': {param: min_raw},
        'maxs': {param: max_raw},
    }


class ParseLimitTests(SimpleTestCase):
    """限值解析：不可用一律 None（绝不静默兜底成 0.0）。"""

    def test_numeric_string(self):
        self.assertEqual(parse_limit('0.5'), 0.5)
        self.assertEqual(parse_limit('-1.25'), -1.25)

    def test_number_passthrough(self):
        self.assertEqual(parse_limit(2), 2.0)
        self.assertIsInstance(parse_limit(2), float)

    def test_non_numeric_keywords_are_none(self):
        for raw in ('Min', 'MAX', 'N/A', 'na', '-', 'none', '', '   '):
            self.assertIsNone(parse_limit(raw), f'{raw!r} 应为 None')

    def test_missing_and_junk_are_none(self):
        self.assertIsNone(parse_limit(None))
        self.assertIsNone(parse_limit('abc'))
        self.assertIsNone(parse_limit(float('nan')))
        self.assertIsNone(parse_limit(float('inf')))


class UnparsableLimitStatsTests(SimpleTestCase):
    """缺陷 #3-a：限值不可解析 → None + cp/ca/cpk 'N/A'。"""

    def test_text_limits_give_none_and_na(self):
        s = compute_buyoff_stats(_df([1.0, 1.1, 0.9, 100.0]),
                                 _meta('Min', 'N/A'), 'V_R')
        self.assertIsNone(s['lower_limit'])
        self.assertIsNone(s['upper_limit'])
        self.assertEqual(s['ca'], NA)
        self.assertEqual(s['cp'], NA)
        self.assertEqual(s['cpk'], NA)

    def test_empty_string_limits_give_none_and_na(self):
        s = compute_buyoff_stats(_df([1.0, 1.1, 0.9]), _meta('', ''), 'V_R')
        self.assertIsNone(s['lower_limit'])
        self.assertIsNone(s['upper_limit'])
        self.assertEqual(s['cpk'], NA)

    def test_one_sided_limit_gives_na(self):
        s = compute_buyoff_stats(_df([1.0, 1.1, 0.9]), _meta('0.5', 'N/A'), 'V_R')
        self.assertEqual(s['lower_limit'], 0.5)
        self.assertIsNone(s['upper_limit'])
        self.assertEqual(s['ca'], NA)
        self.assertEqual(s['cp'], NA)
        self.assertEqual(s['cpk'], NA)

    def test_missing_metadata_keys_do_not_raise(self):
        s = compute_buyoff_stats(_df([1.0, 1.1, 0.9]), {'format': 'CTA8290D'}, 'V_R')
        self.assertIsNone(s['lower_limit'])
        self.assertIsNone(s['upper_limit'])
        self.assertEqual(s['cpk'], NA)

    def test_none_metadata_does_not_raise(self):
        s = compute_buyoff_stats(_df([1.0, 1.1, 0.9]), None, 'V_R')
        self.assertEqual(s['cpk'], NA)

    def test_no_huge_negative_cpk_for_text_limits(self):
        """真实故障形态：μ=100、限值不可解析 → 旧实现给出 cpk≈-33.3。"""
        s = compute_buyoff_stats(_df([99.0, 100.0, 101.0]),
                                 _meta('Min', 'Max'), 'V_R')
        self.assertEqual(s['cpk'], NA)


class ZeroToleranceStatsTests(SimpleTestCase):
    """缺陷 #3-b：tol == 0 时 ca/cp/cpk 全部 'N/A'（不是 0.0 / 巨大负数）。"""

    def test_zero_tolerance_gives_na(self):
        s = compute_buyoff_stats(_df([99.0, 100.0, 101.0]),
                                 _meta('100', '100'), 'V_R')
        self.assertEqual(s['lower_limit'], 100.0)
        self.assertEqual(s['upper_limit'], 100.0)
        self.assertEqual(s['ca'], NA, 'ca=0.0 语义是「完美居中」，与 tol=0 事实相反')
        self.assertEqual(s['cp'], NA)
        self.assertEqual(s['cpk'], NA)

    def test_zero_limits_give_na_not_negative_cpk(self):
        """上下限都为 0（旧的兜底值）同样必须 'N/A'。"""
        s = compute_buyoff_stats(_df([99.0, 100.0, 101.0]), _meta('0', '0'), 'V_R')
        self.assertEqual(s['ca'], NA)
        self.assertEqual(s['cp'], NA)
        self.assertEqual(s['cpk'], NA)

    def test_zero_std_gives_na_cp_cpk_but_numeric_ca(self):
        """σ=0：cp/cpk 无定义 → 'N/A'；ca（居中比）在 tol>0 时仍可算。"""
        s = compute_buyoff_stats(_df([1.0, 1.0, 1.0]), _meta('0.5', '1.5'), 'V_R')
        self.assertEqual(s['std'], 0.0)
        self.assertEqual(s['cp'], NA)
        self.assertEqual(s['cpk'], NA)
        self.assertIsInstance(s['ca'], float)
        self.assertAlmostEqual(s['ca'], 0.0)


class ValidLimitStatsTests(SimpleTestCase):
    """正向对照：限值可用时仍给出数值型 ca/cp/cpk。"""

    def test_numeric_cpk(self):
        s = compute_buyoff_stats(_df([0.9, 1.0, 1.1, 1.0, 0.95]),
                                 _meta('0.5', '1.5'), 'V_R')
        self.assertEqual(s['lower_limit'], 0.5)
        self.assertEqual(s['upper_limit'], 1.5)
        for key in ('ca', 'cp', 'cpk'):
            self.assertIsInstance(s[key], float, f'{key} 应为数值')
        self.assertGreater(s['cp'], 0)
        self.assertGreater(s['cpk'], 0)

    def test_descriptive_stats_untouched(self):
        s = compute_buyoff_stats(_df([1.0, 2.0, 3.0]), _meta('0', '4'), 'V_R')
        self.assertEqual(s['min'], 1.0)
        self.assertEqual(s['max'], 3.0)
        self.assertEqual(s['range'], 2.0)
        self.assertEqual(s['mean'], 2.0)

    def test_empty_column_returns_empty_dict(self):
        s = compute_buyoff_stats(_df([None, None]), _meta('0', '1'), 'V_R')
        self.assertEqual(s, {})
