"""
Tests for the ppxai HTTP server.

These tests verify the FastAPI HTTP server endpoints work correctly.
"""

import pytest
from unittest.mock import MagicMock


# Skip tests if server dependencies not installed
pytest.importorskip("fastapi")
pytest.importorskip("httpx")


from fastapi.testclient import TestClient
import ppxai.server.http as http_module


def create_mock_engine():
    """Create a mock EngineClient."""
    engine = MagicMock()
    engine.provider_name = "perplexity"
    engine.model = "sonar-pro"
    engine.tools_enabled = False
    engine.auto_inject_context = True

    # Mock list_providers
    mock_provider = MagicMock()
    mock_provider.id = "perplexity"
    mock_provider.name = "Perplexity AI"
    mock_provider.has_api_key = True
    mock_provider.default_model = "sonar-pro"
    mock_provider.capabilities = MagicMock(
        web_search=True,
        citations=True,
        streaming=True
    )
    engine.list_providers.return_value = [mock_provider]

    # Mock list_models
    mock_model = MagicMock()
    mock_model.id = "sonar-pro"
    mock_model.name = "Sonar Pro"
    mock_model.description = "Pro model with web search"
    engine.list_models.return_value = [mock_model]

    # Mock list_tools
    engine.list_tools.return_value = [
        {"name": "web_search", "description": "Search the web", "source": "engine"}
    ]

    # Mock session methods
    engine.list_sessions.return_value = []

    # Mock usage
    engine.get_usage.return_value = {
        "total_tokens": 1000,
        "prompt_tokens": 500,
        "completion_tokens": 500,
        "estimated_cost": 0.01
    }

    # Mock set methods
    engine.set_provider.return_value = True
    engine.set_model.return_value = True
    engine.set_tool_config.return_value = True
    engine.enable_tools.return_value = True
    engine.disable_tools.return_value = True

    return engine


@pytest.fixture
def mock_client():
    """Create a test client with a mock engine injected after startup."""
    mock_engine = create_mock_engine()

    # Create test client which will run startup event
    with TestClient(http_module.app, raise_server_exceptions=False) as test_client:
        # Now inject the mock engine after startup (replacing the real one)
        original = http_module.engine
        http_module.engine = mock_engine
        yield test_client, mock_engine
        # Restore original (may be real engine from startup)
        http_module.engine = original


@pytest.fixture
def no_engine_client():
    """Create a test client with no engine (set to None after startup)."""
    with TestClient(http_module.app, raise_server_exceptions=False) as test_client:
        original = http_module.engine
        http_module.engine = None
        yield test_client
        http_module.engine = original


class TestHttpServerHealth:
    """Test health and status endpoints."""

    def test_health_check_with_engine(self, mock_client):
        """Test /health endpoint with engine initialized."""
        client, _ = mock_client
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_check_without_engine(self, no_engine_client):
        """Test /health endpoint without engine."""
        response = no_engine_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["engine"] is False

    def test_status_with_engine(self, mock_client):
        """Test /status endpoint with engine."""
        client, _ = mock_client
        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "perplexity"
        assert data["model"] == "sonar-pro"

    def test_status_without_engine(self, no_engine_client):
        """Test /status returns 503 without engine."""
        response = no_engine_client.get("/status")
        assert response.status_code == 503


class TestHttpServerProviders:
    """Test provider management endpoints."""

    def test_get_providers(self, mock_client):
        """Test GET /providers endpoint."""
        client, _ = mock_client
        response = client.get("/providers")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert len(data["providers"]) == 1
        assert data["providers"][0]["id"] == "perplexity"

    def test_set_provider(self, mock_client):
        """Test POST /providers endpoint."""
        client, mock_engine = mock_client
        response = client.post(
            "/providers",
            json={"provider": "perplexity", "model": "sonar-pro"}
        )
        assert response.status_code == 200
        mock_engine.set_provider.assert_called_with("perplexity")

    def test_set_invalid_provider(self, mock_client):
        """Test POST /providers with invalid provider."""
        client, mock_engine = mock_client
        mock_engine.set_provider.return_value = False
        response = client.post(
            "/providers",
            json={"provider": "nonexistent"}
        )
        assert response.status_code == 400


