"""Unit tests for the native OpenAI provider."""

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from types import SimpleNamespace

from ppxai.engine.providers.openai_native import (
    OpenAINativeProvider,
    MAX_COMPLETION_TOKENS_PREFIXES,
    RESTRICTED_PARAM_PREFIXES,
    RESPONSES_API_PREFIXES,
    REASONING_MODEL_PREFIXES,
    RESTRICTED_GENERATION_PARAMS,
)
from ppxai.engine.types import Message, Event, EventType, ProviderCapabilities, UsageStats
from ppxai.engine.providers.wire.responses import ResponsesHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    """Create a provider with mocked OpenAI client."""
    with patch("ppxai.engine.providers.openai_native.OpenAI") as mock_openai:
        p = OpenAINativeProvider(api_key="test-key")
        p.client = mock_openai.return_value
        return p


@pytest.fixture
def provider_with_web_search():
    """Provider with web search enabled."""
    with patch("ppxai.engine.providers.openai_native.OpenAI"):
        p = OpenAINativeProvider(api_key="test-key", enable_web_search=True)
        return p


# ---------------------------------------------------------------------------
# Model classification tests
# ---------------------------------------------------------------------------

class TestModelClassification:
    """Test model classification helper methods."""

    def test_responses_api_models(self):
        assert OpenAINativeProvider._is_responses_api_model("gpt-5.1-codex") is True
        assert OpenAINativeProvider._is_responses_api_model("gpt-5.1-codex-mini") is True
        assert OpenAINativeProvider._is_responses_api_model("codex-mini") is True
        assert OpenAINativeProvider._is_responses_api_model("gpt-5.2-pro") is True
        assert OpenAINativeProvider._is_responses_api_model("gpt-5-pro") is True
        assert OpenAINativeProvider._is_responses_api_model("gpt-5.2") is False
        assert OpenAINativeProvider._is_responses_api_model("gpt-4.1") is False

    def test_reasoning_models(self):
        assert OpenAINativeProvider._is_reasoning_model("o1") is True
        assert OpenAINativeProvider._is_reasoning_model("o1-mini") is True
        assert OpenAINativeProvider._is_reasoning_model("o3") is True
        assert OpenAINativeProvider._is_reasoning_model("o4-mini") is True
        assert OpenAINativeProvider._is_reasoning_model("gpt-5.2") is False
        assert OpenAINativeProvider._is_reasoning_model("gpt-4.1") is False

    def test_max_completion_tokens_models(self):
        assert OpenAINativeProvider._needs_max_completion_tokens("gpt-5.2") is True
        assert OpenAINativeProvider._needs_max_completion_tokens("gpt-5-mini") is True
        assert OpenAINativeProvider._needs_max_completion_tokens("o4-mini") is True
        assert OpenAINativeProvider._needs_max_completion_tokens("o1") is True
        assert OpenAINativeProvider._needs_max_completion_tokens("gpt-4.1") is False
        assert OpenAINativeProvider._needs_max_completion_tokens("gpt-4.1-nano") is False

    def test_restricted_params_models(self):
        assert OpenAINativeProvider._has_restricted_params("gpt-5.2") is True
        assert OpenAINativeProvider._has_restricted_params("o3") is True
        assert OpenAINativeProvider._has_restricted_params("gpt-4.1") is False


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestInit:
    """Test provider initialization."""

    def test_default_capabilities(self):
        """Endpoint fields only (ADR 0012 section 2 Q0g).

        `native_tool_calling` moved off this record: tool calling is a
        MODEL fact, asserted in `TestPromptBasedRouting` below.
        """
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(api_key="test-key")
            assert p.capabilities.streaming is True
            assert p.capabilities.web_search is False
            assert not hasattr(p.capabilities, "native_tool_calling")

    def test_web_search_capabilities(self):
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(api_key="test-key", enable_web_search=True)
            assert p.capabilities.web_search is True
            assert p.capabilities.web_fetch is True

    def test_custom_capabilities(self):
        caps = ProviderCapabilities(web_search=True, citations=True)
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(api_key="test-key", capabilities=caps)
            assert p.capabilities.web_search is True
            assert p.capabilities.citations is True

    def test_validate_config(self):
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(api_key="test-key")
            assert p.validate_config() is True

            p2 = OpenAINativeProvider(api_key="")
            assert p2.validate_config() is False

    def test_kwargs_ignored(self):
        """base_url and other kwargs should not raise."""
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
                extra_arg="ignored"
            )
            assert p.api_key == "test-key"

    def test_ssl_verify_false(self):
        """SSL_VERIFY=false should create httpx client."""
        with patch("ppxai.engine.providers.openai_native.OpenAI") as mock_openai, \
             patch.dict("os.environ", {"SSL_VERIFY": "false"}):
            p = OpenAINativeProvider(api_key="test-key")
            # Check that OpenAI was called with http_client kwarg
            call_kwargs = mock_openai.call_args[1]
            assert "http_client" in call_kwargs


