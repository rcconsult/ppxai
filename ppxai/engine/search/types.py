"""Search layer core types (ADR 0014 Decision 1).

`SearchBackend` is a `Protocol`: any object with `id`, `hosts`, `usable()`
and an async `search()` satisfies it, so a backend needs no shared base
class. Nothing here (or anywhere under `ppxai/engine/search/`) imports
`ppxai.engine.providers` — fenced by
`tests/test_search_layer_imports_no_providers.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..types import ToolUsage


@dataclass(frozen=True)
class SearchResult:
    """One backend's answer to one query.

    `titles` runs parallel to `citations` and may be empty. Gemini fills it:
    its citation URLs are opaque `vertexaisearch.cloud.google.com` redirects,
    and the title (the source's domain) is the only readable part.
    """

    backend: str
    answer: str
    citations: list[str]
    usage: ToolUsage | None
    titles: list[str] = field(default_factory=list)

    def sources(self, limit: int) -> list[tuple[str, str | None]]:
        """The first `limit` citations as `(url, title-or-None)` pairs."""
        return [
            (url, self.titles[i] if i < len(self.titles) and self.titles[i] else None)
            for i, url in enumerate(self.citations[:limit])
        ]


@runtime_checkable
class SearchBackend(Protocol):
    """A provider-independent web-search backend."""

    id: str
    hosts: tuple[str, ...]

    def usable(self) -> bool:
        """True when the backend can run now (e.g. its API key is set)."""
        ...

    async def search(self, query: str, n: int) -> SearchResult:
        """Run one search and return its result. May raise on failure —
        callers (the web_search adapter, future grounding) walk the
        resolved candidate chain and decide fallback there."""
        ...
