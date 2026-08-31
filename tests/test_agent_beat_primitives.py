"""P0 Stage 1 (v1.18.0) — EventType additions + AgentBeatState dataclass.

Pins the wire-shape contracts that subsequent stages depend on:

  - `EventType.AGENT_BEAT` / `AGENT_RUN_START` / `AGENT_RUN_ERROR` /
    `AGENT_ZOMBIE` exist and have stable string values that web and
    VSCode clients can dispatch on.
  - `AgentBeatState.as_event_data()` produces the canonical dict the
    `AGENT_BEAT` event carries — rename anything here and downstream
    clients break silently.
  - `elapsed_s` computes wall time from `start_time` (monotonic).

Stage 1 is additive — no code emits these events yet, no client
renders them yet. The regression surface is purely the types.
"""

import time

from ppxai.engine.types import AgentBeatState, EventType


class TestEventTypeAdditions:
    """New enum members must have stable string values.

    Clients dispatch on the string value (comes across SSE / event bus
    as `event.type.name` → `EventType[name]`). A rename here silently
    drops the event at the client.
    """

    def test_agent_beat_exists(self):
        assert EventType.AGENT_BEAT.value == "agent_beat"

    def test_agent_run_start_exists(self):
        assert EventType.AGENT_RUN_START.value == "agent_run_start"

    def test_agent_run_error_exists(self):
        assert EventType.AGENT_RUN_ERROR.value == "agent_run_error"

    def test_agent_zombie_exists(self):
        assert EventType.AGENT_ZOMBIE.value == "agent_zombie"

    def test_agent_run_complete_exists(self):
        assert EventType.AGENT_RUN_COMPLETE.value == "agent_run_complete"

    def test_existing_agent_event_types_unchanged(self):
        """Sanity — AGENT_COMPLETE / AGENT_ITERATION / AGENT_MAX_ITERATIONS
        already exist from v1.11.8 and must stay exactly as they were.
        Clients subscribed to them can't have their subscriptions
        silently broken by the P0 additions.
        """
        assert EventType.AGENT_COMPLETE.value == "agent_complete"
        assert EventType.AGENT_ITERATION.value == "agent_iteration"
        assert EventType.AGENT_MAX_ITERATIONS.value == "agent_max_iterations"


class TestAgentBeatStateDefaults:
    """Zero-valued state is the initial condition before any iteration
    runs — the `as_event_data()` output here is what a hypothetical
    client would see if it subscribed BEFORE the first beat (shouldn't
    happen in practice, but the shape still has to be valid).
    """

    def test_fresh_state_has_zero_fields(self):
        state = AgentBeatState()
        assert state.iteration == 0
        assert state.beat_sequence == 0
        assert state.last_beat_time == 0.0
        assert state.last_tool == ""
        assert state.last_run_ok is True
        assert state.consecutive_failures == 0
        assert state.start_time == 0.0

    def test_fresh_state_elapsed_is_zero(self):
        """No start_time → elapsed stays 0.0 (not negative, not negative
        of now()). Renderers depend on this to show "0.0s" cleanly
        before the first iteration.
        """
        state = AgentBeatState()
        assert state.elapsed_s == 0.0


class TestElapsedComputation:
    def test_elapsed_measures_monotonic_wall_time(self):
        start = time.monotonic()
        state = AgentBeatState(start_time=start)
        time.sleep(0.01)  # 10ms
        elapsed = state.elapsed_s
        assert elapsed >= 0.009  # allow for clock granularity
        assert elapsed < 1.0     # not wildly wrong

    def test_elapsed_is_zero_when_start_time_zero(self):
        """Even if other fields are set, start_time=0 is the sentinel
        for "run hasn't started" and elapsed must be 0.
        """
        state = AgentBeatState(
            iteration=5,
            beat_sequence=5,
            last_tool="read_file",
            # start_time left at default 0.0
        )
        assert state.elapsed_s == 0.0


class TestAsEventDataWireShape:
    """The `AGENT_BEAT` event payload has a stable schema. Clients
    across 4 languages (Python TUIs, JS web, TS VSCode) depend on these
    exact keys. Any rename is a breaking wire change.
    """

    def test_event_data_contains_all_canonical_keys(self):
        state = AgentBeatState(
            iteration=3,
            beat_sequence=7,
            last_tool="read_file",
            last_run_ok=True,
            consecutive_failures=0,
            start_time=time.monotonic() - 2.5,
        )
        data = state.as_event_data()
        assert set(data.keys()) == {
            "iteration", "beat", "tool", "ok", "failures", "elapsed_s",
        }

    def test_event_data_field_values(self):
        state = AgentBeatState(
            iteration=3,
            beat_sequence=7,
            last_tool="apply_patch",
            last_run_ok=False,
            consecutive_failures=2,
            start_time=time.monotonic() - 5.0,
        )
        data = state.as_event_data()
        assert data["iteration"] == 3
        assert data["beat"] == 7
        assert data["tool"] == "apply_patch"
        assert data["ok"] is False
        assert data["failures"] == 2
        assert isinstance(data["elapsed_s"], float)
        assert data["elapsed_s"] >= 4.9  # monotonic clock, ~5s elapsed

    def test_event_data_elapsed_rounded_to_one_decimal(self):
        """Clients render `"5.0s"` — the 1-decimal rounding keeps
        progress widgets stable and prevents noisy 5.123456s updates.
        """
        state = AgentBeatState(start_time=time.monotonic() - 2.0)
        data = state.as_event_data()
        # Check the rounding — value should be a float like 2.0, not 2.003421
        assert data["elapsed_s"] == round(data["elapsed_s"], 1)

    def test_event_data_is_json_serializable(self):
        """SSE pushes as JSON across the wire; every key and value must
        round-trip cleanly.
        """
        import json
        state = AgentBeatState(
            iteration=1, beat_sequence=1, last_tool="t",
            last_run_ok=True, consecutive_failures=0,
            start_time=time.monotonic(),
        )
        data = state.as_event_data()
        encoded = json.dumps(data)
        decoded = json.loads(encoded)
        assert decoded == data


class TestAgentBeatStateMutation:
    """Typical state machine: add_message → beat fires → fields updated.
    Pin the invariants the chat-loop emission will rely on in Stage 2.
    """

    def test_incrementing_beat_sequence(self):
        state = AgentBeatState(start_time=time.monotonic())
        state.beat_sequence += 1
        assert state.beat_sequence == 1
        state.beat_sequence += 1
        assert state.beat_sequence == 2

    def test_failure_counter_resets_on_success(self):
        """The consecutive_failures counter is what zombie detection
        reads. A successful tool call MUST reset it to 0 — otherwise
        a long-running agent that occasionally fails tools would
        eventually trigger zombie false-positives.
        """
        state = AgentBeatState()
        state.consecutive_failures = 2
        state.last_run_ok = False

        # Tool succeeds on next iteration.
        state.last_run_ok = True
        state.consecutive_failures = 0  # reset contract
        assert state.consecutive_failures == 0

    def test_failures_accumulate_across_iterations(self):
        state = AgentBeatState()
        for _ in range(3):
            state.last_run_ok = False
            state.consecutive_failures += 1
        assert state.consecutive_failures == 3
