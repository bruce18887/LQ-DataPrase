"""导出端点参数贯穿回归（apps/export/views.py + export_ppt.py）。

覆盖缺陷：

* **#6 pptx 开关透传**：视图读出 show_limit/show_3sigma/show_4sigma/
  show_6sigma/show_normal/show_kde 却只传给 xlsx 分支，pptx 一个都不传
  → 同配置导出的 pptx 与 xlsx 图形内容不同。
* **#7 sigma 类型/范围校验**：``request.data.get('sigma', 3)`` 不转 int，
  前端传 ``"3"`` 时 ``mean - "3" * std`` 抛 TypeError → 500；非法值也应 400。
* **#8 html_report 未应用 data_only_bin1**：sigma_limit 与 batch_charts 都应用，
  HTML 报告不应用 → 良率口径与 xlsx 图表不一致。
* **#9 死代码**：``keep_header`` 读出后从未使用（export_to_csv 已删除该参数）。
* **#11 默认参数列表**：``dtype in ('int64','float64')`` 漏掉 float32/int32。
* **#12 百分比精度**：HTML 报告良率 ``{yield_pct:.2f}`` 把 99.998% 显示成 100.00%。

运行：``manage.py test test.backend.test_export_view_params``
"""

import inspect
import io
import zipfile
from types import SimpleNamespace

import numpy as np
import pandas as pd
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.export import export_complete
from apps.export import views as export_views
from apps.export.export_csv import export_to_csv
from apps.export.export_ppt import build_batch_charts_pptx

User = get_user_model()

SIGMA_URL = '/api/v1/export/sigma_limit/'
HTML_URL = '/api/v1/export/html_report/'
CHARTS_URL = '/api/v1/export/batch_charts/'
CSV_URL = '/api/v1/export/to_csv/'

SWITCHES = ('show_limit', 'show_3sigma', 'show_4sigma',
            'show_6sigma', 'show_normal', 'show_kde')


class _ExportViewTests(TestCase):
    """公共装置：真实 User（DRF 鉴权 + 文件名模板都要查库），
    但把 ``load_user_file`` patch 成合成数据——不依赖仓库里的样例 CSV。

    patch 的是**消费方模块的绑定**（``apps.export.views.load_user_file``），
    并用 ``addCleanup`` 还原。
    """

    def build_df(self):
        return pd.DataFrame({
            'SW_Bin': [1, 1, 1, 1, 1, 9],
            'V1': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        })

    def build_metadata(self):
        return {'units': {'V1': 'V'}, 'mins': {'V1': '0'}, 'maxs': {'V1': '10'},
                'format': 'CTA8290D'}

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='exporter', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.df = self.build_df()
        self.metadata = self.build_metadata()
        self.datafile = SimpleNamespace(filename='probe.csv',
                                        format_type='CTA8290D',
                                        program_name='PRG')
        original = export_views.load_user_file
        export_views.load_user_file = (
            lambda request, file_id=None, **kw: (self.df, self.datafile, self.metadata)
        )
        self.addCleanup(setattr, export_views, 'load_user_file', original)

    def body(self, resp):
        return b''.join(resp.streaming_content)