# ---------------------------------------------------------------------------
# Prompt-based routing tests
# ---------------------------------------------------------------------------

class TestPromptBasedRouting:
    """Test that PROMPT_BASED_MODEL_PREFIXES uses prefix matching."""

    def test_prompt_based_for_dated_model_id(self):
        """Dated model IDs like o4-mini-2025-04-16 should get prompt-based routing."""
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(api_key="test-key")
            facts = p.get_facts_for_model("o4-mini-2025-04-16")
            assert facts.tool_mode == "prompt_based"

    def test_prompt_based_for_exact_model_id(self):
        """Exact model IDs should still get prompt-based routing."""
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(api_key="test-key")
            for model in ("o4-mini", "gpt-4.1-mini"):
                facts = p.get_facts_for_model(model)
                assert facts.tool_mode == "prompt_based", f"{model} should be prompt-based"

    def test_native_for_non_prompt_based_models(self):
        """Other models should keep native tool calling."""
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(api_key="test-key")
            for model in ("gpt-5.2", "gpt-4.1", "gpt-5.1-codex"):
                facts = p.get_facts_for_model(model)
                assert facts.tool_mode != "prompt_based", f"{model} should be native"


# ---------------------------------------------------------------------------
# Message conversion tests
# ---------------------------------------------------------------------------

