"""
v1 gateway: stateless single-turn completion (POST /v1/oneshot).

External agents (outlook-monitor classifier, routers, structured-extraction
pipelines, etc.) often want ppxai-server as a thin LLM gateway without
managing sessions per call. The `/chat` endpoint is session-scoped and
streams via SSE — overkill for "given this prompt, return one response."

`/v1/oneshot` is the gateway primitive:

    POST /v1/oneshot
    {
      "prompt": "Classify this email...",
      "provider": "nvidia",                 // optional
      "model": "qwen/qwen3.5-122b-a10b",    // optional
      "system": "You are a classifier...",  // optional
      "response_format": {"type": "json_object"},  // optional
      "max_tokens": 512,                    // optional
      "temperature": 0.0                    // optional
    }

    → 200 {"content": "...", "finish_reason": "stop", "model": "...",
           "provider": "...", "usage": {...}}

The `/v1/` prefix is the **stable API boundary** — semver-style guarantees
on the request/response shape, see [docs/api-gateway.md] for the policy.
Internal endpoints (`/chat`, `/command/*`, `/files/*`) keep evolving and
are not part of the gateway contract.

Implementation notes:
- No `EngineClient` — we build the provider directly from config so the
  call has zero session-state side effects.
- Every shipped provider now implements `oneshot()`: `OpenAICompatibleProvider`
  (covers `local`, `custom`, `openai`-compat NIM/vLLM/Ollama deployments),
  `openai_native`, `perplexity`, and `gemini`. (This bullet previously said
  the native providers raise 400 "until they grow `oneshot()`" — they since
  did, and the note went stale.)
- `response_format` reaches the model on every provider, but by two different
  routes, because only one of them is an OpenAI endpoint:
    * openai_compat / openai_native / perplexity — forwarded verbatim in
      `request_kwargs`. NVIDIA NIM, vLLM and modern OpenAI-compatible
      endpoints accept `{"type": "json_object"}` and
      `{"type": "json_schema", "json_schema": {...}}`.
    * gemini — `generate_content` has no `response_format`, so it is MAPPED
      onto `response_mime_type` / `response_schema` by
      `providers/gemini.py::response_format_to_gemini`. Two consequences
      worth knowing. First, the schema is sanitized — and beyond the shared
      tool-schema filtering, `additionalProperties` is stripped for this key
      specifically: the google-genai SDK's `Schema` model accepts it, but the
      REST API answers 400 INVALID_ARGUMENT ("Unknown name
      `additional_properties` at 'generation_config.response_schema'"), and
      that key is in almost every OpenAI-generated schema. Second — and
      contrary to a briefly-shipped revision of this note — structured output
      does NOT disable grounding: `google_search` coexists with both
      `response_mime_type` and `response_schema` (verified live against
      gemini-3.1-pro-preview, 2026-08-09). Only function declarations
      conflict with grounding.
  Before v1.19.1 the Gemini path accepted `response_format` and dropped it —
  a caller pinning a schema got a 200 and unconstrained output with no error
  raised anywhere.
- Per-model `extra_body` from config is still applied (so e.g. NIM
  `chat_template_kwargs.enable_thinking` carries through).
"""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...common.logger import get_logger
from ...config import (
    get_api_key,
    get_available_providers,
    get_base_url,
    get_default_model,
    get_default_provider,
    get_execution_run_config,
    get_provider_config,
)
from ...engine import task_runner as _task_runner
from ...engine.facts_resolver import get_effective_oneshot_path
from ...engine.providers import create_provider
from ...engine.providers.openai_compat import OpenAICompatibleProvider
from ...engine.task_authorizer import TIERS as _TIERS
from ...engine.task_authorizer import TaskAuthorizationError, authorize_oneshot
from ...engine.tools.search_backends import resolve_web_search_backend
from ...engine.types import ProviderCapabilities
from ..state import get_agent_run_registry

logger = get_logger("server")

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------------------
# Request / response shapes (stable wire contract)
# ---------------------------------------------------------------------------


