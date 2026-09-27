"""Perplexity Sonar search backend (ADR 0014 Decision 1).

Moved out of `tools/builtin/web_premium.py` unchanged in behaviour. This
module owns Sonar API access for `web_search` and retrieval grounding. It
never depended on the Perplexity chat provider, which ADR 0015 removed; its
wire comes from `perplexity_facts.py`.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from openai import AsyncOpenAI

from ppxai.config import get_tool_config
from ppxai.config.tls import tls_verify
from ppxai.constants import APIEndpoint

from ..model_facts import shipped_facts_for_model
from ..types import ToolUsage
from .perplexity_facts import SEARCH_MODEL_FACTS
from .pricing import calculate_tool_cost
from .resolver import BACKEND_HOSTS
from .types import SearchResult

#: Perplexity's two wires. The chat host is the shared constant; the
#: Responses wire lives one path segment deeper (measured — the bare host
#: 404s on `/responses`).
PERPLEXITY_CHAT_BASE_URL = APIEndpoint.PERPLEXITY_API
PERPLEXITY_RESPONSES_BASE_URL = APIEndpoint.PERPLEXITY_API.rstrip("/") + "/v1"


def _output_item_url_rows(item: Any) -> list[Any]:
    """Return the `results` rows of a `search_results` output item, if any.

    Reads attributes directly off the SDK object instead of a dict — see
    `_responses_answer_and_citations` for why `model_dump()` is avoided here.
    Falls back to a dict-shaped item so a hand-built fake in tests still works.
    """
    if isinstance(item, dict):
        if item.get("type") != "search_results":
            return []
        return list(item.get("results") or [])
    if getattr(item, "type", None) != "search_results":
        return []
    return list(getattr(item, "results", None) or [])


def _row_url(row: Any) -> str | None:
    if isinstance(row, dict):
        return row.get("url")
    return getattr(row, "url", None)


def _responses_answer_and_citations(response, num_results: int):
    """Pull answer text and citation URLs out of a Responses reply.

    MEASURED 2026-08-30 (plan W0 (c)): citations arrive as a
    `search_results` OUTPUT ITEM carrying `{id, snippet, date, url}` rows.
    The text block's `annotations` array stays **empty** on this wire, so
    reading annotations — the obvious guess — silently yields no citations.

    MEASURED 2026-09-16: Perplexity's `search_results` item type isn't in
    the openai SDK's `Response.output` union (message / function_call /
    reasoning / ...), so pydantic parses it via a best-effort fallback whose
    declared `type` literal doesn't match the actual string. That's harmless
    for reading attributes off the live object, but calling `.model_dump()`
    (as this used to, to get a plain dict) makes pydantic re-validate the
    mismatch and print a `PydanticSerializationUnexpectedValue` warning to
    stderr on every call. Fix: walk `response.output` directly via getattr/
    duck-typing instead of dumping the whole typed union to a dict.
    """
    output_items = list(getattr(response, "output", None) or [])

    citations: list[str] = []
    for item in output_items:
        for row in _output_item_url_rows(item):
            url = _row_url(row)
            if url and url not in citations:
                citations.append(url)

    content = getattr(response, "output_text", None) or ""
    if not content:
        parts = []
        for item in output_items:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if item_type != "message":
                continue
            item_content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            for part in item_content or []:
                part_type = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
                if part_type == "output_text":
                    part_text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                    parts.append(part_text or "")
        content = "".join(parts)

    return content, citations[:num_results]


async def search_perplexity(query: str, num_results: int = 5) -> tuple[str, list[str], ToolUsage]:
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

    # Get model from config. Default is the Responses-wire id: the
    # chat-completions `sonar` wire retires 2026-09-27, and a code default
    # outlives every user's config (see TestCodeDefaultsAreNotDeprecatedModels
    # in tests/test_web_premium_wire.py) — so the default must name the
    # surviving wire, not the cheapest-looking legacy one.
    tool_config = get_tool_config("web_search")
    perplexity_model = tool_config.get("perplexity_model", "perplexity/sonar")

    # ADR 0012 W3: which wire this model speaks is a per-model FACT, resolved
    # from `perplexity_facts.SEARCH_MODEL_FACTS`. It lived outside the chat
    # provider class so this backend survived that provider's removal (ADR
    # 0015). This tool used to build
    # its own client hardcoded to `/chat/completions`, which meant the
    # 2026-09-27 Sonar retirement would break web_search independently of the
    # provider — a second path to patch instead of one path to fix. Reading
    # the fact here is the root-cause fix: configure `perplexity/sonar` and
    # this tool follows the provider onto the surviving wire with no code
    # change.
    wire = shipped_facts_for_model(
        perplexity_model, SEARCH_MODEL_FACTS
    ).wire_protocol

    # TLS via the shared resolver. This site previously honoured SSL_VERIFY
    # but ignored SSL_CERT_FILE, so a custom-CA install silently verified
    # against the system store here while every other client used the bundle.
    #
    # `async with` because AsyncOpenAI never closes a caller-supplied
    # http_client — an unclosed AsyncClient here leaked its connection
    # pool on every web_search call in a long-lived server. Same pattern
    # as search_gemini below.
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


class PerplexityBackend:
    """`SearchBackend` for Perplexity Sonar."""

    id = "perplexity"
    hosts: tuple[str, ...] = tuple(BACKEND_HOSTS["perplexity"])

    def usable(self) -> bool:
        return bool(os.getenv("PERPLEXITY_API_KEY"))

    async def search(self, query: str, n: int = 5) -> SearchResult:
        content, citations, usage = await search_perplexity(query, n)
        return SearchResult(backend=self.id, answer=content, citations=citations, usage=usage)
