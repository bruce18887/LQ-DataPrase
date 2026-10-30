"""批次 HTML 报告内容测试：KPI、分区块、base64 图表、命名、404 语义、载荷守卫。

runner: ``manage.py test test.backend.test_html_report_batch``
"""

from unittest import mock

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.batch_report import services as batch_services
from apps.batch_report.services import compute_batch_yield_data
from apps.datafiles.models import DataFile
from apps.export.html_report import build_batch_html_report

User = get_user_model()

HTML_URL = '/api/v1/batch-report/batch_html_report/'


def _df():
    # Site 取**数值**：``compute_site_yield_data`` 会 ``float(sv)`` 过滤站点名，
    # 'S1' 这类字符串站点让 ``yield_data`` 直接空掉 ⇒ ``sorted_sites`` 为空、
    # ``aggregate_bin_site_table`` 返回 ``([], [])``，HTML 的 Bin×Site 交叉表与热力图
    # 两块都不会渲染，正向对照就退化成「只验了趋势」。同夹具先例：
    # ``test_batch_report_payload.py`` 的 ``_df()`` 为同一个理由取数值。
    return pd.DataFrame({
        'SW_Bin': [1, 1, 2, 1],
        'Site': [1, 1, 2, 2],
        'V1': [1.0, 2.0, 3.0, 4.0],
    })


def _meta():
    return {'format': 'CTA8290D'}


class BatchHtmlReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='bhr_user', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.mine = DataFile.objects.create(
            owner=self.user, filename='FT1.csv',
            file_path='data/bhr_user/batch/B1/FT1.csv', file_size=2048,
            format_type='CTA8290D', file_type='batch', batch_name='B1',
            status='ready',
        )
        patcher = mock.patch.object(
            batch_services, 'get_cached_parsed_file',
            return_value=(_df(), _meta(), 'CTA8290D'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_has_kpi_and_charts(self):
        resp = self.client.post(HTML_URL, {'batch_name': 'B1'}, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        html = b''.join(resp.streaming_content).decode('utf-8')
        self.assertIn('data-field="file_count"', html)
        self.assertIn('阶段汇总', html)
        self.assertIn('data:image/png;base64,', html, '批次报告应内联 base64 图表')

    def test_filename_is_html(self):
        resp = self.client.post(HTML_URL, {'batch_name': 'B1'}, format='json')
        cd = resp['Content-Disposition']
        self.assertIn('Batch_Report', cd)
        self.assertIn('.html', cd)

    def test_missing_batch_name_returns_400(self):
        resp = self.client.post(HTML_URL, {}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_unknown_batch_returns_404(self):
        resp = self.client.post(HTML_URL, {'batch_name': 'NOPE'}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_json_shaped_payload_is_refused_not_rendered_empty(self):
        """入口守卫（2026-10-30 审查 Important 2）：漏掉 ``for_html_report=True`` 必须炸。

        ``apps/export/html_report/batch.py`` 里那四段分区一律 ``payload.get(...) or {}`` /
        ``or []`` ⇒ 拿 JSON 分支的载荷（默认 ``for_html_report=False``，一个分区都不带）去
        渲染，良率趋势、Bin Pareto、Bin×Site 交叉表**整块静默消失**，而函数正常返回、
        HTTP 200、文件名照常 —— 用户拿到的是一份看着没问题、少了三块的报告。
        所以入口先验载荷形状再往下走：那四把 key 同生同灭，验 ``bin_site_columns``
        一把就够（它是四者里唯一由 ``aggregate_bin_site_table`` 现算的那把，
        也最能说明「这份载荷不是给 HTML 造的」）。错误文案必须指名开关本身，
        否则下一个人只会看到一句 ``ValueError``。
        """
        json_payload = compute_batch_yield_data(self.user, 'B1')
        self.assertNotIn('bin_site_columns', json_payload,
                         '前置：JSON 分支不带那四段分区（判据见 test_batch_report_payload.py）')
        with self.assertRaises(ValueError) as ctx:
            build_batch_html_report(json_payload, dpi=100,
                                    generated_at='2026-01-01 00:00:00')
        self.assertIn('for_html_report=True', str(ctx.exception),
                      '守卫报错没指名该补哪个开关 ⇒ 读到异常的人不知道往哪改')

    def test_html_shaped_payload_passes_the_guard(self):
        """正向对照（防守卫写成「一律拒绝」的假绿）：带开关那份必须渲染出三块。"""
        html_payload = compute_batch_yield_data(self.user, 'B1', for_html_report=True)
        doc = build_batch_html_report(html_payload, dpi=100,
                                      generated_at='2026-01-01 00:00:00')
        for marker in ('良率趋势', 'Bin 分布', '合计'):
            # ``合计`` 只由 ``tables.bin_site_table`` 产出（全仓 grep 唯一命中），
            # 所以它是「Bin×Site 交叉表真的渲染了」的标记，不是别处的通用词。
            self.assertIn(marker, doc, f'HTML 分支的载荷少了分区块：{marker}')
        self.assertIn('data:image/png;base64,', doc)
