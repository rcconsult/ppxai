"""The ONE shared web_search backend resolver (ADR 0009 step ④, sign-off Q5).

Before this module, two resolvers answered "which search backend?" from
different config views and disagreed (ADR 0009 Problem 4):

- ``web_premium.get_premium_search_provider(provider_name)`` — provider-aware
  (per-provider override > global > auto-detect), used at CALL time;
- ``network_policy.pinned_web_search_backend()`` — global-only, used to
  narrow the EGRESS set.

Under a per-provider override the handler could pick one backend while the
egress allowlist narrowed to another — either an allowlist bypass (the
confused-deputy case AC-2 exists to prevent) or a false denial, depending on
the run's ``allow_outbound``. Both modules now import THIS leaf (no imports
from either of them, so no cycle) and read one structured answer.

Q5 settled semantics implemented here:

- ``preferred`` is an **ordering** (first-choice-then-fall-back), NOT a hard
  pin. Narrowing exists only via an explicit ``strict: true``.
- ``preferred`` and ``strict`` resolve **together, as one scoped tuple** —
  a scope is selected first, then BOTH fields are read from it:
    * the provider block (``providers.<name>.web_search``) IF it states
      ``preferred`` — ``strict`` read from the same block, default false;
    * else the global ``tools.web_search`` block;
    * defaults when neither states them: ``preferred="auto"``,
      ``strict=false``.
  A per-provider ``strict`` without a per-provider ``preferred`` is a DEAD
  KEY by construction (surfaced as a warning; ``/doctor`` flags it).
- Fail-safe (pre-existing, preserved): a preferred premium backend whose API
  key is absent is no preference at all — never narrow egress (or starve the
  chain) on a config that can't take effect.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Backend catalog — the single source for backend ids, hosts and key envs.
# (network_policy re-exports these under its historical names.)
# ---------------------------------------------------------------------------

BACKEND_HOSTS: Dict[str, List[str]] = {
    "perplexity": ["https://api.perplexity.ai/"],
    "gemini": ["https://generativelanguage.googleapis.com/"],
    "duckduckgo": ["https://duckduckgo.com/", "https://html.duckduckgo.com/"],
}

BACKEND_ENV: Dict[str, Optional[str]] = {
    "perplexity": "PERPLEXITY_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "duckduckgo": None,  # key-free
}

# Auto-detect order (Perplexity > Gemini > DuckDuckGo) — the historical chain,
# and the DEFAULT for `tools.web_search.order` (see `_read_order`). It is the
# fallback when no order is configured, not a hardcoded chain: an operator who
# writes `"order": ["gemini", "duckduckgo", "perplexity"]` gets exactly that
# sequence, in the one resolver both the call-time chain and the egress
# enumeration consume.
AUTO_ORDER: Tuple[str, ...] = ("perplexity", "gemini", "duckduckgo")

ALL_HOSTS: List[str] = [
    "https://duckduckgo.com/",
    "https://html.duckduckgo.com/",
    "https://api.perplexity.ai/",
    "https://generativelanguage.googleapis.com/",
]


def backend_usable(backend: str) -> bool:
    """A backend is usable when it needs no key or its key env is set."""
    env = BACKEND_ENV.get(backend)
    return env is None or bool(os.getenv(env))


@dataclass(frozen=True)
class BackendResolution:
    """The structured answer both consumers read (ADR 0009 step ④).

    ``scope`` is the field that makes the Q5 tuple auditable — a reviewer or
    a ``/doctor`` check can see WHY a backend was chosen, which is the
    structural reason the global-vs-provider divergence cannot quietly
    return.
    """

    scope: str                       # "provider:<name>" | "global" | "default"
    preferred: str                   # effective preference ("auto" after fail-safe)
    strict: bool                     # effective strictness (False when fail-safed)
    candidates: Tuple[str, ...]      # ordered, USABLE backends the chain may try
    egress_hosts: Tuple[str, ...]    # effective egress URL set for authorize()
    warnings: Tuple[str, ...] = ()   # fail-safe / dead-key / unknown-name notes


def _read_order(block: Dict[str, object], warnings: List[str]) -> Tuple[str, ...]:
    """The configured backend chain, or `AUTO_ORDER` when unset.

    `tools.web_search.order` is DATA for the one resolver — deliberately not
    a second mechanism beside `preferred`. `preferred` still names the first
    choice; `order` names the rest of the chain and the sequence the fallback
    walks. They fold together in `resolve_web_search_backend`, so the
    call-time chain and the egress enumeration read the same tuple and cannot
    drift (debt Item 59's seam).

    Unknown ids are dropped with a warning rather than raising: a typo in a
    config file must not take web_search offline. Known backends the operator
    omitted are appended in `AUTO_ORDER` sequence, so an order of
    `["gemini"]` still falls back rather than becoming an implicit strict pin
    — `strict: true` is how one says "only this one", and it stays the only
    way to say it.
    """
    raw = block.get("order")
    if raw is None:
        return AUTO_ORDER
    if not isinstance(raw, (list, tuple)):
        warnings.append(
            "tools.web_search.order must be a list of backend ids "
            f"(got {type(raw).__name__}) — using the default order"
        )
        return AUTO_ORDER

    seen: List[str] = []
    for entry in raw:
        name = str(entry)
        if name not in BACKEND_HOSTS:
            warnings.append(
                f"unknown web_search backend {name!r} in tools.web_search.order "
                f"(known: {', '.join(sorted(BACKEND_HOSTS))}) — ignored"
            )
            continue
        if name not in seen:
            seen.append(name)
    if not seen:
        warnings.append(
            "tools.web_search.order named no known backend — using the default order"
        )
        return AUTO_ORDER
    # Append anything the operator left out, so the chain stays a full
    # fallback ladder. Narrowing is `strict`'s job, not `order`'s.
    return tuple(seen) + tuple(b for b in AUTO_ORDER if b not in seen)


def _read_scope(
    provider_name: Optional[str],
) -> Tuple[str, str, bool, Tuple[str, ...], List[str]]:
    """Select the (scope, preferred, strict, order) tuple per Q5. Never raises."""
    warnings: List[str] = []
    # Provider block first — it owns the tuple ONLY if it states `preferred`.
    if provider_name:
        try:
            from ...config import get_provider_config

            block = (get_provider_config(provider_name) or {}).get(
                "web_search", {}
            ) or {}
        except Exception:
            block = {}
        if block.get("preferred"):
            return (
                f"provider:{provider_name}",
                str(block["preferred"]),
                bool(block.get("strict", False)),
                _read_order(block, warnings),
                warnings,
            )
        if "strict" in block:
            # Q5: out of scope by construction — never silently effective.
            warnings.append(
                f"providers.{provider_name}.web_search.strict is a dead key "
                "without a per-provider `preferred` in the same block"
            )
    try:
        from ...config import get_tool_config

        g = get_tool_config("web_search") or {}
    except Exception:
        g = {}
    preferred = str(g.get("preferred", "auto") or "auto")
    strict = bool(g.get("strict", False))
    order = _read_order(g, warnings)
    scope = (
        "global"
        if (g.get("preferred") or "strict" in g or "order" in g)
        else "default"
    )
    return scope, preferred, strict, order, warnings


def _backend_hosts_all_allowed(
    backend: str, egress_allows: Callable[[str], bool]
) -> bool:
    """True iff EVERY host a backend contacts is permitted by the run's
    allowlist. web_search's egress is authorized under the superset rule
    (network_policy.authorize), so a backend is only usable when ALL of its
    hosts pass — a partially-allowed backend would still be denied at the
    chokepoint."""
    hosts = BACKEND_HOSTS.get(backend, ())
    return bool(hosts) and all(egress_allows(_host_of(u)) for u in hosts)


def _host_of(url: str) -> str:
    """Bare hostname of a backend URL (``https://api.perplexity.ai/`` →
    ``api.perplexity.ai``). Backend URLs are static and well-formed, so a
    light parse is enough and avoids an ``urllib`` import in this leaf."""
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0].lower()


def resolve_web_search_backend(
    provider_name: Optional[str] = None,
    egress_allows: Optional[Callable[[str], bool]] = None,
) -> BackendResolution:
    """Resolve the web_search backend tuple for this provider context.

    Both the call-time chain (``web_premium``) and the egress enumeration
    (``network_policy.tool_targets``) consume this one answer, so the backend
    the handler contacts and the host set the allowlist was checked against
    can never diverge again.

    ``egress_allows`` (Item 59): when a run narrows egress below the global
    web_search superset — a sandboxed ``/task`` run whose ``task_default_allow``
    permits only ``api.perplexity.ai`` — pass a host-predicate here. Any
    backend whose hosts are NOT all permitted is dropped from ``candidates``
    AND ``egress_hosts``, so the chain never *tries* a host the sandbox will
    deny (the divergence a soft ``preferred:perplexity`` + perplexity-only
    task allowlist otherwise produced: DDG fallback → ``egress denied
    duckduckgo.com`` → no live data). Without it (chat, unconfined runs) the
    resolution is unchanged — the honest global superset.
    """
    scope, preferred, strict, order, warnings = _read_scope(provider_name)

    if preferred != "auto" and preferred not in BACKEND_HOSTS:
        warnings.append(
            f"unknown web_search backend {preferred!r} (known: "
            f"{', '.join(sorted(BACKEND_HOSTS))}) — treating as auto"
        )
        preferred, strict = "auto", False

    if preferred != "auto" and not backend_usable(preferred):
        # Fail-safe: never narrow (or reorder onto) a backend that can't run.
        warnings.append(
            f"preferred web_search backend {preferred!r} has no "
            f"{BACKEND_ENV[preferred]} — preference ignored (fail-safe)"
        )
        preferred, strict = "auto", False

    # The configured order IS the chain — `AUTO_ORDER` is only its default.
    usable = [b for b in order if backend_usable(b)]
    if preferred == "auto":
        candidates = tuple(usable)
    elif strict:
        candidates = (preferred,)
    else:
        # Ordering semantics (Q5-b): first choice, then the rest of the
        # usable chain in the CONFIGURED order.
        candidates = (preferred,) + tuple(b for b in usable if b != preferred)

    # Egress: narrowing ONLY under an effective strict pin — otherwise the
    # honest set is the full superset (session parity IS the fallback chain;
    # authorize() enforces all-of over this set, so narrowing by key presence
    # would turn a missing env var into a policy denial).
    if strict:
        egress = tuple(BACKEND_HOSTS[preferred])
    else:
        # DERIVED from the resolved chain, not a static list. `order` makes
        # the chain configurable, so a hardcoded host set could enumerate a
        # backend the chain will never try (or, worse, omit one it will) —
        # the enumeration-vs-chain divergence this resolver exists to
        # prevent (debt Item 59). Keyed on the ORDER, not on `usable`: a
        # missing API key must never become a policy denial, which is why
        # this stays the honest superset of everything the chain may reach.
        egress = tuple(h for b in order for h in BACKEND_HOSTS[b])

    # Item 59: intersect with the run's narrowed egress allowlist, when given.
    # A sandboxed /task run can allowlist a strict subset of the global search
    # superset (e.g. only api.perplexity.ai). Without this, a soft
    # `preferred:perplexity` left DuckDuckGo in the candidate chain AND in the
    # enumerated superset; `authorize()`'s all-of rule then DENIED the whole
    # call over the unreachable DDG host (observed: fabricated weather answer).
    #
    # Narrowing is a PURE removal keyed on the run's own allowlist — it never
    # adds a backend and never widens egress, so an unconfined run
    # (egress_allows=None) is untouched. Two distinct narrowings, deliberately:
    #
    #   * candidates — the chain TRIES these, so filter (usable ∩ allowed):
    #     drop any backend whose hosts aren't all permitted. The call-time
    #     chain applies the identical filter, so enumeration and chain match.
    #   * egress_hosts — the honest superset authorize() checks. Narrow by the
    #     ALLOWLIST only, NOT by usability (the pre-existing invariant: a
    #     missing API key must never turn into a policy denial). This keeps
    #     egress a subset of the allowlist so the all-of rule passes.
    #
    # If NO known backend is permitted, leave the resolution untouched and let
    # authorize()/the chain fail-close honestly — we never invent a backend.
    if egress_allows is not None:
        permitted = tuple(
            b for b in candidates if _backend_hosts_all_allowed(b, egress_allows)
        )
        allowed_egress = tuple(
            h for h in egress if egress_allows(_host_of(h))
        )
        if permitted and allowed_egress:
            if permitted != candidates:
                warnings.append(
                    "web_search candidates narrowed to "
                    f"{', '.join(permitted)} by the run's egress allowlist "
                    "(backends outside it dropped so the chain never tries a "
                    "host the sandbox would deny)"
                )
            candidates = permitted
            egress = allowed_egress

    return BackendResolution(
        scope=scope,
        preferred=preferred,
        strict=strict,
        candidates=candidates,
        egress_hosts=egress,
        warnings=tuple(warnings),
    )
