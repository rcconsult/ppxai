"""Debt Item 82: a `/task` run's events.jsonl records a degraded turn.

Owner decision (2026-09-23): persist ONLY events carrying a tool-guard
degradation reason, plus the engine's per-turn terminal pair — never
`EventType.INFO` wholesale. The consumer is `ppxai/engine/task_runner.py`'s
engine-event loop; the engine (`engine/chat.py`, `engine/types.py`) is
unchanged.

Every run here goes through the REAL runner (`build_task_runner`), the REAL
registry (`AgentRunRegistry.run_in_background`) and the REAL filesystem store,
written under pytest's `tmp_path`. Assertions read the `events.jsonl` FILE —
the audit question is "what can an auditor answer from that file alone".

Only the EngineClient's provider is scripted (the same `MockProvider` shape
`tests/test_agent_beat_sse.py` uses), so the degradation events and the
terminal rollup are produced by the real `chat_with_tools` tool loop.

How an auditor tells the three states apart from events.jsonl:

  DEGRADED  any `turn_degraded` record, or a `turn_end` whose `degraded` is
            true.
  CLEAN     a `turn_end` whose `degraded` is false, and no `turn_degraded`.
  UNKNOWN   no `turn_end` record for the turn — the engine never reported
            (interrupt/provider-error exits). Never read as clean.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppxai.engine import task_runner
from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.client import EngineClient
from ppxai.engine.model_facts import ModelFacts
from ppxai.engine.types import Event, EventType, ProviderCapabilities, ToolGuardReason

DEGRADED = task_runner.TURN_DEGRADED_EVENT
TURN_END = task_runner.TURN_END_EVENT


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class ScriptedProvider:
    """Yields one scripted event list per provider call (per tool iteration)."""

    def __init__(self, scripted_iterations: list[list[Event]]):
        self._scripts = scripted_iterations
        self._idx = 0
        self.capabilities = ProviderCapabilities()

    def get_capabilities(self):
        return self.capabilities

    def get_facts_for_model(self, _model):
        return ModelFacts(tool_mode="native")

    async def chat(self, messages, model, stream=False, tools=None):
        events = self._scripts[min(self._idx, len(self._scripts) - 1)]
        self._idx += 1
        for ev in events:
            yield ev


def _ok_handler(**kwargs):
    return "ok-result"


class ScriptedEngine(EngineClient):
    """A real EngineClient whose provider is scripted.

    The runner calls `set_provider` / `set_model` / `enable_tools` on the
    engine it builds; those are the only three overridden, so the tool loop,
    the guards, the ScopedToolManager wrap and the event stream are all real.
    """

    def __init__(self, provider: ScriptedProvider, *, budgets=None, max_same=None):
        super().__init__()
        self._scripted = provider
        self._budgets = budgets
        self._max_same = max_same

    def set_provider(self, provider_name: str) -> bool:
        self.provider = self._scripted
        self.provider_name = "mock"
        return True

    def set_model(self, model_id, strict=False, reset_context=True):
        self.model = "mock-model"
        return True

    def enable_tools(self) -> bool:
        super().enable_tools()
        self.tool_manager.register_function(
            name="ok_tool",
            description="Always succeeds.",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
            handler=_ok_handler,
        )
        if self._budgets is not None:
            self.tool_manager.tool_call_budgets = dict(self._budgets)
        if self._max_same is not None:
            self.tool_manager.max_same_tool_calls = self._max_same
        return True


class CraftedEngine(ScriptedEngine):
    """Real EngineClient whose `chat` yields hand-crafted events.

    For the filter tests: events the real tool loop cannot be made to emit
    (an INFO with a non-enum reason, a reason on a non-INFO type, a terminal
    that carries no `degraded` field, an oversized value).
    """

    def __init__(self, events: list[Event]):
        super().__init__(ScriptedProvider([[Event(EventType.STREAM_END, "unused")]]))
        self._crafted = events

    async def chat(self, message, stream=True, attachment_refs=None):
        for ev in self._crafted:
            yield ev


def _call(call_id: str, q: str = "x") -> Event:
    return Event(EventType.TOOL_CALL, {
        "tool": "ok_tool", "arguments": {"q": q}, "tool_call_id": call_id,
    })


def _tool_iteration(call_id: str, q: str = "x") -> list[Event]:
    return [_call(call_id, q), Event(EventType.STREAM_END, "")]


FINAL = [Event(EventType.STREAM_END, "Done.")]


async def _run(tmp_path: Path, monkeypatch, engine: EngineClient) -> tuple[list[dict], str]:
    """Drive one real run to its terminal state; return (events.jsonl rows, run_id)."""
    registry = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(task_runner, "EngineClient", lambda: engine)
    runner = task_runner.build_task_runner(
        registry, provider_name="mock", model="mock-model", task="do it",
        tools=["ok_tool"], allow_outbound=[],
    )
    meta = registry.start_run(
        "do it", tools=["ok_tool"], provider="mock", model="mock-model",
    )
    registry.run_in_background(meta, runner)
    await registry.get_run_task(meta.run_id)

    path = tmp_path / "runs" / meta.run_id / "agent-0" / "events.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return rows, meta.run_id


def _of(rows: list[dict], type_: str) -> list[dict]:
    return [r for r in rows if r["type"] == type_]


def _budget_and_withdrawal_engine() -> ScriptedEngine:
    """ok_tool budget 1: spend it, get refused, reach again → tools withdrawn."""
    return ScriptedEngine(ScriptedProvider([
        _tool_iteration("c1", "a"),   # runs, spends the whole budget
        _tool_iteration("c2", "b"),   # refused (refusal 1)
        _tool_iteration("c3", "c"),   # refused again (refusal 2) → withdrawal
        FINAL,                        # tools withdrawn; answers
    ]), budgets={"ok_tool": 1})


def _repeat_loop_engine() -> ScriptedEngine:
    """Same tool, byte-identical args: two successful calls, the third trips
    (the guard fires once `max_same_tool_calls` have ALREADY run)."""
    return ScriptedEngine(ScriptedProvider([
        _tool_iteration("c1", "same"),
        _tool_iteration("c2", "same"),
        _tool_iteration("c3", "same"),
        FINAL,
    ]), budgets={}, max_same=2)


def _clean_engine() -> ScriptedEngine:
    return ScriptedEngine(ScriptedProvider([
        _tool_iteration("c1", "a"),
        FINAL,
    ]), budgets={})


# ---------------------------------------------------------------------------
# Degraded runs
# ---------------------------------------------------------------------------


class TestDegradedTurnIsAudited:

    async def test_budget_refusal_and_withdrawal_reach_events_jsonl(self, tmp_path, monkeypatch):
        rows, _ = await _run(tmp_path, monkeypatch, _budget_and_withdrawal_engine())

        degraded = _of(rows, DEGRADED)
        assert [r["data"]["reason"] for r in degraded] == [
            ToolGuardReason.TOOL_BUDGET_EXHAUSTED.value,
            ToolGuardReason.TOOL_BUDGET_EXHAUSTED.value,
            ToolGuardReason.TOOLS_WITHDRAWN.value,
        ], degraded
        assert degraded[0]["data"] == {
            "reason": "tool_budget_exhausted", "tool": "ok_tool",
            "budget": 1, "refusal_count": 1,
        }
        assert degraded[1]["data"]["refusal_count"] == 2
        assert degraded[2]["data"] == {"reason": "tools_withdrawn", "trigger_tool": "ok_tool"}
        for r in degraded:
            assert (r["level"], r["category"]) == ("warning", "tool")

        (end,) = _of(rows, TURN_END)
        assert end["data"]["engine_event"] == "agent_run_complete"
        assert end["data"]["degraded"] is True
        assert end["data"]["degradation_reasons"] == ["tool_budget_exhausted", "tools_withdrawn"]
        assert end["level"] == "warning"
        assert end["category"] == "lifecycle"
        # The per-turn records precede the registry's run terminal.
        types = [r["type"] for r in rows]
        assert types.index(TURN_END) < types.index("agent_run_complete")

    async def test_repeat_loop_reaches_events_jsonl(self, tmp_path, monkeypatch):
        rows, _ = await _run(tmp_path, monkeypatch, _repeat_loop_engine())

        (loop,) = _of(rows, DEGRADED)
        assert loop["data"] == {
            "reason": "tool_repeat_loop", "tool": "ok_tool",
            "threshold": 2, "occurrences": 2,
        }
        (end,) = _of(rows, TURN_END)
        assert end["data"]["degraded"] is True
        assert end["data"]["degradation_reasons"] == ["tool_repeat_loop"]

    async def test_the_run_terminal_is_not_duplicated(self, tmp_path, monkeypatch):
        """The engine's terminal is persisted under its OWN name. Both JS tails
        stop reading on `agent_run_complete` / `agent_run_error`, so a second
        record under either name would end a live watch early."""
        rows, _ = await _run(tmp_path, monkeypatch, _budget_and_withdrawal_engine())
        assert len(_of(rows, "agent_run_complete")) == 1
        assert _of(rows, "agent_run_error") == []


# ---------------------------------------------------------------------------
# Clean run (negative half)
# ---------------------------------------------------------------------------


class TestCleanTurn:

    async def test_clean_run_has_no_degradation_record(self, tmp_path, monkeypatch):
        rows, _ = await _run(tmp_path, monkeypatch, _clean_engine())

        assert _of(rows, DEGRADED) == []
        (end,) = _of(rows, TURN_END)
        assert end["data"]["degraded"] is False
        assert end["data"]["degradation_reasons"] == []
        assert end["level"] == "info"
        # The run's own tool activity is still there — the filter did not
        # swallow the stream.
        assert len(_of(rows, "tool_call")) == 1


# ---------------------------------------------------------------------------
# Unknown: the engine never reported
# ---------------------------------------------------------------------------


class TestUnreportedTurnIsUnknown:

    async def test_provider_error_leaves_no_turn_end(self, tmp_path, monkeypatch):
        """A provider error after a degradation: the runner raises on the
        ERROR that PRECEDES the engine's AGENT_RUN_ERROR, so no `turn_end` is
        written. The degradation already seen is still on file; nothing
        claims the turn was clean."""
        engine = ScriptedEngine(ScriptedProvider([
            _tool_iteration("c1", "a"),
            _tool_iteration("c2", "b"),                   # refused
            [Event(EventType.ERROR, {"message": "boom"})],  # provider fails
        ]), budgets={"ok_tool": 1})
        rows, _ = await _run(tmp_path, monkeypatch, engine)

        assert _of(rows, TURN_END) == []
        assert [r["data"]["reason"] for r in _of(rows, DEGRADED)] == ["tool_budget_exhausted"]
        (err,) = _of(rows, "agent_run_error")
        assert "boom" in err["data"]["error"]

    async def test_terminal_without_a_degraded_field_is_not_defaulted(self, tmp_path, monkeypatch):
        """The runner copies what the engine said; it never writes
        `degraded: false` on the engine's behalf."""
        engine = CraftedEngine([
            Event(EventType.AGENT_RUN_COMPLETE, {"iterations": 1, "elapsed_s": 0.1}),
            Event(EventType.STREAM_END, "ok"),
        ])
        rows, _ = await _run(tmp_path, monkeypatch, engine)

        (end,) = _of(rows, TURN_END)
        assert "degraded" not in end["data"]
        assert "degradation_reasons" not in end["data"]


