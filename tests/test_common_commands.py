"""
Tests for ppxai/common/commands.py

Tests the CommandHandler class and CommandResult.
"""

import pytest
from unittest.mock import Mock
from ppxai.common.commands import CommandHandler, CommandResult, CommandStatus


def test_parse_command_simple():
    """Test parsing simple command."""
    handler = CommandHandler()
    command, args = handler.parse_command("/help")

    assert command == "help"
    assert args == ""


def test_parse_command_with_args():
    """Test parsing command with arguments."""
    handler = CommandHandler()
    command, args = handler.parse_command("/tools enable")

    assert command == "tools"
    assert args == "enable"


def test_parse_command_multi_word_args():
    """Test parsing command with multi-word arguments."""
    handler = CommandHandler()
    command, args = handler.parse_command("/save my session name")

    assert command == "save"
    assert args == "my session name"


def test_command_result_to_dict():
    """Test CommandResult serialization."""
    result = CommandResult(
        status=CommandStatus.SUCCESS,
        message="Operation successful",
        data={"count": 5}
    )

    result_dict = result.to_dict()

    assert result_dict["status"] == "success"
    assert result_dict["message"] == "Operation successful"
    assert result_dict["data"]["count"] == 5


def test_execute_unknown_command():
    """Test executing unknown command returns error."""
    handler = CommandHandler()
    result = handler.execute("/unknown")

    assert result.status == CommandStatus.ERROR
    assert "Unknown command" in result.message


def test_execute_quit_command():
    """Test quit command."""
    handler = CommandHandler()
    result = handler.execute("/quit")

    assert result.status == CommandStatus.SUCCESS
    assert result.data["action"] == "quit"


def test_execute_help_command():
    """Test help command returns commands list."""
    handler = CommandHandler()
    result = handler.execute("/help")

    assert result.status == CommandStatus.INFO
    assert "commands" in result.data
    assert "/help" in result.data["commands"]
    assert "/tools" in result.data["commands"]


def test_execute_clear_command_with_callback():
    """Test clear command with callback."""
    clear_called = []
    callbacks = {"clear_session": lambda: clear_called.append(True)}

    handler = CommandHandler(callbacks=callbacks)
    result = handler.execute("/clear")

    assert result.status == CommandStatus.SUCCESS
    assert len(clear_called) == 1


def test_execute_save_command_with_callback():
    """Test save command with callback."""
    callbacks = {"save_session": lambda: "/path/to/session.json"}

    handler = CommandHandler(callbacks=callbacks)
    result = handler.execute("/save")

    assert result.status == CommandStatus.SUCCESS
    assert "filepath" in result.data


def test_execute_save_command_without_callback():
    """Test save command without callback returns error."""
    handler = CommandHandler()
    result = handler.execute("/save")

    assert result.status == CommandStatus.ERROR
    assert "not available" in result.message.lower()


def test_execute_tools_enable():
    """Test tools enable command."""
    mock_engine = Mock()
    mock_engine.enable_tools = Mock()

    handler = CommandHandler(engine_client=mock_engine)
    result = handler.execute("/tools enable")

    assert result.status == CommandStatus.SUCCESS
    mock_engine.enable_tools.assert_called_once()


def test_execute_tools_disable():
    """Test tools disable command."""
    mock_engine = Mock()
    mock_engine.disable_tools = Mock()

    handler = CommandHandler(engine_client=mock_engine)
    result = handler.execute("/tools disable")

    assert result.status == CommandStatus.SUCCESS
    mock_engine.disable_tools.assert_called_once()


def test_execute_tools_status():
    """Test tools status command."""
    mock_engine = Mock()
    mock_engine.tools_enabled = True
    mock_engine.list_tools = Mock(return_value=[])

    handler = CommandHandler(engine_client=mock_engine)
    result = handler.execute("/tools status")

    assert result.status == CommandStatus.INFO
    assert result.data["enabled"] is True


def test_execute_tools_list():
    """Test tools list command."""
    mock_tool = Mock()
    mock_tool.to_dict = Mock(return_value={"name": "test_tool"})

    mock_engine = Mock()
    mock_engine.list_tools = Mock(return_value=[mock_tool])

    handler = CommandHandler(engine_client=mock_engine)
    result = handler.execute("/tools list")

    assert result.status == CommandStatus.INFO
    assert "tools" in result.data
    assert len(result.data["tools"]) == 1


def test_execute_model_list():
    """Test model list command."""
    mock_engine = Mock()
    mock_engine.list_models = Mock(return_value=["model1", "model2"])
    mock_engine.model = "model1"

    handler = CommandHandler(engine_client=mock_engine)
    result = handler.execute("/model list")

    assert result.status == CommandStatus.INFO
    assert "models" in result.data
    assert result.data["current"] == "model1"


def test_execute_model_switch():
    """Test model switch command."""
    mock_engine = Mock()
    mock_engine.set_model = Mock()

    handler = CommandHandler(engine_client=mock_engine)
    result = handler.execute("/model sonar-pro")

    assert result.status == CommandStatus.SUCCESS
    mock_engine.set_model.assert_called_once_with("sonar-pro")


def test_execute_provider_list():
    """Test provider list command."""
    mock_engine = Mock()
    mock_engine.list_providers = Mock(return_value=["perplexity", "openai"])
    mock_engine.provider_name = "perplexity"

    handler = CommandHandler(engine_client=mock_engine)
    result = handler.execute("/provider list")

    assert result.status == CommandStatus.INFO
    assert "providers" in result.data
    assert result.data["current"] == "perplexity"


def test_execute_debug_log_on():
    """Test debug-log on command."""
    handler = CommandHandler()
    result = handler.execute("/debug-log on")

    assert result.status == CommandStatus.SUCCESS
    assert "enabled" in result.message.lower()


def test_execute_debug_log_off():
    """Test debug-log off command."""
    handler = CommandHandler()
    result = handler.execute("/debug-log off")

    assert result.status == CommandStatus.SUCCESS
    assert "disabled" in result.message.lower()


def test_execute_debug_log_status():
    """Test debug-log status command."""
    handler = CommandHandler()
    result = handler.execute("/debug-log status")

    assert result.status == CommandStatus.INFO
    assert "enabled" in result.data
