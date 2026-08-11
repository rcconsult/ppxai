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
    POST /v1/agent/runs/<id>/respond → answer a `waiting` park (T5),
                                    token-checked + owner-scoped
    POST /v1/agent/runs/<id>/ack  → collect a held result (T6):
                                    completed_pending_ack → finalized
    POST /v1/agent/runs/<id>/resume → conditionally continue an
                                    interrupted/cancelled run (T7)

Execution model: runs execute in the **background** (Inc 2). A POST
validates + builds the provider synchronously (a bad provider 400s up
front), mints the run, fires it into a background `asyncio.Task`, and
returns immediately with `status:"running"`. Poll the meta or tail the
event stream to watch it reach a terminal status (completed / failed /
cancelled / interrupted). T6: a successful TOP-LEVEL `/task` run lands in
`completed_pending_ack` — the run has exited but its result is HELD until
`POST .../ack` collects it (→ `finalized`), so a disconnected UI never
loses a result; `execution.task.budgets.result_retention_s` is the lazy-reaped
GC backstop. The tool-free `/run` tier and sub-agent children still land
`completed` (their caller/parent collects inline).

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
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from ...common.logger import get_logger
from ...config import get_default_model
from ...config.execution import (
    get_execution_default_subagent,
    get_execution_task_config,
)
from ...config.tools import get_tool_config
from ...engine.agent_runs import RunMeta, resume_refusal
from ...engine.agent_skill import AgentSkillError, LoadedSkill, load_skill
from ...engine.agent_spec import (
    AgentSpec,
    AgentSpecError,
    load_spec_file,
    spec_from_mapping,
)
from ...engine.tools.network_policy import (
    apply_egress_ceiling,
    grant_has_shell,
)
from ...engine import task_authorizer as _authz
from ...engine.task_authorizer import (
    TaskAuthorizationError,
    TaskRequest,
    authorize_oneshot,
    authorize_task,
)
from ...engine import task_runner as _task_runner
from ...engine.task_runner import (  # noqa: F401  (compat re-exports)
    DEFAULT_AGENT_SYSTEM_PROMPT,
    compose_agent_system_prompt,
)
# Import alias for source compatibility (oneshot.py and older callers do
# `from .agent_v1 import build_task_runner`). NOT a patch point: it is a
# second binding to the same object, so rebinding it redirects nothing.
# Patch `ppxai.engine.task_runner.build_task_runner` instead — see that
# module's docstring and tests/test_runner_builder_patch_point.py.
from ...engine.task_runner import build_task_runner  # noqa: F401
from ..state import get_agent_run_registry
# Reuse oneshot's provider construction so Inc 1 has zero provider-wiring
# duplication; the synchronous run IS a oneshot call under the hood.
from .oneshot import (
    ONESHOT_SEARCH_ITERATIONS,
    _build_provider,
    _validate_provider_or_400,
    _web_search_egress_hosts,
)

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
# MOVED to ppxai/engine/task_runner.py in v1.19.1, alongside the runner
# that consumes it — pure string composition with no HTTP shape, and
# leaving it here made the engine module import from the server layer.
# Re-exported at the imports above for existing importers.



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
            "Recorded on the run for provenance only — NEVER executed and "
            "NEVER widens the grant. /v1/agent/run's effective grant is "
            "config-decided (U3, ADR 0011): {} by default, {web_search} when "
            "execution.run.web_search is on. For an explicit tool grant, use "
            "POST /v1/agent/task."
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
    # ADR 0011 (F1): "task" | "oneshot" run-kind discriminator. Additive —
    # legacy metas surface as "task".
    kind: str = "task"
    parent_run_id: Optional[str] = None
    owner: Optional[str] = None  # Inc 8b: principal that owns the run
    provider: Optional[str] = None
    model: Optional[str] = None
    tools: list[str] = Field(default_factory=list)
    network: list = Field(default_factory=list)
    budget: dict = Field(default_factory=dict)
    resumable: bool = False
    # T5: consent-park context while status == "waiting" — {kind, prompt,
    # token, since, expires_at, ttl_s}. Owner-scoped reads only, and the
    # owner IS the principal entitled to answer, so surfacing the resume
    # token here is deliberate (it's what the consent card / `/task respond`
    # presents back to POST .../respond).
    waiting: Optional[dict] = None
    # T6: when the held result was collected (/ack) or retention-reaped;
    # None until the run is finalized.
    acked_at: Optional[float] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None
    # v1.19.x workdir-alignment: the run's effective working dir (per-run
    # intent; None = server default or a sealed run's jail).
    workdir: Optional[str] = None

    @classmethod
    def from_meta(cls, m: RunMeta) -> "RunMetaResponse":
        return cls(
            run_id=m.run_id,
            task=m.task,
            status=m.status,
            kind=getattr(m, "kind", "task") or "task",
            parent_run_id=m.parent_run_id,
            owner=getattr(m, "owner", None),
            provider=m.provider,
            model=m.model,
            tools=list(m.tools),
            network=list(getattr(m, "network", []) or []),
            budget=dict(getattr(m, "budget", {}) or {}),
            resumable=bool(getattr(m, "resumable", False)),
            waiting=getattr(m, "waiting", None),
            acked_at=getattr(m, "acked_at", None),
            created_at=m.created_at,
            started_at=m.started_at,
            finished_at=m.finished_at,
            result=m.result,
            error=m.error,
            workdir=getattr(m, "workdir", None),
        )


