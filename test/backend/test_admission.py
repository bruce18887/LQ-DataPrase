"""T1：重活准入内核（`apps/common/admission.py`）与 `server_busy` 503 信封。

这个内核最容易被写坏的三件事，判据都对着它们：

1. **槽是真互斥的** —— 容量 1 时第二个线程拿不到槽要等超时（`reason='queue'`），
   前一个释放后必须能进。写成进程级全局变量（跨线程共享）或忘记 release 都会在这里红。
2. **嵌套只占一个槽** —— 线程内 depth 计数；少了它，一个请求里嵌套两次就把容量吃光，
   而单线程测试照样绿。
3. **水位动作的顺序** —— soft 先淘汰到 0.5；hard 淘汰到 0 后**重新判**仍 hard 才 503；
   淘汰函数自己抛错只记日志，不得改变 503 结果。

并发用 `threading.Event` 约定时序，不拿定长 sleep 当同步；水位与淘汰一律 mock，
所以判据不依赖本机此刻的内存占用。

跑法：`.venv/Scripts/python.exe manage.py test test.backend.test_admission`
"""

import logging
import os
import threading
from unittest import mock

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.common import admission, metrics
from apps.common.exceptions import ServerBusy, _code_for_status, custom_exception_handler

PASSWORD = 'x-adm-12345678'

# 只占一个槽、拿不到槽立刻判「排队超时」——超时由真空槽决定，不等真实秒数。
ENV_ONE_SLOT_NO_WAIT = {'LQDP_HEAVY_CONCURRENCY': '1', 'LQDP_HEAVY_WAIT_S': '0'}
# 线程约定的安全上限：真挂住时让用例红，而不是把整个套件吊死。
JOIN_TIMEOUT_S = 10.0


def _budget(level_value=None, side_effect=None):
    """构造 `get_budget()` 的替身，只暴露内核真正读的那一个方法。"""
    budget = mock.Mock()
    if side_effect is not None:
        budget.level.side_effect = side_effect
    else:
        budget.level.return_value = level_value
    return budget


def _patches(env, budget, evict=None):
    """内核依赖的三处外部触点：环境变量、内存水位、缓存淘汰。"""
    stacked = mock.patch.dict(os.environ, env)
    budget_patch = mock.patch('apps.common.memory.get_budget', return_value=budget)
    if evict is None:
        evict_patch = mock.patch('apps.datafiles.services.evict_parse_cache_to')
    else:
        evict_patch = mock.patch('apps.datafiles.services.evict_parse_cache_to',
                                 **evict)
    return stacked, budget_patch, evict_patch


