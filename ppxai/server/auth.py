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

v1.19.0 (Inc 8a): auth now delegates to the pluggable
:class:`~ppxai.server.secrets.ProviderChain` (ADR 0003 §C2). The chain
defaults to a single :class:`EnvSecretProvider` on ``PPXAI_API_TOKEN``,
so the behavior described above is unchanged when ``server.secrets`` is
not configured. With a ``file`` provider configured, multi-token mint/
revoke via ``/v1/tokens`` becomes available — but this module still only
*authenticates* (is the bearer valid?); per-run *authorization* (may
this bearer read THIS run?) lands in Inc 8b.
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
    """Return the configured env API token, or None if unset.

    Read on every request rather than cached at startup so operators
    can enable / disable / rotate the token by updating the env var
    without restarting the server (e.g. via k8s ConfigMap reload).
    Empty strings are treated as "auth disabled" so a stray
    `PPXAI_API_TOKEN=` in a config file doesn't accidentally lock
    everyone out.

    NOTE (v1.19.0): this remains the env-var view only. Whether auth is
    *enforced* now depends on the full provider chain — use
    :func:`is_auth_enabled`.
    """
    token = os.environ.get(ENV_TOKEN_VAR, "").strip()
    return token or None


def _provider_enforces_auth() -> bool:
    """True when auth must be enforced for this server.

    Policy (v1.19.0):

    - A **mutable** provider (one advertising ``mint`` — i.e. an
      operator-managed token store like ``file``) enforces auth by its
      mere *presence*, even when it currently holds zero tokens. An
      empty store means "no one may in" (401), NOT "everyone in". This
      closes the footgun where revoking the last token silently opens
      the server.
    - A read-only ``env`` provider enforces only when its var is set
      (preserves the v1.18.3 loopback desktop UX: unset => unauth).
    - A read-only non-env stub (k8s, ...) we can't introspect is assumed
      to enforce — fail closed.

    First-token bootstrap when a mutable store is empty is handled
    separately by a loopback exemption on ``POST /v1/tokens`` (see
    ``routes/tokens_v1.py``), so closing the server here does not lock
    out the local operator.
    """
    try:
        from .secrets import CAP_MINT, EnvSecretProvider
        from .state import get_secret_provider

        chain = get_secret_provider()
        for provider in getattr(chain, "providers", []):
            if isinstance(provider, EnvSecretProvider):
                if provider.is_active():
                    return True
                continue
            # Mutable store (file, future vault): presence => enforce,
            # regardless of how many tokens it currently holds.
            try:
                if CAP_MINT in provider.capabilities():
                    return True
            except Exception:
                # Can't introspect capabilities — fail closed.
                return True
            # Read-only non-env stub (k8s, ...) — fail closed too.
            return True
    except Exception:
        # Fall back to the legacy env-only view if the chain is unavailable.
        return get_required_token() is not None
    return False


def is_auth_enabled() -> bool:
    """True when bearer-token auth is enforced by any configured provider."""
    return _provider_enforces_auth()


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_loopback(request: Request) -> bool:
    """True when the request originates from the local machine."""
    client = request.client
    host = client.host if client else None
    return host in _LOOPBACK_HOSTS


def _mutable_store_is_empty() -> bool:
    """True when a mutable (mint-capable) provider exists but holds no
    active tokens — the bootstrap window for the first token."""
    try:
        import time as _t

        from .secrets import CAP_LIST, CAP_MINT
        from .state import get_secret_provider

        now = _t.time()
        saw_mutable = False
        for provider in get_secret_provider().providers:
            caps = provider.capabilities()
            if CAP_MINT not in caps:
                continue
            saw_mutable = True
            if CAP_LIST in caps and any(r.is_active(now) for r in provider.list()):
                return False  # has at least one active token => not empty
        return saw_mutable
    except Exception:
        return False  # can't prove it's empty => no bootstrap exemption


def _is_bootstrap_mint(request: Request) -> bool:
    """Allow ONE narrow unauthenticated case: minting the FIRST token.

    ``POST /v1/tokens`` from loopback while the mutable store is empty.
    This lets the local operator bootstrap when the empty-store policy
    has otherwise closed the server; it is NOT a standing hole — once any
    active token exists, this returns False and auth is required again.
    """
    path = request.url.path.rstrip("/")
    if request.method == "POST" and path == "/v1/tokens":
        return _is_loopback(request) and _mutable_store_is_empty()
    return False


def check_request(request: Request) -> Optional[JSONResponse]:
    """Validate auth for a request.

    Returns None if the request should proceed (auth disabled, or
    valid bearer token, or OPTIONS preflight). Returns a 401
    JSONResponse if the request must be rejected.

    OPTIONS preflight is exempted because CORS preflight by spec does
    NOT carry the Authorization header — browsers send the actual
    request with the header only after the preflight succeeds.

    v1.19.0: validates against the provider chain. On success the
    resolved :class:`TokenRecord` is stashed on ``request.state.principal``
    so downstream code (Inc 8b per-run authz) can read the owner without
    re-resolving. A loopback ``POST /v1/tokens`` is exempted while the
    mutable token store is empty, to bootstrap the first token.
    """
    if not is_auth_enabled():
        return None

    # CORS preflight — never carries Authorization. The actual call
    # following the preflight will be re-validated.
    if request.method == "OPTIONS":
        return None

    # First-token bootstrap: loopback mint into an empty mutable store.
    if _is_bootstrap_mint(request):
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

    from .state import get_secret_provider

    record = get_secret_provider().resolve(parts[1])
    if record is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid token"},
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )

    # Stash the authenticated principal for downstream authz (Inc 8b).
    request.state.principal = record
    return None
