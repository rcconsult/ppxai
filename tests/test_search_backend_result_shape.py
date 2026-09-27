"""Every search backend answers the chain in one shape.

The raw backend functions return different tuples (`search_gemini` adds
titles; `search_perplexity` does not), so each is unpacked in exactly one
place: its own `SearchBackend.search()` adapter. Every caller in the chain
(`grounding.retrieve`, `web_premium.web_search_premium`) goes through
`get_backend(id).search()`. This drives each registered backend through that
one call site, with its raw function stubbed, and checks the result.
"""

from __future__ import annotations

import pytest

from ppxai.engine.search import BACKEND_IDS, SearchResult, get_backend
from ppxai.engine.search import duckduckgo as ddg_backend
from ppxai.engine.search import gemini as gemini_backend
from ppxai.engine.search import perplexity as pplx_backend
from ppxai.engine.types import ToolUsage


async def _gemini(query, num_results=5):
    return "g", ["https://r/1"], ToolUsage(call_count=1, provider="gemini"), ["python.org"]


async def _perplexity(query, num_results=5):
    return "p", ["https://python.org/"], ToolUsage(call_count=1, provider="perplexity")


def _ddg(query, num_results=5):
    return "d"


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(gemini_backend, "search_gemini", _gemini)
    monkeypatch.setattr(pplx_backend, "search_perplexity", _perplexity)
    monkeypatch.setattr(ddg_backend.web, "web_search", _ddg)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_id", BACKEND_IDS)
async def test_every_backend_returns_a_search_result(stubbed, backend_id):
    result = await get_backend(backend_id).search("q", 3)
    assert isinstance(result, SearchResult)
    assert result.backend == backend_id
    assert isinstance(result.titles, list)
    # titles is parallel to citations or empty, so sources() never misaligns.
    assert len(result.titles) in (0, len(result.citations))
    assert [url for url, _ in result.sources(5)] == result.citations


@pytest.mark.asyncio
async def test_only_gemini_carries_titles(stubbed):
    assert (await get_backend("gemini").search("q")).sources(5) == [
        ("https://r/1", "python.org")
    ]
    assert (await get_backend("perplexity").search("q")).sources(5) == [
        ("https://python.org/", None)
    ]