class SlotExclusionTests(SimpleTestCase):
    """槽的互斥与释放：靠 Event 约定时序，不靠定长 sleep。"""

    def setUp(self):
        admission.reset_for_tests()

    def tearDown(self):
        admission.reset_for_tests()

    def test_second_thread_rejected_with_queue_reason_while_slot_held(self):
        holding = threading.Event()
        release = threading.Event()
        outcome = {}

        def holder():
            try:
                with admission.heavy_slot('holder'):
                    holding.set()
                    release.wait(JOIN_TIMEOUT_S)
            except BaseException as exc:      # 线程里的异常不能静默丢掉
                outcome['error'] = exc

        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch:
            thread = threading.Thread(target=holder, daemon=True)
            thread.start()
            self.assertTrue(holding.wait(JOIN_TIMEOUT_S), '持槽线程没起来')
            try:
                with self.assertRaises(ServerBusy) as caught:
                    with admission.heavy_slot('second'):
                        self.fail('容量 1 且槽被占时不该放行第二个线程')
            finally:
                release.set()
                thread.join(JOIN_TIMEOUT_S)
        self.assertFalse(thread.is_alive(), '持槽线程没退出')
        self.assertNotIn('error', outcome, outcome.get('error'))
        self.assertEqual(caught.exception.reason, 'queue')
        self.assertEqual(admission.admission_snapshot()['rejected'], 1)
        self.assertEqual(admission.admission_snapshot()['last_reason'], 'queue')

    def test_slot_is_reusable_after_the_holder_leaves(self):
        """释放后必须能进：只 release 不 acquire 的写法在这里看不出来，反之亦然。"""
        holding = threading.Event()
        release = threading.Event()
        outcome = {}

        def holder():
            try:
                with admission.heavy_slot('holder'):
                    holding.set()
                    release.wait(JOIN_TIMEOUT_S)
            except BaseException as exc:
                outcome['error'] = exc

        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch:
            thread = threading.Thread(target=holder, daemon=True)
            thread.start()
            self.assertTrue(holding.wait(JOIN_TIMEOUT_S), '持槽线程没起来')
            release.set()
            thread.join(JOIN_TIMEOUT_S)
            self.assertFalse(thread.is_alive(), '持槽线程没退出')
            with admission.heavy_slot('after-release'):
                self.assertEqual(admission.admission_snapshot()['active'], 1)
        self.assertNotIn('error', outcome, outcome.get('error'))
        self.assertEqual(admission.admission_snapshot()['active'], 0)

    def test_slot_is_returned_when_the_body_raises(self):
        """业务体抛异常也必须还槽：`finally` 少了释放那一半，一次失败就吃掉一格容量。

        容量 1 下这最刺眼 —— 失败之后再也取不到槽，进程慢慢变成「全部 503」。
        计数与「还能再取」一起断：只看 active 的话，把 release 换成 _bump(-1)
        仍能骗过读数，但第二次取槽会当场超时。
        """
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch:
            with self.assertRaises(RuntimeError):
                with admission.heavy_slot('boom'):
                    raise RuntimeError('body failed')
            snapshot = admission.admission_snapshot()
            self.assertEqual(snapshot['active'], 0, '异常路径没还槽')
            self.assertEqual(snapshot['waiting'], 0)
            with admission.heavy_slot('after'):
                self.assertEqual(admission.admission_snapshot()['active'], 1)
        self.assertEqual(admission.admission_snapshot()['active'], 0)

    def test_nested_slot_takes_only_one_of_the_capacity(self):
        """容量 1 下嵌套若再取一次槽，内层会当场超时 → 本用例红。"""
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch:
            with admission.heavy_slot('outer'):
                self.assertEqual(admission.admission_snapshot()['active'], 1)
                with admission.heavy_slot('inner'):
                    self.assertEqual(admission.admission_snapshot()['active'], 1)
                self.assertEqual(admission.admission_snapshot()['active'], 1)
        self.assertEqual(admission.admission_snapshot()['active'], 0)
        self.assertEqual(admission.admission_snapshot()['rejected'], 0)


class _RecordingSemaphore:
    """记录 acquire 那一刻的 waiting 读数：并发计数器只能这样确定性地钉住。"""

    def __init__(self, granted):
        self.granted = granted
        self.waiting_seen = []
        self.releases = 0

    def acquire(self, timeout=None):
        self.waiting_seen.append(admission.admission_snapshot()['waiting'])
        self.timeout = timeout
        return self.granted

    def release(self):
        self.releases += 1


