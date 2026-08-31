"""
Premium web search tools using external APIs.

Provides web search via Perplexity Sonar API or Gemini Google Search Grounding,
with graceful fallback to free DuckDuckGo if premium providers are unavailable.

v1.13.4: Initial implementation
"""

import contextvars
import logging
import os
from typing import Optional, Tuple, List, Dict, Any

import httpx
from openai import AsyncOpenAI

from ppxai.config import get_tool_config, get_tool_pricing
from ppxai.config.tls import tls_verify
from ppxai.constants import APIEndpoint
from ...model_facts import shipped_facts_for_model
from ...providers.perplexity import PerplexityProvider
from ...types import ToolUsage
# ADR 0009 step ④: the ONE shared backend resolver (leaf module, top-level
# import — retires the function-local `network_policy` import this module
# used to reach the pin through).
from ..search_backends import resolve_web_search_backend
from . import web

# Global to store usage from last tool execution (LEGACY channel — see
# _record_usage). Kept maintained for back-compat readers; new code uses
# the per-call ContextVar holder below.
_last_tool_usage: Optional[ToolUsage] = None

# Per-call usage channel (v1.19.1 F4 — fixes ADR 0009 §4's named bug).
# The module global above is a process-wide reset-on-read handoff: with two
# CONCURRENT runs, run A's tool task can finish, then run B's task finishes
# and overwrites the global before A's chat loop resumes to read it — A gets
# B's cost, B gets None. The fix: the CALLER (chat loop) installs a holder
# list via begin_usage_capture() BEFORE creating the tool task; the task
# inherits a context COPY, but the holder LIST is the same object, so the
# handler's usage lands in exactly that caller's holder — per-run by
# construction, no shared mutable slot.
_tool_usage_holder: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar(
    "web_search_usage_holder", default=None
)

# Item 59: the run's egress host-predicate, installed by ScopedToolManager for
# the duration of a sandboxed tool call. When set, the search chain narrows its
# candidate backends to those the run may actually reach — so a soft
# `preferred:perplexity` + perplexity-only task allowlist never *tries* the DDG
# fallback the sandbox would deny (the divergence that produced a fabricated
# weather answer, 2026-08-10). None (chat / unconfined runs) = full chain.
_egress_allows_holder: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "web_search_egress_allows", default=None
)


def set_egress_predicate(pred: Optional[Any]) -> Optional[Any]:
    """Install (and return the prior) run egress host-predicate on the current
    context. ScopedToolManager wraps each network-tool call so the search chain
    resolves the same narrowed candidate set the egress guard authorized."""
    prior = _egress_allows_holder.get()
    _egress_allows_holder.set(pred)
    return prior


def begin_usage_capture() -> list:
    """Install (and return) a fresh per-call usage holder on the current
    context. Call from the tool-loop BEFORE spawning the tool task; every
    premium-search usage recorded during that call appends here."""
    holder: list = []
    _tool_usage_holder.set(holder)
    return holder


def _record_usage(usage: ToolUsage) -> None:
    """Record one premium-search invocation's usage. Appends to the caller's
    ContextVar holder (race-free channel) AND sets the legacy global (kept
    for any out-of-tree reader of get_last_tool_usage)."""
    holder = _tool_usage_holder.get()
    if holder is not None:
        holder.append(usage)
    global _last_tool_usage
    _last_tool_usage = usage


def is_available() -> bool:
    """Check if any premium API keys are available.

    Returns:
        True if PERPLEXITY_API_KEY or GEMINI_API_KEY is set
    """
    return bool(os.getenv("PERPLEXITY_API_KEY") or os.getenv("GEMINI_API_KEY"))


def get_premium_search_provider(provider_name: Optional[str] = None) -> Optional[str]:
    """The FIRST backend the search chain will try, via the shared resolver.

    ADR 0009 step ④: delegates to `resolve_web_search_backend` — the same
    scoped `preferred`/`strict` tuple the egress enumeration reads, so the
    backend contacted and the host set allowlisted can never diverge.
    Preserved contract: returns "perplexity"/"gemini", or None when the
    first choice is DuckDuckGo (free search) or nothing is usable.
    """
    candidates = resolve_web_search_backend(provider_name).candidates
    first = candidates[0] if candidates else None
    return first if first in ("perplexity", "gemini") else None