class TestMessageConversion:
    """Test message conversion for both APIs."""

    def test_convert_messages_basic(self, provider):
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        result = provider._convert_messages(messages)
        assert len(result) == 3
        assert result[0] == {"role": "system", "content": "You are helpful."}
        assert result[1] == {"role": "user", "content": "Hello"}
        assert result[2] == {"role": "assistant", "content": "Hi there"}

    def test_convert_messages_for_responses(self):
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="system", content="More instructions"),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi"),
        ]
        instructions, items = ResponsesHandler.convert_messages(messages)
        assert instructions == "System prompt\n\nMore instructions"
        assert len(items) == 2
        assert items[0] == {"role": "user", "content": "Hello"}
        assert items[1] == {"role": "assistant", "content": "Hi"}

    def test_convert_messages_for_responses_no_system(self):
        messages = [Message(role="user", content="Hello")]
        instructions, items = ResponsesHandler.convert_messages(messages)
        assert instructions is None
        assert len(items) == 1

    def test_convert_tools_for_responses(self):
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                }
            }
        ]
        result = ResponsesHandler.convert_tools(openai_tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["name"] == "web_search"
        assert "parameters" in result[0]
        # Should NOT have nested "function" key
        assert "function" not in result[0]

    def test_convert_tools_for_responses_skips_non_function(self):
        tools = [{"type": "other", "data": "something"}]
        result = ResponsesHandler.convert_tools(tools)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Usage parsing tests
# ---------------------------------------------------------------------------

class TestUsageParsing:
    """Test usage parsing for both APIs."""

    def test_parse_chat_completions_usage(self, provider):
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        result = provider._parse_usage(usage)
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.total_tokens == 150

    def test_parse_usage_none(self, provider):
        assert provider._parse_usage(None) is None

    def test_parse_responses_usage(self):
        usage = SimpleNamespace(input_tokens=200, output_tokens=80)
        result = ResponsesHandler.parse_usage(usage)
        assert result.prompt_tokens == 200
        assert result.completion_tokens == 80
        assert result.total_tokens == 280

    def test_parse_responses_usage_none(self):
        assert ResponsesHandler.parse_usage(None) is None


# ---------------------------------------------------------------------------
# Chat Completions API tests
# ---------------------------------------------------------------------------

class TestChatCompletionsAPI:
    """Test Chat Completions API path."""

    @pytest.mark.asyncio
    async def test_streaming_basic(self, provider):
        """Test basic streaming response."""
        # Mock streaming response
        chunk1 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content="Hello", tool_calls=None, reasoning_content=None, reasoning=None
            ))],
            usage=None,
        )
        chunk2 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content=" world", tool_calls=None, reasoning_content=None, reasoning=None
            ))],
            usage=None,
        )
        chunk_final = SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        provider.client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk_final])

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="Hi")],
            model="gpt-4.1",
            stream=True,
        ):
            events.append(event)

        # Check event sequence
        event_types = [e.type for e in events]
        assert EventType.STREAM_START in event_types
        assert EventType.STREAM_CHUNK in event_types
        assert EventType.STREAM_END in event_types

        # Check content
        stream_end = [e for e in events if e.type == EventType.STREAM_END][0]
        assert stream_end.data == "Hello world"

        # Check usage
        assert stream_end.metadata["usage"].total_tokens == 15

    @pytest.mark.asyncio
    async def test_non_streaming(self, provider):
        """Test non-streaming response."""
        mock_message = SimpleNamespace(
            content="Hello!",
            tool_calls=None,
            reasoning_content=None,
            reasoning=None,
        )
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=mock_message)],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )

        provider.client.chat.completions.create.return_value = mock_response

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="Hi")],
            model="gpt-4.1",
            stream=False,
        ):
            events.append(event)

        stream_end = [e for e in events if e.type == EventType.STREAM_END][0]
        assert stream_end.data == "Hello!"
        assert stream_end.metadata["usage"].total_tokens == 8

    @pytest.mark.asyncio
    async def test_streaming_with_tool_calls(self, provider):
        """Test streaming with native tool calls."""
        tc_chunk1 = SimpleNamespace(
            index=0,
            id="call_123",
            function=SimpleNamespace(name="web_search", arguments='{"q'),
        )
        tc_chunk2 = SimpleNamespace(
            index=0,
            id=None,
            function=SimpleNamespace(name=None, arguments='uery": "test"}'),
        )

        chunk1 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content=None, tool_calls=[tc_chunk1], reasoning_content=None, reasoning=None
            ))],
            usage=None,
        )
        chunk2 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content=None, tool_calls=[tc_chunk2], reasoning_content=None, reasoning=None
            ))],
            usage=None,
        )
        chunk_final = SimpleNamespace(choices=[], usage=None)

        provider.client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk_final])

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="search for test")],
            model="gpt-4.1",
            stream=True,
            tools=[{"type": "function", "function": {"name": "web_search"}}],
        ):
            events.append(event)

        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_call_events) == 1
        assert tool_call_events[0].data["tool"] == "web_search"
        assert tool_call_events[0].data["arguments"] == {"query": "test"}
        assert tool_call_events[0].data["tool_call_id"] == "call_123"

    @pytest.mark.asyncio
    async def test_streaming_reasoning_tokens(self, provider):
        """Test reasoning token handling for o-series models."""
        chunk1 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content=None, tool_calls=None, reasoning_content="Let me think...", reasoning=None
            ))],
            usage=None,
        )
        chunk2 = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content="The answer is 42.", tool_calls=None, reasoning_content=None, reasoning=None
            ))],
            usage=None,
        )
        chunk_final = SimpleNamespace(choices=[], usage=None)

        provider.client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk_final])

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="What is the answer?")],
            model="o4-mini",
            stream=True,
        ):
            events.append(event)

        reasoning_events = [e for e in events if e.type == EventType.REASONING_CHUNK]
        assert len(reasoning_events) == 1
        assert reasoning_events[0].data == "Let me think..."

        stream_end = [e for e in events if e.type == EventType.STREAM_END][0]
        assert stream_end.data == "The answer is 42."
        assert stream_end.metadata["reasoning"] == "Let me think..."

    @pytest.mark.asyncio
    async def test_error_handling(self, provider):
        """Test error event on API failure."""
        import openai as openai_module
        provider.client.chat.completions.create.side_effect = openai_module.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401),
            body=None,
        )

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="Hi")],
            model="gpt-4.1",
            stream=True,
        ):
            events.append(event)

        error_events = [e for e in events if e.type == EventType.ERROR]
        assert len(error_events) == 1
        assert "Authentication failed" in error_events[0].data

    @pytest.mark.asyncio
    async def test_max_completion_tokens_for_gpt5(self, provider):
        """Test that GPT-5 models use max_completion_tokens."""
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="Hello", tool_calls=None, reasoning_content=None, reasoning=None
            ))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )
        provider.client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_get_max_tokens", return_value=4096):
            events = []
            async for event in provider.chat(
                messages=[Message(role="user", content="Hi")],
                model="gpt-5.2",
                stream=False,
            ):
                events.append(event)

        # Verify the API call used max_completion_tokens
        call_kwargs = provider.client.chat.completions.create.call_args[1]
        assert "max_completion_tokens" in call_kwargs
        assert call_kwargs["max_completion_tokens"] == 4096
        assert "max_tokens" not in call_kwargs

    @pytest.mark.asyncio
    async def test_restricted_params_stripped_for_gpt5(self, provider):
        """Test that temperature/top_p are stripped for GPT-5 models."""
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="Hello", tool_calls=None, reasoning_content=None, reasoning=None
            ))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )
        provider.client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_get_generation_params", return_value={
            "temperature": 0.5,
            "top_p": 0.9,
        }):
            events = []
            async for event in provider.chat(
                messages=[Message(role="user", content="Hi")],
                model="gpt-5.2",
                stream=False,
            ):
                events.append(event)

        call_kwargs = provider.client.chat.completions.create.call_args[1]
        assert "temperature" not in call_kwargs
        assert "top_p" not in call_kwargs


