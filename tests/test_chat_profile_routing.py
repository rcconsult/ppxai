"""Facts-driven tool calling mode routing (v1.16.0 Step 2, ADR 0012 §2 Q0e).

`chat_with_tools` resolves ONE record — `ModelFacts` — to determine:
- Native vs prompt-based mode selection
- Fallback on empty response
- Fallback on failure (unknown tool)
- strip_json_from_text

**Retargeted from a two-system setup.** These tests used to patch
`chat.get_profile` for the mode AND set `ProviderCapabilities.
native_tool_calling` on the mock provider for the gate, because the code
asked both in a fixed order. That order was debt Item 43's Layer-2 bug: a
capability resolving native=True never reached the wire if the profile said
prompt_based. `tool_mode` now answers the whole question from the model's
own record, so each test states one value instead of two — and the pairs
that used to express "mode says X but the capability says Y" no longer
have a way to be written, which is the point.
"""

import asyncio
import pytest
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, Any, List, Optional
from unittest.mock import MagicMock, patch, AsyncMock

from ppxai.engine.chat import chat_with_tools, _build_prompt_based_messages
from ppxai.engine.types import Event, EventType, Message, UsageStats, ProviderCapabilities
from ppxai.engine.model_facts import ModelFacts
from ppxai.engine.session import SessionManager
from ppxai.engine.tools.manager import ToolManager


class MockProvider:
    """Minimal mock provider for chat_with_tools tests."""

    def __init__(self, capabilities=None, responses=None, facts=None):
        self.capabilities = capabilities or ProviderCapabilities()
        self.facts = facts or ModelFacts()
        self._responses = responses or []
        self._call_count = 0
        self.chat_calls = []  # Track (messages, model, stream, tools) calls

    def get_capabilities(self):
        return self.capabilities

    def get_facts_for_model(self, model):
        return self.facts

    async def chat(self, messages, model, stream=False, tools=None):
        self.chat_calls.append({
            "messages": messages,
            "model": model,
            "stream": stream,
            "tools": tools,
        })
        idx = min(self._call_count, len(self._responses) - 1)
        events = self._responses[idx] if self._responses else []
        self._call_count += 1
        for event in events:
            yield event


class MockToolManager:
    """Minimal mock ToolManager for routing tests."""

    def __init__(self, tools=None):
        self.max_iterations = 15
        self.auto_retry_empty = 0
        self._tools = tools or {}

    def reset_tool_history(self):
        pass

    def get_tools_openai_format(self):
        return [{"type": "function", "function": {"name": n}} for n in self._tools]

    def get_tools_prompt(self, working_dir=None):
        if self._tools:
            return "Available tools: " + ", ".join(self._tools.keys())
        return ""

    def get_tool(self, name):
        return self._tools.get(name)

    def is_tool_loop_detected(self, name, args):
        return False

    def record_tool_call(self, name, args):
        pass

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
    """Mock ChatContext for testing chat_with_tools routing decisions."""

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


# ── Mode routing tests ──────────────────────────────────────────────


class TestModeRouting:
    """Test profile-driven mode selection."""

    @pytest.mark.asyncio
    async def test_native_mode_with_native_provider(self):
        """mode='native' + native-capable provider → use_native_tools=True."""
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, "Hello")]],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="gpt-5", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="native")
        events = await collect_events(ctx)

        # Provider should be called with tools (native mode)
        assert provider.chat_calls[0]["tools"] is not None
        assert any(e.type == EventType.STREAM_END for e in events)

    @pytest.mark.asyncio
    async def test_prompt_based_sends_no_tools(self):
        """RETARGETED — its original premise is dead under ADR 0012 §2 Q0e.

        This asserted `mode="native"` + a provider whose capability said
        NOT native → no tools, i.e. the capability GATED the mode. That gate
        was debt Item 43's Layer-2 bug in the other direction, and it cannot
        be expressed any more: tool mode is a model fact, and there is no
        provider-level value left to gate it with.

        What survives is the half that was always the real contract — a
        model resolving `prompt_based` must not receive a tools array.
        """
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, "Hello")]],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="prompt_based")
        events = await collect_events(ctx)

        assert provider.chat_calls[0]["tools"] is None

    @pytest.mark.asyncio
    async def test_prompt_based_mode_overrides_native_provider(self):
        """mode='prompt_based' + native-capable provider → use_native_tools=False."""
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, "I used a tool")]],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="gpt-4.1-mini", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="prompt_based")
        events = await collect_events(ctx)

        # Provider should be called WITHOUT tools even though it supports native
        assert provider.chat_calls[0]["tools"] is None

    @pytest.mark.asyncio
    async def test_auto_mode_with_native_provider(self):
        """mode='auto' + native-capable provider → use_native_tools=True."""
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, "Hello")]],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="auto")
        events = await collect_events(ctx)

        # Auto starts with native mode
        assert provider.chat_calls[0]["tools"] is not None

    @pytest.mark.asyncio
    async def test_unmeasured_model_defaults_to_prompt_based(self):
        """INVERTED, deliberately — Q0a flipped this default on purpose.

        The old assertion was "an unknown model gets native tools", because
        `ToolCallingProfile.mode` defaulted to `"native"` while
        `ProviderCapabilities.native_tool_calling` defaulted to `False` —
        two systems, opposite assumptions about the same unmeasured model.
        Unifying on the permissive one would have made every model absent
        from both tables tool-capable, silently, through the task-tier gate
        and oneshot enrichment.

        `prompt_based` wins because a model that degrades is recoverable and
        one that answers HTTP 400 is not. This test is the fence on that
        choice, so it asserts the OPPOSITE of what it used to.
        """
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, "Hello")]],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="unknown-model-xyz", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        # No facts stated: the real conservative floor applies.
        events = await collect_events(ctx)

        assert provider.chat_calls[0]["tools"] is None


