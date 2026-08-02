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
- v1 supports `OpenAICompatibleProvider` (covers `local`, `custom`,
  `openai`-compat NIM/vLLM/Ollama deployments). Native OpenAI / Perplexity
  / Gemini-native providers raise 400 with a clear message until they
  grow `oneshot()`.
- `response_format` forwards to the provider as-is. NVIDIA NIM, vLLM, and
  modern OpenAI-compatible endpoints accept the OpenAI shape
  (`{"type": "json_object"}` or
  `{"type": "json_schema", "json_schema": {...}}`).
- Per-model `extra_body` from config is still applied (so e.g. NIM
  `chat_template_kwargs.enable_thinking` carries through).
"""

import asyncio
from typing import Any, Dict, Optional

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
    get_tool_calling_config,
)
from ...engine.providers import create_provider
from ...engine.providers.openai_compat import OpenAICompatibleProvider
from ...engine.types import ProviderCapabilities

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
    provider: Optional[str] = Field(
        None,
        description="Provider ID. Falls back to the server's default_provider.",
    )
    model: Optional[str] = Field(
        None,
        description="Model ID. Falls back to the provider's default_model.",
    )
    system: Optional[str] = Field(None, description="Optional system message.")
    response_format: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "OpenAI-shaped response_format dict, e.g. "
            '{"type": "json_object"} or '
            '{"type": "json_schema", "json_schema": {...}}.'
        ),
    )
    max_tokens: Optional[int] = Field(
        None, gt=0, description="Cap output tokens. Overrides per-model config."
    )
    temperature: Optional[float] = Field(
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
    path (ADR 0009 §4, F3 facade). Absent → byte-identical legacy response.

    `run_id` is the debug handle: the enriched oneshot executed as a real
    `kind=oneshot` registry run, so `~/.ppxai/runs/<run_id>/` holds its meta
    + event log and the run inspection surfaces work on it. F4 adds
    `queries`/`backend`/`search_cost`."""

    searched: bool = False
    run_id: Optional[str] = None


class OneshotResponse(BaseModel):
    content: str
    finish_reason: Optional[str] = None
    model: str
    provider: str
    usage: Optional[OneshotUsage] = None
    # ADR 0009 §4 wire contract: optional, additive — absent when the
    # enrichment path is off (the shipped consumers see no change).
    grounding: Optional[OneshotGrounding] = None


# ---------------------------------------------------------------------------
# Provider construction (stateless — no EngineClient)
# ---------------------------------------------------------------------------


def _oneshot_grounding_enabled() -> bool:
    """True when the operator has opted oneshot into native web search.

    Option A (docs/plan-oneshot-grounding.md): the tool-FREE oneshot tiers
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


def _provider_web_search_capable(provider_name: str) -> bool:
    """Does this provider advertise NATIVE web search (capabilities axis)?"""
    try:
        return bool(
            get_provider_config(provider_name)
            .get("capabilities", {})
            .get("web_search", False)
        )
    except Exception:
        return False


def _tool_calling_capable(provider_name: str, model: str) -> bool:
    """Can this provider/model drive the §4 web_search tool loop?

    True on native function calling (capabilities.native_tool_calling) or an
    explicit per-provider/per-model `tool_calling` config block (the
    prompt-based path — docs/prompt-based-tool-calling.md). Conservative
    default: neither signal → not capable → the gating table lands on
    closed-book rather than handing tools to a model that can't call them."""
    try:
        caps = get_provider_config(provider_name).get("capabilities", {})
        if caps.get("native_tool_calling", False):
            return True
        mode = (get_tool_calling_config(provider_name, model) or {}).get("mode")
        return bool(mode) and mode != "none"
    except Exception:
        return False


