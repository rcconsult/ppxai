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

    def test_parse_doubly_nested_tool_call(self, engine_client):
        """Test parsing doubly nested tool call structure.

        v1.13.2: Some models (e.g., GPT-OSS 120B via vLLM) output tool calls
        with nested structure like:
        {"tool": "apply_patch", "arguments": {"tool": "apply_patch", "arguments": {...actual args...}}}

        This should be unwrapped to extract the actual arguments.
        """
        # Mock tool for apply_patch
        mock_tool = Mock()
        mock_tool.name = "apply_patch"
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "unified_diff": {"type": "string"}
            },
            "required": ["file_path", "unified_diff"]
        }
        engine_client.tool_manager.get_tool = Mock(return_value=mock_tool)

        # This is the problematic format from GPT-OSS 120B
        text = '''{
  "tool": "apply_patch",
  "arguments": {
    "tool": "apply_patch",
    "arguments": {
      "file_path": "C:\\\\test.ps1",
      "unified_diff": "*** Begin Patch\\n*** End Patch"
    }
  }
}'''

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "apply_patch"
        # The nested structure should be unwrapped
        assert "file_path" in result["arguments"]
        assert result["arguments"]["file_path"] == "C:\\test.ps1"
        assert "unified_diff" in result["arguments"]
        # Should NOT have nested tool/arguments keys
        assert "tool" not in result["arguments"]

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


class TestVLLMToolCallInference:
    """Test tool call inference for vLLM-served models that output raw JSON without 'tool' key.

    These tests validate the dispatcher pattern for inferring tools from argument patterns.
    This is critical for making vLLM endpoints work with ppxai tools.
    """

    @pytest.fixture
    def engine_client(self):
        """Create an EngineClient with real tool registration for inference testing."""
        from ppxai.engine.client import EngineClient

        engine = EngineClient()

        # Register actual tools so inference can match against them
        def mock_tool_getter(name):
            """Return mock tools for known tool names."""
            tools = {
                "web_search": Mock(
                    name="web_search",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "num_results": {"type": "integer"}
                        },
                        "required": ["query"]
                    }
                ),
                "read_file": Mock(
                    name="read_file",
                    parameters={
                        "type": "object",
                        "properties": {
                            "filepath": {"type": "string"},
                            "max_lines": {"type": "integer"}
                        },
                        "required": ["filepath"]
                    }
                ),
                "list_directory": Mock(
                    name="list_directory",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "format": {"type": "string"}
                        },
                        "required": []
                    }
                ),
                "execute_shell_command": Mock(
                    name="execute_shell_command",
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "working_dir": {"type": "string"}
                        },
                        "required": ["command"]
                    }
                ),
                "fetch_url": Mock(
                    name="fetch_url",
                    parameters={
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "max_length": {"type": "integer"}
                        },
                        "required": ["url"]
                    }
                ),
                "get_weather": Mock(
                    name="get_weather",
                    parameters={
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "format": {"type": "string"}
                        },
                        "required": ["location"]
                    }
                ),
                "calculator": Mock(
                    name="calculator",
                    parameters={
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string"}
                        },
                        "required": ["expression"]
                    }
                ),
            }
            return tools.get(name)

        engine.tool_manager.get_tool = mock_tool_getter
        return engine

    def test_infer_web_search_with_num_results(self, engine_client):
        """Test inferring web_search from raw JSON with num_results (vLLM GPT-OSS output)."""
        # This is the exact format that GPT-OSS 120B outputs via vLLM
        text = '{"query": "ppxai utils repository", "num_results": 10}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "web_search"
        assert result["arguments"]["query"] == "ppxai utils repository"
        assert result["arguments"]["num_results"] == 10

    def test_infer_web_search_with_top_n(self, engine_client):
        """Test inferring web_search with top_n alias."""
        text = '{"query": "Python tutorials", "top_n": 5}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "web_search"
        assert result["arguments"]["query"] == "Python tutorials"
        # top_n should be normalized to num_results
        assert result["arguments"]["num_results"] == 5

    def test_infer_web_search_query_only(self, engine_client):
        """Test inferring web_search with just query parameter."""
        text = '{"query": "how to use vLLM"}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "web_search"
        assert result["arguments"]["query"] == "how to use vLLM"

    def test_infer_read_file_with_filepath(self, engine_client):
        """Test inferring read_file from filepath parameter."""
        text = '{"filepath": "/home/user/code.py", "max_lines": 100}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "read_file"
        assert result["arguments"]["filepath"] == "/home/user/code.py"

    def test_infer_read_file_with_path_alias(self, engine_client):
        """Test inferring read_file with path alias (normalized to filepath)."""
        text = '{"path": "/etc/hosts"}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "read_file"
        # path should be normalized to filepath
        assert result["arguments"]["filepath"] == "/etc/hosts"

    def test_infer_list_directory(self, engine_client):
        """Test inferring list_directory from path/format combo."""
        text = '{"path": "/home/user", "format": "detailed"}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "list_directory"
        assert result["arguments"]["path"] == "/home/user"

    def test_infer_execute_shell_command(self, engine_client):
        """Test inferring execute_shell_command from command parameter."""
        text = '{"command": "ls -la", "working_dir": "/tmp"}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        assert result["arguments"]["command"] == "ls -la"

    def test_infer_fetch_url(self, engine_client):
        """Test inferring fetch_url from url parameter."""
        text = '{"url": "https://example.com", "max_length": 5000}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "fetch_url"
        assert result["arguments"]["url"] == "https://example.com"

    def test_infer_get_weather(self, engine_client):
        """Test inferring get_weather from location parameter."""
        text = '{"location": "San Francisco"}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "get_weather"
        assert result["arguments"]["location"] == "San Francisco"

    def test_infer_calculator(self, engine_client):
        """Test inferring calculator from expression parameter."""
        text = '{"expression": "2 + 2 * 3"}'

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "calculator"
        assert result["arguments"]["expression"] == "2 + 2 * 3"

    def test_no_inference_for_unknown_keys(self, engine_client):
        """Test that unknown key combinations return None."""
        text = '{"foo": "bar", "baz": 123}'

        result = engine_client._parse_tool_call(text)

        assert result is None

    def test_no_inference_with_tool_key_present(self, engine_client):
        """Test that inference is skipped when tool key is already present."""
        # Should use normalize_tool_call instead
        text = '{"tool": "web_search", "query": "test"}'

        result = engine_client._parse_tool_call(text)

        # normalize_tool_call should handle this
        assert result is not None
        assert result["tool"] == "web_search"

    def test_infer_from_code_block(self, engine_client):
        """Test tool inference works inside markdown code blocks."""
        text = '''```json
{"query": "AI coding tools 2025", "num_results": 5}
```'''

        result = engine_client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "web_search"
        assert result["arguments"]["query"] == "AI coding tools 2025"


