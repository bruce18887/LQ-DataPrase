"""单文件分析图表记忆设置（analysis_chart_memory / analysis_chart_state）。

GET/PUT /api/v1/auth/settings/：字段在 serializer 白名单内可往返。哑 JSON 存储
（同 export_filename_templates 模式），结构校验由前端 useChartMemory 负责。
独立模块：accounts/tests.py 已 494 行，遵守 600 行限制（CLAUDE.md）。
"""
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User

SAMPLE_STATE = {
    'layout': {
        'v': 1,
        'rows': [['hist'], ['serial', 'qq'], ['box']],
        'rowPcts': [58.0, 21.0, 21.0],
        'colPcts': [[100], [50, 50], [100]],
    },
    'toggles': {'serial': True, 'qq': False, 'box': True},
}


class ChartMemorySettingTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='mem-user', password='strong-pass-123',
        )
        self.client.force_authenticate(user=self.user)
        self.url = '/api/v1/auth/settings/'

    def test_get_defaults_memory_on_state_empty(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIs(resp.data['analysis_chart_memory'], True)
        self.assertEqual(resp.data['analysis_chart_state'], {})

    def test_put_state_round_trips(self):
        resp = self.client.put(
            self.url, {'analysis_chart_state': SAMPLE_STATE}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        resp = self.client.get(self.url)
        self.assertEqual(resp.data['analysis_chart_state'], SAMPLE_STATE)

    def test_put_partial_keeps_state(self):
        """部分更新其它字段不得丢掉已存布局（partial=True + 白名单字段）。"""
        self.client.put(self.url, {'analysis_chart_state': SAMPLE_STATE}, format='json')
        resp = self.client.put(self.url, {'chart_height': 600}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['chart_height'], 600)
        self.assertEqual(resp.data['analysis_chart_state'], SAMPLE_STATE)

    def test_memory_switch_round_trips(self):
        resp = self.client.put(
            self.url, {'analysis_chart_memory': False}, format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIs(resp.data['analysis_chart_memory'], False)
