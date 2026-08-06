"""U4 (ADR 0011): execution.collect — the hold_result mapping, the plain-merge
endpoint, and the config accessor.

- `get_execution_collect()`: auto | yes (default) | no, unknown → yes.
- Launch mapping: "yes" → T6 hold (completed_pending_ack); "auto"/"no" →
  auto-finalize (completed) on BOTH /v1/agent/task and /v1/agent/run.
- POST /sessions/merge-run-result: appends the run's result to the active
  session as a plain assistant message (Q3 — no provenance tagging);
  403 under collect="no"; 404/409 on unknown/resultless runs; owner-guarded
  for remote callers.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore


# ---------------------------------------------------------------------------
# Config accessor
# ---------------------------------------------------------------------------


class TestExecutionCollectConfig:
    def _with_execution(self, monkeypatch, block):
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(
            exec_mod, "get_execution_config", lambda: dict(block)
        )

    def test_default_is_yes(self, monkeypatch):
        from ppxai.config.execution import get_execution_collect
        self._with_execution(monkeypatch, {})
        assert get_execution_collect() == "yes"

    @pytest.mark.parametrize("value", ["auto", "yes", "no"])
    def test_reads_valid_values(self, monkeypatch, value):
        from ppxai.config.execution import get_execution_collect
        self._with_execution(monkeypatch, {"collect": value})
        assert get_execution_collect() == value

    def test_unknown_value_normalizes_to_yes(self, monkeypatch):
        from ppxai.config.execution import get_execution_collect
        self._with_execution(monkeypatch, {"collect": "sometimes"})
        assert get_execution_collect() == "yes"

    def test_case_insensitive(self, monkeypatch):
        from ppxai.config.execution import get_execution_collect
        self._with_execution(monkeypatch, {"collect": "AUTO"})
        assert get_execution_collect() == "auto"


# ---------------------------------------------------------------------------
# hold_result mapping at launch (both families)
# ---------------------------------------------------------------------------


@pytest.fixture
def v1_client(tmp_path, monkeypatch):
    import ppxai.server.state as state
    from ppxai.server.routes import agent_v1

    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)
    real = agent_v1.get_execution_task_config
    monkeypatch.setattr(
        agent_v1, "get_execution_task_config",
        lambda: {**real(), "enabled": True},
    )
    # Pin the one-off grant rule off — these tests are about the hold.
    from ppxai.config import execution as exec_mod
    monkeypatch.setattr(
        exec_mod, "get_execution_run_config",
        lambda: {"web_search": False, "grounding": False},
    )
    app = FastAPI()
    app.include_router(agent_v1.router)
    return TestClient(app), reg


def _pin_collect(monkeypatch, value):
    from ppxai.config import execution as exec_mod
    monkeypatch.setattr(exec_mod, "get_execution_collect", lambda: value)


def _fake_provider():
    from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

    class _FakeProvider(OpenAICompatibleProvider):
        def __init__(self):
            pass

        def oneshot(self, *, prompt, model, system=None, **kw):
            return {"content": f"echo: {prompt}", "finish_reason": "stop"}

    return _FakeProvider()


def _poll_terminal(c, run_id, timeout_s=5.0):
    import time as _t
    terminal = ("completed", "completed_pending_ack", "finalized",
                "failed", "cancelled", "interrupted")
    deadline = _t.monotonic() + timeout_s
    while _t.monotonic() < deadline:
        one = c.get(f"/v1/agent/runs/{run_id}").json()
        if one["status"] in terminal:
            return one
        _t.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish: last={one}")


class TestHoldResultMapping:
    @pytest.mark.parametrize("mode,expected_status", [
        ("yes", "completed_pending_ack"),
        ("auto", "completed"),
        ("no", "completed"),
    ])
    def test_run_family_hold_follows_collect(
        self, v1_client, monkeypatch, mode, expected_status
    ):
        c, reg = v1_client
        from ppxai.server.routes import agent_v1
        _pin_collect(monkeypatch, mode)
        monkeypatch.setattr(
            agent_v1, "_build_provider", lambda name: _fake_provider()
        )
        resp = c.post("/v1/agent/run", json={
            "task": "ping", "provider": "p", "model": "m",
        })
        assert resp.status_code == 200
        one = _poll_terminal(c, resp.json()["run_id"])
        assert one["status"] == expected_status

    @pytest.mark.parametrize("mode,expected_hold", [
        ("yes", True), ("auto", False), ("no", False),
    ])
    def test_task_family_hold_follows_collect(
        self, v1_client, monkeypatch, mode, expected_hold
    ):
        # The /task route's hold flag at launch (stubbed runner — we only
        # care about the start_run stamping, not the sandbox).
        c, reg = v1_client
        from ppxai.server.routes import agent_v1
        _pin_collect(monkeypatch, mode)
        monkeypatch.setattr(
            agent_v1, "_validate_provider_or_400", lambda name: None
        )

        def _stub_runner(registry, **kw):
            async def _r(m):
                return "done"
            return _r

        monkeypatch.setattr(agent_v1, "build_task_runner", _stub_runner)
        resp = c.post("/v1/agent/task", json={
            "task": "do a thing", "tools": ["read_file"],
            "provider": "p", "model": "m",
        })
        assert resp.status_code == 200, resp.text
        run_id = resp.json()["run_id"]
        _poll_terminal(c, run_id)
        meta = reg.get_run(run_id)
        assert bool(getattr(meta, "hold_result", False)) is expected_hold


# ---------------------------------------------------------------------------
# The merge endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def merge_client(tmp_path, monkeypatch):
    import ppxai.server.state as state
    from ppxai.server.routes import sessions as sessions_route

    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)

    added = []

    class _FakeConvo:
        def add_message(self, message):
            added.append(message)

    engine = SimpleNamespace(session=_FakeConvo(), drain_events=lambda: [])
    app = FastAPI()
    app.include_router(sessions_route.router)
    app.dependency_overrides[sessions_route.get_session] = (
        lambda: SimpleNamespace(engine=engine)
    )
    return TestClient(app), reg, added


class TestMergeEndpoint:
    def _finished_run(self, reg, result="the answer", owner=None):
        m = reg.start_run("t", provider="p", model="m", owner=owner)
        reg.finish_run(m, status="completed", result=result)
        return m

    def test_merges_plain_task_result_exchange(self, merge_client, monkeypatch):
        c, reg, added = merge_client
        _pin_collect(monkeypatch, "yes")
        m = self._finished_run(reg, result="42 is the answer")
        r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
        assert r.status_code == 200, r.text
        assert r.json()["merged"] is True
        assert r.json()["chars"] == len("42 is the answer")
        # Q3 plain merge, alternation-proof shape: the run's own task as the
        # user turn, its result as the assistant turn, both verbatim — a lone
        # merged message of either role gets dropped/collapsed by
        # validate_and_fix_alternation (live U4 trial catch).
        assert len(added) == 2
        assert added[0].role == "user" and added[0].content == m.task
        assert added[1].role == "assistant"
        assert added[1].content == "42 is the answer"

    def test_collect_no_refuses_403_with_hint(self, merge_client, monkeypatch):
        c, reg, added = merge_client
        _pin_collect(monkeypatch, "no")
        m = self._finished_run(reg)
        r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
        assert r.status_code == 403
        assert "execution.collect" in r.json()["detail"]
        assert added == []

    def test_unknown_run_404(self, merge_client, monkeypatch):
        c, _reg, added = merge_client
        _pin_collect(monkeypatch, "yes")
        r = c.post("/sessions/merge-run-result",
                   json={"run_id": "run_nope00000"})
        assert r.status_code == 404
        assert added == []

    def test_resultless_run_409(self, merge_client, monkeypatch):
        c, reg, added = merge_client
        _pin_collect(monkeypatch, "yes")
        m = reg.start_run("t", provider="p", model="m")  # still running
        r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
        assert r.status_code == 409
        assert added == []

    def test_owned_run_remote_wrong_owner_403(self, merge_client, monkeypatch):
        # TestClient's host is "testclient" (not loopback) and no principal
        # rides on request.state → caller owner None ≠ "alice" → 403.
        c, reg, added = merge_client
        _pin_collect(monkeypatch, "yes")
        m = self._finished_run(reg, owner="alice")
        r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
        assert r.status_code == 403
        assert added == []

    def test_owned_run_loopback_allowed(self, merge_client, monkeypatch):
        # Loopback keeps the UI exemption's on-the-host trust basis.
        import ppxai.server.auth as auth_mod
        c, reg, added = merge_client
        _pin_collect(monkeypatch, "yes")
        monkeypatch.setattr(auth_mod, "_is_loopback", lambda request: True)
        m = self._finished_run(reg, owner="alice", result="local ok")
        r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
        assert r.status_code == 200
        assert added and added[-1].content == "local ok"

    def test_unowned_run_remote_allowed(self, merge_client, monkeypatch):
        # An unowned run has no principal to protect (mirrors the /v1 read
        # exemption's unowned rule); the auth layer already required a valid
        # token for a remote caller to reach the sessions surface at all.
        c, reg, added = merge_client
        _pin_collect(monkeypatch, "yes")
        m = self._finished_run(reg, owner=None, result="open ok")
        r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
        assert r.status_code == 200
        assert added and added[-1].content == "open ok"


# ---------------------------------------------------------------------------
# GET /config/execution
# ---------------------------------------------------------------------------


class TestConfigExecutionRoute:
    def test_reports_collect_mode(self, monkeypatch):
        from ppxai.server.routes import config as config_route
        _pin_collect(monkeypatch, "auto")
        app = FastAPI()
        app.include_router(config_route.router)
        r = TestClient(app).get("/config/execution")
        assert r.status_code == 200
        assert r.json() == {"collect": "auto"}
