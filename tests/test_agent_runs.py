"""Tests for the agent run registry + /v1/agent/* routes (ADR 0003 Stage 2, Inc 1).

Inc 1 scope: minimal run lifecycle — create/persist/list/get, synchronous
execution. Provider calls are not exercised here (that path is oneshot's,
already tested); these tests cover the registry, the filesystem store, and
the route surface with the provider call bypassed by seeding terminal runs
directly through the registry.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ppxai.engine.agent_runs import (
    AgentRunRegistry,
    FilesystemAgentRunStore,
    RunMeta,
)


@pytest.fixture
def registry(tmp_path: Path) -> AgentRunRegistry:
    return AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))


# ---------------------------------------------------------------------------
# RunMeta dataclass
# ---------------------------------------------------------------------------


class TestRunMeta:
    def test_roundtrip_to_from_dict(self):
        m = RunMeta(run_id="run_x", task="t", tools=["read_file"], created_at=1.0)
        assert RunMeta.from_dict(m.to_dict()) == m

    def test_from_dict_ignores_unknown_keys(self):
        # Forward-compat read: a newer writer's extra field must not crash an
        # older reader.
        d = {"run_id": "run_x", "task": "t", "future_field": "ignored"}
        m = RunMeta.from_dict(d)
        assert m.run_id == "run_x"
        assert not hasattr(m, "future_field")

    def test_defaults(self):
        m = RunMeta(run_id="r", task="t")
        assert m.status == "pending"
        assert m.agent_n == 0
        assert m.tools == []


# ---------------------------------------------------------------------------
# Registry + filesystem store
# ---------------------------------------------------------------------------


class TestAgentRunRegistry:
    def test_create_persists_and_returns_meta(self, registry, tmp_path):
        m = registry.start_run("say hi", tools=["read_file"], provider="p", model="m")
        assert m.run_id.startswith("run_")
        assert m.status == "pending"
        assert m.tools == ["read_file"]
        # on disk at the ADR 0005 Triplet path
        assert (tmp_path / "runs" / m.run_id / "agent-0" / "meta.json").exists()

    def test_run_ids_are_unique(self, registry):
        ids = {registry.start_run("t").run_id for _ in range(20)}
        assert len(ids) == 20

    def test_get_run_returns_persisted(self, registry):
        m = registry.start_run("t")
        got = registry.get_run(m.run_id)
        assert got is not None and got.run_id == m.run_id

    def test_get_unknown_returns_none(self, registry):
        assert registry.get_run("run_does_not_exist") is None

    def test_finish_run_marks_terminal(self, registry):
        m = registry.start_run("t")
        registry.finish_run(m, status="completed", result="hello")
        got = registry.get_run(m.run_id)
        assert got.status == "completed"
        assert got.result == "hello"
        assert got.finished_at is not None

    def test_finish_run_records_error(self, registry):
        m = registry.start_run("t")
        registry.finish_run(m, status="failed", error="boom")
        got = registry.get_run(m.run_id)
        assert got.status == "failed" and got.error == "boom"

    def test_list_runs_newest_first(self, registry):
        m1 = registry.start_run("first")
        m2 = registry.start_run("second")
        runs = registry.list_runs()
        assert [r.run_id for r in runs] == [m2.run_id, m1.run_id]

    def test_list_empty_when_no_runs(self, registry):
        assert registry.list_runs() == []

    def test_corrupt_meta_skipped_not_fatal(self, registry, tmp_path):
        m = registry.start_run("good")
        # Plant a corrupt run dir alongside the good one.
        bad = tmp_path / "runs" / "run_corrupt" / "agent-0"
        bad.mkdir(parents=True)
        (bad / "meta.json").write_text("{not json", encoding="utf-8")
        runs = registry.list_runs()
        # good run still listed; corrupt one skipped, no exception
        assert m.run_id in [r.run_id for r in runs]


# ---------------------------------------------------------------------------
# /v1/agent/* routes (provider call bypassed)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    import ppxai.server.state as state
    from ppxai.server.routes import agent_v1

    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)

    app = FastAPI()
    app.include_router(agent_v1.router)
    return TestClient(app), reg


class TestAgentRunRoutes:
    def test_list_empty(self, client):
        c, _ = client
        assert c.get("/v1/agent/runs").json() == {"runs": []}

    def test_get_unknown_404(self, client):
        c, _ = client
        assert c.get("/v1/agent/runs/run_nope").status_code == 404

    def test_seeded_run_lists_and_fetches(self, client):
        c, reg = client
        m = reg.start_run("manual", tools=["read_file"], provider="p", model="m")
        reg.finish_run(m, status="completed", result="hi")

        listed = c.get("/v1/agent/runs").json()["runs"]
        assert [r["run_id"] for r in listed] == [m.run_id]
        assert listed[0]["tools"] == ["read_file"]

        one = c.get(f"/v1/agent/runs/{m.run_id}").json()
        assert one["status"] == "completed"
        assert one["result"] == "hi"

    def test_no_provider_400_and_no_run_created(self, client, monkeypatch):
        # No provider given and no default configured -> 400, no run created.
        c, reg = client
        from ppxai.server.routes import agent_v1
        monkeypatch.setattr(agent_v1, "get_default_provider", lambda: "")
        resp = c.post("/v1/agent/run", json={"task": "t"})
        assert resp.status_code == 400
        assert reg.list_runs() == []

    def test_happy_path_creates_and_completes_run(self, client, monkeypatch):
        # Full POST flow with the LLM call stubbed: a fake OpenAI-compatible
        # provider returns a canned oneshot result. Asserts the run is created,
        # executed, marked completed with the result, and persisted.
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        monkeypatch.setattr(agent_v1, "get_default_provider", lambda: "fakeprov")
        monkeypatch.setattr(agent_v1, "get_default_model", lambda p: "fakemodel")

        class _FakeProvider(OpenAICompatibleProvider):
            def __init__(self):  # bypass real provider construction
                pass

            def oneshot(self, *, prompt, model, system=None, **kw):
                return {"content": f"echo: {prompt}", "finish_reason": "stop"}

        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _FakeProvider())

        resp = c.post("/v1/agent/run", json={"task": "ping", "tools": ["read_file"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        run_id = body["run_id"]

        # persisted + fetchable with the result + recorded grant
        one = c.get(f"/v1/agent/runs/{run_id}").json()
        assert one["status"] == "completed"
        assert one["result"] == "echo: ping"
        assert one["tools"] == ["read_file"]
        assert one["provider"] == "fakeprov" and one["model"] == "fakemodel"

    def test_provider_failure_marks_run_failed(self, client, monkeypatch):
        # If the LLM call raises, the run is recorded as failed (not lost) and
        # the POST still returns 200 with status=failed (the run exists).
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        monkeypatch.setattr(agent_v1, "get_default_provider", lambda: "fakeprov")
        monkeypatch.setattr(agent_v1, "get_default_model", lambda p: "fakemodel")

        class _BoomProvider(OpenAICompatibleProvider):
            def __init__(self):
                pass

            def oneshot(self, *, prompt, model, system=None, **kw):
                raise RuntimeError("upstream 503")

        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _BoomProvider())

        resp = c.post("/v1/agent/run", json={"task": "ping"})
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]
        one = c.get(f"/v1/agent/runs/{run_id}").json()
        assert one["status"] == "failed"
        assert "upstream 503" in one["error"]

    def test_unsupported_provider_400_marks_failed(self, client, monkeypatch):
        # A non-OpenAI-compatible provider -> 400, and the run is recorded
        # failed (honest record), not left dangling as pending.
        c, reg = client
        from ppxai.server.routes import agent_v1

        monkeypatch.setattr(agent_v1, "get_default_provider", lambda: "fakeprov")
        monkeypatch.setattr(agent_v1, "get_default_model", lambda p: "fakemodel")
        # _build_provider returns something that's NOT an OpenAICompatibleProvider
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: object())

        resp = c.post("/v1/agent/run", json={"task": "ping"})
        assert resp.status_code == 400
        # the run was created then marked failed
        runs = reg.list_runs()
        assert len(runs) == 1 and runs[0].status == "failed"
