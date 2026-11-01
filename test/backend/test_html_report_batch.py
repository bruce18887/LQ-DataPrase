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
        ``or []`` ⇒ 拿 JSON 分支的载荷去渲染，良率趋势、Bin Pareto、Bin×Site 交叉表
        **整块静默消失**，而函数正常返回、HTTP 200、文件名照常 —— 用户拿到的是一份看着
        没问题、少了三块的报告。

        **认门的依据换过一次**（2026-10-31 兼容回包批）：原先验「缺 ``bin_site_columns``」
        就够，因为那四把 key 只在 HTML 分支存在。现在 JSON 分支也带这四把（**空占位**，
        恢复 HEAD 那 14 把键集合），键在不在已经分不出两形状，改用只有 JSON 形状才带的
        ``site_pass_data`` 认门（HTML 报告不读它、故 HTML 载荷不带它 —— 判据
        ``test_batch_report_payload.py`` 的
        ``test_html_payload_carries_report_partitions_and_drops_site_pass_data``）。
        保留「缺 ``bin_site_columns`` 也拒」那一半 ⇒ 连服务产物都不是的手搓载荷仍进不来。
        错误文案必须指名开关本身，否则下一个人只会看到一句 ``ValueError``。
        """
        json_payload = compute_batch_yield_data(self.user, 'B1')
        self.assertEqual(json_payload.get('site_pass_data'), [],
                         '前置：JSON 分支带 site_pass_data 兼容空键（判据见 '
                         'test_batch_report_payload.py 的 JSON_COMPAT_KEYS 那组）')
        self.assertEqual(json_payload.get('bin_site_columns'), [],
                         '前置：JSON 分支那四把都是空占位，不是算出来的分区')
        with self.assertRaises(ValueError) as ctx:
            build_batch_html_report(json_payload, dpi=100,
                                    generated_at='2026-01-01 00:00:00')
        self.assertIn('for_html_report=True', str(ctx.exception),
                      '守卫报错没指名该补哪个开关 ⇒ 读到异常的人不知道往哪改')

    def test_hand_built_payload_missing_the_partitions_is_still_refused(self):
        """认门的两半都要各自咬得住：只有 9 把真实键的手搓载荷（既无 ``site_pass_data``
        也无 ``bin_site_columns``）仍然必须被拒 —— 否则守卫被改成「只认 site_pass_data」
        后，这一类漏带分区就静默少三块。"""
        bare = compute_batch_yield_data(self.user, 'B1')
        for key in ('site_pass_data', 'trend_data', 'bin_distribution',
                    'bin_table_data', 'bin_site_columns'):
            bare.pop(key)
        with self.assertRaises(ValueError):
            build_batch_html_report(bare, dpi=100,
                                    generated_at='2026-01-01 00:00:00')

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

    def test_html_shaped_payload_with_empty_site_partitions_passes_the_guard(self):
        """无 Site 批次的合法 HTML 载荷不能被守卫误杀：分区为空 ≠ 载荷形状是 JSON。

        ``aggregate_bin_site_table`` 对没有 Site 列的批次合法地返回 ``([], [])``，
        ``build_batch_html_report`` 的入口守卫只能看「键在不在」、不能看「值空不空」：
        这里保留 HTML 形状（没有 JSON 兼容键 ``site_pass_data``，但
        ``bin_table_data`` / ``bin_site_columns`` 两把 key 仍在），只是把值置空。
        若守卫被改成 ``not payload.get('bin_site_columns')``，本用例必须红。
        """
        html_payload = compute_batch_yield_data(self.user, 'B1', for_html_report=True)
        self.assertNotIn('site_pass_data', html_payload,
                         '前置：这是 HTML 分支载荷，不该带 JSON 形状兼容键')
        html_payload['bin_table_data'] = []
        html_payload['bin_site_columns'] = []
        html_payload['sorted_sites'] = []

        doc = build_batch_html_report(html_payload, dpi=100,
                                      generated_at='2026-01-01 00:00:00')

        self.assertIn('批次良率报告', doc)
        self.assertNotIn('合计', doc)
