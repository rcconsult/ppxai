"""Pluggable secret-source abstraction for ppxai-server (v1.19.0, Inc 8a).

ADR 0003 §C2 amendment. The "pluggable resolver" promised by C2 is
concretized here as a single Protocol that both `/v1/tokens` and (in
Inc 8b) the per-run authz gate consume, *blind to the backend*. The
validator (`resolve`) is decoupled from the source — the same
decoupling ADR C5.2 made (`auth: "bearer"` does not mandate the
`/v1/tokens` source).

Design properties (each load-bearing — see the ADR):

- ``resolve()`` is the validator. Today's single-shared-token check in
  ``server/auth.py`` becomes ``EnvSecretProvider.resolve()`` with one
  record. When no ``server.secrets`` config is present the server
  behaves exactly as before (unauth-if-unset preserved).
- ``capabilities()`` lets read-only backends coexist with mutable ones.
  ``env`` / k8s Secret are read-only (operator rotates out-of-band) →
  ``/v1/tokens`` ``mint``/``revoke`` return 405 for them; ``file`` is
  fully mutable. This is what lets the *same* ``/v1/tokens`` wire serve
  file-today and k8s-later with no re-shape.
- ``SecretRef`` (never raw material) crosses the seam except at
  ``mint()`` (returns material once, GitHub-PAT style) and
  ``resolve()``. Rotation/expiry/audit live behind the ref.
- ``ProviderChain`` (chain.py) tries providers in order, so a deployment
  runs file-tokens *plus* legacy ``PPXAI_API_TOKEN`` simultaneously →
  non-breaking migration.

This module defines ONLY the protocol + value objects + capability
constants. Concrete providers live in env.py / file.py; composition in
chain.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple, runtime_checkable

# ---------------------------------------------------------------------------
# Capability tokens. A provider advertises which mutating operations it
# supports via capabilities(); the /v1/tokens route returns 405 for an
# operation the resolved provider does not advertise.
# ---------------------------------------------------------------------------
CAP_RESOLVE = "resolve"  # always present — a provider that can't resolve is useless
CAP_LIST = "list"
CAP_MINT = "mint"
CAP_REVOKE = "revoke"
CAP_ROTATE = "rotate"

ALL_CAPABILITIES = frozenset(
    {CAP_RESOLVE, CAP_LIST, CAP_MINT, CAP_REVOKE, CAP_ROTATE}
)


@dataclass(frozen=True)
class SecretRef:
    """Opaque pointer to secret material — NOT the material itself.

    The ref is what is safe to persist, log, and hand across the seam.
    The backend knows how to dereference it; nothing else does. ``kind``
    names the backend ("env", "file", "k8s", ...); ``locator`` is
    backend-private (e.g. an env-var name, a token_id within a file, a
    "namespace/secret/key" for k8s).
    """

    kind: str
    locator: str


@dataclass(frozen=True)
class TokenRecord:
    """Metadata about a token — safe to list and log. Holds NO material.

    ``token_id`` is a public, stable handle (used in ``/v1/tokens`` URLs
    and ``DELETE``). ``owner`` is the principal the token authenticates —
    in Inc 8b this becomes ``RunMeta.owner``. ``roles`` feeds C5.2
    token-role routing. ``expires_at`` / ``revoked`` are evaluated by the
    provider during ``resolve()``; an expired or revoked record must not
    resolve.
    """

    token_id: str
    owner: str
    secret_ref: SecretRef
    roles: Tuple[str, ...] = field(default_factory=tuple)
    expires_at: Optional[float] = None
    revoked: bool = False

    def is_active(self, now: float) -> bool:
        """True when the record may still authenticate at time ``now``."""
        if self.revoked:
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        return True


@runtime_checkable
class SecretProvider(Protocol):
    """A source of bearer tokens, blind to its consumers.

    Implementations live behind ``ProviderChain``. Every method except
    ``resolve``/``capabilities``/``name`` is optional in spirit: a
    read-only provider raises :class:`CapabilityError` (which the route
    maps to 405) for ``mint``/``revoke``. Implementations should still
    *define* the methods so the Protocol is satisfied structurally.
    """

    name: str

    def capabilities(self) -> frozenset:
        """Set of CAP_* this provider supports. Always includes resolve."""
        ...

    def resolve(self, presented: str) -> Optional[TokenRecord]:
        """Validate an inbound bearer string.

        Returns the matching active :class:`TokenRecord`, or ``None`` if
        the token is unknown / expired / revoked. Must be constant-time
        where practical and must never raise on a bad token (return
        ``None``); raising is reserved for backend faults.
        """
        ...

    def list(self) -> "list[TokenRecord]":
        """All known records (metadata only). May raise CapabilityError."""
        ...

    def mint(
        self,
        owner: str,
        roles: Tuple[str, ...] = (),
        ttl_s: Optional[float] = None,
    ) -> Tuple[str, TokenRecord]:
        """Create a token. Returns ``(raw_material, record)``.

        The raw material is returned EXACTLY ONCE; the provider persists
        only a hash. May raise CapabilityError on read-only backends.
        """
        ...

    def revoke(self, token_id: str) -> bool:
        """Revoke by id. Returns True if a record was revoked, else False.

        May raise CapabilityError on read-only backends.
        """
        ...


class CapabilityError(RuntimeError):
    """Raised when an operation is asked of a provider that lacks the
    capability (e.g. ``mint`` on an env-backed read-only provider). The
    ``/v1/tokens`` route maps this to HTTP 405.
    """

    def __init__(self, provider_name: str, capability: str) -> None:
        self.provider_name = provider_name
        self.capability = capability
        super().__init__(
            f"provider {provider_name!r} does not support {capability!r}"
        )
