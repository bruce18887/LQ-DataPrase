"""搜索专用临时连接池 ``SearchSession``（spec §3.7）。

为什么搜索不能复用 ``apps.sftp.pool`` 那条连接
------------------------------------------
池是「一人一条 paramiko 连接」，搜索要并行，共用一条会出两件事：

1. **paramiko 的 ``SFTPClient`` 不是线程安全的**。两个线程在同一 channel 上收发会
   把 SFTP 协议流写乱，之后的包全部错位 —— 典型症状就是
   ``SFTPError: Garbage packet received``。
2. **``channel_timeout`` 改的是共享 channel 的 socket 超时**。扫描要给每个文件设
   ``READ_TIMEOUT_SEC``，若设在池连接上，浏览与下载会跟着继承这个超时（或被恢复成
   别的值），污染与本次搜索无关的请求。

所以搜索自己开 N 条独立连接、用完一律关掉（``finally: close_all()``）。
两条推论：搜索期间面包屑导航照常可用（走池连接，不同 channel）；互斥只需挡
「搜索 vs 下载」。

主机密钥：每条连接都经 ``host_keys.open_verified_transport()``（TOFU 契约，
``test/backend/test_sftp_host_keys.py`` 钉着）。参考工具的 ``AutoAddPolicy``
**不许移植**；``HostKeyMismatchError`` 不降级、不吞，直接上抛。
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional, Tuple

import paramiko

from apps.sftp import cache, host_keys

logger = logging.getLogger(__name__)

ConnItem = Tuple[paramiko.Transport, paramiko.SFTPClient]

# 扫描侧判定「这条连接脏了、要换一条」的错误集（walker/scanners 用 isinstance 判定）。
CONNECTION_ERRORS = (paramiko.SSHException, paramiko.SFTPError, EOFError, OSError)

# exec_transport 借 transport 给服务端 grep 用，只需一次 round-trip，30s 足够。
EXEC_TIMEOUT_SEC = 30


class SearchSessionError(Exception):
    """搜索连接不可用：未登录、一条都开不出来、或会话已关闭/借出超时。"""


class SearchSession:
    """N 条仅供一次搜索使用的临时连接，队列式借还。

    ``open_all()`` 返回**实际**开出来的条数（服务端可能拒绝多余会话），engine 据此
    上报 ``workers_reduced``，绝不用用户请求的数字充数。
    """

    def __init__(self, user_id: int, workers: int):
        self.user_id = user_id
        self.requested = max(1, int(workers))
        self.opened = 0
        self.closed = 0
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.RLock()
        self._opened_all = False
        self._closed = False

    @property
    def size(self) -> int:
        """当前活着的连接数（含借出在外的）。"""
        return self.opened - self.closed

    # —— 建立 ——

    def _credentials(self) -> dict:
        try:
            creds = cache.get_session(self.user_id)
        except Exception as exc:                     # noqa: BLE001 - 缓存后端自身故障
            logger.warning('SFTP search: session cache read failed for user %s',
                           self.user_id, exc_info=True)
            raise SearchSessionError(
                f'no cached session (not connected) for user {self.user_id}: '
                f'session cache failed: {exc}') from exc
        if not creds:
            raise SearchSessionError(
                f'no cached session (not connected) for user {self.user_id}')
        return creds

    def _open_one(self, creds: Optional[dict] = None) -> ConnItem:
        creds = creds or self._credentials()
        transport = host_keys.open_verified_transport(
            creds['host'], creds['port'], creds['username'], creds['password'])
        sftp = paramiko.SFTPClient.from_transport(transport)
        if sftp is None:                             # transport 握手后立刻死了
            transport.close()
            raise SearchSessionError(
                f'SFTPClient.from_transport returned None for user {self.user_id}')
        return (transport, sftp)

    def open_all(self) -> int:
        """开 ``requested`` 条，返回**实际**开出来的条数。幂等。"""
        with self._lock:
            if self._opened_all:
                return self.opened
            self._opened_all = True
            creds = self._credentials()              # 「未连接」就地失败
            mismatch = None
            for _ in range(self.requested):
                try:
                    item = self._open_one(creds)
                except host_keys.HostKeyMismatchError as exc:
                    mismatch = exc                   # 安全边界：不降级，收尾后原样上抛
                    break
                except CONNECTION_ERRORS as exc:
                    logger.warning(
                        'SFTP search: server refused extra connection for user %s '
                        '(%d/%d opened so far, %s); degrading to %d worker(s)',
                        self.user_id, self.opened, self.requested, exc, self.opened)
                    break
                self._q.put(item)
                self.opened += 1
            if mismatch is not None:
                self.close_all()
                raise mismatch
            if self.opened == 0:
                self.close_all()
                raise SearchSessionError(
                    f'无法建立任何 SFTP 连接（user {self.user_id}）')
            return self.opened

    # —— 借还 ——

    def borrow(self, timeout=None) -> ConnItem:
        """取一条连接；无空闲则阻塞到 ``timeout``（None = 一直等）。

        拿到 ``None`` 哨兵（会话已关闭，或坏连接补不上留下的死位）即抛
        ``SearchSessionError``，绝不返回一个已关闭的连接让调用方去踩。
        """
        try:
            item = self._q.get(timeout=timeout)
        except queue.Empty:
            raise SearchSessionError(
                f'borrow SFTP connection timeout after {timeout}s '
                f'(user {self.user_id})') from None
        if item is None:
            # 放回去：可能还有别的 worker 阻塞在同一个哨兵上，取消时它们都得脱身。
            self._q.put(None)
            raise SearchSessionError(
                f'SFTP search session already closed (user {self.user_id})')
        return item

    def give_back(self, item: ConnItem, *, broken: bool = False) -> None:
        """归还；``broken=True`` 表示协议流可能已经脏了，关掉重开一条。"""
        if broken:
            self._close_one(item)
            with self._lock:
                if self._closed:
                    return
                try:
                    fresh = self._open_one()
                except CONNECTION_ERRORS as exc:
                    logger.warning(
                        'SFTP search: cannot replace broken connection for user %s '
                        '(%s); pool shrinks to %d live connection(s)',
                        self.user_id, exc, self.size)
                    self._q.put(self._closed_flag(item))
                else:
                    self.opened += 1
                    self._q.put(fresh)
            return
        if self._closed:
            self._close_one(item)                    # 取消路径：还回来就别再漏出去
            return
        self._q.put(item)

    def _closed_flag(self, item: ConnItem) -> None:
        """补不上新连接时放回队列的哨兵（值本身不重要，「有个东西可拿」才重要）。"""
        return None

    def exec_transport(self) -> paramiko.Transport:
        """借一条连接的 transport 给服务端 grep 用（只要 ``open_session``）。

        **立刻放回队列**再返回它：exec 可能跑几十秒，占着整条连接会饿死 worker，
        而 grep 根本不用 SFTP channel。
        """
        item = self.borrow(timeout=EXEC_TIMEOUT_SEC)
        self.give_back(item)
        return item[0]

    # —— 关闭 ——

    def _close_one(self, item: ConnItem) -> None:
        try:
            item[1].close()
        except Exception:                            # noqa: BLE001 - 关闭失败也要继续
            logger.warning('SFTP search: failed to close SFTP client for user %s',
                           self.user_id, exc_info=True)
        try:
            item[0].close()
        except Exception:                            # noqa: BLE001
            logger.warning('SFTP search: failed to close transport for user %s',
                           self.user_id, exc_info=True)
        self.closed += 1

    def close_all(self) -> None:
        """关掉所有连接，幂等；塞 ``None`` 哨兵把阻塞中的 ``borrow`` 赶出来。

        engine 的取消路径依赖这条：连接一关，卡在 ``read()`` 上的 worker 拿到异常，
        卡在 ``borrow()`` 上的 worker 拿到 ``SearchSessionError``。
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while True:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    break
                if item is not None:
                    self._close_one(item)
            self._q.put(None)

    def __enter__(self) -> 'SearchSession':
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close_all()
        return False
