"""T1：重活动作接入准入信号量（`HeavyActionMixin`）与同步降级准入。

判据对着三件事，共同点是「接线错了没人会发现」：

1. **登记名单**必须是该 ViewSet `get_extra_actions()` 收集到的真 action 的子集，且与
   spec §6.1（`docs/superpowers/specs/2026-10-21-backend-memory-governance-design.md`）
   逐项一致 —— 新增重活端点忘登记、或把 `site_stats` 这类轻端点顺手登记进去，都在这里红。
2. **持槽时重活必须 503** `server_busy`（信封、`detail.reason`、`Retry-After` 一并断）；
   未登记动作不得进 `heavy_slot` —— 后者证明 mixin 不是静默失效。
3. **同步降级也走同一信号量**（`apps/jobs/views.py::_sync_fallback`）：被拒时先把作业结算成
   `error` 再原样上抛（不留永久 `pending` 行），正常路径的
   `200 + 文件流 + X-Job-Fallback: 1` 形状不变。

持槽一律由**另一条线程**做：`heavy_slot` 的 depth 计数是线程内的，同一线程里先持槽再发
请求会被当成嵌套而放行 —— 那样断出来的 200 与准入毫无关系。水位与淘汰全部 mock，判据
不依赖本机此刻的内存占用。

跑法：`.venv/Scripts/python.exe manage.py test test.backend.test_admission_wiring`
"""

import contextlib
import os
import shutil
import tempfile
import threading
from unittest import mock

from django.http import QueryDict
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.analysis.views import AnalysisViewSet, StatisticsViewSet
from apps.batch_report.views import BatchReportViewSet
from apps.buyoff.views import BuyoffViewSet
from apps.common import admission
from apps.common.admission import HeavyActionMixin
from apps.common.exceptions import ServerBusy
from apps.datafiles.models import DataFile
from apps.gage.views import GageViewSet
from apps.jobs.models import Job

PASSWORD = 'x-adm-wire-12345678'

# 容量 1 + 不等待：被拒由「槽真的被占着」决定，不等真实秒数。
ENV_ONE_SLOT_NO_WAIT = {'LQDP_HEAVY_CONCURRENCY': '1', 'LQDP_HEAVY_WAIT_S': '0'}
# 线程约定的安全上限：真挂住时让用例红，而不是把整个套件吊死。
JOIN_TIMEOUT_S = 10.0

# spec §6.1 的登记表，逐项钉住。改这张表就是改契约，要连带改 spec。
EXPECTED_HEAVY_ACTIONS = {
    AnalysisViewSet: frozenset({
        'histogram', 'wafer_map', 'multi_lot', 'correlation',
        'file_correlation_serials', 'file_correlation', 'file_correlation_export',
        'serial_distribution', 'cpk', 'qqplot', 'uph',
    }),
    StatisticsViewSet: frozenset({
        'detect_fail', 'bin_stats', 'zonal_yield', 'correlation_matrix',
        'bin_trend', 'boxplot', 'param_trend',
    }),
    GageViewSet: frozenset({'generate_summary'}),
    BuyoffViewSet: frozenset({'identify_common_items', 'generate_form'}),
    BatchReportViewSet: frozenset({'batch_html_report', 'generate_report'}),
}

# 明确留在名单外的轻端点：登记进去就是「登录后点开一个列表也可能收到 503」。
LIGHT_ACTIONS = {
    StatisticsViewSet: frozenset({'site_stats'}),
    BatchReportViewSet: frozenset({'list_batches', 'batch_yield_data'}),
}

# 两个 ViewSet 各取一个重活：接线是在五个类上重复的同一段，抽两个证明「不止一个类连上了」。
# histogram 这一条带 `params`：空 params 是「只回列名」的快路径，按
# `heavy_slot_required` 钩子不占槽（见 `HistogramFastPathAdmissionTests`），
# 要断准入就得到计算分支上去。
HEAVY_ENDPOINTS = (
    ('post', '/api/v1/analysis/histogram/', {'file_id': 1, 'params': ['A']}),
    ('post', '/api/v1/batch-report/batch_html_report/', {}),
)


def _real_actions(viewset_cls):
    """该 ViewSet 由 `@action` 暴露的动作名（与 `self.action` 同一取值口径：方法名）。

    `self.action` 来自 router 的 `action_map`（值是 `@action` 装饰的**方法名**），
    `url_path=` 覆写只改 URL 不改它 —— 所以这里也取 `__name__`。
    """
    return {fn.__name__ for fn in viewset_cls.get_extra_actions()}