# ---------------------------------------------------------------------------
# Responses API tests
# ---------------------------------------------------------------------------

class TestResponsesAPI:
    """Test Responses API path for codex models."""

    @pytest.mark.asyncio
    async def test_codex_routes_to_responses_api(self, provider):
        """Test that codex models route to Responses API."""
        # Mock non-streaming response
        mock_output_text = SimpleNamespace(type="output_text", text="Generated code")
        mock_message = SimpleNamespace(type="message", content=[mock_output_text])
        mock_response = SimpleNamespace(
            output=[mock_message],
            output_text="Generated code",
            usage=SimpleNamespace(input_tokens=50, output_tokens=100),
        )
        provider.client.responses.create.return_value = mock_response

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="Write hello world")],
            model="gpt-5.1-codex",
            stream=False,
        ):
            events.append(event)

        # Should have used responses.create, not chat.completions.create
        provider.client.responses.create.assert_called_once()
        provider.client.chat.completions.create.assert_not_called()

        stream_end = [e for e in events if e.type == EventType.STREAM_END][0]
        assert stream_end.data == "Generated code"

    @pytest.mark.asyncio
    async def test_codex_streaming(self, provider):
        """Test streaming Responses API."""
        event1 = SimpleNamespace(type="response.output_text.delta", delta="Hello ")
        event2 = SimpleNamespace(type="response.output_text.delta", delta="world")
        event_done = SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                usage=SimpleNamespace(input_tokens=10, output_tokens=5)
            ),
        )

        provider.client.responses.create.return_value = iter([event1, event2, event_done])

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="Code")],
            model="gpt-5.1-codex",
            stream=True,
        ):
            events.append(event)

        chunks = [e for e in events if e.type == EventType.STREAM_CHUNK]
        assert len(chunks) == 2
        assert chunks[0].data == "Hello "
        assert chunks[1].data == "world"

        stream_end = [e for e in events if e.type == EventType.STREAM_END][0]
        assert stream_end.data == "Hello world"
        assert stream_end.metadata["usage"].prompt_tokens == 10
        assert stream_end.metadata["usage"].completion_tokens == 5

    @pytest.mark.asyncio
    async def test_codex_with_instructions(self, provider):
        """Test that system messages become instructions in Responses API."""
        mock_response = SimpleNamespace(
            output=[],
            output_text="result",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        provider.client.responses.create.return_value = mock_response

        events = []
        async for event in provider.chat(
            messages=[
                Message(role="system", content="Be concise"),
                Message(role="user", content="Hello"),
            ],
            model="gpt-5.1-codex",
            stream=False,
        ):
            events.append(event)

        call_kwargs = provider.client.responses.create.call_args[1]
        assert call_kwargs["instructions"] == "Be concise"
        assert len(call_kwargs["input"]) == 1  # Only user message, not system

    @pytest.mark.asyncio
    async def test_codex_streaming_tool_call(self, provider):
        """Test that streaming Responses API emits TOOL_CALL events for function calls."""
        item_added = SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(type="function_call", call_id="call_abc", name="read_file"),
        )
        args_delta1 = SimpleNamespace(
            type="response.function_call_arguments.delta",
            call_id="call_abc",
            delta='{"path":',
        )
        args_delta2 = SimpleNamespace(
            type="response.function_call_arguments.delta",
            call_id="call_abc",
            delta='"/src/main.py"}',
        )
        args_done = SimpleNamespace(
            type="response.function_call_arguments.done",
            call_id="call_abc",
            arguments='{"path":"/src/main.py"}',
        )
        completed = SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(usage=SimpleNamespace(input_tokens=20, output_tokens=10)),
        )

        provider.client.responses.create.return_value = iter([
            item_added, args_delta1, args_delta2, args_done, completed
        ])

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="Read /src/main.py")],
            model="gpt-5.1-codex",
            stream=True,
            tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}],
        ):
            events.append(event)

        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_call_events) == 1
        assert tool_call_events[0].data["tool"] == "read_file"
        assert tool_call_events[0].data["arguments"] == {"path": "/src/main.py"}
        assert tool_call_events[0].data["native"] is True
        assert tool_call_events[0].data["tool_call_id"] == "call_abc"

        stream_end = [e for e in events if e.type == EventType.STREAM_END][0]
        assert stream_end.metadata["tool_calls"][0]["function"]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_codex_non_streaming_tool_call(self, provider):
        """Test that non-streaming Responses API emits TOOL_CALL events for function_call items."""
        mock_fc_item = SimpleNamespace(
            type="function_call",
            call_id="call_xyz",
            name="write_file",
            arguments='{"path":"/tmp/out.py","content":"print(1)"}',
        )
        mock_response = SimpleNamespace(
            output=[mock_fc_item],
            output_text=None,
            usage=SimpleNamespace(input_tokens=30, output_tokens=15),
        )
        provider.client.responses.create.return_value = mock_response

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="Write to /tmp/out.py")],
            model="gpt-5.1-codex",
            stream=False,
            tools=[{"type": "function", "function": {"name": "write_file", "parameters": {}}}],
        ):
            events.append(event)

        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_call_events) == 1
        assert tool_call_events[0].data["tool"] == "write_file"
        assert tool_call_events[0].data["arguments"] == {"path": "/tmp/out.py", "content": "print(1)"}
        assert tool_call_events[0].data["tool_call_id"] == "call_xyz"

        stream_end = [e for e in events if e.type == EventType.STREAM_END][0]
        assert stream_end.data == ""  # No text content when tool called
        assert stream_end.metadata["tool_calls"][0]["function"]["name"] == "write_file"

    @pytest.mark.asyncio
    async def test_responses_api_error(self, provider):
        """Test error handling in Responses API."""
        import openai as openai_module
        provider.client.responses.create.side_effect = openai_module.BadRequestError(
            message="Model not found",
            response=MagicMock(status_code=404),
            body=None,
        )

        events = []
        async for event in provider.chat(
            messages=[Message(role="user", content="Hello")],
            model="gpt-5.1-codex",
            stream=False,
        ):
            events.append(event)

        error_events = [e for e in events if e.type == EventType.ERROR]
        assert len(error_events) == 1


