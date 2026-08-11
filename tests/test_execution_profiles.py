"""ADR 0009 step ③: execution.profiles + enrichment in AgentSpec.

Covers, per the ADR's "Requires" list:
- config readers: `execution.profiles` (named AgentSpec-shaped grants) and
  `execution.egress_ceiling` (config-only, intersective, unset = no cap,
  malformed = ValueError — fail loud, never open).
- `enrichment` in the spec shape: tri-state scalar (true/false/absent),
  non-bool rejected, NOT an unknown key anymore (the §3/§5 blocker).
- precedence request > spec > (skills) > profile > default, with
  REPLACE-not-union for tools/network (Q1 sentinel: a narrower layer can
  actually REMOVE a tool and a host).
- §5 resolution order: enrichment resolves as a scalar, derives web_search
  + the backend-superset egress ONCE after resolution; the two
  contradiction cases fail pre-start (400 naming both layers).
- Q3 ceiling: intersection at assembly; an enriched run whose ceiling
  strips every backend host fails pre-start (400 naming stripped hosts) on
  /v1/agent/task AND the /v1/agent/run grant branch.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.agent_spec import AgentSpecError, spec_from_mapping
from ppxai.engine.tools.network_policy import apply_egress_ceiling


# ---------------------------------------------------------------------------
# Config readers
# ---------------------------------------------------------------------------


def _pin_execution(monkeypatch, block):
    from ppxai.config import execution as exec_mod
    monkeypatch.setattr(exec_mod, "get_execution_config", lambda: dict(block))


class TestExecutionProfilesConfig:
    def test_absent_is_empty(self, monkeypatch):
        from ppxai.config.execution import get_execution_profiles
        _pin_execution(monkeypatch, {})
        assert get_execution_profiles() == {}

    def test_reads_mapping(self, monkeypatch):
        from ppxai.config.execution import get_execution_profiles
        _pin_execution(
            monkeypatch, {"profiles": {"research": {"tools": ["web_search"]}}}
        )
        assert get_execution_profiles() == {"research": {"tools": ["web_search"]}}

    def test_non_dict_is_empty(self, monkeypatch):
        from ppxai.config.execution import get_execution_profiles
        _pin_execution(monkeypatch, {"profiles": ["not-a-mapping"]})
        assert get_execution_profiles() == {}


class TestEgressCeilingConfig:
    def test_unset_is_none_no_cap(self, monkeypatch):
        from ppxai.config.execution import get_execution_egress_ceiling
        _pin_execution(monkeypatch, {})
        assert get_execution_egress_ceiling() is None

    def test_reads_list(self, monkeypatch):
        from ppxai.config.execution import get_execution_egress_ceiling
        _pin_execution(monkeypatch, {"egress_ceiling": ["a.example.com"]})
        assert get_execution_egress_ceiling() == ["a.example.com"]

    def test_malformed_fails_loud_not_open(self, monkeypatch):
        # A security ceiling misread as "no cap" would silently widen egress.
        from ppxai.config.execution import get_execution_egress_ceiling
        _pin_execution(monkeypatch, {"egress_ceiling": "a.example.com"})
        with pytest.raises(ValueError):
            get_execution_egress_ceiling()


# ---------------------------------------------------------------------------
# enrichment in the spec shape (the ADR's named blocker)
# ---------------------------------------------------------------------------


class TestSpecEnrichmentField:
    def test_tri_state(self):
        assert spec_from_mapping({"enrichment": True}).enrichment is True
        assert spec_from_mapping({"enrichment": False}).enrichment is False
        assert spec_from_mapping({}).enrichment is None  # absent = inherit

    def test_not_an_unknown_key(self):
        # Pre-③ this warned "ignored unknown spec keys: ['enrichment']" and
        # silently produced the closed-book run §3 exists to fix.
        spec = spec_from_mapping({"enrichment": True})
        assert not spec.warnings

    def test_non_bool_rejected(self):
        # "no" truthy-reading as True would invert a security intent.
        with pytest.raises(AgentSpecError):
            spec_from_mapping({"enrichment": "no"})


# ---------------------------------------------------------------------------
# apply_egress_ceiling (unit)
# ---------------------------------------------------------------------------


def _pin_ceiling(monkeypatch, ceiling):
    from ppxai.config import execution as exec_mod
    monkeypatch.setattr(
        exec_mod, "get_execution_egress_ceiling", lambda: ceiling
    )


class TestApplyEgressCeiling:
    def test_unset_no_cap(self, monkeypatch):
        _pin_ceiling(monkeypatch, None)
        kept, stripped = apply_egress_ceiling(["a.example.com", "b.example.com"])
        assert kept == ["a.example.com", "b.example.com"] and stripped == []

    def test_intersects_exact_hosts(self, monkeypatch):
        _pin_ceiling(monkeypatch, ["a.example.com"])
        kept, stripped = apply_egress_ceiling(["a.example.com", "b.example.com"])
        assert kept == ["a.example.com"]
        assert stripped == ["b.example.com"]

    def test_ceiling_glob_permits_concrete_host(self, monkeypatch):
        _pin_ceiling(monkeypatch, ["*.example.com"])
        kept, stripped = apply_egress_ceiling(["api.example.com", "evil.net"])
        assert kept == ["api.example.com"] and stripped == ["evil.net"]

    def test_run_glob_needs_identical_ceiling_entry(self, monkeypatch):
        # A ceiling cannot safely subsume a WIDER glob → fail-closed strip
        # unless the ceiling states the identical entry.
        _pin_ceiling(monkeypatch, ["*.example.com"])
        assert apply_egress_ceiling(["*.example.com"])[0] == ["*.example.com"]
        _pin_ceiling(monkeypatch, ["api.example.com"])
        kept, stripped = apply_egress_ceiling(["*.example.com"])
        assert kept == [] and stripped == ["*.example.com"]

    def test_dict_entries_matched_by_host(self, monkeypatch):
        _pin_ceiling(monkeypatch, ["api.example.com"])
        entry = {"host": "api.example.com", "paths": ["/v1"]}
        kept, stripped = apply_egress_ceiling([entry, {"host": "other.net"}])
        assert kept == [entry] and stripped == [{"host": "other.net"}]


# ---------------------------------------------------------------------------
# Route-level: /v1/agent/task with profiles
# ---------------------------------------------------------------------------


@pytest.fixture
def task_client(tmp_path, monkeypatch):
    """A /v1/agent/* app with the task tier on, provider validation stubbed,
    the runner stubbed (captures its kwargs), and tool-config emptied so
    egress assertions see exactly what the merge assembled."""
    import ppxai.server.state as state
    from ppxai.server.routes import agent_v1
    from ppxai.engine import task_runner

    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)

    real = agent_v1.get_execution_task_config
    overrides = {"enabled": True}
    monkeypatch.setattr(
        agent_v1, "get_execution_task_config", lambda: {**real(), **overrides}
    )
    monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)
    monkeypatch.setattr(agent_v1, "get_tool_config", lambda tool: {})

    captured = {}

    def _stub_runner(registry, **kw):
        captured.update(kw)

        async def _r(m):
            return "done"

        return _r

    monkeypatch.setattr(task_runner, "build_task_runner", _stub_runner)
    from ppxai.config import execution as exec_mod
    monkeypatch.setattr(exec_mod, "get_execution_collect", lambda: "yes")

    app = FastAPI()
    app.include_router(agent_v1.router)
    return TestClient(app), reg, captured, overrides


def _pin_profiles(monkeypatch, profiles):
    from ppxai.config import execution as exec_mod
    monkeypatch.setattr(exec_mod, "get_execution_profiles", lambda: profiles)


def _baseline_hosts():
    from ppxai.server.routes.oneshot import _web_search_egress_hosts
    return _web_search_egress_hosts()


class TestProfileResolution:
    def test_unknown_profile_400_lists_configured(self, task_client, monkeypatch):
        c, _reg, _cap, _ov = task_client
        _pin_profiles(monkeypatch, {"research": {"tools": ["read_file"]}})
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "nope"})
        assert r.status_code == 400
        assert "research" in r.json()["detail"]

    def test_malformed_profile_400(self, task_client, monkeypatch):
        c, _reg, _cap, _ov = task_client
        _pin_profiles(monkeypatch, {"bad": {"enrichment": "yes"}})
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "bad"})
        assert r.status_code == 400
        assert "Invalid execution profile" in r.json()["detail"]

    def test_profile_supplies_grant_provider_model(self, task_client, monkeypatch):
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "research": {"tools": ["read_file"], "provider": "p2", "model": "m2"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "research"})
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["read_file"]
        assert cap["provider_name"] == "p2" and cap["model"] == "m2"

    def test_request_scalars_beat_profile(self, task_client, monkeypatch):
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "research": {"tools": ["read_file"], "provider": "p2", "model": "m2"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={
            "task": "t", "profile": "research", "provider": "p1",
        })
        assert r.status_code == 200, r.text
        # provider from the request wins; model still inherits the profile's.
        assert cap["provider_name"] == "p1" and cap["model"] == "m2"

    def test_profile_only_passes_request_validation(self, task_client, monkeypatch):
        # 422 without any grant source; a bare profile is a grant source.
        c, _reg, _cap, _ov = task_client
        r = c.post("/v1/agent/task", json={"task": "t"})
        assert r.status_code == 422


class TestReplaceNotUnion:
    """Q1 sentinel: a narrower layer can REMOVE a tool and a host. This is
    the property that silently inverts if anyone "fixes" the merge to union
    later — keep these red-on-union."""

    def test_request_tools_replace_profile_tools(self, task_client, monkeypatch):
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "research": {"tools": ["read_file", "fetch_url"],
                         "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={
            "task": "t", "profile": "research", "tools": ["read_file"],
        })
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["read_file"]  # fetch_url REMOVED, not unioned

    def test_spec_narrows_profile_tools_and_network(
        self, task_client, monkeypatch, tmp_path
    ):
        c, _reg, cap, overrides = task_client
        specs = tmp_path / "specs"
        specs.mkdir()
        (specs / "narrow.json").write_text(
            json.dumps({"tools": ["read_file"], "network": []}),
            encoding="utf-8",
        )
        overrides["sandbox"] = {"specs_dir": str(specs)}
        _pin_profiles(monkeypatch, {
            "research": {"tools": ["read_file", "fetch_url"],
                         "network": ["api.example.com"],
                         "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={
            "task": "t", "profile": "research", "spec": "narrow",
        })
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["read_file"]          # tool removed
        assert cap["allow_outbound"] == []            # host removed (stated-empty)


class TestEnrichmentDerivation:
    def test_enrichment_only_profile_grants_web_search_and_baseline(
        self, task_client, monkeypatch
    ):
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "enriched": {"enrichment": True, "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "enriched"})
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["web_search"]  # derived, exactly once
        # §3: the egress baseline is the FULL backend superset (session
        # parity = the fallback chain), not one backend.
        assert set(_baseline_hosts()) <= set(cap["allow_outbound"])

    def test_enrichment_false_no_widening(self, task_client, monkeypatch):
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "closed": {"enrichment": False, "tools": ["read_file"],
                       "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "closed"})
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["read_file"]
        assert cap["allow_outbound"] == []

    def test_request_enrichment_false_disables_profile_enrichment(
        self, task_client, monkeypatch
    ):
        # §5: "to narrow enrichment, set enrichment: false" — the designed
        # field, not omission. No contradiction, no derivation.
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "enriched": {"enrichment": True, "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={
            "task": "t", "profile": "enriched",
            "enrichment": False, "tools": ["read_file"],
        })
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["read_file"]

    def test_contradiction_request_tools_vs_profile_enrichment(
        self, task_client, monkeypatch
    ):
        # A MORE SPECIFIC layer's explicit tools list omitting web_search
        # under effective enrichment:true → 400 naming both layers.
        c, _reg, _cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "enriched": {"enrichment": True, "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={
            "task": "t", "profile": "enriched", "tools": ["read_file"],
        })
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "request" in detail and "profile" in detail
        assert "enrichment" in detail

    def test_contradiction_same_layer(self, task_client, monkeypatch):
        c, _reg, _cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "confused": {"enrichment": True, "tools": ["read_file"],
                         "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "confused"})
        assert r.status_code == 400
        assert "enrichment" in r.json()["detail"]

    def test_tools_from_less_specific_layer_derive_silently(
        self, task_client, monkeypatch
    ):
        # enrichment declared at the REQUEST, tools stated only by the
        # PROFILE (less specific) → no contradiction; web_search derived.
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "base": {"tools": ["read_file"], "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={
            "task": "t", "profile": "base", "enrichment": True,
        })
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["read_file", "web_search"]


class TestCeilingAtLaunch:
    def test_ceiling_caps_plain_run_silently(self, task_client, monkeypatch):
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "net": {"tools": ["fetch_url"],
                    "network": ["a.example.com", "b.example.com"],
                    "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, ["a.example.com"])
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "net"})
        assert r.status_code == 200, r.text
        assert cap["allow_outbound"] == ["a.example.com"]

    def test_enriched_run_stripped_of_all_backends_400(
        self, task_client, monkeypatch
    ):
        # Q3: never start half-enriched — pre-start 400 naming stripped hosts.
        c, reg, _cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "enriched": {"enrichment": True, "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, ["unrelated.example.com"])
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "enriched"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "egress_ceiling" in detail
        assert _baseline_hosts()[0] in detail  # names the stripped hosts
        assert reg.list_runs() == []           # pre-start: no run record

    def test_enriched_run_partial_ceiling_400_all_of(
        self, task_client, monkeypatch
    ):
        # Step ④ Q3 refinement: authorize() is ALL-OF over the effective
        # egress set, so a partially-surviving baseline would pass grant time
        # while the tool is un-callable at run time — that must 400 too.
        c, _reg, _cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "enriched": {"enrichment": True, "provider": "p", "model": "m"},
        })
        _pin_ceiling(monkeypatch, [_baseline_hosts()[0]])  # one of four
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "enriched"})
        assert r.status_code == 400
        assert "all-of" in r.json()["detail"]

    def test_enriched_strict_pin_with_matching_ceiling_starts(
        self, task_client, monkeypatch
    ):
        # The sanctioned narrow-ceiling shape: a strict pin shrinks the
        # effective egress set to the pinned backend, so a ceiling keeping
        # exactly that backend composes instead of colliding (ADR 0009 §3).
        import ppxai.config as config_pkg
        c, _reg, cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "enriched": {"enrichment": True, "provider": "p", "model": "m"},
        })
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        real_get_tool_config = config_pkg.get_tool_config
        monkeypatch.setattr(
            config_pkg, "get_tool_config",
            lambda tool: ({"preferred": "perplexity", "strict": True}
                          if tool == "web_search"
                          else real_get_tool_config(tool)),
        )
        _pin_ceiling(monkeypatch, ["api.perplexity.ai"])
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "enriched"})
        assert r.status_code == 200, r.text
        assert cap["allow_outbound"] == ["api.perplexity.ai"]

    def test_malformed_ceiling_400_not_silent_no_cap(
        self, task_client, monkeypatch
    ):
        c, _reg, _cap, _ov = task_client
        _pin_profiles(monkeypatch, {
            "net": {"tools": ["fetch_url"], "provider": "p", "model": "m"},
        })
        from ppxai.config import execution as exec_mod
        _pin_execution(monkeypatch, {"egress_ceiling": "not-a-list",
                                     "profiles": {}})
        monkeypatch.setattr(
            exec_mod, "get_execution_profiles",
            lambda: {"net": {"tools": ["fetch_url"],
                             "provider": "p", "model": "m"}},
        )
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "net"})
        assert r.status_code == 400
        assert "egress_ceiling" in r.json()["detail"]


def _pin_default_grant(monkeypatch, grant, *, allow_user_default=True):
    """Item 58: pin execution.task.default_grant + allow_user_default."""
    from ppxai.config import execution as exec_mod
    monkeypatch.setattr(
        exec_mod, "get_execution_task_default_grant", lambda: grant
    )
    monkeypatch.setattr(
        exec_mod, "get_execution_task_allow_user_default",
        lambda: allow_user_default,
    )


def _pin_subagent(monkeypatch, provider, model):
    """default_grant carries no provider/model (Item 58 scope: tools/network/
    budget), so a bare task's provider/model come from default_subagent — as
    on coder (default_subagent=qwen36)."""
    from ppxai.server.routes import agent_v1
    from ppxai.config import execution as exec_mod
    sub = {"provider": provider, "model": model}
    monkeypatch.setattr(agent_v1, "get_execution_default_subagent", lambda: sub)
    monkeypatch.setattr(exec_mod, "get_execution_default_subagent", lambda: sub)


class TestTaskDefaultGrant:
    """Item 58: `execution.task.default_grant` — the user's standing default
    grant. A NEW precedence layer below profile / above the built-in empty
    default. It must (a) let a bare `/task` run, (b) always lose to an explicit
    request/spec/profile, and (c) escalate NOTHING — every clamp still applies.
    """

    def test_config_readers(self, monkeypatch):
        from ppxai.config.execution import (
            get_execution_task_allow_user_default,
            get_execution_task_default_grant,
        )
        _pin_execution(monkeypatch, {})
        assert get_execution_task_default_grant() == {}
        assert get_execution_task_allow_user_default() is True
        _pin_execution(monkeypatch, {
            "task": {"default_grant": {"tools": ["web_search"]},
                     "allow_user_default": False},
        })
        assert get_execution_task_default_grant() == {"tools": ["web_search"]}
        assert get_execution_task_allow_user_default() is False

    def test_non_dict_default_grant_is_empty(self, monkeypatch):
        from ppxai.config.execution import get_execution_task_default_grant
        _pin_execution(monkeypatch, {"task": {"default_grant": ["nope"]}})
        assert get_execution_task_default_grant() == {}

    def test_bare_task_resolves_grant_from_default(self, task_client, monkeypatch):
        # THE Item 58 goal: `/task "<desc>"` with no flags now RUNS, seeding
        # its grant from the user's default instead of 422-ing.
        c, _reg, cap, _ov = task_client
        _pin_default_grant(monkeypatch, {"tools": ["web_search"]})
        _pin_subagent(monkeypatch, "p", "m")
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "weather in Lausanne"})
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["web_search"]

    def test_bare_task_still_422_when_no_default_configured(
        self, task_client, monkeypatch
    ):
        # The historical invariant holds when nothing is configured.
        c, _reg, _cap, _ov = task_client
        _pin_default_grant(monkeypatch, {})
        r = c.post("/v1/agent/task", json={"task": "t"})
        assert r.status_code == 422

    def test_allow_user_default_false_fails_closed(self, task_client, monkeypatch):
        # Operator kill-switch: a configured default is IGNORED when the
        # operator locked it down — bare task 422s (fail-closed posture).
        c, _reg, _cap, _ov = task_client
        _pin_default_grant(
            monkeypatch, {"tools": ["web_search"]}, allow_user_default=False
        )
        _pin_subagent(monkeypatch, "p", "m")
        r = c.post("/v1/agent/task", json={"task": "t"})
        assert r.status_code == 422

    def test_request_tools_replace_default_grant(self, task_client, monkeypatch):
        # Item 58 precedence: an explicit --tools always wins (replace/narrow).
        c, _reg, cap, _ov = task_client
        _pin_default_grant(monkeypatch, {"tools": ["web_search", "fetch_url"]})
        _pin_subagent(monkeypatch, "p", "m")
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={
            "task": "t", "tools": ["read_file"],
        })
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["read_file"]  # default REPLACED, not unioned

    def test_profile_beats_default_grant(self, task_client, monkeypatch):
        # A named profile is more specific than the standing default.
        c, _reg, cap, _ov = task_client
        _pin_default_grant(monkeypatch, {"tools": ["web_search"]})
        _pin_profiles(monkeypatch, {
            "research": {"tools": ["read_file"], "provider": "p", "model": "m"},
        })
        _pin_subagent(monkeypatch, "p", "m")
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "t", "profile": "research"})
        assert r.status_code == 200, r.text
        assert cap["tools"] == ["read_file"]  # profile wins over default_grant

    def test_default_grant_cannot_grant_shell(self, task_client, monkeypatch):
        # NO ESCALATION: a user default naming shell is rejected by the SAME
        # shell-reject every source faces — the sandbox is never jailbroken.
        c, _reg, _cap, _ov = task_client
        _pin_default_grant(
            monkeypatch, {"tools": ["execute_shell_command"]}
        )
        _pin_subagent(monkeypatch, "p", "m")
        _pin_ceiling(monkeypatch, None)
        r = c.post("/v1/agent/task", json={"task": "t"})
        assert r.status_code == 400
        assert "shell" in r.json()["detail"].lower()

    def test_default_grant_egress_clamped_by_ceiling(self, task_client, monkeypatch):
        # NO ESCALATION: a user default naming a host OUTSIDE the operator
        # ceiling is silently clamped, never honored. The run keeps only the
        # ceiling-permitted host.
        c, _reg, cap, _ov = task_client
        _pin_default_grant(monkeypatch, {
            "tools": ["fetch_url"],
            "network": ["api.allowed.com", "evil.example.com"],
        })
        _pin_subagent(monkeypatch, "p", "m")
        _pin_ceiling(monkeypatch, ["api.allowed.com"])
        r = c.post("/v1/agent/task", json={"task": "t"})
        assert r.status_code == 200, r.text
        assert cap["allow_outbound"] == ["api.allowed.com"]  # evil.* clamped out

    def test_malformed_default_grant_400(self, task_client, monkeypatch):
        # A bad default grant is a pre-start 400 (same normalizer as profiles),
        # never a silent bypass or an async run failure. It carries a valid
        # `tools` so it passes the request-shape 422 gate and reaches the
        # resolver, where the non-bool `enrichment` is rejected.
        c, _reg, _cap, _ov = task_client
        _pin_default_grant(
            monkeypatch, {"tools": ["web_search"], "enrichment": "yes"}
        )
        _pin_subagent(monkeypatch, "p", "m")
        r = c.post("/v1/agent/task", json={"task": "t"})
        assert r.status_code == 400
        assert "default_grant" in r.json()["detail"]


class TestRunFamilyCeiling:
    def test_run_grant_branch_stripped_of_all_backends_400(
        self, task_client, monkeypatch
    ):
        # The one-off tier's Q3 fail-fast: execution.run.web_search on +
        # ceiling stripping every backend → 400, no half-enriched run.
        c, reg, _cap, _ov = task_client
        from ppxai.config import execution as exec_mod
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(
            exec_mod, "get_execution_run_config",
            lambda: {"web_search": True, "grounding": False},
        )
        monkeypatch.setattr(
            agent_v1, "_v1_provider_or_400", lambda name: object()
        )
        _pin_ceiling(monkeypatch, ["unrelated.example.com"])
        r = c.post("/v1/agent/run", json={
            "task": "t", "provider": "p", "model": "m",
        })
        assert r.status_code == 400
        assert "egress_ceiling" in r.json()["detail"]
        assert reg.list_runs() == []
