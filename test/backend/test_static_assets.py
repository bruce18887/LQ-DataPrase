"""Tests for SPA static-asset serving in standalone/production mode.

Regression coverage for a bug where the SPA catch-all URL pattern
``r'^(?!api/).*$'`` matched ``/assets/<hash>.js`` and returned ``index.html``
(content-type text/html) instead of the actual JS file. The browser then
received HTML where it expected JavaScript, so the Vue app never mounted
and the login page never rendered.

These tests verify that:
  * ``/assets/<file>`` is served with the correct content-type (JS/CSS),
    not as text/html
  * ``/favicon.svg`` and ``/icons.svg`` are served as image/svg+xml
  * ``/login`` (a client-side route) still returns index.html (the SPA shell)
  * ``/api/v1/auth/profile/`` without credentials returns 401 (API still works)

The tests run against the ``standalone`` settings module so that
``TEMPLATES[0]['DIRS']`` points at ``frontend/dist`` and the asset-serving
views can find the files.

Run with:
    .venv\\Scripts\\python.exe manage.py test test.backend.test_static_assets --settings=config.settings.standalone
"""
import os
import unittest
from pathlib import Path

# These tests MUST run under the standalone settings module, which registers
# frontend/dist in TEMPLATES[0]['DIRS']. The default manage.py uses
# development.py, which does not — without that, the asset views 404 and the
# regression would not be detectable.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.standalone')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.test import Client  # noqa: E402


def _frontend_dist() -> Path:
    dirs = settings.TEMPLATES[0].get('DIRS', [])
    return Path(dirs[0]) if dirs else Path()


def _has_frontend_dist() -> bool:
    dist = _frontend_dist()
    return dist.is_dir() and (dist / 'index.html').is_file()


@unittest.skipUnless(_has_frontend_dist(), 'frontend/dist not built — run `npm run build` in frontend/')
class StaticAssetServingTests(unittest.TestCase):
    """Verify SPA static assets are served with correct content-types.

    Previously the SPA catch-all returned index.html (text/html) for every
    non-API path, including /assets/*.js — so the Vue app never mounted.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = Client()
        cls.dist = _frontend_dist()
        cls.assets_dir = cls.dist / 'assets'

    def _find_chunk(self, pattern: str) -> str | None:
        if not self.assets_dir.is_dir():
            return None
        matches = list(self.assets_dir.glob(pattern))
        return matches[0].name if matches else None

    def test_assets_js_served_as_javascript_not_html(self):
        """``/assets/<hash>.js`` must return application/javascript, not text/html."""
        js_file = self._find_chunk('index-*.js')
        self.assertIsNotNone(js_file, 'no index-*.js chunk found in frontend/dist/assets')
        response = self.client.get(f'/assets/{js_file}')
        self.assertEqual(response.status_code, 200, f'Expected 200 for /assets/{js_file}')
        content_type = response.headers.get('Content-Type', '')
        self.assertIn('javascript', content_type,
                      f'Expected javascript content-type, got {content_type!r} '
                      '(this is the regression — the SPA catch-all returned index.html)')
        # FileResponse streams its content; consume the stream to check the size.
        # The JS chunk should be much larger than index.html (~534 bytes).
        body = b''.join(response.streaming_content)
        self.assertGreater(len(body), 1000,
                           f'JS chunk is only {len(body)} bytes — likely index.html, not JS')

    def test_assets_css_served_as_css_not_html(self):
        """``/assets/<hash>.css`` must return text/css, not text/html."""
        css_file = self._find_chunk('index-*.css')
        self.assertIsNotNone(css_file, 'no index-*.css chunk found in frontend/dist/assets')
        response = self.client.get(f'/assets/{css_file}')
        self.assertEqual(response.status_code, 200)
        content_type = response.headers.get('Content-Type', '')
        self.assertIn('css', content_type, f'Expected css content-type, got {content_type!r}')

    def test_favicon_svg_served_as_svg(self):
        """``/favicon.svg`` must return image/svg+xml, not text/html."""
        response = self.client.get('/favicon.svg')
        self.assertEqual(response.status_code, 200)
        content_type = response.headers.get('Content-Type', '')
        self.assertIn('svg', content_type, f'Expected svg content-type for favicon, got {content_type!r}')

    def test_icons_svg_served_as_svg(self):
        """``/icons.svg`` must return image/svg+xml, not text/html."""
        response = self.client.get('/icons.svg')
        self.assertEqual(response.status_code, 200)
        content_type = response.headers.get('Content-Type', '')
        self.assertIn('svg', content_type, f'Expected svg content-type for icons.svg, got {content_type!r}')

    def test_spa_route_returns_index_html(self):
        """Client-side routes like ``/login`` must return the SPA shell (index.html)."""
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<div id="app">', response.content,
                      'Expected index.html with #app div for /login SPA route')

    def test_api_still_requires_auth(self):
        """``/api/v1/auth/profile/`` without credentials must return 401."""
        response = self.client.get('/api/v1/auth/profile/')
        self.assertEqual(response.status_code, 401,
                         f'Expected 401 for unauthenticated profile access, got {response.status_code}')

    def test_nonexistent_asset_returns_404(self):
        """A missing asset must return 404, not index.html."""
        response = self.client.get('/assets/this-file-does-not-exist.js')
        self.assertEqual(response.status_code, 404,
                         f'Expected 404 for missing asset, got {response.status_code}')


if __name__ == '__main__':
    unittest.main()