class SigmaLevelValidationTests(_ExportViewTests):
    """缺陷 #7：sigma 必须转 int + 范围校验（非法值 400，不是 500）。"""

    def test_string_sigma_is_accepted(self):
        resp = self.client.post(SIGMA_URL, {'file_id': 1, 'sigma': '3'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(self.body(resp)), 0)

    def test_form_encoded_sigma_is_accepted(self):
        """表单编码天然把 6 变成 '6'——这正是线上 500 的路径。"""
        resp = self.client.post(SIGMA_URL, {'file_id': 1, 'sigma': 6})
        self.assertEqual(resp.status_code, 200)

    def test_int_sigma_still_accepted(self):
        resp = self.client.post(SIGMA_URL, {'file_id': 1, 'sigma': 4}, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_sigma_is_rendered_as_int_in_filename(self):
        resp = self.client.post(SIGMA_URL, {'file_id': 1, 'sigma': '6'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('6sigma', resp['Content-Disposition'])

    def test_invalid_sigma_returns_400(self):
        for bad in ('abc', '', '3.5', 3.5, 0, -3, 99, True, None, [3]):
            with self.subTest(sigma=bad):
                resp = self.client.post(SIGMA_URL, {'file_id': 1, 'sigma': bad},
                                        format='json')
                self.assertEqual(resp.status_code, 400,
                                 f'sigma={bad!r} 应被拒绝为 400，而不是 500/200')

    def test_missing_sigma_defaults_to_3(self):
        resp = self.client.post(SIGMA_URL, {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('3sigma', resp['Content-Disposition'])


class HtmlReportBin1Tests(_ExportViewTests):
    """缺陷 #8 + #12：HTML 报告应用 data_only_bin1，良率用 6 位口径。"""

    def build_df(self):
        return pd.DataFrame({
            'SW_Bin': [1, 1, 1, 7],
            'V1': [1.0, 2.0, 3.0, 4.0],
        })

    def test_data_only_bin1_is_applied(self):
        resp = self.client.post(HTML_URL, {'file_id': 1, 'data_only_bin1': True},
                                format='json')
        self.assertEqual(resp.status_code, 200)
        html = self.body(resp).decode('utf-8')
        self.assertIn('<td>3</td>', html, '总记录数应为过滤后的 bin1 行数')
        self.assertIn('100.00%', html, 'bin1 子集良率应为 100%')

    def test_without_switch_reports_all_rows(self):
        resp = self.client.post(HTML_URL, {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 200)
        html = self.body(resp).decode('utf-8')
        self.assertIn('<td>4</td>', html)
        self.assertIn('75.00%', html)


class HtmlReportYieldPrecisionTests(_ExportViewTests):
    """1/50000 fail → 良率 99.998% 不得显示成误导性的 100.00%。"""

    ROWS = 50000

    def build_df(self):
        bins = np.ones(self.ROWS, dtype='int64')
        bins[-1] = 9
        return pd.DataFrame({'SW_Bin': bins,
                             'V1': np.ones(self.ROWS, dtype='float64')})

    def test_tiny_fail_keeps_six_decimals(self):
        resp = self.client.post(HTML_URL, {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 200)
        html = self.body(resp).decode('utf-8')
        self.assertIn('99.998%', html)
        self.assertNotIn('100.00%', html, '0.002% 的 fail 不得被 2 位小数吞掉')


class PptxSwitchPassThroughTests(_ExportViewTests):
    """缺陷 #6：pptx 分支必须收到与 xlsx 分支相同的图形开关。"""

    def _spy(self):
        calls = {}
        original = export_views.build_batch_charts_pptx

        def spy(*args, **kwargs):
            calls['args'] = args
            calls['kwargs'] = kwargs
            return b'fake-pptx-bytes'

        export_views.build_batch_charts_pptx = spy
        self.addCleanup(setattr, export_views, 'build_batch_charts_pptx', original)
        return calls

    def test_all_switches_forwarded_to_pptx_builder(self):
        calls = self._spy()
        payload = {'file_id': 1, 'params': ['V1'], 'format': 'pptx',
                   'show_limit': False, 'show_3sigma': True, 'show_4sigma': True,
                   'show_6sigma': False, 'show_normal': True, 'show_kde': True}
        resp = self.client.post(CHARTS_URL, payload, format='json')
        self.assertEqual(resp.status_code, 200)
        expected = {name: payload[name] for name in SWITCHES}
        self.assertEqual(calls['kwargs'], expected,
                         'pptx 分支必须把 6 个图形开关原样透传')

    def test_switch_defaults_forwarded_to_pptx_builder(self):
        calls = self._spy()
        resp = self.client.post(CHARTS_URL,
                                {'file_id': 1, 'params': ['V1'], 'format': 'pptx'},
                                format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(calls['kwargs']), set(SWITCHES))
        self.assertTrue(calls['kwargs']['show_limit'])
        self.assertTrue(calls['kwargs']['show_6sigma'])

    def test_pptx_and_xlsx_branches_receive_same_switches(self):
        pptx_calls = self._spy()
        xlsx_calls = {}
        original = export_complete.build_batch_charts_xlsx_with_charts

        def xlsx_spy(*args, **kwargs):
            xlsx_calls['kwargs'] = kwargs
            return b'fake-xlsx-bytes'

        export_complete.build_batch_charts_xlsx_with_charts = xlsx_spy
        self.addCleanup(setattr, export_complete,
                        'build_batch_charts_xlsx_with_charts', original)

        base = {'file_id': 1, 'params': ['V1'], 'show_limit': False,
                'show_3sigma': True, 'show_4sigma': False, 'show_6sigma': False,
                'show_normal': True, 'show_kde': True}
        self.client.post(CHARTS_URL, {**base, 'format': 'pptx'}, format='json')
        self.client.post(CHARTS_URL, {**base, 'format': 'xlsx'}, format='json')
        self.assertEqual(pptx_calls['kwargs'],
                         {k: v for k, v in xlsx_calls['kwargs'].items() if k in SWITCHES},
                         '同一份配置导出的 pptx 与 xlsx 图形开关必须一致')


class PptxBuilderHonorsSwitchesTests(SimpleTestCase):
    """builder 层：开关不只是「收下」，还要真的改变渲染结果。"""

    def _png(self, **toggles):
        df = pd.DataFrame({'V1': np.linspace(1.0, 5.0, 60)})
        metadata = {'units': {'V1': 'V'}, 'mins': {'V1': '0'}, 'maxs': {'V1': '6'},
                    'format': 'CTA8290D'}
        datafile = SimpleNamespace(filename='p.csv', format_type='CTA8290D',
                                   program_name='P')
        blob = build_batch_charts_pptx(datafile, df, metadata, ['V1'], **toggles)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            media = [n for n in z.namelist() if n.startswith('ppt/media/')]
            self.assertEqual(len(media), 1, '每个参数一张图')
            return z.read(media[0])

    def test_builder_accepts_all_switches(self):
        png = self._png(show_limit=True, show_3sigma=True, show_4sigma=True,
                        show_6sigma=False, show_normal=True, show_kde=True)
        self.assertGreater(len(png), 0)

    def test_show_limit_changes_render(self):
        self.assertNotEqual(self._png(show_limit=True), self._png(show_limit=False))

    def test_show_normal_changes_render(self):
        self.assertNotEqual(self._png(show_normal=True), self._png(show_normal=False))

    def test_show_3sigma_changes_render(self):
        self.assertNotEqual(self._png(show_3sigma=True), self._png(show_3sigma=False))


class BatchChartsDefaultParamsTests(_ExportViewTests):
    """缺陷 #11：默认参数列表必须包含窄 dtype 数值列、排除 bool 列。"""

    def build_df(self):
        return pd.DataFrame({
            'SW_Bin': [1, 1, 1, 1],
            'F32': np.array([1.0, 2.0, 3.0, 4.0], dtype='float32'),
            'I32': np.array([1, 2, 3, 4], dtype='int32'),
            'Flag': [True, False, True, True],
            'Text': pd.Series(['a', 'b', 'c', 'd'], dtype='str'),
        })

    def _spy(self):
        calls = {}
        original = export_complete.build_batch_charts_xlsx_with_charts

        def spy(*args, **kwargs):
            calls['args'] = args
            calls['kwargs'] = kwargs
            return b'fake-xlsx-bytes'

        export_complete.build_batch_charts_xlsx_with_charts = spy
        self.addCleanup(setattr, export_complete,
                        'build_batch_charts_xlsx_with_charts', original)
        return calls

    def test_default_params_include_narrow_dtypes(self):
        calls = self._spy()
        resp = self.client.post(CHARTS_URL, {'file_id': 1, 'params': []}, format='json')
        self.assertEqual(resp.status_code, 200)
        params = calls['args'][2]
        self.assertIn('F32', params, 'float32 测量列不得被白名单漏掉')
        self.assertIn('I32', params, 'int32 测量列不得被白名单漏掉')

    def test_default_params_exclude_bool_and_text(self):
        calls = self._spy()
        self.client.post(CHARTS_URL, {'file_id': 1, 'params': []}, format='json')
        params = calls['args'][2]
        self.assertNotIn('Flag', params, 'bool 是 Pass/Fail 标记，不是可分析测量值')
        self.assertNotIn('Text', params)
        self.assertNotIn('SW_Bin', params)


class DeadCodeRemovedTests(SimpleTestCase):
    """缺陷 #9：keep_header 读出来后从未使用（export_to_csv 早已删除该参数）。"""

    def test_views_source_has_no_keep_header(self):
        source = inspect.getsource(export_views)
        self.assertNotIn('keep_header', source,
                         'views.py 不得再读取已废弃的 keep_header')

    def test_export_to_csv_has_no_keep_header_param(self):
        self.assertNotIn('keep_header', inspect.signature(export_to_csv).parameters)


class ToCsvStillWorksTests(_ExportViewTests):
    """死代码删除后 to_csv 端点行为不变（含前端仍在发的 keep_header 字段）。"""

    def test_legacy_keep_header_payload_is_ignored(self):
        resp = self.client.post(CSV_URL, {'file_id': 1, 'keep_header': True},
                                format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'V1', self.body(resp))
