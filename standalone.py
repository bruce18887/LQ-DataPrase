"""Entry point for PyInstaller standalone build.

When frozen (packaged by PyInstaller), this script:

1. Sets ``DJANGO_SETTINGS_MODULE`` to ``config.settings.standalone``
2. Ensures ``media/`` directory exists next to the executable
3. Runs database migrations automatically
4. Creates a default admin user if none exists
5. Collects static files (frontend SPA + Django admin assets)
6. Starts the Django development server

Usage:
    LQ-DataPrase.exe                     # default port 8000
    LQ-DataPrase.exe --port 9000         # custom port
    LQ-DataPrase.exe --ready-fd 3        # write 'ready\\n' to fd 3 when server is up

Electron integration:
    When ``--ready-fd`` is provided, the script writes a JSON line to stdout
    after the server starts listening:  {"event":"ready","port":<port>}
    This allows the Electron host process to detect when the backend is ready.
"""

import argparse
import os
import sys
from pathlib import Path


def _setup_path():
    """Ensure the frozen bundle's root is on sys.path.

    PyInstaller extracts the collected packages into ``sys._MEIPASS``
    (the ``_internal/`` directory next to the exe).  Both the ``apps``
    and ``config`` packages live there, so we prepend it to ``sys.path``.
    """
    if getattr(sys, 'frozen', False):
        meipass = sys._MEIPASS
        if meipass not in sys.path:
            sys.path.insert(0, meipass)


def _setup_django():
    """Configure Django settings and run bootstrap."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.standalone')

    import django
    django.setup()


def _bootstrap():
    """Run migrations, create superuser, collect static files."""
    from django.conf import settings
    from django.core.management import call_command

    base = settings.BASE_DIR

    # Ensure media and staticfiles directories exist
    media = settings.MEDIA_ROOT
    os.makedirs(media, exist_ok=True)
    os.makedirs(settings.STATIC_ROOT, exist_ok=True)

    # Run migrations
    print('[bootstrap] Running database migrations...', flush=True)
    call_command('migrate', '--run-syncdb', verbosity=0)

    # Create default admin user if no superuser exists
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if not User.objects.filter(is_superuser=True).exists():
        print('[bootstrap] Creating default admin user (admin / admin123)...', flush=True)
        User.objects.create_superuser(
            username='admin',
            password='admin123',
            email='admin@localhost',
        )
        print('[bootstrap] IMPORTANT: Change the default password after first login!', flush=True)

    # Collect static files (only when the frontend dist is present)
    # In the standalone build we use WhiteNoise's finders to serve static files
    # directly from each app's static/ directory and from STATICFILES_DIRS. This
    # avoids a lengthy ``collectstatic`` pass on first run, which was the main
    # cause of the "cannot connect to server" startup timeout.
    if getattr(settings, 'WHITENOISE_USE_FINDERS', False):
        print('[bootstrap] Serving static files via WhiteNoise finders, skipping collectstatic.', flush=True)
    else:
        static_root = settings.STATIC_ROOT
        # In frozen builds, frontend_dist lives in sys._MEIPASS, not BASE_DIR.
        if getattr(sys, 'frozen', False):
            frontend_dist = Path(sys._MEIPASS) / 'frontend_dist'
        else:
            frontend_dist = base / 'frontend_dist'
        if frontend_dist.is_dir():
            # Skip collectstatic if the output directory already exists and is
            # non-empty. The frontend assets bundled with PyInstaller never change
            # at runtime, so re-collecting on every start only wastes time.
            static_root_path = Path(static_root)
            if static_root_path.is_dir() and any(static_root_path.iterdir()):
                print('[bootstrap] Static files already collected, skipping collectstatic.', flush=True)
            else:
                print('[bootstrap] Collecting static files...', flush=True)
                import time as _time
                _cs_start = _time.time()
                call_command('collectstatic', '--noinput', verbosity=0)
                print(f'[bootstrap] collectstatic finished in {_time.time() - _cs_start:.2f}s', flush=True)

    print(f'[bootstrap] Database : {settings.DATABASES["default"]["NAME"]}', flush=True)
    print(f'[bootstrap] Media dir: {media}', flush=True)
    print(f'[bootstrap] Static   : {settings.STATIC_ROOT}', flush=True)


def main():
    parser = argparse.ArgumentParser(description='LQ-DataPrase Standalone Server')
    parser.add_argument('--port', type=int, default=8000, help='Port to listen on (default: 8000)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind (default: 0.0.0.0)')
    parser.add_argument('--ready-fd', type=int, default=None,
                        help='File descriptor to write "ready\\n" when server is up (Electron integration)')
    args = parser.parse_args()

    # Allow Electron to override the base directory (points to userData)
    lqdp_base = os.environ.get('LQDP_BASE_DIR')
    if lqdp_base:
        os.environ.setdefault('LQDP_OVERRIDE_BASE_DIR', lqdp_base)

    _setup_path()
    _setup_django()
    _bootstrap()

    # When --port 0 is given (used by the Electron main process to auto-assign
    # a free port), resolve a real port via the OS before starting runserver.
    # Django's runserver does bind to a real port when given 0, but our startup
    # banner would still show port 0 — breaking the Electron parent's regex
    # that parses this line to discover where the backend is listening.
    if args.port == 0:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            args.port = s.getsockname()[1]

    from django.core.management import call_command

    port = args.port
    # If port is 0, find a free port
    if port == 0:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((args.host, 0))
        port = sock.getsockname()[1]
        sock.close()

    print(f'\n[server] Starting LQ-DataPrase on http://{args.host}:{port}', flush=True)
    print('[server] Press Ctrl+C to stop.\n', flush=True)

    # Signal readiness to Electron via ready-fd
    if args.ready_fd is not None:
        import json
        ready_msg = json.dumps({'event': 'ready', 'port': port, 'pid': os.getpid()})
        try:
            with open(args.ready_fd, 'w', encoding='utf-8') as f:
                f.write(f'{ready_msg}\n')
                f.flush()
            print(f'[server] Ready signal written to fd {args.ready_fd}', flush=True)
        except OSError as e:
            print(f'[server] Warning: could not write ready-fd {args.ready_fd}: {e}', flush=True)

    call_command('runserver', f'{args.host}:{port}', '--noreload')


if __name__ == '__main__':
    main()
