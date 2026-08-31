"""
Tests for EngineClient tool call parsing.

Ensures the engine correctly parses tool calls from various model outputs,
including the Gemini-style nested JSON format.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import json

from ppxai.engine.tools.parser import (
    _find_json_objects,
    parse_tool_call,
    strip_tool_json_from_text,
    detect_truncated_tool_call,
)


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


class TestNativeToolCallNesting:
    """Test native tool call argument unwrapping in EngineClient.

    v1.13.10: Some models (e.g., GPT-OSS 120B via vLLM) send native tool calls
    with nested structure where arguments contain another {"tool": ..., "arguments": {...}}.
    This should be unwrapped before execution.
    """

    def test_native_tool_call_nested_arguments_unwrapped(self):
        """Test that nested native tool call arguments are unwrapped correctly.

        This tests the fix at line ~1277-1282 in client.py where native tool call
        arguments are checked for nested structure and unwrapped.
        """
        from ppxai.engine.client import EngineClient

        # Create engine with mock tool
        engine = EngineClient()

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
        engine.tool_manager.get_tool = Mock(return_value=mock_tool)

        # Simulate what the chat() method does with native tool calls
        # This is the problematic format from GPT-OSS 120B via vLLM
        native_tool_call = {
            "tool": "apply_patch",
            "arguments": {
                "tool": "apply_patch",
                "arguments": {
                    "file_path": "/test/file.py",
                    "unified_diff": "--- a\n+++ b\n"
                }
            }
        }

        # Extract and unwrap arguments (mimic the fix in client.py)
        tool_args = native_tool_call.get("arguments", {})
        if isinstance(tool_args, dict) and "tool" in tool_args and "arguments" in tool_args:
            tool_args = tool_args["arguments"]

        # Verify the unwrapping worked
        assert "file_path" in tool_args
        assert tool_args["file_path"] == "/test/file.py"
        assert "unified_diff" in tool_args
        assert "tool" not in tool_args  # Should NOT have nested tool key

    def test_native_tool_call_normal_arguments_unchanged(self):
        """Test that normal (non-nested) native tool call arguments pass through unchanged."""
        # Normal structure - should not be modified
        native_tool_call = {
            "tool": "read_file",
            "arguments": {
                "filepath": "/etc/hosts",
                "max_lines": 100
            }
        }

        tool_args = native_tool_call.get("arguments", {})
        if isinstance(tool_args, dict) and "tool" in tool_args and "arguments" in tool_args:
            tool_args = tool_args["arguments"]

        # Should remain unchanged
        assert "filepath" in tool_args
        assert tool_args["filepath"] == "/etc/hosts"
        assert tool_args["max_lines"] == 100


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

    def test_tool_mode_is_a_model_fact_not_an_endpoint_one(self):
        """RETARGETED — the premise moved records (ADR 0012 section 2 Q0a/Q0g).

        This asserted `ProviderCapabilities.native_tool_calling` defaulted
        False, could be enabled, and round-tripped through `from_dict`. The
        field is gone from that record: tool calling is a fact about a
        MODEL, and keeping it on the endpoint record is what let a
        provider-wide statement speak for `sonar` (debt Item 43).

        The three properties it checked all survive, on `ModelFacts`:
        a conservative default, the ability to state otherwise, and
        round-tripping through config.
        """
        from ppxai.engine.model_facts import ModelFacts, apply_overrides
        from ppxai.engine.types import ProviderCapabilities

        # The boolean is DELETED, not aliased — a readable alias is how the
        # seam bug survived review in the first place.
        assert not hasattr(ProviderCapabilities(), "native_tool_calling")
        assert "native_tool_calling" not in ProviderCapabilities.from_dict(
            {"native_tool_calling": True}
        ).__dict__

        # Conservative default: an unmeasured model degrades, never 400s.
        assert ModelFacts().tool_mode == "prompt_based"

        # Statable, and round-trips through the config vocabulary.
        assert apply_overrides(
            ModelFacts(), {"tool_mode": "native"}
        ).tool_mode == "native"

    def test_openai_provider_default_no_native_tools(self):
        """Test that OpenAI provider defaults to no native tool calling."""
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        # RETARGETED: the endpoint record no longer carries tool calling, so
        # "this provider defaults to no native tools" is now a statement
        # about a MODEL. An unlisted model resolves conservatively.
        assert not hasattr(
            OpenAICompatibleProvider.default_capabilities, "native_tool_calling"
        )
        p = OpenAICompatibleProvider(
            api_key="k", base_url="http://localhost:8000/v1"
        )
        assert p.get_facts_for_model("some-unlisted-model").tool_mode == (
            "prompt_based"
        )

    @pytest.mark.asyncio
    async def test_openai_provider_handles_tool_calls_in_response(self):
        """Test that OpenAI provider correctly parses tool_calls from response."""
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
        from ppxai.engine.types import EventType, ProviderCapabilities, Message
        from unittest.mock import MagicMock
        from types import SimpleNamespace

        # Create provider with native tool calling enabled
        caps = ProviderCapabilities()
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
        from unittest.mock import MagicMock

        # Create provider WITHOUT native tool calling
        caps = ProviderCapabilities()
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


class TestToolArgumentValidation:
    """Test that tool execution validates required arguments.

    v1.13.2: Some models (e.g., GPT-OSS 120B via vLLM) sometimes send empty
    or incomplete arguments. The tool manager should validate and provide
    clear error messages.
    """

    @pytest.fixture
    def tool_manager(self):
        """Create a tool manager with tools that have required arguments."""
        from ppxai.engine.tools.manager import ToolManager
        from ppxai.engine.tools.base import FunctionTool

        manager = ToolManager()

        # Register apply_patch tool with required arguments
        async def apply_patch_handler(file_path: str, unified_diff: str):
            return f"Patched: {file_path}"

        apply_patch = FunctionTool(
            name="apply_patch",
            description="Apply a patch to a file",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file"},
                    "unified_diff": {"type": "string", "description": "Unified diff"}
                },
                "required": ["file_path", "unified_diff"]
            },
            handler=apply_patch_handler
        )
        manager.register_tool(apply_patch)

        # Register read_file tool with one required argument
        async def read_file_handler(filepath: str, max_lines: int = None):
            return f"Contents of: {filepath}"

        read_file = FunctionTool(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to file"},
                    "max_lines": {"type": "integer", "description": "Max lines"}
                },
                "required": ["filepath"]
            },
            handler=read_file_handler
        )
        manager.register_tool(read_file)

        return manager

    @pytest.mark.asyncio
    async def test_execute_tool_with_valid_arguments(self, tool_manager):
        """Test successful execution with all required arguments."""
        result = await tool_manager.execute_tool(
            "apply_patch",
            file_path="/test/file.py",
            unified_diff="--- a\n+++ b\n"
        )
        assert "Patched: /test/file.py" in result

    @pytest.mark.asyncio
    async def test_execute_tool_with_empty_arguments(self, tool_manager):
        """Test that empty arguments raise clear error for apply_patch."""
        with pytest.raises(ValueError) as exc_info:
            await tool_manager.execute_tool("apply_patch")

        error_msg = str(exc_info.value)
        assert "Missing required arguments" in error_msg
        assert "apply_patch" in error_msg
        assert "file_path" in error_msg
        assert "unified_diff" in error_msg

    @pytest.mark.asyncio
    async def test_execute_tool_with_partial_arguments(self, tool_manager):
        """Test that partial arguments raise error listing missing ones."""
        with pytest.raises(ValueError) as exc_info:
            await tool_manager.execute_tool(
                "apply_patch",
                file_path="/test/file.py"
                # missing unified_diff
            )

        error_msg = str(exc_info.value)
        assert "Missing required arguments" in error_msg
        assert "unified_diff" in error_msg
        assert "file_path" not in error_msg  # file_path was provided

    @pytest.mark.asyncio
    async def test_execute_tool_with_optional_missing(self, tool_manager):
        """Test that optional arguments can be omitted."""
        result = await tool_manager.execute_tool(
            "read_file",
            filepath="/etc/hosts"
            # max_lines is optional
        )
        assert "Contents of: /etc/hosts" in result

    @pytest.mark.asyncio
    async def test_execute_tool_all_required_missing(self, tool_manager):
        """Test error when all required arguments are missing."""
        with pytest.raises(ValueError) as exc_info:
            await tool_manager.execute_tool("read_file")

        error_msg = str(exc_info.value)
        assert "Missing required arguments" in error_msg
        assert "filepath" in error_msg

    @pytest.mark.asyncio
    async def test_execute_tool_unexpected_params_filtered(self, tool_manager):
        """Test that unexpected parameters are silently filtered out.

        v1.13.10: Small models sometimes hallucinate parameters that don't
        exist in the tool schema (e.g., 'language' for web_search).
        These should be filtered out instead of causing errors.
        """
        # read_file only accepts 'filepath' and 'max_lines' - 'language' should be filtered
        result = await tool_manager.execute_tool(
            "read_file",
            filepath="/etc/hosts",
            language="en",  # unexpected parameter - should be filtered
            encoding="utf-8"  # another unexpected parameter
        )
        # Should succeed despite unexpected parameters
        assert "Contents of: /etc/hosts" in result


class TestTruncatedToolCallDetection:
    """Tests for detecting truncated/incomplete tool call attempts (v1.15.2).

    GPT-OSS and other models sometimes output "I'll use X tool" followed by
    JSON that gets truncated due to token limits. This detection enables
    targeted retry feedback.
    """

    def test_detect_truncated_json_unclosed_braces(self):
        """Test detection of truncated JSON with unclosed braces."""
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        text = """I'll use the apply_patch tool to fix the issue.
```json
{
  "tool": "apply_patch",
  "arguments": {
    "file_path": "test.py",
    "content": "some very long content that gets cut off"""

        result = detect_truncated_tool_call(text)

        assert result is not None
        assert result["tool"] == "apply_patch"
        assert result["reason"] == "truncated_json"

    def test_detect_no_json_after_intent(self):
        """Test detection when model states intent but outputs no JSON."""
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        text = "I'll use the write_file tool to create the file."

        result = detect_truncated_tool_call(text)

        assert result is not None
        assert result["tool"] == "write_file"
        assert result["reason"] == "no_json"

    def test_detect_unclosed_code_block(self):
        """Test detection of unclosed markdown code block."""
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        text = """I'll use the read_file tool.
```json
{"tool": "read_file", "arguments": {"filepath": "test.py"}}"""

        result = detect_truncated_tool_call(text)

        assert result is not None
        assert result["tool"] == "read_file"
        assert result["reason"] == "likely_truncated"

    def test_no_detection_for_normal_text(self):
        """Test that normal text without tool intent is not flagged."""
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        text = "Here's the answer to your question. The file contains valid data."

        result = detect_truncated_tool_call(text)

        assert result is None

    def test_no_detection_for_complete_tool_call(self):
        """Test that complete tool calls are not flagged as truncated."""
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        text = """I'll use the shell tool.
```json
{"tool": "shell", "arguments": {"command": "ls -la"}}
```
Done."""

        result = detect_truncated_tool_call(text)

        # Should not detect as truncated since JSON is complete
        assert result is None

    def test_detect_various_intent_patterns(self):
        """Test detection of various intent phrase patterns."""
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        patterns = [
            ("I'll use the test_tool tool.", "test_tool"),
            ("I will use test_tool tool now.", "test_tool"),
            ("Let me use the my_function tool.", "my_function"),
            ("Using the helper_tool tool:", "helper_tool"),
        ]

        for text, expected_tool in patterns:
            result = detect_truncated_tool_call(text)
            assert result is not None, f"Failed to detect: {text}"
            assert result["tool"] == expected_tool, f"Wrong tool for: {text}"

    def test_detect_tool_with_underscores(self):
        """Test detection of tools with underscores in name."""
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        text = "I'll use the execute_shell_command tool to run the script."

        result = detect_truncated_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"

    def test_detect_truncated_none_input(self):
        """Test detect_truncated_tool_call with None input doesn't crash.

        Regression test: provider may emit STREAM_END with data=None,
        causing 'NoneType' object has no attribute 'strip' error.
        """
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        result = detect_truncated_tool_call(None)
        assert result is None

    def test_detect_truncated_empty_input(self):
        """Test detect_truncated_tool_call with empty string."""
        from ppxai.engine.tools.parser import detect_truncated_tool_call

        result = detect_truncated_tool_call("")
        assert result is None


class TestParseToolCallNoneGuard:
    """Regression tests for None/empty input to parse_tool_call.

    Bug: STREAM_END event with data=None caused 'NoneType' object has no
    attribute 'strip' in parse_tool_call() when provider returned no content.
    """

    def test_parse_tool_call_none_input(self):
        """parse_tool_call(None) returns None without crashing."""
        from ppxai.engine.tools.parser import parse_tool_call

        result = parse_tool_call(None, lambda name: None)
        assert result is None

    def test_parse_tool_call_empty_input(self):
        """parse_tool_call('') returns None."""
        from ppxai.engine.tools.parser import parse_tool_call

        result = parse_tool_call("", lambda name: None)
        assert result is None


class TestFindJsonObjects:
    """Tests for _find_json_objects brace-counting parser (v1.15.6, P2)."""

    def test_simple_json_object(self):
        """Parse a single JSON object from text."""

        text = 'Here is the result: {"tool": "web_search", "arguments": {"query": "hello"}}'
        objects = _find_json_objects(text)
        assert len(objects) == 1
        assert objects[0]["tool"] == "web_search"

    def test_multiple_json_objects(self):
        """Find multiple JSON objects in text."""

        text = 'First: {"a": 1} then {"b": 2} end'
        objects = _find_json_objects(text)
        assert len(objects) == 2
        assert objects[0] == {"a": 1}
        assert objects[1] == {"b": 2}

    def test_nested_braces_in_strings(self):
        """Handle nested braces inside string values (apply_patch diffs)."""

        text = '{"tool": "apply_patch", "arguments": {"patch": "--- a.py\\n+++ b.py\\n@@ -1 +1 @@\\n-def foo() {\\n+def bar() {"}}'
        objects = _find_json_objects(text)
        assert len(objects) == 1
        assert objects[0]["tool"] == "apply_patch"

    def test_escaped_quotes_in_strings(self):
        """Handle escaped quotes inside string values."""

        text = '{"key": "value with \\"quotes\\" inside"}'
        objects = _find_json_objects(text)
        assert len(objects) == 1
        assert "quotes" in objects[0]["key"]

    def test_json_in_code_block(self):
        """Find JSON inside markdown code blocks."""

        text = "Here's my tool call:\n```json\n{\"tool\": \"read_file\", \"arguments\": {\"filepath\": \"test.py\"}}\n```"
        objects = _find_json_objects(text)
        assert len(objects) == 1
        assert objects[0]["tool"] == "read_file"

    def test_no_json_in_text(self):
        """Return empty list when no JSON objects found."""

        objects = _find_json_objects("Just plain text with no JSON")
        assert objects == []

    def test_invalid_json_skipped(self):
        """Skip text that looks like JSON but isn't valid."""

        text = '{not valid json} and {"valid": true}'
        objects = _find_json_objects(text)
        assert len(objects) == 1
        assert objects[0] == {"valid": True}

    def test_unclosed_brace_handled(self):
        """Handle unclosed braces without crashing."""

        text = '{"unclosed": "value'
        objects = _find_json_objects(text)
        assert objects == []

    def test_empty_string(self):
        """Handle empty string input."""

        assert _find_json_objects("") == []

    def test_deeply_nested_json(self):
        """Handle deeply nested JSON objects."""

        text = '{"tool": "test", "arguments": {"nested": {"deep": {"value": 42}}}}'
        objects = _find_json_objects(text)
        assert len(objects) == 1
        assert objects[0]["arguments"]["nested"]["deep"]["value"] == 42


