"""Health and readiness probes.

Why these exist (2026-10-15, architecture review P0-2)
-------------------------------------------------------
The packaged app had no dedicated liveness path. Electron polled ``/api/v1/``
— whose only contract was "any response, even a 404, proves the server is
listening" — and Playwright's ``webServer`` gate polled ``/api/schema/``, which
is routed only when ``API_DOCS_ENABLED`` is true, i.e. **never** in the shipped
desktop or server profiles. Readiness was therefore coupled to an API-docs
switch that exists for a completely different reason.

Two endpoints, deliberately different:

``GET /api/v1/health/``
    **Liveness.** Always 200. No DB, no disk, no auth. Answers exactly one
    question: "is this process serving HTTP?" This is what Electron's startup
    poll and Playwright's ``webServer`` readiness gate should use.

``GET /api/v1/ready/``
    **Readiness.** Checks that the database answers a query, that the data
    directory is writable, and that migrations are applied. 200 when every
    check passes, 503 with a per-check breakdown otherwise.

Both are ``AllowAny`` and explicitly unthrottled on purpose: Electron must be
able to poll before any user has logged in, and a 429 during startup would be
indistinguishable from a dead backend.
"""

from pathlib import Path
import logging

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """Liveness. Intentionally does no work."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes: list = []

    def get(self, request):
        return Response({'status': 'ok'})


class ReadyView(APIView):
    """Readiness — DB reachable, data dir writable, migrations applied."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes: list = []

    def get(self, request):
        checks = {
            'database': self._check_database,
            'data_dir_writable': self._check_data_dir_writable,
            'migrations_applied': self._check_migrations,
        }
        results = {}
        for name, fn in checks.items():
            try:
                ok, detail = fn()
            except Exception as exc:  # noqa: BLE001 — a probe must never 500
                ok, detail = False, f'{type(exc).__name__}: {exc}'
            results[name] = {'ok': ok, 'detail': detail}

        all_ok = all(item['ok'] for item in results.values())
        body = {
            'status': 'ok' if all_ok else 'degraded',
            'checks': results,
        }
        if not settings.DEBUG:
            # Paths and driver messages describe the host's filesystem layout.
            # The status flags are enough for a probe; detail is dev-only.
            for item in body['checks'].values():
                if not item['ok']:
                    item['detail'] = None
        return Response(
            body,
            status=status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # ------------------------------------------------------------------
    # Checks — each returns (ok, detail)
    # ------------------------------------------------------------------
    def _check_database(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return True, connection.vendor

    def _check_data_dir_writable(self):
        """The media root is where uploads and exports land, so it is the
        directory whose writability actually matters at runtime. ``BASE_DIR``
        holds the database file, which SQLite would have already failed on."""
        target = Path(settings.MEDIA_ROOT)
        if not target.is_dir():
            return False, f'not a directory: {target}'

        probe = target / '.lqdp-write-probe'
        try:
            probe.write_text('ok', encoding='utf-8')
        except OSError as exc:
            return False, f'not writable: {exc}'

        # The write above is what proves writability; removing the probe is
        # housekeeping. Swallowed broadly on purpose: this runs inside a
        # readiness probe whose only job is to report, and deleting a file is
        # exactly the kind of operation that something outside our control —
        # an endpoint-protection agent, a sandbox shim, a signal handler — may
        # interrupt by raising something that is *not* an Exception subclass.
        # Letting that turn "the directory is writable" into a 500 would make
        # the probe less trustworthy than having no probe at all. KeyboardInterrupt
        # is re-raised so Ctrl+C still works.
        try:
            probe.unlink()
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # noqa: BLE001
            logger.debug('Write probe %s could not be removed: %r', probe, exc)

        return True, str(target)

    def _check_migrations(self):
        """Compare the migration graph's leaves against what is recorded as
        applied. ``migrate --check`` would do the same thing but as a management
        command, which is far heavier and writes to stdout."""
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            pending = ', '.join(f'{m.app_label}.{m.name}' for m, _ in plan[:5])
            more = '' if len(plan) <= 5 else f' (+{len(plan) - 5} more)'
            return False, f'{len(plan)} pending: {pending}{more}'
        return True, 'up to date'
