"""Resolve Gemini's grounding redirect links to the pages they point at
(ADR 0019, owner decision 2026-11-21).

Gemini's search results cite `https://vertexaisearch.cloud.google.com/
grounding-api-redirect/<token>` links, not the source pages, and the
links expire. A source stored in a conversation, a run or an export must
still open later, so each redirect is looked up once, when the search
returns: one GET to the redirect host, NOT following it, and the
`Location` header is the page's real address. The target page itself is
never fetched.

Best effort, never fatal: a lookup that fails, times out, answers without
a usable `Location`, or is outside the caller's egress predicate keeps the
redirect link as it was. Only the redirect host is contacted, and only
when the caller's `egress_allows` (the run's network policy, or the
deployment's egress ceiling) allows it; with no predicate (an unconfined
chat turn) it is allowed. A run that wants resolved links lists
`vertexaisearch.cloud.google.com` in its allowlist.

The redirect host is deliberately NOT in `BACKEND_HOSTS["gemini"]`: the
resolver requires ALL of a backend's hosts to pass a run's egress
predicate, so adding it there would drop Gemini search from every run
that allows only the API host.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from ppxai.config.tls import tls_verify

from .types import SearchResult

logger = logging.getLogger(__name__)

REDIRECT_HOST = "vertexaisearch.cloud.google.com"
REDIRECT_PATH = "/grounding-api-redirect/"

#: Per lookup. A slow lookup must not hold up the answer for long.
TIMEOUT_S = 4.0

#: Resolved links, so the same redirect in a later search of the process
#: costs nothing. Bounded; oldest dropped first.
_CACHE: OrderedDict[str, str] = OrderedDict()
_CACHE_MAX = 512


def is_grounding_redirect(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname == REDIRECT_HOST
        and parts.path.startswith(REDIRECT_PATH)
    )


def _make_client() -> httpx.AsyncClient:
    """The client the lookups use (tests swap in a mock transport)."""
    return httpx.AsyncClient(verify=tls_verify())


async def _lookup(client: httpx.AsyncClient, url: str) -> str | None:
    """The redirect's `Location`, or None. Never raises."""
    try:
        resp = await client.get(url, follow_redirects=False, timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — best effort
        logger.info(f"grounding redirect lookup failed: {exc}")
        return None
    location = resp.headers.get("location") if 300 <= resp.status_code < 400 else None
    if not location:
        return None
    try:
        target = urlsplit(location)
    except ValueError:
        return None
    if target.scheme not in ("http", "https") or not target.hostname:
        return None
    return location


async def resolve_redirects(
    urls: list[str], egress_allows: Callable[[str], bool] | None = None
) -> list[str]:
    """`urls` with every Gemini grounding redirect replaced by its target,
    where it can be looked up. Order and length are unchanged."""
    todo = [u for u in dict.fromkeys(urls) if is_grounding_redirect(u) and u not in _CACHE]
    if todo and (egress_allows is None or egress_allows(REDIRECT_HOST)):
        async with _make_client() as client:
            found = await asyncio.gather(*(_lookup(client, u) for u in todo))
        for url, target in zip(todo, found):
            if target:
                _CACHE[url] = target
                while len(_CACHE) > _CACHE_MAX:
                    _CACHE.popitem(last=False)
    return [_CACHE.get(u, u) for u in urls]


async def resolve_result(
    result: SearchResult, egress_allows: Callable[[str], bool] | None = None
) -> SearchResult:
    """`result` with its citations resolved (titles stay parallel)."""
    if not any(is_grounding_redirect(u) for u in result.citations):
        return result
    try:
        resolved = await resolve_redirects(list(result.citations), egress_allows)
    except Exception as exc:  # noqa: BLE001 — never fail a search over this
        logger.warning(f"grounding redirect resolution failed: {exc}")
        return result
    return dataclasses.replace(result, citations=resolved)
