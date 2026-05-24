"""
Bearer-token auth for ppxai-server (v1.18.3).

Opt-in, default off:
- When `PPXAI_API_TOKEN` is unset (or empty), the server runs
  unauthenticated. This preserves the localhost desktop UX where
  the Rich/Textual TUI, web app, and VSCode extension talk to
  ppxai-server on loopback and don't carry an Authorization header.
- When `PPXAI_API_TOKEN` is set, every non-preflight request must
  carry `Authorization: Bearer <token>` matching the configured
  value, or it gets a 401 with `WWW-Authenticate: Bearer ...`.

Enable for cluster-internal deployments behind a NetworkPolicy
(defense-in-depth) and any deployment where the server is
reachable beyond loopback (mandatory).

What this does NOT include (deliberately, see docs/api-gateway.md
"Future directions"): multi-token per-agent identity, token
rotation/expiry, scoped tokens, rate limiting per token, OIDC/JWT
integration. Single shared token is the foot-in-the-door for v1.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse


ENV_TOKEN_VAR = "PPXAI_API_TOKEN"

# Headers we attach to 401 responses so well-behaved clients can
# discover that auth is required and prompt for a token.
_WWW_AUTHENTICATE = 'Bearer realm="ppxai"'


def get_required_token() -> Optional[str]:
    """Return the configured API token, or None if auth is disabled.

    Read on every request rather than cached at startup so operators
    can enable / disable / rotate the token by updating the env var
    without restarting the server (e.g. via k8s ConfigMap reload).
    Empty strings are treated as "auth disabled" so a stray
    `PPXAI_API_TOKEN=` in a config file doesn't accidentally lock
    everyone out.
    """
    token = os.environ.get(ENV_TOKEN_VAR, "").strip()
    return token or None


def is_auth_enabled() -> bool:
    """True when bearer-token auth is configured."""
    return get_required_token() is not None


def check_request(request: Request) -> Optional[JSONResponse]:
    """Validate auth for a request.

    Returns None if the request should proceed (auth disabled, or
    valid bearer token, or OPTIONS preflight). Returns a 401
    JSONResponse if the request must be rejected.

    OPTIONS preflight is exempted because CORS preflight by spec does
    NOT carry the Authorization header — browsers send the actual
    request with the header only after the preflight succeeds.
    """
    expected = get_required_token()
    if expected is None:
        return None

    # CORS preflight — never carries Authorization. The actual call
    # following the preflight will be re-validated.
    if request.method == "OPTIONS":
        return None

    authorization = request.headers.get("authorization", "")
    parts = authorization.split(None, 1)

    if len(parts) != 2 or parts[0].lower() != "bearer":
        return JSONResponse(
            status_code=401,
            content={
                "detail": (
                    "Missing or malformed Authorization header. "
                    "Expected: Authorization: Bearer <token>"
                )
            },
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )

    if parts[1] != expected:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid token"},
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )

    return None
