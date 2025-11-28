"""Unit tests for ppxai.client module."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile
from pathlib import Path

from ppxai.client import PerplexityClient, AIClient


class TestPerplexityClient:
    """Tests for PerplexityClient class."""

    @pytest.fixture
    def client(self):
        """Create a client instance for testing."""
        with patch('ppxai.client.OpenAI'):
            return PerplexityClient("test-api-key")

    def test_init_creates_session_name(self, client):
        """Test that initialization creates a session name."""
        assert client.session_name is not None
        assert client.session_name.startswith("session_")

    def test_init_with_custom_session_name(self):
        """Test initialization with custom session name."""
        with patch('ppxai.client.OpenAI'):
            client = PerplexityClient("test-api-key", session_name="my-session")
            assert client.session_name == "my-session"

    def test_init_creates_empty_history(self, client):
        """Test that initialization creates empty conversation history."""
        assert client.conversation_history == []

    def test_init_creates_usage_tracking(self, client):
        """Test that initialization creates usage tracking."""
        assert client.current_session_usage["total_tokens"] == 0
        assert client.current_session_usage["prompt_tokens"] == 0
        assert client.current_session_usage["completion_tokens"] == 0
        assert client.current_session_usage["estimated_cost"] == 0.0

    def test_auto_route_enabled_by_default(self, client):
        """Test that auto_route is enabled by default."""
        assert client.auto_route is True

    def test_clear_history(self, client):
        """Test clearing conversation history."""
        client.conversation_history = [{"role": "user", "content": "test"}]
        client.clear_history()
        assert client.conversation_history == []

    def test_get_usage_summary_returns_copy(self, client):
        """Test that get_usage_summary returns a copy."""
        usage1 = client.get_usage_summary()
        usage1["total_tokens"] = 999
        usage2 = client.get_usage_summary()
        assert usage2["total_tokens"] == 0

    def test_session_metadata_initialized(self, client):
        """Test that session metadata is initialized."""
        assert "created_at" in client.session_metadata
        assert "model" in client.session_metadata
        assert "message_count" in client.session_metadata


class TestPerplexityClientSessions:
    """Tests for session management."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Create a temporary sessions directory."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        return sessions_dir

    def test_list_sessions_empty(self, temp_sessions_dir, monkeypatch):
        """Test listing sessions when empty."""
        monkeypatch.setattr('ppxai.client.SESSIONS_DIR', temp_sessions_dir)
        sessions = PerplexityClient.list_sessions()
        assert sessions == []

    def test_list_sessions_with_sessions(self, temp_sessions_dir, monkeypatch):
        """Test listing sessions with saved sessions."""
        monkeypatch.setattr('ppxai.client.SESSIONS_DIR', temp_sessions_dir)

        # Create a test session file
        session_data = {
            "session_name": "test-session",
            "metadata": {"created_at": "2024-01-01T00:00:00"},
            "conversation_history": [{"role": "user", "content": "hello"}],
            "saved_at": "2024-01-01T01:00:00"
        }
        session_file = temp_sessions_dir / "test-session.json"
        session_file.write_text(json.dumps(session_data))

        sessions = PerplexityClient.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["name"] == "test-session"
        assert sessions[0]["message_count"] == 1


class TestPerplexityClientUsageTracking:
    """Tests for usage tracking."""

    @pytest.fixture
    def client(self):
        """Create a client instance for testing."""
        with patch('ppxai.client.OpenAI'):
            return PerplexityClient("test-api-key")

    def test_track_usage_updates_session_usage(self, client):
        """Test that _track_usage updates session usage."""
        mock_usage = Mock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50
        mock_usage.total_tokens = 150

        with patch.object(client, '_update_global_usage'):
            client._track_usage(mock_usage, "sonar")

        assert client.current_session_usage["prompt_tokens"] == 100
        assert client.current_session_usage["completion_tokens"] == 50
        assert client.current_session_usage["total_tokens"] == 150

    def test_track_usage_calculates_cost(self, client):
        """Test that _track_usage calculates estimated cost."""
        mock_usage = Mock()
        mock_usage.prompt_tokens = 1_000_000  # 1M tokens
        mock_usage.completion_tokens = 1_000_000
        mock_usage.total_tokens = 2_000_000

        with patch.object(client, '_update_global_usage'):
            client._track_usage(mock_usage, "sonar")

        # Sonar pricing: $0.20 input + $0.20 output = $0.40 per million
        expected_cost = 0.20 + 0.20  # $0.40
        assert abs(client.current_session_usage["estimated_cost"] - expected_cost) < 0.01


