"""Tests for proper tool message format (Step 3).

Tests that native tool calls use proper assistant(tool_calls) + tool role messages
instead of synthetic user/assistant pairs.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from ppxai.engine.types import Message
from ppxai.engine.session import SessionManager
from ppxai.engine.providers.base import BaseProvider


# ---------------------------------------------------------------------------
# Message dataclass tests
# ---------------------------------------------------------------------------

class TestMessageToolFields:
    """Test Message dataclass with tool_calls and tool_call_id fields."""

    def test_message_defaults_none(self):
        """New fields default to None for backward compatibility."""
        m = Message("user", "hello")
        assert m.tool_calls is None
        assert m.tool_call_id is None

    def test_message_with_tool_calls(self):
        """Assistant message with tool_calls."""
        tool_calls = [{
            "id": "call_abc123",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "foo.py"}'}
        }]
        m = Message("assistant", "", tool_calls=tool_calls)
        assert m.role == "assistant"
        assert m.content == ""
        assert m.tool_calls == tool_calls
        assert m.tool_call_id is None

    def test_message_with_tool_call_id(self):
        """Tool role message with tool_call_id."""
        m = Message("tool", "file contents here", tool_call_id="call_abc123")
        assert m.role == "tool"
        assert m.content == "file contents here"
        assert m.tool_calls is None
        assert m.tool_call_id == "call_abc123"


# ---------------------------------------------------------------------------
# Session serialization tests
# ---------------------------------------------------------------------------

class TestSessionToolMessageSerialization:
    """Test session save/load round-trip with tool messages.

    v1.17.4 Phase 2.1a: _serialize_message / _deserialize_message became
    instance methods (was @staticmethod) because they now optionally
    consult `self.file_store` to rewrite multimodal content parts. For
    plain text / tool-call content these methods behave identically to
    the previous staticmethods — only the call site changed from
    `SessionManager._serialize_message(m)` to `session._serialize_message(m)`.
    """

    @pytest.fixture
    def session(self, tmp_path):
        return SessionManager(
            sessions_dir=tmp_path, exports_dir=tmp_path / "exports"
        )

    def test_serialize_message_basic(self, session):
        """Basic message serialization (no tool fields)."""
        m = Message("user", "hello")
        d = session._serialize_message(m)
        assert d == {"role": "user", "content": "hello"}

    def test_serialize_message_with_tool_calls(self, session):
        """Serialization includes tool_calls when present."""
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]
        m = Message("assistant", "", tool_calls=tool_calls)
        d = session._serialize_message(m)
        assert d["tool_calls"] == tool_calls
        assert "tool_call_id" not in d

    def test_serialize_message_with_tool_call_id(self, session):
        """Serialization includes tool_call_id when present."""
        m = Message("tool", "result", tool_call_id="call_1")
        d = session._serialize_message(m)
        assert d["tool_call_id"] == "call_1"
        assert "tool_calls" not in d

    def test_deserialize_message_basic(self, session):
        """Basic message deserialization (old format without tool fields)."""
        m = session._deserialize_message({"role": "user", "content": "hello"})
        assert m.role == "user"
        assert m.content == "hello"
        assert m.tool_calls is None
        assert m.tool_call_id is None

    def test_deserialize_message_with_tool_calls(self, session):
        """Deserialization restores tool_calls."""
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]
        m = session._deserialize_message({
            "role": "assistant", "content": "", "tool_calls": tool_calls
        })
        assert m.tool_calls == tool_calls
        assert m.tool_call_id is None

    def test_deserialize_message_with_tool_call_id(self, session):
        """Deserialization restores tool_call_id."""
        m = session._deserialize_message({
            "role": "tool", "content": "result", "tool_call_id": "call_1"
        })
        assert m.tool_call_id == "call_1"
        assert m.tool_calls is None

    def test_save_load_roundtrip_with_tool_messages(self, tmp_path):
        """Full save/load round-trip preserves tool message fields."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")

        # Add a tool interaction sequence
        session.add_message(Message("user", "read foo.py"))
        session.add_message(Message("assistant", "", tool_calls=[{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "foo.py"}'}
        }]))
        session.add_message(Message("tool", "print('hello')", tool_call_id="call_abc"))
        session.add_message(Message("assistant", "The file contains a print statement."))

        name = session.save("test_tool_roundtrip")

        # Load into a fresh session
        session2 = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        assert session2.load(name)

        assert len(session2.messages) == 4
        assert session2.messages[0].role == "user"
        assert session2.messages[1].role == "assistant"
        assert session2.messages[1].tool_calls is not None
        assert session2.messages[1].tool_calls[0]["id"] == "call_abc"
        assert session2.messages[2].role == "tool"
        assert session2.messages[2].tool_call_id == "call_abc"
        assert session2.messages[2].content == "print('hello')"
        assert session2.messages[3].role == "assistant"
        assert session2.messages[3].content == "The file contains a print statement."

    def test_load_old_format_backward_compat(self, tmp_path):
        """Old session format (no tool_calls/tool_call_id) loads fine."""
        # Write a session file in old format
        old_data = {
            "session_name": "old_session",
            "metadata": {"created_at": "2025-01-01", "provider": "openai", "model": "gpt-4", "message_count": 2},
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"}
            ],
            "usage": {"total_tokens": 10, "prompt_tokens": 5, "completion_tokens": 5, "estimated_cost": 0.001},
            "saved_at": "2025-01-01"
        }

        filepath = tmp_path / "old_session.json"
        with open(filepath, 'w') as f:
            json.dump(old_data, f)

        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        assert session.load("old_session")
        assert len(session.messages) == 2
        assert session.messages[0].tool_calls is None
        assert session.messages[0].tool_call_id is None

    def test_load_with_extras_roundtrip(self, tmp_path):
        """load() preserves tool message fields."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        session.add_message(Message("user", "test"))
        session.add_message(Message("assistant", "", tool_calls=[{
            "id": "call_x", "type": "function",
            "function": {"name": "web_search", "arguments": '{"query": "test"}'}
        }]))
        session.add_message(Message("tool", "search results", tool_call_id="call_x"))
        session.add_message(Message("assistant", "Here are the results."))
        session.save_dirty()

        session2 = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        assert session2.load(session.session_name)
        assert session2.messages[1].tool_calls is not None
        assert session2.messages[2].tool_call_id == "call_x"


# ---------------------------------------------------------------------------
# BaseProvider._convert_messages() tests
# ---------------------------------------------------------------------------

class TestBaseProviderConvertMessages:
    """Test that _convert_messages handles tool fields."""

    def _make_provider(self):
        """Create a minimal concrete provider for testing."""
        # BaseProvider is abstract, so we create a minimal concrete subclass
        class TestProvider(BaseProvider):
            async def chat(self, messages, model, stream=False, tools=None):
                pass
        return TestProvider(api_key="test", base_url="http://localhost")

    def test_basic_messages(self):
        provider = self._make_provider()
        messages = [Message("user", "hello"), Message("assistant", "hi")]
        result = provider._convert_messages(messages)
        assert result == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

    def test_messages_with_tool_calls(self):
        provider = self._make_provider()
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]
        messages = [
            Message("user", "read foo"),
            Message("assistant", "", tool_calls=tool_calls),
            Message("tool", "contents", tool_call_id="call_1"),
            Message("assistant", "done"),
        ]
        result = provider._convert_messages(messages)

        assert result[1]["tool_calls"] == tool_calls
        assert "tool_call_id" not in result[1]
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "call_1"
        assert "tool_calls" not in result[2]

    def test_none_fields_not_included(self):
        """Messages without tool fields should not have those keys."""
        provider = self._make_provider()
        messages = [Message("user", "hello")]
        result = provider._convert_messages(messages)
        assert "tool_calls" not in result[0]
        assert "tool_call_id" not in result[0]


# ---------------------------------------------------------------------------
# OpenAINativeProvider._convert_messages_for_responses() tests
# ---------------------------------------------------------------------------

class TestOpenAINativeConvertMessagesForResponses:
    """Test Responses API message conversion with tool fields."""

    def test_tool_role_message(self):
        from ppxai.engine.providers.openai_native import OpenAINativeProvider

        messages = [
            Message("system", "You are helpful"),
            Message("user", "read foo"),
            Message("assistant", "", tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "read_file", "arguments": "{}"}
            }]),
            Message("tool", "file contents", tool_call_id="call_1"),
            Message("assistant", "Here's the file."),
        ]

        instructions, items = OpenAINativeProvider._convert_messages_for_responses(messages)
        assert instructions == "You are helpful"
        assert len(items) == 4  # user, assistant, tool, assistant

        # Check tool item
        tool_item = items[2]
        assert tool_item["role"] == "tool"
        assert tool_item["content"] == "file contents"
        assert tool_item["tool_call_id"] == "call_1"

        # Check assistant with tool_calls
        assistant_item = items[1]
        assert assistant_item["role"] == "assistant"
        assert assistant_item["tool_calls"] is not None

    def test_system_messages_become_instructions(self):
        from ppxai.engine.providers.openai_native import OpenAINativeProvider

        messages = [
            Message("system", "Part 1"),
            Message("system", "Part 2"),
            Message("user", "hello"),
        ]
        instructions, items = OpenAINativeProvider._convert_messages_for_responses(messages)
        assert instructions == "Part 1\n\nPart 2"
        assert len(items) == 1
        assert items[0]["role"] == "user"


# ---------------------------------------------------------------------------
# _non_stream_responses content extraction tests (issue 9.1)
# ---------------------------------------------------------------------------

class TestNonStreamResponsesContentExtraction:
    """Test _non_stream_responses handles various item.content shapes.

    The Responses API can return item.content as a list of parts (normal),
    a plain string (shorthand), or a bool True (observed on some Codex
    model variants). The last case previously raised TypeError.
    """

    def _run(self, output_items, output_text=None):
        """Drive _non_stream_responses with mocked client.responses.create."""
        import asyncio
        from unittest.mock import MagicMock, patch
        from ppxai.engine.providers.openai_native import OpenAINativeProvider
        from ppxai.engine.types import EventType

        response = MagicMock()
        response.output = output_items
        response.output_text = output_text
        response.usage = None

        with patch("ppxai.engine.providers.openai_native.OpenAI") as mock_openai:
            provider = OpenAINativeProvider(api_key="test-key")
            provider.client.responses.create.return_value = response

            async def _drain():
                return [ev async for ev in provider._non_stream_responses({"model": "test"})]

            events = asyncio.run(_drain())

        return next(e for e in events if e.type == EventType.STREAM_END)

    @staticmethod
    def _text_part(text):
        from unittest.mock import MagicMock
        part = MagicMock()
        part.type = "output_text"
        part.text = text
        return part

    @staticmethod
    def _message_item(content):
        from unittest.mock import MagicMock
        item = MagicMock()
        item.type = "message"
        item.content = content
        return item

    def test_content_as_list_of_parts(self):
        """Normal case: content is a list of output_text parts."""
        item = self._message_item([self._text_part("hello world")])
        ev = self._run([item])
        assert ev.data == "hello world"

    def test_content_as_string(self):
        """Shorthand: content is a plain string."""
        item = self._message_item("direct string content")
        ev = self._run([item])
        assert ev.data == "direct string content"

    def test_content_as_bool_does_not_raise(self):
        """Bug 9.1: content=True (bool) must not raise TypeError and logs a warning."""
        from unittest.mock import patch
        item = self._message_item(True)  # ← the bad value seen in production
        with patch("ppxai.engine.providers.openai_native.logger") as mock_logger:
            # Must not raise TypeError: 'bool' object is not iterable
            ev = self._run([item])
            assert ev.data == ""  # unexpected content type silently skipped
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "bool" in warning_msg
            assert "Unexpected" in warning_msg

    def test_content_none_falls_through_to_output_text(self):
        """content=None: falls through to output_text fallback."""
        item = self._message_item(None)
        ev = self._run([item], output_text="fallback text")
        assert ev.data == "fallback text"


# ---------------------------------------------------------------------------
# validate_and_fix_alternation() tests
# ---------------------------------------------------------------------------

class TestAlternationValidationWithToolMessages:
    """Test that alternation validator handles tool role messages correctly."""

    def test_valid_tool_sequence(self, tmp_path):
        """Valid: user → assistant(tool_calls) → tool → assistant."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        session.messages = [
            Message("user", "read foo"),
            Message("assistant", "", tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "read_file", "arguments": "{}"}
            }]),
            Message("tool", "contents", tool_call_id="call_1"),
            Message("assistant", "Here's the file."),
        ]
        removed = session.validate_and_fix_alternation()
        assert removed == 0
        assert len(session.messages) == 4

    def test_multiple_tool_messages(self, tmp_path):
        """Valid: assistant(tool_calls) → tool → tool (multi-tool)."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        session.messages = [
            Message("user", "compare foo and bar"),
            Message("assistant", "", tool_calls=[
                {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"foo"}'}},
                {"id": "call_2", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"bar"}'}},
            ]),
            Message("tool", "foo contents", tool_call_id="call_1"),
            Message("tool", "bar contents", tool_call_id="call_2"),
            Message("assistant", "Here's the comparison."),
        ]
        removed = session.validate_and_fix_alternation()
        assert removed == 0
        assert len(session.messages) == 5

    def test_orphan_tool_message_removed(self, tmp_path):
        """Tool message without preceding assistant(tool_calls) is removed."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        session.messages = [
            Message("user", "hello"),
            Message("assistant", "hi"),  # No tool_calls
            Message("tool", "orphan", tool_call_id="call_x"),
            Message("user", "what?"),
            Message("assistant", "sorry"),
        ]
        removed = session.validate_and_fix_alternation()
        # The orphan tool message should be removed, plus any resulting alternation issues
        assert removed > 0
        # Verify no tool messages without proper preceding assistant
        for i, m in enumerate(session.messages):
            if m.role == "tool":
                assert i > 0
                prev = session.messages[i - 1]
                assert (prev.role == "assistant" and prev.tool_calls) or prev.role == "tool"

    def test_trailing_tool_message_removed(self, tmp_path):
        """Tool message at end of session is removed."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        session.messages = [
            Message("user", "read foo"),
            Message("assistant", "", tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "read_file", "arguments": "{}"}
            }]),
            Message("tool", "contents", tool_call_id="call_1"),
        ]
        removed = session.validate_and_fix_alternation()
        # Trailing tool (and then possibly trailing assistant with tool_calls) should be cleaned
        assert removed > 0
        if session.messages:
            assert session.messages[-1].role == "assistant"

    def test_leading_tool_message_removed(self, tmp_path):
        """Leading tool message is removed."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        session.messages = [
            Message("tool", "orphan", tool_call_id="call_x"),
            Message("user", "hello"),
            Message("assistant", "hi"),
        ]
        removed = session.validate_and_fix_alternation()
        assert removed >= 1
        assert session.messages[0].role == "user"


