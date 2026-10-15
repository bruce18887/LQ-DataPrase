"""Graceful shutdown — Python side.

The problem this solves (2026-10-15, architecture review P0-3)
--------------------------------------------------------------
``electron/backend.ts`` already implements the *host* half: ``stopBackend()``
sends SIGTERM, waits 5 s, then force-kills (``taskkill /F`` on Windows). But the
**backend half did not exist** — the Django process had no signal handler and no
shutdown path at all, so on exit it never closed its database connection.

Worse, on Windows (the primary delivery target) that SIGTERM never arrives as a
signal anyway: Node's ``child.kill('SIGTERM')`` is implemented with
``TerminateProcess``, which does **not** run any Python-level handler. So for the
packaged app the 5 s "graceful" window was purely decorative.

Hence two paths, because one is not enough:

``POST /api/v1/system/shutdown/``
    The only reliable path on Windows. Electron generates a random per-launch
    token, passes it as ``LQDP_SHUTDOWN_TOKEN``, and posts it before quitting.
    Requires the token *and* a loopback source address. Not mounted in effect
    unless the token is configured (the view 404s otherwise).

``SIGTERM`` / ``SIGINT``
    Covers POSIX development, the server profile, and Ctrl+C.

What cleanup actually does — and deliberately does not
------------------------------------------------------
Done: close every database connection (SQLite checkpoints its WAL and releases
the file lock on close), flush logs and stdout (Electron pipes them to
``userData/logs``), then exit 0.

**Not** done: waiting for in-flight work. A batch chart export can run for
minutes; blocking quit on it would hang the user's app, and SQLite is
crash-safe by design — an interrupted write rolls back on next open. The 150 ms
delay before exit exists only so the HTTP response can be flushed. Orphaned
``ProcessPoolExecutor`` children are not explicitly reaped either; on Windows
they are terminated with the parent's job object.

There is also no cancellation of running SFTP searches: executors live on the
runner instances (``apps/sftp/search/runner.py``) with no process-wide registry,
and each run already tears its own down via
``shutdown(wait=False, cancel_futures=True)``. Adding a registry just for this
would be more moving parts than the problem justifies — if that changes, it
belongs in a spec, not here.
"""

import atexit
import logging
import os
import secrets
import signal
import sys
import threading
import time

from django.conf import settings
from django.db import connections
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

# How long to let the HTTP response flush before the process disappears. Not a
# drain window — see the module docstring.
_EXIT_DELAY_SECONDS = 0.15

# Guard against re-entry: a signal arriving while cleanup is already running, or
# the endpoint being hit twice, must not run the steps twice.
_shutdown_lock = threading.Lock()
_shutdown_started = False

# Loopback sources. IPv4-mapped IPv6 (``::ffff:127.0.0.1``) shows up when a
# dual-stack listener accepts an IPv4 client, which is exactly what happens on
# Windows when Electron connects to ``127.0.0.1`` on a ``::`` socket.
_LOOPBACK_ADDRESSES = frozenset({'127.0.0.1', '::1', '::ffff:127.0.0.1'})

SHUTDOWN_TOKEN_HEADER = 'X-LQDP-Shutdown-Token'


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def _close_database_connections():
    """Close every connection. For SQLite this checkpoints the WAL and drops
    the file lock, so the next start does not have to recover it."""
    for alias in connections:
        try:
            connections[alias].close()
        except Exception as exc:  # noqa: BLE001 — cleanup must not raise
            logger.warning('Shutdown: closing connection %r failed: %r', alias, exc)


def _flush_output():
    try:
        logging.shutdown()
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass


def _cleanup(reason: str) -> None:
    """Run the cleanup steps exactly once."""
    global _shutdown_started
    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    logger.info('Shutting down (%s)', reason)
    _close_database_connections()
    _flush_output()


def _exit_now(reason: str) -> None:
    """``os._exit`` rather than ``sys.exit``/``SystemExit``: the HTTP-triggered
    path runs in a request thread, where raising ``SystemExit`` would only end
    that thread and leave the server serving. Explicit cleanup first, then a
    hard exit, is deterministic regardless of which thread we are on."""
    _cleanup(reason)
    os._exit(0)


# ---------------------------------------------------------------------------
# Signal path (POSIX dev, server profile, Ctrl+C)
# ---------------------------------------------------------------------------
def _signal_handler(signum, _frame):
    name = signal.Signals(signum).name if signum in {s.value for s in signal.Signals} else str(signum)
    _exit_now(f'signal {name}')


def install_signal_handlers():
    """Register SIGTERM/SIGINT handlers. Idempotent.

    Note this *replaces* Python's default SIGINT behaviour, so Ctrl+C now goes
    through our cleanup instead of raising ``KeyboardInterrupt``. That is the
    intent: previously Ctrl+C skipped the DB close entirely.
    """
    for signame in ('SIGTERM', 'SIGINT'):
        sig = getattr(signal, signame, None)
        if sig is None:  # not defined on this platform
            continue
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError) as exc:
            # ValueError: not in the main thread. Non-fatal — the HTTP path
            # still works, and the process is not the one that needs it.
            logger.warning('Could not install %s handler: %r', signame, exc)

    # Last-resort net for exits that bypass the handlers (e.g. an unhandled
    # exception unwinding main). Idempotent via _cleanup's guard.
    atexit.register(_cleanup, 'interpreter exit')


# ---------------------------------------------------------------------------
# HTTP path (the only reliable one on Windows)
# ---------------------------------------------------------------------------
def request_shutdown(reason: str, delay: float = _EXIT_DELAY_SECONDS) -> None:
    """Schedule cleanup + exit from a daemon thread.

    Backgrounded so the calling request can return and its response body reach
    the client before the socket dies. Electron treats a 200 here as "the
    backend is stopping on purpose" and can shorten its force-kill wait.
    """
    def _run():
        time.sleep(delay)
        _exit_now(reason)

    threading.Thread(target=_run, name='lqdp-shutdown', daemon=True).start()


def _is_loopback(request) -> bool:
    return request.META.get('REMOTE_ADDR') in _LOOPBACK_ADDRESSES


class ShutdownView(APIView):
    """``POST /api/v1/system/shutdown/`` — stop the backend on purpose.

    Two independent gates, because this endpoint terminates the process:

    1. **Loopback source only.** A LAN client on the server profile must never
       be able to stop the service.
    2. **A per-launch random token** (``LQDP_SHUTDOWN_TOKEN``), compared in
       constant time. The token is generated fresh by Electron on every start
       and never persisted, so it is not a durable credential.

    With no token configured the view returns 404 — indistinguishable from the
    route not existing, which is the right posture for a dev/server install
    where nothing needs to stop the backend programmatically.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes: list = []

    def post(self, request):
        expected = getattr(settings, 'SHUTDOWN_TOKEN', None)
        if not expected:
            raise Http404('shutdown endpoint not enabled')

        if not _is_loopback(request):
            logger.warning(
                'Shutdown refused: non-loopback source %s', request.META.get('REMOTE_ADDR'),
            )
            raise PermissionDenied('shutdown is loopback-only')

        supplied = request.headers.get(SHUTDOWN_TOKEN_HEADER, '')
        if not secrets.compare_digest(str(supplied), str(expected)):
            logger.warning('Shutdown refused: bad or missing token')
            raise PermissionDenied('invalid shutdown token')

        request_shutdown('api request')
        return Response({'status': 'shutting_down'}, status=status.HTTP_200_OK)