class OneshotRequest(BaseModel):
    """Stateless single-turn completion request.

    The shape is part of the stable v1 gateway contract — see
    docs/api-gateway.md. Adding optional fields is non-breaking;
    removing or repurposing fields requires a `/v2/oneshot`.
    """
    prompt: str = Field(..., min_length=1, description="User message content.")
    provider: str | None = Field(
        None,
        description="Provider ID. Falls back to the server's default_provider.",
    )
    model: str | None = Field(
        None,
        description="Model ID. Falls back to the provider's default_model.",
    )
    system: str | None = Field(None, description="Optional system message.")
    response_format: dict[str, Any] | None = Field(
        None,
        description=(
            "OpenAI-shaped response_format dict, e.g. "
            '{"type": "json_object"} or '
            '{"type": "json_schema", "json_schema": {...}}.'
        ),
    )
    max_tokens: int | None = Field(
        None, gt=0, description="Cap output tokens. Overrides per-model config."
    )
    temperature: float | None = Field(
        None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. Overrides per-model config.",
    )


class OneshotUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OneshotGrounding(BaseModel):
    """Present ONLY when the request was served by the enriched search-loop
    path (ADR 0009 §4, F3/F4 facade). Absent → byte-identical legacy
    response.

    `run_id` is the debug handle: the enriched oneshot executed as a real
    `kind=oneshot` registry run, so `~/.ppxai/runs/<run_id>/` holds its meta
    + event log and the run inspection surfaces work on it. All fields are
    derived from THAT run's own audit trail (F4) — never from any
    process-global — so concurrent requests can't cross-attribute."""

    searched: bool = False
    run_id: str | None = None
    # F4: the query strings the model actually searched (from the run's
    # tool_call events), the premium backend that served them (from the
    # run's usage record; "duckduckgo" inferred for the costless path), and
    # the premium-search cost in USD for THIS request.
    queries: list = Field(default_factory=list)
    backend: str | None = None
    search_cost: float = 0.0


class OneshotResponse(BaseModel):
    content: str
    finish_reason: str | None = None
    model: str
    provider: str
    usage: OneshotUsage | None = None
    # ADR 0009 §4 wire contract: optional, additive — absent when the
    # enrichment path is off (the shipped consumers see no change).
    grounding: OneshotGrounding | None = None


# ---------------------------------------------------------------------------
# Provider construction (stateless — no EngineClient)
# ---------------------------------------------------------------------------


def _oneshot_grounding_enabled() -> bool:
    """True when the operator has opted oneshot into native web search.

    Option A (docs/archive/plan-oneshot-grounding.md): the tool-FREE oneshot tiers
    (`/v1/oneshot`, `/v1/agent/run`) may augment a single-turn completion with
    the PROVIDER'S OWN web search (Perplexity Sonar, Gemini grounding) — NOT by
    handing the model a `web_search`/`fetch_url` tool (that's Option B, with the
    tool-loop exfiltration surface). Retrieval happens inside the provider's API
    call, so the egress perimeter is unchanged: the same provider host the call
    already reaches, and no model-named URL fetch.

    Default OFF — when off, oneshot behaves exactly as before (ppxai-sre's
    `/v1/oneshot` consumers see no change). Read from
    `execution.run.grounding` (ADR 0011 Q5), which dual-reads the legacy
    `tools.web_search.oneshot_grounding` key until it is retired.
    """
    try:
        return bool(get_execution_run_config().get("grounding", False))
    except Exception:
        return False


def _oneshot_enrichment_enabled() -> bool:
    """True when the operator opted the one-off tier into the ADR 0009 §4
    enrichment loop: the `web_search` fallback chain exposed to the model,
    driven through the run tier by the oneshot facade (F3 — until it lands
    this flag only steers the gating log below).

    Default OFF. Read from `execution.run.web_search` (ADR 0011: the ONLY
    tool the one-off tier can ever grant)."""
    try:
        return bool(get_execution_run_config().get("web_search", False))
    except Exception:
        return False


def _oneshot_effective_path(provider_name: str, model: str) -> str:
    """The ADR 0009 §4 gating truth table, resolved per request. Thin
    delegate — the logic lives on the config axis
    (`engine.facts_resolver.get_effective_oneshot_path`) so `/doctor` reports
    the same decision without importing server routes (F5)."""
    return get_effective_oneshot_path(provider_name, model)


# ---------------------------------------------------------------------------
# Enriched oneshot — the F3 facade over the run tier (ADR 0009 step ①)
# ---------------------------------------------------------------------------

