"""P0 Stages 2 + 4 (v1.18.0) — agent heartbeat emission + AppState wiring.

Verifies the full path:

    engine.chat() running chat_with_tools
        → emits AGENT_RUN_START once at top
        → emits AGENT_BEAT at end of each tool-iteration
        → emits AGENT_RUN_ERROR on interrupt / provider errors
        → _chat_with_tools in EngineClient intercepts AGENT_BEAT to
          populate AppState.agent_beat field
        → _SSE_SYNC_FIELDS contract pushes agent_beat to web/VSCode

Each stage-gate is pinned here so that renaming any EventType, moving
the emission site, or changing the AgentBeatState wire shape trips a
specific test rather than silently breaking downstream clients.

Uses the same MockProvider/MockToolManager/MockChatContext fixtures
already used elsewhere in the suite (see test_tool_messages.py).
"""

import json
from unittest.mock import patch

import pytest

from ppxai.engine.chat import chat_with_tools
from ppxai.engine.session import SessionManager
from ppxai.engine.types import (
    AgentBeatState,
    Event,
    EventType,
    Message,
    ProviderCapabilities,
)
from ppxai.engine.model_profiles import ModelProfile, ToolCallingProfile


class MockProvider:
    def __init__(self, capabilities=None, responses=None):
        self.capabilities = capabilities or ProviderCapabilities()
        self._responses = responses or []
        self._call_count = 0

    def get_capabilities_for_model(self, model):
        return self.capabilities

    async def chat(self, messages, model, stream=False, tools=None):
        idx = min(self._call_count, len(self._responses) - 1)
        events = self._responses[idx] if self._responses else []
        self._call_count += 1
        for event in events:
            yield event


class MockToolManager:
    def __init__(self, tools=None, loop_on=None):
        self.max_iterations = 15
        self.auto_retry_empty = 0
        self.max_same_tool_calls = 3
        self._tools = tools or {}
        self._loop_on = loop_on
        self._recorded_calls = []

    def reset_tool_history(self):
        self._recorded_calls = []

    def get_tools_openai_format(self):
        return [{"type": "function", "function": {"name": n}} for n in self._tools]

    def get_tools_prompt(self, working_dir=None):
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
    def __init__(self, provider=None, model="test-model", tool_manager=None):
        self._provider = provider or MockProvider()
        self._model = model
        self._session = SessionManager()
        self._tool_manager = tool_manager or MockToolManager()
        self._interrupted = False
        self._consent_events = []
        self._current_tool_usage = {}

    @property
    def provider(self): return self._provider
    @property
    def provider_name(self): return "test"
    @property
    def model(self): return self._model
    @property
    def session(self): return self._session
    @property
    def tool_manager(self): return self._tool_manager
    @property
    def is_interrupted(self): return self._interrupted
    def get_consent_events(self):
        evs = self._consent_events[:]
        self._consent_events.clear()
        return evs
    def track_tool_usage(self, *_args, **_kwargs): pass
    @property
    def agent_mode(self): return False
    def commit_agent_changes_if_needed(self, *_args, **_kwargs): return None
    def get_bootstrap_prompt(self): return ""
    def get_working_dir(self): return "/tmp/test"


async def _collect(ctx, stream=False):
    events = []
    async for ev in chat_with_tools(ctx, stream):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Stage 2 — emission order + payload shape
# ---------------------------------------------------------------------------