class AgentRunResponse(BaseModel):
    """Immediate reply to POST /v1/agent/run."""

    run_id: str
    status: str
    # v1.19.x workdir-alignment: True when the request carried a `workdir`
    # but the filesystem seal is ON — the run keeps its per-run jail and the
    # client should surface a warning. Absent/False otherwise.
    workdir_ignored: bool = False


class RunListResponse(BaseModel):
    runs: list[RunMetaResponse]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/run", response_model=AgentRunResponse)
async def create_agent_run(req: AgentRunRequest, request: Request) -> AgentRunResponse:
    """Create a `kind=oneshot` run and execute it in the background.

    U3 (ADR 0011): this is the `/run` UX launch. Grant rule — one brain
    with the /v1/oneshot facade: `{}` by default, `{web_search}` when
    `execution.run.web_search` is on (same egress baseline, same small
    iteration budget). The request CANNOT widen the grant: `req.tools`
    stays provenance-only and is never executed.

    Validation + provider build happen synchronously (so a bad provider
    still gets a 400 up front), then the run is fired into a background
    task and the POST returns immediately with status='running'. Poll
    GET /v1/agent/runs/<id> to watch it flip. A successful run HOLDS its
    result (T6, `completed_pending_ack`) until collected — same UX
    contract as /task; U4 maps `execution.collect` onto this.
    """
    registry = get_agent_run_registry()

    # ADMISSION. Same boundary /task uses; the `kind="oneshot"` row supplies
    # the differences (no tier gate, config-decided grant, no client fallback
    # for provider/model). Provider/model stays PER-RUN INJECTED INTENT
    # (ADR 0003 §9) — the interactive session's provider is deliberately not
    # consulted, which the tier row encodes as honors_client_fallback=False.
    # NOTE: per-session sub-agent config + a /subagent slash command, both
    # persisted in the session checkpoint, are a later increment (debt-filed);
    # they will slot in as a layer between request and global config there.
    try:
        auth = authorize_oneshot(
            req.task,
            provider=req.provider,
            model=req.model,
            system=req.system,
        )
    except TaskAuthorizationError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)

    # Build the provider BEFORE minting/backgrounding so an UNBUILDABLE
    # provider (unknown name / missing key) fails fast with 400 and creates no
    # run. v1.19.x: any buildable provider is accepted (gates by capability,
    # not class — see _v1_provider_or_400).
    provider = _v1_provider_or_400(auth.provider)

    # U4 (ADR 0011): execution.collect drives the T6 hold. "yes" → hold
    # until collected; "auto"/"no" → auto-finalize (the watching client
    # merges on "auto"; "no" offers no merge path at all).
    hold = _collect_holds()

    # U3 grant rule (config-decided, never request-decided): web_search on
    # → the run goes through the FULL task-tier sandbox with the hardwired
    # {web_search} grant + built-in backend hosts + the operator's
    # tools.web_search.egress baseline; off → plain closed-book LLM call.
    # `auth.tools` IS that decision, already capped by the Q3 ceiling.
    if auth.tools:
        meta = registry.start_run(
            task=auth.task, kind="oneshot", tools=list(auth.tools),
            provider=auth.provider, model=auth.model,
            network=list(auth.network),
            budget=dict(auth.budget),
            owner=_caller_owner(request),
            hold_result=hold,
            system=auth.system,
        )
        runner = _task_runner.build_task_runner(
            registry,
            provider_name=auth.provider,
            model=auth.model,
            task=auth.task,
            tools=list(auth.tools),
            allow_outbound=list(auth.network),
            allow_spawn=False,  # consent/park path structurally unreachable
            system=auth.system,
        )
        registry.run_in_background(meta, runner)
        return AgentRunResponse(run_id=meta.run_id, status=meta.status)

    meta = registry.start_run(
        task=auth.task, kind="oneshot", tools=req.tools,
        provider=auth.provider, model=auth.model,
        owner=_caller_owner(request),
        hold_result=hold,  # same execution.collect contract as the grant path
    )

    async def _runner(m) -> str:
        # provider.oneshot is blocking I/O — run it off the event loop so
        # other requests (e.g. GET status polls) aren't starved.
        result = await asyncio.to_thread(
            provider.oneshot, prompt=auth.task, model=auth.model,
            system=auth.system,
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
        default_factory=list,
        description=(
            "Capability grant — the ONLY tools this run may call. Required + "
            "non-empty UNLESS a `spec` supplies it (T3): a request with neither "
            "tools nor spec is rejected 422; a spec that yields an empty grant "
            "is rejected 400 post-merge."
        ),
    )
    spec: Optional[str] = Field(
        None,
        description=(
            "T3: name of a spec file under execution.task.sandbox.specs_dir "
            "(NAME only — no path, no traversal). Its fields fill any request "
            "field left unset; explicit request fields always win. The merged "
            "grant is clamped by the same ceiling as a direct request "
            "(no-shell, execution.task.enabled)."
        ),
    )
    skills: list[str] = Field(
        default_factory=list,
        description=(
            "T4: names of skill directories under "
            "execution.task.sandbox.skills_dir "
            "(NAME only — no path, no traversal). Each skill's SKILL.md is a spec "
            "(T3 loader) and its directory is mounted into the run's read-scope. "
            "Multiple skills compose (tool grants union, read roots union); the "
            "merged grant faces the same ceiling as a direct request. A skill "
            "that requires scripts/ is refused unless allow_skill_scripts is on "
            "(scripts stay inert until the container tier)."
        ),
    )
    profile: Optional[str] = Field(
        None,
        description=(
            "ADR 0009 §1 (step ③): name of an execution profile under "
            "execution.profiles in ppxai-config.json — a named, reusable, "
            "AgentSpec-shaped grant. Precedence: request > spec > profile > "
            "default_subagent > built-in default; list fields (tools, "
            "network) REPLACE, so a more specific layer can narrow. Unknown "
            "name → 400 (pre-start)."
        ),
    )
    enrichment: Optional[bool] = Field(
        None,
        description=(
            "ADR 0009 §3/§5: tri-state context-enrichment intent. Resolved "
            "through the same precedence chain as provider/model; effective "
            "true derives web_search + its egress baseline AFTER resolution. "
            "Absent = inherit from spec/skill/profile; default false."
        ),
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
    workdir: Optional[str] = Field(
        None,
        description=(
            "Working directory for the run's relative tool paths — per-run "
            "intent like provider/model (clients thread their session "
            "working dir; `--work-dir` overrides). Honored ONLY while the "
            "filesystem seal is OFF: a sealed run keeps its per-run jail and "
            "the response flags `workdir_ignored`. Absent = the server "
            "default (`server.working_dir` config, else home) — never the "
            "server process launch dir. Must exist (400 otherwise)."
        ),
    )

    @model_validator(mode="after")
    def _grant_required_without_spec(self) -> "AgentTaskRequest":
        # Preserve the /task invariant "a tool-capable run can never go tool-free
        # by accident" (422) — but let a spec, skill, or profile supply the
        # grant (step ③ adds profile; enrichment:true also derives one). With
        # any grant source, the non-empty check happens post-merge in the
        # route (400). Without one, an empty/absent grant is a request-shape
        # error here.
        #
        # Item 58: a configured, operator-enabled `execution.task.default_grant`
        # is ALSO a grant source — a bare `/task` then resolves its grant from
        # the user's standing default (merged + clamped in the authorizer)
        # instead of 422-ing here. When no default is configured, or the
        # operator set `allow_user_default:false`, the historical 422 stands
        # (fail-closed). The authorizer's post-merge non-empty check remains the
        # final authority; this only decides whether to defer to it.
        if (not self.spec and not self.skills and not self.tools
                and not self.profile and self.enrichment is not True
                and not _has_usable_task_default_grant()):
            raise ValueError(
                "a tool-capable /task run needs an explicit tool grant: pass "
                "`--tools web_search` (or `--tools a,b,c`), or a "
                "`--spec`/`--skill`/`--profile` that supplies one. For a "
                "tool-free answer use /run instead."
            )
        return self


# --- T3/T4 + grant/egress helpers: ONE implementation, in the engine -------
#
# These used to be defined here, which is exactly how the in-process clients
# ended up on a weaker path (they could not import a route module). They now
# live in `engine/task_authorizer.py`; the names below stay as delegating
# aliases because tests and `create_agent_run` still reach for them, and a
# second copy would be the very drift this change removes.
#
# The two that raise map the engine's `TaskAuthorizationError` onto HTTP —
# that translation is the only thing this layer legitimately owns.

_reject_unsafe_name = _authz.reject_unsafe_name
_within_root = _authz.within_root
_LAYER_RANK = _authz._LAYER_RANK
_web_search_banned = _authz.web_search_banned
_with_tool_egress_defaults = _authz.with_tool_egress_defaults
_enrichment_survives_ceiling = _authz.enrichment_survives_ceiling


def _apply_ceiling_or_400(network: list) -> tuple[list, list]:
    """`apply_egress_ceiling` at the trust boundary, as an HTTP 400."""
    try:
        return _authz.apply_ceiling_or_error(network)
    except TaskAuthorizationError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)