# ---------------------------------------------------------------------------
# get_messages_as_dicts() tests
# ---------------------------------------------------------------------------

class TestGetMessagesAsDicts:
    """Test that get_messages_as_dicts includes tool fields."""

    def test_includes_tool_fields(self, tmp_path):
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        session.add_message(Message("assistant", "", tool_calls=[{"id": "call_1"}]))
        session.add_message(Message("tool", "result", tool_call_id="call_1"))

        dicts = session.get_messages_as_dicts()
        assert dicts[0]["tool_calls"] == [{"id": "call_1"}]
        assert dicts[1]["tool_call_id"] == "call_1"

    def test_basic_messages_no_extra_keys(self, tmp_path):
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "exports")
        session.add_message(Message("user", "hello"))

        dicts = session.get_messages_as_dicts()
        assert dicts[0] == {"role": "user", "content": "hello"}
        assert "tool_calls" not in dicts[0]
        assert "tool_call_id" not in dicts[0]


# ---------------------------------------------------------------------------
# Multi-tool execution tests (Step 4)
# ---------------------------------------------------------------------------

import asyncio
from unittest.mock import patch
from ppxai.engine.chat import chat_with_tools, _execute_single_tool
from ppxai.engine.types import Event, EventType, ProviderCapabilities
from ppxai.engine.model_profiles import ModelProfile, ToolCallingProfile