class TestStripToolJsonFromText:
    """Tests for strip_tool_json_from_text (v1.15.6, Gap 4)."""

    def test_strip_tool_call_json(self):
        """Strip tool call JSON from response text."""

        text = 'I will search for that. {"tool": "web_search", "arguments": {"query": "python"}} Let me know if you need more.'
        result = strip_tool_json_from_text(text)
        assert '{"tool"' not in result
        assert "I will search for that." in result
        assert "Let me know if you need more." in result

    def test_preserve_non_tool_json(self):
        """Don't strip JSON that isn't a tool call."""

        text = 'The config is: {"debug": true, "level": 5}'
        result = strip_tool_json_from_text(text)
        assert '{"debug": true' in result

    def test_strip_tool_json_in_code_block(self):
        """Strip tool call JSON wrapped in markdown code block."""

        text = 'I will call the tool:\n```json\n{"tool": "read_file", "arguments": {"filepath": "test.py"}}\n```\nDone.'
        result = strip_tool_json_from_text(text)
        assert '{"tool"' not in result
        assert "```" not in result
        assert "Done." in result

    def test_no_stripping_needed(self):
        """Return text unchanged when no tool JSON present."""

        text = "Just a normal response with no JSON."
        assert strip_tool_json_from_text(text) == text

    def test_empty_input(self):
        """Handle empty string."""

        assert strip_tool_json_from_text("") == ""

    def test_none_guard(self):
        """Handle None input (returns None)."""

        assert strip_tool_json_from_text(None) is None

    def test_strip_name_key_variant(self):
        """Strip JSON with 'name' key (OpenAI function call format)."""

        text = 'Calling function: {"name": "web_search", "arguments": {"query": "test"}}'
        result = strip_tool_json_from_text(text)
        assert '{"name"' not in result
        assert "Calling function:" in result

    def test_strip_multiple_tool_calls(self):
        """Strip multiple tool call JSON blocks."""

        text = (
            'Step 1: {"tool": "read_file", "arguments": {"filepath": "a.py"}} '
            'Step 2: {"tool": "web_search", "arguments": {"query": "test"}}'
        )
        result = strip_tool_json_from_text(text)
        assert '{"tool"' not in result

    def test_no_brace_in_text(self):
        """Fast path: text without braces returned as-is."""

        text = "No braces here at all"
        assert strip_tool_json_from_text(text) == text


