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
    engine.last_model_switch_reset = 0
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
        mock_engine.set_model.assert_called_with("sonar-pro", reset_context=True)

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
        mock_engine.session.clear.assert_called_once()

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


class TestContextReload:
    """Test /context/reload endpoint (v1.14.1)."""

    def test_context_reload_success(self, mock_client):
        """Test POST /context/reload reloads bootstrap context."""
        client, mock_engine = mock_client
        mock_engine.reload_bootstrap_context.return_value = True
        mock_engine.get_bootstrap_status.return_value = {
            "loaded": True,
            "source": "AGENTS.md",
            "sources": ["c:/project/AGENTS.md"],
            "char_count": 1500,
            "has_hints": True
        }

        response = client.post("/context/reload")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["loaded"] is True
        mock_engine.reload_bootstrap_context.assert_called_once()

    def test_context_reload_no_bootstrap_file(self, mock_client):
        """Test POST /context/reload when no bootstrap file exists."""
        client, mock_engine = mock_client
        mock_engine.reload_bootstrap_context.return_value = False
        mock_engine.get_bootstrap_status.return_value = {
            "loaded": False,
            "source": None,
            "sources": [],
            "char_count": 0,
            "has_hints": False
        }

        response = client.post("/context/reload")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["loaded"] is False

    def test_context_reload_without_engine(self, no_engine_client):
        """Test POST /context/reload returns 503 without engine."""
        response = no_engine_client.post("/context/reload")
        assert response.status_code == 503


