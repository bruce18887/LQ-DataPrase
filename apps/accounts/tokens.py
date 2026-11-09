"""Refresh-token revocation helpers.

``CHECK_REVOKE_TOKEN`` already makes every access/refresh token issued before
a password change fail authentication. Blacklisting the outstanding rows as
well makes ``/auth/refresh/`` itself return 401 instead of minting an access
token that the API will reject.
"""

from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


def revoke_refresh_tokens(user):
    tokens = OutstandingToken.objects.filter(
        user=user, expires_at__gt=timezone.now()
    )
    for token in tokens:
        BlacklistedToken.objects.get_or_create(token=token)
