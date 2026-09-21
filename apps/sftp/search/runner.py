"""``SearchRunner``：一次搜索的阶段机与事件流（spec §3.8 / §3.9）。

「阶段」这个概念只允许存在于本文件：walker 只列候选、scanners 只扫一个文件、
shell_grep 只跑一条命令，它们都只吃 spec、只吐事件，不知道 Django，也不知道彼此。
把它们串成 ``probe → LISTING → SCANNING → DONE``、并决定什么时候发什么事件，是本模块
的唯一职责。事件的协议字面量（kind / 码表 / 批合成阈值）在 :mod:`.events`，
「这次用哪一档引擎」的谓词在 :mod:`.engine`。

四条不可让的性质（各有一条测试钉着）：

1. **grep 档没有候选阶段**：不发 ``stage:'listing'``、不发 ``candidates``，进度全程
   ``total: null``（§3.8）。前端据此走三态进度的不定档。
2. **取消三件事的顺序与形式**：``cancel_event.set()`` → 不 join 地关掉线程池 →
   关掉全部临时连接（§3.9）。线程池**绝不当上下文管理器用**，因为它的 ``__exit__``
   是 ``shutdown(wait=True)``，取消时会把这条 HTTP 请求挂住直到几千个文件扫完。
3. **生成器以 ``queue.get(timeout=EVENT_POLL_SEC)`` 排空**，取消延迟因此有界；收到
   ``GeneratorExit`` 后不再 yield，清理全在 ``finally``。
4. **上限从不静默**：每个截断/降级码都出一条 ``notice`` 并汇总进 ``done.limits_hit``。
"""

import logging
import posixpath
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

from apps.sftp.downloads import channel_timeout
from apps.sftp.search import scanners, shell_grep, walker
from apps.sftp.search.connect import CONNECTION_ERRORS
from apps.sftp.search.contracts import READ_TIMEOUT_SEC, SearchSpec
from apps.sftp.search.engine import (PROBE_NO_ACCELERATION, ProbeResult,
                                     probe_caused_fallback, select_engine)
# 逐个名字 import，不是 ``import events``：类里有个叫 ``events()`` 的方法，类体中
# ``events.Flusher`` 会先撞上那个方法对象（注解在 class 语句执行时就要求值）。
from apps.sftp.search.events import (EVENT_POLL_SEC, INCOMPLETE_CODES,
                                      SCAN_THREAD_PREFIX, TRUNCATION_TEXT,
                                      Flusher, brief, notice)

logger = logging.getLogger(__name__)

_META_CACHE_MAX = 512        # grep 档补元数据的按路径缓存上限，防长查询吃内存