class TestFileWrite:
    """Test /files/write endpoint (v1.14.1)."""

    def test_file_write_success(self, mock_client, tmp_path):
        """Test POST /files/write writes file successfully."""
        client, mock_engine = mock_client

        # Set working directory to temp path
        mock_engine.get_working_dir.return_value = str(tmp_path)

        test_file = tmp_path / "test.txt"
        response = client.post(
            "/files/write",
            json={"path": str(test_file), "content": "Hello World"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["created"] is True
        assert data["size"] == 11
        assert test_file.read_text() == "Hello World"

    def test_file_write_update_existing(self, mock_client, tmp_path):
        """Test POST /files/write updates existing file."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        test_file = tmp_path / "existing.txt"
        test_file.write_text("Original content")

        response = client.post(
            "/files/write",
            json={"path": str(test_file), "content": "Updated content"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["created"] is False  # File existed
        assert test_file.read_text() == "Updated content"

    def test_file_write_creates_parent_dirs(self, mock_client, tmp_path):
        """Test POST /files/write creates parent directories."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        nested_file = tmp_path / "subdir" / "nested" / "test.txt"
        response = client.post(
            "/files/write",
            json={"path": str(nested_file), "content": "Nested content"}
        )
        assert response.status_code == 200
        assert nested_file.exists()
        assert nested_file.read_text() == "Nested content"

    def test_file_write_relative_path(self, mock_client, tmp_path):
        """Test POST /files/write resolves relative paths."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        response = client.post(
            "/files/write",
            json={"path": "relative.txt", "content": "Relative path test"}
        )
        assert response.status_code == 200
        assert (tmp_path / "relative.txt").exists()


class TestFileWritePathValidation:
    """Test /files/write path validation security (v1.14.1)."""

    def test_file_write_outside_working_dir_denied(self, mock_client, tmp_path):
        """Test POST /files/write denies paths outside working dir."""
        import tempfile
        client, mock_engine = mock_client

        # Working dir is tmp_path
        mock_engine.get_working_dir.return_value = str(tmp_path)

        # Try to write to system temp (outside working dir and home)
        # Use a path that's definitely outside both
        outside_path = "/etc/passwd" if not tmp_path.drive else "C:\\Windows\\System32\\test.txt"

        response = client.post(
            "/files/write",
            json={"path": outside_path, "content": "Malicious content"}
        )
        # Should be 403 Forbidden
        assert response.status_code == 403
        assert "denied" in response.json()["detail"].lower()

    def test_file_write_path_traversal_blocked(self, mock_client, tmp_path):
        """Test POST /files/write blocks path traversal to outside directories.

        Note: On Windows, tmp_path is often under user's home directory, so path
        traversal to parent may be allowed by the home_dir check. On Linux, temp
        is /tmp which is outside home_dir, so path traversal is blocked.

        This test uses a path completely outside both working_dir and home_dir.
        """
        import os
        client, mock_engine = mock_client

        # Create a subdirectory as working dir
        subdir = tmp_path / "workdir"
        subdir.mkdir()
        mock_engine.get_working_dir.return_value = str(subdir)

        # Attempt to write to a path that's definitely outside working_dir tree AND home_dir
        if os.name == 'nt':
            # Use a UNC path or different drive letter that doesn't exist
            outside_path = "Z:\\definitely\\outside\\path.txt"
        else:
            # Use /var which is outside /home on Linux
            outside_path = "/var/tmp/ppxai_test_blocked.txt"

        response = client.post(
            "/files/write",
            json={"path": outside_path, "content": "Should be blocked"}
        )
        # Path outside allowed directories is blocked
        assert response.status_code == 403
        assert "denied" in response.json()["detail"].lower()

    def test_file_write_home_dir_allowed(self, mock_client, tmp_path):
        """Test POST /files/write allows writing to home directory."""
        import os
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        # Use a path in home directory (use .ppxai to avoid cluttering home)
        home_test_dir = os.path.expanduser("~/.ppxai/test_temp")
        os.makedirs(home_test_dir, exist_ok=True)
        home_test_file = os.path.join(home_test_dir, "test_write.txt")

        try:
            response = client.post(
                "/files/write",
                json={"path": home_test_file, "content": "Home dir test"}
            )
            assert response.status_code == 200
            assert os.path.exists(home_test_file)
        finally:
            # Cleanup
            if os.path.exists(home_test_file):
                os.remove(home_test_file)
            if os.path.exists(home_test_dir):
                os.rmdir(home_test_dir)

    def test_file_write_tilde_expansion(self, mock_client, tmp_path):
        """Test POST /files/write expands tilde in paths."""
        import os
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        # Use tilde path to home directory
        home_test_dir = "~/.ppxai/test_temp"
        expanded_dir = os.path.expanduser(home_test_dir)
        os.makedirs(expanded_dir, exist_ok=True)
        tilde_path = "~/.ppxai/test_temp/tilde_test.txt"
        expanded_path = os.path.expanduser(tilde_path)

        try:
            response = client.post(
                "/files/write",
                json={"path": tilde_path, "content": "Tilde expansion test"}
            )
            assert response.status_code == 200
            assert os.path.exists(expanded_path)
        finally:
            # Cleanup
            if os.path.exists(expanded_path):
                os.remove(expanded_path)
            if os.path.exists(expanded_dir):
                os.rmdir(expanded_dir)


class TestFileReadRelativePath:
    """Test /files/read returns relative path in 'filename' field (bugfix/1.16.2).

    The 'filename' field must be the path relative to the working directory, not
    just the basename.  Without this fix, the web editor loses the directory
    prefix and saves to the working directory root on save.
    """

    def test_file_in_subdir_returns_relative_filename(self, mock_client, tmp_path):
        """filename field must be 'subdir/file.py', not 'file.py'."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        subdir = tmp_path / "outlook_agent"
        subdir.mkdir()
        (subdir / "main.py").write_text("# hello", encoding="utf-8")

        response = client.post("/files/read", json={"path": "outlook_agent/main.py"})
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "outlook_agent/main.py", (
            f"Expected 'outlook_agent/main.py', got '{data['filename']}'"
        )

    def test_file_in_root_returns_basename(self, mock_client, tmp_path):
        """For a top-level file the relative path equals the basename."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        (tmp_path / "README.md").write_text("# readme", encoding="utf-8")

        response = client.post("/files/read", json={"path": "README.md"})
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "README.md"

    def test_deeply_nested_file_returns_full_relative_path(self, mock_client, tmp_path):
        """Deeply nested files return the full relative path."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (nested / "deep.txt").write_text("deep", encoding="utf-8")

        response = client.post("/files/read", json={"path": "a/b/c/deep.txt"})
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "a/b/c/deep.txt"


class TestServeImage:
    """Test GET /files/image/{path} endpoint (v1.16.2).

    Serves raw image binary with correct Content-Type for inline display
    in web app chat bubbles via marked.js ![alt](url) rendering.
    """

    def _create_png(self, path):
        """Create a minimal 1x1 PNG file."""
        # Minimal valid PNG: 1x1 pixel, 8-bit RGBA
        import struct
        import zlib

        def _chunk(chunk_type, data):
            c = chunk_type + data
            crc = struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
            return struct.pack('>I', len(data)) + c + crc

        signature = b'\x89PNG\r\n\x1a\n'
        ihdr = _chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
        raw_data = b'\x00\xff\x00\x00'  # filter byte + RGB
        idat = _chunk(b'IDAT', zlib.compress(raw_data))
        iend = _chunk(b'IEND', b'')
        png_bytes = signature + ihdr + idat + iend
        path.write_bytes(png_bytes)
        return png_bytes

    def test_serves_png_with_correct_content_type(self, mock_client, tmp_path):
        """PNG file served with image/png content type."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        png_bytes = self._create_png(tmp_path / "chart.png")

        response = client.get("/files/image/chart.png")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/png")
        assert response.content == png_bytes

    def test_serves_jpg(self, mock_client, tmp_path):
        """JPEG file served with image/jpeg content type."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        (tmp_path / "photo.jpg").write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100)

        response = client.get("/files/image/photo.jpg")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")

    def test_rejects_non_image_file(self, mock_client, tmp_path):
        """Non-image files return 400."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        (tmp_path / "data.json").write_text('{"key": "value"}', encoding="utf-8")

        response = client.get("/files/image/data.json")
        assert response.status_code == 400

    def test_404_for_missing_file(self, mock_client, tmp_path):
        """Missing file returns 404."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        response = client.get("/files/image/nonexistent.png")
        assert response.status_code == 404

    def test_serves_image_in_subdirectory(self, mock_client, tmp_path):
        """Images in subdirectories are accessible via path."""
        client, mock_engine = mock_client
        mock_engine.get_working_dir.return_value = str(tmp_path)

        subdir = tmp_path / "output" / "plots"
        subdir.mkdir(parents=True)
        self._create_png(subdir / "result.png")

        response = client.get("/files/image/output/plots/result.png")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/png")