def _has_usable_task_default_grant() -> bool:
    """Item 58: does an operator-enabled `execution.task.default_grant` supply
    a grant a bare `/task` could resolve? Gates whether the request-shape 422
    defers to the authorizer's post-merge check. A default with no `tools` (or
    `allow_user_default:false`, or none configured) is not a usable grant
    source, so the 422 stands. Config errors resolve to "no default" — the
    validator must never fail open on an unreadable config.
    """
    try:
        from ...config.execution import (
            get_execution_task_allow_user_default,
            get_execution_task_default_grant,
        )

        if not get_execution_task_allow_user_default():
            return False
        grant = get_execution_task_default_grant()
        return bool(grant.get("tools"))
    except Exception:
        return False


def _collect_holds() -> bool:
    """U4 (ADR 0011): does execution.collect map to a T6 hold at launch?

    "yes" → hold_result=True (held until collected); "auto"/"no" →
    hold_result=False (auto-finalize — on "auto" the watching client
    merges, on "no" no merge path exists). Config errors fall back to the
    shipped default ("yes" — hold)."""
    from ...config.execution import get_execution_collect

    try:
        return get_execution_collect() == "yes"
    except Exception:
        return True



def _enriched_oneshot_egress_or_400(provider_name: Optional[str] = None) -> list:
    """HTTP adapter over `task_authorizer.enriched_oneshot_egress_or_error`.

    The assembly itself lives in the engine so `/v1/agent/run`, the
    `/v1/oneshot` facade and any in-process caller share ONE copy — this
    function only maps the engine's `TaskAuthorizationError` onto HTTP. Used
    by the facade (`oneshot.py`); `create_agent_run` reaches the same logic
    through `authorize_oneshot`.
    """
    try:
        return _authz.enriched_oneshot_egress_or_error(provider_name)
    except TaskAuthorizationError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)


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
    # ADMISSION: every gate for this tier lives in the engine's authorizer, so
    # the in-process clients (TUIs, SDK embedders) cannot be a weaker path to
    # the same runner — the T8b bug this route used to own alone. Statuses and
    # detail text are the authorizer's; this route only translates them onto
    # HTTP. See ppxai/engine/task_authorizer.py.
    try:
        auth = authorize_task(
            TaskRequest(
                task=req.task,
                tools=list(req.tools),
                spec=req.spec,
                skills=list(req.skills),
                profile=req.profile,
                enrichment=req.enrichment,
                provider=req.provider,
                model=req.model,
                system=req.system,
                budget=_budget_dict(req.budget),
                # None = "not stated" (inherit); [] = "stated: no egress".
                # Collapsing the two would let a deliberately egress-free
                # request inherit a spec's allowlist.
                network=(
                    list(req.network.allow_outbound)
                    if req.network is not None
                    else None
                ),
                workdir=req.workdir,
            )
        )
    except TaskAuthorizationError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)

    registry = get_agent_run_registry()
    eff = {
        "task": auth.task, "tools": auth.tools, "system": auth.system,
        "budget": auth.budget, "network": auth.network,
        "read_roots": auth.read_roots,
    }
    tools = auth.tools
    provider_name = auth.provider
    model = auth.model
    workdir = auth.workdir
    workdir_ignored = auth.workdir_ignored

    meta = registry.start_run(
        task=eff["task"], kind="task", tools=tools,
        provider=provider_name, model=model,
        network=eff["network"],
        budget=eff["budget"],
        owner=_caller_owner(request),
        # T6 two-phase termination: a top-level /task run HOLDS its result
        # (completed_pending_ack) until POST .../ack collects it, so a
        # disconnected UI never loses it. Sub-agent children don't hold —
        # the awaiting parent is their collector. U4: execution.collect
        # maps onto the hold ("yes" → hold; "auto"/"no" → auto-finalize).
        hold_result=_collect_holds(),
        # T7: persist the remaining runner inputs so POST .../resume can
        # rebuild the scoped runner faithfully after an interrupt/restart.
        system=eff["system"],
        read_roots=eff["read_roots"],
        workdir=workdir,
    )

    runner = _task_runner.build_task_runner(
        registry,
        provider_name=provider_name,
        model=model,
        task=eff["task"],
        tools=list(tools),
        allow_outbound=eff["network"],
        allow_spawn=True,  # top-level run may spawn ONE child (depth=1; Inc 7)
        system=eff["system"],  # request or spec: caller's agent framing (AGENT.md)
        extra_read_paths=eff["read_roots"],  # T4: mounted --skill dirs
        workdir=workdir,
    )
    registry.run_in_background(meta, runner)
    return AgentRunResponse(
        run_id=meta.run_id, status=meta.status, workdir_ignored=workdir_ignored
    )




