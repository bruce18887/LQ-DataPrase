"""真 paramiko SFTP 服务器上的并行一致性集成测试（spec §4.3）。

全计划里**唯一**能抓出「多线程共用一条 channel 把协议流写乱」（参考工具
``csv_content_searcher.py:24-27`` 记的 ``Garbage packet received``）的一级：
``FakeSftp`` 与 ``MagicMock`` 都不走协议，只有真客户端对真服务器才会现形。
所以这里跑的是真 ``paramiko.SFTPClient`` 对真 ``paramiko.SFTPServer`` 子进程。

最值钱的一条断言：同一份 spec，``workers=1`` 与 ``workers=4`` 的结果集逐字相同。
不一致就是竞态，必须当场解决——放宽断言或加 sleep 都等于把这一级作废。

跑法：python manage.py test test.backend.test_sftp_search_integration
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, REPO_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase, override_settings  # noqa: E402

from apps.sftp.search import contracts, walker  # noqa: E402
from apps.sftp.search.connect import SearchSession  # noqa: E402
from apps.sftp.search.runner import SearchRunner  # noqa: E402

SERVER = os.path.join(REPO_ROOT, 'frontend', 'e2e', 'helpers', 'sftp_server.py')
# 首行超时含「造 20 万行 fixture」这段时间；超时即判定起不来，不无限阻塞在管道上。
STARTUP_TIMEOUT_SEC = 10
# 搜索的软超时（`spec.timeout`，判点在 ``runner._stopped``）：卡在**扫描**阶段时到点收尾。
# 健康跑单次约 0.2s，这里宽 100 倍。
COLLECT_TIMEOUT_SEC = 30
# 硬上限（看门狗）：列目录阶段的卡死是上面那条救不了的 —— runner 只在两批目录之间判
# 超时，而 ``walker`` 的 ``as_completed`` 永不返回。真竞态在服务器上的表现常常就是**卡死**
# 而不是错值（实测把 4 个 worker 换成共用一条 channel 后永不返回），没有这一层就等于把
# 整条 ``manage.py test`` 挂住；有它才是一次有界、可复现的失败。
HARD_CAP_SEC = 60


class _Server:
    """起停真 SFTP 服务器子进程。

    任何失败路径都要杀进程 + 删临时目录：``sftpServer.ts:40-43`` 那段注释就是为
    ``%TEMP%`` 泄漏写的，Python 侧同罪。主机密钥每次新生成，故配合下面的
    ``SFTP_HOST_KEY_CHECK='off'``（业务代码里不许出现 ``AutoAddPolicy``）。
    """

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix='sftp-int-')
        self.proc = None
        self._stderr = tempfile.TemporaryFile()
        self._stopped = False
        try:
            self.proc = subprocess.Popen(
                [sys.executable, SERVER, '--root', self.root, '--fixture'],
                stdout=subprocess.PIPE, stderr=self._stderr, text=True)
            info = json.loads(self._read_hello_line())
            self.host, self.port = info['host'], info['port']
        except Exception as exc:              # noqa: BLE001 - 起不来就地收尾再抛，别留孤儿
            detail = self._drain_stderr()
            self.stop()
            raise AssertionError(
                f'SFTP 测试服务器没起来（{type(exc).__name__}: {exc}）；'
                f'stderr={detail!r}') from exc

    def _read_hello_line(self) -> str:
        """读 stdout 首行（``{"host":..., "port":...}``），带超时。"""
        box: queue.Queue = queue.Queue(maxsize=1)

        def reader():
            try:
                box.put(self.proc.stdout.readline())
            except BaseException as exc:      # noqa: BLE001 - 交回主线程重抛，线程里 print 没用
                box.put(exc)

        threading.Thread(target=reader, daemon=True).start()
        try:
            line = box.get(timeout=STARTUP_TIMEOUT_SEC)
        except queue.Empty:
            raise TimeoutError(
                f'{STARTUP_TIMEOUT_SEC}s 内没有输出端口 JSON（fixture 造树太慢或子进程没起）'
            ) from None
        if isinstance(line, BaseException):
            raise line
        if not line:
            raise RuntimeError('子进程已退出，stdout 首行为空')
        return line

    def _drain_stderr(self) -> str:
        self._stderr.seek(0)
        return self._stderr.read()[:1000].decode('utf-8', errors='replace')

    def stop(self) -> None:
        """terminate → 超时才 kill；无论如何删临时目录。幂等。"""
        if self._stopped:
            return
        self._stopped = True
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:      # 收尾不留孤儿进程
                self.proc.kill()
                self.proc.wait(timeout=5)
            if self.proc.stdout is not None:
                self.proc.stdout.close()
        self._stderr.close()
        shutil.rmtree(self.root, ignore_errors=True)


def collect(spec_kwargs, workers):
    """直连 runner/session 跑一次真服务器搜索（绕开 HTTP 层）。

    返回 ``(matched 路径, candidates 路径, 全部事件)``，两个路径列表都排过序：并行只该
    改变到达顺序、不该改变集合，所以比较前把两边归一到同一个可比较形状。
    """
    spec = contracts.parse_spec({**spec_kwargs, 'workers': workers,
                                 'timeout': COLLECT_TIMEOUT_SEC})
    session = SearchSession(1, workers)
    session.open_all()
    runner = None
    try:
        runner = SearchRunner(spec, session)
        events = _drain_events(runner, session)
    finally:
        if runner is not None:
            runner.close()
        session.close_all()
    matched = sorted(i['path'] for e in events if e['kind'] == 'match'
                     for i in e['items'])
    candidates = sorted(i['path'] for e in events if e['kind'] == 'candidates'
                        for i in e['items'])
    return matched, candidates, events


def _drain_events(runner, session):
    """把事件流排空，但**绝不无限等**：卡死就地判红（见 ``HARD_CAP_SEC`` 那段）。

    线程只用来给卡死一个边界，不改变被测语义：异常照样原样抛回本线程，
    收尾仍由调用方的 ``finally`` 做（这里先把连接关掉，把卡在读响应上的线程逼出来）。
    """
    done = threading.Event()
    box: list = []

    def drain():
        try:
            box.append(('ok', list(runner.events())))
        except BaseException as exc:          # noqa: BLE001 - 交回主线程重抛，线程里 print 没用
            box.append(('err', exc))
        finally:
            done.set()

    threading.Thread(target=drain, name='sftp-int-collect', daemon=True).start()
    done.wait(HARD_CAP_SEC)
    if not done.is_set():
        runner.close()
        session.close_all()
        done.wait(HARD_CAP_SEC)
        raise AssertionError(
            f'搜索在 {HARD_CAP_SEC}s 内没有收尾（workers={runner.spec.workers}）。'
            '并行=1 时若正常，这就是并行路径上的协议流竞态：多线程共用一条 channel 后 '
            'response 会被别的线程读走，列目录线程永久等在 read_response 上。')
    status, payload = box[0]
    if status == 'err':
        raise payload
    return payload


@override_settings(SFTP_HOST_KEY_CHECK='off')
class ParallelConsistencyTests(SimpleTestCase):
    """该服务器每次新生成 RSAKey，故关掉主机密钥校验；
    真连接的 TOFU 契约由 test_sftp_host_keys.py 专门守。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = _Server()
        cls._orig = SearchSession._credentials

        def creds(self):
            return {'host': cls.srv.host, 'port': cls.srv.port,
                    'username': 'any', 'password': 'any'}
        SearchSession._credentials = creds

    @classmethod
    def tearDownClass(cls):
        SearchSession._credentials = cls._orig
        cls.srv.stop()
        super().tearDownClass()

    NAME_ONLY = {'roots': ['/'], 'mode': 'name', 'data_files_only': False}
    CONTENT = {'roots': ['/'], 'mode': 'content', 'term': 'ShadowReg2',
               'data_files_only': False}

    def test_single_vs_four_workers_same_result(self):
        """最值钱的一条：并行不得改变结果。不一致就是协议流竞态。"""
        m1, c1, _ = collect(self.CONTENT, 1)
        m4, c4, _ = collect(self.CONTENT, 4)
        self.assertEqual(m1, m4)
        self.assertEqual(c1, c4)
        self.assertTrue(m1, '真服务器上应当有命中')
        # fixture 里那 200 份小文件的全部意义在这一句：命中太少就等于只测了「必然炸」，
        # 测不到「偶发竞态」。少了这批，本文件相对 FakeSftp 就没有增量。
        self.assertGreater(len(c1), 200, f'候选只有 {len(c1)} 个，并行量级不够')

    def test_eight_workers_still_identical(self):
        m1, _, _ = collect(self.CONTENT, 1)
        m8, _, _ = collect(self.CONTENT, 8)
        self.assertEqual(m1, m8)

    def test_repeated_runs_are_stable(self):
        """同一 spec 跑三遍结果必须逐字相同 —— 竞态常表现为偶发差异。"""
        first = collect(self.CONTENT, 4)
        for _ in range(2):
            again = collect(self.CONTENT, 4)
            self.assertEqual(first[0], again[0])

    def test_gbk_chinese_term_hits_the_real_file(self):
        """编码探测在真 read() 分块下也要成立（假 sftp 一次给完整内容）。"""
        matched, _c, events = collect(
            {'roots': ['/'], 'mode': 'content', 'term': '漏电电流',
             'data_files_only': False}, 2)
        self.assertEqual(matched, ['/batch2/RT_10.csv'])
        hello = next(e for e in events if e['kind'] == 'hello')
        self.assertEqual(hello['engine'], 'client', '非 ASCII 必须走客户端引擎')

    def test_line_number_of_deep_hit_matches_expected(self):
        """20 万行、跨多个 1 MiB chunk 之后的行号计数，只有真读能验。

        计划原文断言 ``item['line'] > 200_000``，但那测不到：``first_hit_per_file`` 默认
        True，而 BIG.csv 的第 2 行就含 ``ShadowReg2``（与 ``sftp_fake.sample_tree()`` 同形
        的头部），顶层 ``line`` 恒为 2。改成显式要多次命中、比最后一条的**绝对行号**，
        并把首命中钉在 2 行 —— 两头都对，才算真验到了跨 chunk 的行号累加。
        """
        matched, candidates, events = collect(
            {**self.CONTENT, 'first_hit_per_file': False, 'matches_per_file': 20}, 2)
        self.assertIn('/batch1/BIG.csv', matched)
        one = next(i for e in events if e['kind'] == 'match'
                   for i in e['items'] if i['path'] == '/batch1/BIG.csv')
        self.assertEqual(one['line'], 2, '首命中就是文件头那一行')
        self.assertGreater(one['hits'][-1]['line'], 200_000)
        # 进度：收尾必须有一帧带真分母（§3.8），且分母 = 候选数 = 扫过的文件数。
        progress = [e for e in events if e['kind'] == 'progress']
        self.assertTrue(progress, '20 万行的扫描必须吐进度帧')
        last = progress[-1]
        self.assertEqual(last['stage'], 'scanning')
        self.assertEqual(last['total'], len(candidates))
        self.assertEqual(last['done'], last['total'], '收尾帧的分子该等于扫完的文件数')

    def test_depth_prune_and_dotdir_semantics_on_real_server(self):
        _m, c_all, _ = collect({**self.NAME_ONLY, 'depth': 'all'}, 2)
        _m, c_children, _ = collect({**self.NAME_ONLY, 'depth': 'children'}, 2)
        self.assertIn('/batch1/Deep/RT_3.csv', c_all)
        self.assertNotIn('/batch1/Deep/RT_3.csv', c_children)
        self.assertNotIn('/.hidden/RT_8.csv', c_all)
        _m, c_pruned, _ = collect({**self.NAME_ONLY, 'prune_dirs': ['backup']}, 2)
        self.assertNotIn('/backup/RT_9.csv', c_pruned)

    def test_summary_and_non_csv_excluded_by_data_files_only(self):
        """``data_files_only`` 默认档在真服务器上也得挡住汇总与非 CSV。

        fixture 里 ``Sum_total.csv`` 刻意含查询串 —— 不含的话「被排除」这条断言就是空转。
        """
        _m, c, _e = collect({'roots': ['/'], 'mode': 'name'}, 2)
        self.assertIn('/batch1/RT_1.csv', c)
        self.assertNotIn('/batch1/Sum_total.csv', c)
        self.assertNotIn('/batch1/notes.txt', c)

    def test_unreadable_dir_degrades_to_one_dir_scoped_error(self):
        """服务端列不出来的目录只降级成一条 ``error{scope:"dir"}``，不炸整次搜索。"""
        matched, candidates, events = collect(self.CONTENT, 4)
        dirs = [e for e in events
                if e.get('kind') == 'error' and e.get('scope') == 'dir']
        self.assertEqual([e['path'] for e in dirs], ['/NoAccess'], dirs)
        self.assertNotIn('/NoAccess/RT_7.csv', candidates)
        self.assertNotIn('/NoAccess/RT_7.csv', matched)
        self.assertTrue(matched, '一个坏目录不该让整次搜索没有结果')
        done = next(e for e in events if e['kind'] == 'done')
        self.assertIn('dir_unreadable', done['limits_hit'])

    def test_dir_resolution_never_degrades_silently_on_real_client(self):
        """环保护靠「解析后的真身」去重（§3.4），这条在真客户端上必须是活的。

        集成测试第一次跑就抓到：paramiko 5.0 的 ``SFTPClient`` **没有** ``realpath``
        （改叫 ``normalize``），而 ``FakeSftp`` 两个都有 —— 于是每次列目录都静默退回
        normpath，软链接环保护变成「只有 max_entries/timeout 兜着」。这类 API 漂移
        MagicMock 永远测不到，正是本文件存在的理由。降级只许是异常路径。
        """
        session = SearchSession(1, 1)
        session.open_all()
        try:
            item = session.borrow()
            try:
                with self.assertNoLogs('apps.sftp.search.walker', level='WARNING'):
                    resolved = walker._resolve_dir(item[1], '/batch1/Deep')
            finally:
                session.give_back(item)
        finally:
            session.close_all()
        self.assertEqual(resolved, '/batch1/Deep')

    def test_no_connection_leak_after_each_run(self):
        """每次搜索的临时连接必须散干净。"""
        before = threading.active_count()
        for _ in range(3):
            collect(self.CONTENT, 4)
        time.sleep(1.0)
        self.assertLessEqual(threading.active_count(), before + 1,
                             '线程未回收：executor 可能用了 with（会 join）或没 shutdown')