class TestAgentLifecycleEmission:
    """AGENT_RUN_START, AGENT_BEAT, AGENT_RUN_ERROR fire at the right
    moments with the right payloads.
    """

    @pytest.mark.asyncio
    async def test_run_start_fires_once_at_top(self):
        """AGENT_RUN_START must fire exactly once — immediately after
        STREAM_START, before any tool iteration.
        """
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[[Event(EventType.STREAM_END, "Done.")]],
        )
        ctx = MockChatContext(provider=provider, model="test")
        ctx.session.add_message(Message("user", "hello"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        run_starts = [e for e in events if e.type == EventType.AGENT_RUN_START]
        assert len(run_starts) == 1

        # Must come before any other iteration-level event.
        types = [e.type for e in events]
        first_stream_idx = types.index(EventType.STREAM_START)
        run_start_idx = types.index(EventType.AGENT_RUN_START)
        assert run_start_idx == first_stream_idx + 1

    @pytest.mark.asyncio
    async def test_run_start_payload_shape(self):
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[[Event(EventType.STREAM_END, "Done.")]],
        )
        ctx = MockChatContext(provider=provider, model="test-model-v3")
        ctx.session.add_message(Message("user", "hello"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        run_start = next(e for e in events if e.type == EventType.AGENT_RUN_START)
        assert isinstance(run_start.data, dict)
        assert run_start.data["model"] == "test-model-v3"
        assert run_start.data["provider"] == "test"
        assert "max_iterations" in run_start.data
        assert run_start.data["agent_mode"] is False

    @pytest.mark.asyncio
    async def test_beat_fires_per_tool_iteration(self):
        """Two tool iterations → exactly two AGENT_BEAT events."""
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                # Iteration 1: tool call
                [
                    Event(EventType.TOOL_CALL, {
                        "tool": "read_file",
                        "arguments": {"path": "a"},
                        "tool_call_id": "c1",
                    }),
                    Event(EventType.STREAM_END, ""),
                ],
                # Iteration 2: tool call
                [
                    Event(EventType.TOOL_CALL, {
                        "tool": "read_file",
                        "arguments": {"path": "b"},
                        "tool_call_id": "c2",
                    }),
                    Event(EventType.STREAM_END, ""),
                ],
                # Iteration 3: final answer (no tool call)
                [Event(EventType.STREAM_END, "Done.")],
            ],
        )
        tm = MockToolManager(tools={"read_file": lambda path="": f"body of {path}"})
        ctx = MockChatContext(provider=provider, model="t", tool_manager=tm)
        ctx.session.add_message(Message("user", "read a and b"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        beats = [e for e in events if e.type == EventType.AGENT_BEAT]
        assert len(beats) == 2  # two tool iterations, not the final-answer iter

    @pytest.mark.asyncio
    async def test_beat_payload_matches_canonical_wire_shape(self):
        """AGENT_BEAT payload has every field from AgentBeatState.as_event_data()."""
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                [
                    Event(EventType.TOOL_CALL, {
                        "tool": "read_file",
                        "arguments": {"path": "a"},
                        "tool_call_id": "c1",
                    }),
                    Event(EventType.STREAM_END, ""),
                ],
                [Event(EventType.STREAM_END, "Done.")],
            ],
        )
        tm = MockToolManager(tools={"read_file": lambda path="": "body"})
        ctx = MockChatContext(provider=provider, model="t", tool_manager=tm)
        ctx.session.add_message(Message("user", "read a"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        beat = next(e for e in events if e.type == EventType.AGENT_BEAT)
        assert set(beat.data.keys()) == {
            "iteration", "beat", "tool", "ok", "failures", "elapsed_s",
        }
        assert beat.data["iteration"] == 1
        assert beat.data["beat"] == 1
        assert beat.data["tool"] == "read_file"
        assert beat.data["ok"] is True
        assert beat.data["failures"] == 0
        assert beat.data["elapsed_s"] >= 0

    @pytest.mark.asyncio
    async def test_beat_resets_failures_on_success(self):
        """Mix of failing + succeeding iterations → consecutive_failures
        counter resets on each success. Zombie detection depends on this
        invariant.
        """
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[
                # Iter 1: tool fails
                [
                    Event(EventType.TOOL_CALL, {
                        "tool": "fails",
                        "arguments": {},
                        "tool_call_id": "c1",
                    }),
                    Event(EventType.STREAM_END, ""),
                ],
                # Iter 2: tool succeeds
                [
                    Event(EventType.TOOL_CALL, {
                        "tool": "ok_tool",
                        "arguments": {},
                        "tool_call_id": "c2",
                    }),
                    Event(EventType.STREAM_END, ""),
                ],
                # Iter 3: final answer
                [Event(EventType.STREAM_END, "Done.")],
            ],
        )

        def failing_tool():
            raise RuntimeError("boom")

        tm = MockToolManager(tools={
            "fails": failing_tool,
            "ok_tool": lambda: "success",
        })
        ctx = MockChatContext(provider=provider, model="t", tool_manager=tm)
        ctx.session.add_message(Message("user", "retry"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        beats = [e for e in events if e.type == EventType.AGENT_BEAT]
        assert len(beats) == 2
        assert beats[0].data["ok"] is False
        assert beats[0].data["failures"] == 1
        # Iter 2 succeeded → counter resets
        assert beats[1].data["ok"] is True
        assert beats[1].data["failures"] == 0

    @pytest.mark.asyncio
    async def test_run_error_fires_on_provider_error(self):
        """Provider yielding an ERROR event → AGENT_RUN_ERROR follows
        before the generator returns.
        """
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[[Event(EventType.ERROR, "upstream 500")]],
        )
        ctx = MockChatContext(provider=provider, model="t")
        ctx.session.add_message(Message("user", "hi"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        # ERROR preceded by AGENT_RUN_START, followed by AGENT_RUN_ERROR
        types = [e.type for e in events]
        assert EventType.AGENT_RUN_START in types
        assert EventType.ERROR in types
        assert EventType.AGENT_RUN_ERROR in types
        err_idx = types.index(EventType.ERROR)
        run_err_idx = types.index(EventType.AGENT_RUN_ERROR)
        assert run_err_idx == err_idx + 1

        run_err = events[run_err_idx]
        assert run_err.data["reason"] == "provider_error"
        assert "iteration" in run_err.data
        assert "elapsed_s" in run_err.data

    @pytest.mark.asyncio
    async def test_run_error_fires_on_interrupt_at_iteration_top(self):
        """Interrupt before the first iteration → AGENT_RUN_ERROR with
        reason='interrupted'.
        """
        provider = MockProvider(
            capabilities=ProviderCapabilities(native_tool_calling=True),
            responses=[[Event(EventType.STREAM_END, "unused")]],
        )
        ctx = MockChatContext(provider=provider, model="t")
        ctx.session.add_message(Message("user", "hi"))
        ctx._interrupted = True  # simulate user hitting Escape

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        types = [e.type for e in events]
        assert EventType.AGENT_RUN_ERROR in types
        run_err = next(e for e in events if e.type == EventType.AGENT_RUN_ERROR)
        assert run_err.data["reason"] == "interrupted"


# ---------------------------------------------------------------------------
# Stage 4 — AppState schema + EngineClient wiring
# ---------------------------------------------------------------------------


class TestAppStateSchemaField:
    """The `agent_beat` schema field must load with the right shape and
    default, and mutate correctly on set().
    """

    def test_agent_beat_field_loads_from_schema(self):
        from ppxai.engine.app_state import AppState
        assert "agent_beat" in AppState.FIELDS
        assert AppState.FIELDS["agent_beat"] == {}

    def test_agent_beat_default_is_empty_dict(self):
        from ppxai.engine.app_state import AppState
        state = AppState()
        assert state.get("agent_beat") == {}

    def test_agent_beat_setter_fires_listener(self):
        from ppxai.engine.app_state import AppState
        state = AppState()
        received = []
        state.on("agent_beat", lambda v: received.append(v))
        payload = {
            "iteration": 1, "beat": 1, "tool": "read_file",
            "ok": True, "failures": 0, "elapsed_s": 0.1,
        }
        state.set("agent_beat", payload)
        assert received == [payload]

    def test_agent_beat_mutable_default_not_shared(self):
        """Each AppState instance must get its own dict copy — otherwise
        mutating on one instance would leak to others (classic mutable-
        default bug; already asserted for context_attachments).
        """
        from ppxai.engine.app_state import AppState
        a = AppState()
        b = AppState()
        a.get("agent_beat")["iteration"] = 1
        assert b.get("agent_beat") == {}


class TestEngineClientWiresAgentBeat:
    """EngineClient._chat_with_tools intercepts lifecycle events and
    keeps AppState.agent_beat in sync.
    """

    @pytest.mark.asyncio
    async def test_agent_beat_field_updates_during_run(self):
        from ppxai.engine.client import EngineClient

        # Use a real EngineClient but swap in a mock chat_with_tools
        # that yields the lifecycle events we want to test.
        engine = EngineClient()
        engine.tools_enabled = True

        captured_states = []
        engine.state.on(
            "agent_beat",
            lambda v: captured_states.append(dict(v) if v else {}),
        )

        async def fake_generator(_ctx, _stream):
            yield Event(EventType.AGENT_RUN_START, {"model": "t"})
            yield Event(EventType.AGENT_BEAT, {
                "iteration": 1, "beat": 1, "tool": "read_file",
                "ok": True, "failures": 0, "elapsed_s": 0.5,
            })
            yield Event(EventType.AGENT_BEAT, {
                "iteration": 2, "beat": 2, "tool": "apply_patch",
                "ok": True, "failures": 0, "elapsed_s": 1.2,
            })
            yield Event(EventType.AGENT_RUN_COMPLETE, {
                "iterations": 2, "elapsed_s": 1.5,
            })
            yield Event(EventType.STREAM_END, "done")

        with patch("ppxai.engine.client.chat_with_tools", fake_generator):
            events = []
            async for ev in engine._chat_with_tools(stream=False):
                events.append(ev)

        # Observed mutations: two beat states → empty on AGENT_RUN_COMPLETE
        assert len(captured_states) >= 3
        assert captured_states[0]["iteration"] == 1
        assert captured_states[1]["iteration"] == 2
        assert captured_states[-1] == {}  # cleared on AGENT_RUN_COMPLETE

    @pytest.mark.asyncio
    async def test_agent_beat_field_cleared_on_run_error(self):
        from ppxai.engine.client import EngineClient

        engine = EngineClient()
        engine.tools_enabled = True
        # Prime state so we can observe the clearing.
        engine.state.set("agent_beat", {"iteration": 3, "beat": 5})

        async def fake_generator(_ctx, _stream):
            yield Event(EventType.AGENT_RUN_ERROR, {
                "reason": "provider_error",
                "iteration": 3,
                "elapsed_s": 2.1,
            })

        with patch("ppxai.engine.client.chat_with_tools", fake_generator):
            events = []
            async for ev in engine._chat_with_tools(stream=False):
                events.append(ev)

        assert engine.state.get("agent_beat") == {}