def _normal_budget():
    """水位固定在 normal：本文件判的是接线，水位行为归 `test_admission`。"""
    budget = mock.Mock()
    budget.level.return_value = 'normal'
    return budget


def _hold_slot(holding, release, errors):
    """另一条线程的持槽体：拿到槽就发信号，等测试发释放信号再退出。"""
    try:
        with admission.heavy_slot('holder'):
            holding.set()
            release.wait(JOIN_TIMEOUT_S)
    except BaseException as exc:      # 线程里的异常不能静默丢掉
        errors.append(exc)


@contextlib.contextmanager
def _slot_held_elsewhere():
    """让唯一的槽被另一条线程真占住（容量 1 / 无等待），退出时保证释放。"""
    holding, release, errors = threading.Event(), threading.Event(), []
    thread = threading.Thread(target=_hold_slot,
                              args=(holding, release, errors), daemon=True)
    with mock.patch.dict(os.environ, ENV_ONE_SLOT_NO_WAIT), \
            mock.patch('apps.common.memory.get_budget',
                       return_value=_normal_budget()):
        thread.start()
        try:
            if not holding.wait(JOIN_TIMEOUT_S):
                raise AssertionError('持槽线程没起来：判据失效')
            yield thread, errors
        finally:
            release.set()
            thread.join(JOIN_TIMEOUT_S)


class HeavyActionDeclarationTests(SimpleTestCase):
    """登记名单本身：五个 ViewSet 的 `heavy_actions` 与 spec §6.1 一致。"""

    def test_mixin_default_is_empty(self):
        self.assertEqual(HeavyActionMixin.heavy_actions, frozenset())

    def test_every_registered_viewset_mixes_in_the_hook_leftmost(self):
        for viewset in EXPECTED_HEAVY_ACTIONS:
            self.assertIs(viewset.__mro__[1], HeavyActionMixin,
                          f'{viewset.__name__} 的 MRO 里 HeavyActionMixin 不在最左')

    def test_collector_sees_real_actions(self):
        """先证明收集器有货：子集判定在空集上恒真，那样这条绊线是哑的。"""
        for viewset in EXPECTED_HEAVY_ACTIONS:
            self.assertTrue(_real_actions(viewset), viewset.__name__)

    def test_declared_actions_are_real_actions(self):
        for viewset in EXPECTED_HEAVY_ACTIONS:
            declared, real = set(viewset.heavy_actions), _real_actions(viewset)
            self.assertLessEqual(
                declared, real,
                f'{viewset.__name__}.heavy_actions 里 {sorted(declared - real)} 不是真 action')

    def test_declared_lists_match_the_spec_exactly(self):
        for viewset, expected in EXPECTED_HEAVY_ACTIONS.items():
            declared = viewset.heavy_actions
            self.assertIsInstance(declared, frozenset, viewset.__name__)
            self.assertEqual(set(declared), set(expected),
                             f'{viewset.__name__} 的登记表与 spec §6.1 不一致')

    def test_light_endpoints_stay_out_of_the_heavy_list(self):
        for viewset, light in LIGHT_ACTIONS.items():
            real = _real_actions(viewset)
            for name in sorted(light):
                self.assertIn(name, real,
                              f'{viewset.__name__} 没有 {name} 这个 action —— 本断言失效')
                self.assertNotIn(name, viewset.heavy_actions,
                                 f'{name} 是轻端点，登记进 heavy_actions 会让普通浏览也可能 503')


class HistogramFastPathAdmissionTests(SimpleTestCase):
    """histogram 空 params 是「只回列名」的快路径 —— 不占重活槽（其余重活照旧）。

    分析页一打开就先发一次空 params 请求拿参数列表（只扫列名，不跑直方图计算）。
    不豁免它，负载下这次「点开页面」就会排队 10s 再 503，参数列表整块清空 ——
    一个只读列的请求被当成重活拒掉。判据分两层：钩子本身（本类）与请求级
    （`HeavyActionRequestTests` 的两条），后者证明 `initial()` 真按钩子分支。
    """

    def _view(self, data, query=''):
        """只装出钩子读的那两处：`request.data` 与 `request.query_params`。"""
        view = AnalysisViewSet()
        view.request = mock.Mock(data=data, query_params=QueryDict(query))
        return view

    def test_empty_params_histogram_does_not_need_the_slot(self):
        self.assertFalse(self._view({}).heavy_slot_required('histogram'))

    def test_histogram_with_params_still_needs_the_slot(self):
        self.assertTrue(self._view({'params': ['A']}).heavy_slot_required('histogram'))

    def test_histogram_params_in_query_string_also_count(self):
        """params 走查询串（GET 形态）同样是计算路径，不能按「没传」放过。"""
        self.assertTrue(self._view({}, 'params=A').heavy_slot_required('histogram'))

    def test_other_heavy_actions_always_need_the_slot(self):
        view = self._view({})
        for action in sorted(AnalysisViewSet.heavy_actions - {'histogram'}):
            self.assertTrue(view.heavy_slot_required(action), action)

    def test_non_heavy_actions_are_unaffected(self):
        self.assertTrue(self._view({}).heavy_slot_required('list'))