@router.get("/runs", response_model=RunListResponse)
async def list_agent_runs(
    request: Request, kind: Optional[str] = None
) -> RunListResponse:
    """List agent runs, newest first.

    Owner-scoped (Inc 8b): when auth is enabled, only the caller's own runs
    (plus unowned runs) are returned — a bearer holder must not enumerate
    another owner's runs. When auth is disabled the full list is returned
    (loopback UX).

    ADR 0011 (F1): optional `?kind=task|oneshot` filter — each command
    family lists only its own runs (legacy metas count as "task")."""
    if kind is not None and kind not in ("task", "oneshot"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown kind {kind!r} — expected 'task' or 'oneshot'.",
        )
    registry = get_agent_run_registry()
    caller = _caller_owner(request)
    # T6: lazy retention backstop — an expired completed_pending_ack hold is
    # finalized the next time anyone lists the runs (no timer task).
    retention = float(
    get_execution_task_config()["budgets"]["result_retention_s"]
)
    runs = [registry.maybe_reap_hold(m, retention) for m in registry.list_runs()]
    if caller is not None:
        runs = [m for m in runs if m.owner is None or m.owner == caller]
    if kind is not None:
        runs = [m for m in runs if (getattr(m, "kind", "task") or "task") == kind]
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
    # T6: single-run lazy reap (already-loaded meta — no extra disk read).
    retention = float(
    get_execution_task_config()["budgets"]["result_retention_s"]
)
    meta = registry.maybe_reap_hold(meta, retention)
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