# ── Fallback tests ──────────────────────────────────────────────────


class TestFallbackOnEmpty:
    """Test fallback_on_empty behavior."""

    @pytest.mark.asyncio
    async def test_fallback_on_empty_retries_prompt_based(self):
        """fallback_on_empty=True + native returns empty → retries with prompt-based."""
        provider = MockProvider(
            responses=[
                # First call: native returns empty
                [Event(EventType.STREAM_END, "")],
                # Second call: prompt-based returns content
                [Event(EventType.STREAM_END, "Here is the answer")],
            ],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="native",
                    fallback_on_empty=True,)
        events = await collect_events(ctx)

        # Should have 2 provider calls: native (empty) + prompt-based fallback
        assert len(provider.chat_calls) == 2
        # First call has tools (native)
        assert provider.chat_calls[0]["tools"] is not None
        # Second call has no tools (prompt-based fallback)
        assert provider.chat_calls[1]["tools"] is None
        # Should emit INFO about fallback
        info_events = [e for e in events if e.type == EventType.INFO]
        assert any("prompt-based" in str(e.data) for e in info_events)

    @pytest.mark.asyncio
    async def test_no_fallback_on_empty_when_disabled(self):
        """fallback_on_empty=False + native returns empty → no retry."""
        provider = MockProvider(
            responses=[
                [Event(EventType.STREAM_END, "")],
            ],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="native",
                    fallback_on_empty=False,)
        events = await collect_events(ctx)

        # Only 1 provider call — no fallback retry
        assert len(provider.chat_calls) == 1

    @pytest.mark.asyncio
    async def test_no_fallback_when_native_returns_content(self):
        """fallback_on_empty=True but native returns content → no fallback needed."""
        provider = MockProvider(
            responses=[
                [Event(EventType.STREAM_END, "I have an answer")],
            ],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="native",
                    fallback_on_empty=True,)
        events = await collect_events(ctx)

        # Only 1 call — response was not empty
        assert len(provider.chat_calls) == 1


class TestFallbackOnFailure:
    """Test fallback_on_failure behavior."""

    @pytest.mark.asyncio
    async def test_fallback_on_failure_tries_prompt_parser(self):
        """fallback_on_failure=True + unknown native tool → tries prompt-based parser."""
        provider = MockProvider(
            responses=[[
                Event(EventType.TOOL_CALL, {"tool": "unknown_tool_xyz", "arguments": {}}),
                Event(EventType.STREAM_END, '```json\n{"tool": "read_file", "arguments": {"filepath": "test.py"}}\n```'),
            ]],
        )
        tm = MockToolManager(tools={"read_file": lambda filepath="": f"content of {filepath}"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "read test.py"))

        provider.facts = ModelFacts(tool_mode="native",
                    fallback_on_failure=True,)
        events = await collect_events(ctx)

        # Should have found the tool call via prompt-based parser
        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_call_events) >= 1
        assert tool_call_events[0].data["tool"] == "read_file"

    @pytest.mark.asyncio
    async def test_no_fallback_on_failure_when_disabled(self):
        """fallback_on_failure=False + unknown native tool → no fallback."""
        provider = MockProvider(
            responses=[[
                Event(EventType.TOOL_CALL, {"tool": "unknown_tool_xyz", "arguments": {}}),
                Event(EventType.STREAM_END, '```json\n{"tool": "read_file", "arguments": {}}\n```'),
            ]],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="native",
                    fallback_on_failure=False,)
        events = await collect_events(ctx)

        # Tool call should still use the unknown tool name (no fallback)
        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        if tool_call_events:
            assert tool_call_events[0].data["tool"] == "unknown_tool_xyz"


# ── Strip JSON tests ────────────────────────────────────────────────