def calculate_tool_cost(provider: str, tokens_in: int = 0, tokens_out: int = 0, query_count: int = 0) -> float:
    """Calculate tool usage cost based on pricing model.

    Args:
        provider: Provider name ("perplexity" or "gemini_grounding")
        tokens_in: Input tokens (for per-token pricing)
        tokens_out: Output tokens (for per-token pricing)
        query_count: Number of queries (for per-query pricing)

    Returns:
        Estimated cost in USD
    """
    pricing = get_tool_pricing("web_search", provider)

    if not pricing:
        return 0.0

    pricing_model = pricing.get("model", "per_token")

    if pricing_model == "per_token":
        # Perplexity: per-million-token pricing
        input_price = pricing.get("input", 0.0)
        output_price = pricing.get("output", 0.0)
        input_cost = (tokens_in / 1_000_000) * input_price if input_price else 0.0
        output_cost = (tokens_out / 1_000_000) * output_price if output_price else 0.0
        return input_cost + output_cost

    elif pricing_model == "per_query":
        # Gemini Grounding: per-query pricing
        per_query_price = pricing.get("per_query", 0.0)
        return (query_count / 1000) * per_query_price if per_query_price else 0.0

    return 0.0


#: Perplexity's two wires. The chat host is the shared constant; the
#: Responses wire lives one path segment deeper (measured — the bare host
#: 404s on `/responses`).
PERPLEXITY_CHAT_BASE_URL = APIEndpoint.PERPLEXITY_API
PERPLEXITY_RESPONSES_BASE_URL = APIEndpoint.PERPLEXITY_API.rstrip("/") + "/v1"


def _responses_answer_and_citations(response, num_results: int):
    """Pull answer text and citation URLs out of a Responses reply.

    MEASURED 2026-08-30 (plan W0 (c)): citations arrive as a
    `search_results` OUTPUT ITEM carrying `{id, snippet, date, url}` rows.
    The text block's `annotations` array stays **empty** on this wire, so
    reading annotations — the obvious guess — silently yields no citations.
    """
    payload = {}
    try:
        payload = response.model_dump()
    except Exception:  # noqa: BLE001 - SDK shape varies; fall back below
        payload = {}

    citations = []
    for item in payload.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") == "search_results":
            for row in item.get("results") or []:
                url = (row or {}).get("url")
                if url and url not in citations:
                    citations.append(url)

    content = getattr(response, "output_text", None) or ""
    if not content:
        parts = []
        for item in payload.get("output", []) or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    parts.append(part.get("text") or "")
        content = "".join(parts)

    return content, citations[:num_results]