class RespondRequest(BaseModel):
    """Answer a `waiting` park (T5). At least one of `approved`/`text` must be
    present. For a consent park (`waiting.kind == "consent"`), only
    `approved: true` approves — a text-only answer is treated as a denial with
    a message (fail-closed); `text` becomes first-class when an ask-user
    `waiting{input}` park lands."""

    token: str = Field(
        ..., min_length=1,
        description="Resume token from the run's waiting.token / agent_waiting event.",
    )
    approved: Optional[bool] = Field(
        None, description="Consent decision (true approves, false denies)."
    )
    text: Optional[str] = Field(
        None, description="Free-text answer (waiting{input} parks; optional otherwise)."
    )

    @model_validator(mode="after")
    def _answer_required(self) -> "RespondRequest":
        if self.approved is None and self.text is None:
            raise ValueError("provide `approved` and/or `text`")
        return self


@router.post("/runs/{run_id}/respond")
async def respond_agent_run(
    run_id: str, req: RespondRequest, request: Request
) -> dict:
    """Deliver a human answer to a run parked in `waiting` (T5).

    The parked runner resumes at its park point (`waiting → running`), and the
    run continues — this is the interactive-consent seam ADR 0003 §8 promised
    (today: the spawn_subagent gate; later: ask-user input parks). 404 unknown
    run, 403 not the owner (Inc 8b), 409 when the run isn't answerable (not
    parked, token mismatch, already answered, or parked before a restart —
    that last one is T7's /resume job)."""
    registry = get_agent_run_registry()
    meta = registry.get_run(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id!r}")
    _authorize_run_access(request, meta)
    ok, why = registry.respond_run(
        run_id, token=req.token, approved=req.approved, text=req.text
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id!r} cannot accept a response: {why}.",
        )
    return {"ok": True, "run_id": run_id, "status": "running"}


