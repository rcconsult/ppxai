"""Per-run egress allowlist (ADR 0003 §3c, AC-2) — Inc 5.

A tool-capable agent run carries a *network policy*: the set of outbound
hosts (optionally path-scoped) its network-capable tools may reach. This
is the MVP's central prompt-injection-exfiltration defense — a model that
is tricked into fetching `http://attacker/?leak=<secret>` must be stopped
at the egress boundary, not trusted to behave.

Two pieces:

  * `NetworkPolicy` — built from a run's `allow_outbound` spec. `check(url)`
    returns `Allow(rule_id)` or `Deny(reason)`. **Fail-closed:** an empty
    or absent allowlist denies everything; an unresolvable target denies.

  * `tool_targets(name, kwargs)` — the SET of every URL a tool call could
    reach, BEFORE the handler runs. Critically, a tool's real egress host
    is often NOT a single predictable value:
      - `fetch_url(url=...)` → the one URL the model gave.
      - `web_search` → resolved at CALL time inside `web_search_premium`
        with a fallback chain, so it may hit DuckDuckGo OR Perplexity OR
        Gemini. All are *possible* → all are returned.
      - `get_weather` → tries https then falls back to plain http on the
        same host, so BOTH schemes are possible targets.
    We cannot predict which branch the handler will take, so we enumerate
    every branch. A network-capable tool we can't resolve at all returns
    an empty set → the caller denies (fail-closed).

`NetworkPolicy.authorize(name, kwargs)` is the decision used at the
chokepoint: a tool is allowed ONLY IF **every** possible target passes
`check()`. This is the load-bearing correctness property (AC-2): a run
that allowlists only duckduckgo.com must NOT be able to run `web_search`
if that call could instead reach api.perplexity.ai. Requiring the full
superset closes the confused-deputy gap and keeps the audit event honest.

Enforcement lives at the `ScopedToolManager.execute_tool` chokepoint
(the same single point Inc 4 established): the grant check runs first,
then — if the tool is network-capable — `authorize`. Non-network tools
(`read_file`, `grep`, …) are never gated by the policy.

Why the chokepoint and not per-handler: the web tools call
`urllib.request.urlopen` inline, `web_search` goes through the `ddgs`
package / premium SDKs, and the premium dispatch picks a backend at call
time — there is no single socket we can wrap and no single host we can
predict. The execute boundary is the one place every call passes through
with its args still visible, and the superset check makes the
unpredictable backend safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from ...common.logger import get_logger

logger = get_logger("tui")


# Network-capable builtins and the SET of URLs each could reach. The value
# is either a kwarg reference (the model supplies the URL) or a fixed list of
# every host the handler might hit across its dispatch + fallback branches.
#
#   ("kwarg", name) → one target: the URL in kwargs[name]
#   ("fixed", [urls]) → these exact targets, ALL of which must be allowed
#
# web_search dispatches to a premium backend chosen at call time
# (web_premium.get_premium_search_provider) with a Perplexity→Gemini→DDG
# fallback chain — so its possible egress is the UNION of all of them. A run
# must allowlist every one to be permitted web_search (superset rule), else
# it could exfiltrate through an unallowlisted backend.
#
# get_weather tries https then falls back to plain http on wttr.in
# (web.get_weather) — both schemes are possible. Since the MVP denies http,
# get_weather is effectively un-allowlistable until the http fallback is
# removed; that's the honest, fail-closed outcome.
#
# A tool NOT in this map is non-network: the policy ignores it. A tool here
# whose targets can't be resolved → empty set → denied (fail-closed).

# Shell-execution tools run ARBITRARY commands (curl, pip, Invoke-WebRequest,
# git clone, a python urllib one-liner …). Their egress is unknowable to a
# host/path allowlist, so AC-2 cannot contain them — only the deferred OS
# isolation tier (ADR 0003 §3 tier-d) can. They are therefore NOT grantable to
# a tool-capable agent run in the MVP: the route rejects such a grant up front,
# and ScopedToolManager refuses to run them whenever an egress policy is active
# (defense-in-depth). Kept here (the egress module) so the network-confinement
# concepts live in one place; agent_scoped_tools imports it.
SHELL_TOOL_NAMES = frozenset({"execute_shell_command"})


def grant_has_shell(grant) -> bool:
    """True if a capability grant includes any shell-execution tool."""
    return bool(set(grant or []) & SHELL_TOOL_NAMES)


_NETWORK_TOOLS: Dict[str, Tuple[str, Any]] = {
    "fetch_url": ("kwarg", "url"),
    "web_search": ("fixed", [
        "https://duckduckgo.com/",
        "https://html.duckduckgo.com/",
        "https://api.perplexity.ai/",
        "https://generativelanguage.googleapis.com/",
    ]),
    "get_weather": ("fixed", [
        "https://wttr.in/",
        "http://wttr.in/",  # handler's plain-http fallback — denied under MVP
    ]),
}


@dataclass(frozen=True)
class Allow:
    rule_id: str  # index/host of the matched rule — for audit (allowlist_rule_id)


@dataclass(frozen=True)
class Deny:
    reason: str  # human-readable, surfaced in the NETWORK_POLICY_DENIED event


Decision = Union[Allow, Deny]


@dataclass(frozen=True)
class ToolDecision:
    """A whole-tool-call verdict (from `NetworkPolicy.authorize`), carrying the
    audit fields the chokepoint emits. Unlike `check`'s per-URL `Decision`,
    this reflects the superset rule over a tool's full egress set."""

    allowed: bool
    target_host: str
    target_path: str
    rule_id: Optional[str]  # allowlist_rule_id for audit (None on deny)
    reason: str


