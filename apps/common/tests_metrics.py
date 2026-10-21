"""T1：`apps/common/metrics.py` 的采样与 `/api/v1/metrics/` 契约。

这个模块最容易写坏的两件事，判据都对着它们：

1. **「取不到」不能写成 0** —— RSS 拿不到、DB 没建表、窗口里没有样本，
   都必须显式呈现为「拿不到」。运维页显示 `RSS 0 MB` 比不显示这个数字危险得多。
2. **观测者不能改变被观测值** —— metrics 自己那个端点若进样本池，
   运维页开久了 Top-1 就永远是它自己。

跑法：`.venv/Scripts/python.exe manage.py test apps.common.tests_metrics`
"""

import sys
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.common import metrics

PASSWORD = 'x-met-12345678'


class PercentileTests(TestCase):
    def test_p50_p95_and_max_on_a_known_list(self):
        values = list(range(1, 101))          # 1..100 ms
        self.assertEqual(metrics.percentile(values, 0.5), 51)
        self.assertEqual(metrics.percentile(values, 0.95), 95)
        self.assertEqual(metrics.percentile(values, 1.0), 100)

    def test_empty_window_is_none_not_zero(self):
        """0 会被读成「全都快得看不见」，None 才是「没有样本」。"""
        self.assertIsNone(metrics.percentile([], 0.95))


class PathNormalizerTests(TestCase):
    def test_numeric_segments_collapse(self):
        """不折 id 的话统计基数无界，Top-N 会退化成「最近点了哪些 id」。"""
        self.assertEqual(metrics.normalize_path('/api/v1/jobs/12/download/'),
                         '/api/v1/jobs/<id>/download/')
        self.assertEqual(metrics.normalize_path('/api/v1/files/7/activate/'),
                         '/api/v1/files/<id>/activate/')

    def test_non_numeric_paths_pass_through(self):
        """对照组：只有纯数字段才折，否则 `browse/`、`summary/` 会被误伤成一样。"""
        self.assertEqual(metrics.normalize_path('/api/v1/browse/'), '/api/v1/browse/')
        self.assertEqual(metrics.normalize_path('/api/v1/files/options/'),
                         '/api/v1/files/options/')

    def test_self_endpoint_is_not_recorded(self):
        self.assertFalse(metrics.is_worth_recording('/api/v1/metrics/'))
        self.assertTrue(metrics.is_worth_recording('/api/v1/browse/'))


class MiddlewareSamplingTests(TestCase):
    def setUp(self):
        metrics._samples.clear()

    def _run(self, path):
        class Req:
            def __init__(self, p):
                self.path = p
                self.method = 'GET'

        def get_response(request):
            return object()

        metrics.MetricsMiddleware(get_response)(Req(path))

    def test_business_request_records_one_sample(self):
        self._run('/api/v1/browse/')
        rows = list(metrics._samples)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'GET /api/v1/browse/')

    def test_metrics_own_call_adds_no_sample(self):
        self._run('/api/v1/metrics/')
        self.assertEqual(len(metrics._samples), 0,
                         '轮询运维页本身不该污染 P95 与 Top-N')

    def test_window_drops_samples_older_than_five_minutes(self):
        """用注入的 `now` 判过期，不 sleep —— 判据不能靠等。"""
        metrics._samples.clear()
        metrics._samples.append((metrics.time.monotonic() - 400, 'GET /old/', 12.0))
        metrics._samples.append((metrics.time.monotonic(), 'GET /new/', 30.0))
        summary = metrics.latency_summary()
        self.assertEqual(summary['samples'], 1, summary)
        self.assertEqual(summary['slowest'][0]['path'], 'GET /new/')

    def test_empty_window_reports_none_percentiles(self):
        metrics._samples.clear()
        summary = metrics.latency_summary()
        self.assertEqual(summary['samples'], 0)
        self.assertIsNone(summary['p95_ms'])
        self.assertEqual(summary['slowest'], [])


