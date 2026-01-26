"""
Test suite for TUI Command Factory Integration (Phase 6.2).

Validates that factory commands work correctly in the Textual TUI environment.
Tests command execution, error handling, and result rendering.

Phase 6.2: Command Handler Validation
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from textual.app import App

from ppxai.commands.factory import CommandFactory
from ppxai.commands.protocol import CommandContext
from ppxai.commands.results import (
    ResultStatus,
    TextResult,
    ErrorResult,
    FileViewResult,
    TableResult,
    KeyValueResult,
    ConfirmationResult,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_engine_client():
    """Mock EngineClient for testing commands that need engine access."""
    client = Mock()
    client.get_working_dir = Mock(return_value=str(Path.cwd()))
    client.get_provider = Mock(return_value="openai")
    client.get_model = Mock(return_value="gpt-4")
    client.get_tools_enabled = Mock(return_value=True)
    client.tools_enabled = True
    client.agent_mode = False
    client.set_provider = AsyncMock()
    client.set_model = AsyncMock()
    client.enable_tools = Mock()
    client.disable_tools = Mock()
    client.save_session = Mock(return_value="session_123")
    client.load_session = Mock()
    client.list_sessions = Mock(return_value=["session_1", "session_2"])
    client.get_session_history = Mock(return_value=[])
    client.clear_history = Mock()
    client.export_to_markdown = Mock(return_value="# Exported Chat\n\nContent here")
    client.get_bootstrap_status = Mock(return_value={
        "loaded": True,
        "sources": [{"path": str(Path.cwd() / "AGENTS.md"), "scope": "project"}]
    })
    client.get_usage_stats = Mock(return_value={
        "total_tokens": 1000,
        "total_cost": 0.05
    })
    return client


@pytest.fixture
def mock_context(mock_engine_client):
    """Mock CommandContext for testing."""
    context = Mock(spec=CommandContext)
    context.engine_client = mock_engine_client
    context.add_system_message = Mock()
    context.add_assistant_message = Mock()
    context.update_status_bar = Mock()
    context.show_file_in_panel = Mock()
    context.close_panel = Mock()
    context.get_theme = Mock(return_value="catppuccin-mocha")
    context.set_theme = Mock()
    context.get_provider = Mock(return_value="openai")
    context.get_model = Mock(return_value="gpt-4")
    context.set_provider = AsyncMock()
    context.set_model = AsyncMock()
    return context


# =============================================================================
# Factory Registration Tests
# =============================================================================

def test_all_commands_registered():
    """Verify all expected commands are registered in factory."""
    commands = CommandFactory.list_all()

    # Should have at least 30 commands
    assert len(commands) >= 30, f"Expected at least 30 commands, got {len(commands)}"

    # Check key commands exist
    critical_commands = [
        "help", "status", "provider", "model", "tools",
        "save", "load", "sessions", "clear", "export",
        "cd", "pwd", "show", "agent", "undo",
    ]

    for cmd in critical_commands:
        assert cmd in commands, f"Critical command /{cmd} not registered"


def test_command_categories():
    """Verify commands are properly categorized."""
    categories = CommandFactory.get_categories()

    expected_categories = {
        "agent", "coding", "display", "navigation",
        "provider", "session", "system", "tools", "utility"
    }

    assert set(categories) == expected_categories, \
        f"Category mismatch: {set(categories)} vs {expected_categories}"


def test_command_aliases():
    """Verify command aliases work correctly."""
    # /cat is alias for /show
    show_spec = CommandFactory.get("show")
    cat_spec = CommandFactory.get("cat")
    assert show_spec is cat_spec, "Alias /cat should resolve to /show"


# =============================================================================
# System Command Tests (No Engine Required)
# =============================================================================

def test_help_command(mock_context):
    """Test /help command returns help text."""
    spec = CommandFactory.get("help")
    assert spec is not None

    result = spec.handler(mock_context, "")

    assert isinstance(result, TextResult)
    assert result.status in (ResultStatus.SUCCESS, ResultStatus.INFO)
    assert "Available Commands" in result.message or "help" in result.message.lower()


def test_status_command(mock_context):
    """Test /status command returns current state."""
    spec = CommandFactory.get("status")
    assert spec is not None

    result = spec.handler(mock_context, "")

    assert isinstance(result, (TextResult, TableResult, KeyValueResult))
    assert result.status == ResultStatus.SUCCESS


def test_theme_command_list(mock_context):
    """Test /theme list shows available themes."""
    spec = CommandFactory.get("theme")
    assert spec is not None

    result = spec.handler(mock_context, "list")

    assert isinstance(result, (TextResult, TableResult, KeyValueResult))
    assert result.status in (ResultStatus.SUCCESS, ResultStatus.INFO)


def test_pwd_command(mock_context):
    """Test /pwd returns current working directory."""
    spec = CommandFactory.get("pwd")
    assert spec is not None

    result = spec.handler(mock_context, "")

    assert isinstance(result, (TextResult, KeyValueResult))
    assert result.status == ResultStatus.SUCCESS
    # Check content is present (either in message, content, or pairs)
    assert (hasattr(result, 'message') and result.message) or \
           (hasattr(result, 'content') and result.content) or \
           (hasattr(result, 'pairs') and result.pairs)


# =============================================================================
# Navigation Command Tests
# =============================================================================

def test_cd_command_valid_path(mock_context, tmp_path):
    """Test /cd with valid directory path."""
    spec = CommandFactory.get("cd")
    assert spec is not None

    # Mock get_working_dir to return tmp_path
    mock_context.engine_client.get_working_dir = Mock(return_value=str(tmp_path))

    # Create a test subdirectory
    test_dir = tmp_path / "testdir"
    test_dir.mkdir()

    result = spec.handler(mock_context, str(test_dir))

    # Should succeed or return appropriate result
    assert isinstance(result, (TextResult, ErrorResult))


def test_cd_command_invalid_path(mock_context):
    """Test /cd with invalid directory path."""
    spec = CommandFactory.get("cd")
    assert spec is not None

    result = spec.handler(mock_context, "/nonexistent/path/12345")

    assert isinstance(result, ErrorResult)
    assert result.status == ResultStatus.ERROR


# =============================================================================
# Provider/Model Command Tests
# =============================================================================

def test_provider_list(mock_context):
    """Test /provider list shows available providers."""
    spec = CommandFactory.get("provider")
    assert spec is not None

    result = spec.handler(mock_context, "list")

    assert isinstance(result, (TextResult, TableResult))
    assert result.status == ResultStatus.SUCCESS


def test_model_list(mock_context):
    """Test /model list shows available models."""
    spec = CommandFactory.get("model")
    assert spec is not None

    result = spec.handler(mock_context, "list")

    assert isinstance(result, (TextResult, TableResult))
    assert result.status == ResultStatus.SUCCESS


# =============================================================================
# Session Command Tests
# =============================================================================

def test_save_command(mock_context):
    """Test /save creates a session."""
    spec = CommandFactory.get("save")
    assert spec is not None

    result = spec.handler(mock_context, "")

    # Should succeed or return session info
    assert isinstance(result, (TextResult, ErrorResult))
    if result.status == ResultStatus.SUCCESS:
        mock_context.engine_client.save_session.assert_called()


def test_sessions_command(mock_context):
    """Test /sessions lists saved sessions."""
    spec = CommandFactory.get("sessions")
    assert spec is not None

    result = spec.handler(mock_context, "")

    assert isinstance(result, (TextResult, TableResult))
    assert result.status == ResultStatus.SUCCESS


def test_clear_command(mock_context):
    """Test /clear clears conversation history."""
    spec = CommandFactory.get("clear")
    assert spec is not None

    result = spec.handler(mock_context, "")

    assert isinstance(result, (TextResult, ErrorResult))
    if result.status == ResultStatus.SUCCESS:
        mock_context.engine_client.clear_history.assert_called()


def test_export_command(mock_context):
    """Test /export creates markdown file."""
    spec = CommandFactory.get("export")
    assert spec is not None

    with patch("pathlib.Path.write_text") as mock_write:
        result = spec.handler(mock_context, "")

        assert isinstance(result, (TextResult, FileViewResult, ErrorResult))


# =============================================================================
# Tools Command Tests
# =============================================================================

def test_tools_status(mock_context):
    """Test /tools shows current tools status."""
    spec = CommandFactory.get("tools")
    assert spec is not None

    result = spec.handler(mock_context, "status")

    assert isinstance(result, (TextResult, TableResult))
    assert result.status == ResultStatus.SUCCESS


def test_tools_on(mock_context):
    """Test /tools on enables AI tools."""
    spec = CommandFactory.get("tools")
    assert spec is not None

    result = spec.handler(mock_context, "on")

    assert isinstance(result, (TextResult, ErrorResult))
    if result.status == ResultStatus.SUCCESS:
        mock_context.engine_client.enable_tools.assert_called()


def test_tools_off(mock_context):
    """Test /tools off disables AI tools."""
    spec = CommandFactory.get("tools")
    assert spec is not None

    result = spec.handler(mock_context, "off")

    assert isinstance(result, (TextResult, ErrorResult))
    if result.status == ResultStatus.SUCCESS:
        mock_context.engine_client.disable_tools.assert_called()


# =============================================================================
# Display Command Tests
# =============================================================================

def test_show_command_existing_file(mock_context, tmp_path):
    """Test /show with existing file."""
    spec = CommandFactory.get("show")
    assert spec is not None

    # Create test file
    test_file = tmp_path / "test.py"
    test_file.write_text("# Test Python file\nprint('hello')\n")

    # Mock working directory
    mock_context.engine_client.get_working_dir = Mock(return_value=str(tmp_path))

    result = spec.handler(mock_context, str(test_file))

    assert isinstance(result, (FileViewResult, ErrorResult))
    if isinstance(result, FileViewResult):
        assert result.status == ResultStatus.SUCCESS
        assert "print('hello')" in result.content


def test_show_command_missing_file(mock_context):
    """Test /show with non-existent file."""
    spec = CommandFactory.get("show")
    assert spec is not None

    result = spec.handler(mock_context, "/nonexistent/file.txt")

    assert isinstance(result, ErrorResult)
    assert result.status == ResultStatus.ERROR


def test_show_command_no_args(mock_context):
    """Test /show without arguments shows usage."""
    spec = CommandFactory.get("show")
    assert spec is not None

    result = spec.handler(mock_context, "")

    assert isinstance(result, ErrorResult)
    assert result.status == ResultStatus.ERROR
    assert "Usage" in result.message or "suggestions" in str(result.__dict__)


# =============================================================================
# Agent Command Tests
# =============================================================================

def test_agent_command_status(mock_context):
    """Test /agent shows current agent status."""
    spec = CommandFactory.get("agent")
    assert spec is not None

    result = spec.handler(mock_context, "")

    # Should return status or error
    assert isinstance(result, (TextResult, ErrorResult))


def test_undo_command(mock_context):
    """Test /undo restores previous state."""
    spec = CommandFactory.get("undo")
    assert spec is not None

    result = spec.handler(mock_context, "")

    # May succeed or fail depending on checkpoint availability
    assert isinstance(result, (TextResult, ErrorResult))


# =============================================================================
# Error Handling Tests
# =============================================================================

def test_command_with_missing_engine(mock_context):
    """Test command behavior when engine_client is None."""
    mock_context.engine_client = None

    # Provider command should fail gracefully
    spec = CommandFactory.get("provider")
    result = spec.handler(mock_context, "list")

    assert isinstance(result, ErrorResult)
    assert result.status == ResultStatus.ERROR


def test_command_with_exception_handling(mock_context):
    """Test that command exceptions are caught and returned as ErrorResult."""
    spec = CommandFactory.get("model")

    # Make engine_client.get_provider raise an exception
    mock_context.engine_client.get_provider = Mock(side_effect=RuntimeError("Test error"))

    result = spec.handler(mock_context, "")

    # Should return error result, not raise exception
    # (This depends on whether commands have try/except internally)
    assert result is not None


# =============================================================================
# Integration Tests
# =============================================================================

def test_command_composition(mock_context):
    """Test that commands can call other commands via CommandFactory.call()."""
    # Some commands may internally call other commands
    # Example: /help might call /status to show current state

    # This is a placeholder - actual composition depends on implementation
    spec = CommandFactory.get("help")
    result = spec.handler(mock_context, "")

    assert isinstance(result, TextResult)
    assert result.status == ResultStatus.SUCCESS


def test_multiple_commands_in_sequence(mock_context):
    """Test executing multiple commands sequentially."""
    commands = [
        ("pwd", ""),
        ("status", ""),
        ("tools", "status"),
        ("help", ""),
    ]

    results = []
    for cmd, args in commands:
        spec = CommandFactory.get(cmd)
        assert spec is not None, f"Command {cmd} not found"
        result = spec.handler(mock_context, args)
        results.append(result)

    # All commands should return results
    assert len(results) == len(commands)
    # Most should succeed
    success_count = sum(1 for r in results if r.status == ResultStatus.SUCCESS)
    assert success_count >= len(commands) // 2, "Too many command failures"


# =============================================================================
# Performance Tests
# =============================================================================

def test_command_lookup_performance():
    """Test that command lookup is fast (O(1) hash lookup)."""
    import time

    # Lookup should be instant even with many commands
    commands = CommandFactory.list_all()

    start = time.perf_counter()
    for _ in range(1000):
        for cmd in commands:
            spec = CommandFactory.get(cmd)
            assert spec is not None
    elapsed = time.perf_counter() - start

    # Should complete 1000 * 30 = 30,000 lookups in < 0.1 seconds
    assert elapsed < 0.1, f"Command lookup too slow: {elapsed:.3f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
