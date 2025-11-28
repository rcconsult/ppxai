"""
Tests for command handlers with both Perplexity and Custom providers.
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock, call
from io import StringIO

from ppxai.commands import CommandHandler, send_coding_task
from ppxai.client import AIClient


class TestCommandHandlerBothProviders:
    """Test CommandHandler with both providers."""

    @pytest.fixture
    def mock_client_perplexity(self):
        """Create a mock AIClient for Perplexity."""
        client = Mock(spec=AIClient)
        client.conversation_history = []
        client.session_name = "test_session"
        client.session_metadata = {"model": "sonar-pro", "provider": "perplexity"}
        client.current_session_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0
        }
        client.auto_route = True
        return client

    @pytest.fixture
    def mock_client_custom(self):
        """Create a mock AIClient for custom provider."""
        client = Mock(spec=AIClient)
        client.conversation_history = []
        client.session_name = "test_session_custom"
        client.session_metadata = {"model": "custom-model", "provider": "custom"}
        client.current_session_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0
        }
        client.auto_route = True
        return client

    @pytest.fixture
    def handler_perplexity(self, mock_client_perplexity):
        """Create CommandHandler for Perplexity provider."""
        return CommandHandler(
            mock_client_perplexity,
            "test-api-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )

    @pytest.fixture
    def handler_custom(self, mock_client_custom):
        """Create CommandHandler for custom provider."""
        return CommandHandler(
            mock_client_custom,
            "custom-api-key",
            "custom-model",
            "https://custom.example.com/v1",
            "custom"
        )

    # ==================== /quit Command ====================

    def test_quit_command_perplexity(self, handler_perplexity, mock_client_perplexity):
        """Test /quit command with Perplexity provider."""
        mock_client_perplexity.conversation_history = [{"role": "user", "content": "test"}]
        mock_client_perplexity.save_session = Mock()
        result = handler_perplexity.handle_quit()
        assert result is True
        mock_client_perplexity.save_session.assert_called_once()

    def test_quit_command_custom(self, handler_custom, mock_client_custom):
        """Test /quit command with custom provider."""
        mock_client_custom.conversation_history = [{"role": "user", "content": "test"}]
        mock_client_custom.save_session = Mock()
        result = handler_custom.handle_quit()
        assert result is True
        mock_client_custom.save_session.assert_called_once()

    def test_quit_with_empty_history_perplexity(self, handler_perplexity, mock_client_perplexity):
        """Test /quit with empty history for Perplexity."""
        mock_client_perplexity.conversation_history = []
        mock_client_perplexity.save_session = Mock()
        result = handler_perplexity.handle_quit()
        assert result is True
        # Should not save when history is empty
        mock_client_perplexity.save_session.assert_not_called()

    def test_quit_with_empty_history_custom(self, handler_custom, mock_client_custom):
        """Test /quit with empty history for custom provider."""
        mock_client_custom.conversation_history = []
        mock_client_custom.save_session = Mock()
        result = handler_custom.handle_quit()
        assert result is True
        mock_client_custom.save_session.assert_not_called()

    # ==================== /clear Command ====================

    def test_clear_command_perplexity(self, handler_perplexity, mock_client_perplexity):
        """Test /clear command with Perplexity provider."""
        mock_client_perplexity.conversation_history = [{"role": "user", "content": "test"}]
        mock_client_perplexity.clear_history = Mock()
        handler_perplexity.handle_clear()
        mock_client_perplexity.clear_history.assert_called_once()

    def test_clear_command_custom(self, handler_custom, mock_client_custom):
        """Test /clear command with custom provider."""
        mock_client_custom.conversation_history = [{"role": "user", "content": "test"}]
        mock_client_custom.clear_history = Mock()
        handler_custom.handle_clear()
        mock_client_custom.clear_history.assert_called_once()

    # ==================== /usage Command ====================

    def test_usage_command_perplexity(self, handler_perplexity, mock_client_perplexity):
        """Test /usage command with Perplexity provider."""
        mock_usage = {
            "total_tokens": 100,
            "prompt_tokens": 60,
            "completion_tokens": 40,
            "estimated_cost": 0.001
        }
        mock_client_perplexity.get_usage_summary = Mock(return_value=mock_usage)

        with patch('ppxai.commands.display_usage') as mock_display:
            with patch('ppxai.commands.display_global_usage') as mock_global:
                handler_perplexity.handle_usage()
                mock_display.assert_called_once_with(mock_usage)
                mock_global.assert_called_once()

    def test_usage_command_custom(self, handler_custom, mock_client_custom):
        """Test /usage command with custom provider."""
        mock_usage = {
            "total_tokens": 200,
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "estimated_cost": 0.002
        }
        mock_client_custom.get_usage_summary = Mock(return_value=mock_usage)

        with patch('ppxai.commands.display_usage') as mock_display:
            with patch('ppxai.commands.display_global_usage') as mock_global:
                handler_custom.handle_usage()
                mock_display.assert_called_once_with(mock_usage)
                mock_global.assert_called_once()

    # ==================== /model Command ====================

    @patch('ppxai.commands.select_model')
    def test_model_command_perplexity(self, mock_select, handler_perplexity):
        """Test /model command with Perplexity provider."""
        mock_select.return_value = "sonar-reasoning"
        handler_perplexity.handle_model()

        assert handler_perplexity.current_model == "sonar-reasoning"
        assert handler_perplexity.client.session_metadata["model"] == "sonar-reasoning"
        mock_select.assert_called_once_with("perplexity")

    @patch('ppxai.commands.select_model')
    def test_model_command_custom(self, mock_select, handler_custom):
        """Test /model command with custom provider."""
        mock_select.return_value = "gpt-oss-120b"
        handler_custom.handle_model()

        assert handler_custom.current_model == "gpt-oss-120b"
        assert handler_custom.client.session_metadata["model"] == "gpt-oss-120b"
        mock_select.assert_called_once_with("custom")

    # ==================== /save Command ====================

    def test_save_command_perplexity(self, handler_perplexity, mock_client_perplexity):
        """Test /save command with Perplexity provider."""
        mock_client_perplexity.export_conversation = Mock(return_value="/path/to/export.md")
        handler_perplexity.handle_save("my_export")
        mock_client_perplexity.export_conversation.assert_called_once_with("my_export")

    def test_save_command_custom(self, handler_custom, mock_client_custom):
        """Test /save command with custom provider."""
        mock_client_custom.export_conversation = Mock(return_value="/path/to/custom_export.md")
        handler_custom.handle_save("custom_export")
        mock_client_custom.export_conversation.assert_called_once_with("custom_export")

    def test_save_without_filename_perplexity(self, handler_perplexity, mock_client_perplexity):
        """Test /save without filename for Perplexity."""
        mock_client_perplexity.export_conversation = Mock(return_value="/path/to/export.md")
        handler_perplexity.handle_save("")
        mock_client_perplexity.export_conversation.assert_called_once_with(None)

    def test_save_without_filename_custom(self, handler_custom, mock_client_custom):
        """Test /save without filename for custom provider."""
        mock_client_custom.export_conversation = Mock(return_value="/path/to/export.md")
        handler_custom.handle_save("")
        mock_client_custom.export_conversation.assert_called_once_with(None)

    # ==================== /sessions Command ====================

    @patch('ppxai.client.AIClient.list_sessions')
    @patch('ppxai.commands.display_sessions')
    def test_sessions_command_perplexity(self, mock_display, mock_list, handler_perplexity):
        """Test /sessions command with Perplexity provider."""
        mock_sessions = [
            {"name": "session1", "created": "2024-01-01", "provider": "perplexity"},
            {"name": "session2", "created": "2024-01-02", "provider": "perplexity"}
        ]
        mock_list.return_value = mock_sessions
        handler_perplexity.handle_sessions()
        mock_list.assert_called_once()
        mock_display.assert_called_once_with(mock_sessions)

    @patch('ppxai.client.AIClient.list_sessions')
    @patch('ppxai.commands.display_sessions')
    def test_sessions_command_custom(self, mock_display, mock_list, handler_custom):
        """Test /sessions command with custom provider."""
        mock_sessions = [
            {"name": "custom_session1", "created": "2024-01-01", "provider": "custom"},
        ]
        mock_list.return_value = mock_sessions
        handler_custom.handle_sessions()
        mock_list.assert_called_once()
        mock_display.assert_called_once_with(mock_sessions)

    # ==================== /autoroute Command ====================

    @patch('ppxai.commands.get_coding_model')
    def test_autoroute_on_perplexity(self, mock_get_coding, handler_perplexity, mock_client_perplexity):
        """Test /autoroute on with Perplexity provider."""
        mock_get_coding.return_value = "sonar-reasoning"
        mock_client_perplexity.auto_route = False
        handler_perplexity.handle_autoroute("on")
        assert mock_client_perplexity.auto_route is True

    @patch('ppxai.commands.get_coding_model')
    def test_autoroute_on_custom(self, mock_get_coding, handler_custom, mock_client_custom):
        """Test /autoroute on with custom provider."""
        mock_get_coding.return_value = "gpt-oss-120b"
        mock_client_custom.auto_route = False
        handler_custom.handle_autoroute("on")
        assert mock_client_custom.auto_route is True

    @patch('ppxai.commands.get_coding_model')
    def test_autoroute_off_perplexity(self, mock_get_coding, handler_perplexity, mock_client_perplexity):
        """Test /autoroute off with Perplexity provider."""
        mock_get_coding.return_value = "sonar-reasoning"
        mock_client_perplexity.auto_route = True
        handler_perplexity.handle_autoroute("off")
        assert mock_client_perplexity.auto_route is False

    @patch('ppxai.commands.get_coding_model')
    def test_autoroute_off_custom(self, mock_get_coding, handler_custom, mock_client_custom):
        """Test /autoroute off with custom provider."""
        mock_get_coding.return_value = "gpt-oss-120b"
        mock_client_custom.auto_route = True
        handler_custom.handle_autoroute("off")
        assert mock_client_custom.auto_route is False

    @patch('ppxai.commands.get_coding_model')
    def test_autoroute_status_perplexity(self, mock_get_coding, handler_perplexity, mock_client_perplexity):
        """Test /autoroute status check with Perplexity provider."""
        mock_get_coding.return_value = "sonar-reasoning"
        handler_perplexity.handle_autoroute("")
        # Should not change current status
        assert mock_client_perplexity.auto_route is True

    @patch('ppxai.commands.get_coding_model')
    def test_autoroute_status_custom(self, mock_get_coding, handler_custom, mock_client_custom):
        """Test /autoroute status check with custom provider."""
        mock_get_coding.return_value = "gpt-oss-120b"
        handler_custom.handle_autoroute("")
        assert mock_client_custom.auto_route is True

    # ==================== /provider Command ====================

    @patch('ppxai.commands.select_provider')
    @patch('ppxai.commands.select_model')
    @patch('ppxai.commands.get_api_key')
    @patch('ppxai.commands.get_base_url')
    @patch('ppxai.commands.get_provider_config')
    @patch('ppxai.client.AIClient')
    def test_provider_switch_perplexity_to_custom(
        self,
        mock_aiclient_class,
        mock_get_config,
        mock_get_url,
        mock_get_key,
        mock_select_model,
        mock_select_provider,
        handler_perplexity
    ):
        """Test switching from Perplexity to custom provider."""
        # Setup mocks
        mock_select_provider.return_value = "custom"
        mock_get_key.return_value = "custom-key"
        mock_get_url.return_value = "https://custom.example.com/v1"
        mock_get_config.return_value = {"name": "Custom Provider", "api_key_env": "CUSTOM_API_KEY"}
        mock_select_model.return_value = "gpt-oss-120b"

        # Create mock new client
        new_client = Mock()
        new_client.conversation_history = []
        new_client.session_metadata = {}
        new_client.current_session_usage = {}
        mock_aiclient_class.return_value = new_client

        handler_perplexity.handle_provider()

        # Verify provider switched
        assert handler_perplexity.provider == "custom"
        assert handler_perplexity.api_key == "custom-key"
        assert handler_perplexity.base_url == "https://custom.example.com/v1"
        assert handler_perplexity.current_model == "gpt-oss-120b"

    @patch('ppxai.commands.select_provider')
    @patch('ppxai.commands.select_model')
    @patch('ppxai.commands.get_api_key')
    @patch('ppxai.commands.get_base_url')
    @patch('ppxai.commands.get_provider_config')
    @patch('ppxai.client.AIClient')
    def test_provider_switch_custom_to_perplexity(
        self,
        mock_aiclient_class,
        mock_get_config,
        mock_get_url,
        mock_get_key,
        mock_select_model,
        mock_select_provider,
        handler_custom
    ):
        """Test switching from custom to Perplexity provider."""
        # Setup mocks
        mock_select_provider.return_value = "perplexity"
        mock_get_key.return_value = "ppx-key"
        mock_get_url.return_value = "https://api.perplexity.ai"
        mock_get_config.return_value = {"name": "Perplexity AI", "api_key_env": "PERPLEXITY_API_KEY"}
        mock_select_model.return_value = "sonar-pro"

        # Create mock new client
        new_client = Mock()
        new_client.conversation_history = []
        new_client.session_metadata = {}
        new_client.current_session_usage = {}
        mock_aiclient_class.return_value = new_client

        handler_custom.handle_provider()

        # Verify provider switched
        assert handler_custom.provider == "perplexity"
        assert handler_custom.api_key == "ppx-key"
        assert handler_custom.base_url == "https://api.perplexity.ai"
        assert handler_custom.current_model == "sonar-pro"

    @patch('ppxai.commands.select_provider')
    def test_provider_same_selection_perplexity(self, mock_select, handler_perplexity):
        """Test selecting same provider (Perplexity)."""
        mock_select.return_value = "perplexity"
        original_provider = handler_perplexity.provider
        handler_perplexity.handle_provider()
        # Should stay the same
        assert handler_perplexity.provider == original_provider

    @patch('ppxai.commands.select_provider')
    def test_provider_same_selection_custom(self, mock_select, handler_custom):
        """Test selecting same provider (custom)."""
        mock_select.return_value = "custom"
        original_provider = handler_custom.provider
        handler_custom.handle_provider()
        assert handler_custom.provider == original_provider

    @patch('ppxai.commands.select_provider')
    @patch('ppxai.commands.get_api_key')
    @patch('ppxai.commands.get_provider_config')
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

    @patch('ppxai.commands.select_provider')
    @patch('ppxai.commands.get_api_key')
    @patch('ppxai.commands.get_provider_config')
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
    def mock_client(self):
        """Create a mock client."""
        client = Mock(spec=AIClient)
        client.auto_route = True
        client.chat = Mock(return_value="Code generated successfully")
        return client

    @pytest.fixture
    def handler_perplexity(self, mock_client):
        """Handler with Perplexity provider."""
        return CommandHandler(
            mock_client,
            "test-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )

    @pytest.fixture
    def handler_custom(self, mock_client):
        """Handler with custom provider."""
        return CommandHandler(
            mock_client,
            "custom-key",
            "custom-model",
            "https://custom.example.com/v1",
            "custom"
        )

    # ==================== /generate Command ====================

    @patch('ppxai.commands.send_coding_task')
    def test_generate_perplexity(self, mock_send, handler_perplexity):
        """Test /generate command with Perplexity."""
        handler_perplexity.handle_generate("a fibonacci function")
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "generate"
        assert "fibonacci" in args[0][2]
        assert args[0][3] == "sonar-pro"

    @patch('ppxai.commands.send_coding_task')
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

    @patch('ppxai.commands.send_coding_task')
    def test_debug_perplexity(self, mock_send, handler_perplexity):
        """Test /debug command with Perplexity."""
        error_msg = "TypeError: 'NoneType' object is not subscriptable"
        handler_perplexity.handle_debug(error_msg)
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "debug"
        assert "TypeError" in args[0][2]

    @patch('ppxai.commands.send_coding_task')
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

    @patch('ppxai.commands.send_coding_task')
    def test_implement_perplexity(self, mock_send, handler_perplexity):
        """Test /implement command with Perplexity."""
        spec = "a REST API endpoint for user authentication"
        handler_perplexity.handle_implement(spec)
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][1] == "implement"
        assert "authentication" in args[0][2]

    @patch('ppxai.commands.send_coding_task')
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
    def mock_client(self):
        """Create a mock client."""
        client = Mock(spec=AIClient)
        client.session_name = "test_session"
        client.conversation_history = []
        client.session_metadata = {}
        client.current_session_usage = {}
        return client

    @pytest.fixture
    def handler_perplexity(self, mock_client):
        """Handler with tools available for Perplexity."""
        handler = CommandHandler(
            mock_client,
            "test-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )
        handler.tools_available = True
        # Create a proper mock class (not instance)
        mock_tool_class = type('MockPerplexityClientPromptTools', (), {})
        handler.PerplexityClientPromptTools = mock_tool_class
        return handler

    @pytest.fixture
    def handler_custom(self, mock_client):
        """Handler with tools available for custom provider."""
        handler = CommandHandler(
            mock_client,
            "custom-key",
            "custom-model",
            "https://custom.example.com/v1",
            "custom"
        )
        handler.tools_available = True
        # Create a proper mock class (not instance)
        mock_tool_class = type('MockPerplexityClientPromptTools', (), {})
        handler.PerplexityClientPromptTools = mock_tool_class
        return handler

    def test_tools_status_disabled_perplexity(self, handler_perplexity):
        """Test /tools status when disabled for Perplexity."""
        handler_perplexity.handle_tools("status")
        # Should show tools not enabled

    def test_tools_status_disabled_custom(self, handler_custom):
        """Test /tools status when disabled for custom provider."""
        handler_custom.handle_tools("status")

    @patch('ppxai.commands.asyncio.run')
    def test_tools_enable_perplexity(self, mock_asyncio, handler_perplexity):
        """Test /tools enable for Perplexity."""
        # Create a proper mock class that can be used with isinstance
        class MockToolClient:
            def __init__(self, *args, **kwargs):
                self.conversation_history = []
                self.session_metadata = {}
                self.current_session_usage = {}
                self.initialize_tools = Mock()

        # Replace with our mock class
        handler_perplexity.PerplexityClientPromptTools = MockToolClient
        handler_perplexity.handle_tools("enable")

        # Should create tool client
        assert isinstance(handler_perplexity.client, MockToolClient)

    @patch('ppxai.commands.asyncio.run')
    def test_tools_enable_custom(self, mock_asyncio, handler_custom):
        """Test /tools enable for custom provider."""
        # Create a proper mock class that can be used with isinstance
        class MockToolClient:
            def __init__(self, *args, **kwargs):
                self.conversation_history = []
                self.session_metadata = {}
                self.current_session_usage = {}
                self.initialize_tools = Mock()

        # Replace with our mock class
        handler_custom.PerplexityClientPromptTools = MockToolClient
        handler_custom.handle_tools("enable")

        # Should create tool client
        assert isinstance(handler_custom.client, MockToolClient)

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


class TestSendCodingTask:
    """Test send_coding_task function for both providers."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock client."""
        client = Mock(spec=AIClient)
        client.auto_route = True
        client.chat = Mock(return_value="Task completed")
        return client

    @patch('ppxai.commands.get_coding_model')
    def test_send_coding_task_perplexity(self, mock_get_coding, mock_client):
        """Test send_coding_task with Perplexity provider."""
        mock_get_coding.return_value = "sonar-reasoning"

        result = send_coding_task(
            mock_client,
            "generate",
            "Write a function",
            "sonar-pro",
            "perplexity"
        )

        # Should auto-route to coding model
        assert mock_client.chat.called
        # Should use coding model
        call_args = mock_client.chat.call_args
        assert call_args[0][1] == "sonar-reasoning"

    @patch('ppxai.commands.get_coding_model')
    def test_send_coding_task_custom(self, mock_get_coding, mock_client):
        """Test send_coding_task with custom provider."""
        mock_get_coding.return_value = "gpt-oss-120b"

        result = send_coding_task(
            mock_client,
            "generate",
            "Write a function",
            "custom-model",
            "custom"
        )

        assert mock_client.chat.called
        call_args = mock_client.chat.call_args
        assert call_args[0][1] == "gpt-oss-120b"

    @patch('ppxai.commands.get_coding_model')
    def test_send_coding_task_no_autoroute_perplexity(self, mock_get_coding, mock_client):
        """Test send_coding_task with auto-route disabled for Perplexity."""
        mock_client.auto_route = False
        mock_get_coding.return_value = "sonar-reasoning"

        result = send_coding_task(
            mock_client,
            "generate",
            "Write a function",
            "sonar-pro",
            "perplexity"
        )

        # Should use the model passed, not coding model
        call_args = mock_client.chat.call_args
        assert call_args[0][1] == "sonar-pro"

    @patch('ppxai.commands.get_coding_model')
    def test_send_coding_task_no_autoroute_custom(self, mock_get_coding, mock_client):
        """Test send_coding_task with auto-route disabled for custom provider."""
        mock_client.auto_route = False
        mock_get_coding.return_value = "gpt-oss-120b"

        result = send_coding_task(
            mock_client,
            "generate",
            "Write a function",
            "custom-model",
            "custom"
        )

        call_args = mock_client.chat.call_args
        assert call_args[0][1] == "custom-model"

    def test_send_coding_task_invalid_type_perplexity(self, mock_client):
        """Test send_coding_task with invalid task type for Perplexity."""
        result = send_coding_task(
            mock_client,
            "invalid_task",
            "Some task",
            "sonar-pro",
            "perplexity"
        )

        assert result is None

    def test_send_coding_task_invalid_type_custom(self, mock_client):
        """Test send_coding_task with invalid task type for custom provider."""
        result = send_coding_task(
            mock_client,
            "invalid_task",
            "Some task",
            "custom-model",
            "custom"
        )

        assert result is None