class MockProvider:
    """Minimal mock provider for multi-tool tests."""

    def __init__(self, capabilities=None, responses=None):
        self.capabilities = capabilities or ProviderCapabilities()
        self._responses = responses or []
        self._call_count = 0
        self.chat_calls = []

    def get_capabilities_for_model(self, model):
        return self.capabilities

    async def chat(self, messages, model, stream=False, tools=None):
        self.chat_calls.append({
            "messages": messages, "model": model,
            "stream": stream, "tools": tools,
        })
        idx = min(self._call_count, len(self._responses) - 1)
        events = self._responses[idx] if self._responses else []
        self._call_count += 1
        for event in events:
            yield event


class MockToolManager:
    """Mock ToolManager for multi-tool tests."""

    def __init__(self, tools=None, loop_on=None):
        self.max_iterations = 15
        self.auto_retry_empty = 0
        self.max_same_tool_calls = 3
        self._tools = tools or {}
        self._loop_on = loop_on  # (tool_name, args_dict) triggers loop detection
        self._recorded_calls = []

    def reset_tool_history(self):
        self._recorded_calls = []

    def get_tools_openai_format(self):
        return [{"type": "function", "function": {"name": n}} for n in self._tools]

    def get_tools_prompt(self, working_dir=None):
        if self._tools:
            return "Available tools: " + ", ".join(self._tools.keys())
        return ""

    def get_tool(self, name):
        return self._tools.get(name)

    def is_tool_loop_detected(self, name, args):
        if self._loop_on and name == self._loop_on[0]:
            return json.dumps(args, sort_keys=True) == json.dumps(self._loop_on[1], sort_keys=True)
        return False

    def record_tool_call(self, name, args):
        self._recorded_calls.append((name, args))

    async def execute_tool(self, name, **kwargs):
        tool = self._tools.get(name)
        if callable(tool):
            return tool(**kwargs)
        return f"Result from {name}"

    def get_tool_display_limit(self, tool_name, tool_args):
        return 4000

    def get_loop_message(self, tool_name):
        return f"Stop calling {tool_name}"


