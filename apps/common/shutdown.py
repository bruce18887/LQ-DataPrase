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
Done, in this order: close the job executor's two pools (their in-flight jobs are
reaped into terminal DB rows first, which is why this runs *before* the connection
close; then each pool's management thread gets a bounded head start, which is what
actually reaps the worker processes — see ``_pool_manager_threads``); close every
database connection (SQLite checkpoints its WAL and releases the file lock on
close); flush logs and stdout (Electron pipes them to ``userData/logs``); then
exit 0.

**Not** done: waiting for in-flight work. A batch chart export can run for
minutes; blocking quit on it would hang the user's app, and SQLite is
crash-safe by design — an interrupted write rolls back on next open. The 150 ms
delay before exit exists only so the HTTP response can be flushed. The same
reason keeps the pools on ``wait=False``: queued work is cancelled and its row
landed as ``error`` by the reap, because nobody is left to write it back —
``_exit_now`` calls ``os._exit`` a moment later.

The pool step, measured rather than assumed
-------------------------------------------
Three-arm measurement on 2026-10-29 (WSL2 Ubuntu, CPython 3.12.3; the app itself runs
3.13.12 on Windows — the two differ in quoted line numbers, not in shape; n=10 per
arm): a 4-worker ``spawn`` pool with children **idle** on the call queue survived 10/10
runs with no pool step, survived **8 of 10** with a bare ``shutdown(wait=False,
cancel_futures=True)`` followed immediately by ``os._exit(0)`` (the shape this file
shipped until the review), and reaped 10/10 with capture-before-shutdown plus
``join(0.5)`` — the shape it ships now. So the bare arm is not "never works", it is
"works when the scheduler happens to run the management thread before ``os._exit``",
which is nothing an exit path may rely on: that is why the join is not decoration, and
why the capture must precede the call (``shutdown()`` nulls the thread reference;
``_pool_manager_threads`` carries the per-version source citations). Children
**inside** a work item survive every arm, 10/10 — the thread defers sentinel-pushing
while work items are outstanding, so the bounded join logs a WARNING instead of
blocking, and that line is the operator-facing half of the residual. Full per-arm
numbers, the version-split source citations, the reap's transaction boundary, and the
harness-rebuild recipe (the probe script itself was a gitignored throwaway — this doc
is the record) live in
``docs/reference/c3-exit-pool-orphan-forensics-2026-10-29.md``.