# Small §4 iteration cap: enough for search → answer, not an agent budget.
# The value is TIER DATA (`task_authorizer.TIERS["oneshot"].iterations`) —
# it belongs with the grant rule that decides it, not with the transport.
# Re-exported here because this is where the long tail of importers looks.
ONESHOT_SEARCH_ITERATIONS = _TIERS["oneshot"].iterations
# Bound the synchronous wait; on expiry the run is cooperatively cancelled
# and the 504 carries the run id (the run record keeps whatever happened).
ONESHOT_SEARCH_TIMEOUT_S = 180.0


def _web_search_egress_hosts(provider_name: str | None = None) -> list:
    """The bare HOSTNAMES of web_search's EFFECTIVE egress set, for the run's
    allowlist. Resolver entries are URLs (the shape `tool_targets` compares
    against), but `NetworkPolicy` allowlist rules take bare hosts — passing
    the URLs verbatim silently matches nothing (fail-closed deny; caught
    live in the F3 trial via the run's own network_policy_denied event).

    Step ④ (ADR 0009 Q5): reads the shared backend resolver, so under an
    effective `strict` pin the enrichment baseline narrows to the pinned
    backend's host(s) — the §3-sanctioned narrowing — and in auto/ordering
    mode it is the full superset (session parity = the fallback chain).
    Step ② composes on top: the operator's `tools.web_search.egress`
    baseline is merged via `_with_tool_egress_defaults` at the call site —
    the same mechanism `/v1/agent/task` uses."""
    from urllib.parse import urlparse


    hosts = resolve_web_search_backend(provider_name).egress_hosts
    return sorted({urlparse(u).netloc for u in hosts if urlparse(u).netloc})


def _grounding_from_events(
    registry, run_id: str
) -> tuple[OneshotGrounding, OneshotUsage | None]:
    """Derive the grounding record + model usage from the run's OWN audit
    trail (F4). No side channel, no process-global: the tool_call events
    carry the queries, the run_usage event carries tokens + the premium
    backend/cost — all keyed by this run_id, so concurrent requests are
    structurally unable to cross-attribute."""
    # Collect into locals and construct the model ONCE with every field
    # explicit: the route serializes with response_model_exclude_unset, and
    # in-place mutation (e.g. list.append) never marks a field as set — a
    # mutated-in field would silently vanish from the wire.
    searched = False
    queries: list = []
    backend: str | None = None
    search_cost = 0.0
    usage: OneshotUsage | None = None
    try:
        for e in registry.read_events(run_id):
            etype = getattr(e, "type", "")
            data = getattr(e, "data", {}) or {}
            if etype == "tool_call" and data.get("tool") == "web_search":
                searched = True
                q = (data.get("arguments") or {}).get("query")
                if q:
                    queries.append(str(q))
            elif etype == "run_usage":
                usage = OneshotUsage(
                    prompt_tokens=int(data.get("prompt_tokens") or 0),
                    completion_tokens=int(data.get("completion_tokens") or 0),
                    total_tokens=int(data.get("total_tokens") or 0),
                )
                ws = data.get("web_search") or {}
                backend = ws.get("backend") or backend
                search_cost = float(ws.get("estimated_cost") or 0.0)
    except Exception:
        pass
    if searched and backend is None:
        # Only the free path records no premium ToolUsage — a search that
        # cost nothing went through DuckDuckGo (the sole costless backend).
        backend = "duckduckgo"
    grounding = OneshotGrounding(
        searched=searched,
        run_id=run_id,
        queries=queries,
        backend=backend,
        search_cost=search_cost,
    )
    return grounding, usage


def _authorize_oneshot_search_loop(task: str, provider_name: str, model: str):
    """Admission for the enriched `/v1/oneshot` path — the shared authorizer.

    This branch used to hardwire `tools=["web_search"]` and go straight to
    `build_task_runner`, which made it a THIRD admission route that applied
    none of the tier's policy. Concretely: `tools.web_search.enabled=false`
    is an operator veto that returned 403 for `POST /v1/agent/run`, and an
    enriched oneshot searched anyway. The grant is still config-decided and
    still un-widenable by the request — that is `TIERS["oneshot"]`'s job, not
    this function's — but it is now DERIVED by `authorize_oneshot()` rather
    than asserted here.

    Raises `TaskAuthorizationError`; the caller maps it onto `HTTPException`
    exactly as `agent_v1` does.
    """

    return authorize_oneshot(task, provider=provider_name, model=model)