# ---------------------------------------------------------------------------
# Web search tests
# ---------------------------------------------------------------------------

class TestWebSearch:
    """Test web search integration."""

    def test_needs_tool_without_web_search(self, provider):
        assert provider.needs_tool("web_search") is True
        assert provider.needs_tool("weather") is True

    def test_needs_tool_with_web_search(self, provider_with_web_search):
        assert provider_with_web_search.needs_tool("web_search") is False
        assert provider_with_web_search.needs_tool("weather") is False

    @pytest.mark.asyncio
    async def test_web_search_tool_added_for_codex(self, provider_with_web_search):
        """Web search tool should be included in Responses API calls."""
        mock_response = SimpleNamespace(
            output=[],
            output_text="result",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        provider_with_web_search.client.responses.create.return_value = mock_response

        events = []
        async for event in provider_with_web_search.chat(
            messages=[Message(role="user", content="Search test")],
            model="gpt-5.1-codex",
            stream=False,
        ):
            events.append(event)

        call_kwargs = provider_with_web_search.client.responses.create.call_args[1]
        tools = call_kwargs.get("tools", [])
        web_search_tools = [t for t in tools if t.get("type") == "web_search_preview"]
        assert len(web_search_tools) == 1


# ---------------------------------------------------------------------------
# Error formatting tests
# ---------------------------------------------------------------------------

class TestErrorFormatting:
    """Test error message formatting."""

    def test_auth_error(self):
        import openai as openai_module
        e = openai_module.AuthenticationError(
            message="Invalid key", response=MagicMock(status_code=401), body=None
        )
        msg = OpenAINativeProvider._format_error(e)
        assert "Authentication failed" in msg
        assert "OPENAI_API_KEY" in msg

    def test_rate_limit_error(self):
        import openai as openai_module
        e = openai_module.RateLimitError(
            message="Rate limit", response=MagicMock(status_code=429), body=None
        )
        msg = OpenAINativeProvider._format_error(e)
        assert "Rate limit" in msg

    def test_connection_error(self):
        import openai as openai_module
        e = openai_module.APIConnectionError(request=MagicMock())
        msg = OpenAINativeProvider._format_error(e)
        assert "Connection failed" in msg

    def test_bad_request_404(self):
        import openai as openai_module
        e = openai_module.BadRequestError(
            message="404 not found", response=MagicMock(status_code=400), body=None
        )
        msg = OpenAINativeProvider._format_error(e)
        assert "not found" in msg.lower()

    def test_generic_error(self):
        msg = OpenAINativeProvider._format_error(ValueError("something broke"))
        assert "ValueError" in msg
        assert "something broke" in msg


# ---------------------------------------------------------------------------
# List models test
# ---------------------------------------------------------------------------

class TestListModels:
    """Test model listing."""

    def test_list_models(self):
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            p = OpenAINativeProvider(
                api_key="test-key",
                models={
                    "1": {"id": "gpt-4.1", "name": "GPT 4.1", "description": "Fast"},
                    "2": {"id": "gpt-5.2", "name": "GPT 5.2", "context_length": 1048576},
                },
            )
            models = p.list_models()
            assert len(models) == 2
            assert models[0].id == "gpt-4.1"
            assert models[0].name == "GPT 4.1"
            assert models[1].context_length == 1048576


# ---------------------------------------------------------------------------
# Provider registry test
# ---------------------------------------------------------------------------

class TestProviderRegistry:
    """Test that OpenAINativeProvider is registered correctly."""

    def test_openai_registered_as_native(self):
        from ppxai.engine.providers import get_provider_class
        cls = get_provider_class("openai")
        assert cls is OpenAINativeProvider

    def test_other_providers_unchanged(self):
        from ppxai.engine.providers import get_provider_class, OpenAICompatibleProvider
        assert get_provider_class("local") is OpenAICompatibleProvider
        assert get_provider_class("custom") is OpenAICompatibleProvider


# ---------------------------------------------------------------------------
# chat_sync_simple test
# ---------------------------------------------------------------------------

class TestChatSyncSimple:
    """Test synchronous chat method."""

    def test_basic(self, provider):
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello!"))]
        )
        provider.client.chat.completions.create.return_value = mock_response

        result = provider.chat_sync_simple(
            messages=[Message(role="user", content="Hi")],
            model="gpt-4.1",
        )
        assert result == "Hello!"

    def test_uses_max_completion_tokens_for_gpt5(self, provider):
        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello!"))]
        )
        provider.client.chat.completions.create.return_value = mock_response

        with patch.object(provider, "_get_max_tokens", return_value=8192):
            provider.chat_sync_simple(
                messages=[Message(role="user", content="Hi")],
                model="gpt-5.2",
            )

        call_kwargs = provider.client.chat.completions.create.call_args[1]
        assert "max_completion_tokens" in call_kwargs
        assert call_kwargs["max_completion_tokens"] == 8192
