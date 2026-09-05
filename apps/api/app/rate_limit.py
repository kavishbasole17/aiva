"""Rate limiting (slowapi/limits, in-memory — swappable for a Redis storage
backend at scale via `Limiter(storage_uri=...)`, not needed at this size).

A conservative default applies to every route; auth endpoints (the classic
brute-force target) and public token-gated candidate endpoints (unauthenticated
by design, so a token itself is the only secret — worth extra protection
against brute-forcing/enumeration) get stricter explicit limits at their
router. IP-based (`get_remote_address`): behind a reverse proxy, configure it
to set a trusted `X-Forwarded-For` and swap the key function accordingly —
not needed for direct-exposure dev/demo deployment.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

AUTH_LOGIN_LIMIT = "10/minute"
AUTH_REGISTER_LIMIT = "5/minute"
AUTH_REFRESH_LIMIT = "30/minute"
PUBLIC_ENDPOINT_LIMIT = "30/minute"
