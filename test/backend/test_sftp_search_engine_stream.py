"""阶段机、事件协议、取消与清理（spec §3.8 / §3.9）。

跑法：python manage.py test test.backend.test_sftp_search_engine_stream
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, engine, walker  # noqa: E402
# 码表按名字取：模块名 events 与这些测试里满地的局部变量 events 同名。
from apps.sftp.search.events import (SCAN_THREAD_PREFIX, CLAMPED_TEXT, INCOMPLETE_CODES,
                                      NOTICE_TEXT, SPEED_ONLY_CODES, TRUNCATION_TEXT,
                                      notice)  # noqa: E402
from apps.sftp.search.runner import SearchRunner  # noqa: E402
from test.backend.sftp_fake import FakeSession, FakeSftp, sample_tree  # noqa: E402

NO_GREP = engine.ProbeResult(False, False, False, '测试环境不提供 grep')

# §3.8 的码表：钳位码与截断码都要有文案，缺一个就是 KeyError。
ALL_CLAMP_CODES = ('clamped_workers', 'clamped_timeout', 'clamped_max_entries',
                   'clamped_max_candidates', 'clamped_max_matches',
                   'clamped_matches_per_file', 'clamped_column_rows',
                   'clamped_max_scan_bytes', 'clamped_max_depth')
ALL_LIMIT_CODES = ('truncated_depth', 'truncated_entries', 'truncated_candidates',
                   'truncated_matches', 'scan_budget_exceeded', 'grep_fallback',
                   'grep_unavailable', 'workers_reduced', 'dir_unreadable',
                   # 不在 §3.8 的清单里，但 events.py 补了它（到点静默返回同样是少结果）
                   'timeout')


class _SlowSftp(FakeSftp):
    """每次 open 睡 20ms：让扫描阶段一定比取消慢，否则「取消提前收尾」测不出东西。"""

    def open(self, path, mode='rb', bufsize=-1):
        time.sleep(0.02)
        return super().open(path, mode, bufsize)


class _NoExecTransport:
    """开出来的通道连 ``grep --version`` 都跑不出来：探测就是「这台机器没有 grep」。"""

    def open_session(self, timeout=None):
        return _GrepChan([], exit_status=127)


class _ExecSpy(FakeSession):
    """数一数本次搜索真的借了几次 exec 通道 —— 探测该不该发，看这个计数。"""

    def __init__(self, sftp, size: int = 1):
        super().__init__(sftp, size=size)
        self.exec_calls = 0

    def exec_transport(self):
        self.exec_calls += 1
        return _NoExecTransport()


class _CountingSession(_ExecSpy):
    """带 opened/closed 计数的会话替身：钉住「不留未关连接」这条（spec §3.7）。"""

    def __init__(self, sftp, size: int = 1):
        super().__init__(sftp, size=size)
        self.opened = size
        self.closed = 0
        self.event_set_when_closed = None

    def close_all(self):
        self.closed = self.opened


class _ProbeStub(SearchRunner):
    """把 ``_probe`` 换成常量：探测接线是计划点名的缝，测试从这个方法切。"""

    def _probe(self):
        return NO_GREP


def spec(**over):
    base = {'roots': ['/data'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def run(s, tree=None):
    sftp = FakeSftp(tree if tree is not None else sample_tree())
    runner = SearchRunner(s, _ExecSpy(sftp, size=s.workers))
    return list(runner.events()), sftp


def kinds(events):
    return [e['kind'] for e in events]


def first(events, kind):
    return next(e for e in events if e['kind'] == kind)


def match_items(events):
    return [i for e in events if e['kind'] == 'match' for i in e['items']]


def codes(events, kind='notice'):
    return [e['code'] for e in events if e['kind'] == kind]


class HelloTests(SimpleTestCase):
    def test_hello_is_the_first_event(self):
        events, _ = run(spec())
        self.assertEqual(events[0]['kind'], 'hello')

    def test_hello_declares_engine_and_reason(self):
        events, _ = run(spec())
        self.assertEqual(events[0]['engine'], 'client')
        self.assertTrue(events[0]['engine_reason'].strip())

    def test_hello_reports_actual_worker_count(self):
        """并行数必须是真实值，否则用户看到的是假的。"""
        events, _ = run(spec(workers=3))
        self.assertEqual(events[0]['workers_actual'], 3)   # FakeSession size=workers

    def test_hello_echoes_the_roots(self):
        events, _ = run(spec())
        self.assertEqual(list(events[0]['roots']), ['/data'])

    def test_clamped_fields_become_notices(self):
        events, _ = run(spec(workers=99))
        self.assertIn('notice', kinds(events))
        self.assertTrue(any(e['kind'] == 'notice'
                            and 'workers' in e['code'] for e in events))

    def test_quota_degradation_is_reported(self):
        """开不出来那么多连接就得说：否则用户看到的并行数是假的（spec §3.7）。"""
        sftp = FakeSftp(sample_tree())
        runner = SearchRunner(spec(workers=8), _ExecSpy(sftp, size=2))
        events = list(runner.events())
        self.assertEqual(events[0]['workers_actual'], 2)
        self.assertIn('workers_reduced', codes(events))
        self.assertIn('workers_reduced', first(events, 'done')['limits_hit'])
        # 但它只是「慢」不是「少」：把它报成 truncated 会让一次完整的搜索显示成 partial，
        # 用户据此判定结果不可信并重搜 —— 那是假警报（spec §3.13 的黄条只属于少结果）。
        self.assertFalse(first(events, 'done')['truncated'])
        reduced = [e for e in events if e['kind'] == 'notice' and e['code'] == 'workers_reduced']
        self.assertTrue(reduced)
        self.assertFalse(reduced[0]['incomplete'], '只影响快慢的码不许标成结果不完整')


class StageProtocolTests(SimpleTestCase):
    def test_client_engine_sequence(self):
        events, _ = run(spec())
        seq = kinds(events)
        self.assertEqual(seq[0], 'hello')
        self.assertIn('stage', seq)
        self.assertIn('candidates', seq)
        self.assertIn('match', seq)
        self.assertEqual(seq[-1], 'done')

    def test_listing_then_scanning_stages(self):
        events, _ = run(spec())
        stages = [e['stage'] for e in events if e['kind'] == 'stage']
        self.assertEqual(stages, ['listing', 'scanning', 'done'])

    def test_stop_after_listing_skips_scanning(self):
        events, sftp = run(spec(stop_after_listing=True))
        self.assertNotIn('scanning',
                         [e['stage'] for e in events if e['kind'] == 'stage'])
        self.assertEqual(sftp.open_count, 0, '仅列候选不该读任何文件内容')
        self.assertTrue(first(events, 'done')['matched'] >= 0)

    def test_progress_total_is_null_during_listing(self):
        """listing 没有分母，UI 只能走不定档 —— 这条性质要被钉住。"""
        events, _ = run(spec())
        prog = [e for e in events if e['kind'] == 'progress']
        self.assertIsNone(prog[0]['total'])

    def test_scanning_progress_has_a_denominator(self):
        events, _ = run(spec())
        scan_prog = [e for e in events
                     if e['kind'] == 'progress' and e['stage'] == 'scanning']
        self.assertTrue(scan_prog and scan_prog[-1]['total'] > 0)

    def test_candidates_are_batched_not_one_per_event(self):
        """十万条目逐条发事件会把 SSE 变成瓶颈。"""
        tree = {f'/data/batch1/f{i}.csv': b'[DATA]\r\nSN,ShadowReg2\r\n'
                for i in range(600)}
        events, _ = run(spec(mode='name', data_files_only=False), tree)
        batches = [e for e in events if e['kind'] == 'candidates']
        self.assertLessEqual(len(batches), 20)
        self.assertGreater(max(len(b['items']) for b in batches), 1)

    def test_candidates_event_carries_total_so_far(self):
        tree = {f'/data/b{i}.csv': b'x\r\n' for i in range(250)}
        events, _ = run(spec(mode='name', data_files_only=False), tree)
        batches = [e for e in events if e['kind'] == 'candidates']
        self.assertGreater(len(batches), 1, '250 项 > FLUSH_MAX_ITEMS，至少要分两帧')
        self.assertEqual(batches[-1]['total_so_far'], 250)

    def test_matches_are_batched_too(self):
        tree = {f'/data/b{i}.csv': b'x,ShadowReg2\r\n' for i in range(450)}
        events, _ = run(spec(mode='content', data_files_only=False), tree)
        batches = [e for e in events if e['kind'] == 'match']
        self.assertLessEqual(len(batches), 10, '450 条命中不该催出几百个事件')
        self.assertEqual(sum(len(b['items']) for b in batches), 450)
        self.assertGreater(max(len(b['items']) for b in batches), 1)


class TruncationTests(SimpleTestCase):
    def test_candidate_cap_is_reported_not_silent(self):
        """搜出 5000 而真实有 40000 时静默返回，比慢十倍更伤信任。"""
        events, _ = run(spec(max_candidates=1))
        done = first(events, 'done')
        self.assertTrue(done['truncated'])
        self.assertIn('truncated_candidates', done['limits_hit'])

    def test_match_cap_is_reported(self):
        tree = {f'/data/b{i}.csv': b'x,ShadowReg2\r\n' for i in range(50)}
        events, _ = run(spec(max_matches=3, data_files_only=False), tree)
        self.assertIn('truncated_matches', first(events, 'done')['limits_hit'])

    def test_match_cap_actually_stops_emitting(self):
        tree = {f'/data/b{i}.csv': b'x,ShadowReg2\r\n' for i in range(50)}
        events, _ = run(spec(max_matches=3, data_files_only=False), tree)
        self.assertEqual(len(match_items(events)), 3)

    def test_depth_cap_is_reported(self):
        events, _ = run(spec(mode='name', depth='children',
                             data_files_only=False))
        self.assertIn('truncated_depth', first(events, 'done')['limits_hit'])

    def test_unreadable_dir_lands_in_limits_hit(self):
        sftp = FakeSftp(sample_tree(), unreadable=['/data/batch1'])
        events = list(SearchRunner(spec(), _ExecSpy(sftp, size=1)).events())
        self.assertIn('dir_unreadable', first(events, 'done')['limits_hit'])

    def test_every_limit_code_has_a_message(self):
        missing = [c for c in ALL_LIMIT_CODES if c not in NOTICE_TEXT]
        self.assertEqual(missing, [], f'码表缺文案：{missing}')

    def test_every_clamp_code_has_a_message(self):
        missing = [c for c in ALL_CLAMP_CODES if c not in CLAMPED_TEXT]
        self.assertEqual(missing, [], f'钳位文案缺失：{missing}')

    def test_no_notice_is_emitted_without_text(self):
        events, _ = run(spec(max_candidates=1, workers=99))
        self.assertTrue([e for e in events if e['kind'] == 'notice'])
        for evt in (e for e in events if e['kind'] == 'notice'):
            self.assertTrue(evt['message'].strip(), evt)

    def test_limit_codes_are_split_into_two_classes(self):
        """「少结果」/「只是慢」这一分类必须逐码有归属，且不重不漏。

        这是**双向**键名比对：新增一个 limits_hit 码而忘了分类，这条就红 —— 前端不再抄
        一份码名表（它只读 `notice.incomplete`），所以唯一的漂移闸就是这里。
        """
        both = INCOMPLETE_CODES & SPEED_ONLY_CODES
        self.assertEqual(both, set(), f'同一码不可能既少结果又只是慢：{sorted(both)}')
        missing = set(TRUNCATION_TEXT) - (INCOMPLETE_CODES | SPEED_ONLY_CODES)
        self.assertEqual(missing, set(), f'未分类的 limits_hit 码：{sorted(missing)}')
        unknown = (INCOMPLETE_CODES | SPEED_ONLY_CODES) - set(TRUNCATION_TEXT)
        self.assertEqual(unknown, set(), f'分类里有、码表里没有（文案会 KeyError）：{sorted(unknown)}')
        self.assertFalse(set(CLAMPED_TEXT) & set(TRUNCATION_TEXT),
                         '钳位码只告知不进 limits_hit，混进截断表就会串味')

    def test_incomplete_flag_follows_the_class(self):
        self.assertTrue(notice('truncated_candidates')['incomplete'])
        for code in ('workers_reduced', 'grep_fallback', 'grep_unavailable'):
            self.assertFalse(notice(code)['incomplete'], code)
        self.assertFalse(notice('clamped_workers')['incomplete'])

    def test_truncation_notice_is_marked_incomplete_in_the_stream(self):
        events, _ = run(spec(max_candidates=1))
        hits = [e for e in events if e['kind'] == 'notice' and e['code'] == 'truncated_candidates']
        self.assertTrue(hits)
        self.assertTrue(hits[0]['incomplete'])
        self.assertTrue(first(events, 'done')['truncated'])

    def test_every_limits_hit_code_also_arrived_as_a_notice(self):
        """前端能只渲染 notice 文案的前提：进了 `limits_hit` 的码必然也发过一条带文案的 notice。

        破一条就是用户看到一个裸英文码（或啥也看不见），而前端并没有第二份码表可查。
        """
        cases = [spec(max_candidates=1), spec(max_matches=3, data_files_only=False),
                 spec(mode='name', depth='children', data_files_only=False),
                 spec(workers=8, max_candidates=1)]
        for s in cases:
            with self.subTest(**{k: getattr(s, k) for k in ('mode', 'depth', 'max_candidates')}):
                events, _ = run(s)
                done = first(events, 'done')
                emitted = {e['code']: e for e in events if e['kind'] == 'notice'}
                for code in done['limits_hit']:
                    self.assertIn(code, emitted, f'{code} 只进了 limits_hit，没发 notice')
                    self.assertTrue(emitted[code]['message'].strip())
                    self.assertEqual(emitted[code]['incomplete'],
                                     code in INCOMPLETE_CODES, code)


class MatchPayloadTests(SimpleTestCase):
    def test_content_match_carries_line_snippet_and_metadata(self):
        events, _ = run(spec())
        items = match_items(events)
        self.assertTrue(items)
        for one in items:
            for key in ('path', 'name', 'size', 'mtime', 'line', 'snippet',
                        'test_file', 'start_time'):
                self.assertIn(key, one)
        # 命中来自并发扫描，跨目录的到达顺序不是契约的一部分（walker 并发列目录），
        # 所以这里问「有没有解析出文件头」，而不是问第几号文件先到。
        with_head = [i for i in items if i['test_file']]
        self.assertEqual([i['test_file'] for i in with_head], ['lotA_w01.stdf'])
        self.assertEqual(with_head[0]['start_time'], '2026-09-01 08:12:33')

    def test_column_match_carries_values(self):
        events, _ = run(spec(mode='column', term='', column_name='ShadowReg2'))
        items = match_items(events)
        self.assertTrue(items and items[0]['values'])

    def test_name_mode_emits_no_match_events(self):
        events, _ = run(spec(mode='name', data_files_only=False))
        self.assertNotIn('match', kinds(events))

    def test_one_per_folder_scans_one_file_per_directory(self):
        tree = {f'/data/batch1/f{i}.csv': b'[DATA]\r\nSN,ShadowReg2\r\n1,0.5\r\n'
                for i in range(10)}
        _events, sftp = run(spec(one_per_folder=True, data_files_only=False), tree)
        self.assertEqual(sftp.open_count, 1)


class ErrorEventTests(SimpleTestCase):
    def test_unreadable_dir_becomes_scoped_error(self):
        s = spec()
        sftp = FakeSftp(sample_tree(), unreadable=['/data/batch1'])
        events = list(SearchRunner(s, _ExecSpy(sftp, size=1)).events())
        self.assertIn(('/data/batch1', 'dir'),
                      [(e['path'], e['scope']) for e in events
                       if e['kind'] == 'error'])

    def test_search_continues_past_a_failing_file(self):
        """单文件读失败绝不能终止整次搜索。"""
        events, _ = run(spec())
        self.assertTrue([i for e in events if e['kind'] == 'match'
                         for i in e['items']])

    def test_done_is_still_emitted_after_errors(self):
        sftp = FakeSftp(sample_tree(), unreadable=['/data/batch1'])
        events = list(SearchRunner(spec(), _ExecSpy(sftp, size=1)).events())
        self.assertEqual(kinds(events)[-1], 'done')


class GrepProbeWiringTests(SimpleTestCase):
    def test_probe_failure_becomes_grep_unavailable_notice(self):
        """探测不过不是错误而是环境事实：回落 client 并告知（spec §3.6）。"""
        runner = _ProbeStub(spec(), FakeSession(FakeSftp(sample_tree()), size=1))
        events = list(runner.events())
        self.assertIn('grep_unavailable', codes(events))
        self.assertEqual(first(events, 'hello')['engine'], 'client')

    def test_probe_is_not_paid_for_when_grep_cannot_be_used(self):
        """列候选 / 列值查询根本用不上 grep：不该多花一次 exec 往返。"""
        for over in ({'mode': 'name', 'data_files_only': False},
                     {'mode': 'column', 'term': '', 'column_name': 'SN'},
                     {'allow_server_grep': False}):
            with self.subTest(**over):
                session = _ExecSpy(FakeSftp(sample_tree()), size=1)
                list(SearchRunner(spec(**over), session).events())
                self.assertEqual(session.exec_calls, 0)

    def test_probe_happens_exactly_once_when_it_could_be_used(self):
        """正对照：内容档确实探测一次，而且只一次（每文件一次往返会慢到不能用）。"""
        session = _ExecSpy(FakeSftp(sample_tree()), size=1)
        events = list(SearchRunner(spec(), session).events())
        self.assertEqual(session.exec_calls, 1)
        self.assertEqual(first(events, 'hello')['engine'], 'client')

    def test_fuzzy_query_does_not_claim_grep_was_unavailable(self):
        """spec 侧的回落原因不能被探测文案盖掉（用户下次换服务器还得踩一遍）。"""
        runner = _ProbeStub(spec(matching='fuzzy'),
                            FakeSession(FakeSftp(sample_tree()), size=1))
        events = list(runner.events())
        self.assertNotIn('grep_unavailable', codes(events))
        self.assertEqual(first(events, 'done')['engine'], 'client')


class GrepPathTests(SimpleTestCase):
    def test_grep_engine_skips_listing(self):
        """grep 档一次性完成列举+匹配：不该有 listing 阶段、不该有 candidates。"""
        tree = {'/d/a.csv': b'x,ShadowReg2\r\n'}
        s = spec()
        sftp = FakeSftp(tree)

        def chan_factory():
            return _GrepChan([b'/d/a.csv:1:x,ShadowReg2\r\n'])

        runner = SearchRunner(
            s, FakeSession(sftp, size=1), chan_factory=chan_factory,
            forced_engine='grep')
        events = list(runner.events())
        self.assertEqual(first(events, 'hello')['engine'], 'grep')
        self.assertNotIn('candidates', kinds(events))
        self.assertEqual(sftp.listdir_calls, [])

    def test_grep_stage_sequence_is_scanning_then_done(self):
        tree = {'/d/a.csv': b'x,ShadowReg2\r\n'}
        sftp = FakeSftp(tree)
        runner = SearchRunner(
            spec(), FakeSession(sftp, size=1),
            chan_factory=lambda: _GrepChan([b'/d/a.csv:1:x,ShadowReg2\r\n']),
            forced_engine='grep')
        events = list(runner.events())
        self.assertEqual([e['stage'] for e in events if e['kind'] == 'stage'],
                         ['scanning', 'done'])
        self.assertTrue([p for p in events if p['kind'] == 'progress'])
        for prog in (p for p in events if p['kind'] == 'progress'):
            self.assertIsNone(prog['total'], 'grep 档全程没有分母（spec §3.8）')
        self.assertEqual(first(events, 'done')['engine'], 'grep')

    def test_grep_match_item_has_the_same_shape_as_client(self):
        tree = {'/d/a.csv': b'[HEADER]\r\nTestFile,D:\\x\\lotB_w02.stdf\r\n'
                            b'[DATA]\r\nx,ShadowReg2\r\n'}
        runner = SearchRunner(
            spec(), FakeSession(FakeSftp(tree), size=1),
            chan_factory=lambda: _GrepChan([b'/d/a.csv:2:x,ShadowReg2\r\n']),
            forced_engine='grep')
        one = match_items(list(runner.events()))[0]
        for key in ('path', 'name', 'size', 'mtime', 'line', 'snippet',
                    'test_file', 'start_time'):
            self.assertIn(key, one)
        self.assertEqual(one['line'], 2)
        self.assertEqual(one['test_file'], 'lotB_w02.stdf')
        self.assertEqual(one['size'], len(tree['/d/a.csv']))

    def test_grep_runtime_failure_falls_back_to_client(self):
        """探测过了但真跑炸了：必须回落并让用户看见这次回落。"""
        s = spec()

        def chan_factory():
            return _GrepChan([], exit_status=2)

        runner = SearchRunner(
            s, FakeSession(FakeSftp(sample_tree()), size=1),
            chan_factory=chan_factory, forced_engine='grep')
        events = list(runner.events())
        self.assertTrue(any(e['kind'] == 'notice' and 'grep' in e['code']
                            for e in events))
        self.assertEqual(first(events, 'done')['engine'], 'client')

    def test_grep_fallback_is_recorded_in_limits_hit(self):
        runner = SearchRunner(
            spec(), FakeSession(FakeSftp(sample_tree()), size=1),
            chan_factory=lambda: _GrepChan([], exit_status=2),
            forced_engine='grep')
        events = list(runner.events())
        self.assertIn('grep_fallback', codes(events))
        self.assertIn('grep_fallback', first(events, 'done')['limits_hit'])
        self.assertTrue(match_items(events), '回落后必须给出 client 档的结果')


class CancellationTests(SimpleTestCase):
    def test_close_after_events_leaves_no_open_files(self):
        """SearchRunner 必须自己收干净：runner 返回后不应还有未关闭的连接。"""
        s = spec()
        sftp = FakeSftp(sample_tree())
        runner = SearchRunner(s, _ExecSpy(sftp, size=1))
        for _ in runner.events():
            break                     # 只取一个事件就放弃（模拟 GeneratorExit）
        runner.close()
        self.assertTrue(runner.closed)

    def test_generator_exit_closes_every_connection(self):
        """GeneratorExit 走 finally：借出去的连接必须全部还回并关掉（spec §3.7）。"""
        session = _CountingSession(FakeSftp(sample_tree()), size=2)
        gen = SearchRunner(spec(), session).events()
        self.assertEqual(next(gen)['kind'], 'hello')
        gen.close()
        self.assertEqual((session.opened, session.closed), (2, 2))

    def test_cancel_event_is_set_before_the_connections_are_dropped(self):
        """取消三件事的顺序不能反：先喊停，再关连接，否则 worker 会拿到半截数据。

        这里**不**自己 set 事件：让 ``close()`` 在 GeneratorExit 的 finally 里去做，
        被观测的才是 runner 内部那三件事的先后。
        """
        ev = threading.Event()
        session = _CountingSession(FakeSftp(sample_tree()), size=1)

        def spy():
            session.event_set_when_closed = ev.is_set()
            session.closed = session.opened
        session.close_all = spy
        runner = SearchRunner(spec(), session, cancel_event=ev)
        gen = runner.events()
        next(gen)
        gen.close()
        self.assertTrue(session.event_set_when_closed,
                        'close_all 之前必须已经 cancel_event.set()')

    def test_executor_is_not_used_as_context_manager(self):
        """源码级守卫：把线程池构造写进 ``with`` 括号里，退出时会 join 全部 worker，
        取消时把请求挂住直到几千个文件扫完。持有线程池的模块里绝不允许出现。"""
        import inspect
        runner_module = inspect.getmodule(SearchRunner)   # 阶段机拆在 runner.py 里
        for module in (engine, runner_module, walker):
            src = inspect.getsource(module)
            self.assertNotIn('with ThreadPoolExecutor(', src,
                             f'{module.__name__}: 必须显式 shutdown(wait=False, '
                             f'cancel_futures=True)')
        # 反向半边：扫描线程池所在的那个模块必须真的不 join。
        src = inspect.getsource(runner_module)
        self.assertIn('shutdown(wait=False', src)

    def test_cancel_event_stops_before_scanning_all(self):
        ev = threading.Event()
        s = spec()
        sftp = FakeSftp(sample_tree())
        runner = SearchRunner(s, _ExecSpy(sftp, size=1), cancel_event=ev)
        seen = 0
        for _event in runner.events():
            seen += 1
            if seen == 1:
                ev.set()
        self.assertTrue(runner.cancelled)

    def test_cancel_during_scanning_returns_promptly_and_kills_the_pool(self):
        """真取消：几千个文件、每个 20ms —— 取消必须秒级返回且不留 worker 线程。"""
        tree = {f'/data/b{i}.csv': b'x,ShadowReg2\r\n' for i in range(2000)}
        ev = threading.Event()
        sftp = _SlowSftp(tree)
        runner = SearchRunner(spec(workers=4),
                                     _ExecSpy(sftp, size=4), cancel_event=ev)
        gen = runner.events()
        started = time.monotonic()
        for event in gen:
            if event['kind'] == 'match':
                ev.set()
                break
        gen.close()
        self.assertLess(time.monotonic() - started, 3.0,
                        '取消被挂在了扫描上：worker 只认 threading.Event')
        self.assertTrue(runner.cancelled)
        self.assertLess(sftp.open_count, len(tree), '剩余文件不该继续扫')
        self._assert_no_search_threads_left()

    def _assert_no_search_threads_left(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            left = [t.name for t in threading.enumerate()
                    if SCAN_THREAD_PREFIX in t.name]
            if not left:
                return
            time.sleep(0.02)
        self.fail(f'线程池没退干净，残留 worker 线程：{left}')


class _GrepChan:
    def __init__(self, lines, exit_status=0):
        self.lines = list(lines)
        self.exit_status = exit_status
        self.closed = False

    def exec_command(self, cmd):
        self.command = cmd

    def settimeout(self, seconds):
        self.timeout = seconds

    def makefile(self, *a, **k):
        return self

    def readline(self):
        return self.lines.pop(0) if self.lines else b''

    def read(self, n=-1):
        return b''

    def recv_exit_status(self):
        return self.exit_status

    def close(self):
        self.closed = True