async def _oneshot_via_search_loop(
    req: OneshotRequest, provider_name: str, model: str, owner: str | None
) -> OneshotResponse:
    """Serve an enriched oneshot as a REAL `kind=oneshot` registry run.

    ADR 0011: oneshot is a facade verb over unmodified task-tier gears —
    same registry, same `build_task_runner` sandbox (ScopedToolManager grant
    + NetworkPolicy egress + budget control), same event log. The only
    oneshot-shaped differences: the grant is hardwired to `{web_search}`
    (no flag can widen it), the HTTP request awaits the terminal state
    (spawn_subagent's parent-await pattern, `get_run_task`), and
    `hold_result=False` lands the run straight in `completed` (no T6 hold).
    The run record in `~/.ppxai/runs/<id>/` is the debug surface.
    """
    # Lazy: agent_v1 top-imports from this module (provider construction);
    # importing it at module level would be circular.
    from .agent_v1 import _enriched_oneshot_egress_or_400
    # Through the module, never a from-import binding: the patch point
    # is task_runner.build_task_runner, and a bound reference captured
    # here would not see it (see that module's docstring).

    # Effective backend egress set (resolver; step ④) + the operator's
    # tools.web_search.egress baseline (step ②), capped by
    # execution.egress_ceiling (step ③ Q3 — 400 pre-start when the cap
    # breaks the set, never a half-enriched request) — one mechanism shared
    # with /v1/agent/run.
    # Admission FIRST — before any run is minted. The tier's policy (grant
    # source, operator kill-switches, provider validation) lives in one place
    # for every client; see task_authorizer.TIERS["oneshot"].

    try:
        _authorize_oneshot_search_loop(req.prompt, provider_name, model)
    except TaskAuthorizationError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e

    egress_hosts = _enriched_oneshot_egress_or_400(provider_name)
    registry = get_agent_run_registry()
    meta = registry.start_run(
        task=req.prompt,
        kind="oneshot",
        tools=["web_search"],  # the ONLY grant — ADR 0011 "no tools by design"
        provider=provider_name,
        model=model,
        network=list(egress_hosts),
        budget={"iterations": ONESHOT_SEARCH_ITERATIONS},
        owner=owner,
        hold_result=False,  # oneshot semantics: the response IS the collect
        system=req.system,
    )
    runner = _task_runner.build_task_runner(
        registry,
        provider_name=provider_name,
        model=model,
        task=req.prompt,
        tools=["web_search"],
        allow_outbound=list(egress_hosts),
        allow_spawn=False,  # consent/park path structurally unreachable
        system=req.system,
    )
    registry.run_in_background(meta, runner)
    run_task = registry.get_run_task(meta.run_id)
    try:
        if run_task is not None:
            # shield: on timeout we cancel COOPERATIVELY (clean checkpoint)
            # instead of ripping the task out mid-tool-call.
            await asyncio.wait_for(
                asyncio.shield(run_task), timeout=ONESHOT_SEARCH_TIMEOUT_S
            )
    except asyncio.TimeoutError:
        registry.cancel_run(meta.run_id)
        raise HTTPException(
            status_code=504,
            detail=(
                f"Enriched oneshot timed out after {ONESHOT_SEARCH_TIMEOUT_S:.0f}s; "
                f"run {meta.run_id} was cancelled — its record remains inspectable."
            ),
        )
    except asyncio.CancelledError:
        # Client disconnect / server shutdown: never leave a headless spender.
        registry.cancel_run(meta.run_id)
        raise

    final = registry.get_run(meta.run_id) or meta
    if final.status != "completed":
        raise HTTPException(
            status_code=502,
            detail=(
                f"Enriched oneshot run {meta.run_id} ended "
                f"{final.status!r}: {final.error or 'no result'}"
            ),
        )
    grounding, usage = _grounding_from_events(registry, meta.run_id)
    return OneshotResponse(
        content=final.result or "",
        finish_reason="stop",
        model=model,
        provider=provider_name,
        usage=usage,
        grounding=grounding,
    )


