"""单文件 HTML 报告内容测试：含图（base64）、分区块、转义（XSS）、自包含。

runner: ``manage.py test test.backend.test_html_report_single``
"""

from types import SimpleNamespace

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.export import views as export_views

User = get_user_model()

HTML_URL = '/api/v1/export/html_report/'


class _HtmlReportTests(TestCase):
    def build_df(self):
        return pd.DataFrame({
            'SW_Bin': [1, 1, 2, 1],
            'Site': ['S1', 'S1', 'S2', 'S2'],
            'V1': [1.0, 2.0, 3.0, 4.0],
        })

    def build_metadata(self):
        return {'format': 'CTA8290D', 'units': {'V1': 'V'},
                'mins': {'V1': '0'}, 'maxs': {'V1': '10'}}

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='hr_user', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.df = self.build_df()
        self.metadata = self.build_metadata()
        self.datafile = SimpleNamespace(id=1, filename='probe.csv',
                                        format_type='CTA8290D',
                                        program_name='PRG')
        original = export_views.load_user_file
        export_views.load_user_file = (
            lambda request, file_id=None, **kw: (self.df, self.datafile, self.metadata)
        )
        self.addCleanup(setattr, export_views, 'load_user_file', original)

    def render(self, payload=None):
        resp = self.client.post(HTML_URL, payload or {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 200)
        return b''.join(resp.streaming_content).decode('utf-8'), resp


class HtmlReportContentTests(_HtmlReportTests):
    def test_embeds_base64_charts(self):
        html, _ = self.render()
        self.assertIn('data:image/png;base64,', html, '报告应内联 base64 图表')

    def test_sections_present(self):
        html, _ = self.render()
        for title in ('Bin 构成', 'Site 良率', 'Bin × Site 交叉表', '测试项总览'):
            self.assertIn(title, html, f'报告应含区块 {title}')

    def test_self_contained_no_external_refs(self):
        html, _ = self.render()
        self.assertNotIn('src="http', html, '不得引用外部资源')
        self.assertNotIn('<link', html, '不得有外链样式表')

    def test_content_disposition_html_filename(self):
        _, resp = self.render()
        self.assertIn('.html', resp['Content-Disposition'])


class HtmlReportXssTests(_HtmlReportTests):
    def setUp(self):
        super().setUp()
        self.datafile.filename = '<script>alert(1)</script>.csv'
        self.datafile.program_name = '"><img src=x onerror=alert(1)>'

    def test_dynamic_values_are_escaped(self):
        html, _ = self.render()
        self.assertNotIn('<script>', html, '文件名不得原样注入 <script>')
        self.assertNotIn('<img src=x', html, '程序名不得原样注入 <img> 标签')
        self.assertIn('&lt;script&gt;', html, '应出现转义后的文件名')
        self.assertIn('&lt;img src=x', html, '应出现转义后的程序名')