class TestProfileStripJson:
    """Test profile-driven strip_json_from_text."""

    @pytest.mark.asyncio
    async def test_strip_json_enabled_without_native_calls(self):
        """strip_json_from_text=True + no native calls → strips from response text."""
        json_in_text = 'Here is the answer.\n```json\n{"tool": "read_file", "arguments": {}}\n```\nDone.'
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, json_in_text)]],
        )
        # No tools registered so parse_tool_call won't match
        tm = MockToolManager(tools={})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="prompt_based",
                    strip_json_from_text=True,)
        events = await collect_events(ctx)

        # The final STREAM_END should have stripped JSON
        end_events = [e for e in events if e.type == EventType.STREAM_END]
        assert len(end_events) == 1
        # The JSON block should be removed or reduced
        assert '{"tool": "read_file"' not in end_events[0].data

    @pytest.mark.asyncio
    async def test_strip_json_disabled_keeps_text(self):
        """strip_json_from_text=False + no native calls → text unchanged."""
        json_in_text = 'Here is the answer.\n```json\n{"tool": "read_file", "arguments": {}}\n```\nDone.'
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, json_in_text)]],
        )
        tm = MockToolManager(tools={})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="prompt_based",
                    strip_json_from_text=False,)
        events = await collect_events(ctx)

        end_events = [e for e in events if e.type == EventType.STREAM_END]
        assert len(end_events) == 1
        # Text should still contain the JSON (not stripped)
        assert "read_file" in end_events[0].data


# ── Belt-and-suspenders tests ───────────────────────────────────────


