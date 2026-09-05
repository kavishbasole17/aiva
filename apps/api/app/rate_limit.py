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

# Pen-test pass (M12): PUBLIC_ENDPOINT_LIMIT was previously wired into only 2 of
# the ~18 unauthenticated, raw-token-gated candidate endpoints (the two GET
# "fetch state" routes) -- every other one relied solely on the 200/minute
# global default above. Tokens are 256-bit (`generate_invite_token`), so this
# was never a practical brute-force gap, but it was an inconsistent one, and
# the global default alone is a weak DoS ceiling for routes that don't need
# it. Now applied to every public route *except* the two genuinely
# high-frequency, low-marginal-risk ones: code autosave (800ms-debounced
# keystroke saves can legitimately exceed 30/minute while typing) and code
# execution (a candidate iterating quickly while debugging) -- both stay
# under the 200/minute global default instead, which is still a real ceiling,
# just not one that risks throttling normal use.
