"""
Tests for ppxai server routes using FastAPI TestClient.

Creates a minimal FastAPI app with only the routers under test,
overriding the get_session dependency to inject a mock Session.
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ppxai.server.state import Session, get_session
from ppxai.server.routes.config import router as config_router
from ppxai.server.routes.providers import router as providers_router
from ppxai.server.routes.sessions import router as sessions_router
from ppxai.server.routes.state import router as state_router  # v1.18.0


def create_test_app():
    """Create a minimal FastAPI app with only the routers under test."""
    app = FastAPI()
    app.include_router(config_router)
    app.include_router(providers_router)
    app.include_router(sessions_router)
    app.include_router(state_router)
    return app


def make_mock_session():
    """Create a mock Session with a mock EngineClient."""
    from ppxai.engine.app_state import AppState

    engine = MagicMock()
    engine.provider_name = "openai"
    engine.model = "gpt-4"
    engine.tools_enabled = True
    # Real AppState so routes can use state.get()/snapshot()
    engine.state = AppState(initial={
        "provider": "openai",
        "model": "gpt-4",
        "tools_enabled": True,
    })
    return Session(id="test", engine=engine, lock=asyncio.Lock())


@pytest.fixture
def mock_session():
    return make_mock_session()


@pytest.fixture
def client(mock_session):
    app = create_test_app()
    app.dependency_overrides[get_session] = lambda: mock_session
    return TestClient(app)


# ---------------------------------------------------------------------------
# Config routes
# ---------------------------------------------------------------------------

class TestConfigRoutes:

    def test_reload_config_success(self, client):
        """POST /config/reload returns success when reload_config() succeeds."""
        with patch("ppxai.server.routes.config.reload_config") as mock_reload, \
             patch("ppxai.server.routes.config.find_config_file", return_value=Path("/home/user/.ppxai/ppxai-config.json")):
            mock_reload.return_value = None

            resp = client.post("/config/reload")

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["message"] == "Configuration reloaded successfully"
            # Normalise separators so Windows (\) and POSIX (/) both pass.
            assert data["config_path"].replace("\\", "/") == "/home/user/.ppxai/ppxai-config.json"
            mock_reload.assert_called_once()

    def test_reload_config_failure(self, client):
        """POST /config/reload returns 500 when reload_config() raises."""
        with patch("ppxai.server.routes.config.reload_config", side_effect=RuntimeError("parse error")):
            resp = client.post("/config/reload")

            assert resp.status_code == 500
            assert "parse error" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Provider routes
# ---------------------------------------------------------------------------

def _make_provider(id_, name, has_api_key=True, default_model="m1",
                   web_search=False, citations=False, streaming=True):
    """Build a mock provider object with nested capabilities."""
    p = MagicMock()
    p.id = id_
    p.name = name
    p.has_api_key = has_api_key
    p.default_model = default_model
    p.capabilities.web_search = web_search
    p.capabilities.citations = citations
    p.capabilities.streaming = streaming
    return p


def _make_model(id_, name, description=""):
    m = MagicMock()
    m.id = id_
    m.name = name
    m.description = description
    return m


class TestProviderRoutes:

    def test_get_providers(self, client, mock_session):
        """GET /providers returns provider list with capabilities."""
        mock_session.engine.list_providers.return_value = [
            _make_provider("openai", "OpenAI", web_search=False, citations=False),
            _make_provider("perplexity", "Perplexity", web_search=True, citations=True),
        ]

        resp = client.get("/providers")

        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "openai"
        assert len(data["providers"]) == 2

        oai = data["providers"][0]
        assert oai["id"] == "openai"
        assert oai["name"] == "OpenAI"
        assert oai["has_api_key"] is True
        assert oai["capabilities"]["web_search"] is False

        pplx = data["providers"][1]
        assert pplx["id"] == "perplexity"
        assert pplx["capabilities"]["web_search"] is True
        assert pplx["capabilities"]["citations"] is True

    def test_get_models(self, client, mock_session):
        """GET /models returns model list with current model and provider."""
        mock_session.engine.list_models.return_value = [
            _make_model("gpt-4", "GPT-4", "Most capable model"),
            _make_model("gpt-4o-mini", "GPT-4o Mini", "Fast and cheap"),
        ]

        resp = client.get("/models")

        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "gpt-4"
        assert data["provider"] == "openai"
        assert len(data["models"]) == 2
        assert data["models"][0]["id"] == "gpt-4"
        assert data["models"][0]["description"] == "Most capable model"
        assert data["models"][1]["id"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Session routes
# ---------------------------------------------------------------------------

class TestSessionRoutes:

    def test_export_answer_success(self, client, mock_session):
        """POST /export returns filepath on success."""
        mock_session.engine.export_answer.return_value = Path("/tmp/export.md")

        resp = client.post("/export", json={})

        assert resp.status_code == 200
        # Normalise separators so Windows (\) and POSIX (/) both pass.
        assert resp.json()["filepath"].replace("\\", "/") == "/tmp/export.md"
        mock_session.engine.export_answer.assert_called_once_with(None)

    def test_export_answer_no_message(self, client, mock_session):
        """POST /export returns 400 when no messages to export."""
        mock_session.engine.export_answer.side_effect = ValueError("No messages to export")

        resp = client.post("/export", json={})

        assert resp.status_code == 400
        assert "No messages to export" in resp.json()["detail"]

    def test_export_answer_with_filename(self, client, mock_session):
        """POST /export passes filename through to engine."""
        mock_session.engine.export_answer.return_value = Path("/tmp/my-notes.md")

        resp = client.post("/export", json={"filename": "my-notes"})

        assert resp.status_code == 200
        # Normalise separators so Windows (\) and POSIX (/) both pass.
        assert resp.json()["filepath"].replace("\\", "/") == "/tmp/my-notes.md"
        mock_session.engine.export_answer.assert_called_once_with("my-notes")


# ---------------------------------------------------------------------------
# State route — v1.18.0 Phase 2 (SSE reconnect -> AppState refresh)
# ---------------------------------------------------------------------------


class TestStateRoute:
    """GET /state returns a snapshot of all SSE-synced AppState fields
    so web / VSCode clients can recover after an SSE disconnect without
    losing the state_sync events that fired during the gap.
    """

    def test_returns_all_sse_sync_fields(self, client):
        """Response contains every field in SSE_SYNC_FIELDS."""
        from ppxai.engine.client import SSE_SYNC_FIELDS

        resp = client.get("/state")
        assert resp.status_code == 200
        body = resp.json()
        # Shape = the whitelist. No extra fields, no missing fields.
        assert set(body.keys()) == set(SSE_SYNC_FIELDS)

    def test_returns_current_values(self, client, mock_session):
        """Fields present in AppState return their current values."""
        resp = client.get("/state")
        body = resp.json()
        assert body["provider"] == "openai"
        assert body["model"] == "gpt-4"
        assert body["tools_enabled"] is True

    def test_returns_schema_defaults_for_unset_fields(self, client, mock_session):
        """Fields not overridden on AppState return their schema default.

        AppState initialises every declared field to its schema default
        at construction time (see app_state._build_fields), so a
        "never set" field still has a value. For `agent_beat` that's
        an empty dict; for `context_attachments` it's an empty list.
        The client's updateFromPython() reads these as "no active beat"
        / "no attachments" — no special None handling needed.
        """
        resp = client.get("/state")
        body = resp.json()
        # These were never set on the mock, so they're at schema default.
        assert body["agent_beat"] == {}
        assert body["context_attachments"] == []

    def test_does_not_include_usage_fields(self, client):
        """High-frequency fields (usage tokens, is_streaming) stay out
        of the snapshot — clients get those from STREAM_END metadata.
        """
        resp = client.get("/state")
        body = resp.json()
        # Sanity-check the exclusions so future additions to
        # SSE_SYNC_FIELDS don't accidentally leak frequently-mutating
        # state into the reconnect snapshot.
        for excluded in ("total_tokens", "prompt_tokens",
                         "completion_tokens", "total_cost",
                         "is_streaming", "cancel_requested"):
            assert excluded not in body
