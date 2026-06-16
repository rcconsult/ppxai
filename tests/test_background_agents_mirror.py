"""AppState background_agents mirror (v1.19.0, Inc 9).

The server-global AgentRunRegistry exposes a compact active-run summary and
an on_change hook; the server mirrors it into AppState (`background_agents`)
so connected clients get a state_sync push and reconnecting clients get it
from GET /state.
"""

from __future__ import annotations

import pytest

from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.app_state import AppState


@pytest.fixture
def reg(tmp_path):
    return AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))


class TestActiveSummary:
    def test_empty_when_no_runs(self, reg):
        assert reg.active_summary() == []

    def test_includes_pending_and_running(self, reg):
        m = reg.start_run(task="do a thing", owner="alice")
        summary = reg.active_summary()
        assert len(summary) == 1
        entry = summary[0]
        assert entry["run_id"] == m.run_id
        assert entry["task"] == "do a thing"
        assert entry["owner"] == "alice"
        assert entry["status"] == "pending"

    def test_excludes_terminal_runs(self, reg):
        m = reg.start_run(task="x")
        reg.finish_run(m, status="completed", result="done")
        assert reg.active_summary() == []

    def test_only_badge_fields_exposed(self, reg):
        reg.start_run(task="secret", owner="alice")
        entry = reg.active_summary()[0]
        # Never leak result/error/events through the summary.
        assert set(entry.keys()) == {"run_id", "status", "task", "owner"}

    def test_newest_first(self, reg):
        a = reg.start_run(task="first")
        b = reg.start_run(task="second")
        ids = [e["run_id"] for e in reg.active_summary()]
        # list_runs (and thus active_summary) is newest-first.
        assert ids.index(b.run_id) < ids.index(a.run_id)


class TestOnChange:
    def test_hook_fires_on_finish(self, reg):
        calls = []
        reg.on_change(lambda: calls.append(reg.active_summary()))
        m = reg.start_run(task="x")
        reg.finish_run(m, status="completed", result="r")
        # finish_run fired the hook at least once; last snapshot is empty.
        assert calls and calls[-1] == []

    def test_bad_listener_does_not_raise(self, reg):
        def boom():
            raise RuntimeError("listener blew up")

        reg.on_change(boom)
        m = reg.start_run(task="x")
        # Must not propagate — run lifecycle keeps working.
        reg.finish_run(m, status="completed", result="r")


class TestSchemaField:
    def test_background_agents_in_schema(self):
        assert "background_agents" in AppState.FIELDS
        assert AppState.FIELDS["background_agents"] == []

    def test_in_sse_sync_fields(self):
        from ppxai.engine.client import SSE_SYNC_FIELDS

        assert "background_agents" in SSE_SYNC_FIELDS

    def test_appstate_holds_run_summaries(self):
        st = AppState()
        st.set("background_agents", [{"run_id": "run_1", "status": "running",
                                      "task": "t", "owner": "alice"}])
        assert st.get("background_agents")[0]["run_id"] == "run_1"
