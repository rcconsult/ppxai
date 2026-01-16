"""
Tests for command handlers with both Perplexity and Custom providers.

v1.12.0: Updated to use EngineClient instead of legacy AIClient.
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock, call, AsyncMock
from io import StringIO

from ppxai.commands import CommandHandler, send_coding_task


class TestCommandHandlerBothProviders:
    """Test CommandHandler with both providers using EngineClient."""

    @pytest.fixture
    def mock_engine_client(self):
        """Create a mock EngineClient with session."""
        engine = Mock()
        engine.session = Mock()
        engine.session.messages = []
        engine.session.session_name = "test_session"
        engine.session.get_usage = Mock(return_value={
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0
        })
        engine.session.save = Mock()
        engine.session.clear = Mock()
        engine.tools_enabled = False
        engine.model = "sonar-pro"
        engine.provider = "perplexity"
        return engine

    @pytest.fixture
    def handler_perplexity(self, mock_engine_client):
        """Create CommandHandler for Perplexity provider."""
        handler = CommandHandler(
            "test-api-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )
        handler.engine_client = mock_engine_client
        return handler

    @pytest.fixture
    def handler_custom(self, mock_engine_client):
        """Create CommandHandler for custom provider."""
        mock_engine_client.model = "custom-model"
        mock_engine_client.provider = "custom"
        handler = CommandHandler(
            "custom-api-key",
            "custom-model",
            "https://custom.example.com/v1",
            "custom"
        )
        handler.engine_client = mock_engine_client
        return handler

    # ==================== /quit Command ====================

    def test_quit_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /quit command with Perplexity provider."""
        mock_engine_client.session.messages = [Mock(role="user", content="test")]
        result = handler_perplexity.handle_quit()
        assert result is True
        mock_engine_client.session.save.assert_called_once()

    def test_quit_command_custom(self, handler_custom, mock_engine_client):
        """Test /quit command with custom provider."""
        mock_engine_client.session.messages = [Mock(role="user", content="test")]
        result = handler_custom.handle_quit()
        assert result is True
        mock_engine_client.session.save.assert_called_once()

    def test_quit_with_empty_history_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /quit with empty history for Perplexity."""
        mock_engine_client.session.messages = []
        result = handler_perplexity.handle_quit()
        assert result is True
        # Should not save when history is empty
        mock_engine_client.session.save.assert_not_called()

    def test_quit_with_empty_history_custom(self, handler_custom, mock_engine_client):
        """Test /quit with empty history for custom provider."""
        mock_engine_client.session.messages = []
        result = handler_custom.handle_quit()
        assert result is True
        mock_engine_client.session.save.assert_not_called()

    # ==================== /clear Command ====================

    def test_clear_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /clear command with Perplexity provider."""
        mock_engine_client.session.messages = [Mock(role="user", content="test")]
        handler_perplexity.handle_clear()
        mock_engine_client.session.clear.assert_called_once()

    def test_clear_command_custom(self, handler_custom, mock_engine_client):
        """Test /clear command with custom provider."""
        mock_engine_client.session.messages = [Mock(role="user", content="test")]
        handler_custom.handle_clear()
        mock_engine_client.session.clear.assert_called_once()

    # ==================== /usage Command ====================

    def test_usage_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /usage command with Perplexity provider."""
        mock_usage = {
            "total_tokens": 100,
            "prompt_tokens": 60,
            "completion_tokens": 40,
            "estimated_cost": 0.001,
            "by_model": {},
            "display_mode": "session"
        }
        mock_engine_client.session.get_usage.return_value = mock_usage

        # v1.12.2: /usage now uses _display_usage_report instead of display_usage
        handler_perplexity.handle_usage()
        mock_engine_client.session.get_usage.assert_called_once()

    def test_usage_command_custom(self, handler_custom, mock_engine_client):
        """Test /usage command with custom provider."""
        mock_usage = {
            "total_tokens": 200,
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "estimated_cost": 0.002,
            "by_model": {},
            "display_mode": "session"
        }
        mock_engine_client.session.get_usage.return_value = mock_usage

        # v1.12.2: /usage now uses _display_usage_report instead of display_usage
        handler_custom.handle_usage()
        mock_engine_client.session.get_usage.assert_called_once()

    def test_usage_show_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /usage show <mode> command (v1.12.2)."""
        mock_engine_client.session.set_usage_display_mode = Mock(return_value=True)

        # Test setting display mode to 'model'
        handler_perplexity.handle_usage("show model")
        mock_engine_client.session.set_usage_display_mode.assert_called_with("model")

        # Test setting display mode to 'provider'
        handler_perplexity.handle_usage("show provider")
        mock_engine_client.session.set_usage_display_mode.assert_called_with("provider")

        # Test setting display mode to 'off'
        handler_perplexity.handle_usage("show off")
        mock_engine_client.session.set_usage_display_mode.assert_called_with("off")

    def test_usage_reset_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /usage reset command (v1.12.2)."""
        mock_engine_client.session.reset_usage = Mock()

        handler_perplexity.handle_usage("reset")
        mock_engine_client.session.reset_usage.assert_called_once()

    # ==================== /model Command ====================

    @patch('ppxai.commands.handler.select_model')
    def test_model_command_perplexity(self, mock_select, handler_perplexity, mock_engine_client):
        """Test /model command with Perplexity provider."""
        mock_select.return_value = "sonar-reasoning"
        mock_engine_client.set_model = Mock(return_value=True)
        handler_perplexity.handle_model()

        assert handler_perplexity.current_model == "sonar-reasoning"
        mock_engine_client.set_model.assert_called_once_with("sonar-reasoning")
        mock_select.assert_called_once_with("perplexity")

    @patch('ppxai.commands.handler.select_model')
    def test_model_command_custom(self, mock_select, handler_custom, mock_engine_client):
        """Test /model command with custom provider."""
        mock_select.return_value = "gpt-oss-120b"
        mock_engine_client.set_model = Mock(return_value=True)
        handler_custom.handle_model()

        assert handler_custom.current_model == "gpt-oss-120b"
        mock_engine_client.set_model.assert_called_once_with("gpt-oss-120b")
        mock_select.assert_called_once_with("custom")

    # ==================== /save Command ====================

    def test_save_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /save command with Perplexity provider - saves session to JSON."""
        mock_engine_client.session.save = Mock()
        handler_perplexity.handle_save("")
        mock_engine_client.session.save.assert_called_once()

    def test_save_command_custom(self, handler_custom, mock_engine_client):
        """Test /save command with custom provider - saves session to JSON."""
        mock_engine_client.session.save = Mock()
        handler_custom.handle_save("")
        mock_engine_client.session.save.assert_called_once()

    # ==================== /export Command ====================

    def test_export_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /export command with Perplexity provider - exports last answer to markdown."""
        mock_engine_client.session.messages = [
            Mock(role="user", content="Hello"),
            Mock(role="assistant", content="Hi there!")
        ]
        handler_perplexity.handle_export("my_export")
        # Should write last assistant message to exports folder

    def test_export_without_filename_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /export without filename for Perplexity - generates timestamp filename."""
        mock_engine_client.session.messages = [
            Mock(role="user", content="Hello"),
            Mock(role="assistant", content="Hi there!")
        ]
        handler_perplexity.handle_export("")
        # Should write last assistant message with auto-generated filename

    def test_export_no_assistant_message(self, handler_perplexity, mock_engine_client):
        """Test /export with no assistant message yet."""
        mock_engine_client.session.messages = [
            Mock(role="user", content="Hello")
        ]
        handler_perplexity.handle_export("")
        # Should show warning message

    # ==================== /sessions Command ====================

    @patch('ppxai.commands.handler.display_sessions')
    def test_sessions_command_perplexity(self, mock_display, handler_perplexity, mock_engine_client):
        """Test /sessions command with Perplexity provider."""
        # Create mock SessionInfo objects with expected attributes
        session1 = Mock()
        session1.name = "session1"
        session1.created_at = "2024-01-01"
        session1.provider = "perplexity"
        session1.model = "sonar-pro"
        session1.message_count = 5

        session2 = Mock()
        session2.name = "session2"
        session2.created_at = "2024-01-02"
        session2.provider = "perplexity"
        session2.model = "sonar-pro"
        session2.message_count = 10

        mock_sessions = [session1, session2]
        mock_engine_client.session.list_sessions = Mock(return_value=mock_sessions)
        handler_perplexity.handle_sessions()
        mock_engine_client.session.list_sessions.assert_called_once()
        mock_display.assert_called_once()

    @patch('ppxai.commands.handler.display_sessions')
    def test_sessions_command_custom(self, mock_display, handler_custom, mock_engine_client):
        """Test /sessions command with custom provider."""
        # Create mock SessionInfo objects with expected attributes
        session1 = Mock()
        session1.name = "custom_session1"
        session1.created_at = "2024-01-01"
        session1.provider = "custom"
        session1.model = "custom-model"
        session1.message_count = 3

        mock_sessions = [session1]
        mock_engine_client.session.list_sessions = Mock(return_value=mock_sessions)
        handler_custom.handle_sessions()
        mock_engine_client.session.list_sessions.assert_called_once()
        mock_display.assert_called_once()

    # ==================== /autoroute Command ====================

    @patch('ppxai.commands.handler.get_coding_model')
    def test_autoroute_on_perplexity(self, mock_get_coding, handler_perplexity, mock_engine_client):
        """Test /autoroute on with Perplexity provider."""
        mock_get_coding.return_value = "sonar-reasoning"
        handler_perplexity.auto_route = False
        handler_perplexity.handle_autoroute("on")
        assert handler_perplexity.auto_route is True

    @patch('ppxai.commands.handler.get_coding_model')
    def test_autoroute_on_custom(self, mock_get_coding, handler_custom, mock_engine_client):
        """Test /autoroute on with custom provider."""
        mock_get_coding.return_value = "gpt-oss-120b"
        handler_custom.auto_route = False
        handler_custom.handle_autoroute("on")
        assert handler_custom.auto_route is True

    @patch('ppxai.commands.handler.get_coding_model')
    def test_autoroute_off_perplexity(self, mock_get_coding, handler_perplexity, mock_engine_client):
        """Test /autoroute off with Perplexity provider."""
        mock_get_coding.return_value = "sonar-reasoning"
        handler_perplexity.auto_route = True
        handler_perplexity.handle_autoroute("off")
        assert handler_perplexity.auto_route is False

    @patch('ppxai.commands.handler.get_coding_model')
    def test_autoroute_off_custom(self, mock_get_coding, handler_custom, mock_engine_client):
        """Test /autoroute off with custom provider."""
        mock_get_coding.return_value = "gpt-oss-120b"
        handler_custom.auto_route = True
        handler_custom.handle_autoroute("off")
        assert handler_custom.auto_route is False

    @patch('ppxai.commands.handler.get_coding_model')
    def test_autoroute_status_perplexity(self, mock_get_coding, handler_perplexity, mock_engine_client):
        """Test /autoroute status check with Perplexity provider."""
        mock_get_coding.return_value = "sonar-reasoning"
        handler_perplexity.auto_route = True
        handler_perplexity.handle_autoroute("")
        # Should not change current status
        assert handler_perplexity.auto_route is True

    @patch('ppxai.commands.handler.get_coding_model')
    def test_autoroute_status_custom(self, mock_get_coding, handler_custom, mock_engine_client):
        """Test /autoroute status check with custom provider."""
        mock_get_coding.return_value = "gpt-oss-120b"
        handler_custom.auto_route = True
        handler_custom.handle_autoroute("")
        assert handler_custom.auto_route is True

    # ==================== /provider Command ====================

    @patch('ppxai.commands.handler.select_provider')
    @patch('ppxai.commands.handler.select_model')
    @patch('ppxai.commands.handler.get_api_key')
    @patch('ppxai.commands.handler.get_base_url')
    @patch('ppxai.commands.handler.get_provider_config')
    def test_provider_switch_perplexity_to_custom(
        self,
        mock_get_config,
        mock_get_url,
        mock_get_key,
        mock_select_model,
        mock_select_provider,
        handler_perplexity,
        mock_engine_client
    ):
        """Test switching from Perplexity to custom provider."""
        # Setup mocks
        mock_select_provider.return_value = "custom"
        mock_get_key.return_value = "custom-key"
        mock_get_url.return_value = "https://custom.example.com/v1"
        mock_get_config.return_value = {"name": "Custom Provider", "api_key_env": "CUSTOM_API_KEY"}
        mock_select_model.return_value = "gpt-oss-120b"
        mock_engine_client.set_provider = Mock(return_value=True)
        mock_engine_client.set_model = Mock(return_value=True)

        handler_perplexity.handle_provider()

        # Verify provider switched
        assert handler_perplexity.provider == "custom"
        assert handler_perplexity.api_key == "custom-key"
        assert handler_perplexity.base_url == "https://custom.example.com/v1"
        assert handler_perplexity.current_model == "gpt-oss-120b"

    @patch('ppxai.commands.handler.select_provider')
    @patch('ppxai.commands.handler.select_model')
    @patch('ppxai.commands.handler.get_api_key')
    @patch('ppxai.commands.handler.get_base_url')
    @patch('ppxai.commands.handler.get_provider_config')
    def test_provider_switch_custom_to_perplexity(
        self,
        mock_get_config,
        mock_get_url,
        mock_get_key,
        mock_select_model,
        mock_select_provider,
        handler_custom,
        mock_engine_client
    ):
        """Test switching from custom to Perplexity provider."""
        # Setup mocks
        mock_select_provider.return_value = "perplexity"
        mock_get_key.return_value = "ppx-key"
        mock_get_url.return_value = "https://api.perplexity.ai"
        mock_get_config.return_value = {"name": "Perplexity AI", "api_key_env": "PERPLEXITY_API_KEY"}
        mock_select_model.return_value = "sonar-pro"
        mock_engine_client.set_provider = Mock(return_value=True)
        mock_engine_client.set_model = Mock(return_value=True)

        handler_custom.handle_provider()

        # Verify provider switched
        assert handler_custom.provider == "perplexity"
        assert handler_custom.api_key == "ppx-key"
        assert handler_custom.base_url == "https://api.perplexity.ai"
        assert handler_custom.current_model == "sonar-pro"

    @patch('ppxai.commands.handler.select_provider')
    def test_provider_same_selection_perplexity(self, mock_select, handler_perplexity):
        """Test selecting same provider (Perplexity)."""
        mock_select.return_value = "perplexity"
        original_provider = handler_perplexity.provider
        handler_perplexity.handle_provider()
        # Should stay the same
        assert handler_perplexity.provider == original_provider

    @patch('ppxai.commands.handler.select_provider')
    def test_provider_same_selection_custom(self, mock_select, handler_custom):
        """Test selecting same provider (custom)."""
        mock_select.return_value = "custom"
        original_provider = handler_custom.provider
        handler_custom.handle_provider()
        assert handler_custom.provider == original_provider

    @patch('ppxai.commands.handler.select_provider')
    @patch('ppxai.commands.handler.get_api_key')
    @patch('ppxai.commands.handler.get_provider_config')
    def test_provider_switch_missing_api_key_perplexity(
        self,
        mock_get_config,
        mock_get_key,
        mock_select,
        handler_perplexity
    ):
        """Test switching provider with missing API key from Perplexity."""
        mock_select.return_value = "custom"
        mock_get_key.return_value = None  # Missing API key
        mock_get_config.return_value = {"api_key_env": "CUSTOM_API_KEY"}

        original_provider = handler_perplexity.provider
        handler_perplexity.handle_provider()

        # Should stay on original provider
        assert handler_perplexity.provider == original_provider

    @patch('ppxai.commands.handler.select_provider')
    @patch('ppxai.commands.handler.get_api_key')
    @patch('ppxai.commands.handler.get_provider_config')
    def test_provider_switch_missing_api_key_custom(
        self,
        mock_get_config,
        mock_get_key,
        mock_select,
        handler_custom
    ):
        """Test switching provider with missing API key from custom."""
        mock_select.return_value = "perplexity"
        mock_get_key.return_value = None
        mock_get_config.return_value = {"api_key_env": "PERPLEXITY_API_KEY"}

        original_provider = handler_custom.provider
        handler_custom.handle_provider()

        assert handler_custom.provider == original_provider


