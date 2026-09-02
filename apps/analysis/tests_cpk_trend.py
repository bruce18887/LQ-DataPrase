"""CPK 计算、正态 PDF 曲线与逐文件限值的参数趋势回归测试。
（自 2473 行的 tests.py 按主题拆出，用例逐字搬迁。）
"""
import pandas as pd
import math
from django.test import SimpleTestCase


class ParamTrendPerFileLimitsTests(SimpleTestCase):
    """compute_param_trend 必须按文件独立解析规格限。

    回归：旧实现把第一个文件的 lsl/usl 复用到所有文件——不同批次/
    程序版本的规格不同时，后续文件的 CPK 数学上错误。
    """

    @staticmethod
    def _file(df, fid, mins, maxs):
        return {
            'df': df,
            'metadata': {'mins': mins, 'maxs': maxs, 'units': {}},
            'file_id': fid,
            'filename': f'f{fid}.csv',
            'timestamp': '',
        }

    def test_per_file_limits_drive_per_file_cpk(self):
        from apps.analysis.services.statistics.trends import compute_param_trend
        df = pd.DataFrame({'Param': [10.0, 10.2, 10.4]})
        files = [
            self._file(df.copy(), 1, {'Param': '9.0'}, {'Param': '11.0'}),
            self._file(df.copy(), 2, {'Param': '5.0'}, {'Param': '15.0'}),
        ]
        out = compute_param_trend(files, 'Param')

        self.assertEqual(out['trend_data'][0]['lsl'], 9.0)
        self.assertEqual(out['trend_data'][1]['lsl'], 5.0)
        # 同分布数据：限值越宽 → CPK 越大（文件 2 用自身限值而非文件 1 的）
        self.assertGreater(out['trend_data'][1]['cpk'], out['trend_data'][0]['cpk'])
        self.assertGreater(out['trend_data'][0]['cpk'], 0.0)
        # 响应级 limits 取首个完整对
        self.assertEqual(out['limits']['lsl'], 9.0)

    def test_file_without_limits_zero_cpk_and_later_file_keeps_own(self):
        from apps.analysis.services.statistics.trends import compute_param_trend
        df = pd.DataFrame({'Param': [10.0, 10.2, 10.4]})
        files = [
            self._file(df.copy(), 1, {}, {}),
            self._file(df.copy(), 2, {'Param': '9.0'}, {'Param': '11.0'}),
        ]
        out = compute_param_trend(files, 'Param')

        # 缺失限值（parse 回退 0.0 会算出负 CPK）→ lsl=None、cpk=0
        self.assertIsNone(out['trend_data'][0]['lsl'])
        self.assertEqual(out['trend_data'][0]['cpk'], 0.0)
        self.assertEqual(out['trend_data'][1]['lsl'], 9.0)
        self.assertGreater(out['trend_data'][1]['cpk'], 0.0)
        # 首个完整对来自文件 2
        self.assertEqual(out['limits']['lsl'], 9.0)


class NormalPdfCurveTests(SimpleTestCase):
    """normal_pdf_curve：高斯 PDF 公式单一来源（前端/导出/响应共用）。"""

    def test_formula_values(self):
        import math
        from apps.analysis.services.statistics import normal_pdf_curve
        # 奇数采样点 → 中心点恰为均值 0，可直接断言公式值
        curve = normal_pdf_curve(0.0, 1.0, -3.0, 3.0, n_points=201)
        self.assertEqual(len(curve), 201)
        center = curve[100]
        self.assertAlmostEqual(center[0], 0.0, places=5)
        self.assertAlmostEqual(center[1], 1 / math.sqrt(2 * math.pi), places=5)
        # 对称性
        self.assertAlmostEqual(curve[99][1], curve[101][1], places=6)

    def test_zero_std_returns_none(self):
        from apps.analysis.services.statistics import normal_pdf_curve
        self.assertIsNone(normal_pdf_curve(1.0, 0.0, 0.0, 2.0))
        self.assertIsNone(normal_pdf_curve(1.0, -1.0, 0.0, 2.0))

    def test_sampling_range(self):
        from apps.analysis.services.statistics import normal_pdf_curve
        curve = normal_pdf_curve(5.0, 2.0, 1.0, 9.0, n_points=100)
        self.assertEqual(curve[0][0], 1.0)
        self.assertEqual(curve[-1][0], 9.0)
        # 采样点单调
        xs = [c[0] for c in curve]
        self.assertEqual(xs, sorted(xs))


class ComputeCpkSingleSidedTests(SimpleTestCase):
    """compute_cpk 单边规格限：cp/pp 必须为 None（双侧才可定义），cpk/ppk 单侧可算。

    回归：缺失侧以 -inf/+inf 传入时 cp = inf，破坏 JSON 序列化且语义错误。
    """

    def test_lower_only_limit(self):
        from apps.analysis.services.statistics import compute_cpk
        result = compute_cpk(10.0, 1.0, float('-inf'), 12.0)
        self.assertIsNone(result['cp'])
        self.assertIsNone(result['pp'])
        self.assertEqual(result['cp_level'], 'N/A')
        self.assertEqual(result['cp_color'], 'gray')
        # 单侧能力 = (12-10)/(3*1) = 0.667
        self.assertAlmostEqual(result['cpk'], 0.6667, places=3)
        self.assertEqual(result['ppk'], result['cpk'])

    def test_upper_only_limit(self):
        from apps.analysis.services.statistics import compute_cpk
        result = compute_cpk(10.0, 1.0, 8.0, float('inf'))
        self.assertIsNone(result['cp'])
        self.assertAlmostEqual(result['cpk'], 0.6667, places=3)

    def test_both_limits_still_return_cp(self):
        from apps.analysis.services.statistics import compute_cpk
        result = compute_cpk(10.0, 1.0, 8.0, 12.0)
        self.assertAlmostEqual(result['cp'], 0.6667, places=3)
        self.assertIsNotNone(result['pp'])


class FilterFiniteTests(SimpleTestCase):
    """filter_finite：NaN/±inf 一步移除，等价于 dropna + inf 过滤。"""

    def test_removes_nan_and_inf(self):
        from apps.analysis.services.statistics import filter_finite
        series = pd.Series([1.0, float('nan'), 2.0, float('inf'), 3.0, float('-inf')])
        out = filter_finite(series)
        self.assertEqual(out.tolist(), [1.0, 2.0, 3.0])

    def test_index_preserved(self):
        from apps.analysis.services.statistics import filter_finite
        series = pd.Series([1.0, float('nan'), 2.0], index=['a', 'b', 'c'])
        out = filter_finite(series)
        self.assertEqual(out.index.tolist(), ['a', 'c'])

    def test_non_numeric_coerced_to_nan(self):
        from apps.analysis.services.statistics import filter_finite
        series = pd.Series([1.0, 'x', 2.0])
        out = filter_finite(series)
        self.assertEqual(out.tolist(), [1.0, 2.0])