class SearchRunner:
    """一次搜索的阶段机，输出 spec §3.8 的那些事件 dict。

    ``chan_factory`` 只被 grep 档（与能力探测）用来开 exec 通道，缺省即从 session 借一条
    transport；``forced_engine`` **只为测试 grep 分支而存在**，生产路径的引擎一律由
    :func:`~apps.sftp.search.engine.select_engine` 决定 —— 有测试替身之后，grep 分支不该
    等到接上真服务器才第一次被执行。``now`` 注入的是单调时钟，测试不需要真 sleep 就能
    造出「攒够 200ms」与超时。
    """

    def __init__(self, spec: SearchSpec, session, *,
                 chan_factory: Optional[Callable[[], Any]] = None,
                 cancel_event: Optional[threading.Event] = None,
                 forced_engine: Optional[str] = None,
                 now: Callable[[], float] = time.monotonic):
        self.spec = spec
        self.session = session
        self.forced_engine = forced_engine
        self.now = now
        # 未注入的两者都有生产默认值：取消信号是本次搜索自己的 Event，exec 通道则
        # 从 session 借一条 transport 现开（spec §3.6：搜索只碰临时连接）。
        self.cancel_event = cancel_event or threading.Event()
        self._chan_factory = chan_factory or self._open_exec_channel
        self.executor: Optional[ThreadPoolExecutor] = None
        self.deadline: Optional[float] = None
        self.closed = False
        self.cancelled = False
        self.timed_out = False
        self.engine_used = 'client'
        self._limits: List[str] = []
        self._candidate_frames: List[Dict[str, Any]] = []
        self._candidate_flusher = Flusher(now)
        self._candidates_emitted = 0
        self._received = 0          # worker 推来的命中条数（可能多于上限）
        self._emitted = 0           # 已经发给前端的命中条数
        self._scanned = 0
        self._bytes_scanned = 0
        self._own_stop = False      # 达到上限/够了 → 是自己停的，不是用户取消
        self._finished = False
        self._started = now()
        self._meta_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ 事件流

    def events(self) -> Iterator[Dict[str, Any]]:
        """吐本次搜索的全部事件。清理只在 finally 里做，GeneratorExit 也不例外。"""
        q: queue.Queue = queue.Queue()
        self.deadline = self.now() + self.spec.timeout
        try:
            probe = None
            if self.forced_engine:
                engine_name = self.forced_engine
                reason = '由调用方指定的引擎（仅测试路径，生产走 select_engine）'
            else:
                probe = self._probe()
                engine_name, reason = select_engine(self.spec, probe)
            yield {'kind': 'hello', 'engine': engine_name, 'engine_reason': reason,
                   'workers_actual': self.session.size, 'roots': list(self.spec.roots)}
            for code in self.spec.clamped:
                yield notice(code)
            if engine_name == 'client' and probe_caused_fallback(reason, probe):
                yield notice('grep_unavailable', reason)
            if self.session.size < self.spec.workers:
                yield self._limit(
                    'workers_reduced',
                    f'服务器只接受了 {self.session.size}/{self.spec.workers} 条并发连接，'
                    f'本次按 {self.session.size} 并行继续')
            if engine_name == 'grep':
                yield from self._run_grep(q)
            else:
                yield from self._run_client(q)
        finally:
            self.close()          # 幂等；GeneratorExit / 正常收尾 / 异常都走这里

    def _probe(self) -> ProbeResult:
        """grep 档的全部前提：两级能力探测（spec §3.6）。

        探测不过不是错误而是环境事实，所以不上抛、由 ``select_engine`` 转成回落。
        不需要加速的查询（列候选、列值、用户关了加速）连探测都不发，省一次 exec 往返。
        """
        if not self.spec.allow_server_grep or self.spec.mode != 'content':
            return ProbeResult(False, False, False, PROBE_NO_ACCELERATION)
        return shell_grep.probe(self._chan_factory, self.spec.roots)

    def _open_exec_channel(self) -> Any:
        """生产路径的 exec 通道：借一条临时连接的 transport 自己开会话（spec §3.6）。

        池连接不参与搜索，所以这里拿到的 transport 只属于本次搜索。
        """
        return self.session.exec_transport().open_session(timeout=READ_TIMEOUT_SEC)

    # ------------------------------------------------------------------ client 档

    def _run_client(self, q: queue.Queue) -> Iterator[Dict[str, Any]]:
        """LISTING → SCANNING：BFS 列候选（批合成）后并行扫描。"""
        spec = self.spec
        self.engine_used = 'client'
        if self._stopped():
            yield from self._finish(0, 0)
            return
        yield self._stage('listing', 0, 0)
        yield self._progress('listing', 0, None)     # listing 没有分母：total 恒 None
        result = walker.walk(spec, self.session, on_candidate=self._on_candidate,
                             cancel_event=self.cancel_event, deadline=self.deadline)
        self._flush_candidate_tail()
        for frame in self._candidate_frames:
            yield frame
        for code in result.truncated:
            yield self._limit(code)
        for event in result.events:
            if event.get('kind') == 'error' and event.get('scope') == 'dir':
                if 'dir_unreadable' not in self._limits:
                    yield self._limit('dir_unreadable')
            yield event
        candidates = result.candidates
        yield self._progress('listing', len(candidates), None)
        # 只列候选 / 名字档没有可扫的东西 / 一个候选都没有 / 遍历被取消或超时：到此为止。
        if (spec.stop_after_listing or spec.mode == 'name' or not candidates
                or self._stopped()):
            matched = len(candidates) if (spec.mode == 'name'
                                          or spec.stop_after_listing) else self._emitted
            yield from self._finish(matched, self._scanned)
            return
        yield from self._run_scanning(candidates, q)

    def _stage(self, stage: str, candidates: Any, matches: int) -> Dict[str, Any]:
        return {'kind': 'stage', 'stage': stage, 'candidates': candidates,
                'matches': matches}

    def _on_candidate(self, cand) -> None:
        """walker 的回调：攒候选帧。

        列目录期间生成器正阻塞在 ``walk()`` 里、发不出事件，所以满帧先存着，遍历一结束
        就整批发出去（``FLUSH_MAX_ITEMS`` 这条规则照常生效；200ms 那条在阻塞期管不到）。
        """
        self._candidate_flusher.add(cand.as_dict())
        if self._candidate_flusher.full:
            self._candidate_frames.append(
                self._candidates_event(self._candidate_flusher.take()))

    def _flush_candidate_tail(self) -> None:
        if self._candidate_flusher.items:
            self._candidate_frames.append(
                self._candidates_event(self._candidate_flusher.take()))

    def _candidates_event(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._candidates_emitted += len(items)
        return {'kind': 'candidates', 'items': items,
                'total_so_far': self._candidates_emitted}

    def _run_scanning(self, candidates: Sequence[Any],
                      q: queue.Queue) -> Iterator[Dict[str, Any]]:
        """并行扫描：worker 只往队列里塞消息，主线程有界排空并合成事件。"""
        spec = self.spec
        targets = (self._one_per_folder(candidates) if spec.one_per_folder
                   else list(candidates))
        total = len(targets)
        yield self._stage('scanning', total, self._emitted)
        workers = max(1, min(spec.workers, self.session.size))
        # 绝不把线程池当上下文管理器用（把构造写进 ``with`` 括号里那种写法）：它的
        # __exit__ 是 shutdown(wait=True)，取消时请求会挂到几千个文件扫完（spec §3.9
        # 第 1 条）。test_executor_is_not_used_as_context_manager 在源码层钉着这条，
        # 所以本文件连那个字面量都不许出现——注释里也不行。
        self.executor = ThreadPoolExecutor(max_workers=workers,
                                           thread_name_prefix=SCAN_THREAD_PREFIX)
        flusher = Flusher(self.now)
        last_progress = self.now()
        futures: List[Any] = []
        try:
            futures = [self.executor.submit(self._scan_one, cand, q) for cand in targets]
            while True:
                if self._stopped():
                    break
                for msg in self._drain(q, EVENT_POLL_SEC):
                    yield from self._handle(msg, flusher)
                if flusher.full or flusher.aged:
                    frame = self._emit_matches(flusher)
                    if frame:
                        yield frame
                if self._received >= spec.max_matches:
                    frame = self._emit_matches(flusher)
                    if frame:
                        yield frame
                    if self._received > self._emitted or self._pending(futures):
                        yield self._limit('truncated_matches')
                    self._stop_workers()
                    break
                if self.now() - last_progress >= EVENT_POLL_SEC:
                    yield self._progress('scanning', self._scanned, total)
                    last_progress = self.now()
                if not self._pending(futures):
                    break
        finally:
            if self.executor is not None:
                self.executor.shutdown(wait=False, cancel_futures=True)
        if not self._stopped():
            for msg in self._drain(q, 0.0):        # 只收现成的，不再等
                yield from self._handle(msg, flusher)
        frame = self._emit_matches(flusher)
        if frame:
            yield frame
        yield self._progress('scanning', self._scanned, total)   # 收尾必发一帧带分母
        yield from self._finish(self._emitted, self._scanned)

    @staticmethod
    def _pending(futures: List[Any]) -> bool:
        return any(not future.done() for future in futures)

    def _drain(self, q: queue.Queue, timeout: float) -> Iterator[Any]:
        """有界地取一条，再顺手把队列里现成的都收掉（保证取消延迟 ≤ timeout）。"""
        try:
            yield q.get(timeout=timeout)
        except queue.Empty:
            return
        while True:
            try:
                yield q.get_nowait()
            except queue.Empty:
                return

    def _handle(self, msg: Any, flusher: Flusher) -> List[Dict[str, Any]]:
        """折一条 worker 消息进计数器，返回需要立刻发出去的事件。"""
        kind, payload = msg
        if kind == 'match':
            self._received += 1
            flusher.add(payload)
            return []
        if kind == 'scanned':
            self._scanned += 1
            self._bytes_scanned += payload
            return []
        if kind == 'limit':
            return [self._limit(payload)]
        return [payload]                        # ('error', 已经成形的事件 dict)

    def _emit_matches(self, flusher: Flusher) -> Optional[Dict[str, Any]]:
        """出一帧命中；超出 ``max_matches`` 的尾巴裁掉（多攒的不能超发）。"""
        items = flusher.take()
        if not items:
            return None
        room = self.spec.max_matches - self._emitted
        if room < len(items):
            items = items[:max(0, room)]
        if not items:
            return None
        self._emitted += len(items)
        return {'kind': 'match', 'items': items}

    def _one_per_folder(self, candidates: Sequence[Any]) -> List[Any]:
        """每个目录只派一个文件（spec §3.4）：取遍历顺序里的第一个，稳定可复现。"""
        seen = set()
        picked = []
        for cand in candidates:
            parent = posixpath.dirname(cand.path)
            if parent in seen:
                continue
            seen.add(parent)
            picked.append(cand)
        return picked

    def _scan_one(self, cand, q: queue.Queue) -> None:
        """一个文件一条任务：借连接 → 设读超时 → 扫 → 还。

        worker 收不到 ``GeneratorExit``，所以只认 ``cancel_event``（spec §3.9 第 2 条）；
        连接级异常换一条连接**重试一次**，再失败就只丢这个文件（记
        ``error{scope:"file"}``），绝不终止整次搜索。
        """
        for attempt in (1, 2):
            if self.cancel_event.is_set():
                return
            try:
                item = self.session.borrow()
            except Exception as exc:  # noqa: BLE001 - 会话已关（取消路径）或补不上连接
                logger.warning('SFTP search skipped %s: no connection available (%s)',
                               cand.path, exc)
                return
            try:
                with channel_timeout(item[1], READ_TIMEOUT_SEC):
                    result = self._read_one(item[1], cand)
            except CONNECTION_ERRORS as exc:
                self.session.give_back(item, broken=True)
                if attempt == 1 and not self.cancel_event.is_set():
                    logger.warning(
                        'SFTP search hit a broken connection on %s (%s); retrying once '
                        'on a fresh one', cand.path, exc)
                    continue
                logger.warning('SFTP search could not read %s after retry: %s',
                               cand.path, exc)
                q.put(self._file_error(cand, exc))
                return
            except Exception as exc:  # noqa: BLE001 - 单文件的意外只丢这个文件，不丢搜索
                self.session.give_back(item)
                logger.warning('SFTP search failed on %s: %s', cand.path, exc,
                               exc_info=True)
                q.put(self._file_error(cand, exc))
                return
            self.session.give_back(item)
            if result:
                q.put(('match', result))
            q.put(('scanned', cand.size))
            if cand.size > self.spec.max_scan_bytes:
                # scan_file 到预算就停，但不会自带「为什么停」——按候选大小判定这一条。
                q.put(('limit', 'scan_budget_exceeded'))
            return

    def _read_one(self, sftp, cand):
        """按模式分派到扫描内核（列值档读值，其余按字节扫）。"""
        if self.spec.mode == 'column':
            return scanners.read_column(sftp, cand, self.spec)
        return scanners.scan_file(sftp, cand, self.spec)

    @staticmethod
    def _file_error(cand, exc: BaseException) -> Any:
        return ('error', {'kind': 'error', 'scope': 'file', 'path': cand.path,
                          'message': str(exc) or type(exc).__name__})

    # ------------------------------------------------------------------ grep 档

    def _run_grep(self, q: queue.Queue) -> Iterator[Dict[str, Any]]:
        """grep 档：一条 exec 通道跑完整棵树，只有命中流。

        §3.8 的三条「grep 档不发」都在这里：不发 ``stage:'listing'``、不发
        ``candidates``，``stage`` 序列是 ``scanning → done``，进度全程 ``total: null``。
        运行时失败（退出码 ≥2 / 连接炸了）整次改跑 client 档，并且必须先发
        ``notice{code:'grep_fallback'}`` 让用户看见这次换了引擎。
        """
        spec = self.spec
        if self._stopped():
            yield from self._finish(0, 0)
            return
        self.engine_used = 'grep'
        yield self._stage('scanning', None, self._emitted)
        yield self._progress('scanning', self._emitted, None)
        chan: Any = None
        flusher = Flusher(self.now)
        last_progress = self.now()
        try:
            chan = self._chan_factory()
            stream = shell_grep.grep_stream(chan, spec, cancel_event=self.cancel_event,
                                            deadline=self.deadline)
            for hit in stream:
                self._received += 1
                flusher.add(self._grep_item(hit))
                if flusher.full or flusher.aged or self._received >= spec.max_matches:
                    frame = self._emit_matches(flusher)
                    if frame:
                        yield frame
                if self._received >= spec.max_matches:
                    yield self._limit('truncated_matches')
                    self._stop_workers()
                    break
                if self.now() - last_progress >= EVENT_POLL_SEC:
                    yield self._progress('scanning', self._emitted, None)
                    last_progress = self.now()
                if self._stopped():
                    break
            frame = self._emit_matches(flusher)
            if frame:
                yield frame
            yield self._progress('scanning', self._emitted, None)
            yield from self._finish(self._emitted, len(self._meta_cache))
        except (RuntimeError,) + CONNECTION_ERRORS as exc:
            logger.warning('SFTP search: server-side grep broke at runtime (%s); '
                           'falling back to the client engine', exc)
            # 计数清零，免得 client 档的命中被 grep 档已发出去的条数顶掉上限；
            # 已经流出去的那几行会重复一次，所以文案里明说「重新搜索」。
            self._received = self._emitted = 0
            flusher.items = []
            yield self._limit('grep_fallback',
                              f'{TRUNCATION_TEXT["grep_fallback"]}'
                              f'（{brief(exc)}）：之前流出的命中可能重复')
            yield from self._run_client(q)
        finally:
            if chan is not None:
                try:
                    chan.close()
                except Exception as exc:  # noqa: BLE001 - 关不掉也不能盖掉事件的收尾
                    logger.warning('SFTP search: failed to close the grep channel: %s',
                                   exc)

    def _grep_item(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        """grep 只给 ``path:line:content``，SSE 的 match 形状还要 size/mtime 与文件头三段。

        补法是：按路径 stat + 读一次文件头（``scanners.parse_head``，与 client 档同一个
        解析器），同一路径只补一次。补不到只丢这几列，命中本身是真的，照样发出去。
        """
        path = hit['path']
        meta = self._meta_for(path)
        return {'path': path, 'name': posixpath.basename(path),
                'size': meta['size'], 'mtime': meta['mtime'],
                'line': hit['line'], 'snippet': hit['snippet'],
                'test_file': meta['test_file'], 'start_time': meta['start_time'],
                'pts_modify_time': meta['pts_modify_time']}

    def _meta_for(self, path: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {'size': 0, 'mtime': 0, 'test_file': '',
                                'start_time': '', 'pts_modify_time': ''}
        if path in self._meta_cache:
            return self._meta_cache[path]
        self._scanned += 1                    # grep 档的 scanned = 出过命中的文件数
        try:
            item = self.session.borrow()
        except Exception as exc:  # noqa: BLE001 - 借不到就只缺这几列，命中本身照发
            logger.warning('SFTP search grep: no connection to fetch metadata of %s (%s)',
                           path, exc)
            return meta
        try:
            with channel_timeout(item[1], READ_TIMEOUT_SEC):
                attr = item[1].stat(path)
                meta['size'] = int(getattr(attr, 'st_size', 0) or 0)
                meta['mtime'] = int(getattr(attr, 'st_mtime', 0) or 0)
                head = self._head_of(item[1], path)
                meta.update(zip(('test_file', 'start_time', 'pts_modify_time'),
                                scanners.parse_head(head)))
        except CONNECTION_ERRORS as exc:
            self.session.give_back(item, broken=True)
            item = None
            logger.warning('SFTP search grep: metadata of %s hit a broken connection (%s)',
                           path, exc)
        except Exception as exc:  # noqa: BLE001 - stat 失败（文件被并发改名等）只丢元数据
            logger.warning('SFTP search grep: cannot fetch metadata of %s (%s)', path, exc)
        finally:
            if item is not None:
                self.session.give_back(item)
        if len(self._meta_cache) < _META_CACHE_MAX:
            self._meta_cache[path] = meta
        return meta

    @staticmethod
    def _head_of(sftp, path: str) -> bytes:
        """读文件头：只为了 ``TestFile`` / ``StartTime`` 那三列，读不到就空着。"""
        try:
            with sftp.open(path, 'rb') as remote:
                return remote.read(scanners.HEAD_SIZE)
        except Exception as exc:  # noqa: BLE001 - 头部读不到只丢表头三列，命中本身照发
            logger.warning('SFTP search grep: cannot read the head of %s (%s)', path, exc)
            return b''

    # ------------------------------------------------------------------ 收尾

    def _progress(self, stage: str, done: int, total: Optional[int]) -> Dict[str, Any]:
        return {'kind': 'progress', 'stage': stage, 'done': done, 'total': total,
                'elapsed_s': round(self.now() - self._started, 3),
                'files_scanned': self._scanned, 'bytes_scanned': self._bytes_scanned}

    def _finish(self, matched: int, files_scanned: int) -> List[Dict[str, Any]]:
        """收口事件：``stage:'done'`` + ``done``。

        ``self._finished`` 是「正常跑完」的标记，:meth:`close` 据此区分「用户取消」与
        「自己收尾」——达到 max_matches 而主动停剩余文件不该被记成取消。
        """
        self._finished = True
        out: List[Dict[str, Any]] = []
        if self.timed_out and 'timeout' not in self._limits:
            out.append(self._limit('timeout'))
        out.append(self._stage('done', self._candidates_emitted, matched))
        out.append({'kind': 'done', 'matched': matched, 'scanned': files_scanned,
                    'elapsed_s': round(self.now() - self._started, 3),
                    # ``truncated`` 说的是「结果集不完整」，不是「本次有过告知」：
                    # workers_reduced / grep_fallback / grep_unavailable 只改快慢，
                    # 把它们算进来会把一次完整搜索报成 partial（黄条说谎）。
                    # 判据与 notice.incomplete 同源，都在 events.INCOMPLETE_CODES。
                    'truncated': any(c in INCOMPLETE_CODES for c in self._limits),
                    'limits_hit': list(self._limits),
                    'engine': self.engine_used, 'cancelled': self.cancelled,
                    'timed_out': self.timed_out})
        return out

    def _limit(self, code: str, message: Optional[str] = None) -> Dict[str, Any]:
        """一条要进 ``done.limits_hit`` 的告知：上限从不静默（spec §3.8）。"""
        if code not in self._limits:
            self._limits.append(code)
        return notice(code, message)

    def _stopped(self) -> bool:
        """取消/超时的唯一判定处（worker 侧只读 ``cancel_event``，不看这里）。"""
        if self.cancel_event.is_set():
            if not self._own_stop:
                self.cancelled = True
            return True
        if self.deadline is not None and self.now() >= self.deadline:
            self.timed_out = True
            return True
        return False

    def _stop_workers(self) -> None:
        """结果够了也要停剩下的扫描。标成「自己停的」，``cancelled`` 只记用户那次。"""
        self._own_stop = True
        self.cancel_event.set()

    def close(self) -> None:
        """取消三件事，顺序与形式都不能换（spec §3.9 第 2 条）：

        1. ``cancel_event.set()`` —— worker 只认它，收不到 ``GeneratorExit``；
        2. ``shutdown(wait=False, cancel_futures=True)`` —— 排队中的文件直接作废，
           **不 join**，否则请求挂住；
        3. 关掉全部临时连接 —— 连接一关，卡在 ``read()`` 上的 worker 立刻拿到异常返回，
           所以最坏 15s（``READ_TIMEOUT_SEC``）是上界而不是典型值。

        幂等：``events()`` 的 finally 与外部 ``runner.close()`` 都会调它，第二次直接返回。
        """
        if self.closed:
            return
        self.closed = True
        self.cancel_event.set()
        executor, self.executor = self.executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        try:
            self.session.close_all()
        except Exception as exc:  # noqa: BLE001 - 收尾失败也不该盖掉已经发出去的事件
            logger.warning('SFTP search: failed to close the search session %s: %s',
                           self.session, exc)
        if not self._finished:
            self.cancelled = True