@dataclass(frozen=True)
class _Rule:
    """One normalized allowlist entry: a host matcher + optional path prefixes."""

    host: str                 # exact host or "*.suffix" single-label glob
    paths: Tuple[str, ...]    # path prefixes; empty = any path
    rule_id: str              # stable id for audit (the index)

    def matches_host(self, host: str) -> bool:
        if self.host.startswith("*."):
            suffix = self.host[1:]  # ".wikipedia.org"
            # single-label glob, suffix-anchored: en.wikipedia.org matches,
            # a.b.wikipedia.org does NOT (one label), and
            # wikipedia.org.evil.com does NOT (suffix anchor).
            if not host.endswith(suffix):
                return False
            label = host[: -len(suffix)]
            return bool(label) and "." not in label
        return host == self.host

    def matches_path(self, path: str) -> bool:
        if not self.paths:
            return True
        return any(path.startswith(p) for p in self.paths)


def is_network_tool(name: str) -> bool:
    """True if this tool makes outbound requests (so the policy applies)."""
    return name in _NETWORK_TOOLS


def tool_targets(name: str, kwargs: dict) -> List[str]:
    """Every URL a network-capable tool call could reach (its egress set).

    Returns a list of candidate URLs. Empty list = the tool is
    network-capable but its target(s) can't be resolved → the caller must
    fail-closed (deny). For non-network tools, callers should not call this
    (guard with is_network_tool).
    """
    spec = _NETWORK_TOOLS.get(name)
    if spec is None:
        return []
    kind, ref = spec
    if kind == "fixed":
        return list(ref)
    # kind == "kwarg": the URL is whatever the model passed (single target)
    raw = kwargs.get(ref)
    if not isinstance(raw, str) or not raw.strip():
        return []
    return [raw.strip()]


class NetworkPolicy:
    """Per-run egress allowlist. Deny-by-default, fail-closed.

    Built from a run's `allow_outbound`, a list whose entries are either:
      * a bare host string         → exact host, any path
      * {"host": "...", "paths"?: [...]}  → host (exact or "*.suffix"), path prefixes

    `check(url)` is called at the execute chokepoint for every
    network-capable tool, before the request fires.
    """

    def __init__(self, allow_outbound: Optional[List] = None) -> None:
        self._rules: List[_Rule] = []
        for i, entry in enumerate(allow_outbound or []):
            if isinstance(entry, str):
                host, paths = entry, ()
            elif isinstance(entry, dict):
                host = entry.get("host")
                raw_paths = entry.get("paths") or []
                paths = tuple(p for p in raw_paths if isinstance(p, str))
            else:
                logger.warning(f"NetworkPolicy: ignoring malformed rule {entry!r}")
                continue
            if not isinstance(host, str) or not host:
                logger.warning(f"NetworkPolicy: ignoring rule with no host: {entry!r}")
                continue
            self._rules.append(_Rule(host=host.lower(), paths=paths, rule_id=str(i)))

    @property
    def is_empty(self) -> bool:
        return not self._rules

    def check(self, url: Optional[str]) -> Decision:
        """Allow only if the URL matches a rule. Fail-closed otherwise."""
        if not url:
            return Deny("no resolvable target host")
        parsed = urlparse(url)
        # MVP: https-only (the read-only research profile needs only https GETs).
        if parsed.scheme not in ("https", ""):
            return Deny(f"scheme {parsed.scheme!r} not allowed (https only)")
        host = (parsed.hostname or "").lower()
        if not host:
            return Deny(f"unparseable target host in {url!r}")
        path = parsed.path or "/"
        for rule in self._rules:
            if rule.matches_host(host):
                if rule.matches_path(path):
                    return Allow(rule.rule_id)
                return Deny(
                    f"path {path!r} not in allowed prefixes "
                    f"{list(rule.paths)} for host {host!r}"
                )
        return Deny(f"host {host!r} not in egress allowlist")

    def authorize(self, name: str, kwargs: dict) -> "ToolDecision":
        """Decide a network-capable tool call against the policy.

        The tool is ALLOWED only if EVERY URL it could reach (its full egress
        set from `tool_targets`) passes `check()`. This superset rule is the
        AC-2 correctness property: a tool whose backend is chosen at call time
        (e.g. web_search → DDG/Perplexity/Gemini) must have ALL branches
        allowlisted, so a run can never reach an unallowlisted host by taking
        a different branch than the one we'd guess.

        Returns a ToolDecision carrying the allow/deny verdict plus the
        target host/path/rule used for the audit event. On deny, the host/
        path reported is the FIRST disallowed target (the reason it failed).
        """
        targets = tool_targets(name, kwargs)
        if not targets:
            return ToolDecision(False, "", "", None, "no resolvable target host")
        first_allow_rule: Optional[str] = None
        for url in targets:
            decision = self.check(url)
            if isinstance(decision, Deny):
                parsed = urlparse(url)
                return ToolDecision(
                    allowed=False,
                    target_host=parsed.hostname or "",
                    target_path=parsed.path or "",
                    rule_id=None,
                    reason=decision.reason,
                )
            if first_allow_rule is None:
                first_allow_rule = decision.rule_id
        # Every target passed. Report the (first) resolvable target for audit.
        parsed = urlparse(targets[0])
        return ToolDecision(
            allowed=True,
            target_host=parsed.hostname or "",
            target_path=parsed.path or "",
            rule_id=first_allow_rule,
            reason=(
                "matched egress allowlist"
                if len(targets) == 1
                else f"all {len(targets)} possible targets in allowlist"
            ),
        )
