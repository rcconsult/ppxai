"""v1 gateway: agent runs (ADR 0003 Stage 2 — Increment 1).

An *agent run* is a durable, addressable execution of an agent task. This
module is the HTTP surface over `engine.agent_runs.AgentRunRegistry`:

    POST /v1/agent/run        → create + run a task, returns {run_id, status}
    GET  /v1/agent/runs       → list all runs
    GET  /v1/agent/runs/<id>  → fetch one run's meta

**Increment 1 (intentionally minimal):** the run executes
**synchronously** — `POST /v1/agent/run` blocks until the task completes,
then returns the terminal status. This keeps Inc 1 free of background-task
machinery while still being a real, curl-able capability. Inc 2 moves
execution to a background `asyncio.Task` so the POST returns immediately
with `status:"running"`.

NOT yet (later increments, additively): background exec (Inc 2),
events.jsonl + SSE (Inc 3), capability/tool enforcement (Inc 4 — the
`tools` grant is recorded but not enforced), egress policy (Inc 5),
budgets/cancel (Inc 6), sub-agents (Inc 7), per-run authz (Inc 8).

The `/v1/` prefix is the stable gateway boundary (see docs/api-gateway.md):
adding optional request fields is non-breaking; removing/repurposing
needs a `/v2`.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...common.logger import get_logger
from ...config.providers import get_default_model, get_default_provider
from ...engine.agent_runs import RunMeta
from ...engine.providers.openai_compat import OpenAICompatibleProvider
from ..state import get_agent_run_registry
# Reuse oneshot's provider construction so Inc 1 has zero provider-wiring
# duplication; the synchronous run IS a oneshot call under the hood.
from .oneshot import _build_provider

logger = get_logger("server")

router = APIRouter(prefix="/v1/agent")


# ---------------------------------------------------------------------------
# Wire contract
# ---------------------------------------------------------------------------


class AgentRunRequest(BaseModel):
    """Create-and-run request. Optional fields grow additively per increment."""

    task: str = Field(..., min_length=1, description="The agent task / prompt.")
    tools: list[str] = Field(
        default_factory=list,
        description=(
            "Tool grant for the run. Inc 1 records it but does not enforce; "
            "enforcement lands in Inc 4."
        ),
    )
    provider: Optional[str] = Field(
        None, description="Provider ID. Falls back to server default_provider."
    )
    model: Optional[str] = Field(
        None, description="Model ID. Falls back to the provider's default_model."
    )
    system: Optional[str] = Field(None, description="Optional system message.")


class RunMetaResponse(BaseModel):
    """Public projection of a run's meta (the stable list/get shape)."""

    run_id: str
    task: str
    status: str
    parent_run_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    tools: list[str] = Field(default_factory=list)
    created_at: float = 0.0
    finished_at: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def from_meta(cls, m: RunMeta) -> "RunMetaResponse":
        return cls(
            run_id=m.run_id,
            task=m.task,
            status=m.status,
            parent_run_id=m.parent_run_id,
            provider=m.provider,
            model=m.model,
            tools=list(m.tools),
            created_at=m.created_at,
            finished_at=m.finished_at,
            result=m.result,
            error=m.error,
        )


class AgentRunResponse(BaseModel):
    """Immediate reply to POST /v1/agent/run."""

    run_id: str
    status: str


class RunListResponse(BaseModel):
    runs: list[RunMetaResponse]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/run", response_model=AgentRunResponse)
async def create_agent_run(req: AgentRunRequest) -> AgentRunResponse:
    """Create a run and execute it synchronously (Inc 1). See module docstring."""
    registry = get_agent_run_registry()

    provider_name = req.provider or get_default_provider()
    if not provider_name:
        raise HTTPException(
            status_code=400,
            detail="No provider specified and no default_provider configured.",
        )
    model = req.model or get_default_model(provider_name)
    if not model:
        raise HTTPException(
            status_code=400,
            detail=f"No model specified and no default_model for provider {provider_name!r}.",
        )

    meta = registry.start_run(
        task=req.task, tools=req.tools, provider=provider_name, model=model
    )

    # --- synchronous execution (Inc 1) ---------------------------------
    provider = _build_provider(provider_name)
    if not isinstance(provider, OpenAICompatibleProvider):
        # Mirror oneshot's v1 carve-out. Mark the run failed so the record
        # is honest, then surface the same 400.
        registry.finish_run(
            meta, status="failed",
            error=f"Provider {provider_name!r} not supported by v1 agent runs yet.",
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider {provider_name!r} doesn't support v1 agent runs yet "
                f"(v1 supports OpenAI-compatible providers)."
            ),
        )

    try:
        result = provider.oneshot(prompt=req.task, model=model, system=req.system)
        meta = registry.finish_run(
            meta, status="completed", result=result.get("content", "")
        )
    except Exception as e:  # noqa: BLE001 — record any failure on the run
        logger.warning(f"Agent run {meta.run_id} failed: {e}")
        meta = registry.finish_run(meta, status="failed", error=str(e))

    return AgentRunResponse(run_id=meta.run_id, status=meta.status)


@router.get("/runs", response_model=RunListResponse)
async def list_agent_runs() -> RunListResponse:
    """List all agent runs, newest first."""
    registry = get_agent_run_registry()
    return RunListResponse(
        runs=[RunMetaResponse.from_meta(m) for m in registry.list_runs()]
    )


@router.get("/runs/{run_id}", response_model=RunMetaResponse)
async def get_agent_run(run_id: str) -> RunMetaResponse:
    """Fetch one run's meta, or 404."""
    registry = get_agent_run_registry()
    meta = registry.get_run(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id!r}")
    return RunMetaResponse.from_meta(meta)