def _oneshot_effective_path(provider_name: str, model: str) -> str:
    """The ADR 0009 §4 gating truth table, resolved per request.

    `native` (provider's own search) beats `search-loop` (enrichment) —
    enrichment XOR native, never both; anything else is `closed-book`:

        grounding_on AND capable(web_search)            → native
        elif enrichment_on AND tool_calling_capable     → search-loop
        else                                            → closed-book

    F2: computed + logged only (the search-loop execution path arrives with
    the F3 facade); with both keys at their defaults the request is
    byte-identical to the shipped behavior."""
    native_effective = _oneshot_grounding_enabled() and _provider_web_search_capable(
        provider_name
    )
    if native_effective:
        return "native"
    if _oneshot_enrichment_enabled() and _tool_calling_capable(provider_name, model):
        return "search-loop"
    return "closed-book"


# ---------------------------------------------------------------------------
# Enriched oneshot — the F3 facade over the run tier (ADR 0009 step ①)
# ---------------------------------------------------------------------------

# Small §4 iteration cap: enough for search → answer, not an agent budget.
ONESHOT_SEARCH_ITERATIONS = 2
# Bound the synchronous wait; on expiry the run is cooperatively cancelled
# and the 504 carries the run id (the run record keeps whatever happened).
ONESHOT_SEARCH_TIMEOUT_S = 180.0


def _web_search_egress_hosts() -> list:
    """The bare HOSTNAMES of web_search's backend superset, for the run's
    allowlist. `_WEB_SEARCH_ALL_HOSTS` entries are URLs (that's the shape
    `tool_targets` compares against), but `NetworkPolicy` allowlist rules
    take bare hosts — passing the URLs verbatim silently matches nothing
    (fail-closed deny; caught live in the F3 trial via the run's own
    network_policy_denied event). Step ② swaps the source to
    `tools.web_search.egress` with the same host shape."""
    from urllib.parse import urlparse

    from ...engine.tools.network_policy import _WEB_SEARCH_ALL_HOSTS

    return sorted({
        urlparse(u).netloc for u in _WEB_SEARCH_ALL_HOSTS if urlparse(u).netloc
    })


def _run_used_web_search(registry, run_id: str) -> bool:
    """Did the run actually invoke web_search? Read from the run's own event
    log (category=tool) — no side channel, the audit trail IS the source."""
    try:
        events = registry.read_events(run_id)
        return any(
            getattr(e, "category", "") == "tool"
            and "web_search" in str(getattr(e, "data", {}))
            for e in events
        )
    except Exception:
        return False


async def _oneshot_via_search_loop(
    req: OneshotRequest, provider_name: str, model: str, owner: Optional[str]
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
    from ..state import get_agent_run_registry
    from .agent_v1 import build_task_runner

    egress_hosts = _web_search_egress_hosts()  # step ② swaps the source
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
    runner = build_task_runner(
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
    return OneshotResponse(
        content=final.result or "",
        finish_reason="stop",
        model=model,
        provider=provider_name,
        usage=None,  # F4: model tokens + search cost accounting
        grounding=OneshotGrounding(
            searched=_run_used_web_search(registry, meta.run_id),
            run_id=meta.run_id,
        ),
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

    # v1.19.x: oneshot() is now part of the BaseProvider contract (implemented
    # on every provider), so /v1/oneshot is provider-agnostic — no
    # isinstance-by-class guard. _build_provider already 400s on unknown
    # provider / missing key.
    try:
        # provider.oneshot is blocking I/O (SDK round-trip). Offload it so a
        # slow provider (e.g. Gemini preview, multi-second reasoning) doesn't
        # starve the single event loop and stall every other request. The
        # agent-run tier (agent_v1._runner) already offloads the same call.
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
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(
            f"/v1/oneshot provider call failed: {provider_name}/{model}: {e}"
        )
        raise HTTPException(
            status_code=502,
            detail=f"Provider call failed: {e}",
        )

    usage = None
    if result.get("usage") is not None:
        usage = OneshotUsage(**result["usage"])

    return OneshotResponse(
        content=result.get("content", ""),
        finish_reason=result.get("finish_reason"),
        model=result.get("model", model),
        provider=provider_name,
        usage=usage,
    )