class TestAIClientMultiProvider:
    """Tests for AIClient multi-provider support."""

    @pytest.fixture
    def perplexity_client(self):
        """Create a Perplexity client instance for testing."""
        with patch('ppxai.client.OpenAI'):
            return AIClient("test-api-key", provider="perplexity")

    @pytest.fixture
    def custom_client(self):
        """Create a custom provider client instance for testing."""
        with patch('ppxai.client.OpenAI'):
            return AIClient(
                "custom-api-key",
                base_url="https://custom.example.com/v1",
                provider="custom"
            )

    def test_aiclient_is_perplexityclient(self):
        """Test that AIClient and PerplexityClient are the same."""
        assert AIClient is PerplexityClient

    def test_client_stores_provider(self, perplexity_client):
        """Test that client stores provider name."""
        assert perplexity_client.provider == "perplexity"

    def test_custom_client_stores_provider(self, custom_client):
        """Test that custom client stores provider name."""
        assert custom_client.provider == "custom"

    def test_client_stores_base_url(self, custom_client):
        """Test that client stores custom base URL."""
        assert custom_client.base_url == "https://custom.example.com/v1"

    def test_perplexity_client_default_base_url(self, perplexity_client):
        """Test that perplexity client uses default base URL."""
        assert perplexity_client.base_url == "https://api.perplexity.ai"

    def test_session_metadata_includes_provider(self, custom_client):
        """Test that session metadata includes provider."""
        assert "provider" in custom_client.session_metadata
        assert custom_client.session_metadata["provider"] == "custom"

    def test_openai_client_initialized_with_custom_url(self):
        """Test that OpenAI client is initialized with custom base URL."""
        # Temporarily override SSL_VERIFY to ensure consistent test behavior
        with patch.dict('os.environ', {"SSL_VERIFY": "true"}):
            with patch('ppxai.client.OpenAI') as mock_openai:
                AIClient(
                    "test-key",
                    base_url="https://custom.example.com/v1",
                    provider="custom"
                )
                mock_openai.assert_called_once_with(
                    api_key="test-key",
                    base_url="https://custom.example.com/v1"
                )


class TestAIClientLoadSessionWithProvider:
    """Tests for loading sessions with provider support."""

    @pytest.fixture
    def temp_sessions_dir(self, tmp_path):
        """Create a temporary sessions directory."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        return sessions_dir

    def test_load_session_with_provider(self, temp_sessions_dir, monkeypatch):
        """Test loading a session with custom provider."""
        monkeypatch.setattr('ppxai.client.SESSIONS_DIR', temp_sessions_dir)

        # Create a test session file
        session_data = {
            "session_name": "custom-session",
            "metadata": {
                "created_at": "2024-01-01T00:00:00",
                "provider": "custom"
            },
            "conversation_history": [{"role": "user", "content": "hello"}],
            "usage": {
                "total_tokens": 100,
                "prompt_tokens": 50,
                "completion_tokens": 50,
                "estimated_cost": 0.0
            },
            "saved_at": "2024-01-01T01:00:00"
        }
        session_file = temp_sessions_dir / "custom-session.json"
        session_file.write_text(json.dumps(session_data))

        with patch('ppxai.client.OpenAI'):
            loaded_client = AIClient.load_session(
                "custom-session",
                "custom-api-key",
                base_url="https://custom.example.com/v1",
                provider="custom"
            )

        assert loaded_client is not None
        assert loaded_client.provider == "custom"
        assert loaded_client.base_url == "https://custom.example.com/v1"
        assert len(loaded_client.conversation_history) == 1
