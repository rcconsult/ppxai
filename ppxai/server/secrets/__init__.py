"""Pluggable secret-source framework (v1.19.0, Inc 8a).

ADR 0003 §C2 amendment. See base.py for the design rationale.

The public surface is :func:`build_chain_from_config` (constructs the
configured :class:`ProviderChain`) plus the value objects re-exported for
consumers (``server/auth.py``, the ``/v1/tokens`` route, and — in Inc 8b
— the per-run authz gate).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...common.logger import get_logger
from .base import (
    ALL_CAPABILITIES,
    CAP_LIST,
    CAP_MINT,
    CAP_RESOLVE,
    CAP_REVOKE,
    CAP_ROTATE,
    CapabilityError,
    SecretProvider,
    SecretRef,
    TokenRecord,
)
from .chain import ProviderChain
from .env import DEFAULT_ENV_VAR, EnvSecretProvider
from .file import FileSecretProvider

logger = get_logger(__name__)

__all__ = [
    "ALL_CAPABILITIES",
    "CAP_LIST",
    "CAP_MINT",
    "CAP_RESOLVE",
    "CAP_REVOKE",
    "CAP_ROTATE",
    "CapabilityError",
    "SecretProvider",
    "SecretRef",
    "TokenRecord",
    "ProviderChain",
    "EnvSecretProvider",
    "FileSecretProvider",
    "build_chain_from_config",
]


def _build_one(spec: Dict[str, Any]) -> Optional[SecretProvider]:
    """Construct a single provider from a config dict, or None if the
    type is unknown (logged + skipped — an unknown future backend in a
    config should degrade, not crash an older server)."""
    ptype = spec.get("type")
    if ptype == "env":
        return EnvSecretProvider(var=spec.get("var", DEFAULT_ENV_VAR))
    if ptype == "file":
        path = spec.get("path", "~/.ppxai/tokens.json")
        return FileSecretProvider(path=path)
    logger.warning(f"unknown secret provider type {ptype!r} — skipping")
    return None


def build_chain_from_config(server_config: Dict[str, Any]) -> ProviderChain:
    """Build the :class:`ProviderChain` from ``server.secrets.providers``.

    Backward-compatible default: when ``server.secrets`` is absent or has
    no providers, fall back to a single :class:`EnvSecretProvider` on
    ``PPXAI_API_TOKEN`` — i.e. EXACTLY today's behavior (unauth when the
    env var is unset, single-shared-token when set).
    """
    secrets_cfg = (server_config or {}).get("secrets") or {}
    raw_providers: List[Dict[str, Any]] = secrets_cfg.get("providers") or []

    providers: List[SecretProvider] = []
    for spec in raw_providers:
        built = _build_one(spec)
        if built is not None:
            providers.append(built)

    if not providers:
        # Legacy default — preserves the v1.18.3 single-shared-token model.
        providers = [EnvSecretProvider()]

    return ProviderChain(providers)