class HeavyActionRequestTests(TestCase):
    """请求级：持槽 → 503 信封；未登记 → 不取槽；认证先于取槽；业务体异常 → finally 还槽。"""

    def setUp(self):
        admission.reset_for_tests()
        self.user = User.objects.create_user(
            'adm_wiring', 'aw@localhost', PASSWORD, role='administrator')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        admission.reset_for_tests()

    def test_heavy_actions_return_503_while_the_only_slot_is_held(self):
        for method, url, payload in HEAVY_ENDPOINTS:
            with _slot_held_elsewhere() as (thread, errors):
                resp = getattr(self.client, method)(url, payload, format='json')
            self.assertFalse(thread.is_alive(), '持槽线程没退出')
            self.assertEqual(errors, [], f'持槽线程抛了异常：{errors}')
            self.assertEqual(resp.status_code, 503,
                             f'{url} 持槽时应 503，实际 {resp.status_code}：{resp.content!r}')
            body = resp.json()
            self.assertEqual(body['code'], 'server_busy', url)
            self.assertEqual(body['message'], '服务器繁忙，请稍后重试', url)
            self.assertEqual(body['detail'], {'reason': 'queue'},
                             f'{url} 的 reason 必须是排队超时')
            self.assertEqual(resp['Retry-After'], '5', url)

    def test_registered_action_holds_the_slot_under_its_own_name(self):
        ctx = mock.MagicMock()
        with mock.patch('apps.common.admission.heavy_slot',
                        return_value=ctx) as slot:
            resp = self.client.post('/api/v1/batch-report/batch_html_report/',
                                    {}, format='json')
        slot.assert_called_once_with('batch_html_report')
        ctx.__enter__.assert_called_once_with()
        ctx.__exit__.assert_called_once()
        # 业务体确实跑了（缺参数 → 400），不是被准入挡下的 503
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['code'], 'param_required')

    def test_empty_params_histogram_never_touches_heavy_slot(self):
        """请求级：空 params 的「只回列名」分支不取槽（负载下不该排队再 503）。"""
        with mock.patch('apps.common.admission.heavy_slot') as slot:
            resp = self.client.post('/api/v1/analysis/histogram/',
                                    {'file_id': 1}, format='json')
        slot.assert_not_called()
        # 业务体跑到了（文件不存在 → 400），不是被准入挡下的 503
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['code'], 'file_not_found')

    def test_histogram_with_params_takes_the_slot(self):
        """同一端点的计算路径照旧取槽：豁免只落在空 params 那一条分支上。"""
        ctx = mock.MagicMock()
        with mock.patch('apps.common.admission.heavy_slot',
                        return_value=ctx) as slot:
            resp = self.client.post('/api/v1/analysis/histogram/',
                                    {'file_id': 1, 'params': ['A']}, format='json')
        slot.assert_called_once_with('histogram')
        ctx.__enter__.assert_called_once_with()
        ctx.__exit__.assert_called_once()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['code'], 'file_not_found')

    def test_unregistered_actions_never_touch_heavy_slot(self):
        with mock.patch('apps.common.admission.heavy_slot') as slot:
            listing = self.client.get('/api/v1/batch-report/list_batches/')
            site = self.client.get('/api/v1/statistics/site_stats/')
            yield_data = self.client.get('/api/v1/batch-report/batch_yield_data/')
        slot.assert_not_called()
        self.assertEqual(listing.status_code, 200, listing.content)
        # 两个都是「体跑到了、缺参数」的 400，不是被准入挡下的 503
        self.assertEqual(site.status_code, 400, site.content)
        self.assertEqual(yield_data.status_code, 400, yield_data.content)

    def test_anonymous_request_is_rejected_before_it_takes_a_slot(self):
        """认证先于取槽：匿名请求不该先占住一个槽（再在 401 里还回去）。"""
        self.client.force_authenticate(user=None)
        with mock.patch('apps.common.admission.heavy_slot') as slot:
            resp = self.client.post('/api/v1/analysis/histogram/',
                                    {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 401, resp.content)
        slot.assert_not_called()
        self.assertEqual(admission.admission_snapshot()['active'], 0,
                         '匿名请求不该占到槽')

    def test_slot_is_released_when_the_business_body_raises(self):
        """业务体抛 ValueError ⇒ 统一 500 信封，槽仍由 `finalize_response` 归还。

        action 本体在请求期由 `getattr(self, action)` 取（`as_view` 的 view 闭包），
        所以替掉类属性只换业务体；`self.action` 仍来自 `action_map`，取槽判定不受影响。
        带 `params` 走计算分支：空 params 的快路径按钩子不占槽。
        """
        ctx = mock.MagicMock()
        with mock.patch('apps.common.admission.heavy_slot', return_value=ctx), \
                mock.patch.object(AnalysisViewSet, 'histogram',
                                  side_effect=ValueError('boom')):
            resp = self.client.post('/api/v1/analysis/histogram/',
                                    {'file_id': 1, 'params': ['A']}, format='json')
        ctx.__enter__.assert_called_once_with()
        ctx.__exit__.assert_called_once()
        self.assertEqual(resp.status_code, 500, resp.content)
        self.assertEqual(resp.json()['code'], 'internal_error')


class SyncFallbackAdmissionTests(TestCase):
    """`_sync_fallback` 的外层准入：被拒结算成 error，成功路径形状不变。"""

    def setUp(self):
        admission.reset_for_tests()
        self.user = User.objects.create_user('adm_fallback', 'af@localhost', PASSWORD)
        self.tmpdir = tempfile.mkdtemp(prefix='adm_wiring_')
        self.path = os.path.join(self.tmpdir, 'tiny.csv')
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write('CTA8280F\n[Data]\nA,\n1,\n')
        self.datafile = DataFile.objects.create(
            owner=self.user, filename='tiny.csv', file_path=self.path,
            file_size=os.path.getsize(self.path), format_type='CTA8280F',
            status='ready', program_name='PROG')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        admission.reset_for_tests()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _submit(self):
        return self.client.post('/api/v1/jobs/export_excel/',
                                {'file_id': self.datafile.id}, format='json')

    def test_rejected_sync_fallback_marks_the_job_error_and_still_raises(self):
        with mock.patch('apps.jobs.executor.executor_available', return_value=False), \
                mock.patch('apps.jobs.views.heavy_slot',
                           side_effect=ServerBusy(reason='queue')):
            resp = self._submit()

        # 原样上抛 ⇒ 503 信封；若被吞掉，这条会变成 200/500
        self.assertEqual(resp.status_code, 503, resp.content)
        body = resp.json()
        self.assertEqual(body['code'], 'server_busy')
        self.assertEqual(body['detail'], {'reason': 'queue'})
        self.assertEqual(resp['Retry-After'], '5')

        job = Job.objects.get(owner=self.user)
        self.assertEqual(job.status, 'error', '被拒的降级不能留 pending 行')
        self.assertEqual(job.error, '服务器繁忙，请稍后重试')
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(job.result_path, '', '没进重活就不该有产物')

    def test_successful_fallback_keeps_the_200_file_stream_shape(self):
        seen = []

        @contextlib.contextmanager
        def fake_slot(action):
            seen.append(action)
            yield

        def fake_entry(task):
            os.makedirs(os.path.dirname(task['out_path']), exist_ok=True)
            with open(task['out_path'], 'wb') as fh:
                fh.write(b'sync fallback')
            return {'out_path': task['out_path'], 'downloadable': True}

        with mock.patch('apps.jobs.executor.executor_available', return_value=False), \
                mock.patch('apps.jobs.views.heavy_slot', fake_slot), \
                mock.patch.dict('apps.jobs.views.executor.KIND_RUNNERS',
                                {'export_excel': {'entry': fake_entry}}, clear=True):
            resp = self._submit()

        self.assertEqual(seen, ['sync_fallback'],
                         '同步降级必须按自己的名字取同一个信号量')
        # FileResponse 没有 .content —— 断言消息里只能读头
        self.assertEqual(resp.status_code, 200,
                         resp.get('Content-Disposition') or resp.headers)
        self.assertEqual(resp.get('X-Job-Fallback'), '1')
        self.assertTrue(resp.get('Content-Disposition'), '降级响应必须带下载文件名')
        job = Job.objects.get(owner=self.user)
        self.assertEqual(job.status, 'done')
        self.assertEqual(job.progress, 100)
        self.assertTrue(job.result_name.endswith('.xlsx'), job.result_name)