def _apply_oneshot_grounding(provider, provider_name: str) -> None:
    """Turn on a provider's NATIVE web search for a oneshot call, in place.

    Capability-gated: only providers that advertise `capabilities.web_search`
    are touched, so the flag can never be mistaken for tool exposure on a
    non-search provider (OpenAI/NVIDIA → no-op). The mechanism is per-provider:

    - Gemini: set `enable_grounding=True`; `oneshot()` then builds the config
      with `GoogleSearch()` (no ppxai tools are passed on the oneshot path, so
      grounding is not suppressed by function-calling).
    - Perplexity: search is intrinsic to sonar* models and already on for the
      configured default — no per-call switch to flip here. (A future tightening
      could substitute a sonar model when a non-search model is requested; out
      of scope for this increment, and we must not silently downgrade a
      deliberately chosen reasoning model.)
    - Others with web_search capability but no oneshot grounding hook: no-op.

    Best-effort and fail-open-to-current-behavior: any error leaves the
    provider as built (oneshot still works, just ungrounded)."""
    try:
        cfg = get_provider_config(provider_name)
        if not cfg.get("capabilities", {}).get("web_search", False):
            return  # non-search provider — never reach for search
        if hasattr(provider, "enable_grounding"):
            provider.enable_grounding = True
    except Exception:
        return


def _validate_provider_or_400(provider_name: str) -> None:
    """Cheap fail-fast: raise HTTPException(400) if `provider_name` is unknown
    or has no API key, WITHOUT constructing the provider.

    Same two checks `_build_provider` does up front, factored out so a caller
    that only needs to validate (e.g. the `/v1/agent/task` tier, which builds
    its own provider later inside the run) doesn't instantiate and immediately
    throw away an SDK client. Keep this in sync with `_build_provider`'s guards.
    """
    if provider_name not in get_available_providers():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider_name!r}. "
            f"Configure it in ppxai-config.json.",
        )
    if not get_api_key(provider_name):
        raise HTTPException(
            status_code=400,
            detail=f"No API key for provider {provider_name!r}. "
            f"Set it in ~/.ppxai/.env.",
        )


def _build_provider(provider_name: str):
    """Construct a provider instance directly from config.

    Mirrors `engine/provider_ops.py::set_provider` minus the
    `EngineClient` mutation. Returns the provider or raises HTTPException
    with a friendly message that the caller can surface to clients.

    When `tools.web_search.oneshot_grounding` is enabled, search-capable
    providers are switched into native-grounding mode before return (Option A —
    see `_apply_oneshot_grounding`). This is the single construction site shared
    by `/v1/oneshot` and the agent-run tier (`agent_v1._v1_provider_or_400`
    delegates here), so both oneshot tiers pick up grounding from one place.
    """
    # get_provider_config falls back to "perplexity" for unknown providers,
    # which would silently swap providers under the caller. Check membership
    # explicitly first.
    if provider_name not in get_available_providers():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider_name!r}. "
            f"Configure it in ppxai-config.json.",
        )
    cfg = get_provider_config(provider_name)

    api_key = get_api_key(provider_name)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key for provider {provider_name!r}. "
            f"Set it in ~/.ppxai/.env.",
        )

    base_url = get_base_url(provider_name)
    capabilities = ProviderCapabilities.from_dict(cfg.get("capabilities", {}))
    options = cfg.get("options", {})

    provider = create_provider(
        provider_name,
        api_key=api_key,
        base_url=base_url,
        models=cfg.get("models", {}),
        capabilities=capabilities,
        **options,
    )
    if provider is None:
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            models=cfg.get("models", {}),
            capabilities=capabilities,
            provider_id=provider_name,
        )

    # Option A: opt-in native web search for the tool-free oneshot tiers.
    # No-op unless tools.web_search.oneshot_grounding is on AND the provider is
    # search-capable. Does NOT expose any web tool to the model.
    if _oneshot_grounding_enabled():
        _apply_oneshot_grounding(provider, provider_name)
    elif hasattr(provider, "enable_grounding"):
        # Default OFF: the oneshot perimeter is unchanged regardless of a
        # provider's configured chat-grounding. A Gemini provider is built with
        # enable_grounding=True (config default), so WITHOUT this it would run
        # live Google Search on every oneshot even though the operator never
        # opted oneshot into web search — breaking the default-OFF guarantee.
        provider.enable_grounding = False

    return provider


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


