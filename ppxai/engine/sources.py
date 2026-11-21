"""One citation contract (ADR 0019): the engine's notion of a source.

A `Source` is one web page an answer may cite as `[n]`. A `SourceLedger`
holds the sources of ONE turn (one user message up to the final assistant
message, tool calls included; a `/run` or a `/task` run is one turn) and
hands out the numbers: every producer — retrieval grounding, the
`web_search` tool, Gemini's built-in grounding — adds to the ledger and
cites the number it gets back, so `[n]` means the same source wherever it
appears in the turn. Numbering starts at 1 per turn; a URL already in the
ledger keeps its first number.

The turn's ledger reaches a tool through a ContextVar (`install_ledger`,
`current_ledger`), the same mechanism `web_premium.begin_usage_capture`
uses for search cost: the chat loop installs it before creating the tool
task, the task inherits a copy of the context, and the ledger object is
shared.

This module imports nothing from ppxai on purpose: the search backends, the
tools (`tools/builtin/web.py`, which `engine/search/duckduckgo.py` imports)
and `engine/types.py` all use it, so it must not import any of them.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Source:
    """One source an answer may cite as `[n]`."""

    n: int
    url: str
    #: Gemini: the source's domain, beside an opaque redirect URL.
    title: str | None = None
    #: The search backend or provider that found it ("gemini", "perplexity", ...).
    backend: str | None = None
    #: The search that found it.
    query: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Source:
        known = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


class SourceLedger:
    """The numbered sources of one turn."""

    def __init__(self) -> None:
        self._sources: list[Source] = []
        self._by_url: dict[str, Source] = {}

    @classmethod
    def from_dicts(cls, rows: Iterable[dict[str, Any]] | None) -> SourceLedger:
        """A ledger continuing from stored rows (a resumed `/task` run keeps
        its numbers). Rows keep their own `n`; new URLs number on from the
        highest."""
        ledger = cls()
        for row in rows or ():
            if isinstance(row, dict) and row.get("url"):
                source = Source.from_dict(row)
                ledger._sources.append(source)
                ledger._by_url[source.url] = source
        return ledger

    def add(
        self,
        url: str,
        title: str | None = None,
        *,
        backend: str | None = None,
        query: str | None = None,
    ) -> Source:
        """Register `url` and return its `Source`. A URL already in the
        ledger returns the existing entry, number unchanged."""
        existing = self._by_url.get(url)
        if existing is not None:
            return existing
        source = Source(
            n=max((s.n for s in self._sources), default=0) + 1,
            url=url, title=title or None, backend=backend, query=query,
        )
        self._sources.append(source)
        self._by_url[url] = source
        return source

    @property
    def sources(self) -> list[Source]:
        return list(self._sources)

    def to_dicts(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._sources]

    def __len__(self) -> int:
        return len(self._sources)


def number_sources(
    pairs: Iterable[tuple[str, str | None]],
    ledger: SourceLedger | None,
    *,
    backend: str | None = None,
    query: str | None = None,
) -> list[int]:
    """The `[n]` for each `(url, title)` in `pairs`.

    With a ledger, each URL is added to it and gets the ledger's number.
    Without one (a caller outside any turn), they are numbered 1, 2, ... so
    the text still reads the same way."""
    pairs = list(pairs)
    if ledger is None:
        return list(range(1, len(pairs) + 1))
    return [ledger.add(url, title, backend=backend, query=query).n for url, title in pairs]


def sources_from_rows(rows: Iterable[dict[str, Any]] | None) -> list[Source]:
    """Stored `{n, url, ...}` rows (a run's meta, a session file) back as
    `Source`s, skipping anything malformed."""
    return [
        Source.from_dict(r) for r in rows or ()
        if isinstance(r, dict) and r.get("url") and isinstance(r.get("n"), int)
    ]


_ledger_holder: contextvars.ContextVar[SourceLedger | None] = contextvars.ContextVar(
    "turn_source_ledger", default=None
)


def install_ledger(ledger: SourceLedger | None) -> SourceLedger | None:
    """Install (and return the prior) turn ledger on the current context.
    Call BEFORE creating the tool task, so the task's context copy sees it."""
    prior = _ledger_holder.get()
    _ledger_holder.set(ledger)
    return prior


def current_ledger() -> SourceLedger | None:
    """The turn ledger a tool should number its sources from, or None."""
    return _ledger_holder.get()