The worst case an operator will actually hit is a locked database. The reap
writes, and every SQLite connection here carries ``PRAGMA busy_timeout=30000``
(``apps/common/db_pragmas.py:14``), so the pool step may sit up to 30 s waiting
for the write lock while ``electron/backend.ts:486`` force-kills at 5 s — that
quit then ends mid-cleanup: no WAL checkpoint (SQLite replays it at the next
open), and the children this step would have reaped are left behind. Chosen over
shortening the timeout, because with a short one a busy library makes the reap
*fail* instead of wait, and a job row parked at ``running`` forever is the worse
failure (that is C1's whole point). Nothing here bounds that DB wait; the joins
are bounded, so the lock is the only unbounded step left on the exit path. To
read it as an operator: ``userData/logs`` carries the ``Shutting down (…)`` INFO
line as the start stamp, and a last log line ~5 s after it means the force-kill
won that quit — the join-timeout WARNING above is the marker for the child
residual.

That explicit pool shutdown replaces a claim the 2026-10-28 review could not
support: that Windows orphans were "terminated with the parent's job object".
Re-verified 2026-10-30 with ``grep -rn --include=*.py --include=*.ts "Job[O]bject"
apps config standalone.py test electron`` → zero hits. The 2026-10-29 version of
this line recorded the same grep **without** ``electron`` — an 11-``.ts``-file tree
that is exactly where such a claim would live, which made ``--include=*.ts`` inert
and the evidence line narrower than the conclusion; the reviewer checked ``electron/``
by hand and the conclusion held, so this is the command that now matches it (run it
again before trusting either). Four parts of that command carry
weight: the bracket stops this line from becoming its own evidence, ``--include``
stops a stale ``__pycache__/*.pyc`` from doing the same, ``electron`` is what makes
the ``.ts`` include real, and ``docs/`` is left out
on purpose because a *plan* to add a job object
(``docs/superpowers/plans/2026-10-21-backend-memory-governance.md``) is not a
safety net. The net has no in-repo basis on either platform, so both need the
step above.

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

# How long to wait for each job pool's management thread after asking the pool to
# shut down. Bounded on purpose: that thread pushes the worker sentinels and then
# blocks in ``p.join()`` on every child (CPython 3.13.12
# ``concurrent/futures/process.py:556`` then ``:565-568``), so an unbounded join
# would let a still-running export decide when we are allowed to exit — while
# ``electron/backend.ts:486`` force-kills us at 5 s anyway. Measured budget:
# ``_EXIT_DELAY_SECONDS`` + one join per pool, still well inside that window
# (per-arm numbers and sample size: the forensics doc pointed to by the module
# docstring; the in-repo bound pin is test_shutdown_closes_pools.py).
_POOL_MANAGER_JOIN_SECONDS = 0.5

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


def _pool_manager_threads(jobs_executor):
    """Grab the job pools' management threads *now* — before anything shuts a pool down.

    Why the capture has to happen here and earlier than the shutdown call: the
    ``None`` sentinels that make a worker process leave its ``call_queue.get()`` loop
    and exit are pushed by that thread (CPython 3.13.12 ``process.py:535-547``,
    reached from ``_join_executor_internals`` at ``:556``; on the 3.12.3 review
    interpreter the same code sits at ``:560-572`` reached at ``:581`` — the
    per-version split, and why line numbers may not be reused across versions,
    are recorded in ``docs/reference/c3-exit-pool-orphan-forensics-2026-10-29.md``),
    while ``ProcessPoolExecutor.shutdown(wait=False)`` itself only sets flags and
    wakes it (``:842-848``) and then **nulls the reference to the thread** (``:854``).
    Read it after the call and it is always ``None``, nothing gets joined, and the
    children are still orphaned — which is what a bare ``shutdown(wait=False)``
    measured (arm (b) in the forensics doc).

    Reaching past the module's own API into ``_pool``/``_download_pool`` stays here
    rather than in ``executor.shutdown_pools_for_exit()`` because the *join policy*
    belongs to the exit path: the executor function is tested standalone (no thread
    semantics there), and splitting capture (executor) from join (shutdown) would
    spread one step across two owners. The earlier rationale "executor is at the
    600-line cap" went away with the 2026-10-30 monitor split — recorded here so
    the sentence does not fossilize into a second, false provenance.

    A ``ThreadPoolExecutor`` (the download lane) has no such attribute at all
    (pinned on both interpreters by ``test/backend/test_shutdown_closes_pools.py::
    ManagerThreadAttributePinTests``), so in production this returns the process
    pool's thread or nothing at all. If CPython ever *renames* that private
    attribute, the silent shape is "4 orphans, zero log lines" — a fix that
    quietly stops being a fix — so the process lane missing it gets one WARNING
    (pinned by ``PoolRenameAlarmTests``, both directions: shout when the process
    pool is there without the thread, stay quiet when only the download lane is).
    """
    threads = []
    for attr in ('_pool', '_download_pool'):
        pool = getattr(jobs_executor, attr, None)
        if pool is None:
            continue
        thread = getattr(pool, '_executor_manager_thread', None)
        if thread is None:
            if attr == '_pool':
                logger.warning('Shutdown: the process pool exposes no '
                               '`_executor_manager_thread`; there is nothing to join — '
                               'if CPython renamed it, worker processes are left '
                               'orphaned silently')
            continue
        threads.append(thread)
    return threads


def _close_pools_and_join_managers(jobs_executor, manager_threads):
    """Close the pools, then give their management thread a bounded head start."""
    try:
        jobs_executor.shutdown_pools_for_exit()
    except Exception as exc:  # noqa: BLE001 — cleanup must not raise
        logger.warning('Shutdown: closing job pools failed: %r', exc)
    # Still joined after a failed close: `shutdown_pools_for_exit` guards each pool
    # itself, so getting here means the flags were at least partly set, and a bounded
    # join is the only thing that can still turn into reaped children.
    for thread in manager_threads:
        try:
            thread.join(_POOL_MANAGER_JOIN_SECONDS)
        except Exception as exc:  # noqa: BLE001 — cleanup must not raise
            logger.warning('Shutdown: waiting for pool manager thread failed: %r', exc)
            continue
        if thread.is_alive():
            # The operator-facing half of the residual: this line is the only place
            # a quit that left a child behind becomes visible in userData/logs.
            logger.warning('Shutdown: pool manager thread still running after %.2fs; '
                           'a worker inside a work item was not stopped',
                           _POOL_MANAGER_JOIN_SECONDS)


def _close_job_pools():
    """Best-effort: hand the job executor's two pools their shutdown.

    Ordering is load-bearing, not style: ``shutdown_pools_for_exit()`` first *reaps*
    the in-flight jobs into terminal DB rows (``_write_back`` deliberately returns early
    on a cancelled future, so whoever cancels must write — same invariant as the
    broken-pool path), and that write needs a live connection. Hence this runs before
    ``_close_database_connections()``. Closing a pool is not enough on its own — see
    ``_pool_manager_threads`` for the join that actually reaps the children.

    The import is deliberately function-level: ``apps.common`` must not gain a
    top-level dependency on ``apps.jobs`` (that module imports models, so a module-level
    import would raise ``AppRegistryNotReady`` in anything importing this file during
    app loading; pinned at runtime by
    ``test/backend/test_exit_pool_shutdown.py::ExecutorNotImportedAtRuntimeTests``).
    An executor that cannot be imported skips the step silently —
    "could not import" is not "failed to exit", and the exit code must not change.
    ``import x.y as z`` (not ``from x import y``) is what keeps that true: the latter
    would hand back the already-cached submodule instead of raising.
    """
    try:
        import apps.jobs.executor as jobs_executor
    except Exception as exc:  # noqa: BLE001 — absent jobs app is not a failed exit
        logger.debug('Shutdown: jobs executor unavailable, pools left alone: %r', exc)
        return
    try:
        manager_threads = _pool_manager_threads(jobs_executor)
    except Exception as exc:  # noqa: BLE001 — a capture failure must not skip the close
        logger.warning('Shutdown: could not capture pool manager threads: %r', exc)
        manager_threads = []
    _close_pools_and_join_managers(jobs_executor, manager_threads)


def _cleanup(reason: str) -> None:
    """Run the cleanup steps exactly once."""
    global _shutdown_started
    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    logger.info('Shutting down (%s)', reason)
    _close_job_pools()                # before the DB close — its reap writes rows
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
