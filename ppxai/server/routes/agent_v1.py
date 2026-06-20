"""v1 gateway: agent runs (ADR 0003 Stage 2 — Increments 1–7).

An *agent run* is a durable, addressable execution of an agent task. This
module is the HTTP surface over `engine.agent_runs.AgentRunRegistry`:

    POST /v1/agent/run            → tool-FREE run (oneshot); {run_id, status}
    POST /v1/agent/task           → tool-CAPABLE, sandboxed run (Inc 4)
    GET  /v1/agent/runs           → list all runs
    GET  /v1/agent/runs/<id>      → fetch one run's meta
    GET  /v1/agent/runs/<id>/events → replay + ?live=1 SSE (Inc 3),
                                    ?since= / ?min_level= / ?category= filters
    POST /v1/agent/runs/<id>/cancel → cooperative cancel (Inc 6)

Execution model: runs execute in the **background** (Inc 2). A POST
validates + builds the provider synchronously (a bad provider 400s up
front), mints the run, fires it into a background `asyncio.Task`, and
returns immediately with `status:"running"`. Poll the meta or tail the
event stream to watch it reach a terminal status (completed / failed /
cancelled / interrupted).

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

Provider choice on `/task` (v1.19.x): ANY configured provider is accepted
(the tier gates by capability, not class — see `_v1_provider_or_400`). But
acceptance is a *plumbing + security* guarantee, NOT a tool-calling-quality
one: the AC-1/AC-2 sandbox enforces identically across providers and across
native-vs-prompt-based tool calling, yet how RELIABLY a given model emits
valid tool calls is per-model. Models without native function calling
(e.g. Perplexity Sonar — `native_tool_calling:false`) fall back to
prompt-based routing and may substitute shell/native-search for granted
tools (see CLAUDE.md "Known Issues" — accepted behavior). For dependable
agentic runs prefer a native-tool-calling model (nvidia/qwen, gemini-3.x,
gpt-5.x, ...). The platform won't stop you pointing `/task` at a weak
tool-caller; it just can't make that model call tools well. (Debt Item 37i.)

Per-run controls on `/task` (Inc 6): an optional `budget`
{iterations, time_s, tokens} stops the run at a clean tool-loop checkpoint
(status `interrupted`, resumable); `POST .../cancel` stops it cooperatively
(status `cancelled`, resumable). Inc 7: a granted `spawn_subagent` tool lets
a top-level run spawn ONE child run (child grant ⊆ parent, child egress ⊆
parent, depth=1, consent-gated) — both runners share `build_task_runner`.

Inc 8a (landed): `/v1/tokens` CRUD over a pluggable secret-source chain
(`server/secrets/`); `server/auth.py` validates against it (credential
layer — see `routes/tokens_v1.py`).

Inc 8b (landed): per-run authz. `start_run` stamps `RunMeta.owner` from
`request.state.principal` (set by the auth middleware). The per-run
endpoints (`GET /runs/<id>`, `/events`, `POST .../cancel`) return 403 to a
caller who is not the run's owner; `GET /runs` is filtered to the caller's
own (+ unowned) runs. No-op when auth is disabled (loopback UX preserved).

Inc 9 (landed): active (non-terminal) runs are mirrored into AppState
`background_agents` (via the registry's on_change hook → SessionManager
broadcast); `GET /state` recomputes it live so a reconnecting client sees
the authoritative active set. This module just creates/finishes runs that
drive that mirror — see `engine/agent_runs.AgentRunRegistry.active_summary`.

The `/v1/` prefix is the stable gateway boundary (see docs/api-gateway.md):
adding optional request fields is non-breaking; removing/repurposing
needs a `/v2`.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...common.logger import get_logger
from ...config.tools import get_agent_config
from ...engine.agent_runs import RunMeta
from ...engine.tools.network_policy import grant_has_shell
from ..state import get_agent_run_registry
# Reuse oneshot's provider construction so Inc 1 has zero provider-wiring
# duplication; the synchronous run IS a oneshot call under the hood.
from .oneshot import _build_provider

logger = get_logger("server")


# ---------------------------------------------------------------------------
# Agent-tier system prompt (v1.19.x) — bounded-agent framing
# ---------------------------------------------------------------------------
# /v1/agent/task drives a sandboxed, capability-granted run. Left to the
# provider's CHAT system prompt, some models behave wrong for an agent task —
# notably Perplexity Sonar, whose config prompt steers it toward NATIVE web
# search instead of the granted tools (CLAUDE.md Known Issues). This default
# framing replaces that with bounded-agent instructions so a tool-capable run
# uses the GRANTED tools and doesn't substitute native capabilities.
#
# It's a DEFAULT, not a lock-in: a caller's `system` (e.g. ppxai-sre's
# rendered AGENT.md — Identity/Role/Boundaries) is composed ON TOP via
# `compose_agent_system_prompt`, and the tool-calling mechanics block is still
# appended by the engine. Ownership stays with the consumer (the AGENT.md /
# persona artifact lives in ppxai-sre); ppxai provides the seam + a sane base.
DEFAULT_AGENT_SYSTEM_PROMPT = (
    "You are an autonomous agent executing a single bounded task. "
    "Use ONLY the tools you have been granted to accomplish it — do not ask "
    "the user for input, and do not fall back to any native capability "
    "(e.g. built-in web search) when a granted tool covers the need. "
    "When you need an action, emit a tool call in the required format rather "
    "than describing what you would do. Work within your capability grant and "
    "egress allowlist; if the task cannot be done with the granted tools, say "
    "so plainly and stop. Be concise; report results, not intentions."
)


def compose_agent_system_prompt(caller_system: Optional[str]) -> str:
    """Build the /task engine system prompt: the bounded-agent default, plus
    the caller-supplied `system` (rendered AGENT.md / persona) when present.

    The caller's instructions come SECOND so they refine/extend the base
    framing (identity, role, boundaries) without losing the
    use-only-granted-tools guarantee. Returns the default alone when the
    caller passes nothing."""
    base = DEFAULT_AGENT_SYSTEM_PROMPT
    extra = (caller_system or "").strip()
    return f"{base}\n\n{extra}" if extra else base


# ---------------------------------------------------------------------------
# Per-run authorization (Inc 8b)
# ---------------------------------------------------------------------------
# The auth MIDDLEWARE (server/auth.py) already authenticated the caller and
# stashed the resolved TokenRecord on request.state.principal. This layer
# adds AUTHORIZATION: only the run's owner may read/cancel a given run.
#
# Rules:
# - Auth disabled (no principal on the request) => no per-run scoping. Runs
#   are created unowned (owner=None) and every read is allowed. Preserves the
#   loopback/desktop UX exactly (matches the empty-store/env-unset model).
# - Auth enabled => the run is stamped with the creator's owner. A read is
#   allowed iff caller.owner == run.owner. A run with owner=None (created
#   before auth was on, or a sub-agent) is readable by any AUTHENTICATED
#   caller — it is never broadened to unauthenticated access.


def _caller_owner(request: Request) -> Optional[str]:
    """Owner string of the authenticated principal, or None when auth is off.

    Tolerates a request without a ``state`` (e.g. hand-built test doubles or
    a path that bypassed the auth middleware) — that simply means no
    authenticated principal."""
    state = getattr(request, "state", None)
    principal = getattr(state, "principal", None) if state is not None else None
    return getattr(principal, "owner", None) if principal is not None else None


def _authorize_run_access(request: Request, meta: RunMeta) -> None:
    """Raise 403 unless the caller may access this run.

    No-op when auth is disabled (caller owner is None AND the run is
    unowned). When the run has an owner, the caller must match it.
    """
    caller = _caller_owner(request)
    if caller is None:
        # Auth disabled for this request. (If auth WERE enabled the
        # middleware would have rejected an unauthenticated caller before
        # reaching here, so a None caller means the server is open.)
        return
    if meta.owner is None:
        # Unowned run (pre-8b or sub-agent): any authenticated caller may read.
        return
    if meta.owner != caller:
        raise HTTPException(
            status_code=403,
            detail=f"Run {meta.run_id!r} is not owned by the authenticated caller.",
        )


def _v1_provider_or_400(provider_name: str):
    """Build the provider for a v1 agent run.

    v1.19.x: gates by CAPABILITY, not provider class. Both v1 agent tiers
    need only methods every `BaseProvider` implements — `/v1/agent/task`
    drives `engine.chat()` (abstract on BaseProvider; all providers have it)
    and `/v1/agent/run` drives `provider.oneshot()` (now abstract on
    BaseProvider too — implemented on every provider). So any buildable
    provider is accepted; the old `isinstance(OpenAICompatibleProvider)`
    check was rejecting native openai/gemini/perplexity for a method
    (`oneshot`) the tier either doesn't call (`/task`) or that they now
    have (`/run`). `_build_provider` still raises 400 on unknown provider /
    missing key."""
    return _build_provider(provider_name)

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
    owner: Optional[str] = None  # Inc 8b: principal that owns the run
    provider: Optional[str] = None
    model: Optional[str] = None
    tools: list[str] = Field(default_factory=list)
    network: list = Field(default_factory=list)
    budget: dict = Field(default_factory=dict)
    resumable: bool = False
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
            owner=getattr(m, "owner", None),
            provider=m.provider,
            model=m.model,
            tools=list(m.tools),
            network=list(getattr(m, "network", []) or []),
            budget=dict(getattr(m, "budget", {}) or {}),
            resumable=bool(getattr(m, "resumable", False)),
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
async def create_agent_run(req: AgentRunRequest, request: Request) -> AgentRunResponse:
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

    # Build the provider BEFORE minting/backgrounding so an UNBUILDABLE
    # provider (unknown name / missing key) fails fast with 400 and creates no
    # run. v1.19.x: any buildable provider is accepted (gates by capability,
    # not class — see _v1_provider_or_400).
    provider = _v1_provider_or_400(provider_name)

    meta = registry.start_run(
        task=req.task, tools=req.tools, provider=provider_name, model=model,
        owner=_caller_owner(request),
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


class NetworkSpec(BaseModel):
    """Egress allowlist spec — ADR 0003 §11 `network{allow_outbound[]}`.

    `allow_outbound` entries are either a bare host string (exact host, any
    path) or an object `{host, paths?}` where `host` may be `*.suffix` for a
    single-label suffix-anchored glob and `paths` is a list of path prefixes.

    Defined BEFORE AgentTaskRequest so the latter can reference it directly
    (not as a string forward-ref) — that avoids needing
    `model_rebuild()`/`update_forward_refs()`, which differ between Pydantic
    v1 and v2 and would otherwise couple this module to a specific Pydantic
    major at import time.
    """

    allow_outbound: list = Field(
        default_factory=list,
        description="Allowed outbound rules; empty = no outbound (fail-closed).",
    )


class BudgetSpec(BaseModel):
    """Per-run resource caps (Inc 6). Defined before AgentTaskRequest so it's
    referenced directly (no forward-ref / model_rebuild — Pydantic v1/v2 safe).

    Each field is optional; an absent cap means unbounded on that axis. Caps
    are enforced cooperatively at tool-loop boundaries, so a stop lands at a
    clean checkpoint (status='interrupted', resumable)."""

    iterations: Optional[int] = Field(None, ge=1, description="Max tool-loop iterations.")
    time_s: Optional[float] = Field(None, gt=0, description="Max wall-clock seconds.")
    tokens: Optional[int] = Field(
        None, ge=1,
        description=(
            "Max tokens consumed. Best-effort: checked at tool-loop boundaries, "
            "so a non-tool-calling run (one large completion) may finish before "
            "the cap is observed. Use time_s/iterations for hard stops."
        ),
    )


def _budget_dict(spec: "Optional[BudgetSpec]") -> dict:
    """Budget spec -> plain {axis: cap} dict, omitting unset axes. Built field
    by field so it works on Pydantic v1 and v2 (no model_dump/.dict coupling)."""
    if spec is None:
        return {}
    out: dict = {}
    if spec.iterations is not None:
        out["iterations"] = spec.iterations
    if spec.time_s is not None:
        out["time_s"] = spec.time_s
    if spec.tokens is not None:
        out["tokens"] = spec.tokens
    return out


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
    budget: Optional[BudgetSpec] = Field(
        None,
        description=(
            "Per-run resource caps (Inc 6). Any subset of "
            "{iterations, time_s, tokens}; an absent key = no cap on that axis. "
            "Checked cooperatively at each tool-loop boundary — a run that hits "
            "a cap stops at a clean checkpoint with status='interrupted' "
            "(resumable), not 'failed'."
        ),
    )
    network: Optional[NetworkSpec] = Field(
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


@router.post("/task", response_model=AgentRunResponse)
async def create_agent_task(req: AgentTaskRequest, request: Request) -> AgentRunResponse:
    """Tool-capable, sandboxed agent run (ADR 0003 §4 / AC-1).

    The tool-calling tier, separate from the safe tool-free /v1/agent/run.
    The run executes via `chat_with_tools` through a `ScopedToolManager`
    that exposes ONLY the granted tools to the model and hard-denies any
    off-grant `execute_tool` (emitting a `tool_denied` event). Shares the
    run registry / events / monitor infra with /run.
    """
    # The tool-capable tier ships DEFAULT-OFF (v1.19.0). It is sandboxed
    # in-process only (no OS isolation; ADR 0003 tier-d deferred) and is safe
    # ONLY for trusted operators (threat model A). An operator must opt in
    # explicitly — that toggle IS the "trusted operator" gate. The tool-free
    # tiers (/v1/agent/run, /v1/oneshot) are always available.
    if not get_agent_config().get("task_tier_enabled", False):
        raise HTTPException(
            status_code=403,
            detail=(
                "The tool-capable agent tier (/v1/agent/task) is disabled. It is "
                "sandboxed in-process only and intended for trusted operators; "
                "enable it deliberately via tools.agent.task_tier_enabled=true in "
                "ppxai-config.json. The tool-free tier (/v1/agent/run) is always "
                "available."
            ),
        )

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

    _v1_provider_or_400(provider_name)

    meta = registry.start_run(
        task=req.task, tools=req.tools, provider=provider_name, model=model,
        network=(req.network.allow_outbound if req.network else []),
        budget=_budget_dict(req.budget),
        owner=_caller_owner(request),
    )

    runner = build_task_runner(
        registry,
        provider_name=provider_name,
        model=model,
        task=req.task,
        tools=list(req.tools),
        allow_outbound=(req.network.allow_outbound if req.network else []),
        allow_spawn=True,  # top-level run may spawn ONE child (depth=1; Inc 7)
        system=req.system,  # v1.19.x: caller's agent framing (rendered AGENT.md)
    )
    registry.run_in_background(meta, runner)
    return AgentRunResponse(run_id=meta.run_id, status=meta.status)


def build_task_runner(
    registry,
    *,
    provider_name: str,
    model: str,
    task: str,
    tools: list[str],
    allow_outbound: list,
    allow_spawn: bool = False,
    system: Optional[str] = None,
):
    """Build the async runner that drives a tool-capable run (Inc 4–7).

    Shared by `/v1/agent/task` (top-level) and the `spawn_subagent` tool
    (child run) so both go through the IDENTICAL sandbox: ScopedToolManager
    (AC-1 grant), NetworkPolicy (AC-2 egress), and Inc 6 budget/cancel
    control. The runner is a function of explicit params, not the request, so
    a child run can be built with its own (subset) grant + allowlist.

    allow_spawn gates depth: a top-level run gets the `spawn_subagent` tool
    registered IF it's in the grant; a child run is always built with
    allow_spawn=False, so it can never spawn — enforcing the N=1 / depth=1
    rule structurally (a grandchild is impossible).
    """
    async def _runner(m) -> str:
        from ...engine.client import EngineClient
        from ...engine.agent_scoped_tools import ScopedToolManager
        from ...engine.tools.network_policy import NetworkPolicy
        from ...engine.tools.agent_spawn import SpawnSubagentTool
        from ...engine.types import EventType

        engine = EngineClient()
        engine.set_provider(provider_name)
        engine.set_model(model)
        engine.enable_tools()  # registers builtins + sets tool-loop limits
        # v1.19.x: bounded-agent framing (+ caller's rendered AGENT.md via
        # `system`) REPLACES the provider's chat system_prompt for this run, so
        # the model uses granted tools instead of native fallbacks. Set on this
        # per-run engine only (D1 isolation) — never touches other sessions.
        engine.system_prompt_override = compose_agent_system_prompt(system)

        # Inc 7: register spawn_subagent ONLY for a top-level run whose grant
        # includes it. A child run (allow_spawn=False) never gets the tool, so
        # depth is capped at 1 structurally — not by a runtime check the model
        # could probe. The tool carries this run as the parent context and
        # enforces child grant ⊆ this grant, child egress ⊆ this allowlist.
        if allow_spawn and "spawn_subagent" in tools:
            # Adapt the engine's shell-consent (summary, cwd) to the spawn
            # tool's single-arg (summary) contract — a spawn has no cwd, so we
            # don't pass a meaningless "." that a consent UI might display.
            async def _spawn_consent(summary: str) -> bool:
                return await engine.request_shell_consent(summary)

            # Server-context spawn consent policy (tools.agent.spawn_consent):
            # "deny" (default, safe) | "auto" (allow API-driven spawns; subset
            # rules remain the boundary). There's no interactive consent
            # channel over /v1/agent/task, so without "auto" a spawn is refused.
            spawn_consent = (get_agent_config().get("spawn_consent") or "deny")
            engine.tool_manager.register_tool(SpawnSubagentTool(
                registry=registry,
                parent_run_id=m.run_id,
                parent_owner=getattr(m, "owner", None),
                parent_tools=list(tools),
                parent_allow_outbound=list(allow_outbound),
                parent_provider=provider_name,
                parent_model=model,
                request_consent=_spawn_consent,
                consent_policy=spawn_consent,
            ))

        def _on_deny(name: str) -> None:
            registry.emit_event(
                m.run_id, "tool_denied", level="warning", category="tool",
                data={"tool": name, "grant": list(tools)},
            )

        # AC-2: per-run egress allowlist. Always installed for a tool-capable
        # run — even with no `network` spec, so a granted network tool is
        # deny-by-default (fail-closed). on_network emits the typed audit event.
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
            engine.tool_manager, list(tools), on_deny=_on_deny,
            network_policy=net_policy, on_network=_on_network,
        )

        # Inc 6: cooperative budget/cancel control. Polled at each tool-loop
        # boundary (on TOOL_CALL) so a cap or cancel stops the run at a clean
        # checkpoint — never mid-tool-call. control.check() raises RunCancelled
        # / RunBudgetExceeded, which run_in_background maps to the right status.
        control = registry.get_control(m.run_id)

        final_text: list[str] = []
        async for event in engine.chat(task, stream=False):
            # Surface tool activity on the run's event stream. The engine's
            # TOOL_CALL carries the name in event.data["tool"] (a dict), not
            # in metadata; STREAM_END carries the final text as event.data,
            # which is a plain string (sometimes a dict with "content").
            if event.type == EventType.TOOL_CALL:
                if control is not None:
                    # Refresh the run's cumulative token total from the engine
                    # before checking, so the token budget is actually enforced
                    # (not just iterations/time). This EngineClient is run-local
                    # (D1: one per run), so session.usage.total_tokens IS this
                    # run's total. Then check() — BEFORE counting this iteration:
                    # a budget of N lets N iterations run, stops at the (N+1)th.
                    try:
                        control.tokens_used = engine.session.usage.total_tokens
                    except AttributeError:
                        pass  # usage not available — leave token axis unenforced
                    control.check(now=time.monotonic())
                    control.iterations += 1
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

    return _runner


@router.get("/runs", response_model=RunListResponse)
async def list_agent_runs(request: Request) -> RunListResponse:
    """List agent runs, newest first.

    Owner-scoped (Inc 8b): when auth is enabled, only the caller's own runs
    (plus unowned runs) are returned — a bearer holder must not enumerate
    another owner's runs. When auth is disabled the full list is returned
    (loopback UX)."""
    registry = get_agent_run_registry()
    caller = _caller_owner(request)
    runs = registry.list_runs()
    if caller is not None:
        runs = [m for m in runs if m.owner is None or m.owner == caller]
    return RunListResponse(
        runs=[RunMetaResponse.from_meta(m) for m in runs]
    )


@router.get("/runs/{run_id}", response_model=RunMetaResponse)
async def get_agent_run(run_id: str, request: Request) -> RunMetaResponse:
    """Fetch one run's meta, or 404. Owner-scoped (Inc 8b): 403 if the
    authenticated caller doesn't own the run."""
    registry = get_agent_run_registry()
    meta = registry.get_run(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id!r}")
    _authorize_run_access(request, meta)
    return RunMetaResponse.from_meta(meta)


@router.post("/runs/{run_id}/cancel")
async def cancel_agent_run(run_id: str, request: Request) -> dict:
    """Request cooperative cancellation of an in-flight run (Inc 6).

    Flips the run's control flag and moves it to `cancelling`; the runner
    observes it at its next tool-loop boundary and stops at a clean
    checkpoint (status → `cancelled`, resumable). Returns 404 if the run is
    unknown, 403 if the caller doesn't own it (Inc 8b), 409 if it's already
    terminal (nothing to cancel)."""
    registry = get_agent_run_registry()
    meta = registry.get_run(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id!r}")
    _authorize_run_access(request, meta)
    if registry.cancel_run(run_id):
        return {"ok": True, "run_id": run_id, "status": "cancelling"}
    # Not in flight — already terminal (or never started).
    raise HTTPException(
        status_code=409,
        detail=f"Run {run_id!r} is not cancellable (status={meta.status!r}).",
    )


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
    _meta = registry.get_run(run_id)
    if _meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id!r}")
    _authorize_run_access(request, _meta)  # Inc 8b: owner-scoped (403)

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