# ---------------------------------------------------------------------------
# The filter is keyed on the ENUM
# ---------------------------------------------------------------------------


class TestFilterKeyedOnEnum:

    async def test_stray_and_non_enum_reasons_are_not_persisted(self, tmp_path, monkeypatch):
        engine = CraftedEngine([
            Event(EventType.INFO, "Step 2: processing ok_tool result..."),       # no metadata
            Event(EventType.INFO, "some info", {"other": 1}),                    # no reason
            Event(EventType.INFO, "not a guard", {"reason": "zombie"}),          # non-enum
            Event(EventType.INFO, "not a guard", {"reason": "TOOL_REPEAT_LOOP"}),  # member NAME, not value
            Event(EventType.INFO, "weird", {"reason": ["tool_repeat_loop"]}),    # unhashable
            Event(EventType.INFO, "weird", {"reason": None}),
            Event(EventType.STREAM_END, "ok"),
        ])
        rows, _ = await _run(tmp_path, monkeypatch, engine)
        assert _of(rows, DEGRADED) == []

    async def test_a_valid_reason_on_a_non_info_event_is_persisted(self, tmp_path, monkeypatch):
        engine = CraftedEngine([
            Event(EventType.STATUS, "future carrier", {
                "reason": ToolGuardReason.TOOL_REPEAT_LOOP.value, "tool": "ok_tool",
            }),
            Event(EventType.STREAM_END, "ok"),
        ])
        rows, _ = await _run(tmp_path, monkeypatch, engine)
        (rec,) = _of(rows, DEGRADED)
        assert rec["data"] == {"reason": "tool_repeat_loop", "tool": "ok_tool"}

    async def test_oversized_values_are_clamped(self, tmp_path, monkeypatch):
        huge = "x" * 5000
        engine = CraftedEngine([
            Event(EventType.INFO, "budget", {
                "reason": ToolGuardReason.TOOL_BUDGET_EXHAUSTED.value,
                "tool": huge, "budget": 3, "refusal_count": 1,
            }),
            Event(EventType.AGENT_RUN_ERROR, {
                "reason": "zombie", "iteration": 2, "elapsed_s": 1.5,
                "detail": huge, "degraded": True,
                "degradation_reasons": ["tool_budget_exhausted"],
            }),
            Event(EventType.STREAM_END, "stopped"),
        ])
        rows, _ = await _run(tmp_path, monkeypatch, engine)

        (rec,) = _of(rows, DEGRADED)
        assert rec["data"]["tool"] == "x" * 200
        assert rec["data"]["budget"] == 3
        (end,) = _of(rows, TURN_END)
        assert end["data"]["detail"] == "x" * 200
        assert end["data"]["degraded"] is True          # a bool, not "True"
        assert end["data"]["engine_event"] == "agent_run_error"
        assert end["data"]["reason"] == "zombie"
        assert end["level"] == "warning"

    @pytest.mark.parametrize("member", list(ToolGuardReason), ids=lambda m: m.value)
    def test_every_member_is_recognised(self, member):
        ev = Event(EventType.INFO, "x", {"reason": member.value})
        assert task_runner.degradation_reason(ev) is member


# ---------------------------------------------------------------------------
# Fence: persisted vocabulary == ToolGuardReason, both directions
# ---------------------------------------------------------------------------


class TestPersistedVocabularyFence:
    """Every `ToolGuardReason` reaches events.jsonl through a real run, and
    nothing outside it does — the `TestReasonVocabularyFence` pattern
    (`tests/test_tool_loop_guard.py`), one layer further downstream."""

    async def test_persisted_reasons_equal_the_enum(self, tmp_path, monkeypatch):
        persisted: set[str] = set()
        rolled_up: set[str] = set()
        for i, make in enumerate((_budget_and_withdrawal_engine, _repeat_loop_engine)):
            rows, _ = await _run(tmp_path / f"s{i}", monkeypatch, make())
            persisted |= {r["data"]["reason"] for r in _of(rows, DEGRADED)}
            for end in _of(rows, TURN_END):
                rolled_up |= set(end["data"].get("degradation_reasons", []))

        declared = {member.value for member in ToolGuardReason}
        assert persisted == declared, (
            f"events.jsonl vocabulary drift: persisted {persisted}, enum declares "
            f"{declared}. Add a scenario for the missing side, or explain the "
            f"exemption here."
        )
        assert rolled_up == declared
