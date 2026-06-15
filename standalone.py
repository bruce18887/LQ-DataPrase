"""Entry point for PyInstaller standalone build.

When frozen (packaged by PyInstaller), this script:

1. Sets ``DJANGO_SETTINGS_MODULE`` to ``config.settings.standalone``
2. Ensures ``media/`` directory exists next to the executable
3. Runs database migrations automatically
4. Creates a default admin user if none exists
5. Collects static files (frontend SPA + Django admin assets)
6. Starts the Django development server on ``0.0.0.0:8000``

Usage:
    LQ-DataPrase.exe              # default port 8000
    LQ-DataPrase.exe --port 9000  # custom port
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
    print('[bootstrap] Running database migrations...')
    call_command('migrate', '--run-syncdb', verbosity=1)

    # Create default admin user if no superuser exists
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if not User.objects.filter(is_superuser=True).exists():
        print('[bootstrap] Creating default admin user (admin / admin123)...')
        User.objects.create_superuser(
            username='admin',
            password='admin123',
            email='admin@localhost',
        )
        print('[bootstrap] IMPORTANT: Change the default password after first login!')

    # Collect static files (only when the frontend dist is present)
    static_root = settings.STATIC_ROOT
    frontend_dist = base / 'frontend_dist'
    if frontend_dist.is_dir():
        print('[bootstrap] Collecting static files...')
        call_command('collectstatic', '--noinput', verbosity=0)

    print(f'[bootstrap] Database : {settings.DATABASES["default"]["NAME"]}')
    print(f'[bootstrap] Media dir: {media}')
    print(f'[bootstrap] Static   : {static_root}')


def main():
    parser = argparse.ArgumentParser(description='LQ-DataPrase Standalone Server')
    parser.add_argument('--port', type=int, default=8000, help='Port to listen on (default: 8000)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind (default: 0.0.0.0)')
    args = parser.parse_args()

    _setup_path()
    _setup_django()
    _bootstrap()

    from django.core.management import call_command

    print(f'\n[server] Starting LQ-DataPrase on http://{args.host}:{args.port}')
    print('[server] Press Ctrl+C to stop.\n')
    call_command('runserver', f'{args.host}:{args.port}', '--noreload')


if __name__ == '__main__':
    main()
