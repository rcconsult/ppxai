"""Gemini Google-Search-Grounding backend (ADR 0014 Decision 1).

Moved out of `tools/builtin/web_premium.py` unchanged in behaviour. Uses
the REST API directly (avoids the extra `google-genai` dependency) — this
is NOT the Gemini chat provider.
"""

from __future__ import annotations

import os

import httpx

from ppxai.config import get_tool_config
from ppxai.config.tls import tls_verify

from ..types import ToolUsage
from .pricing import calculate_tool_cost
from .resolver import BACKEND_HOSTS
from .types import SearchResult


async def search_gemini(query: str, num_results: int = 5) -> tuple[str, list[str], ToolUsage]:
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

    # Get model from config. Default is gemini-3.6-flash since 2026-08-31:
    # the 2.5 line has a sunset date (EARLIEST 2026-10-16, ai.google.dev), and
    # this default is CODE, not user config — the web_search fallback backend
    # would have died on sunset for everyone who never set the key. 3.6-flash
    # is GA and was smoke-tested live on this path (generateContent +
    # google_search, grounding chunks returned) before the swap. See debt
    # Item 54.
    tool_config = get_tool_config("web_search")
    gemini_model = tool_config.get("gemini_model", "gemini-3.6-flash")

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


class GeminiBackend:
    """`SearchBackend` for Gemini Google Search Grounding (REST)."""

    id = "gemini"
    hosts: tuple[str, ...] = tuple(BACKEND_HOSTS["gemini"])

    def usable(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))

    async def search(self, query: str, n: int = 5) -> SearchResult:
        content, citations, usage = await search_gemini(query, n)
        return SearchResult(backend=self.id, answer=content, citations=citations, usage=usage)
