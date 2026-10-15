"""Django project package.

Deliberately empty of side effects. This module used to import
``config.celery`` to expose ``celery_app`` so that ``@shared_task`` would bind
to the project's app — but the repo never defined a single task, and both
shipped profiles (``config.settings.standalone`` and ``config.settings.server``)
already stripped ``celery`` out of ``INSTALLED_APPS``. The import was therefore
pure import-time overhead plus a misleading signal that a broker was part of
the runtime.

Removed 2026-10-15 (architecture review P0-1). The project's asynchronous work
is **in-process**: ``ProcessPoolExecutor`` for export chart rendering and
``ThreadPoolExecutor`` for SFTP search. See ``apps/CLAUDE.md``.
"""
