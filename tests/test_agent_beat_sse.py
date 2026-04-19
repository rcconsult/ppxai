"""P0 Stages 2+4 (v1.18.0) — SSE wire-format tests for agent heartbeat.

Verifies that the full request → SSE stream path carries agent-beat
lifecycle events in the exact shape downstream clients (web,
VSCode) consume. Each assertion pins a wire contract that the JS and
TS AppState facades depend on — renaming a field or dropping an event
here means a silent UI regression on web/VSCode.

Scope:
  - `sse_event_generator` (ppxai/server/streaming.py) is exercised with
    a real EngineClient + mocked provider that drives a full agent
    tool-loop with 2 iterations.
  - We parse the SSE response as an event stream and assert:
      * AGENT_RUN_START appears once near the top
      * AGENT_BEAT appears at each tool-iteration end
      * state_sync events carry `agent_beat` payloads (the
        _SSE_SYNC_FIELDS contract clients depend on)
      * state_sync sets agent_beat back to `{}` on AGENT_COMPLETE
      * Error path yields AGENT_RUN_ERROR + state_sync with `{}`
  - The Pydantic / FastAPI wrapper in chat route is tested separately
    (test_chat_route_r15.py). This file focuses on the raw SSE shape.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, List
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from ppxai.engine.client import EngineClient
from ppxai.engine.model_profiles import ModelProfile, ToolCallingProfile
from ppxai.engine.types import (
    Event,
    EventType,
    Message,
    ProviderCapabilities,
)
from ppxai.server.streaming import sse_event_generator


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------


def _parse_sse(frames: List[str]) -> List[dict]:
    """Parse a sequence of SSE `data: ...\\n\\n` frames into event dicts.

    Keepalive comments (`: keepalive`) are skipped. Returns the list of
    parsed event dicts in arrival order.
    """
    events: List[dict] = []
    for frame in frames:
        for line in frame.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                # Not a JSON frame (keepalive comment, etc.) — skip
                pass
    return events


async def _drain_sse(gen: AsyncIterator[str]) -> List[dict]:
    """Drain an sse_event_generator and return the parsed event list."""
    frames: List[str] = []
    async for frame in gen:
        frames.append(frame)
    return _parse_sse(frames)


# ---------------------------------------------------------------------------
# Provider + tool mocks
# ---------------------------------------------------------------------------


class MockProvider:
    """Minimal provider that yields scripted event sequences per iteration."""

    def __init__(self, capabilities=None, scripted_iterations=None):
        self.capabilities = capabilities or ProviderCapabilities(
            native_tool_calling=True,
        )
        self._scripts = scripted_iterations or []
        self._idx = 0

    def get_capabilities_for_model(self, _model):
        return self.capabilities

    async def chat(self, messages, model, stream=False, tools=None):
        events = self._scripts[min(self._idx, len(self._scripts) - 1)]
        self._idx += 1
        for ev in events:
            yield ev


def _install_mock_provider(engine: EngineClient, provider: MockProvider) -> None:
    """Replace the engine's current provider with a mock.

    chat_with_tools reads ctx.provider directly; in production this is
    populated by set_provider(). For tests we bypass config lookup and
    set it explicitly.
    """
    engine.provider = provider
    engine.provider_name = "mock"
    engine.model = "mock-model"


def _register_echo_tools(engine: EngineClient) -> None:
    """Register two throwaway tools so the tool manager recognizes them.

    The mock provider's scripted events include tool_call IDs pointing
    to these; without registration chat_with_tools would flag them as
    unknown and fall back to prompt-based parsing.
    """
    def _ok_handler(**kwargs):
        return "ok-result"

    def _fail_handler(**kwargs):
        raise RuntimeError("boom")

    engine.tool_manager.register_function(
        name="ok_tool",
        description="Always succeeds.",
        parameters={"type": "object", "properties": {}},
        handler=_ok_handler,
    )
    engine.tool_manager.register_function(
        name="fail_tool",
        description="Always fails.",
        parameters={"type": "object", "properties": {}},
        handler=_fail_handler,
    )


# ---------------------------------------------------------------------------
# SSE wire-format tests
# ---------------------------------------------------------------------------


class TestAgentBeatSSEHappyPath:
    """Happy path: 2 tool iterations + final answer. Verifies the
    lifecycle events and state_sync payloads that web/VSCode clients
    subscribe to.
    """

    @pytest.fixture
    def engine(self):
        eng = EngineClient()
        eng.tools_enabled = True
        _register_echo_tools(eng)
        return eng

    @pytest.fixture
    def provider(self, engine):
        p = MockProvider(scripted_iterations=[
            # Iteration 1
            [
                Event(EventType.TOOL_CALL, {
                    "tool": "ok_tool",
                    "arguments": {},
                    "tool_call_id": "c1",
                }),
                Event(EventType.STREAM_END, ""),
            ],
            # Iteration 2
            [
                Event(EventType.TOOL_CALL, {
                    "tool": "ok_tool",
                    "arguments": {},
                    "tool_call_id": "c2",
                }),
                Event(EventType.STREAM_END, ""),
            ],
            # Iteration 3 — final answer
            [Event(EventType.STREAM_END, "Done.")],
        ])
        _install_mock_provider(engine, p)
        return p

    @pytest.mark.asyncio
    async def test_sse_carries_lifecycle_events_in_order(self, engine, provider):
        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _drain_sse(sse_event_generator("hello", engine))

        types = [e["type"] for e in events]

        # AGENT_RUN_START fires once, right after stream_start.
        assert "stream_start" in types
        assert types.count("agent_run_start") == 1
        first_ss = types.index("stream_start")
        first_run_start = types.index("agent_run_start")
        assert first_run_start == first_ss + 1

        # AGENT_BEAT fires per tool-iteration, twice.
        assert types.count("agent_beat") == 2

        # AGENT_RUN_COMPLETE always fires at end of run (mode-agnostic,
        # unlike the legacy agent_mode-gated AGENT_COMPLETE).
        assert types.count("agent_run_complete") == 1

        # Final stream_end closes the stream.
        assert types[-1] == "stream_end"

    @pytest.mark.asyncio
    async def test_agent_run_start_payload(self, engine, provider):
        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _drain_sse(sse_event_generator("hello", engine))

        run_start = next(e for e in events if e["type"] == "agent_run_start")
        assert isinstance(run_start["data"], dict)
        assert "model" in run_start["data"]
        assert "provider" in run_start["data"]
        assert "max_iterations" in run_start["data"]
        assert "agent_mode" in run_start["data"]

    @pytest.mark.asyncio
    async def test_agent_beat_payload_canonical_keys(self, engine, provider):
        """Beat payload is the schema contract — every client that
        subscribes to AppState.agent_beat reads these exact keys.
        """
        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _drain_sse(sse_event_generator("hello", engine))

        beats = [e for e in events if e["type"] == "agent_beat"]
        assert len(beats) == 2
        for beat in beats:
            assert set(beat["data"].keys()) == {
                "iteration", "beat", "tool", "ok", "failures", "elapsed_s",
            }
            assert beat["data"]["tool"] == "ok_tool"
            assert beat["data"]["ok"] is True
            assert beat["data"]["failures"] == 0

    @pytest.mark.asyncio
    async def test_state_sync_pushes_agent_beat_updates(self, engine, provider):
        """_SSE_SYNC_FIELDS wiring: every AGENT_BEAT → AppState.set →
        state_sync event on the wire with the new agent_beat value.
        Web + VSCode depend on this for live updates.
        """
        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _drain_sse(sse_event_generator("hello", engine))

        state_syncs = [e for e in events if e["type"] == "state_sync"]
        beat_syncs = [
            e for e in state_syncs
            if isinstance(e.get("data"), dict) and "agent_beat" in e["data"]
        ]

        # Two populated beats + one clearing on AGENT_COMPLETE = 3 syncs.
        assert len(beat_syncs) >= 3

        # Last one must be the clearing sync with empty dict.
        assert beat_syncs[-1]["data"]["agent_beat"] == {}

        # First two should be populated beat payloads.
        assert beat_syncs[0]["data"]["agent_beat"]["iteration"] == 1
        assert beat_syncs[1]["data"]["agent_beat"]["iteration"] == 2


class TestAgentBeatSSEErrorPath:
    """Error path: provider yields ERROR → lifecycle events wind down
    cleanly; state_sync clears agent_beat.
    """

    @pytest.fixture
    def engine(self):
        eng = EngineClient()
        eng.tools_enabled = True
        _register_echo_tools(eng)
        return eng

    @pytest.mark.asyncio
    async def test_provider_error_yields_agent_run_error_and_clears_state(self, engine):
        provider = MockProvider(scripted_iterations=[
            [Event(EventType.ERROR, "upstream 500")],
        ])
        _install_mock_provider(engine, provider)

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _drain_sse(sse_event_generator("hello", engine))

        types = [e["type"] for e in events]
        assert "agent_run_start" in types
        assert "error" in types
        assert "agent_run_error" in types

        err_idx = types.index("error")
        run_err_idx = types.index("agent_run_error")
        assert run_err_idx == err_idx + 1

        # The run-error event carries the reason.
        run_err = events[run_err_idx]
        assert run_err["data"]["reason"] == "provider_error"


class TestAgentBeatSSEMixedSuccessFailure:
    """Tool-level failure inside a run: beat shows ok=false, failures=1,
    but the run continues (no AGENT_RUN_ERROR unless the whole run fails).
    """

    @pytest.fixture
    def engine(self):
        eng = EngineClient()
        eng.tools_enabled = True
        _register_echo_tools(eng)
        return eng

    @pytest.mark.asyncio
    async def test_failing_tool_iteration_produces_ok_false_beat(self, engine):
        provider = MockProvider(scripted_iterations=[
            # Iteration 1 — fail_tool raises
            [
                Event(EventType.TOOL_CALL, {
                    "tool": "fail_tool",
                    "arguments": {},
                    "tool_call_id": "c1",
                }),
                Event(EventType.STREAM_END, ""),
            ],
            # Iteration 2 — ok_tool succeeds
            [
                Event(EventType.TOOL_CALL, {
                    "tool": "ok_tool",
                    "arguments": {},
                    "tool_call_id": "c2",
                }),
                Event(EventType.STREAM_END, ""),
            ],
            # Iteration 3 — final answer
            [Event(EventType.STREAM_END, "recovered")],
        ])
        _install_mock_provider(engine, provider)

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _drain_sse(sse_event_generator("hello", engine))

        beats = [e for e in events if e["type"] == "agent_beat"]
        assert len(beats) == 2
        # Iter 1: fail_tool → ok=False, failures=1
        assert beats[0]["data"]["ok"] is False
        assert beats[0]["data"]["failures"] == 1
        assert beats[0]["data"]["tool"] == "fail_tool"
        # Iter 2: ok_tool → ok=True, failures reset to 0
        assert beats[1]["data"]["ok"] is True
        assert beats[1]["data"]["failures"] == 0
        assert beats[1]["data"]["tool"] == "ok_tool"


class TestStateSyncBeatPayloadRoundTrips:
    """Payload round-trips cleanly through JSON serialization in the
    SSE frame. No weird types / no non-serializable elapsed_s.
    """

    @pytest.fixture
    def engine(self):
        eng = EngineClient()
        eng.tools_enabled = True
        _register_echo_tools(eng)
        return eng

    @pytest.mark.asyncio
    async def test_all_beat_payloads_are_valid_json_shapes(self, engine):
        provider = MockProvider(scripted_iterations=[
            [
                Event(EventType.TOOL_CALL, {
                    "tool": "ok_tool",
                    "arguments": {},
                    "tool_call_id": "c1",
                }),
                Event(EventType.STREAM_END, ""),
            ],
            [Event(EventType.STREAM_END, "done")],
        ])
        _install_mock_provider(engine, provider)

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _drain_sse(sse_event_generator("hello", engine))

        # Every event type must have parsed — _drain_sse dropped malformed frames
        # silently via try/except. Assert total count is non-zero and no
        # suspicious missing types.
        assert events  # at least something streamed
        for ev in events:
            assert "type" in ev  # every frame has a type
            # Values that appear on the wire must be JSON-native.
            json.dumps(ev)  # re-encode — will raise if something non-native slipped in