async def web_search_perplexity(query: str, num_results: int = 5) -> Tuple[str, List[str], ToolUsage]:
    """Search web using Perplexity Sonar API.

    Uses OpenAI-compatible API format.

    Args:
        query: Search query
        num_results: Maximum number of results to return

    Returns:
        Tuple of (answer_text, list_of_citation_urls, tool_usage)

    Raises:
        ValueError: If PERPLEXITY_API_KEY not set
    """
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY not set")

    # Get model from config, default to sonar
    tool_config = get_tool_config("web_search")
    perplexity_model = tool_config.get("perplexity_model", "sonar")

    # ADR 0012 W3: which wire this model speaks is a per-model FACT, resolved
    # from the same table `PerplexityProvider` uses. This tool used to build
    # its own client hardcoded to `/chat/completions`, which meant the
    # 2026-09-27 Sonar retirement would break web_search independently of the
    # provider — a second path to patch instead of one path to fix. Reading
    # the fact here is the root-cause fix: configure `perplexity/sonar` and
    # this tool follows the provider onto the surviving wire with no code
    # change.
    wire = shipped_facts_for_model(
        perplexity_model, PerplexityProvider.shipped_model_facts
    ).wire_protocol

    # TLS via the shared resolver. This site previously honoured SSL_VERIFY
    # but ignored SSL_CERT_FILE, so a custom-CA install silently verified
    # against the system store here while every other client used the bundle.
    #
    # `async with` because AsyncOpenAI never closes a caller-supplied
    # http_client — an unclosed AsyncClient here leaked its connection
    # pool on every web_search call in a long-lived server. Same pattern
    # as web_search_gemini below.
    async with httpx.AsyncClient(verify=tls_verify()) as http_client:
        if wire == "responses":
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=PERPLEXITY_RESPONSES_BASE_URL,
                http_client=http_client,
            )
            # MEASURED 2026-08-30 (plan W0 (c)): on this wire search is an
            # explicit TOOL, not implicit as it is on Sonar chat-completions.
            # A plain request runs no search at all and returns no citations,
            # so the tool must be requested by name — the migration is
            # behavioural, not a change of parse site.
            response = await client.responses.create(
                model=perplexity_model,
                input=query,
                tools=[{"type": "web_search"}],
            )
            content, citations = _responses_answer_and_citations(
                response, num_results
            )
            usage_obj = getattr(response, "usage", None)
            tokens_in = getattr(usage_obj, "input_tokens", 0) or 0
            tokens_out = getattr(usage_obj, "output_tokens", 0) or 0
        else:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=PERPLEXITY_CHAT_BASE_URL,
                http_client=http_client,
            )
            response = await client.chat.completions.create(
                model=perplexity_model,
                messages=[{"role": "user", "content": query}]
            )
            content = response.choices[0].message.content
            citations = list(getattr(response, "citations", None) or [])[:num_results]
            tokens_in = response.usage.prompt_tokens
            tokens_out = response.usage.completion_tokens

    usage = ToolUsage(
        call_count=1,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        provider="perplexity"
    )
    usage.estimated_cost = calculate_tool_cost("perplexity", tokens_in, tokens_out)

    return content, citations, usage


