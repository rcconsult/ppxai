"""v1 gateway: token management (ADR 0003 Stage 2 — Increment 8a).

CRUD over the configured :class:`~ppxai.server.secrets.ProviderChain`:

    GET    /v1/tokens          → list token metadata (never material)
    POST   /v1/tokens          → mint a token; returns material ONCE
    DELETE /v1/tokens/<id>     → revoke a token

The route is backend-blind: it calls the chain, which routes each
operation to the first capable provider. Against a read-only backend
(env / k8s Secret) the mutating operations return **405** (the chain
raises :class:`CapabilityError`, mapped here).

Auth: these endpoints are themselves behind the standard auth
middleware (``server/auth.py``). When auth is disabled (no provider
enforces a token) they are reachable on loopback like every other
endpoint — minting the first token is how an operator bootstraps a
file-backed deployment. Per-run *authorization* is Inc 8b; this module
only manages the credentials.

The material is returned exactly once on mint and never persisted raw
(the file provider stores a salted SHA-256 hash). It is never logged.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...common.logger import get_logger
from ..secrets import CAP_LIST, CAP_MINT, CAP_REVOKE, CapabilityError
from ..state import get_secret_provider

logger = get_logger(__name__)

router = APIRouter()


class MintTokenRequest(BaseModel):
    owner: str = Field(..., description="Principal the token authenticates.")
    roles: List[str] = Field(
        default_factory=list,
        description="Role labels for routing/authz (C5.2 token-role).",
    )
    ttl_s: Optional[float] = Field(
        default=None,
        description="Lifetime in seconds; omit for a non-expiring token.",
    )


class TokenMeta(BaseModel):
    token_id: str
    owner: str
    roles: List[str]
    expires_at: Optional[float]
    revoked: bool
    source: str = Field(description="Backend kind that holds the token.")


class MintTokenResponse(BaseModel):
    token: str = Field(description="The raw bearer material — shown ONCE.")
    meta: TokenMeta


def _meta(record) -> TokenMeta:
    return TokenMeta(
        token_id=record.token_id,
        owner=record.owner,
        roles=list(record.roles),
        expires_at=record.expires_at,
        revoked=record.revoked,
        source=record.secret_ref.kind,
    )


@router.get("/v1/tokens", response_model=List[TokenMeta])
async def list_tokens() -> List[TokenMeta]:
    chain = get_secret_provider()
    try:
        records = chain.list()
    except CapabilityError:
        raise HTTPException(
            status_code=405,
            detail=(
                "No configured secret provider supports listing tokens "
                "(the active backend is read-only). Configure a 'file' "
                "provider under server.secrets to manage tokens."
            ),
        )
    return [_meta(r) for r in records]


@router.post("/v1/tokens", response_model=MintTokenResponse, status_code=201)
async def mint_token(req: MintTokenRequest) -> MintTokenResponse:
    chain = get_secret_provider()
    if not req.owner.strip():
        raise HTTPException(status_code=422, detail="owner must be non-empty")
    try:
        material, record = chain.mint(
            owner=req.owner,
            roles=tuple(req.roles),
            ttl_s=req.ttl_s,
        )
    except CapabilityError:
        raise HTTPException(
            status_code=405,
            detail=(
                "No configured secret provider supports minting tokens "
                "(the active backend is read-only). Configure a 'file' "
                "provider under server.secrets to mint tokens."
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Never log the material — only the public id.
    logger.info(f"minted token {record.token_id} for owner {record.owner}")
    return MintTokenResponse(token=material, meta=_meta(record))


@router.delete("/v1/tokens/{token_id}")
async def revoke_token(token_id: str) -> dict:
    chain = get_secret_provider()
    try:
        revoked = chain.revoke(token_id)
    except CapabilityError:
        raise HTTPException(
            status_code=405,
            detail=(
                "No configured secret provider supports revoking tokens "
                "(the active backend is read-only)."
            ),
        )
    if not revoked:
        raise HTTPException(
            status_code=404, detail=f"no token with id {token_id!r}"
        )
    logger.info(f"revoked token {token_id}")
    return {"ok": True, "token_id": token_id, "revoked": True}