# response_model_exclude_unset: the legacy paths set every field explicitly,
# so their wire shape is byte-identical to the shipped contract; `grounding`
# is set ONLY by the enriched facade — absent (not null) everywhere else.
@router.post(
    "/oneshot", response_model=OneshotResponse, response_model_exclude_unset=True
)
async def oneshot(req: OneshotRequest, request: Request) -> OneshotResponse:
    """Stateless single-turn completion. See module docstring."""
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
            detail=f"No model specified and no default_model for "
            f"provider {provider_name!r}.",
        )

    # ADR 0009 §4 gating: resolve + log the effective path per request.
    # Both keys default off → byte-identical wire for existing consumers.
    effective_path = _oneshot_effective_path(provider_name, model)
    logger.debug(
        f"/v1/oneshot gating: provider={provider_name} model={model} "
        f"grounding_on={_oneshot_grounding_enabled()} "
        f"enrichment_on={_oneshot_enrichment_enabled()} -> {effective_path}"
    )

    if effective_path == "search-loop":
        # F3: the enriched path executes as a real kind=oneshot registry run.
        owner = None
        try:
            from .agent_v1 import _caller_owner  # lazy — see facade docstring

            owner = _caller_owner(request)
        except Exception:
            owner = None
        return await _oneshot_via_search_loop(req, provider_name, model, owner)

    provider = _build_provider(provider_name)

    # FU (ADR 0009 follow-up unification): the plain path ALSO executes as a
    # real `kind=oneshot` registry run — the direct non-registry branch that
    # used to live here is DELETED, so the whole one-off tier has exactly one
    # execution path (the run registry) and every oneshot is auditable in
    # `~/.ppxai/runs/<id>/` and visible to `/run ls`. The native-grounding
    # prerequisite is satisfied by construction: the runner closes over the
    # provider `_build_provider` returned, which already carries the
    # effective grounding switch — grounded and closed-book calls ride the
    # same gears.
    #
    # v1.19.x: oneshot() is part of the BaseProvider contract (implemented on
    # every provider), so this is provider-agnostic — no isinstance guard.
    # _build_provider already 400s on unknown provider / missing key.
    owner = None
    try:
        from .agent_v1 import _caller_owner  # lazy — circular at module level

        owner = _caller_owner(request)
    except Exception:
        owner = None

    registry = get_agent_run_registry()
    meta = registry.start_run(
        task=req.prompt,
        kind="oneshot",
        tools=[],  # closed-book: no grant, no egress, no budget
        provider=provider_name,
        model=model,
        owner=owner,
        hold_result=False,  # oneshot semantics: the response IS the collect
        system=req.system,
    )

    # The run registry keeps only the result STRING; the wire contract needs
    # the provider's full envelope (finish_reason / model / usage) byte-
    # identical to the pre-FU direct path — the awaiting handler holds this
    # closure, so the envelope never touches shared state.
    envelope: dict[str, Any] = {}

    async def _runner(m) -> str:
        # provider.oneshot is blocking I/O (SDK round-trip). Offload it so a
        # slow provider (e.g. Gemini preview, multi-second reasoning) doesn't
        # starve the single event loop and stall every other request.
        result = await asyncio.to_thread(
            lambda: provider.oneshot(
                prompt=req.prompt,
                model=model,
                system=req.system,
                response_format=req.response_format,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
            )
        )
        envelope.update(result or {})
        return (result or {}).get("content", "")

    registry.run_in_background(meta, _runner)
    run_task = registry.get_run_task(meta.run_id)
    try:
        if run_task is not None:
            # shield: a client disconnect cancels the RUN cooperatively
            # (never a headless spender) instead of ripping the provider
            # call out mid-flight. No timeout here — parity with the
            # pre-FU direct path, which waited as long as the provider did.
            await asyncio.shield(run_task)
    except asyncio.CancelledError:
        registry.cancel_run(meta.run_id)
        raise

    final = registry.get_run(meta.run_id) or meta
    if final.status != "completed":
        # Same error contract as the pre-FU direct path (502, provider
        # message verbatim) — plus the run id as the debug handle.
        logger.warning(
            f"/v1/oneshot provider call failed: {provider_name}/{model}: "
            f"{final.error} (run {meta.run_id})"
        )
        raise HTTPException(
            status_code=502,
            detail=f"Provider call failed: {final.error}",
        )

    usage = None
    if envelope.get("usage") is not None:
        usage = OneshotUsage(**envelope["usage"])

    return OneshotResponse(
        content=envelope.get("content", ""),
        finish_reason=envelope.get("finish_reason"),
        model=envelope.get("model", model),
        provider=provider_name,
        usage=usage,
    )