class TestCommandHandlerIntegration:
    """Integration tests for command handling with both providers."""

    @pytest.fixture
    def handler_perplexity(self):
        """Create a real CommandHandler for Perplexity."""
        client = Mock(spec=AIClient)
        client.conversation_history = []
        client.session_metadata = {"model": "sonar-pro", "provider": "perplexity"}
        client.auto_route = True
        return CommandHandler(
            client,
            "test-key",
            "sonar-pro",
            "https://api.perplexity.ai",
            "perplexity"
        )

    @pytest.fixture
    def handler_custom(self):
        """Create a real CommandHandler for custom provider."""
        client = Mock(spec=AIClient)
        client.conversation_history = []
        client.session_metadata = {"model": "custom-model", "provider": "custom"}
        client.auto_route = True
        return CommandHandler(
            client,
            "custom-key",
            "custom-model",
            "https://custom.example.com/v1",
            "custom"
        )

    def test_handle_unknown_command_perplexity(self, handler_perplexity):
        """Test handling unknown command with Perplexity."""
        result = handler_perplexity.handle_command("/unknown")
        assert result is False

    def test_handle_unknown_command_custom(self, handler_custom):
        """Test handling unknown command with custom provider."""
        result = handler_custom.handle_command("/unknown")
        assert result is False

    def test_handle_quit_command_perplexity(self, handler_perplexity):
        """Test /quit command returns True for Perplexity."""
        handler_perplexity.client.save_session = Mock()
        result = handler_perplexity.handle_command("/quit")
        assert result is True

    def test_handle_quit_command_custom(self, handler_custom):
        """Test /quit command returns True for custom provider."""
        handler_custom.client.save_session = Mock()
        result = handler_custom.handle_command("/quit")
        assert result is True

    def test_handle_exit_command_perplexity(self, handler_perplexity):
        """Test /exit command returns True for Perplexity."""
        handler_perplexity.client.save_session = Mock()
        result = handler_perplexity.handle_command("/exit")
        assert result is True

    def test_handle_exit_command_custom(self, handler_custom):
        """Test /exit command returns True for custom provider."""
        handler_custom.client.save_session = Mock()
        result = handler_custom.handle_command("/exit")
        assert result is True

    @patch('ppxai.commands.display_welcome')
    def test_handle_help_command_perplexity(self, mock_welcome, handler_perplexity):
        """Test /help command for Perplexity."""
        result = handler_perplexity.handle_command("/help")
        assert result is False
        mock_welcome.assert_called_once()

    @patch('ppxai.commands.display_welcome')
    def test_handle_help_command_custom(self, mock_welcome, handler_custom):
        """Test /help command for custom provider."""
        result = handler_custom.handle_command("/help")
        assert result is False
        mock_welcome.assert_called_once()