class TestBeltAndSuspenders:
    """Test that fallback-capable profiles inject tool hints in native mode."""

    @pytest.mark.asyncio
    async def test_tool_hints_injected_for_fallback_models(self):
        """Models with fallback flags get tool descriptions in system prompt (belt-and-suspenders)."""
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, "Hello")]],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="native",
                    fallback_on_empty=True,)
        events = await collect_events(ctx)

        # The first message sent should be a system message containing tool descriptions
        first_call = provider.chat_calls[0]
        system_msgs = [m for m in first_call["messages"] if m.role == "system"]
        assert any("read_file" in m.content for m in system_msgs)

    @pytest.mark.asyncio
    async def test_no_tool_hints_without_fallback_flags(self):
        """Models without fallback flags don't get extra tool hints in native mode."""
        provider = MockProvider(
            responses=[[Event(EventType.STREAM_END, "Hello")]],
        )
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        ctx = MockChatContext(provider=provider, model="test-model", tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        provider.facts = ModelFacts(tool_mode="native",
                    fallback_on_empty=False,
                    fallback_on_failure=False,)
        events = await collect_events(ctx)

        # System messages should NOT contain tool descriptions
        first_call = provider.chat_calls[0]
        system_msgs = [m for m in first_call["messages"] if m.role == "system"]
        # Either no system messages, or none mentioning the tool
        assert not any("Available tools:" in m.content for m in system_msgs)


# ── Helper function tests ───────────────────────────────────────────


class TestBuildPromptBasedMessages:
    """Test _build_prompt_based_messages helper."""

    def test_returns_messages_with_system_prompt(self):
        """Helper injects tool descriptions into system message."""
        tm = MockToolManager(tools={"read_file": lambda: "content"})
        provider = MockProvider()
        ctx = MockChatContext(provider=provider, tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        messages = _build_prompt_based_messages(ctx)

        # First message should be system with tool descriptions
        assert messages[0].role == "system"
        assert "read_file" in messages[0].content
        # Original user message should follow
        assert messages[1].role == "user"
        assert messages[1].content == "hi"

    def test_returns_plain_messages_without_tools(self):
        """Helper returns unmodified messages when no tools available."""
        tm = MockToolManager(tools={})
        provider = MockProvider()
        ctx = MockChatContext(provider=provider, tool_manager=tm)
        ctx.session.add_message(Message("user", "hi"))

        messages = _build_prompt_based_messages(ctx)

        # No system message added (no tools)
        assert messages[0].role == "user"
        assert messages[0].content == "hi"


# ── Truncation recovery tests ──────────────────────────────────────


class TestTruncationRecovery:
    """Test truncated tool call recovery with stuck-loop detection (v1.16.0)."""

    @pytest.mark.asyncio
    async def test_truncated_tool_call_triggers_retry(self):
        """Single truncated tool call gets recovery message and retry."""
        # First response: truncated JSON (no closing braces)
        truncated_json = '{"tool": "apply_patch", "arguments": {"patch": "--- a.py\\n+++ b.py\\n'
        provider = MockProvider(
            responses=[
                [Event(EventType.STREAM_END, truncated_json)],
                [Event(EventType.STREAM_END, "I'll use a smaller approach instead.")],
            ],
        )
        tm = MockToolManager(tools={"apply_patch": lambda **kw: "ok"})
        ctx = MockChatContext(provider=provider, model="sonar-pro", tool_manager=tm)
        ctx.session.add_message(Message("user", "fix the file"))

        provider.facts = ModelFacts(tool_mode="prompt_based")
        events = await collect_events(ctx)

        # Should have retried (2 provider calls)
        assert len(provider.chat_calls) >= 2
        # Should have INFO event about truncation
        info_events = [e for e in events if e.type == EventType.INFO]
        assert any("Truncated tool call" in str(e.data) for e in info_events)

    @pytest.mark.asyncio
    async def test_stuck_loop_escalation_after_2_retries(self):
        """After 2 consecutive truncated retries, recovery message escalates to CRITICAL."""
        truncated_json = '{"tool": "apply_patch", "arguments": {"patch": "--- a.py\\n+++ b.py\\n'
        provider = MockProvider(
            responses=[
                [Event(EventType.STREAM_END, truncated_json)],  # 1st truncation
                [Event(EventType.STREAM_END, truncated_json)],  # 2nd truncation (escalated)
                [Event(EventType.STREAM_END, "OK I will try differently.")],  # Finally responds
            ],
        )
        tm = MockToolManager(tools={"apply_patch": lambda **kw: "ok"})
        ctx = MockChatContext(provider=provider, model="sonar-pro", tool_manager=tm)
        ctx.session.add_message(Message("user", "fix the file"))

        provider.facts = ModelFacts(tool_mode="prompt_based")
        events = await collect_events(ctx)

        # Should have 3 provider calls (2 retries + final)
        assert len(provider.chat_calls) >= 3
        # The 2nd retry should inject CRITICAL message into session
        user_msgs = [m.content for m in ctx.session.messages if m.role == "user"]
        assert any("CRITICAL" in msg for msg in user_msgs)

    @pytest.mark.asyncio
    async def test_truncation_retry_cap_emits_warning(self):
        """After MAX_TRUNCATION_RETRIES (3), emits stuck_tool_loop warning and stops retrying."""
        truncated_json = '{"tool": "apply_patch", "arguments": {"patch": "--- a.py\\n+++ b.py\\n'
        # 4 truncated responses + 1 final (the 4th truncation exceeds cap)
        provider = MockProvider(
            responses=[
                [Event(EventType.STREAM_END, truncated_json)],  # retry 1
                [Event(EventType.STREAM_END, truncated_json)],  # retry 2
                [Event(EventType.STREAM_END, truncated_json)],  # retry 3
                [Event(EventType.STREAM_END, truncated_json)],  # exceeds cap → warning
            ],
        )
        tm = MockToolManager(tools={"apply_patch": lambda **kw: "ok"})
        ctx = MockChatContext(provider=provider, model="sonar-pro", tool_manager=tm)
        ctx.session.add_message(Message("user", "fix the file"))

        provider.facts = ModelFacts(tool_mode="prompt_based")
        events = await collect_events(ctx)

        # Should emit WARNING event with stuck_tool_loop type
        warning_events = [e for e in events if e.type == EventType.WARNING]
        stuck_warnings = [
            e for e in warning_events
            if isinstance(e.data, dict) and e.data.get("type") == "stuck_tool_loop"
        ]
        assert len(stuck_warnings) >= 1
        assert "truncated" in stuck_warnings[0].data["message"]

    @pytest.mark.asyncio
    async def test_truncation_counter_resets_on_success(self):
        """Consecutive truncation counter resets when a non-truncated response arrives."""
        truncated_json = '{"tool": "apply_patch", "arguments": {"patch": "--- a.py\\n+++ b.py\\n'
        provider = MockProvider(
            responses=[
                [Event(EventType.STREAM_END, truncated_json)],  # retry 1
                [Event(EventType.STREAM_END, "Here is my answer without tools.")],  # success
            ],
        )
        tm = MockToolManager(tools={"apply_patch": lambda **kw: "ok"})
        ctx = MockChatContext(provider=provider, model="sonar-pro", tool_manager=tm)
        ctx.session.add_message(Message("user", "fix the file"))

        provider.facts = ModelFacts(tool_mode="prompt_based")
        events = await collect_events(ctx)

        # Should complete successfully (2 calls, no stuck_tool_loop warning)
        assert len(provider.chat_calls) == 2
        warning_events = [
            e for e in events
            if e.type == EventType.WARNING and isinstance(e.data, dict)
            and e.data.get("type") == "stuck_tool_loop"
        ]
        assert len(warning_events) == 0
        # Should have a STREAM_END with the final answer
        end_events = [e for e in events if e.type == EventType.STREAM_END]
        assert any("answer" in str(e.data) for e in end_events)
