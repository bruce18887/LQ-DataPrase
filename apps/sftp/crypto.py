"""Symmetric encryption helpers for SFTP config secrets (passwords).

Key derivation strategy
-----------------------
A stable 32-byte url-safe base64 Fernet key is derived once (lazily, then
module-cached) from one of two sources, in priority order:

1. ``settings.SFTP_CONFIG_KEY`` — if set, it must be a valid Fernet key
   string (``Fernet.generate_key()`` output). Providing this via the
   environment allows the encryption key to be **rotated independently of
   Django's SECRET_KEY** (e.g. rotate SECRET_KEY without invalidating every
   stored SFTP password, or vice versa).
2. Otherwise the key is derived deterministically from
   ``settings.SECRET_KEY`` using PBKDF2-HMAC-SHA256 with a fixed
   app-specific salt. This means no extra configuration is required to run
   — but rotating SECRET_KEY would invalidate existing tokens, so set
   SFTP_CONFIG_KEY in production if you need independent rotation.

Only ``encrypt`` / ``decrypt`` are public. They operate on ``str`` and never
log or return plaintext.
"""

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings

# Fixed, app-specific salt. Changing this invalidates all SECRET_KEY-derived
# tokens, so it must stay constant.
_SALT = b'dataphrase.sftp.config'
_ITERATIONS = 390000

_fernet = None  # module-level cache; derivation happens once.


def _derive_key() -> bytes:
    """Return a url-safe base64 32-byte Fernet key from settings."""
    configured = getattr(settings, 'SFTP_CONFIG_KEY', None)
    if configured:
        # Already a valid Fernet key string from the environment.
        return configured.encode('utf-8') if isinstance(configured, str) else configured

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=_ITERATIONS,
    )
    derived = kdf.derive(settings.SECRET_KEY.encode('utf-8'))
    return base64.urlsafe_b64encode(derived)


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string → url-safe Fernet token string.

    Empty / falsy input yields an empty string (no token stored).
    """
    if not plaintext:
        return ''
    token = _get_fernet().encrypt(plaintext.encode('utf-8'))
    return token.decode('utf-8')


def decrypt(token: str) -> str:
    """Decrypt a Fernet token string → plaintext string.

    Empty / falsy input yields an empty string.
    """
    if not token:
        return ''
    plaintext = _get_fernet().decrypt(token.encode('utf-8'))
    return plaintext.decode('utf-8')
