"""P0 Stage 3 (v1.18.0) — zombie detection / circuit breaker.

Verifies the tool-loop circuit breaker:

  - below the threshold: consecutive failures keep accumulating; no
    AGENT_ZOMBIE event, the loop continues to the next iteration.
  - at the threshold: AGENT_ZOMBIE fires, AGENT_RUN_ERROR follows,
    the loop exits (no further AGENT_BEAT events).
  - threshold=0: zombie detection disabled; failures accumulate
    indefinitely up to max_iterations.
  - a success after a streak of failures resets the counter; the
    breaker doesn't trip from a now-stale failure count.
  - config flows through — `tools.agent.zombie_threshold` from
    ppxai-config.json is what the engine uses.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.chat import chat_with_tools
from ppxai.engine.session import SessionManager
from ppxai.engine.types import (
    Event,
    EventType,
    Message,
    ProviderCapabilities,
)
from ppxai.engine.model_profiles import ModelProfile, ToolCallingProfile


class MockProvider:
    def __init__(self, capabilities=None, scripted=None):
        self.capabilities = capabilities or ProviderCapabilities(
            native_tool_calling=True,
        )
        self._scripts = scripted or []
        self._idx = 0

    def get_capabilities_for_model(self, _model):
        return self.capabilities

    async def chat(self, messages, model, stream=False, tools=None):
        events = self._scripts[min(self._idx, len(self._scripts) - 1)]
        self._idx += 1
        for ev in events:
            yield ev


class MockToolManager:
    def __init__(self, tools=None):
        self.max_iterations = 15
        self.auto_retry_empty = 0
        self.max_same_tool_calls = 3
        self._tools = tools or {}
        self._recorded = []

    def reset_tool_history(self): self._recorded = []
    def get_tools_openai_format(self):
        return [{"type": "function", "function": {"name": n}} for n in self._tools]
    def get_tools_prompt(self, working_dir=None): return ""
    def get_tool(self, name): return self._tools.get(name)
    def is_tool_loop_detected(self, name, args): return False
    def record_tool_call(self, name, args): self._recorded.append((name, args))
    async def execute_tool(self, name, **kwargs):
        tool = self._tools.get(name)
        if callable(tool):
            return tool(**kwargs)
        return f"Result from {name}"
    def get_tool_display_limit(self, tn, ta): return 4000
    def get_loop_message(self, tn): return f"Stop {tn}"


class MockChatContext:
    def __init__(self, provider=None, tool_manager=None):
        self._provider = provider or MockProvider()
        self._session = SessionManager()
        self._tool_manager = tool_manager or MockToolManager()
        self._interrupted = False
        self._current_tool_usage = {}

    @property
    def provider(self): return self._provider
    @property
    def provider_name(self): return "test"
    @property
    def model(self): return "test-model"
    @property
    def session(self): return self._session
    @property
    def tool_manager(self): return self._tool_manager
    @property
    def is_interrupted(self): return self._interrupted
    def get_consent_events(self): return []
    def track_tool_usage(self, *a, **kw): pass
    @property
    def agent_mode(self): return False
    def commit_agent_changes_if_needed(self, *a, **kw): return None
    def get_bootstrap_prompt(self): return ""
    def get_working_dir(self): return "/tmp/test"


def _fail_response(tool_name="fail_tool", call_id="c"):
    """Provider response that emits one failing tool_call."""
    return [
        Event(EventType.TOOL_CALL, {
            "tool": tool_name, "arguments": {}, "tool_call_id": call_id,
        }),
        Event(EventType.STREAM_END, ""),
    ]


def _ok_response(tool_name="ok_tool", call_id="c"):
    return [
        Event(EventType.TOOL_CALL, {
            "tool": tool_name, "arguments": {}, "tool_call_id": call_id,
        }),
        Event(EventType.STREAM_END, ""),
    ]


async def _collect(ctx, stream=False):
    out = []
    async for ev in chat_with_tools(ctx, stream):
        out.append(ev)
    return out


def _failing_tool():
    raise RuntimeError("boom")


def _ok_tool():
    return "fine"


# ---------------------------------------------------------------------------
# Threshold behavior
# ---------------------------------------------------------------------------


class TestZombieDetectionAtDefaultThreshold:
    """Default threshold is 3. Three consecutive failing iterations
    should trip the breaker; two should not.
    """

    @pytest.mark.asyncio
    async def test_below_threshold_no_zombie_event(self):
        # 2 failing iterations (threshold is 3), then a successful
        # final answer. Should NOT trip — failures=2 < 3.
        provider = MockProvider(scripted=[
            _fail_response("fails", "c1"),
            _fail_response("fails", "c2"),
            [Event(EventType.STREAM_END, "Giving up, here's text.")],
        ])
        tm = MockToolManager(tools={"fails": _failing_tool, "ok": _ok_tool})
        ctx = MockChatContext(provider=provider, tool_manager=tm)
        ctx.session.add_message(Message("user", "try"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        types = [e.type for e in events]
        assert EventType.AGENT_ZOMBIE not in types
        # Normal completion via AGENT_RUN_COMPLETE
        assert EventType.AGENT_RUN_COMPLETE in types
        # 2 beats emitted, both ok=False
        beats = [e for e in events if e.type == EventType.AGENT_BEAT]
        assert len(beats) == 2
        assert all(b.data["ok"] is False for b in beats)

    @pytest.mark.asyncio
    async def test_at_threshold_zombie_fires_and_loop_exits(self):
        # 3 consecutive failing iterations should trip at the 3rd beat.
        provider = MockProvider(scripted=[
            _fail_response("fails", "c1"),
            _fail_response("fails", "c2"),
            _fail_response("fails", "c3"),
            # If the breaker DIDN'T fire, a 4th iteration would also
            # receive a response. This one would complete normally.
            [Event(EventType.STREAM_END, "unreachable")],
        ])
        tm = MockToolManager(tools={"fails": _failing_tool})
        ctx = MockChatContext(provider=provider, tool_manager=tm)
        ctx.session.add_message(Message("user", "retry"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        types = [e.type for e in events]
        assert EventType.AGENT_ZOMBIE in types
        assert EventType.AGENT_RUN_ERROR in types

        # No AGENT_RUN_COMPLETE — the breaker exits via AGENT_RUN_ERROR
        # (reason=zombie) instead.
        assert EventType.AGENT_RUN_COMPLETE not in types

        # Ordering — zombie event immediately before run_error.
        zombie_idx = types.index(EventType.AGENT_ZOMBIE)
        run_err_idx = types.index(EventType.AGENT_RUN_ERROR)
        assert run_err_idx == zombie_idx + 1

        # Only 3 beats emitted (no 4th — loop exited).
        beats = [e for e in events if e.type == EventType.AGENT_BEAT]
        assert len(beats) == 3
        assert beats[-1].data["failures"] == 3

    @pytest.mark.asyncio
    async def test_zombie_payload_has_context(self):
        provider = MockProvider(scripted=[
            _fail_response("fails", "c1"),
            _fail_response("fails", "c2"),
            _fail_response("fails", "c3"),
            [Event(EventType.STREAM_END, "unreachable")],
        ])
        tm = MockToolManager(tools={"fails": _failing_tool})
        ctx = MockChatContext(provider=provider, tool_manager=tm)
        ctx.session.add_message(Message("user", "retry"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        zombie = next(e for e in events if e.type == EventType.AGENT_ZOMBIE)
        assert "reason" in zombie.data
        assert "3 consecutive tool failures" in zombie.data["reason"]
        assert zombie.data["threshold"] == 3
        assert zombie.data["last_tool"] == "fails"
        assert zombie.data["iteration"] == 3
        assert "elapsed_s" in zombie.data


class TestZombieDetectionResetsOnSuccess:
    """A successful iteration after 2 failures must reset the counter
    below the threshold so the breaker does NOT trip on a later single
    failure. Prevents false-positives on long-running recoverable runs.
    """

    @pytest.mark.asyncio
    async def test_success_resets_counter_preventing_trip(self):
        # Sequence: fail, fail, SUCCEED, fail, fail — should NOT trip
        # (max failures=2 after the success, but threshold is 3).
        provider = MockProvider(scripted=[
            _fail_response("fails", "c1"),
            _fail_response("fails", "c2"),
            _ok_response("ok", "c3"),    # resets consecutive_failures to 0
            _fail_response("fails", "c4"),
            _fail_response("fails", "c5"),
            [Event(EventType.STREAM_END, "done")],
        ])
        tm = MockToolManager(tools={"fails": _failing_tool, "ok": _ok_tool})
        ctx = MockChatContext(provider=provider, tool_manager=tm)
        ctx.session.add_message(Message("user", "long recovery"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            events = await _collect(ctx)

        types = [e.type for e in events]
        assert EventType.AGENT_ZOMBIE not in types
        assert EventType.AGENT_RUN_COMPLETE in types

        beats = [e for e in events if e.type == EventType.AGENT_BEAT]
        # Verify the reset — beat[2] is the ok run, failures=0 there.
        assert len(beats) == 5
        assert beats[2].data["ok"] is True
        assert beats[2].data["failures"] == 0
        assert beats[3].data["failures"] == 1  # counts from the reset
        assert beats[4].data["failures"] == 2


class TestZombieThresholdZeroDisables:
    """threshold=0 via config disables zombie detection entirely — the
    run continues to max_iterations even with sustained failures.
    """

    @pytest.mark.asyncio
    async def test_threshold_zero_disables_circuit_breaker(self):
        provider = MockProvider(scripted=[
            _fail_response("fails", "c1"),
            _fail_response("fails", "c2"),
            _fail_response("fails", "c3"),
            _fail_response("fails", "c4"),
            [Event(EventType.STREAM_END, "finally done")],
        ])
        tm = MockToolManager(tools={"fails": _failing_tool})
        ctx = MockChatContext(provider=provider, tool_manager=tm)
        ctx.session.add_message(Message("user", "retry"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile, \
             patch("ppxai.engine.chat._get_zombie_threshold") as mock_threshold:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            mock_threshold.return_value = 0
            events = await _collect(ctx)

        types = [e.type for e in events]
        assert EventType.AGENT_ZOMBIE not in types
        # Ran all 4 failing iterations + final answer → AGENT_RUN_COMPLETE
        assert EventType.AGENT_RUN_COMPLETE in types


class TestZombieThresholdFromConfig:
    """The threshold resolves through get_agent_config(), so overriding
    `tools.agent.zombie_threshold` in config actually changes behavior.
    """

    @pytest.mark.asyncio
    async def test_custom_threshold_trips_early(self):
        """Setting threshold=2 should trip after 2 failures, not 3."""
        provider = MockProvider(scripted=[
            _fail_response("fails", "c1"),
            _fail_response("fails", "c2"),
            # Would continue if breaker didn't fire.
            [Event(EventType.STREAM_END, "unreachable")],
        ])
        tm = MockToolManager(tools={"fails": _failing_tool})
        ctx = MockChatContext(provider=provider, tool_manager=tm)
        ctx.session.add_message(Message("user", "retry"))

        with patch("ppxai.engine.chat.get_profile") as mock_profile, \
             patch("ppxai.engine.chat._get_zombie_threshold") as mock_threshold:
            mock_profile.return_value = ModelProfile(
                tool_calling=ToolCallingProfile(mode="native"),
            )
            mock_threshold.return_value = 2
            events = await _collect(ctx)

        types = [e.type for e in events]
        assert EventType.AGENT_ZOMBIE in types
        # Exactly 2 beats then the trip.
        beats = [e for e in events if e.type == EventType.AGENT_BEAT]
        assert len(beats) == 2


# ---------------------------------------------------------------------------
# Config path tests — verify the threshold resolves correctly
# ---------------------------------------------------------------------------


class TestAgentConfigIncludesZombieThreshold:
    """get_agent_config() must include zombie_threshold, default 3,
    override-able via ppxai-config.json.
    """

    def test_default_is_three(self):
        from ppxai.config import get_agent_config
        cfg = get_agent_config()
        assert cfg["zombie_threshold"] == 3

    def test_custom_value_from_config(self):
        from ppxai.config import get_agent_config
        from ppxai.config.store import ConfigStore

        store = ConfigStore.get_instance()
        original_config = dict(store.config)
        try:
            store.set_for_testing({
                "tools": {
                    "agent": {"zombie_threshold": 7},
                },
            })
            assert get_agent_config()["zombie_threshold"] == 7
        finally:
            store.set_for_testing(original_config)

    def test_zero_is_accepted(self):
        from ppxai.config import get_agent_config
        from ppxai.config.store import ConfigStore

        store = ConfigStore.get_instance()
        original_config = dict(store.config)
        try:
            store.set_for_testing({
                "tools": {
                    "agent": {"zombie_threshold": 0},
                },
            })
            assert get_agent_config()["zombie_threshold"] == 0
        finally:
            store.set_for_testing(original_config)