class MockChatContext:
    """Mock ChatContext for multi-tool tests."""

    def __init__(self, provider=None, model="test-model", tool_manager=None):
        self._provider = provider or MockProvider()
        self._model = model
        self._session = SessionManager()
        self._tool_manager = tool_manager or MockToolManager()
        self._interrupted = False
        self._consent_events = []
        self._current_tool_usage = {}

    @property
    def provider(self):
        return self._provider

    @property
    def provider_name(self):
        return "test"

    @property
    def model(self):
        return self._model

    @property
    def session(self):
        return self._session

    @property
    def tool_manager(self):
        return self._tool_manager

    @property
    def is_interrupted(self):
        return self._interrupted

    def get_consent_events(self):
        events = self._consent_events[:]
        self._consent_events.clear()
        return events

    def track_tool_usage(self, tool_name, usage):
        pass

    @property
    def agent_mode(self):
        return False

    def commit_agent_changes_if_needed(self, message):
        return None

    def get_bootstrap_prompt(self):
        return ""

    def get_working_dir(self):
        return "/tmp/test"


async def collect_events(ctx, stream=False):
    """Helper: collect all events from chat_with_tools."""
    events = []
    async for event in chat_with_tools(ctx, stream):
        events.append(event)
    return events


class TestMultiToolExecution:
    """Test multi-tool support (Step 4)."""

    @pytest.mark.asyncio
    async def test_two_native_tool_calls_both_execute(self):
        """When parallel_tool_calls=True, both native tool calls are executed."""
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                # First call: 2 tool calls
                [
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "a.py"}, "tool_call_id": "call_1"}),
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "b.py"}, "tool_call_id": "call_2"}),
                    Event(EventType.STREAM_END, ""),
                ],
                # Second call: final response
                [Event(EventType.STREAM_END, "Both files read.")],
            ],
        )
        tm = MockToolManager(tools={
            "read_file": lambda path="": f"contents of {path}",
        })
        ctx = MockChatContext(provider=provider, model="gpt-5.2", tool_manager=tm)
        ctx.session.add_message(Message("user", "read a.py and b.py"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native", parallel_tool_calls=True),
            )
            events = await collect_events(ctx)

        # Both tool calls should fire
        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_call_events) == 2
        assert tool_call_events[0].data["arguments"]["path"] == "a.py"
        assert tool_call_events[1].data["arguments"]["path"] == "b.py"

        # Both tool results should appear
        tool_result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
        assert len(tool_result_events) == 2

        # Final response
        end_events = [e for e in events if e.type == EventType.STREAM_END]
        assert len(end_events) == 1
        assert end_events[0].data == "Both files read."

    @pytest.mark.asyncio
    async def test_single_tool_when_parallel_false(self):
        """When parallel_tool_calls=False, only first native tool call is processed."""
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                # First call: 2 tool calls
                [
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "a.py"}, "tool_call_id": "call_1"}),
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "b.py"}, "tool_call_id": "call_2"}),
                    Event(EventType.STREAM_END, ""),
                ],
                # Second call: final response
                [Event(EventType.STREAM_END, "File read.")],
            ],
        )
        tm = MockToolManager(tools={
            "read_file": lambda path="": f"contents of {path}",
        })
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "read a.py"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native", parallel_tool_calls=False),
            )
            events = await collect_events(ctx)

        # Only first tool call should fire
        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_call_events) == 1
        assert tool_call_events[0].data["arguments"]["path"] == "a.py"

    @pytest.mark.asyncio
    async def test_multi_tool_session_messages_native(self):
        """Multi-tool creates ONE assistant(tool_calls) + N tool messages."""
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                [
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "a.py"}, "tool_call_id": "call_1"}),
                    Event(EventType.TOOL_CALL, {"tool": "list_directory", "arguments": {"path": "."}, "tool_call_id": "call_2"}),
                    Event(EventType.STREAM_END, ""),
                ],
                [Event(EventType.STREAM_END, "Done.")],
            ],
        )
        tm = MockToolManager(tools={
            "read_file": lambda path="": "file contents",
            "list_directory": lambda path="": "dir listing",
        })
        ctx = MockChatContext(provider=provider, model="gpt-5.2", tool_manager=tm)
        ctx.session.add_message(Message("user", "read file and list dir"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native", parallel_tool_calls=True),
            )
            events = await collect_events(ctx)

        # Check session messages: user, assistant(tool_calls=[2]), tool, tool, assistant
        msgs = ctx.session.messages
        assert msgs[0].role == "user"

        # Assistant message with 2 tool_calls
        assert msgs[1].role == "assistant"
        assert msgs[1].tool_calls is not None
        assert len(msgs[1].tool_calls) == 2
        assert msgs[1].tool_calls[0]["function"]["name"] == "read_file"
        assert msgs[1].tool_calls[1]["function"]["name"] == "list_directory"

        # Two tool result messages
        assert msgs[2].role == "tool"
        assert msgs[2].tool_call_id == "call_1"
        assert msgs[3].role == "tool"
        assert msgs[3].tool_call_id == "call_2"

        # Final assistant response
        assert msgs[4].role == "assistant"
        assert msgs[4].content == "Done."

    @pytest.mark.asyncio
    async def test_error_in_second_tool_still_records_both(self):
        """If second tool errors, both results are added to session."""
        def failing_tool(**kwargs):
            raise ValueError("disk full")

        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                [
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "a.py"}, "tool_call_id": "call_1"}),
                    Event(EventType.TOOL_CALL, {"tool": "write_file", "arguments": {"path": "b.py"}, "tool_call_id": "call_2"}),
                    Event(EventType.STREAM_END, ""),
                ],
                [Event(EventType.STREAM_END, "First succeeded, second failed.")],
            ],
        )
        tm = MockToolManager(tools={
            "read_file": lambda path="": "file contents",
            "write_file": failing_tool,
        })
        ctx = MockChatContext(provider=provider, model="gpt-5.2", tool_manager=tm)
        ctx.session.add_message(Message("user", "read a.py and write b.py"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native", parallel_tool_calls=True),
            )
            events = await collect_events(ctx)

        # Should have TOOL_CALL, TOOL_RESULT, TOOL_CALL, TOOL_ERROR
        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        tool_result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
        tool_error_events = [e for e in events if e.type == EventType.TOOL_ERROR]
        assert len(tool_call_events) == 2
        assert len(tool_result_events) == 1
        assert len(tool_error_events) == 1

        # Session should have: user, assistant(tool_calls=[2]), tool(ok), tool(err), assistant
        msgs = ctx.session.messages
        assert msgs[1].role == "assistant"
        assert len(msgs[1].tool_calls) == 2
        assert msgs[2].role == "tool"
        assert msgs[2].tool_call_id == "call_1"
        assert "file contents" in msgs[2].content
        assert msgs[3].role == "tool"
        assert msgs[3].tool_call_id == "call_2"
        assert "disk full" in msgs[3].content

    @pytest.mark.asyncio
    async def test_loop_detection_mid_batch_stops_remaining(self):
        """Loop detection on second tool stops processing remaining tools."""
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                [
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "a.py"}, "tool_call_id": "call_1"}),
                    Event(EventType.TOOL_CALL, {"tool": "list_directory", "arguments": {"path": "."}, "tool_call_id": "call_2"}),
                    Event(EventType.STREAM_END, ""),
                ],
                [Event(EventType.STREAM_END, "Stopped.")],
            ],
        )

        class LoopOnSecondToolManager(MockToolManager):
            """Triggers loop detection on list_directory."""
            def is_tool_loop_detected(self, name, args):
                return name == "list_directory"

        tm = LoopOnSecondToolManager(tools={
            "read_file": lambda path="": "contents",
            "list_directory": lambda path="": "listing",
        })
        ctx = MockChatContext(provider=provider, model="gpt-5.2", tool_manager=tm)
        ctx.session.add_message(Message("user", "read and list"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native", parallel_tool_calls=True),
            )
            events = await collect_events(ctx)

        # First call executes, second triggers loop detection
        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_call_events) == 1  # Only first fires (read_file)
        assert tool_call_events[0].data["tool"] == "read_file"
        info_events = [e for e in events if e.type == EventType.INFO]
        assert any("Loop detected" in str(e.data) for e in info_events)

    @pytest.mark.asyncio
    async def test_prompt_based_stays_single_tool(self):
        """Prompt-based mode still processes only one tool call."""
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=False),
            responses=[
                [Event(EventType.STREAM_END, '{"tool": "read_file", "arguments": {"path": "a.py"}}')],
                [Event(EventType.STREAM_END, "Done reading.")],
            ],
        )
        tm = MockToolManager(tools={
            "read_file": lambda path="": "file contents",
        })
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "read a.py"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="prompt_based"),
            )
            events = await collect_events(ctx)

        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_call_events) == 1

        # Prompt-based uses synthetic pairs
        msgs = ctx.session.messages
        # Find the synthetic assistant/user pair
        synthetic_assistant = [m for m in msgs if m.role == "assistant" and "I'll use" in m.content]
        assert len(synthetic_assistant) >= 1

    @pytest.mark.asyncio
    async def test_interrupt_mid_batch_stops(self):
        """Interrupt during second tool execution stops and returns."""
        call_count = 0

        async def slow_tool(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Simulate interrupt during second tool
                ctx._interrupted = True
            return f"result {call_count}"

        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                [
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "a.py"}, "tool_call_id": "call_1"}),
                    Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"path": "b.py"}, "tool_call_id": "call_2"}),
                    Event(EventType.STREAM_END, ""),
                ],
            ],
        )

        class InterruptToolManager(MockToolManager):
            async def execute_tool(self, name, **kwargs):
                return await slow_tool(**kwargs)

        tm = InterruptToolManager(tools={"read_file": True})
        ctx = MockChatContext(provider=provider, model="gpt-5.2", tool_manager=tm)
        ctx.session.add_message(Message("user", "read files"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native", parallel_tool_calls=True),
            )
            events = await collect_events(ctx)

        # Should get error event for interrupt
        error_events = [e for e in events if e.type == EventType.ERROR]
        assert any("Interrupted" in str(e.data) for e in error_events)
