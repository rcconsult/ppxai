"""Tests for the v1 gateway primitive: POST /v1/oneshot.

Covers:
1. Request validation (empty prompt, missing model with no default, etc.)
2. Provider construction failure (unknown provider, no API key)
3. Response shape — pinned as part of the stable v1 contract
4. response_format / max_tokens / temperature plumb through to the
   provider call
5. Provider exceptions surface as 502 (not 500 / 200-with-error)

The provider call is mocked at the boundary — these tests exercise the
route's contract, not OpenAI SDK behavior. End-to-end provider tests
live in tests/test_provider_throttle.py and the per-provider modules.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient


@pytest.fixture
def http_client():
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def stub_provider():
    """Patch _build_provider so we don't need a real API key configured.

    Returns the mock so individual tests can assert call_args.
    """
    fake = MagicMock()
    fake.oneshot.return_value = {
        "content": "stub-response",
        "finish_reason": "stop",
        "model": "stub-model",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    # Make isinstance(fake, OpenAICompatibleProvider) pass.
    from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
    fake.__class__ = OpenAICompatibleProvider
    with patch(
        "ppxai.server.routes.oneshot._build_provider", return_value=fake
    ):
        yield fake


class TestRequestValidation:
    def test_empty_prompt_rejected(self, http_client):
        r = http_client.post("/v1/oneshot", json={"prompt": ""})
        assert r.status_code == 422  # pydantic min_length

    def test_missing_prompt_rejected(self, http_client):
        r = http_client.post("/v1/oneshot", json={})
        assert r.status_code == 422

    def test_negative_max_tokens_rejected(self, http_client):
        r = http_client.post(
            "/v1/oneshot", json={"prompt": "hi", "max_tokens": -1}
        )
        assert r.status_code == 422

    def test_temperature_above_2_rejected(self, http_client):
        r = http_client.post(
            "/v1/oneshot", json={"prompt": "hi", "temperature": 3.0}
        )
        assert r.status_code == 422


class TestProviderResolution:
    def test_unknown_provider_400(self, http_client):
        r = http_client.post(
            "/v1/oneshot",
            json={"prompt": "hi", "provider": "no_such_provider", "model": "x"},
        )
        assert r.status_code == 400
        assert "no_such_provider" in r.json()["detail"]

    def test_no_default_model_falls_through_helpfully(self, http_client):
        # Provider exists but no model specified and no default_model →
        # 400 with a clear message. We patch get_default_model to None
        # to simulate this, alongside _build_provider so we don't need
        # a real provider config / API key.
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
        fake = MagicMock()
        fake.__class__ = OpenAICompatibleProvider
        with patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value=None
        ), patch(
            "ppxai.server.routes.oneshot._build_provider", return_value=fake
        ):
            r = http_client.post(
                "/v1/oneshot",
                json={"prompt": "hi", "provider": "perplexity"},
            )
        assert r.status_code == 400
        assert "default_model" in r.json()["detail"]


class TestResponseShape:
    """Pin the v1 response contract — semver-stable per docs/api-gateway.md."""

    def test_success_returns_full_envelope(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})

        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {
            "content", "finish_reason", "model", "provider", "usage"
        }
        assert body["content"] == "stub-response"
        assert body["finish_reason"] == "stop"
        assert body["model"] == "stub-model"
        assert body["provider"] == "custom"
        assert body["usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_usage_can_be_null(self, http_client, stub_provider):
        stub_provider.oneshot.return_value = {
            "content": "x",
            "finish_reason": "stop",
            "model": "m",
            "usage": None,
        }
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})
        assert r.status_code == 200
        assert r.json()["usage"] is None


class TestParameterPlumbing:
    """response_format / max_tokens / temperature must reach the provider."""

    def test_response_format_forwarded(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            http_client.post(
                "/v1/oneshot",
                json={
                    "prompt": "Hello",
                    "response_format": {"type": "json_object"},
                },
            )
        kwargs = stub_provider.oneshot.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_max_tokens_forwarded(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            http_client.post(
                "/v1/oneshot", json={"prompt": "Hello", "max_tokens": 256}
            )
        assert stub_provider.oneshot.call_args.kwargs["max_tokens"] == 256

    def test_temperature_forwarded(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            http_client.post(
                "/v1/oneshot", json={"prompt": "Hello", "temperature": 0.0}
            )
        assert stub_provider.oneshot.call_args.kwargs["temperature"] == 0.0

    def test_system_message_forwarded(self, http_client, stub_provider):
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            http_client.post(
                "/v1/oneshot",
                json={"prompt": "Hello", "system": "You are terse."},
            )
        assert stub_provider.oneshot.call_args.kwargs["system"] == "You are terse."


class TestProviderErrors:
    def test_provider_exception_surfaces_as_502(self, http_client, stub_provider):
        stub_provider.oneshot.side_effect = RuntimeError("API down")
        with patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="custom"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="qwen3"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})
        assert r.status_code == 502
        assert "API down" in r.json()["detail"]


class TestProviderCapabilityCheck:
    """v1.19.x: /v1/oneshot is provider-AGNOSTIC — oneshot() is part of the
    BaseProvider contract, so any buildable provider works (no
    isinstance-by-class 400). Only an unbuildable provider 400s."""

    def test_any_provider_with_oneshot_succeeds(self, http_client):
        # A non-OpenAICompatibleProvider whose oneshot() returns the contract
        # dict must now be accepted (was rejected by class pre-1.19.x).
        prov = MagicMock()
        prov.oneshot.return_value = {
            "content": "hi", "finish_reason": "stop",
            "model": "some_model", "usage": None,
        }
        with patch(
            "ppxai.server.routes.oneshot._build_provider", return_value=prov
        ), patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="some_provider"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="some_model"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})
        assert r.status_code == 200
        assert r.json()["content"] == "hi"

    def test_unbuildable_provider_400(self, http_client):
        from fastapi import HTTPException

        def _raise(name):
            raise HTTPException(status_code=400, detail=f"unknown provider {name!r}")
        with patch(
            "ppxai.server.routes.oneshot._build_provider", side_effect=_raise
        ), patch(
            "ppxai.server.routes.oneshot.get_default_provider", return_value="nope"
        ), patch(
            "ppxai.server.routes.oneshot.get_default_model", return_value="m"
        ):
            r = http_client.post("/v1/oneshot", json={"prompt": "Hello"})
        assert r.status_code == 400


class TestEnrichedOneshotFacade:
    """F3 (ADR 0009 step ① / ADR 0011): the search-loop path serves the
    request as a REAL kind=oneshot registry run — spawn_subagent's
    parent-await pattern with HTTP as the parent. Zero agent-code changes;
    these tests stub build_task_runner and use a real registry."""

    @pytest.fixture
    def reg(self, tmp_path, monkeypatch):
        from ppxai.engine.agent_runs import (
            AgentRunRegistry,
            FilesystemAgentRunStore,
        )
        import ppxai.server.state as state

        reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
        monkeypatch.setattr(state, "_agent_run_registry", reg)
        return reg

    @pytest.fixture
    def search_loop(self, monkeypatch):
        from ppxai.server.routes import oneshot as oneshot_mod

        monkeypatch.setattr(
            oneshot_mod, "_oneshot_effective_path", lambda p, m: "search-loop"
        )

    @staticmethod
    def _stub_runner(monkeypatch, fn):
        from ppxai.server.routes import agent_v1

        monkeypatch.setattr(agent_v1, "build_task_runner", lambda *a, **k: fn)

    def test_serves_via_kind_oneshot_run(
        self, http_client, reg, search_loop, monkeypatch
    ):
        async def runner(m):
            return "grounded answer"

        self._stub_runner(monkeypatch, runner)
        r = http_client.post(
            "/v1/oneshot",
            json={"prompt": "what happened today?", "provider": "p", "model": "m"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["content"] == "grounded answer"
        g = body.get("grounding")
        assert g and g["run_id"].startswith("run_")
        meta = reg.get_run(g["run_id"])
        assert meta.kind == "oneshot"
        assert meta.status == "completed"
        assert meta.tools == ["web_search"]  # perimeter: the ONLY grant
        assert meta.hold_result is False  # the response IS the collect
        assert meta.result == "grounded answer"

    def test_failed_run_maps_502_with_run_id(
        self, http_client, reg, search_loop, monkeypatch
    ):
        async def runner(m):
            raise RuntimeError("backend exploded")

        self._stub_runner(monkeypatch, runner)
        r = http_client.post(
            "/v1/oneshot", json={"prompt": "boom", "provider": "p", "model": "m"}
        )
        assert r.status_code == 502
        assert "run_" in r.json()["detail"]
        assert "failed" in r.json()["detail"]

    def test_timeout_cancels_run_and_returns_504(
        self, http_client, reg, search_loop, monkeypatch
    ):
        from ppxai.server.routes import oneshot as oneshot_mod

        monkeypatch.setattr(oneshot_mod, "ONESHOT_SEARCH_TIMEOUT_S", 0.05)

        async def runner(m):
            import asyncio

            await asyncio.sleep(5)
            return "too late"

        self._stub_runner(monkeypatch, runner)
        r = http_client.post(
            "/v1/oneshot", json={"prompt": "slow", "provider": "p", "model": "m"}
        )
        assert r.status_code == 504
        detail = r.json()["detail"]
        assert "run_" in detail and "cancelled" in detail
        # Cooperative cancel was REQUESTED (the stub never polls its control,
        # so the status parks at cancelling — a real runner lands cancelled).
        run_id = detail.split("run ")[1].split(" ")[0]
        assert reg.get_run(run_id).status == "cancelling"

    def test_facade_egress_authorizes_web_search(self):
        """REGRESSION (caught live in the F3 trial): NetworkPolicy allowlist
        rules take bare HOSTS, but _WEB_SEARCH_ALL_HOSTS entries are URLs —
        passing them verbatim silently matched nothing and every web_search
        call was denied (fail-closed). The facade's egress hosts must
        authorize web_search's ENTIRE backend superset (the AC-2 all-or-
        nothing rule), against the real policy code — no mocks."""
        from ppxai.engine.tools.network_policy import (
            Allow,
            NetworkPolicy,
            tool_targets,
        )
        from ppxai.server.routes.oneshot import _web_search_egress_hosts

        policy = NetworkPolicy(_web_search_egress_hosts())
        targets = tool_targets("web_search", {})
        assert targets, "web_search must declare its egress superset"
        for url in targets:
            decision = policy.check(url)
            assert isinstance(decision, Allow), f"{url} denied: {decision}"

    def test_grounding_absent_when_not_search_loop(
        self, http_client, stub_provider, monkeypatch
    ):
        # Byte-identical guarantee: the legacy paths must NOT grow a
        # "grounding" key — not even a null one.
        from ppxai.server.routes import oneshot as oneshot_mod

        monkeypatch.setattr(
            oneshot_mod, "_oneshot_effective_path", lambda p, m: "closed-book"
        )
        r = http_client.post(
            "/v1/oneshot", json={"prompt": "hi", "provider": "p", "model": "m"}
        )
        assert r.status_code == 200
        assert "grounding" not in r.json()
