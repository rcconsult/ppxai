"""Env-var secret provider (v1.19.0, Inc 8a).

Wraps today's ``PPXAI_API_TOKEN`` single-shared-token model behind the
:class:`SecretProvider` seam, with ZERO behavior change: when the env var
is unset, ``resolve`` matches nothing (and the chain, finding no active
providers, leaves the server unauthenticated exactly as before).

Read-only by design — the operator rotates the env var out-of-band (k8s
ConfigMap/Secret reload, shell export). ``mint``/``revoke``/``list`` are
unsupported (``capabilities()`` advertises only ``resolve``), so
``/v1/tokens`` returns 405 for those against this backend.
"""

from __future__ import annotations

import builtins
import hmac
import os

from .base import (
    CAP_RESOLVE,
    CapabilityError,
    SecretProvider,
    SecretRef,
    TokenRecord,
)

DEFAULT_ENV_VAR = "PPXAI_API_TOKEN"

# Stable id/owner for the single env token. There is exactly one principal
# in the shared-token model; Inc 8b stamps this owner on runs created with
# the env token so ownership checks still work uniformly.
_ENV_TOKEN_ID = "env"
_ENV_OWNER = "env"


class EnvSecretProvider:
    """Single-shared-token provider backed by an environment variable."""

    def __init__(self, var: str = DEFAULT_ENV_VAR) -> None:
        self.var = var
        self.name = f"env:{var}"

    # -- capabilities -------------------------------------------------
    def capabilities(self) -> frozenset:
        return frozenset({CAP_RESOLVE})

    def _expected(self) -> str | None:
        """Current configured token, or None when auth is disabled.

        Read live (not cached) so operators can enable/disable/rotate by
        updating the env var without a restart — matches the historical
        ``auth.get_required_token`` contract. Empty string == disabled.
        """
        token = os.environ.get(self.var, "").strip()
        return token or None

    def is_active(self) -> bool:
        """True when this provider currently enforces a token."""
        return self._expected() is not None

    # -- resolve ------------------------------------------------------
    def resolve(self, presented: str) -> TokenRecord | None:
        expected = self._expected()
        if expected is None:
            return None
        # Constant-time compare to avoid leaking length/prefix via timing.
        if not hmac.compare_digest(presented, expected):
            return None
        return TokenRecord(
            token_id=_ENV_TOKEN_ID,
            owner=_ENV_OWNER,
            secret_ref=SecretRef(kind="env", locator=self.var),
        )

    # -- mutating ops (unsupported) -----------------------------------
    def list(self) -> builtins.list[TokenRecord]:
        raise CapabilityError(self.name, "list")

    def mint(
        self,
        owner: str,
        roles: tuple[str, ...] = (),
        ttl_s: float | None = None,
    ) -> tuple[str, TokenRecord]:
        raise CapabilityError(self.name, "mint")

    def revoke(self, token_id: str) -> bool:
        raise CapabilityError(self.name, "revoke")


# Structural conformance check (cheap, import-time).
_: SecretProvider = EnvSecretProvider()