class RssDegradationTests(TestCase):
    def test_missing_psutil_yields_none_not_zero(self):
        """缺 psutil 的精简打包/损坏环境必须优雅降级，而不是拿 0 冒充 RSS。"""
        with mock.patch.dict(sys.modules, {'psutil': None}):
            self.assertIsNone(metrics.process_rss_bytes())

    def test_snapshot_marks_rss_unavailable_instead_of_faking_a_number(self):
        with mock.patch.object(metrics, 'process_rss_bytes', return_value=None):
            snap = metrics.snapshot()
        self.assertFalse(snap['rss_available'])
        self.assertIsNone(snap['rss_bytes'])

    def test_snapshot_carries_rss_when_available(self):
        with mock.patch.object(metrics, 'process_rss_bytes', return_value=123456789):
            snap = metrics.snapshot()
        self.assertTrue(snap['rss_available'])
        self.assertEqual(snap['rss_bytes'], 123456789)

    def test_memory_unavailable_is_null_not_zero(self):
        with mock.patch.object(metrics, 'process_rss_bytes', return_value=None):
            snap = metrics.snapshot()
        self.assertIsNone(snap['memory']['used_ratio'])
        self.assertIsNone(snap['memory']['level'])


class MetricsEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('met_admin', 'ma@localhost', PASSWORD,
                                              role='administrator')
        self.viewer = User.objects.create_user('met_viewer', 'mv@localhost', PASSWORD,
                                               role='viewer')
        metrics._samples.clear()

    def _get(self, user=None):
        client = APIClient()
        if user:
            client.force_authenticate(user=user)
        return client.get('/api/v1/metrics/')

    def test_anonymous_is_rejected(self):
        self.assertIn(self._get().status_code, (401, 403))

    def test_non_admin_is_forbidden(self):
        """运维数字里有路径、作业量、内存 —— viewer 不该看到。"""
        self.assertEqual(self._get(self.viewer).status_code, 403)

    def test_admin_gets_the_whole_payload(self):
        """逐键点名：少一个键就是少一类归因能力，不能让「返回 200」当绿灯。"""
        self._run_sample()
        resp = self._get(self.admin)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(
            set(body), {'uptime_seconds', 'pid', 'rss_bytes', 'rss_available',
                        'memory', 'parse_cache', 'summary_cache', 'jobs',
                        'requests'})
        self.assertEqual(set(body['memory']), {
            'budget_bytes', 'jobs_budget_bytes', 'web_budget_bytes',
            'cache_budget_bytes', 'private_bytes', 'used_ratio', 'level',
            'system',
        })
        self.assertEqual(set(body['memory']['system']), {
            'total_bytes', 'available_bytes',
            'commit_used_bytes', 'commit_limit_bytes',
        })
        self.assertEqual(set(body['requests']),
                         {'samples', 'window_seconds', 'p50_ms', 'p95_ms',
                          'max_ms', 'slowest'})
        self.assertEqual(body['requests']['samples'], 1)

    def test_parse_cache_reports_budget_and_usage(self):
        """预算与实际占用是「命中率接近 0」那条论点的直接读数，必须都在。"""
        body = self._get(self.admin).json()
        cache = body['parse_cache']
        self.assertEqual(set(cache), {
            'entries', 'bytes', 'budget_bytes', 'in_flight',
            'hits', 'misses', 'evictions', 'clears',
        })
        self.assertGreater(cache['budget_bytes'], 0)

    def test_jobs_section_survives_missing_table(self):
        """表不存在（未 migrate）时报 available:false，而不是 500 掉整个端点。"""
        from apps.common import metrics as m
        with mock.patch.object(m, '_job_counts', return_value={'available': False}):
            body = self._get(self.admin).json()
        self.assertEqual(body['jobs'], {'available': False})

    def _run_sample(self):
        def get_response(request):
            return object()

        class Req:
            path = '/api/v1/browse/'
            method = 'GET'
        metrics.MetricsMiddleware(get_response)(Req())