class TestParseToolCallBraceCountingIntegration:
    """Integration tests verifying parse_tool_call uses brace-counting parser."""

    @pytest.fixture
    def mock_get_tool(self):
        """Create a mock get_tool function."""
        mock_tool = Mock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "patch": {"type": "string"},
                "file_path": {"type": "string"},
            },
            "required": ["patch"]
        }

        def get_tool(name):
            if name == "apply_patch":
                return mock_tool
            return None

        return get_tool

    def test_parse_apply_patch_with_nested_braces(self, mock_get_tool):
        """parse_tool_call handles apply_patch with braces in diff content."""
        # Simulate a model response with apply_patch containing code with braces
        text = (
            'I will apply the patch:\n'
            '{"tool": "apply_patch", "arguments": {"patch": '
            '"--- a/main.py\\n+++ b/main.py\\n@@ -1,3 +1,3 @@\\n'
            '-def foo():\\n+def bar():\\n     return {\\\"key\\\": \\\"value\\\"}"}}'
        )
        result = parse_tool_call(text, mock_get_tool)
        assert result is not None
        assert result["tool"] == "apply_patch"
        assert "patch" in result["arguments"]


class TestDetectTruncatedRawJson:
    """Tests for raw JSON truncation detection without preamble (v1.16.0).

    sonar-pro and similar models output raw tool JSON without "I'll use X tool"
    text. The extended detect_truncated_tool_call must catch these.
    """

    def test_raw_truncated_json_no_preamble(self):
        """Raw JSON with 'tool' key and unclosed braces detected as truncated."""
        # Sonar-pro pattern: just outputs JSON directly, gets truncated
        text = '{"tool": "apply_patch", "arguments": {"patch": "--- a/main.py\\n+++ b/main.py\\n@@ -1,100 +1,100 @@\\n-old line'
        result = detect_truncated_tool_call(text)
        assert result is not None
        assert result["tool"] == "apply_patch"
        assert result["reason"] == "truncated_json"

    def test_raw_truncated_json_in_code_block(self):
        """Truncated JSON inside a markdown code block without preamble."""
        text = '```json\n{"tool": "apply_patch", "arguments": {"patch": "some long patch content...'
        result = detect_truncated_tool_call(text)
        assert result is not None
        assert result["tool"] == "apply_patch"
        assert result["reason"] == "truncated_json"

    def test_raw_complete_json_not_flagged(self):
        """Complete raw JSON without preamble should NOT be flagged as truncated."""
        text = '{"tool": "read_file", "arguments": {"filepath": "test.py"}}'
        result = detect_truncated_tool_call(text)
        assert result is None

    def test_raw_json_different_tools(self):
        """Raw truncated JSON detected for various tool names."""
        for tool in ["read_file", "web_search", "execute_shell_command"]:
            text = f'{{"tool": "{tool}", "arguments": {{"key": "value'
            result = detect_truncated_tool_call(text)
            assert result is not None, f"Failed to detect truncation for {tool}"
            assert result["tool"] == tool

    def test_no_tool_key_not_detected(self):
        """JSON without 'tool' key is not detected as truncated tool call."""
        text = '{"name": "something", "data": {"nested": "value'
        result = detect_truncated_tool_call(text)
        assert result is None

    def test_raw_json_with_surrounding_text(self):
        """Raw truncated JSON with non-intent surrounding text still detected."""
        text = 'Here is the change:\n{"tool": "apply_patch", "arguments": {"patch": "--- a.py\\n+++ b.py\\n'
        result = detect_truncated_tool_call(text)
        assert result is not None
        assert result["tool"] == "apply_patch"

    def test_preamble_pattern_still_takes_priority(self):
        """If preamble pattern matches, Pattern 1 handles it (not Pattern 2)."""
        text = "I'll use the apply_patch tool.\n{\"tool\": \"apply_patch\", \"arguments\": {\"patch\": \"incomplete..."
        result = detect_truncated_tool_call(text)
        assert result is not None
        assert result["tool"] == "apply_patch"
        # Pattern 1 detects it via the intent preamble
        assert "attempted to call" in result["message"] or "truncated" in result["reason"]