@router.post("/runs/{run_id}/ack")
async def ack_agent_run(run_id: str, request: Request) -> dict:
    """Collect a held result (T6): `completed_pending_ack → finalized`.

    The run already exited (tokens/CPU freed, sandbox torn down) — ack is
    the collection receipt that makes the record GC-eligible. Idempotent:
    acking a finalized run is 200 (a UI collect and a typed `/task ack`
    can't race into an error). 404 unknown run, 403 not the owner (Inc 8b),
    409 when the run holds nothing (any other status)."""
    registry = get_agent_run_registry()
    meta = registry.get_run(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id!r}")
    _authorize_run_access(request, meta)
    ok, why = registry.ack_run(run_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id!r} cannot be acked: {why}.",
        )
    return {"ok": True, "run_id": run_id, "status": "finalized"}


@router.post("/runs/{run_id}/resume")
async def resume_agent_run(run_id: str, request: Request) -> dict:
    """Conditionally continue an `interrupted`/`cancelled` run (T7).

    Resume REBUILDS the scoped runner from the run's persisted inputs (task,
    grant, egress, budget, system, skill read-roots — all on the meta) and
    drives it exactly like a fresh run under the SAME run_id: identical AC-1/
    AC-2 sandbox, a fresh budget window, events appended to the same log.
    Refused (409, run unchanged) when `resume_refusal` says the checkpoint is
    inconclusive — see its decision matrix. 404 unknown, 403 not the owner
    (Inc 8b) or tier disabled (resume re-executes tools, so it faces the same
    execution.task.enabled gate as POST /task)."""
    # Same trusted-operator gate as creating a /task run — a resume re-enters
    # the tool-calling tier.
    if not get_execution_task_config().get("enabled", False):
        raise HTTPException(
            status_code=403,
            detail=(
                "The tool-capable agent tier (/v1/agent/task) is disabled, so "
                "an interrupted task run cannot be resumed. Enable it via "
                "execution.task.enabled=true in ppxai-config.json."
            ),
        )
    registry = get_agent_run_registry()
    meta = registry.get_run(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id!r}")
    _authorize_run_access(request, meta)
    refusal = resume_refusal(
        meta, in_flight=registry.get_run_task(run_id) is not None
    )
    if refusal is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id!r} cannot be resumed: {refusal}.",
        )
    # Fail fast on an unbuildable provider BEFORE mutating the run record.
    _validate_provider_or_400(meta.provider)

    runner = _task_runner.build_task_runner(
        registry,
        provider_name=meta.provider,
        model=meta.model,
        task=meta.task,
        tools=list(meta.tools),
        allow_outbound=list(getattr(meta, "network", []) or []),
        allow_spawn=True,  # same shape as a fresh top-level /task run
        system=getattr(meta, "system", None),
        extra_read_paths=list(getattr(meta, "read_roots", []) or []),
        workdir=getattr(meta, "workdir", None),  # resume where the run ran
    )
    registry.resume_run(meta, runner)
    return {"ok": True, "run_id": run_id, "status": "running"}


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
