"""DuckDuckGo search backend (ADR 0014 Decision 1).

The free, key-free fallback. The actual search (`ddgs`/`duckduckgo_search`
package, or HTML-scrape fallback) stays in
`tools/builtin/web.py::web_search` — that module also registers it
directly as the "web_search" tool for providers with no premium key, so
the implementation is not duplicated here. This backend wraps it unchanged
in behaviour.
"""

from __future__ import annotations

from ..tools.builtin import web
from .resolver import BACKEND_HOSTS
from .types import SearchResult


class DuckDuckGoBackend:
    """`SearchBackend` for DuckDuckGo.

    Unlike the premium backends, `web.web_search` already returns the
    COMPLETE, final tool-visible string (its own "[via duckduckgo] ..."
    formatting) rather than raw prose + citations. `answer` here carries
    that pre-formatted string; a caller that wants the exact pre-refactor
    `web_search_premium` behaviour uses it as-is, without
    `_format_search_result` wrapping and without a fallback tag — the
    adapter in `tools/builtin/web_premium.py` preserves that special case.
    """

    id = "duckduckgo"
    hosts: tuple[str, ...] = tuple(BACKEND_HOSTS["duckduckgo"])

    def usable(self) -> bool:
        return True

    async def search(self, query: str, n: int = 5) -> SearchResult:
        return SearchResult(
            backend=self.id, answer=web.web_search(query, n), citations=[], usage=None
        )