class TestNativeToolCalling:
    """Test native OpenAI-style tool calling for vLLM with --enable-auto-tool-choice.

    These tests validate the provider-level tool calling that bypasses prompt-based parsing.
    """

    @pytest.fixture
    def tool_manager(self):
        """Create a tool manager with some tools registered."""
        from ppxai.engine.tools.manager import ToolManager
        from ppxai.engine.tools.base import FunctionTool

        manager = ToolManager()

        # Register web_search tool
        async def web_search_handler(query: str, num_results: int = 5):
            return f"Search results for: {query}"

        web_search = FunctionTool(
            name="web_search",
            description="Search the web for information",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num_results": {"type": "integer", "description": "Number of results"}
                },
                "required": ["query"]
            },
            handler=web_search_handler
        )
        manager.register_tool(web_search)

        # Register read_file tool
        async def read_file_handler(filepath: str, max_lines: int = None):
            return f"Contents of: {filepath}"

        read_file = FunctionTool(
            name="read_file",
            description="Read a file from the filesystem",
            parameters={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to file"},
                    "max_lines": {"type": "integer", "description": "Max lines to read"}
                },
                "required": ["filepath"]
            },
            handler=read_file_handler
        )
        manager.register_tool(read_file)

        return manager

    def test_get_tools_openai_format(self, tool_manager):
        """Test that tools are correctly formatted for OpenAI API."""
        tools = tool_manager.get_tools_openai_format()

        assert len(tools) == 2

        # Check format structure
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

        # Check web_search tool
        web_search = next(t for t in tools if t["function"]["name"] == "web_search")
        assert web_search["function"]["description"] == "Search the web for information"
        assert "query" in web_search["function"]["parameters"]["properties"]

    def test_get_tools_openai_format_empty(self):
        """Test that empty tool manager returns empty list."""
        from ppxai.engine.tools.manager import ToolManager

        manager = ToolManager()
        tools = manager.get_tools_openai_format()

        assert tools == []

    def test_provider_capabilities_native_tool_calling(self):
        """Test that ProviderCapabilities includes native_tool_calling flag."""
        from ppxai.engine.types import ProviderCapabilities

        # Default is False
        caps = ProviderCapabilities()
        assert caps.native_tool_calling is False

        # Can be enabled
        caps = ProviderCapabilities(native_tool_calling=True)
        assert caps.native_tool_calling is True

        # Works with from_dict
        caps = ProviderCapabilities.from_dict({"native_tool_calling": True})
        assert caps.native_tool_calling is True

    def test_openai_provider_default_no_native_tools(self):
        """Test that OpenAI provider defaults to no native tool calling."""
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        assert OpenAICompatibleProvider.default_capabilities.native_tool_calling is False

    @pytest.mark.asyncio
    async def test_openai_provider_handles_tool_calls_in_response(self):
        """Test that OpenAI provider correctly parses tool_calls from response."""
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
        from ppxai.engine.types import EventType, ProviderCapabilities, Message
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace

        # Create provider with native tool calling enabled
        caps = ProviderCapabilities(native_tool_calling=True)
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="http://localhost:8000/v1",
            capabilities=caps
        )

        # Mock the OpenAI client response with tool calls using SimpleNamespace
        # to avoid MagicMock's .name attribute interference
        mock_function = SimpleNamespace(
            name="web_search",
            arguments='{"query": "test query", "num_results": 5}'
        )
        mock_tool_call = SimpleNamespace(
            id="call_123",
            function=mock_function
        )
        mock_message = SimpleNamespace(
            content="",
            tool_calls=[mock_tool_call]
        )
        mock_choice = SimpleNamespace(message=mock_message)
        mock_usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        mock_response = SimpleNamespace(
            choices=[mock_choice],
            usage=mock_usage
        )

        with patch.object(provider.client.chat.completions, 'create', return_value=mock_response):
            events = []
            async for event in provider.chat(
                [Message("user", "Search for something")],
                model="gpt-oss-120b",
                stream=False,
                tools=[{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
            ):
                events.append(event)

        # Should have STREAM_START, TOOL_CALL, STREAM_END
        event_types = [e.type for e in events]
        assert EventType.STREAM_START in event_types
        assert EventType.TOOL_CALL in event_types
        assert EventType.STREAM_END in event_types

        # Check tool call event
        tool_call_event = next(e for e in events if e.type == EventType.TOOL_CALL)
        assert tool_call_event.data["tool"] == "web_search"
        assert tool_call_event.data["arguments"]["query"] == "test query"
        assert tool_call_event.data["native"] is True
        assert tool_call_event.data["tool_call_id"] == "call_123"

    @pytest.mark.asyncio
    async def test_openai_provider_no_tools_without_capability(self):
        """Test that tools are not sent when native_tool_calling is disabled."""
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
        from ppxai.engine.types import ProviderCapabilities, Message
        from unittest.mock import MagicMock, patch

        # Create provider WITHOUT native tool calling
        caps = ProviderCapabilities(native_tool_calling=False)
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="http://localhost:8000/v1",
            capabilities=caps
        )

        # Mock the OpenAI client
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Regular response"
        mock_message.tool_calls = None
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20, total_tokens=30)

        create_mock = MagicMock(return_value=mock_response)
        with patch.object(provider.client.chat.completions, 'create', create_mock):
            events = []
            async for event in provider.chat(
                [Message("user", "Hello")],
                model="gpt-4",
                stream=False,
                tools=[{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
            ):
                events.append(event)

        # Verify tools were NOT passed (because native_tool_calling is False)
        call_kwargs = create_mock.call_args[1]
        assert "tools" not in call_kwargs or call_kwargs.get("tools") is None
