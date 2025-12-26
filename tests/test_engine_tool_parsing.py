"""
Tests for EngineClient tool call parsing.

Ensures the engine correctly parses tool calls from various model outputs,
including the Gemini-style nested JSON format.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import json


class TestEngineToolCallParsing:
    """Test EngineClient._parse_tool_call method."""

    @pytest.fixture
    def engine_client(self):
        """Create an EngineClient with mock tool manager."""
        from ppxai.engine.client import EngineClient

        engine = EngineClient()

        # Mock tool manager to return a tool
        mock_tool = Mock()
        mock_tool.name = "execute_shell_command"
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "working_dir": {"type": "string"}
            },
            "required": ["command"]
        }

        engine.tool_manager.get_tool = Mock(return_value=mock_tool)
        return engine

    def test_parse_simple_json_tool_call(self, engine_client):
        """Test parsing a simple JSON tool call."""
        text = '{"tool": "execute_shell_command", "arguments": {"command": "ls"}}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        assert result["arguments"]["command"] == "ls"

    def test_parse_nested_json_tool_call(self, engine_client):
        """Test parsing nested JSON (Gemini-style) tool call.

        This is the critical test for the Gemini fix - ensures nested
        braces in arguments are handled correctly.
        """
        # Gemini often returns tool calls with nested objects
        text = '''{
  "tool": "execute_shell_command",
  "arguments": {
    "command": "printf 'print(\\\"Hello\\\")' > /tmp/hello.py && python3 /tmp/hello.py",
    "working_dir": "/tmp"
  }
}'''

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        assert "command" in result["arguments"]
        assert "working_dir" in result["arguments"]
        assert result["arguments"]["working_dir"] == "/tmp"

    def test_parse_tool_call_in_code_block(self, engine_client):
        """Test parsing tool call inside markdown code block."""
        text = '''Here's what I'll do:

```json
{
  "tool": "execute_shell_command",
  "arguments": {
    "command": "echo hello"
  }
}
```

This will print hello.'''

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        assert result["arguments"]["command"] == "echo hello"

    def test_parse_tool_call_with_text_before_and_after(self, engine_client):
        """Test parsing tool call with surrounding text."""
        text = '''I'll execute a shell command.

{"tool": "execute_shell_command", "arguments": {"command": "pwd"}}

This will show the current directory.'''

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"

    def test_parse_flat_format_tool_call(self, engine_client):
        """Test parsing flat format (parameters at top level, not in arguments)."""
        text = '{"tool": "execute_shell_command", "command": "ls -la"}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        # The normalize function should move command to arguments
        assert "arguments" in result
        assert result["arguments"]["command"] == "ls -la"

    def test_parse_no_tool_call(self, engine_client):
        """Test that regular text returns None."""
        text = "Here's how to list files: use the ls command."

        result = engine_client._parse_tool_call(text)

        assert result is None

    def test_parse_invalid_json(self, engine_client):
        """Test that invalid JSON returns None."""
        text = '{"tool": "execute_shell_command", "arguments": {'

        result = engine_client._parse_tool_call(text)

        assert result is None

    def test_parse_unknown_tool(self, engine_client):
        """Test that unknown tool returns None."""
        engine_client.tool_manager.get_tool = Mock(return_value=None)

        text = '{"tool": "unknown_tool", "arguments": {"foo": "bar"}}'

        result = engine_client._parse_tool_call(text)

        assert result is None

    def test_parse_deeply_nested_json(self, engine_client):
        """Test parsing deeply nested JSON structures."""
        text = '''{
  "tool": "execute_shell_command",
  "arguments": {
    "command": "echo '{\\"nested\\": {\\"deeply\\": true}}'",
    "working_dir": "/home/user"
  }
}'''

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"


class TestEngineToolCallWithCodeBlocks:
    """Test tool call parsing with various code block formats."""

    @pytest.fixture
    def engine_client(self):
        """Create an EngineClient with mock tool manager."""
        from ppxai.engine.client import EngineClient

        engine = EngineClient()

        mock_tool = Mock()
        mock_tool.name = "read_file"
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"}
            },
            "required": ["file_path"]
        }

        engine.tool_manager.get_tool = Mock(return_value=mock_tool)
        return engine

    def test_parse_json_code_block(self, engine_client):
        """Test parsing ```json code block."""
        text = '''```json
{"tool": "read_file", "arguments": {"file_path": "/etc/hosts"}}
```'''

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "read_file"

    def test_parse_plain_code_block(self, engine_client):
        """Test parsing ``` code block without language."""
        text = '''```
{"tool": "read_file", "arguments": {"file_path": "/etc/passwd"}}
```'''

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "read_file"