class CounterTests(SimpleTestCase):
    """`admission_snapshot()` 的六个键与其中三个计数器的变化。"""

    def setUp(self):
        admission.reset_for_tests()

    def tearDown(self):
        admission.reset_for_tests()

    def test_snapshot_shape_and_zeroed_state(self):
        env, budget_patch, evict_patch = _patches(
            {'LQDP_HEAVY_CONCURRENCY': '3', 'LQDP_HEAVY_WAIT_S': '0'},
            _budget('normal'))
        with env, budget_patch, evict_patch:
            self.assertEqual(admission.admission_snapshot(), {
                'capacity': 3, 'active': 0, 'waiting': 0,
                'rejected': 0, 'relief': 0, 'last_reason': None,
            })

    def test_capacity_is_clamped_to_the_documented_band(self):
        for raw, expected in (('0', 1), ('99', 8), ('abc', 2)):
            admission.reset_for_tests()
            env, budget_patch, evict_patch = _patches(
                {'LQDP_HEAVY_CONCURRENCY': raw, 'LQDP_HEAVY_WAIT_S': '0'},
                _budget('normal'))
            with env, budget_patch, evict_patch:
                self.assertEqual(admission.admission_snapshot()['capacity'],
                                 expected, raw)

    def test_active_goes_up_inside_the_slot_and_back_to_zero(self):
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch:
            with admission.heavy_slot('one'):
                self.assertEqual(admission.admission_snapshot()['active'], 1)
            self.assertEqual(admission.admission_snapshot()['active'], 0)

    def test_waiting_counts_only_while_blocked_on_acquire(self):
        semaphore = _RecordingSemaphore(granted=True)
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch, \
                mock.patch.object(admission, '_semaphore_for',
                                  return_value=semaphore):
            with admission.heavy_slot('waiting'):
                pass
        self.assertEqual(semaphore.waiting_seen, [1])
        self.assertEqual(semaphore.timeout, 0, '等待上限要来自 LQDP_HEAVY_WAIT_S')
        self.assertEqual(admission.admission_snapshot()['waiting'], 0)
        self.assertEqual(semaphore.releases, 1)

    def test_waiting_drops_back_when_acquire_times_out(self):
        semaphore = _RecordingSemaphore(granted=False)
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch, \
                mock.patch.object(admission, '_semaphore_for',
                                  return_value=semaphore):
            with self.assertRaises(ServerBusy):
                with admission.heavy_slot('timeout'):
                    self.fail('acquire 返回 False 就不该进临界区')
        snapshot = admission.admission_snapshot()
        self.assertEqual(semaphore.waiting_seen, [1])
        self.assertEqual(snapshot['waiting'], 0)
        self.assertEqual(snapshot['active'], 0)
        self.assertEqual(snapshot['rejected'], 1)
        self.assertEqual(semaphore.releases, 0, '没拿到槽就不能 release')


class WaterLevelTests(SimpleTestCase):
    """水位动作的顺序与计数：soft 淘汰 0.5 / hard 淘汰 0 后重判。"""

    def setUp(self):
        admission.reset_for_tests()

    def tearDown(self):
        admission.reset_for_tests()

    def test_soft_level_evicts_to_half_before_acquiring(self):
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('soft'))
        with env, budget_patch, evict_patch as evict:
            with admission.heavy_slot('soft'):
                pass
        evict.assert_called_once_with(0.5)
        snapshot = admission.admission_snapshot()
        self.assertEqual(snapshot['relief'], 1)
        self.assertEqual(snapshot['rejected'], 0)

    def test_normal_level_does_not_touch_the_cache(self):
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch as evict:
            with admission.heavy_slot('normal'):
                pass
        evict.assert_not_called()
        self.assertEqual(admission.admission_snapshot()['relief'], 0)

    def test_hard_level_evicts_to_zero_then_still_rejects_with_memory(self):
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget(side_effect=['hard', 'hard', 'hard']))
        with env, budget_patch, evict_patch as evict:
            with self.assertRaises(ServerBusy) as caught:
                with admission.heavy_slot('hard'):
                    self.fail('hard 水位下不该放行')
        evict.assert_called_once_with(0.0)
        self.assertEqual(caught.exception.reason, 'memory')
        snapshot = admission.admission_snapshot()
        self.assertEqual(snapshot['active'], 0, '503 前必须先还槽')
        self.assertEqual(snapshot['rejected'], 1)
        self.assertEqual(snapshot['last_reason'], 'memory')

    def test_hard_level_admits_when_eviction_brings_it_back(self):
        """淘汰之后复判 normal 就必须放行 —— 否则 hard 变成永久停摆。"""
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget(side_effect=['hard', 'hard', 'normal']))
        entered = []
        with env, budget_patch, evict_patch as evict:
            with admission.heavy_slot('hard-then-ok'):
                entered.append(True)
        self.assertEqual(entered, [True])
        evict.assert_called_once_with(0.0)
        self.assertEqual(admission.admission_snapshot()['rejected'], 0)

    def test_eviction_failure_is_logged_but_does_not_change_the_verdict(self):
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('hard'),
            evict={'side_effect': RuntimeError('cache exploded')})
        with env, budget_patch, evict_patch as evict, \
                self.assertLogs(admission.__name__, level='WARNING') as logs:
            with self.assertRaises(ServerBusy) as caught:
                with admission.heavy_slot('hard'):
                    self.fail('淘汰失败不能把 503 变成放行')
        evict.assert_called_once_with(0.0)
        self.assertEqual(caught.exception.reason, 'memory')
        self.assertEqual(admission.admission_snapshot()['active'], 0)
        self.assertTrue(any('淘汰' in line for line in logs.output), logs.output)