async def web_search_gemini(query: str, num_results: int = 5) -> Tuple[str, List[str], ToolUsage]:
    """Search web using Gemini + Google Search Grounding.

    Uses REST API for simplicity (avoids extra google-genai dependency).

    Args:
        query: Search query
        num_results: Maximum number of results to return

    Returns:
        Tuple of (answer_text, list_of_citation_urls, tool_usage)

    Raises:
        ValueError: If GEMINI_API_KEY not set
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    # Get model from config, default to gemini-2.5-flash (2.0 deprecated March 2026)
    tool_config = get_tool_config("web_search")
    gemini_model = tool_config.get("gemini_model", "gemini-2.5-flash")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent"

    payload = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}]
    }

    # TLS via the shared resolver — this site also used to collapse the
    # setting to a bool, discarding any configured CA bundle.
    try:
        async with httpx.AsyncClient(verify=tls_verify()) as client:
            resp = await client.post(
                url,
                params={"key": api_key},
                json=payload,
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise ValueError(f"Gemini API error: {e}")

    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        grounding = data["candidates"][0].get("groundingMetadata", {})

        citations = []
        for chunk in grounding.get("groundingChunks", [])[:num_results]:
            if "web" in chunk:
                citations.append(chunk["web"]["uri"])

        # Per-query pricing
        usage = ToolUsage(
            call_count=1,
            provider="gemini"
        )
        usage.estimated_cost = calculate_tool_cost("gemini_grounding", query_count=1)

        return content, citations, usage
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"Failed to parse Gemini response: {e}")


def _format_search_result(
    backend: str, content: str, citations: List[str], fallback: bool = False
) -> str:
    """Provider tag at the beginning for visibility (v1.15.3 — not truncated)."""
    tag = f"[via {backend} (fallback)]" if fallback else f"[via {backend}]"
    result = f"{tag}\n\n{content.lstrip()}\n\nSources:\n"
    for url in citations:
        result += f"- {url}\n"
    return result


async def web_search_premium(query: str, num_results: int = 5, _provider_name: Optional[str] = None) -> str:
    """Search the web through the resolver's ordered backend chain.

    ADR 0009 step ④ / Q5: the chain IS `resolve_web_search_backend(...)`
    .candidates — first choice, then fallback, in the resolved order. A
    concrete `preferred` without `strict` orders the chain (e.g. gemini →
    perplexity → duckduckgo); under `strict: true` the tuple pins a single
    candidate and a failure returns an error instead of falling back — the
    egress allowlist only covers the pinned host, so cross-backend fallback
    would reach a host the run never allowlisted. (Pre-④, a failed
    preferred=gemini skipped perplexity entirely and dropped straight to
    DuckDuckGo — the resolver's ordering fixes that asymmetry too.)

    Args:
        query: Search query
        num_results: Maximum number of results to include
        _provider_name: (Internal) Current provider name for config lookup

    Returns:
        Formatted search result with sources
    """
    logger = logging.getLogger(__name__)
    # Item 59: narrow the chain to backends the run may reach (the egress guard
    # authorized the SAME narrowed set), so we never try a host the sandbox will
    # deny. None outside a sandboxed run → full chain, unchanged.
    resolution = resolve_web_search_backend(
        _provider_name, egress_allows=_egress_allows_holder.get()
    )
    last_error: Optional[Exception] = None

    for i, backend in enumerate(resolution.candidates):
        try:
            if backend == "perplexity":
                content, citations, usage = await web_search_perplexity(query, num_results)
                _record_usage(usage)
            elif backend == "gemini":
                content, citations, usage = await web_search_gemini(query, num_results)
                _record_usage(usage)
            else:  # duckduckgo — free search, formats its own output
                return web.web_search(query, num_results)
            return _format_search_result(backend, content, citations, fallback=i > 0)
        except Exception as e:
            last_error = e
            logger.warning(f"web_search backend failed ({backend}): {e}")
            if resolution.strict:
                # Q5: an operator setting `strict` accepted "this backend or
                # nothing"; the egress set covers only this backend's host.
                return (
                    f"[web_search error] The configured search backend "
                    f"'{backend}' failed and cross-backend fallback is "
                    f"disabled (tools.web_search strict pin, scope "
                    f"{resolution.scope}): {e}"
                )
            logger.info("Trying next backend in the resolved chain")

    # No candidate succeeded (or none usable at all).
    if last_error is not None:
        return f"[web_search error] Every configured backend failed: {last_error}"
    return web.web_search(query, num_results)


async def get_weather_premium(
    location: str, format: str = "short", _provider_name: Optional[str] = None
) -> str:
    """Weather via a three-tier chain: wttr.in → Open-Meteo → premium search.

    web_premium historically upgraded `web_search` to a premium provider but left
    `get_weather` on wttr.in with no fallback, so on a locked-egress host (or when
    wttr.in — a flaky community single-server service — is down) weather failed
    hard. The chain, in order of decreasing accuracy/preference:

      1. wttr.in         — purpose-built real-time weather, pretty one-line output.
      2. Open-Meteo      — professional-grade, key-free, accurate, global; the
                           right tier BEFORE a general web search (added v1.19.1).
      3. premium search  — perplexity/gemini scrape arbitrary pages and return
                           unreliable temperatures (observed live: stale 9-18°C on
                           a 30°C day), so this is the LAST resort, never preferred
                           — even when `tools.web_search.preferred` pins one for
                           SEARCH.

    Each direct source returns an 'Error: ...' string (never raises) on failure,
    so we advance to the next tier only when the current one errors. Where wttr.in
    is reachable, behavior is unchanged.
    """
    logger = logging.getLogger(__name__)

    result = web.get_weather(location, format)
    # web.get_weather returns an 'Error: ...' string on failure (never raises).
    if not result.lstrip().startswith("Error"):
        return result

    # Tier 2: Open-Meteo (reliable, key-free, accurate) before any web search.
    logger.info("wttr.in weather failed; trying open-meteo (reliable fallback)")
    om = web.get_weather_openmeteo(location, format)
    if not om.lstrip().startswith("Error"):
        return om

    # Tier 3: premium web search — last resort, only if a premium key exists.
    if is_available():
        logger.info(
            "wttr.in + open-meteo both failed; falling back to premium search "
            "(less accurate)"
        )
        query = (
            f"What is the current weather and today's forecast for {location}? "
            f"Give temperature, conditions, wind, and precipitation."
        )
        return await web_search_premium(query, 5, _provider_name=_provider_name)

    # No premium key: surface the open-meteo error (more informative than wttr.in's).
    return om


def get_last_tool_usage() -> Optional[ToolUsage]:
    """Get usage from last premium search call.

    LEGACY channel (v1.19.1 F4): process-global, reset-on-read — racy under
    concurrent runs (one caller can consume another's usage). The chat loop
    now uses begin_usage_capture()'s per-call holder instead; this remains
    only for back-compat readers.

    Returns:
        ToolUsage object or None if no premium search executed
    """
    global _last_tool_usage
    usage = _last_tool_usage
    _last_tool_usage = None  # Reset after extraction
    return usage


def register_tools(manager, provider=None):
    """Register premium web search if available.

    Supports per-provider configuration overrides and auto-detection.
    Skips registration for providers with native web search.

    Args:
        manager: ToolManager instance
        provider: Current provider name (e.g., 'perplexity', 'gemini', 'custom-vllm')
    """
    # Skip for providers with native search (Perplexity only)
    # NOTE: Gemini removed from skip list (v1.15.2) because grounding is disabled
    # when native function calling is active. Gemini needs web_search tool in agent mode.
    if provider == "perplexity":
        return

    # Only register if premium provider available
    if not is_available():
        # Fall back to free search
        web.register_tools(manager, provider)
        return

    # Determine which provider to use (with per-provider config support)
    premium_provider = get_premium_search_provider(provider)
    if premium_provider:
        description = f"Search the web using {premium_provider.title()} AI"
    else:
        description = "Search the web using premium AI (Perplexity or Gemini)"

    # Create wrapper that includes provider_name for config lookup
    async def web_search_with_provider(query: str, num_results: int = 5) -> str:
        """Wrapper that passes provider context to web_search_premium."""
        return await web_search_premium(query, num_results, _provider_name=provider)

    # Register with same interface as free search
    manager.register_function(
        name="web_search",
        description=description,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "num_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of results to include"
                }
            },
            "required": ["query"]
        },
        handler=web_search_with_provider,
        # Only exclude Perplexity (has native web search)
        # Gemini needs web_search tool in agent mode because grounding is disabled
        # when native function calling is active (Live API limitation)
        provider_excluded=["perplexity"]
    )

    # get_weather via the premium-aware wrapper (v1.19.1): wttr.in when reachable,
    # premium provider (perplexity/gemini) as fallback or when pinned — so weather
    # works wherever web_search does (matches the search backend policy).
    async def get_weather_with_provider(location: str, format: str = "short") -> str:
        return await get_weather_premium(location, format, _provider_name=provider)

    manager.register_function(
        name="get_weather",
        description="Get current weather and forecast for a location",
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name, optionally with country (e.g., 'Geneva', 'Geneva,Switzerland', 'New York', 'Tokyo')"
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'short' (one line), 'detailed' (current only), 'forecast' (2-day forecast)",
                    "enum": ["short", "detailed", "forecast"]
                }
            },
            "required": ["location"]
        },
        handler=get_weather_with_provider,
        provider_excluded=["perplexity"]  # Perplexity has native weather via grounding
    )

    manager.register_function(
        name="fetch_url",
        description="Fetch and read the text content of a web page URL",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch (e.g., 'https://example.com/page')"
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum characters to return (default: 5000)"
                }
            },
            "required": ["url"]
        },
        handler=web.fetch_url,
        provider_excluded=["perplexity"]  # Perplexity can fetch URLs via search
    )
