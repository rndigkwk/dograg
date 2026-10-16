"""Who is signed in: the Supabase Auth access token a request carries (ADR-0008 P4).

The browser signs in with Google through Supabase Auth and sends its access token as
`Authorization: Bearer <token>`. The API uses it for one thing only: to count a signed-in person's
questions by their account (src/rate_limit.py) instead of by a browser id they can clear. It never
reads or writes the user's records (row level security handles those, in the browser).

A token counts only when all of these hold (anything else is treated as no sign-in, never an error):
- signed by the project's current key, fetched from its JWKS (ES256: asymmetric, so no secret is
  kept here; an HS256 or `alg: none` token is refused before any key is looked up);
- issued by this project (`iss`), for signed-in users (`aud` "authenticated", `role` "authenticated");
- not expired (`exp`, with LEEWAY_SECONDS for clock skew), with a user id (`sub`).
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import jwt

from src import settings

logger = logging.getLogger(__name__)

DEFAULT_SUPABASE_URL = "https://ffdahevkdymdaxcexkth.supabase.co"  # public: the browser uses it too
ALGORITHMS = ["ES256"]  # what the project's JWKS publishes (2026-10-16); HS256 would need a secret
LEEWAY_SECONDS = 30
_USER_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def supabase_url() -> str:
    return (settings.get_setting("SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")


@lru_cache(maxsize=1)
def _jwks(url: str) -> jwt.PyJWKClient:
    # Keys are cached for an hour; a token with an unknown key id refetches once (key rotation).
    return jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600, timeout=5)


def user_id(authorization: str | None) -> str | None:
    """The signed-in user's id from an `Authorization: Bearer` header, or None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    try:
        if jwt.get_unverified_header(token).get("alg") not in ALGORITHMS:
            return None  # refuse HS256 / none before touching a key: no algorithm confusion
        url = supabase_url()
        key = _jwks(url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, key.key, algorithms=ALGORITHMS, audience="authenticated", issuer=f"{url}/auth/v1",
            leeway=LEEWAY_SECONDS, options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except jwt.PyJWKClientError as error:
        # A key id the project does not have is a forged or stale token: no log for each one. Only a
        # failure to fetch the keys at all is worth a warning (every signed-in user counts as signed out).
        if "Unable to find a signing key" not in str(error):
            logger.warning("Supabase signing keys unavailable; treating the request as signed out: %s", error)
        return None
    except jwt.PyJWTError:
        return None
    sub = claims.get("sub")
    if claims.get("role") != "authenticated" or not isinstance(sub, str) or not _USER_ID.fullmatch(sub):
        return None
    return sub
