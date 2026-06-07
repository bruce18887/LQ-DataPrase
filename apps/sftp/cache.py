"""Session store for transient SFTP connection credentials.

Why this module exists
----------------------
``apps.sftp.views.SftpViewSet.connect`` previously cached ``host / port /
username / password`` in ``django.core.cache`` with a 1-hour TTL. The default
Django cache backend is **per-process** (LocMemCache), so a multi-worker
gunicorn / uwsgi deployment could not share the cached connection between
workers, and the password was stored **in plaintext** in cache — which would
also be a problem if we ever switched the cache backend to a shared store
(e.g. Redis) to fix the per-process issue.

This module replaces that cache with a small, opinionated wrapper that:

1. **Prefers shared Redis** (multi-worker / multi-host safe) when available.
2. **Falls back to Django's default cache** (LocMemCache in dev) when Redis is
   unreachable, so single-process development works out of the box without
   requiring a running Redis server.
3. **Encrypts the password** with the same Fernet helper that already protects
   saved ``SftpConfig`` passwords (``apps.sftp.crypto``). Even if the cache
   backend is dumped, the password is not recoverable without the key.
4. Namespaces keys under ``sftp:conn:<user_id>`` (Redis) or
   ``sftp_session_<user_id>`` (Django cache) so unrelated cache keys cannot
   collide.

Callers never need to know which backend is active — ``get_session`` /
``set_session`` / ``delete_session`` provide a uniform interface.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from django.conf import settings

from . import crypto

logger = logging.getLogger(__name__)

# Public so tests can introspect without re-deriving.
KEY_PREFIX = 'sftp:conn:'
DJANGO_CACHE_PREFIX = 'sftp_session_'
DEFAULT_TTL_SECONDS = 3600  # 1 hour, matches the previous Django cache TTL.


class SftpSessionCacheError(Exception):
    """Raised when no cache backend can store or retrieve the session."""


def _ttl_seconds() -> int:
    return int(getattr(settings, 'SFTP_SESSION_TTL', DEFAULT_TTL_SECONDS))


def _redis_url() -> Optional[str]:
    """Return the Redis URL to use, or ``None`` if not configured.

    Resolution order:
      1. ``settings.SFTP_SESSION_REDIS_URL`` (explicit override)
      2. ``settings.REDIS_URL`` (the project-wide var, also in .env.example)
      3. ``settings.CELERY_BROKER_URL`` (Celery already needs a broker)
    """
    return (
        getattr(settings, 'SFTP_SESSION_REDIS_URL', None)
        or getattr(settings, 'REDIS_URL', None)
        or getattr(settings, 'CELERY_BROKER_URL', None)
    )


_redis_client = None  # module-level singleton; None = not yet probed.
_redis_unavailable = False  # True once we know Redis is down → skip retries.


def _get_redis():
    """Return a Redis client, or ``None`` if Redis is unreachable.

    On first call the client is created and ``ping()`` is issued.  If that
    fails, subsequent calls return ``None`` immediately (no retry storm).
    A successful ping caches the client for the process lifetime.
    """
    global _redis_client, _redis_unavailable

    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client

    url = _redis_url()
    if not url:
        _redis_unavailable = True
        return None

    try:
        import redis  # type: ignore
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        _redis_client = client
        logger.info('SFTP session cache: using Redis at %s', url.split('@')[-1] if '@' in url else url)
        return client
    except Exception as exc:
        _redis_unavailable = True
        logger.warning(
            'SFTP session cache: Redis unavailable (%s), falling back to Django cache.', exc,
        )
        return None


def _django_cache():
    """Return Django's default cache backend (lazy import)."""
    from django.core.cache import cache
    return cache


def _redis_key(user_id) -> str:
    return f"{KEY_PREFIX}{user_id}"


def _django_key(user_id) -> str:
    return f"{DJANGO_CACHE_PREFIX}{user_id}"


def _decrypt_payload(raw: str) -> Optional[dict]:
    """Parse a JSON cache payload and decrypt its password field."""
    try:
        payload = json.loads(raw)
        encrypted_pw = payload.get('password') or ''
        payload['password'] = crypto.decrypt(encrypted_pw) if encrypted_pw else ''
        return payload
    except Exception:
        return None


def get_session(user_id) -> Optional[dict]:
    """Return the stored session dict for ``user_id`` or ``None``.

    Tries Redis first; if Redis is unavailable, falls back to Django's
    default cache.  Returns ``None`` on cache miss or corrupt payload.
    """
    client = _get_redis()
    if client is not None:
        try:
            raw = client.get(_redis_key(user_id))
            if raw:
                payload = _decrypt_payload(raw)
                if payload:
                    return payload
                # Corrupt → drop it.
                try:
                    client.delete(_redis_key(user_id))
                except Exception:
                    pass
            return None
        except Exception as exc:
            logger.warning('SFTP session Redis read failed, trying Django cache: %s', exc)

    # Fallback: Django default cache.
    cache = _django_cache()
    raw = cache.get(_django_key(user_id))
    if not raw:
        return None
    payload = _decrypt_payload(raw)
    if not payload:
        cache.delete(_django_key(user_id))
        return None
    return payload


def set_session(user_id, host: str, port: int, username: str, password: str) -> None:
    """Encrypt ``password`` and store the session for ``user_id``.

    Tries Redis first; falls back to Django's default cache.
    Raises ``SftpSessionCacheError`` only if **both** backends fail.
    """
    encrypted_pw = crypto.encrypt(password or '')
    payload = json.dumps({
        'host': host,
        'port': int(port),
        'username': username,
        'password': encrypted_pw,
    })
    ttl = _ttl_seconds()

    client = _get_redis()
    if client is not None:
        try:
            client.set(_redis_key(user_id), payload, ex=ttl)
            return
        except Exception as exc:
            logger.warning('SFTP session Redis write failed, trying Django cache: %s', exc)

    # Fallback: Django default cache.
    try:
        _django_cache().set(_django_key(user_id), payload, ttl)
    except Exception as exc:
        logger.error('SFTP session Django cache write also failed: %s', exc)
        raise SftpSessionCacheError(str(exc)) from exc


def delete_session(user_id) -> None:
    """Remove the session for ``user_id`` from whichever backend has it."""
    client = _get_redis()
    if client is not None:
        try:
            client.delete(_redis_key(user_id))
        except Exception as exc:
            logger.warning('SFTP session Redis delete failed: %s', exc)

    try:
        _django_cache().delete(_django_key(user_id))
    except Exception:
        pass
