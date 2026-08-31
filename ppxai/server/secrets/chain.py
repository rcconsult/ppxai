"""Provider chain (v1.19.0, Inc 8a) — compose multiple secret sources.

A deployment can run several providers at once (e.g. file-tokens PLUS
the legacy ``PPXAI_API_TOKEN`` env var) so migration is non-breaking and
C5.2's ``header:X-Custom-Token`` model is just another link.

``resolve`` tries each provider in order and returns the first match.
``mint``/``revoke``/``list`` route to the first provider advertising the
capability — so ``/v1/tokens`` writes land in the file backend even when
a read-only env provider sits in the chain. When NO provider advertises a
mutating capability, the chain raises :class:`CapabilityError` (→ 405).
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence

from .base import (
    CAP_LIST,
    CAP_MINT,
    CAP_REVOKE,
    CapabilityError,
    SecretProvider,
    TokenRecord,
)


class ProviderChain:
    """Ordered composition of :class:`SecretProvider` instances."""

    name = "chain"

    def __init__(self, providers: Sequence[SecretProvider]) -> None:
        self.providers: list[SecretProvider] = list(providers)

    def is_empty(self) -> bool:
        return not self.providers

    # -- capabilities (union) -----------------------------------------
    def capabilities(self) -> frozenset:
        caps: frozenset = frozenset()
        for p in self.providers:
            caps = caps | p.capabilities()
        return caps

    # -- resolve (first match wins) -----------------------------------
    def resolve(self, presented: str) -> TokenRecord | None:
        for p in self.providers:
            record = p.resolve(presented)
            if record is not None:
                return record
        return None

    def _first_with(self, capability: str) -> SecretProvider:
        for p in self.providers:
            if capability in p.capabilities():
                return p
        raise CapabilityError(self.name, capability)

    # -- list (concatenate every capable provider) --------------------
    def list(self) -> builtins.list[TokenRecord]:
        out: list[TokenRecord] = []
        any_capable = False
        for p in self.providers:
            if CAP_LIST in p.capabilities():
                any_capable = True
                out.extend(p.list())
        if not any_capable:
            raise CapabilityError(self.name, CAP_LIST)
        return out

    # -- mint / revoke (first capable provider) -----------------------
    def mint(
        self,
        owner: str,
        roles: tuple[str, ...] = (),
        ttl_s: float | None = None,
    ) -> tuple[str, TokenRecord]:
        return self._first_with(CAP_MINT).mint(owner, roles, ttl_s)

    def revoke(self, token_id: str) -> bool:
        # Try every revoke-capable provider — the id may live in any of
        # them — and report True if any one revoked it.
        any_capable = False
        revoked = False
        for p in self.providers:
            if CAP_REVOKE in p.capabilities():
                any_capable = True
                if p.revoke(token_id):
                    revoked = True
        if not any_capable:
            raise CapabilityError(self.name, CAP_REVOKE)
        return revoked


# Structural conformance check.
_: SecretProvider = ProviderChain([])
