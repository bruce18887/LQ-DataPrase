"""Settings *package* marker — this module is deliberately NOT a settings file.

``DJANGO_SETTINGS_MODULE`` must point at a concrete profile:

* ``config.settings.development`` — SQLite, DEBUG on, Swagger on (default for
  ``manage.py``, ``config/wsgi.py``, ``config/asgi.py`` and every test module).
* ``config.settings.standalone``  — the packaged desktop build (DEBUG off,
  loopback ALLOWED_HOSTS, API docs routed off).
* ``config.settings.server``      — the LAN multi-user profile (SQLite,
  ``LQDP_SERVER_BASE_DIR`` / ``DJANGO_ALLOWED_HOSTS`` / ``SECRET_KEY`` /
  ``SFTP_CONFIG_KEY`` all required from the environment).
* ``config.settings.e2e_slot``    — one e2e pool slot (isolated by
  ``LQDP_E2E_SLOT_DIR``).

All profiles are thin overrides on top of ``config.settings.base``.

This file used to hold a third, standalone copy of the settings. It was stale
and dangerous in equal measure: a hard-coded public ``django-insecure-``
SECRET_KEY, ``DEBUG=True``, and an ``INSTALLED_APPS`` that had not been updated
since the project had two apps (it was missing analysis / dashboard / export /
sftp / gage / buyoff / batch_report / common / drf_spectacular). Any
script that pointed ``DJANGO_SETTINGS_MODULE`` at ``config.settings`` therefore
ran in debug mode with a known key and a broken app registry — which is exactly
what ``scripts/update_sub_batch.py`` did. Fail loudly instead: with no settings
defined here, such a mistake raises ``ImproperlyConfigured`` at ``django.setup()``
rather than quietly booting an insecure profile.
"""
