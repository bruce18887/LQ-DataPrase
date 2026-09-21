"""Per-process SFTP connection pool — eliminates the per-click SSH handshake.

Why this module exists
----------------------
``apps.sftp.views.SftpViewSet`` previously opened a brand-new
``paramiko.Transport`` (full SSH handshake: TCP + protocol negotiation +
auth, ~300-500ms of round-trips) on *every* request and closed it immediately
afterwards. Credentials were cached (``apps.sftp.cache``) but the connection
itself was not reused, so every directory click paid the handshake cost again.

This module keeps the connection established at login *alive* inside each
worker process, keyed by ``user_id``. Subsequent clicks reuse it and only pay
for the ``listdir`` round-trip.

Concurrency model
-----------------
A per-user ``threading.RLock`` serialises this module's *state transitions*:
the liveness check, the rebuild, and the pop/close in ``invalidate``/``close``.

The original "lock-free by design" note rested on gunicorn sync workers, but the
shipping desktop app runs ``manage.py runserver`` (standalone.py:224), which is
threaded by default in Django 6 (--nothreading is store_false). Concurrent
same-user requests therefore really do reach here from different threads.

What the lock does NOT cover: it guards the pool dict and the transport/sftp
lifecycle, not paramiko's ``SFTPClient`` *operations*. Two threads running
``listdir``/``open`` on the same client would still desync the protocol stream.
That stays kept away by one-connection-per-user + the frontend transfer mutex +
searches using their own ephemeral connections (``search/connect.py``).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional

import paramiko
from django.conf import settings

from .cache import get_session, SftpSessionCacheError
from . import host_keys

logger = logging.getLogger(__name__)

DEFAULT_IDLE_TTL_SECONDS = 300  # Recycle connections idle longer than this.


class SftpPoolError(Exception):
    """Raised when a live connection cannot be obtained or rebuilt."""


class _Entry:
    __slots__ = ('transport', 'sftp', 'last_used')

    def __init__(self, transport, sftp, last_used):
        self.transport = transport
        self.sftp = sftp
        self.last_used = last_used


_pool: Dict[object, _Entry] = {}

# threaded runserver（桌面版实际形态）下同 user 会并发进来，_pool 的状态转换必须串行。
# 锁按 user_id 分：否则一个用户的慢握手会挡住所有用户。
_locks: Dict[object, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(user_id) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(user_id)
        if lock is None:
            lock = _locks[user_id] = threading.RLock()
        return lock


def _idle_ttl() -> int:
    return int(getattr(settings, 'SFTP_POOL_IDLE_TTL', DEFAULT_IDLE_TTL_SECONDS))


def _close_entry(entry: Optional[_Entry]) -> None:
    if entry is None:
        return
    try:
        entry.sftp.close()
    except Exception:
        logger.warning('Failed to close SFTP client', exc_info=True)
    try:
        entry.transport.close()
    except Exception:
        logger.warning('Failed to close SFTP transport', exc_info=True)


def _build_entry(user_id) -> _Entry:
    """Open a fresh SFTP connection using cached credentials."""
    try:
        data = get_session(user_id)
    except SftpSessionCacheError as exc:
        raise SftpPoolError(f'session cache unavailable: {exc}') from exc
    if not data:
        raise SftpPoolError('no cached session (not connected)')

    try:
        # 主机密钥 TOFU 校验（见 apps/sftp/host_keys.py）：已记录的主机必须
        # 公钥匹配，否则拒绝连接——凭据不会发往可疑主机。
        transport = host_keys.open_verified_transport(
            data['host'], data['port'], data['username'], data['password'])
        sftp = paramiko.SFTPClient.from_transport(transport)
    except host_keys.HostKeyMismatchError as exc:
        raise SftpPoolError(f'SFTP 主机密钥校验失败: {exc}') from exc
    except Exception as exc:
        raise SftpPoolError(f'failed to establish SFTP connection: {exc}') from exc

    return _Entry(transport, sftp, time.time())


def get_connection(user_id) -> paramiko.SFTPClient:
    """Return a live ``SFTPClient`` for ``user_id``, reusing when possible.

    Rebuilds the connection when it is missing, dead (transport inactive), or
    idle beyond ``SFTP_POOL_IDLE_TTL``. Raises ``SftpPoolError`` if no live
    connection can be established (e.g. session expired / handshake failed).
    """
    # 整个函数体（含 _build_entry 握手）都在锁内：只锁字典不锁握手的话，
    # N 个线程会各握一次手，后完成的覆盖先完成的，白丢连接。
    with _lock_for(user_id):
        now = time.time()
        entry = _pool.get(user_id)

        if entry is not None:
            alive = False
            try:
                alive = entry.transport.is_active()
            except Exception:
                logger.warning('SFTP liveness probe failed for user %s; rebuilding',
                               user_id, exc_info=True)
                alive = False
            if alive and (now - entry.last_used) <= _idle_ttl():
                entry.last_used = now
                return entry.sftp
            # Stale or dead: drop and rebuild.
            _close_entry(entry)
            _pool.pop(user_id, None)

        entry = _build_entry(user_id)
        _pool[user_id] = entry
        return entry.sftp


def invalidate(user_id) -> None:
    """Drop and close the user's connection so the next call rebuilds it."""
    with _lock_for(user_id):
        _close_entry(_pool.pop(user_id, None))


def close(user_id) -> None:
    """Close and remove the user's connection (used on explicit disconnect)."""
    with _lock_for(user_id):
        _close_entry(_pool.pop(user_id, None))
