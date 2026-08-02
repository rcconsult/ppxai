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

from ppxai.config import get_tool_config, get_tool_pricing, get_provider_config
from ...types import ToolUsage
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
    """Determine which premium search provider to use.

    Priority:
    1. Per-provider config override (if specified in provider config)
    2. Global tools.web_search.preferred setting
    3. Auto-detect: Perplexity > Gemini > None

    Args:
        provider_name: Current provider name (to check for provider-specific config)

    Returns:
        "perplexity", "gemini", or None if no premium provider available
    """
    # Check for per-provider override
    if provider_name:
        try:
            provider_config = get_provider_config(provider_name)
            provider_web_search = provider_config.get("web_search", {})
            preferred = provider_web_search.get("preferred")

            if preferred and preferred != "auto":
                # Explicit provider specified for this provider
                if preferred == "perplexity" and os.getenv("PERPLEXITY_API_KEY"):
                    return "perplexity"
                elif preferred == "gemini" and os.getenv("GEMINI_API_KEY"):
                    return "gemini"
                elif preferred == "duckduckgo":
                    return None  # Use free search
                # If specified provider key not available, fall through to auto-detect
        except Exception:
            pass  # Fall through to global config

    # Check global tools.web_search.preferred setting
    try:
        tool_config = get_tool_config("web_search")
        preferred = tool_config.get("preferred", "auto")

        if preferred != "auto":
            # Explicit provider specified globally
            if preferred == "perplexity" and os.getenv("PERPLEXITY_API_KEY"):
                return "perplexity"
            elif preferred == "gemini" and os.getenv("GEMINI_API_KEY"):
                return "gemini"
            elif preferred == "duckduckgo":
                return None  # Use free search
            # If specified provider key not available, fall through to auto-detect
    except Exception:
        pass  # Fall through to auto-detect

    # Auto-detect: Perplexity > Gemini > None
    if os.getenv("PERPLEXITY_API_KEY"):
        return "perplexity"
    elif os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return None


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

    # Respect SSL_VERIFY setting (for corporate proxies with SSL inspection)
    ssl_verify = os.getenv("SSL_VERIFY", "true").lower() != "false"
    http_client = None
    if not ssl_verify:
        http_client = httpx.AsyncClient(verify=False)

    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.perplexity.ai",
        http_client=http_client
    )

    response = await client.chat.completions.create(
        model=perplexity_model,
        messages=[{"role": "user", "content": query}]
    )

    content = response.choices[0].message.content
    citations = getattr(response, 'citations', [])[:num_results]

    # Calculate cost
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

    # Respect SSL_VERIFY setting (for corporate proxies with SSL inspection)
    ssl_verify = os.getenv("SSL_VERIFY", "true").lower() != "false"

    try:
        async with httpx.AsyncClient(verify=ssl_verify) as client:
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


async def web_search_premium(query: str, num_results: int = 5, _provider_name: Optional[str] = None) -> str:
    """Search web using best available premium provider.

    Auto-detects premium provider (Perplexity > Gemini), falls back to DuckDuckGo.
    Supports per-provider configuration overrides.

    Args:
        query: Search query
        num_results: Maximum number of results to include
        _provider_name: (Internal) Current provider name for config lookup

    Returns:
        Formatted search result with sources
    """
    provider = get_premium_search_provider(_provider_name)

    # When the operator PINS a backend via tools.web_search.preferred, the
    # egress policy narrows web_search's allowlisted target set to that one
    # backend (network_policy.pinned_web_search_backend). Cross-backend
    # fallback would then try to reach a host the run never allowlisted (e.g.
    # a pinned-perplexity failure silently hitting DuckDuckGo), so it is
    # forbidden here: a pinned backend either succeeds on its own host or
    # returns an error. "auto" (unpinned) keeps the full fallback chain.
    from ..network_policy import pinned_web_search_backend
    pinned = pinned_web_search_backend()

    try:
        if provider == "perplexity":
            content, citations, usage = await web_search_perplexity(query, num_results)
            _record_usage(usage)
        elif provider == "gemini":
            content, citations, usage = await web_search_gemini(query, num_results)
            _record_usage(usage)
        else:
            # Fall back to free DuckDuckGo
            return web.web_search(query, num_results)

        # Format result with provider tag at the beginning for visibility
        tag = f"[via {provider}]"
        result = f"{tag}\n\n{content.lstrip()}\n\nSources:\n"
        for url in citations:
            result += f"- {url}\n"
        return result

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Premium search failed ({provider}): {e}")

        # Pinned backend: no cross-backend fallback (see note above) — the
        # egress allowlist only covers the pinned host.
        if pinned:
            return (
                f"[web_search error] The configured search backend "
                f"'{pinned}' failed and cross-backend fallback is disabled "
                f"(tools.web_search.preferred={pinned}): {e}"
            )

        # Auto mode fall-back chain: Perplexity -> Gemini -> DuckDuckGo (v1.15.2)
        # If Perplexity failed, try Gemini as fallback before DuckDuckGo
        if provider == "perplexity" and os.getenv("GEMINI_API_KEY"):
            try:
                logger.info("Trying Gemini grounding as fallback")
                content, citations, usage = await web_search_gemini(query, num_results)
                _record_usage(usage)
                # v1.15.3: Tag at beginning for visibility (not truncated)
                tag = "[via gemini (fallback)]"
                result = f"{tag}\n\n{content.lstrip()}\n\nSources:\n"
                for url in citations:
                    result += f"- {url}\n"
                return result
            except Exception as gemini_error:
                logger.warning(f"Gemini fallback also failed: {gemini_error}")

        # Final fallback to DuckDuckGo
        logger.info("Falling back to DuckDuckGo")
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
