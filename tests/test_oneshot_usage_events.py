"""The tool-free oneshot paths record their own tokens (ADR 0008).

`/cost` sums the cross-tier usage log. The search-loop oneshot path and
`/task` runs record through the task runner, but the plain `/v1/oneshot`
call and the tool-free `/v1/agent/run` recorded nothing, so `/cost` never
counted them. Found 2026-09-27 while adding retrieval grounding.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import ppxai.server.http as http_module
import ppxai.server.state as state
from ppxai.config import execution as exec_mod
from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.server.routes import agent_v1
from ppxai.server.routes import oneshot as oneshot_mod
from ppxai.usage_events import TIER_ONESHOT, read_usage_events

USAGE = {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        state, "_agent_run_registry",
        AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs")),
    )
    monkeypatch.setattr(oneshot_mod, "get_execution_run_grounding_mode", lambda: "off")
    monkeypatch.setattr(oneshot_mod, "_oneshot_effective_path", lambda p, m: "closed-book")
    monkeypatch.setattr(oneshot_mod, "get_default_provider", lambda: "gemini")
    monkeypatch.setattr(oneshot_mod, "get_default_model", lambda p: "gemini-3.8-flash")


def _provider(usage=USAGE):
    fake = MagicMock()
    fake.oneshot.return_value = {
        "content": "ok", "finish_reason": "stop", "model": "echoed-id", "usage": usage,
    }
    return fake


@pytest.fixture
def http_client():
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


class TestPlainOneshot:

    def test_the_call_is_recorded_under_the_oneshot_tier(self, http_client, monkeypatch):
        calls: list = []
        monkeypatch.setattr(oneshot_mod, "_build_provider", lambda n, **kw: _provider())
        monkeypatch.setattr(oneshot_mod, "record_usage", lambda **kw: calls.append(kw) or True)
        monkeypatch.setattr(oneshot_mod, "calculate_cost",
                            lambda p, c, model, provider: 0.0123 if model == "gemini-3.8-flash" else -1)
        r = http_client.post("/v1/oneshot", json={"prompt": "Hi"})
        assert r.status_code == 200, r.text
        [ev] = calls
        assert ev["tier"] == TIER_ONESHOT
        assert (ev["provider"], ev["model"]) == ("gemini", "gemini-3.8-flash")
        assert (ev["prompt_tokens"], ev["completion_tokens"]) == (1200, 300)
        # Priced by the requested id (the pricing key), not the echoed one.
        assert ev["estimated_cost"] == pytest.approx(0.0123)
        assert ev["run_id"]

    def test_no_usage_from_the_provider_records_zeros(self, http_client, monkeypatch):
        calls: list = []
        monkeypatch.setattr(oneshot_mod, "_build_provider", lambda n, **kw: _provider(None))
        monkeypatch.setattr(oneshot_mod, "record_usage", lambda **kw: calls.append(kw) or True)
        assert http_client.post("/v1/oneshot", json={"prompt": "Hi"}).status_code == 200
        assert (calls[0]["prompt_tokens"], calls[0]["completion_tokens"]) == (0, 0)

    def test_accounting_failure_never_fails_the_request(self, http_client, monkeypatch):
        def boom(**kw):
            raise RuntimeError("disk full")
        monkeypatch.setattr(oneshot_mod, "_build_provider", lambda n, **kw: _provider())
        monkeypatch.setattr(oneshot_mod, "record_usage", boom)
        r = http_client.post("/v1/oneshot", json={"prompt": "Hi"})
        assert r.status_code == 200 and r.json()["content"] == "ok"

    def test_the_wire_is_unchanged(self, http_client, monkeypatch):
        monkeypatch.setattr(oneshot_mod, "_build_provider", lambda n, **kw: _provider())
        monkeypatch.setattr(oneshot_mod, "record_usage", lambda **kw: True)
        body = http_client.post("/v1/oneshot", json={"prompt": "Hi"}).json()
        assert set(body) == {"content", "finish_reason", "model", "provider", "usage"}

    def test_the_event_reaches_the_real_sink(self, http_client, monkeypatch, tmp_path):
        """End to end through the real `record_usage`, read back the way
        `/cost` reads it."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(oneshot_mod, "_build_provider", lambda n, **kw: _provider())
        assert http_client.post("/v1/oneshot", json={"prompt": "Hi"}).status_code == 200
        events, skipped = read_usage_events(tier=TIER_ONESHOT)
        assert skipped == 0
        [ev] = events
        assert ev.provider == "gemini" and ev.prompt_tokens == 1200


class TestToolFreeAgentRun:

    def test_the_run_is_recorded(self, tmp_path, monkeypatch):
        calls: list = []
        monkeypatch.setattr(exec_mod, "get_execution_collect", lambda: "no")
        monkeypatch.setattr(exec_mod, "get_execution_run_grounding_mode", lambda: "off")
        monkeypatch.setattr(exec_mod, "get_execution_run_config",
                            lambda: {"web_search": False, "grounding": False})
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _provider())
        monkeypatch.setattr(oneshot_mod, "record_usage", lambda **kw: calls.append(kw) or True)
        monkeypatch.setattr(oneshot_mod, "calculate_cost", lambda *a, **k: 0.5)

        app = FastAPI()
        app.include_router(agent_v1.router)
        resp = TestClient(app).post(
            "/v1/agent/run", json={"task": "t", "provider": "p", "model": "m"},
        )
        assert resp.status_code == 200, resp.text
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not calls:
            time.sleep(0.02)
        [ev] = calls
        assert ev["tier"] == TIER_ONESHOT and (ev["provider"], ev["model"]) == ("p", "m")
        assert ev["estimated_cost"] == 0.5
        assert ev["run_id"] == resp.json()["run_id"]
