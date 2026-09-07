"""相关性散点 p_value 回归测试（2026-09-06 参照原型补能力批次）：

/analysis/correlation/ 此前只返回 pearson_r，散点 KPI 无显著性信息。
p_value 与 correlation_matrix 的 p_values 同一公式同一助手
（t = r*sqrt((n-2)/(1-r²))，双侧 p = 2*(1 - t_cdf(|t|, n-2))），
r 无定义（n<=2 或两轴 σ=0）时返回 None。

运行：``manage.py test test.backend.test_correlation_scatter_pvalue``
"""
import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.data_services import compute_correlation_scatter


class CorrelationPValueTests(SimpleTestCase):
    """compute_correlation_scatter 的 p_value 边界与对称性。"""

    @staticmethod
    def _df_xy(n: int = 200, seed: int = 7, noise: float = 0.1) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        x = rng.normal(0.0, 1.0, n)
        y = x + rng.normal(0.0, noise, n)
        return pd.DataFrame({'X': x, 'Y': y})

    def test_strong_r_large_n_gives_tiny_p(self):
        out = compute_correlation_scatter(self._df_xy(), 'X', 'Y')
        self.assertGreater(out['pearson_r'], 0.9)
        self.assertIsNotNone(out['p_value'])
        self.assertLess(out['p_value'], 1e-10)

    def test_p_in_unit_interval_and_symmetric(self):
        df = self._df_xy(noise=1.0)
        xy = compute_correlation_scatter(df, 'X', 'Y')
        yx = compute_correlation_scatter(df, 'Y', 'X')
        for o in (xy, yx):
            self.assertGreaterEqual(o['p_value'], 0.0)
            self.assertLessEqual(o['p_value'], 1.0)
        # r 与 p 对 x/y 互换均不变
        self.assertEqual(xy['pearson_r'], yx['pearson_r'])
        self.assertEqual(xy['p_value'], yx['p_value'])

    def test_independent_data_gives_high_p(self):
        # 双流取数：固定种子下独立样本也可能撞出 p<0.05（B11 场景本身成立），
        # 故选 r 极小的种子组合并断言 p>0.5 而非贴着 0.05 阈值
        df = pd.DataFrame({
            'A': np.random.default_rng(5).normal(0.0, 1.0, 500).tolist(),
            'B': np.random.default_rng(1005).normal(0.0, 1.0, 500).tolist(),
        })
        out = compute_correlation_scatter(df, 'A', 'B')
        self.assertLess(abs(out['pearson_r']), 0.05)
        self.assertGreater(out['p_value'], 0.5)

    def test_constant_column_p_is_none(self):
        df = pd.DataFrame({
            'A': [1.0, 2.0, 3.0, 4.0, 5.0],
            'C': [2.0, 2.0, 2.0, 2.0, 2.0],
        })
        out = compute_correlation_scatter(df, 'A', 'C')
        self.assertEqual(out['pearson_r'], 0.0)
        self.assertIsNone(out['p_value'])

    def test_tiny_sample_p_is_none(self):
        df = pd.DataFrame({'A': [1.0, 2.0], 'B': [2.0, 4.0]})
        out = compute_correlation_scatter(df, 'A', 'B')
        self.assertEqual(out['n'], 2)
        self.assertIsNone(out['p_value'])

    def test_p_not_rounded_to_zero_for_large_n(self):
        """round(p, 6) 会把大 n 的强相关 p（~1e-40）抹成 0.0——
        前端 formatPValue 的科学计数法分支永远吃不到真值，「p=0」语义错误。
        响应必须保留完整双精度（非 0、非 1、量级 <1e-10）。"""
        out = compute_correlation_scatter(self._df_xy(), 'X', 'Y')
        self.assertIsNotNone(out['p_value'])
        self.assertGreater(out['p_value'], 0.0)
        self.assertLess(out['p_value'], 1e-10)
