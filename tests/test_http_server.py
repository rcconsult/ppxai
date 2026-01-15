"""
Tests for the ppxai HTTP server.

These tests verify the FastAPI HTTP server endpoints work correctly.

v1.13.10: Updated to work with SessionManager instead of global default_engine.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


# Skip tests if server dependencies not installed
pytest.importorskip("fastapi")
pytest.importorskip("httpx")


from fastapi.testclient import TestClient
import ppxai.server.http as http_module
from ppxai.server.session_manager import SessionManager


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


def create_mock_session_manager(mock_engine=None):
    """Create a mock SessionManager with a mock engine."""
    manager = MagicMock(spec=SessionManager)
    manager.is_initialized = mock_engine is not None
    manager._default_engine = mock_engine
    manager.default_engine = mock_engine
    manager.session_count = 0
    manager.last_activity = 0.0
    manager.shutdown_requested = False

    # Configure async method get_or_create_session to return (session_id, engine, lock)
    mock_lock = asyncio.Lock()
    if mock_engine:
        manager.get_or_create_session = AsyncMock(
            return_value=("default", mock_engine, mock_lock)
        )
    else:
        # When no engine, raise RuntimeError as SessionManager would
        manager.get_or_create_session = AsyncMock(
            side_effect=RuntimeError("SessionManager not initialized")
        )

    # Configure other async methods
    manager.list_sessions = AsyncMock(return_value=[])
    manager.cleanup_expired_sessions = AsyncMock(return_value=0)
    manager.shutdown = AsyncMock()

    return manager


@pytest.fixture
def mock_client():
    """Create a test client with a mock engine injected via SessionManager."""
    mock_engine = create_mock_engine()
    mock_manager = create_mock_session_manager(mock_engine)

    # Create test client which will run startup event
    with TestClient(http_module.app, raise_server_exceptions=False) as test_client:
        # Inject the mock session manager after startup
        original = http_module.session_manager
        http_module.session_manager = mock_manager
        yield test_client, mock_engine
        # Restore original
        http_module.session_manager = original


@pytest.fixture
def no_engine_client():
    """Create a test client with no engine (SessionManager not initialized)."""
    mock_manager = create_mock_session_manager(None)

    with TestClient(http_module.app, raise_server_exceptions=False) as test_client:
        original = http_module.session_manager
        http_module.session_manager = mock_manager
        yield test_client
        http_module.session_manager = original


class TestHttpServerHealth:
    """Test health and status endpoints."""

    def test_health_check_with_engine(self, mock_client):
        """Test /health endpoint with engine initialized."""
        client, _ = mock_client
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
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


class TestHttpServerToolsHelp:
    """Test /tools/help endpoint (v1.14.0)."""

    def test_get_tool_help(self, mock_client):
        """Test GET /tools/help/{tool_name} returns tool definition."""
        client, mock_engine = mock_client
        mock_engine.tools_enabled = True

        # Create mock tool with get_definition method
        mock_tool = MagicMock()
        mock_tool.get_definition.return_value = {
            "function": {
                "name": "calculator",
                "description": "Perform mathematical calculations",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "Mathematical expression to evaluate"
                        }
                    },
                    "required": ["expression"]
                }
            }
        }

        mock_engine.tool_manager = MagicMock()
        mock_engine.tool_manager.get_tool.return_value = mock_tool
        mock_engine.tool_manager.list_tools.return_value = [
            {"name": "calculator", "description": "Math tool"}
        ]

        response = client.get("/tools/help/calculator")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "calculator"
        assert "description" in data
        assert "parameters" in data

    def test_get_tool_help_not_found(self, mock_client):
        """Test GET /tools/help/{tool_name} returns 404 for unknown tool."""
        client, mock_engine = mock_client
        mock_engine.tools_enabled = True
        mock_engine.tool_manager = MagicMock()
        mock_engine.tool_manager.get_tool.return_value = None
        mock_engine.tool_manager.list_tools.return_value = [
            {"name": "calculator", "description": "Math tool"}
        ]

        response = client.get("/tools/help/unknown_tool")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_tool_help_tools_disabled(self, mock_client):
        """Test GET /tools/help returns 400 when tools disabled."""
        client, mock_engine = mock_client
        mock_engine.tools_enabled = False
        mock_engine.tool_manager = None

        response = client.get("/tools/help/calculator")
        assert response.status_code == 400
        assert "not enabled" in response.json()["detail"].lower()


class TestHttpServerCheckpointInfo:
    """Test /checkpoint/info endpoint (v1.14.0)."""

    def test_get_checkpoint_info(self, mock_client):
        """Test GET /checkpoint/info/{id} returns checkpoint details."""
        client, mock_engine = mock_client

        mock_engine.list_checkpoints.return_value = [
            {
                "id": "abc123def456",
                "description": "Agent task: Fix bug",
                "timestamp": "2025-01-05 12:00:00"
            },
            {
                "id": "xyz789",
                "description": "Agent task: Add feature",
                "timestamp": "2025-01-05 11:00:00"
            }
        ]
        mock_engine.get_checkpoint_status.return_value = {
            "backend": "git",
            "enabled": True,
            "last_checkpoint": "abc123def456",
            "is_valid": True
        }

        response = client.get("/checkpoint/info/abc123")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "abc123def456"
        assert data["description"] == "Agent task: Fix bug"
        assert data["is_current"] == True
        assert data["is_valid"] == True

    def test_get_checkpoint_info_historical(self, mock_client):
        """Test GET /checkpoint/info returns historical status for old checkpoint."""
        client, mock_engine = mock_client

        mock_engine.list_checkpoints.return_value = [
            {
                "id": "abc123",
                "description": "Current checkpoint",
                "timestamp": "2025-01-05 12:00:00"
            },
            {
                "id": "xyz789",
                "description": "Old checkpoint",
                "timestamp": "2025-01-05 11:00:00"
            }
        ]
        mock_engine.get_checkpoint_status.return_value = {
            "backend": "git",
            "enabled": True,
            "last_checkpoint": "abc123",
            "is_valid": True
        }

        response = client.get("/checkpoint/info/xyz789")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "xyz789"
        assert data["is_current"] == False
        assert data["status"] == "historical"

    def test_get_checkpoint_info_not_found(self, mock_client):
        """Test GET /checkpoint/info returns 404 for unknown checkpoint."""
        client, mock_engine = mock_client
        mock_engine.list_checkpoints.return_value = []

        response = client.get("/checkpoint/info/unknown")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestSSETermination:
    """Test SSE stream termination signals (v1.13.9)."""

    @pytest.mark.asyncio
    async def test_sse_generator_sends_done_signal(self):
        """Test that sse_event_generator sends [DONE] termination signal."""
        from ppxai.server.http import sse_event_generator
        from ppxai.engine.types import Event, EventType
        from unittest.mock import AsyncMock

        # Create mock engine that yields a simple response
        mock_engine = AsyncMock()
        mock_engine.session = MagicMock()
        mock_engine.session.save_usage_to_persistent_storage = MagicMock()
        mock_engine._consent_event_queue = []

        # Mock chat to yield start, chunk, end events
        async def mock_chat(prompt):
            yield Event(EventType.STREAM_START, None)
            yield Event(EventType.STREAM_CHUNK, "Hello")
            yield Event(EventType.STREAM_END, "Hello")

        mock_engine.chat = mock_chat

        # Collect all SSE events
        events = []
        async for event in sse_event_generator("test", mock_engine, "test-session"):
            events.append(event)

        # Verify [DONE] is the last event
        assert len(events) >= 1
        assert events[-1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_sse_coding_task_generator_sends_done_signal(self):
        """Test that sse_coding_task_generator sends [DONE] termination signal."""
        from ppxai.server.http import sse_coding_task_generator
        from ppxai.engine.types import Event, EventType
        from unittest.mock import AsyncMock

        # Create mock engine
        mock_engine = AsyncMock()
        mock_engine.session = MagicMock()
        mock_engine.session.save_usage_to_persistent_storage = MagicMock()

        # Mock coding_task to yield events
        async def mock_coding_task(prompt, task_type):
            yield Event(EventType.STREAM_START, None)
            yield Event(EventType.STREAM_CHUNK, "Code here")
            yield Event(EventType.STREAM_END, "Code here")

        mock_engine.coding_task = mock_coding_task

        # Collect all SSE events
        events = []
        async for event in sse_coding_task_generator("test", "generate", mock_engine):
            events.append(event)

        # Verify [DONE] is the last event
        assert len(events) >= 1
        assert events[-1] == "data: [DONE]\n\n"

    def test_done_signal_is_valid_sse_format(self):
        """Test that [DONE] signal follows SSE format specification."""
        done_signal = "data: [DONE]\n\n"

        # Verify format: starts with "data: ", ends with double newline
        assert done_signal.startswith("data: ")
        assert done_signal.endswith("\n\n")

        # Verify content is exactly [DONE] (OpenAI convention)
        content = done_signal[6:-2]  # Strip "data: " prefix and "\n\n" suffix
        assert content == "[DONE]"