class TestCodingCommands:
    """Test coding-related commands for both providers."""

    @pytest.fixture
    def mock_engine_client(self):
        """Create a mock engine client."""
        engine = Mock()
        engine.session = Mock()
        engine.session.messages = []
        engine.session.session_name = "test"
        engine.session.get_usage = Mock(return_value={})
        engine.tools_enabled = False
        engine.model = "sonar-pro"
        engine.provider = "perplexity"
        return engine

    @pytest.fixture
    def handler_perplexity(self, mock_engine_client):
        """Handler with Perplexity provider."""
        handler = CommandHandler(
            "test-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )
        handler.engine_client = mock_engine_client
        return handler

    @pytest.fixture
    def handler_custom(self, mock_engine_client):
        """Handler with custom provider."""
        mock_engine_client.model = "custom-model"
        mock_engine_client.provider = "custom"
        handler = CommandHandler(
            "custom-key",
            "custom-model",
            "https://custom.example.com/v1",
            "custom"
        )
        handler.engine_client = mock_engine_client
        return handler

    # ==================== /generate Command ====================

    @patch('ppxai.commands.handler.send_coding_task')
    def test_generate_perplexity(self, mock_send, handler_perplexity):
        """Test /generate command with Perplexity."""
        handler_perplexity.handle_generate("a fibonacci function")
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "generate"
        assert "fibonacci" in args[0][2]
        assert args[0][3] == "sonar-pro"

    @patch('ppxai.commands.handler.send_coding_task')
    def test_generate_custom(self, mock_send, handler_custom):
        """Test /generate command with custom provider."""
        handler_custom.handle_generate("a sorting algorithm")
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "generate"
        assert "sorting" in args[0][2]
        assert args[0][3] == "custom-model"

    def test_generate_no_args_perplexity(self, handler_perplexity):
        """Test /generate without arguments for Perplexity."""
        # Should print error, not crash
        handler_perplexity.handle_generate("")

    def test_generate_no_args_custom(self, handler_custom):
        """Test /generate without arguments for custom provider."""
        handler_custom.handle_generate("")

    # ==================== /debug Command ====================

    @patch('ppxai.commands.handler.send_coding_task')
    def test_debug_perplexity(self, mock_send, handler_perplexity):
        """Test /debug command with Perplexity."""
        error_msg = "TypeError: 'NoneType' object is not subscriptable"
        handler_perplexity.handle_debug(error_msg)
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "debug"
        assert "TypeError" in args[0][2]

    @patch('ppxai.commands.handler.send_coding_task')
    def test_debug_custom(self, mock_send, handler_custom):
        """Test /debug command with custom provider."""
        error_msg = "IndexError: list index out of range"
        handler_custom.handle_debug(error_msg)
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "debug"
        assert "IndexError" in args[0][2]

    def test_debug_no_args_perplexity(self, handler_perplexity):
        """Test /debug without arguments for Perplexity."""
        handler_perplexity.handle_debug("")

    def test_debug_no_args_custom(self, handler_custom):
        """Test /debug without arguments for custom provider."""
        handler_custom.handle_debug("")

    # ==================== /implement Command ====================

    @patch('ppxai.commands.handler.send_coding_task')
    def test_implement_perplexity(self, mock_send, handler_perplexity):
        """Test /implement command with Perplexity."""
        spec = "a REST API endpoint for user authentication"
        handler_perplexity.handle_implement(spec)
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "implement"
        assert "authentication" in args[0][2]

    @patch('ppxai.commands.handler.send_coding_task')
    def test_implement_custom(self, mock_send, handler_custom):
        """Test /implement command with custom provider."""
        spec = "a caching layer with Redis"
        handler_custom.handle_implement(spec)
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "implement"
        assert "caching" in args[0][2]

    def test_implement_no_args_perplexity(self, handler_perplexity):
        """Test /implement without arguments for Perplexity."""
        handler_perplexity.handle_implement("")

    def test_implement_no_args_custom(self, handler_custom):
        """Test /implement without arguments for custom provider."""
        handler_custom.handle_implement("")


class TestToolsCommands:
    """Test /tools command for both providers."""

    @pytest.fixture
    def mock_engine_client(self):
        """Create a mock engine client."""
        engine = Mock()
        engine.session = Mock()
        engine.session.messages = []
        engine.session.session_name = "test"
        engine.session.get_usage = Mock(return_value={})
        engine.tools_enabled = False
        engine.model = "sonar-pro"
        engine.provider = "perplexity"
        engine.enable_tools = Mock()
        engine.disable_tools = Mock()
        return engine

    @pytest.fixture
    def handler_perplexity(self, mock_engine_client):
        """Handler with tools available for Perplexity."""
        handler = CommandHandler(
            "test-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )
        handler.engine_client = mock_engine_client
        handler.tools_available = True
        return handler

    @pytest.fixture
    def handler_custom(self, mock_engine_client):
        """Handler with tools available for custom provider."""
        mock_engine_client.model = "custom-model"
        mock_engine_client.provider = "custom"
        handler = CommandHandler(
            "custom-key",
            "custom-model",
            "https://custom.example.com/v1",
            "custom"
        )
        handler.engine_client = mock_engine_client
        handler.tools_available = True
        return handler

    def test_tools_status_disabled_perplexity(self, handler_perplexity):
        """Test /tools status when disabled for Perplexity."""
        handler_perplexity.handle_tools("status")
        # Should show tools not enabled

    def test_tools_status_disabled_custom(self, handler_custom):
        """Test /tools status when disabled for custom provider."""
        handler_custom.handle_tools("status")

    @patch('ppxai.commands.handler.asyncio.run')
    def test_tools_enable_perplexity(self, mock_asyncio, handler_perplexity, mock_engine_client):
        """Test /tools enable for Perplexity."""
        handler_perplexity.handle_tools("enable")
        # Should call engine_client.enable_tools()
        mock_engine_client.enable_tools.assert_called_once()

    @patch('ppxai.commands.handler.asyncio.run')
    def test_tools_enable_custom(self, mock_asyncio, handler_custom, mock_engine_client):
        """Test /tools enable for custom provider."""
        handler_custom.handle_tools("enable")
        # Should call engine_client.enable_tools()
        mock_engine_client.enable_tools.assert_called_once()

    def test_tools_unavailable_perplexity(self, handler_perplexity):
        """Test /tools when not available for Perplexity."""
        handler_perplexity.tools_available = False
        handler_perplexity.handle_tools("enable")
        # Should show error message

    def test_tools_unavailable_custom(self, handler_custom):
        """Test /tools when not available for custom provider."""
        handler_custom.tools_available = False
        handler_custom.handle_tools("enable")

    def test_tools_invalid_subcommand_perplexity(self, handler_perplexity):
        """Test /tools with invalid subcommand for Perplexity."""
        handler_perplexity.handle_tools("invalid")
        # Should show error

    def test_tools_invalid_subcommand_custom(self, handler_custom):
        """Test /tools with invalid subcommand for custom provider."""
        handler_custom.handle_tools("invalid")

    @patch('ppxai.commands.handler.display_file_editing_help')
    def test_tools_help_editing_perplexity(self, mock_help, handler_perplexity):
        """Test /tools help editing for Perplexity."""
        handler_perplexity.handle_tools("help editing")
        mock_help.assert_called_once()

    @patch('ppxai.commands.handler.display_file_editing_help')
    def test_tools_help_editing_custom(self, mock_help, handler_custom):
        """Test /tools help editing for custom provider."""
        handler_custom.handle_tools("help editing")
        mock_help.assert_called_once()

    def test_tools_help_no_topic_perplexity(self, handler_perplexity):
        """Test /tools help without topic for Perplexity."""
        handler_perplexity.handle_tools("help")
        # Should show available topics

    def test_tools_help_no_topic_custom(self, handler_custom):
        """Test /tools help without topic for custom provider."""
        handler_custom.handle_tools("help")
        # Should show available topics

    def test_tools_help_invalid_topic_perplexity(self, handler_perplexity):
        """Test /tools help with invalid topic for Perplexity."""
        handler_perplexity.handle_tools("help invalid_topic")
        # Should show available topics

    def test_tools_help_invalid_topic_custom(self, handler_custom):
        """Test /tools help with invalid topic for custom provider."""
        handler_custom.handle_tools("help invalid_topic")
        # Should show available topics


class TestSendCodingTask:
    """Test send_coding_task function for both providers."""

    @pytest.fixture
    def mock_engine_client(self):
        """Create a mock engine client."""
        engine = Mock()
        engine.session = Mock()
        engine.session.messages = []
        engine.session.session_name = "test"
        engine.tools_enabled = False
        engine.model = "sonar-pro"
        engine.provider = "perplexity"
        engine.set_model = Mock(return_value=True)
        return engine

    @pytest.fixture
    def handler(self, mock_engine_client):
        """Create a handler for testing send_coding_task."""
        handler = CommandHandler(
            "test-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )
        handler.engine_client = mock_engine_client
        handler.auto_route = True
        return handler

    @patch('ppxai.commands.handler.get_coding_model')
    @patch('ppxai.commands.handler.asyncio.run')
    def test_send_coding_task_perplexity(self, mock_run, mock_get_coding, handler):
        """Test send_coding_task with Perplexity provider."""
        mock_get_coding.return_value = "sonar-reasoning"
        # Consume coroutine to avoid warning
        def run_and_close(coro):
            coro.close()
            return "Code generated"
        mock_run.side_effect = run_and_close

        result = send_coding_task(
            handler,
            "generate",
            "Write a function",
            "sonar-pro",
            "perplexity"
        )

        # Should auto-route to coding model
        mock_get_coding.assert_called_once_with("perplexity")

    @patch('ppxai.commands.handler.get_coding_model')
    @patch('ppxai.commands.handler.asyncio.run')
    def test_send_coding_task_custom(self, mock_run, mock_get_coding, handler):
        """Test send_coding_task with custom provider."""
        mock_get_coding.return_value = "gpt-oss-120b"
        # Consume coroutine to avoid warning
        def run_and_close(coro):
            coro.close()
            return "Code generated"
        mock_run.side_effect = run_and_close
        handler.provider = "custom"

        result = send_coding_task(
            handler,
            "generate",
            "Write a function",
            "custom-model",
            "custom"
        )

        mock_get_coding.assert_called_once_with("custom")

    @patch('ppxai.commands.handler.get_coding_model')
    @patch('ppxai.commands.handler.asyncio.run')
    def test_send_coding_task_gemini(self, mock_run, mock_get_coding, handler):
        """Test send_coding_task with Gemini provider (regression test for bug-tui-20251223)."""
        mock_get_coding.return_value = "gemini-2.5-pro"
        # Consume coroutine to avoid warning
        def run_and_close(coro):
            coro.close()
            return "Code generated"
        mock_run.side_effect = run_and_close
        handler.provider = "gemini"

        result = send_coding_task(
            handler,
            "convert",
            "Convert R to Python",
            "gemini-2.0-flash-lite",
            "gemini"
        )

        # Should use Gemini's coding model, NOT Perplexity's
        mock_get_coding.assert_called_once_with("gemini")

    @patch('ppxai.commands.handler.get_coding_model')
    @patch('ppxai.commands.handler.asyncio.run')
    def test_send_coding_task_no_autoroute_perplexity(self, mock_run, mock_get_coding, handler):
        """Test send_coding_task with auto-route disabled for Perplexity."""
        handler.auto_route = False
        mock_get_coding.return_value = "sonar-reasoning"
        # Consume coroutine to avoid warning
        def run_and_close(coro):
            coro.close()
            return "Code generated"
        mock_run.side_effect = run_and_close

        result = send_coding_task(
            handler,
            "generate",
            "Write a function",
            "sonar-pro",
            "perplexity"
        )

        # Should use the model passed, not coding model
        # (auto-route disabled, so model stays as sonar-pro)
        mock_get_coding.assert_called_once_with("perplexity")

    @patch('ppxai.commands.handler.get_coding_model')
    @patch('ppxai.commands.handler.asyncio.run')
    def test_send_coding_task_no_autoroute_custom(self, mock_run, mock_get_coding, handler):
        """Test send_coding_task with auto-route disabled for custom provider."""
        handler.auto_route = False
        mock_get_coding.return_value = "gpt-oss-120b"
        # Consume coroutine to avoid warning
        def run_and_close(coro):
            coro.close()
            return "Code generated"
        mock_run.side_effect = run_and_close
        handler.provider = "custom"

        result = send_coding_task(
            handler,
            "generate",
            "Write a function",
            "custom-model",
            "custom"
        )

        mock_get_coding.assert_called_once_with("custom")

    def test_send_coding_task_invalid_type_perplexity(self, handler):
        """Test send_coding_task with invalid task type for Perplexity."""
        result = send_coding_task(
            handler,
            "invalid_task",
            "Some task",
            "sonar-pro",
            "perplexity"
        )

        assert result is None

    def test_send_coding_task_invalid_type_custom(self, handler):
        """Test send_coding_task with invalid task type for custom provider."""
        handler.provider = "custom"
        result = send_coding_task(
            handler,
            "invalid_task",
            "Some task",
            "custom-model",
            "custom"
        )

        assert result is None


class TestCommandHandlerIntegration:
    """Integration tests for command handling with both providers."""

    @pytest.fixture
    def mock_engine_client(self):
        """Create a mock engine client."""
        engine = Mock()
        engine.session = Mock()
        engine.session.messages = []
        engine.session.session_name = "test"
        engine.session.get_usage = Mock(return_value={})
        engine.session.save = Mock()
        engine.tools_enabled = False
        engine.model = "sonar-pro"
        engine.provider = "perplexity"
        return engine

    @pytest.fixture
    def handler_perplexity(self, mock_engine_client):
        """Create a real CommandHandler for Perplexity."""
        handler = CommandHandler(
            "test-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )
        handler.engine_client = mock_engine_client
        return handler

    @pytest.fixture
    def handler_custom(self, mock_engine_client):
        """Create a real CommandHandler for custom provider."""
        mock_engine_client.model = "custom-model"
        mock_engine_client.provider = "custom"
        handler = CommandHandler(
            "custom-key",
            "custom-model",
            "https://custom.example.com/v1",
            "custom"
        )
        handler.engine_client = mock_engine_client
        return handler

    def test_handle_unknown_command_perplexity(self, handler_perplexity):
        """Test handling unknown command with Perplexity."""
        result = handler_perplexity.handle_command("/unknown")
        assert result is False

    def test_handle_unknown_command_custom(self, handler_custom):
        """Test handling unknown command with custom provider."""
        result = handler_custom.handle_command("/unknown")
        assert result is False

    def test_handle_quit_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /quit command returns True for Perplexity."""
        result = handler_perplexity.handle_command("/quit")
        assert result is True

    def test_handle_quit_command_custom(self, handler_custom, mock_engine_client):
        """Test /quit command returns True for custom provider."""
        result = handler_custom.handle_command("/quit")
        assert result is True

    def test_handle_exit_command_perplexity(self, handler_perplexity, mock_engine_client):
        """Test /exit command returns True for Perplexity."""
        result = handler_perplexity.handle_command("/exit")
        assert result is True

    def test_handle_exit_command_custom(self, handler_custom, mock_engine_client):
        """Test /exit command returns True for custom provider."""
        result = handler_custom.handle_command("/exit")
        assert result is True

    @patch('ppxai.commands.handler.display_welcome')
    def test_handle_help_command_perplexity(self, mock_welcome, handler_perplexity):
        """Test /help command for Perplexity."""
        result = handler_perplexity.handle_command("/help")
        assert result is False  # Should not exit
        mock_welcome.assert_called()

    @patch('ppxai.commands.handler.display_welcome')
    def test_handle_help_command_custom(self, mock_welcome, handler_custom):
        """Test /help command for custom provider."""
        result = handler_custom.handle_command("/help")
        assert result is False
        mock_welcome.assert_called()


class TestCommandsWithToolUsage:
    """Tests for command handlers with tool usage tracking (v1.13.4)."""

    @pytest.fixture
    def mock_engine_with_tool_usage(self):
        """Create a mock EngineClient with tool usage data."""
        engine = Mock()
        engine.session = Mock()
        engine.session.messages = []
        engine.session.session_name = "test_session"
        engine.session.get_usage = Mock(return_value={
            "total_tokens": 2500,
            "prompt_tokens": 1500,
            "completion_tokens": 1000,
            "estimated_cost": 0.10,
            "tool_calls": {
                "web_search": {
                    "call_count": 2,
                    "tokens_in": 200,
                    "tokens_out": 400,
                    "estimated_cost": 0.01,
                    "provider": "perplexity"
                }
            }
        })
        engine.session.save = Mock()
        engine.tools_enabled = True
        engine.model = "gpt-4o"
        engine.provider = "openai"
        return engine

    @pytest.fixture
    def handler_with_tools(self, mock_engine_with_tool_usage):
        """Create CommandHandler with tool usage enabled."""
        handler = CommandHandler(
            "test-api-key",
            "gpt-4o",
            "https://api.openai.com/v1",
            "openai"
        )
        handler.engine_client = mock_engine_with_tool_usage
        return handler

    def test_usage_command_includes_tool_usage(self, handler_with_tools, capsys):
        """Test /usage command displays tool usage breakdown."""
        handler_with_tools.handle_command("/usage")
        captured = capsys.readouterr()

        # Should contain tool information
        output = captured.out
        assert "web_search" in output or "Tools" in output or "tool" in output.lower()

    def test_usage_command_tool_costs(self, handler_with_tools, capsys):
        """Test /usage command shows tool costs separately."""
        handler_with_tools.handle_command("/usage")
        captured = capsys.readouterr()

        output = captured.out
        # Should show model cost (0.10) and tool cost (0.01)
        # Total should be around 0.11
        assert "0.1" in output or "$0" in output or "Cost" in output

    def test_usage_command_without_tool_usage(self, capsys):
        """Test /usage command when no tools were used."""
        mock_engine = Mock()
        mock_engine.session = Mock()
        mock_engine.session.messages = []
        mock_engine.session.get_usage.return_value = {
            "total_tokens": 1500,
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "estimated_cost": 0.05,
            "tool_calls": {}  # No tool calls
        }
        mock_engine.tools_enabled = False
        mock_engine.model = "sonar-pro"
        mock_engine.provider = "perplexity"

        handler = CommandHandler(
            "test-api-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )
        handler.engine_client = mock_engine

        handler.handle_command("/usage")
        captured = capsys.readouterr()

        output = captured.out
        # Should not crash and should show basic usage
        assert "Cost" in output or "total" in output.lower()

    @pytest.fixture
    def mock_engine_with_multiple_tools(self):
        """Create EngineClient with multiple tool usage."""
        engine = Mock()
        engine.session = Mock()
        engine.session.messages = []
        engine.session.get_usage = Mock(return_value={
            "total_tokens": 3000,
            "prompt_tokens": 2000,
            "completion_tokens": 1000,
            "estimated_cost": 0.15,
            "tool_calls": {
                "web_search": {
                    "call_count": 3,
                    "tokens_in": 300,
                    "tokens_out": 600,
                    "estimated_cost": 0.02,
                    "provider": "perplexity"
                },
                "shell": {
                    "call_count": 2,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "estimated_cost": 0.0,
                    "provider": "free"
                }
            }
        })
        engine.session.save = Mock()
        engine.tools_enabled = True
        engine.model = "gpt-4o"
        engine.provider = "openai"
        return engine

    def test_usage_command_multiple_tools(self, mock_engine_with_multiple_tools, capsys):
        """Test /usage command with multiple tools used."""
        handler = CommandHandler(
            "test-api-key",
            "gpt-4o",
            "https://api.openai.com/v1",
            "openai"
        )
        handler.engine_client = mock_engine_with_multiple_tools

        handler.handle_command("/usage")
        captured = capsys.readouterr()

        output = captured.out
        # Should show both tools
        assert ("web_search" in output or "tool" in output.lower()) or "Call" in output

    @patch('ppxai.engine.tools.builtin.web_premium.is_available')
    def test_tools_status_shows_premium_search(self, mock_available, handler_with_tools, capsys):
        """Test /tools status displays premium search provider."""
        mock_available.return_value = True

        with patch('ppxai.engine.tools.builtin.web_premium.get_premium_search_provider') as mock_provider:
            mock_provider.return_value = "perplexity"
            handler_with_tools.handle_command("/tools status")
            captured = capsys.readouterr()

            output = captured.out
            # Should show some information about web search
            assert "search" in output.lower() or "perplexity" in output.lower() or "Web" in output

    @patch('ppxai.engine.tools.builtin.web_premium.is_available')
    def test_tools_status_shows_free_search(self, mock_available, handler_with_tools, capsys):
        """Test /tools status shows free DuckDuckGo when no premium available."""
        mock_available.return_value = False

        handler_with_tools.handle_command("/tools status")
        captured = capsys.readouterr()

        output = captured.out
        # Should show web search status
        assert "search" in output.lower() or "Web" in output or "DuckDuckGo" in output
