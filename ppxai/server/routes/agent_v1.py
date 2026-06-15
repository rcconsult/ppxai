"""v1 gateway: agent runs (ADR 0003 Stage 2 — Increments 1–5).

An *agent run* is a durable, addressable execution of an agent task. This
module is the HTTP surface over `engine.agent_runs.AgentRunRegistry`:

    POST /v1/agent/run            → tool-FREE run (oneshot); {run_id, status}
    POST /v1/agent/task           → tool-CAPABLE, sandboxed run (Inc 4)
    GET  /v1/agent/runs           → list all runs
    GET  /v1/agent/runs/<id>      → fetch one run's meta
    GET  /v1/agent/runs/<id>/events → replay + ?live=1 SSE (Inc 3),
                                    ?since= / ?min_level= / ?category= filters

Execution model: runs execute in the **background** (Inc 2). A POST
validates + builds the provider synchronously (a bad provider 400s up
front), mints the run, fires it into a background `asyncio.Task`, and
returns immediately with `status:"running"`. Poll the meta or tail the
event stream to watch it reach `completed`/`failed`.

Two tiers:
- `/run` is tool-FREE (oneshot, safe). Its `tools` field is recorded for
  provenance but never executed.
- `/task` is tool-CAPABLE: the grant is ENFORCED by a `ScopedToolManager`
  (Inc 4 / AC-1 — model sees only granted tools; off-grant `execute_tool`
  hard-denied) and outbound network is governed by a per-run egress
  allowlist (Inc 5 / AC-2 — deny-by-default, typed `NETWORK_POLICY_*`
  events). A shell-execution tool is rejected from a `/task` grant up
  front (shell escapes the egress allowlist; needs the deferred OS-
  isolation tier).

NOT yet (later increments, additively):
budgets/cancel (Inc 6), sub-agents (Inc 7), per-run authz (Inc 8),
AppState mirror (Inc 9).

The `/v1/` prefix is the stable gateway boundary (see docs/api-gateway.md):
adding optional request fields is non-breaking; removing/repurposing
needs a `/v2`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...common.logger import get_logger
from ...config.tools import get_agent_config
from ...engine.agent_runs import RunMeta
from ...engine.providers.openai_compat import OpenAICompatibleProvider
from ...engine.tools.network_policy import grant_has_shell
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
            "Recorded on the run for provenance. /v1/agent/run is the "
            "TOOL-FREE tier (oneshot) — tools here are NOT executed. For a "
            "tool-capable, allowlist-enforced run, use POST /v1/agent/task."
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
    network: list = Field(default_factory=list)
    created_at: float = 0.0
    started_at: Optional[float] = None
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
            network=list(getattr(m, "network", []) or []),
            created_at=m.created_at,
            started_at=m.started_at,
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
    """Create a run and execute it in the background (Inc 2).

    Validation + provider build happen synchronously (so a bad provider
    still gets a 400 up front), then the run is fired into a background
    task and the POST returns immediately with status='running'. Poll
    GET /v1/agent/runs/<id> to watch it flip to completed/failed.
    """
    registry = get_agent_run_registry()

    # Provider/model is PER-RUN INJECTED INTENT (ADR 0003 §9), not inherited
    # from the interactive chat session. Resolution: explicit request value
    # -> tools.agent.default_subagent config -> 400. The session's active
    # chat provider is deliberately NOT consulted (a sub-agent's model is
    # chosen for its task, not for whatever the UI happens to be on).
    # NOTE: per-session sub-agent config + a /subagent slash command, both
    # persisted in the session checkpoint, are a later increment (debt-filed);
    # they will slot in as a layer between request and global config here.
    sub_defaults = get_agent_config().get("default_subagent", {}) or {}
    provider_name = req.provider or sub_defaults.get("provider")
    model = req.model or sub_defaults.get("model")
    if not provider_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "No provider for the agent run. Pass `provider` in the request, "
                "or set tools.agent.default_subagent.provider in ppxai-config.json."
            ),
        )
    if not model:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No model for provider {provider_name!r}. Pass `model` in the "
                f"request, or set tools.agent.default_subagent.model in config."
            ),
        )

    # Build the provider + apply the v1 carve-out BEFORE minting/backgrounding,
    # so an unsupported provider fails fast with 400 and creates no run.
    # (_build_provider raises HTTPException 400 on unknown provider / no key.)
    provider = _build_provider(provider_name)
    if not isinstance(provider, OpenAICompatibleProvider):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider {provider_name!r} doesn't support v1 agent runs yet "
                f"(v1 supports OpenAI-compatible providers)."
            ),
        )

    meta = registry.start_run(
        task=req.task, tools=req.tools, provider=provider_name, model=model
    )

    async def _runner(m) -> str:
        # provider.oneshot is blocking I/O — run it off the event loop so
        # other requests (e.g. GET status polls) aren't starved.
        result = await asyncio.to_thread(
            provider.oneshot, prompt=req.task, model=model, system=req.system
        )
        return result.get("content", "")

    registry.run_in_background(meta, _runner)
    return AgentRunResponse(run_id=meta.run_id, status=meta.status)


class AgentTaskRequest(BaseModel):
    """Tool-capable run request (POST /v1/agent/task — the sandboxed tier).

    Unlike /v1/agent/run (tool-free, safe), a task REQUIRES a non-empty
    `tools` grant: it's the opt-in to the tool-calling sandbox tier, and
    the run may call ONLY those tools (ADR 0003 §4 / AC-1).
    """

    task: str = Field(..., min_length=1, description="The agent task / prompt.")
    tools: list[str] = Field(
        ..., min_length=1,
        description="Capability grant — the ONLY tools this run may call (required, non-empty).",
    )
    provider: Optional[str] = Field(None, description="Provider (per-run intent).")
    model: Optional[str] = Field(None, description="Model (per-run intent).")
    system: Optional[str] = Field(None, description="Optional system message.")
    network: Optional["NetworkSpec"] = Field(
        None,
        description=(
            "Per-run egress allowlist (ADR 0003 §3c / AC-2). Outbound network "
            "from network-capable tools is DENY-BY-DEFAULT: absent or empty "
            "`allow_outbound` means a granted network tool (web_search, "
            "fetch_url, get_weather) reaches nothing. Each entry is a host "
            "string (exact, or `*.suffix` single-label glob) or "
            "{host, paths:[prefix,...]}."
        ),
    )


class NetworkSpec(BaseModel):
    """Egress allowlist spec — ADR 0003 §11 `network{allow_outbound[]}`.

    `allow_outbound` entries are either a bare host string (exact host, any
    path) or an object `{host, paths?}` where `host` may be `*.suffix` for a
    single-label suffix-anchored glob and `paths` is a list of path prefixes.
    """

    allow_outbound: list = Field(
        default_factory=list,
        description="Allowed outbound rules; empty = no outbound (fail-closed).",
    )


AgentTaskRequest.model_rebuild()


@router.post("/task", response_model=AgentRunResponse)
async def create_agent_task(req: AgentTaskRequest) -> AgentRunResponse:
    """Tool-capable, sandboxed agent run (ADR 0003 §4 / AC-1).

    The tool-calling tier, separate from the safe tool-free /v1/agent/run.
    The run executes via `chat_with_tools` through a `ScopedToolManager`
    that exposes ONLY the granted tools to the model and hard-denies any
    off-grant `execute_tool` (emitting a `tool_denied` event). Shares the
    run registry / events / monitor infra with /run.
    """
    registry = get_agent_run_registry()

    # AC-2: a shell-execution tool runs arbitrary commands whose network egress
    # the allowlist cannot inspect (curl/pip/Invoke-WebRequest/…), so it would
    # bypass the egress chokepoint entirely. The only tier that can contain it
    # is OS isolation (ADR 0003 §3 tier-d), deferred past the MVP. Reject the
    # grant up front with a clear error rather than silently never running it.
    if grant_has_shell(req.tools):
        raise HTTPException(
            status_code=400,
            detail=(
                "execute_shell_command is not permitted in a tool-capable "
                "agent run: arbitrary shell escapes the egress allowlist "
                "(AC-2). It requires the OS-isolation tier (ADR 0003 §3 "
                "tier-d), which is deferred past the MVP. Use read-only tools "
                "(read_file, grep, web_search, fetch_url) instead."
            ),
        )

    sub_defaults = get_agent_config().get("default_subagent", {}) or {}
    provider_name = req.provider or sub_defaults.get("provider")
    model = req.model or sub_defaults.get("model")
    if not provider_name or not model:
        raise HTTPException(
            status_code=400,
            detail=(
                "Agent task needs provider+model (request or "
                "tools.agent.default_subagent config)."
            ),
        )

    provider = _build_provider(provider_name)
    if not isinstance(provider, OpenAICompatibleProvider):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider {provider_name!r} doesn't support v1 agent tasks yet "
                f"(v1 supports OpenAI-compatible providers)."
            ),
        )

    meta = registry.start_run(
        task=req.task, tools=req.tools, provider=provider_name, model=model,
        network=(req.network.allow_outbound if req.network else []),
    )

    async def _runner(m) -> str:
        # Build a dedicated EngineClient for this run (ADR 0003 §9 D1 — new
        # client per run, full isolation), enable tools, then SCOPE its tool
        # manager to the grant. The model sees only granted tools; the
        # ScopedToolManager.execute_tool chokepoint denies anything else.
        from ...engine.client import EngineClient
        from ...engine.agent_scoped_tools import ScopedToolManager
        from ...engine.tools.network_policy import NetworkPolicy
        from ...engine.types import EventType

        engine = EngineClient()
        engine.set_provider(provider_name)
        engine.set_model(model)
        engine.enable_tools()  # registers builtins + sets tool-loop limits

        def _on_deny(name: str) -> None:
            registry.emit_event(
                m.run_id, "tool_denied", level="warning", category="tool",
                data={"tool": name, "grant": list(req.tools)},
            )

        # AC-2: per-run egress allowlist. Always installed for a tool-capable
        # run — even with no `network` spec, so a granted network tool is
        # deny-by-default (fail-closed). on_network emits the typed audit event.
        allow_outbound = req.network.allow_outbound if req.network else []
        net_policy = NetworkPolicy(allow_outbound)

        def _on_network(allowed: bool, payload: dict) -> None:
            payload = {**payload, "run_id": m.run_id}
            registry.emit_event(
                m.run_id,
                "network_policy_allowed" if allowed else "network_policy_denied",
                level="info" if allowed else "warning",
                category="network",
                data=payload,
            )

        engine.tool_manager = ScopedToolManager(
            engine.tool_manager, list(req.tools), on_deny=_on_deny,
            network_policy=net_policy, on_network=_on_network,
        )

        final_text: list[str] = []
        async for event in engine.chat(req.task, stream=False):
            # Surface tool activity on the run's event stream. The engine's
            # TOOL_CALL carries the name in event.data["tool"] (a dict), not
            # in metadata; STREAM_END carries the final text as event.data,
            # which is a plain string (sometimes a dict with "content").
            if event.type == EventType.TOOL_CALL:
                d = event.data or {}
                name = d.get("tool", "") if isinstance(d, dict) else ""
                registry.emit_event(
                    m.run_id, "tool_call", level="debug", category="tool",
                    data={"tool": name},
                )
            elif event.type in (EventType.ERROR, EventType.PROVIDER_THROTTLED):
                # The engine reports provider/config failures as EVENTS, not
                # exceptions — chat() yields ERROR ("No provider", auth, network)
                # or PROVIDER_THROTTLED (429/403) and returns normally. If we
                # only watched STREAM_END, run_in_background would see a clean
                # return and mark the run COMPLETED with an empty result. Raise
                # so the run finishes FAILED with the provider's message.
                d = event.data
                msg = d.get("message") if isinstance(d, dict) else str(d)
                raise RuntimeError(
                    f"{event.type.value}: {msg or 'provider call failed'}"
                )
            elif event.type == EventType.STREAM_END and event.data is not None:
                d = event.data
                text = d.get("content", "") if isinstance(d, dict) else str(d)
                if text:
                    final_text.append(text)
        return "\n".join(final_text)

    registry.run_in_background(meta, _runner)
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


def _parse_categories(category: Optional[str]) -> Optional[set[str]]:
    if not category:
        return None
    cats = {c.strip() for c in category.split(",") if c.strip()}
    return cats or None


@router.get("/runs/{run_id}/events")
async def get_agent_run_events(
    run_id: str,
    request: Request,
    since: int = Query(0, ge=0, description="Return events with seq > since (replay cursor)."),
    live: bool = Query(False, description="Keep the connection open and stream new events (SSE)."),
    min_level: str = Query("debug", description="debug|info|warning|error — drop lower severities."),
    category: Optional[str] = Query(None, description="Comma-separated: lifecycle,tool,network,consent,result."),
):
    """Run events (ADR 0003 §11a). Replay (?since=) + optional live tail
    (?live=1), filtered by ?min_level= and ?category=.

    Always persisted; this endpoint just reads/streams. Non-live returns
    the filtered backlog as JSON; live returns an SSE stream that first
    replays the filtered backlog, then tails new events.
    """
    registry = get_agent_run_registry()
    if registry.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id!r}")

    cats = _parse_categories(category)

    if not live:
        backlog = registry.read_events(
            run_id, since=since, min_level=min_level, categories=cats
        )
        return {"events": [e.to_dict() for e in backlog]}

    async def _sse():
        # ORDER MATTERS (lost-event race): subscribe to the live queue
        # FIRST, THEN snapshot the backlog. Any event emitted during/after
        # the backlog read lands in the queue and is delivered after the
        # backlog; the last_seq dedup drops the overlap. If we read the
        # backlog before subscribing, an event emitted in that window would
        # be in neither and be lost forever.
        q = registry.subscribe(run_id)
        last_seq = since

        def _drain_from_disk(after_seq: int):
            """Yield-able list of filtered events on disk after `after_seq`.
            Used for the initial backlog AND for overflow self-heal."""
            return registry.read_events(
                run_id, since=after_seq, min_level=min_level, categories=cats
            )

        try:
            # Initial backlog.
            for ev in _drain_from_disk(last_seq):
                last_seq = max(last_seq, ev.seq)
                yield f"data: {json.dumps(ev.to_dict())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                # Self-heal: if the queue overflowed (slow consumer), the
                # dropped events are still on disk — replay everything after
                # last_seq, then clear the flag and resume the live tail. No
                # silent gap; the durable log is the source of truth.
                if getattr(q, "_ppxai_overflowed", False):
                    q._ppxai_overflowed = False  # type: ignore[attr-defined]
                    for ev in _drain_from_disk(last_seq):
                        last_seq = max(last_seq, ev.seq)
                        yield f"data: {json.dumps(ev.to_dict())}\n\n"
                    continue
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if ev.seq <= last_seq:
                    continue  # already sent (backlog or resync dedup)
                if not ev.passes(min_level=min_level, categories=cats):
                    continue
                last_seq = ev.seq
                yield f"data: {json.dumps(ev.to_dict())}\n\n"
        finally:
            registry.unsubscribe(run_id, q)

    return StreamingResponse(_sse(), media_type="text/event-stream")