class RejectLogRateLimitTests(SimpleTestCase):
    """连续拒绝只留一条日志：日志是证据，不是剂量。"""

    def setUp(self):
        admission.reset_for_tests()
        self.records = []
        handler = logging.Handler(level=logging.WARNING)
        handler.emit = self.records.append
        logger = logging.getLogger(admission.__name__)
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        self.addCleanup(logger.removeHandler, handler)

    def tearDown(self):
        admission.reset_for_tests()

    def test_two_rejections_within_window_log_once(self):
        # 复用同一个「永远拿不到」的信号量替身：拒绝本身不占槽，真信号量下第二次会成功。
        semaphore = _RecordingSemaphore(granted=False)
        env, budget_patch, evict_patch = _patches(
            ENV_ONE_SLOT_NO_WAIT, _budget('normal'))
        with env, budget_patch, evict_patch, \
                mock.patch.object(admission, '_semaphore_for',
                                  return_value=semaphore):
            for action in ('first', 'second'):
                with self.assertRaises(ServerBusy):
                    with admission.heavy_slot(action):
                        self.fail('没槽还放行')
        rejections = [r for r in self.records if r.levelno == logging.WARNING]
        self.assertEqual(len(rejections), 1,
                         [r.getMessage() for r in rejections])
        self.assertEqual(admission.admission_snapshot()['rejected'], 2,
                         '限频只压日志，不许压计数')


class ServerBusyEnvelopeTests(SimpleTestCase):
    """503 信封：code / message / detail.reason / Retry-After 逐字对齐。"""

    def test_envelope_fields(self):
        response = custom_exception_handler(ServerBusy(reason='queue'), {})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'server_busy')
        self.assertEqual(response.data['message'], '服务器繁忙，请稍后重试')
        self.assertEqual(response.data['detail'], {'reason': 'queue'})
        self.assertEqual(response['Retry-After'], '5')

    def test_memory_reason_survives_the_envelope(self):
        response = custom_exception_handler(ServerBusy(reason='memory'), {})
        self.assertEqual(response.data['detail'], {'reason': 'memory'})
        self.assertEqual(response.data['code'], 'server_busy')

    def test_status_code_falls_back_to_server_busy(self):
        """即便异常类型不在已知表里，503 也必须落到 server_busy 而不是 http_503。"""
        self.assertEqual(_code_for_status(503), 'server_busy')

    def test_exception_class_carries_the_contract(self):
        exc = ServerBusy(reason='queue')
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(exc.default_code, 'server_busy')
        self.assertEqual(exc.default_detail, '服务器繁忙，请稍后重试')
        self.assertEqual(exc.reason, 'queue')
        self.assertEqual(exc.detail, {'reason': 'queue'})


class MetricsAdmissionSectionTests(TestCase):
    """`/metrics/` 的 admission 段是运维判断「是不是我在拒人」的唯一读数。"""

    def setUp(self):
        admission.reset_for_tests()
        self.admin = User.objects.create_user(
            'adm_busy', 'ab@localhost', PASSWORD, role='administrator')

    def tearDown(self):
        admission.reset_for_tests()

    def test_snapshot_api_carries_admission_with_six_keys(self):
        body = metrics.snapshot()
        self.assertIn('admission', body)
        self.assertEqual(set(body['admission']), {
            'capacity', 'active', 'waiting', 'rejected', 'relief', 'last_reason',
        })
        self.assertGreaterEqual(body['admission']['capacity'], 1)

    def test_metrics_endpoint_exposes_the_admission_section(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get('/api/v1/metrics/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()['admission']), {
            'capacity', 'active', 'waiting', 'rejected', 'relief', 'last_reason',
        })
