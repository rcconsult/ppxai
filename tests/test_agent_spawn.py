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


def _tool(registry, *, parent_tools, parent_allow, consent=None):
    return SpawnSubagentTool(
        registry=registry,
        parent_run_id="run_parent",
        parent_tools=parent_tools,
        parent_allow_outbound=parent_allow,
        parent_provider="p",
        parent_model="m",
        request_consent=consent,
    )


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


# ---------------------------------------------------------------------------
# execute(): refusal paths (no run minted)
# ---------------------------------------------------------------------------


class TestExecuteRefusals:
    @pytest.mark.asyncio
    async def test_escalation_refused_no_run_minted(self, registry):
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[])
        out = await t.execute(task="x", tools=["write_file"])
        assert out.startswith("Error: cannot spawn sub-agent")
        assert registry.list_runs() == []  # nothing created

    @pytest.mark.asyncio
    async def test_egress_widen_refused_no_run_minted(self, registry):
        t = _tool(registry, parent_tools=["fetch_url"], parent_allow=["api.github.com"])
        out = await t.execute(task="x", tools=["fetch_url"], allow_outbound=["evil.com"])
        assert out.startswith("Error: cannot spawn sub-agent")
        assert registry.list_runs() == []

    @pytest.mark.asyncio
    async def test_consent_denied_no_run_minted(self, registry):
        async def deny(_summary, _wd): return False
        t = _tool(registry, parent_tools=["read_file"], parent_allow=[], consent=deny)
        out = await t.execute(task="x", tools=["read_file"])
        assert "denied permission" in out
        assert registry.list_runs() == []


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

        async def approve(_s, _w): return True
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
