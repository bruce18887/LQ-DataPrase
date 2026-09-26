"""箱线图对「非数值列」的视图层契约（从 e2e 下沉，2026-09-26）。

来源：``frontend/e2e/analysis/boxplot-bool-params.spec.ts`` 的两条用例整文件都是
API 级断言（400 / error 码 / requested 载荷），跑一次要付 gotoApp + 两次带 JWT 的
fetch ≈ 5s/例，而判据完全不依赖浏览器 —— 属于三层判据里的 T1，故搬到后端层。

被锁的行为在 ``apps/analysis/views/_helpers.py:_sanitize_numeric_params``：
bool 列 ``is_numeric_dtype`` 为真但被显式剔除（pass/fail 标志画箱线无意义，且历史上
``.quantile()`` 会抛 "numpy boolean subtract"），str 列同样剔除；全被剔完时视图返回
400 ``no_valid_params`` 并带 ``requested``/``missing`` 载荷。

关键区分（e2e 原来没锁住）：``missing`` 只在「列不存在于文件」时非空；
列存在但不可测时 ``missing == []``。把这两件事混成一个信号，前端就无法区分
「切文件后参数失效」与「该参数本就不该画」。

运行：``manage.py test test.backend.test_boxplot_nonnumeric_params``
"""
import types

import pandas as pd
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.analysis.views import statistics_views
from apps.analysis.views.statistics_views import StatisticsViewSet


def _call_boxplot(df, params):
    """用给定 DataFrame 打 GET /statistics/boxplot/，返回 DRF response。

    直接 monkey-patch 加载器，不碰数据库：视图在 df.columns 分支上就决定了 400/200，
    真实 DataFile 与解析结果对本判据无贡献（同 apps/analysis/tests_param_guards.py 手法）。
    """
    original = statistics_views._load_df_from_request

    def fake_load(request):
        return (
            df,
            types.SimpleNamespace(id=1, filename='fake.csv', format_type='CTA8290D'),
            {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}},
            None,
        )

    statistics_views._load_df_from_request = fake_load
    request = APIRequestFactory().get(
        '/api/v1/statistics/boxplot/', {'file_id': 1, 'params': params}
    )
    force_authenticate(request, user=types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False,
    ))
    try:
        response = StatisticsViewSet.as_view({'get': 'boxplot'})(request)
        response.render()
        return response
    finally:
        statistics_views._load_df_from_request = original


class BoxplotNonNumericColumnTests(SimpleTestCase):
    """bool / str 列在视图层被剔除后的响应形态。"""

    def _df(self):
        return pd.DataFrame({
            'Param0': [1.0, 2.0, 3.0, 4.0],
            'Dut_Pass': [True, False, True, True],
            'Site #': ['1', '2', '1', '2'],
        })

    def test_bool_column_only_returns_400_no_valid_params(self):
        """文件里存在的 bool 列（Dut_Pass）→ 400，而不是 service 层退化箱线或 500。"""
        response = _call_boxplot(self._df(), ['Dut_Pass'])

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'no_valid_params')
        self.assertEqual(response.data.get('requested'), ['Dut_Pass'])
        # 列在文件里，只是不可测 —— 不能报成 missing，否则前端会误判成「切错文件」。
        self.assertEqual(response.data.get('missing'), [])

    def test_string_metadata_column_returns_400_not_500(self):
        """str 元数据列（Site #）同样被剔成 400，防回归到 abs('str') 的 500。"""
        response = _call_boxplot(self._df(), ['Site #'])

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'no_valid_params')
        self.assertEqual(response.data.get('missing'), [])

    def test_unknown_param_still_reports_missing(self):
        """对照组：列真不存在时 missing 必须非空 —— 与上面两条构成两种信号。"""
        response = _call_boxplot(self._df(), ['__bogus__'])

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data.get('error'), 'no_valid_params')
        self.assertEqual(response.data.get('missing'), ['__bogus__'])

    def test_mixed_params_drop_non_numeric_and_still_succeed(self):
        """数值列 + bool 列同时请求：剔掉 bool 但整请求不失败。"""
        response = _call_boxplot(self._df(), ['Param0', 'Dut_Pass'])

        self.assertEqual(response.status_code, 200, response.content)
        results = response.data.get('results', {})
        self.assertIn('Param0', results)
        self.assertNotIn('Dut_Pass', results)

    def test_constant_numeric_column_is_not_filtered_out(self):
        """常量数值列（nunique==1）合法：_helpers 注释明确要求不排除。"""
        df = self._df().assign(Const_Code=[7.0, 7.0, 7.0, 7.0])
        response = _call_boxplot(df, ['Const_Code'])

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('Const_Code', response.data.get('results', {}))