class TestHttpServerModels:
    """Test model management endpoints."""

    def test_get_models(self, mock_client):
        """Test GET /models endpoint."""
        client, _ = mock_client
        response = client.get("/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert len(data["models"]) == 1
        assert data["models"][0]["id"] == "sonar-pro"

    def test_set_model(self, mock_client):
        """Test POST /models endpoint."""
        client, mock_engine = mock_client
        response = client.post("/models", json={"model": "sonar-pro"})
        assert response.status_code == 200
        mock_engine.set_model.assert_called_with("sonar-pro")

    def test_set_invalid_model(self, mock_client):
        """Test POST /models with invalid model."""
        client, mock_engine = mock_client
        mock_engine.set_model.return_value = False
        response = client.post("/models", json={"model": "nonexistent"})
        assert response.status_code == 400


class TestHttpServerTools:
    """Test tool management endpoints."""

    def test_get_tools(self, mock_client):
        """Test GET /tools endpoint."""
        client, _ = mock_client
        response = client.get("/tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "enabled" in data

    def test_enable_tools(self, mock_client):
        """Test POST /tools to enable tools."""
        client, mock_engine = mock_client
        response = client.post("/tools", json={"enabled": True})
        assert response.status_code == 200
        mock_engine.enable_tools.assert_called_once()

    def test_disable_tools(self, mock_client):
        """Test POST /tools to disable tools."""
        client, mock_engine = mock_client
        response = client.post("/tools", json={"enabled": False})
        assert response.status_code == 200
        mock_engine.disable_tools.assert_called_once()

    def test_tools_config(self, mock_client):
        """Test POST /tools/config endpoint."""
        client, mock_engine = mock_client
        response = client.post(
            "/tools/config",
            json={"setting": "max_iterations", "value": "20"}
        )
        assert response.status_code == 200
        mock_engine.set_tool_config.assert_called_with("max_iterations", "20")
        data = response.json()
        assert data["success"] is True

    def test_tools_config_unknown_setting(self, mock_client):
        """Test POST /tools/config with unknown setting."""
        client, mock_engine = mock_client
        mock_engine.set_tool_config.return_value = False
        response = client.post(
            "/tools/config",
            json={"setting": "unknown_setting", "value": "foo"}
        )
        assert response.status_code == 400


class TestHttpServerUsage:
    """Test usage statistics endpoint."""

    def test_get_usage(self, mock_client):
        """Test GET /usage endpoint."""
        client, _ = mock_client
        response = client.get("/usage")
        assert response.status_code == 200
        data = response.json()
        assert data["total_tokens"] == 1000
        assert data["prompt_tokens"] == 500
        assert data["completion_tokens"] == 500
        assert data["estimated_cost"] == 0.01

    def test_usage_without_engine(self, no_engine_client):
        """Test GET /usage returns 503 without engine."""
        response = no_engine_client.get("/usage")
        assert response.status_code == 503


class TestHttpServerSessions:
    """Test session management endpoints."""

    def test_get_sessions(self, mock_client):
        """Test GET /sessions endpoint."""
        client, _ = mock_client
        response = client.get("/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data

    def test_clear_session(self, mock_client):
        """Test POST /sessions/clear endpoint."""
        client, mock_engine = mock_client
        response = client.post("/sessions/clear")
        assert response.status_code == 200
        mock_engine.clear_history.assert_called_once()

    def test_sessions_without_engine(self, no_engine_client):
        """Test GET /sessions returns 503 without engine."""
        response = no_engine_client.get("/sessions")
        assert response.status_code == 503
