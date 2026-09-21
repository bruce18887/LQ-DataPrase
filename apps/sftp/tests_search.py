"""搜索端点的 HTTP 与 SSE 契约（spec §3.8 / §3.11）。

跑法：``python manage.py test apps.sftp.tests_search``

视图层只测**HTTP 形状**：状态码、错误体、响应头、帧序列、断流之后的连接账目。
阶段机/遍历/扫描的行为在 ``test/backend/test_sftp_search_*.py``，这里不重跑一遍。

两条钉住的契约（spec §3.11）：
1. 流开始**前**的失败 → ``400 {'error': msg}``，响应绝不能是 SSE 流；
   未连接复用既有哨兵 ``'not_connected'``（与 ``views.py`` 十余处同形，
   ``utils/ssePost.ts`` 只读 ``err.error``）。
2. 流开始**后**只能是带内 ``error`` 事件，生成器内绝不抛 DRF 异常。
"""
import gc
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.sftp import search_views
from apps.sftp.host_keys import HostKeyMismatchError
from apps.sftp.search.connect import SearchSession, SearchSessionError
from apps.sftp.search.runner import SearchRunner
from test.backend.sftp_fake import FakeSftp, FakeSession, sample_tree

# 项目换过 AUTH_USER_MODEL（accounts.User），直接 import contrib 的 User 会炸
# "Manager isn't available"——计划原文的那句 import 照抄不得。
User = get_user_model()

URL = '/api/v1/sftp/search/'

# **导入时**抓一份两个缝的默认值：setUp 会把它们换成替身，晚一步就取不到真件了。
_REAL_BUILD_SESSION = search_views.SftpSearchMixin._build_session
_REAL_RUNNER_CLASS = search_views.SftpSearchMixin._runner_class


def sse_events(body: str):
    """把 'data: {...}\\n\\n' 帧串解析成 dict 列表。"""
    out = []
    for chunk in body.split('\n\n'):
        chunk = chunk.strip()
        if chunk.startswith('data: '):
            out.append(json.loads(chunk[len('data: '):]))
    return out


class CountingSession(FakeSession):
    """带连接账目的 ``FakeSession``。

    断流之后要断言的是「没留下开着的连接」（``opened == closed``），而计数是真
    :class:`~apps.sftp.search.connect.SearchSession` 才有的东西；
    ``test/backend/sftp_fake.FakeSession`` 是四个任务共用的基座（只记 borrow/give_back），
    所以账目补在这层子类里，不去动基座。
    """

    def __init__(self, sftp, size: int = 1):
        super().__init__(sftp, size=size)
        self.opened = size
        self.closed = 0
        self.close_calls = 0

    def close_all(self):
        self.close_calls += 1
        self.closed = self.opened


class ClientEngineRunner(SearchRunner):
    """真 ``SearchRunner``，只是把引擎钉死成 client 档。

    视图层测的是 HTTP 形状与帧序列，能力探测的接线在
    ``test/backend/test_sftp_search_engine_stream.py`` 逐条钉着；这里若让探测照跑，
    ``FakeSession`` 没有 exec 通道 → 回落靠的是「探测吞掉一切异常」，
    「测试为什么通过」就成了隐式依赖。

    必须是**类**而不是模块级函数：函数放进类属性就成了方法，
    ``self._runner_class(spec, session)`` 会多绑一个 ``self`` 进去。
    """

    def __init__(self, spec, session):
        super().__init__(spec, session, forced_engine='client')


class SearchEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u1', password='pw')
        self.client.force_authenticate(self.user)
        self.sftp = FakeSftp(sample_tree())
        self.sessions = []
        self._orig_build = search_views.SftpSearchMixin._build_session
        self._orig_runner = search_views.SftpSearchMixin._runner_class

        def fake_build(view, user_id, workers):
            session = CountingSession(self.sftp, size=workers)
            self.sessions.append(session)
            return session

        search_views.SftpSearchMixin._build_session = fake_build
        search_views.SftpSearchMixin._runner_class = ClientEngineRunner

    def tearDown(self):
        search_views.SftpSearchMixin._build_session = self._orig_build
        search_views.SftpSearchMixin._runner_class = self._orig_runner

    def post(self, payload):
        return self.client.post(URL, payload, format='json')

    def consume(self, resp) -> str:
        return b''.join(resp.streaming_content).decode()

    # ---------------------------------------------------------------- 鉴权

    def test_auth_required(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.post({'roots': ['/data'], 'mode': 'name'}).status_code,
                         401)

    def test_the_two_test_seams_default_to_the_real_objects(self):
        """替身只活在测试里：默认值必须是真 ``SearchRunner`` 与真的 ``_build_session``。

        没有这条，上面所有断言都可能只是在测替身（缝被谁在模块级别改掉都看不出来）。
        """
        self.assertIs(_REAL_RUNNER_CLASS, SearchRunner)
        self.assertEqual(_REAL_BUILD_SESSION.__qualname__,
                         'SftpSearchMixin._build_session')

    # ------------------------------------------------- 流开始前的失败：一律 400

    def test_unknown_key_is_400_before_the_stream(self):
        resp = self.post({'roots': ['/data'], 'mode': 'name', 'recursive': True})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.data)
        self.assertNotIn('text/event-stream', resp.get('Content-Type', ''))
        # 「不是半截 SSE」的可观察形式：响应压根不是流，且一条连接都没开。
        self.assertFalse(resp.streaming)
        self.assertEqual(self.sessions, [])

    def test_missing_roots_is_400(self):
        self.assertEqual(self.post({'mode': 'name'}).status_code, 400)

    def test_roots_none_is_400_not_500(self):
        """``{'roots': None}`` 键在值不在——``.get(k, default)`` 那类缺陷的温床。

        契约层（``contracts._get``）已把显式 ``null`` 当缺失处理，所以这里必须是
        一句 400 的「roots 不能为空」，而不是 ``TypeError`` / 500。
        """
        resp = self.post({'roots': None, 'mode': 'name'})
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertIn('roots', str(resp.data['error']))
        self.assertFalse(resp.streaming)
        self.assertEqual(self.sessions, [])

    def test_term_none_is_400_not_500(self):
        """同族：``term=None`` 而 ``mode=content``（必填）也得是 400。"""
        resp = self.post({'roots': ['/data'], 'mode': 'content', 'term': None})
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertIn('term', str(resp.data['error']))

    def test_not_connected_returns_the_existing_sentinel(self):
        """未连接 → 复用既有哨兵 ``not_connected``（spec §3.11），且绝不开流。"""
        search_views.SftpSearchMixin._build_session = (
            lambda self, uid, workers: (_ for _ in ()).throw(
                search_views.SearchSessionError(
                    'no cached session (not connected) for user 1')))
        resp = self.post({'roots': ['/data'], 'mode': 'name'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'not_connected')
        self.assertFalse(resp.streaming)
        self.assertNotIn('text/event-stream', resp.get('Content-Type', ''))

    def test_real_connection_failure_keeps_its_own_message(self):
        """连接开不出来 ≠ 未连接：把原因说清楚，别一律报成 not_connected。"""
        search_views.SftpSearchMixin._build_session = (
            lambda self, uid, workers: (_ for _ in ()).throw(
                search_views.SearchSessionError('无法建立任何 SFTP 连接（user 1）')))
        resp = self.post({'roots': ['/data'], 'mode': 'name'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], '无法建立任何 SFTP 连接（user 1）')

    def test_host_key_mismatch_is_a_400_not_an_html_500(self):
        """``HostKeyMismatchError`` 不降级、不吞（spec §3.7），但也绝不能变成 500。

        它不是 ``SearchSessionError`` 的子类，所以靠 ``search`` 里那道兜底分支接住；
        这条同时钉住「不静默」（缺陷 #12：except 必留 WARNING）。
        """
        search_views.SftpSearchMixin._build_session = (
            lambda self, uid, workers: (_ for _ in ()).throw(
                HostKeyMismatchError('主机密钥与已信任记录不一致')))
        with self.assertLogs('apps.sftp.search_views', level='WARNING') as cm:
            resp = self.post({'roots': ['/data'], 'mode': 'name'})
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertIn('主机密钥', resp.data['error'])
        self.assertFalse(resp.streaming)
        self.assertTrue(cm.output)

    # ---------------------------------------------------------------- 成功流

    def test_success_streams_event_stream(self):
        resp = self.post({'roots': ['/data'], 'mode': 'content',
                          'term': 'ShadowReg2'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/event-stream')
        self.assertEqual(resp['Cache-Control'], 'no-cache')
        self.assertEqual(resp['X-Accel-Buffering'], 'no')

    def test_frame_sequence_ends_with_done(self):
        resp = self.post({'roots': ['/data'], 'mode': 'content',
                          'term': 'ShadowReg2'})
        events = sse_events(self.consume(resp))
        kinds = [e['kind'] for e in events]
        self.assertEqual(events[0]['kind'], 'hello')
        self.assertEqual(events[-1]['kind'], 'done')
        self.assertIn('match', kinds)
        self.assertEqual(events[-1]['matched'], 4)     # sample_tree 里 4 个数据 CSV

    def test_generator_closes_the_session(self):
        """流被消费完（或断开）后不得留开着的连接，且 ``close_all`` 恰一次。"""
        resp = self.post({'roots': ['/data'], 'mode': 'name'})
        self.consume(resp)
        session = self.sessions[0]
        self.assertEqual(session.close_calls, 1)
        self.assertEqual(session.opened, session.closed)

    def test_client_disconnect_closes_the_session(self):
        """客户端中途断流（``GeneratorExit``）：清理照样跑完，连接不漏。"""
        resp = self.post({'roots': ['/data'], 'mode': 'content',
                          'term': 'ShadowReg2'})
        first = next(iter(resp.streaming_content)).decode()   # 只取一帧就断
        self.assertIn('"kind": "hello"', first)               # 断在流的最开头
        resp.close()                                # 服务端看到的「客户端走了」
        gc.collect()                                # 链式生成器收尾的保险
        session = self.sessions[0]
        self.assertEqual(session.opened, session.closed)
        self.assertEqual(session.close_calls, 1)

    # --------------------------------------------------- 流开始后的异常只能发事件

    def test_exception_inside_stream_never_becomes_html_500(self):
        """流一旦开始就只能发事件；异常要转成 error 事件而不是半截 SSE。"""

        class _Boom:
            def __init__(self, *a, **k):
                pass

            def events(self):
                raise RuntimeError('unexpected')
                yield {}     # noqa: 让它成为生成器

            def close(self):
                pass

        search_views.SftpSearchMixin._runner_class = _Boom
        with self.assertLogs('apps.sftp.search_views', level='WARNING') as cm:
            resp = self.post({'roots': ['/data'], 'mode': 'name'})
            body = self.consume(resp)
        # 状态码仍是 200：流已经开了，此时改状态码只会变成一坨 HTML 错误页。
        self.assertEqual(resp.status_code, 200)
        self.assertIn('"kind": "error"', body)
        self.assertIn('"scope": "fatal"', body)
        self.assertIn('unexpected', body)
        self.assertNotIn('Traceback', body)
        self.assertTrue(cm.output)                  # except 不得静默（缺陷 #12）


class NotConnectedMarkerTests(SimpleTestCase):
    """视图那句「哪一支配哨兵」的判据，得跟 ``connect.py`` 的实际措辞咬得上。

    ``_is_not_connected`` 判的是消息文本；文本改了而判据没改，端点就会把「没连接」
    吐成一句裸消息，前端不再提示重新连接——这条测试是那个漂移的报警器。
    """

    def test_the_sentinel_marker_matches_the_real_message(self):
        with mock.patch('apps.sftp.cache.get_session', return_value=None):
            with self.assertRaises(SearchSessionError) as caught:
                SearchSession(999, 1).open_all()
        self.assertTrue(search_views._is_not_connected(caught.exception),
                        f'真实消息未被判据认出来: {caught.exception}')

    def test_other_session_failures_are_not_reported_as_not_connected(self):
        """反向对照：借连接超时不是「没连接」，原因必须原样给用户。"""
        exc = SearchSessionError('SFTP search session already closed (user 999)')
        self.assertFalse(search_views._is_not_connected(exc))
