"""Tests for spawn_subagent — child run scoped to a subset of the parent
(ADR 0003 §9, Inc 7). The security core is the SUBSET enforcement that keeps
AC-1 (grant) and AC-2 (egress) transitive across the parent→child boundary,
plus the depth=1 / consent gates.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.tools.agent_spawn import SpawnSubagentTool


@pytest.fixture
def registry(tmp_path: Path) -> AgentRunRegistry:
    return AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))


def _tool(registry, *, parent_tools, parent_allow, consent=None, consent_policy="auto",
          parent_owner=None, runner_builder=None):
    # Default consent_policy="auto" in tests so happy-path spawns proceed
    # without an interactive channel; the consent-gate tests override it.
    #
    # runner_builder is INJECTED (v1.19.0) rather than imported inside the tool
    # (that was an engine→server layering inversion + import cycle). Read
    # `build_task_runner` off the module object at CALL time so tests that
    # `monkeypatch.setattr("...agent_v1.build_task_runner", fake)` before
    # calling _tool still see the patched builder.
    if runner_builder is None:
        from ppxai.server.routes import agent_v1
        runner_builder = agent_v1.build_task_runner
    return SpawnSubagentTool(
        registry=registry,
        parent_run_id="run_parent",
        parent_tools=parent_tools,
        parent_allow_outbound=parent_allow,
        parent_provider="p",
        parent_model="m",
        parent_owner=parent_owner,
        request_consent=consent,
        consent_policy=consent_policy,
        runner_builder=runner_builder,
    )


class TestConstructorContract:
    """Guard against call-site/constructor drift.

    The production construction lives inside `build_task_runner`'s async
    `_runner` body (server/routes/agent_v1.py), which only executes when a
    spawn-enabled run actually runs behind a real EngineClient — so a kwarg
    mismatch there is invisible to unit tests and only surfaces at runtime.
    That is exactly how the Inc 8b `parent_owner=` kwarg shipped against a
    constructor that didn't accept it (TypeError on every spawn). These
    tests pin the constructor's accepted kwargs so the drift can't recur.
    """

    def test_accepts_all_build_task_runner_kwargs(self, registry):
        # The exact kwarg set build_task_runner passes (agent_v1.py).
        SpawnSubagentTool(
            registry=registry,
            parent_run_id="r",
            parent_owner="alice",
            parent_tools=["read_file"],
            parent_allow_outbound=[],
            parent_provider="p",
            parent_model="m",
            parent_workdir="/some/dir",  # v1.19.x workdir-alignment
            request_consent=None,
            consent_policy="deny",
            runner_builder=lambda reg, **kw: None,
        )

    def test_parent_workdir_is_optional_and_threaded(self, registry):
        # Optional (old call sites keep working) and stored for the child.
        t = SpawnSubagentTool(
            registry=registry, parent_run_id="r",
            parent_tools=[], parent_allow_outbound=[],
            parent_provider="p", parent_model="m",
        )
        assert t._parent_workdir is None
        t2 = SpawnSubagentTool(
            registry=registry, parent_run_id="r",
            parent_tools=[], parent_allow_outbound=[],
            parent_provider="p", parent_model="m",
            parent_workdir="/repo",
        )
        assert t2._parent_workdir == "/repo"

    def test_parent_owner_is_optional(self, registry):
        # Defaulting keeps the unowned (auth-off) path working.
        t = SpawnSubagentTool(
            registry=registry, parent_run_id="r",
            parent_tools=[], parent_allow_outbound=[],
            parent_provider="p", parent_model="m",
        )
        assert t._parent_owner is None


# ---------------------------------------------------------------------------
# Grant subset (AC-1 transitive)
# ---------------------------------------------------------------------------


class TestGrantSubset:
    def test_subset_ok(self, registry):
        t = _tool(registry, parent_tools=["read_file", "web_search"], parent_allow=[])
        assert t._check_grant_subset(["read_file"]) is None

    def test_equal_ok(self, registry):
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[])
        assert t._check_grant_subset(["read_file"]) is None

    def test_empty_child_ok(self, registry):
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[])
        assert t._check_grant_subset([]) is None

    def test_escalation_denied(self, registry):
        # child asks for a tool the parent doesn't have -> refused
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[])
        err = t._check_grant_subset(["read_file", "write_file"])
        assert err and "write_file" in err and "escalation" in err

    def test_child_shell_denied_even_if_parent_had_it(self, registry):
        # defensive: shell can't be in a parent grant (route 400s it), but if
        # it somehow were, a child still can't carry shell (AC-2).
        t = _tool(registry, parent_tools=["execute_shell_command"], parent_allow=[])
        err = t._check_grant_subset(["execute_shell_command"])
        assert err and "shell" in err.lower()


# ---------------------------------------------------------------------------
# Provider tool-name prefix normalization (Gemini `default_api.` artifact)
# ---------------------------------------------------------------------------


class TestProviderToolPrefix:
    """Gemini's function-calling runtime namespaces tools as
    `default_api.<name>` and the model echoes that prefix into tool-name DATA
    it passes as arguments (live 2026-07-12: a spawn requested child tools
    ['default_api:read_file'] against a parent grant of ['read_file'] and was
    refused, burning an iteration until the model self-corrected). The prefix
    is a provider artifact, never a real ppxai tool name — strip it, and ONLY
    it, before the subset check. Sibling of the schema sanitizer in
    providers/gemini.py."""

    def test_strips_colon_and_dot_variants(self):
        from ppxai.engine.tools.agent_spawn import _strip_provider_tool_prefix
        assert _strip_provider_tool_prefix(
            ["default_api:read_file", "default_api.web_search", "fetch_url"]
        ) == ["read_file", "web_search", "fetch_url"]

    def test_non_prefixed_and_odd_entries_untouched(self):
        from ppxai.engine.tools.agent_spawn import _strip_provider_tool_prefix
        # A name merely CONTAINING the marker (not as a prefix) is untouched,
        # and non-string entries pass through for the subset check to refuse.
        assert _strip_provider_tool_prefix(["my_default_api.tool", 42]) == [
            "my_default_api.tool", 42,
        ]

    @pytest.mark.asyncio
    async def test_prefixed_child_tools_pass_subset_and_spawn_normalized(
        self, registry
    ):
        # The live repro end-to-end: prefixed child tools must clear the
        # subset gate, and the child must be minted with the NORMALIZED grant
        # (a child granted the literal 'default_api:read_file' string could
        # execute nothing).
        captured = {}

        async def fake_runner(meta):
            return "child ok"

        def fake_builder(reg, **kw):
            captured.update(kw)
            return fake_runner

        t = _tool(registry, parent_tools=["read_file"], parent_allow=[],
                  consent=None, consent_policy="auto",
                  runner_builder=fake_builder)
        out = await t.execute(task="summarize", tools=["default_api:read_file"])
        assert "child ok" in out
        assert captured.get("tools") == ["read_file"]
        runs = registry.list_runs()
        assert len(runs) == 1 and runs[0].tools == ["read_file"]

    def test_still_refuses_real_escalation_after_normalization(self, registry):
        # Normalization must not soften the gate: a prefixed name whose BASE
        # is off-grant still refuses.
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[])
        from ppxai.engine.tools.agent_spawn import _strip_provider_tool_prefix
        err = t._check_grant_subset(
            _strip_provider_tool_prefix(["default_api:write_file"])
        )
        assert err and "write_file" in err


# ---------------------------------------------------------------------------
# Egress subset (AC-2 transitive)
# ---------------------------------------------------------------------------


class TestEgressSubset:
    def test_subset_host_ok(self, registry):
        t = _tool(registry, parent_tools=[], parent_allow=["api.github.com", "*.wikipedia.org"])
        assert t._check_egress_subset(["api.github.com"]) is None

    def test_glob_member_ok(self, registry):
        # parent allows *.wikipedia.org; child asks for en.wikipedia.org -> ok
        t = _tool(registry, parent_tools=[], parent_allow=["*.wikipedia.org"])
        assert t._check_egress_subset(["en.wikipedia.org"]) is None

    def test_empty_child_egress_ok(self, registry):
        t = _tool(registry, parent_tools=[], parent_allow=["api.github.com"])
        assert t._check_egress_subset([]) is None

    def test_host_outside_parent_denied(self, registry):
        t = _tool(registry, parent_tools=[], parent_allow=["api.github.com"])
        err = t._check_egress_subset(["evil.com"])
        assert err and "evil.com" in err and "subset" in err

    def test_child_cannot_widen_when_parent_empty(self, registry):
        # parent has NO egress -> child can't have any host
        t = _tool(registry, parent_tools=[], parent_allow=[])
        err = t._check_egress_subset(["api.github.com"])
        assert err is not None

    def test_child_wildcard_not_covered_by_parent_exact_host(self, registry):
        # Codex fix: parent allows ONE exact subdomain; a child "*.example.com"
        # glob is NOT a subset (it could reach other subdomains) and must be
        # rejected — the old single "sub.example.com" probe wrongly passed it.
        t = _tool(registry, parent_tools=[], parent_allow=["sub.example.com"])
        err = t._check_egress_subset(["*.example.com"])
        assert err and "*.example.com" in err and "subset" in err

    def test_child_wildcard_ok_when_parent_has_covering_glob(self, registry):
        # parent allows the *.example.com glob -> child *.example.com IS a subset
        t = _tool(registry, parent_tools=[], parent_allow=["*.example.com"])
        assert t._check_egress_subset(["*.example.com"]) is None

    # --- path-scoped delegation (codex MEDIUM fix) ----------------------

    def test_child_same_scoped_path_ok(self, registry):
        # parent scoped to /repos/; child asks for the SAME scoped path -> ok
        t = _tool(registry, parent_tools=[],
                  parent_allow=[{"host": "api.github.com", "paths": ["/repos/"]}])
        assert t._check_egress_subset(
            [{"host": "api.github.com", "paths": ["/repos/"]}]) is None

    def test_child_any_path_denied_when_parent_scoped(self, registry):
        # parent scoped to /repos/; child asks for the host with NO path scope
        # (= any path) -> denied (would widen beyond /repos/)
        t = _tool(registry, parent_tools=[],
                  parent_allow=[{"host": "api.github.com", "paths": ["/repos/"]}])
        err = t._check_egress_subset(["api.github.com"])
        assert err is not None

    def test_child_other_path_denied_when_parent_scoped(self, registry):
        t = _tool(registry, parent_tools=[],
                  parent_allow=[{"host": "api.github.com", "paths": ["/repos/"]}])
        err = t._check_egress_subset(
            [{"host": "api.github.com", "paths": ["/users/"]}])
        assert err and "/users/" in err

    def test_child_can_narrow_unrestricted_parent(self, registry):
        # parent allows the whole host; child narrowing to a path is a subset
        t = _tool(registry, parent_tools=[], parent_allow=["api.github.com"])
        assert t._check_egress_subset(
            [{"host": "api.github.com", "paths": ["/repos/"]}]) is None

    def test_glob_parent_accepts_member_via_path_probe(self, registry):
        # parent *.wikipedia.org; child en.wikipedia.org scoped to /wiki/ -> ok
        t = _tool(registry, parent_tools=[], parent_allow=["*.wikipedia.org"])
        assert t._check_egress_subset(
            [{"host": "en.wikipedia.org", "paths": ["/wiki/"]}]) is None


# ---------------------------------------------------------------------------
# execute(): refusal paths (no run minted)
# ---------------------------------------------------------------------------


class TestExecuteRefusals:
    @pytest.mark.asyncio
    async def test_empty_grant_refused_no_run_minted(self, registry):
        # Symmetry with /v1/agent/task (tools required, non-empty): a tool-free
        # child can do no work, so spawn refuses up front and mints nothing.
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[])
        out = await t.execute(task="x", tools=[])
        assert out.startswith("Denied: cannot spawn sub-agent")
        assert "non-empty" in out
        assert registry.list_runs() == []

    @pytest.mark.asyncio
    async def test_escalation_refused_no_run_minted(self, registry):
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[])
        out = await t.execute(task="x", tools=["write_file"])
        assert out.startswith("Denied: cannot spawn sub-agent")
        assert registry.list_runs() == []  # nothing created

    @pytest.mark.asyncio
    async def test_egress_widen_refused_no_run_minted(self, registry):
        t = _tool(registry, parent_tools=["fetch_url"], parent_allow=["api.github.com"])
        out = await t.execute(task="x", tools=["fetch_url"], allow_outbound=["evil.com"])
        assert out.startswith("Denied: cannot spawn sub-agent")
        assert registry.list_runs() == []

    @pytest.mark.asyncio
    async def test_consent_denied_no_run_minted(self, registry):
        # consent_policy="deny" -> the interactive consent gate is consulted;
        # a denying callback refuses the spawn (no child) AND emits spawn_denied.
        async def deny(_summary): return False
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[],
                  consent=deny, consent_policy="deny")
        out = await t.execute(task="x", tools=["read_file"])
        assert "cannot spawn sub-agent" in out
        assert registry.list_runs() == []
        evs = [e.type for e in registry.read_events("run_parent")]
        assert "spawn_denied" in evs

    @pytest.mark.asyncio
    async def test_deny_policy_no_channel_refuses_with_event(self, registry):
        # The bug found in trial: consent_policy="deny" + no interactive channel
        # (request_consent=None, the server context) -> spawn REFUSED, but now
        # with a VISIBLE spawn_denied event (was silent, model fell back).
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[],
                  consent=None, consent_policy="deny")
        out = await t.execute(task="x", tools=["read_file"])
        assert "cannot spawn sub-agent" in out
        # Actionable: points at the config, at its POST-ADR-0010 path. The
        # bare key name would still substring-match the old path, so assert
        # the full new location.
        assert "execution.task.consent.spawn_consent" in out
        assert registry.list_runs() == []
        evs = [e.type for e in registry.read_events("run_parent")]
        assert "spawn_denied" in evs

    @pytest.mark.asyncio
    async def test_auto_policy_spawns_without_consent_channel(self, registry, monkeypatch):
        # consent_policy="auto" -> server-context spawn proceeds with NO
        # interactive channel; subset rules remain the boundary.
        async def fake_runner(meta): return "child ok"
        monkeypatch.setattr(
            "ppxai.server.routes.agent_v1.build_task_runner",
            lambda reg, **kw: fake_runner,
        )
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[],
                  consent=None, consent_policy="auto")
        out = await t.execute(task="summarize", tools=["read_file"])
        assert "completed" in out and "child ok" in out
        assert len(registry.list_runs()) == 1  # child WAS minted

    @pytest.mark.asyncio
    async def test_subset_denial_emits_event(self, registry):
        # even with auto consent, a subset violation refuses + emits the event.
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[],
                  consent_policy="auto")
        out = await t.execute(task="x", tools=["write_file"])  # off-parent
        assert "cannot spawn sub-agent" in out
        evs = [e.type for e in registry.read_events("run_parent")]
        assert "spawn_denied" in evs


# ---------------------------------------------------------------------------
# execute(): happy path mints + runs + links a child (engine stubbed)
# ---------------------------------------------------------------------------


class TestExecuteSpawns:
    @pytest.mark.asyncio
    async def test_spawn_runs_child_and_returns_result(self, registry, monkeypatch):
        # Stub the shared runner so the child "runs" without a real provider.
        import ppxai.engine.tools.agent_spawn as spawn_mod

        async def fake_runner(meta):
            return f"child did: {meta.task}"

        def fake_build(reg, **kw):
            assert kw["allow_spawn"] is False  # depth=1: child can't spawn
            return fake_runner
        monkeypatch.setattr(
            "ppxai.server.routes.agent_v1.build_task_runner", fake_build
        )

        async def approve(_s): return True
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[], consent=approve)
        out = await t.execute(task="summarize", tools=["read_file"])

        assert "completed" in out and "child did: summarize" in out
        # exactly one child run, linked to the parent, marked a sub-agent slot
        runs = registry.list_runs()
        assert len(runs) == 1
        child = runs[0]
        assert child.parent_run_id == "run_parent"
        assert child.tools == ["read_file"]
        # parent stream recorded the spawn + finish lifecycle events
        evs = registry.read_events("run_parent")
        types = [e.type for e in evs]
        assert "subagent_spawned" in types
        assert "subagent_finished" in types

    @pytest.mark.asyncio
    async def test_child_inherits_parent_owner(self, registry, monkeypatch):
        # Inc 8b authz: the child run must inherit the parent's owner so it is
        # scoped to the SAME principal — NOT minted owner=None (which per-run
        # authz treats as readable by any authenticated caller = privilege leak).
        async def fake_runner(meta):
            return "ok"

        monkeypatch.setattr(
            "ppxai.server.routes.agent_v1.build_task_runner",
            lambda reg, **kw: fake_runner,
        )

        async def approve(_s):
            return True

        t = _tool(
            registry, parent_tools=["read_file"], parent_allow=[],
            consent=approve, parent_owner="alice",
        )
        await t.execute(task="summarize", tools=["read_file"])

        child = registry.list_runs()[0]
        assert child.owner == "alice"

    @pytest.mark.asyncio
    async def test_wait_timeout_cancels_child_not_orphan(self, registry, monkeypatch):
        # codex MINOR: on wait timeout the parent must CANCEL the child, not
        # leave it running. Use a runner that polls its control (so cancel can
        # stop it) and never finishes on its own; shrink the wait cap so the
        # timeout path fires fast.
        import asyncio
        import ppxai.engine.tools.agent_spawn as spawn_mod
        monkeypatch.setattr(spawn_mod, "_DEFAULT_CHILD_WAIT_S", 0.2)

        async def forever_runner(meta):
            ctl = registry.get_control(meta.run_id)
            for _ in range(10000):
                ctl.check(now=0.0)        # cooperative: raises RunCancelled
                await asyncio.sleep(0.01)
            return "never"

        monkeypatch.setattr(
            "ppxai.server.routes.agent_v1.build_task_runner",
            lambda reg, **kw: forever_runner,
        )
        async def approve(_s): return True
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[], consent=approve)
        out = await t.execute(task="hang", tools=["read_file"])

        # parent reports a non-completed end, and the child is terminal
        # (cancelled) — NOT still running/orphaned.
        child = registry.list_runs()[0]
        assert child.status in ("cancelled", "interrupted", "failed")
        assert "completed" not in out
        # the child's control was cleaned up (run finished, not orphaned)
        assert registry.get_control(child.run_id) is None

    @pytest.mark.asyncio
    async def test_parent_cancel_propagates_to_child_promptly(self, registry, monkeypatch):
        # Item 37e: when the PARENT is cancelled while awaiting a child, the
        # child must be cancelled promptly (within a tick), NOT after the full
        # wait cap. We register a parent control, flip cancel_requested shortly
        # after the spawn, and assert the child lands cancelled well before the
        # (large) wait cap would have fired.
        import asyncio
        import ppxai.engine.tools.agent_spawn as spawn_mod
        from ppxai.engine.agent_runs import RunControl
        # Large cap so a pass can ONLY come from the parent-cancel path, not a timeout.
        monkeypatch.setattr(spawn_mod, "_DEFAULT_CHILD_WAIT_S", 30.0)

        # Register the parent's cooperative control (keyed by parent_run_id).
        parent_ctl = RunControl(run_id="run_parent", budget={}, started_at=0.0)
        registry._controls["run_parent"] = parent_ctl

        async def forever_runner(meta):
            ctl = registry.get_control(meta.run_id)
            for _ in range(10000):
                ctl.check(now=0.0)  # cooperative: raises when cancelled
                await asyncio.sleep(0.01)
            return "never"

        monkeypatch.setattr(
            "ppxai.server.routes.agent_v1.build_task_runner",
            lambda reg, **kw: forever_runner,
        )

        async def approve(_s):
            return True

        async def flip_parent_cancel():
            await asyncio.sleep(0.2)  # let the child start + parent enter _await_child
            parent_ctl.cancel_requested = True

        t = _tool(registry, parent_tools=["read_file"], parent_allow=[], consent=approve)
        flipper = asyncio.create_task(flip_parent_cancel())
        out = await asyncio.wait_for(t.execute(task="hang", tools=["read_file"]), timeout=10.0)
        await flipper

        child = registry.list_runs()[0]
        assert child.status in ("cancelled", "interrupted", "failed")
        assert "completed" not in out

# ---------------------------------------------------------------------------
# Denial classification (deny != malfunction)
# ---------------------------------------------------------------------------


class TestDenialClassification:
    """A spawn refusal is the tool WORKING as designed (policy said no), not a
    malfunction. The old "Error:"-prefixed denial string made
    `_compute_tool_success` (engine/chat.py) count every denial toward the
    zombie circuit-breaker and reframe the model's next turn with
    failure-recovery prompting — the deny path's head start toward the silent
    empty-result exits (live 2026-07-12, /task runs finishing with chars=0).
    """

    def test_denial_not_classified_as_tool_failure(self, registry):
        from ppxai.engine.chat import _compute_tool_success
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[])
        out = t._deny(
            "spawn not approved (denied, or the consent request expired "
            "unanswered)",
            "consent",
        )
        assert out.startswith("Denied:")
        assert _compute_tool_success("spawn_subagent", out) is True

    def test_real_spawn_malfunction_still_classified_as_failure(self):
        # The non-policy failure path (runner couldn't start) keeps its
        # "Error:" prefix and keeps counting toward the breaker.
        from ppxai.engine.chat import _compute_tool_success
        assert _compute_tool_success(
            "spawn_subagent", "Error: failed to start sub-agent: boom"
        ) is False
