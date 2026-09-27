"""The search layer (ADR 0014 Decision 1): web search as its own package,
independent of any chat provider.

`get_backend(id)` is the one place a caller turns a resolved backend id
(from `resolve_web_search_backend`'s `candidates`) into a `SearchBackend`
instance. Nothing under this package imports `ppxai.engine.providers` —
fenced by `tests/test_search_layer_imports_no_providers.py`.
"""

from __future__ import annotations

from .duckduckgo import DuckDuckGoBackend
from .gemini import GeminiBackend
from .perplexity import PerplexityBackend
from .resolver import BackendResolution, resolve_web_search_backend
from .types import SearchBackend, SearchResult

#: Every backend id the resolver may name, in the order they were added.
BACKEND_IDS: tuple[str, ...] = ("perplexity", "gemini", "duckduckgo")

_REGISTRY: dict[str, type] = {
    "perplexity": PerplexityBackend,
    "gemini": GeminiBackend,
    "duckduckgo": DuckDuckGoBackend,
}


def get_backend(backend_id: str) -> SearchBackend:
    """Return a fresh backend instance for `backend_id`.

    Raises `KeyError` for an unknown id — callers only ever pass ids drawn
    from `resolve_web_search_backend(...).candidates`, which are already
    validated against the known backend set.
    """
    return _REGISTRY[backend_id]()


__all__ = [
    "SearchBackend",
    "SearchResult",
    "BackendResolution",
    "BACKEND_IDS",
    "get_backend",
    "resolve_web_search_backend",
]
