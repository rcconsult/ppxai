"""Trace-replay harness for the per-turn tool-loop guards (v1.19.3).

Two tiers, both hermetic — no live model, no network:

  GUARD tier  a recorded sequence of (tool, args, outcome) is fed straight at
              `ToolManager`, asserting WHICH rule trips and on WHICH call.
              A pure function over a list.

  LOOP tier   the same sequence is driven through the real
              `chat_with_tools()` loop with a scripted provider, proving the
              guard is actually CONSULTED, that the right message reaches the
              model, and that a refused tool stays refused for the rest of
              the turn.

Traces live as DATA in `tests/fixtures/tool_loops/*.json`, one file per
named trace. Adding a newly observed loop means adding ONE json file — not
writing a new test. Schema (see any fixture for an example):

    name                    unique, matches the filename stem
    shape                   DeepEval's three-way split, the only published
                            precedent we could verify: "tool-repetition",
                            "call-graph-cycle" or "reasoning-stagnation".
                            We implement detection for the first two ONLY;
                            nothing here detects reasoning stagnation and no
                            fixture may claim otherwise.
    provenance              "observed" (from a real log) or "constructed"
    source                  where it came from, honestly
    description             what the trace shows
    uses_shipped_defaults   true  -> guards run on Default.* (so raising a
                                     shipped budget breaks the fixture, which
                                     is the point)
                            false -> the fixture's own "config" block is used
    config                  optional {max_same_tool_calls, tool_call_budgets}
    loop_tier               replay this trace through the real chat loop too
    calls                   [{tool, args, success, turn?, truncated_in_log?}, ...]
                            `turn` (default 1) splits a trace across chat
                            turns; the guards are per turn, so the harness
                            resets between them — at the loop tier by driving
                            a real chat() per turn, which is the only caller
                            of reset_tool_history() in production.
    expect.first_trip       {index, rule} (1-based) or null for "never trips"
    expect.first_budget_trip_index / first_repeat_trip_index  or null

Replay semantics: the harness records EVERY call in the trace, including the
ones a guard would have refused. The log is what actually happened with no
guard in place, so continuing past the first trip is what lets one trace
report both rules' first-trip index.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ppxai.constants import Default
from ppxai.engine.client import EngineClient
from ppxai.engine.model_facts import ModelFacts
from ppxai.engine.tools.manager import ToolManager
from ppxai.engine.types import Event, EventType, Message, ProviderCapabilities
from tests.test_tool_messages import MockChatContext, MockProvider, collect_events

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tool_loops"

REQUIRED_KEYS = {
    "name", "shape", "provenance", "source", "description",
    "uses_shipped_defaults", "loop_tier", "calls", "expect",
}

#: DeepEval's agent-loop taxonomy (deepeval.com/docs/metrics-agent-loop-detection).
#: Borrowed rather than invented — no other published taxonomy of agent loop
#: shapes could be verified.
KNOWN_SHAPES = ("tool-repetition", "call-graph-cycle", "reasoning-stagnation")

#: Shapes ppxai actually detects. Reasoning stagnation (the model going in
#: circles in prose, with or without tools) is NOT detected by either guard.
DETECTED_SHAPES = ("tool-repetition", "call-graph-cycle")


def load_traces() -> list[dict]:
    """Every trace fixture on disk, sorted by name."""
    traces = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        trace = json.loads(path.read_text(encoding="utf-8"))
        trace["_path"] = str(path)
        traces.append(trace)
    return traces


TRACES = load_traces()
TRACE_IDS = [t["name"] for t in TRACES]
LOOP_TRACES = [t for t in TRACES if t.get("loop_tier")]
LOOP_TRACE_IDS = [t["name"] for t in LOOP_TRACES]


INCIDENT = "tool-repetition-imdb-image-id-hunt-2026-09-22"


def incident_trace() -> dict:
    """The 2026-09-22 measured incident."""
    return next(t for t in TRACES if t["name"] == INCIDENT)


def manager_for(trace: dict) -> ToolManager:
    """A ToolManager configured the way the trace says."""
    manager = ToolManager()
    if not trace["uses_shipped_defaults"]:
        config = trace.get("config", {})
        if "max_same_tool_calls" in config:
            manager.max_same_tool_calls = config["max_same_tool_calls"]
        if "tool_call_budgets" in config:
            manager.tool_call_budgets = dict(config["tool_call_budgets"])
    return manager


def replay(trace: dict, manager: ToolManager) -> dict:
    """Replay a trace against the guards.

    Returns the verdict: the first trip overall (using the engine's own
    precedence — budget before repeat, mirroring engine/chat.py) plus the
    first trip of each rule considered on its own.
    """
    verdict = {"first_trip": None, "first_budget_trip_index": None,
               "first_repeat_trip_index": None}
    current_turn = trace["calls"][0].get("turn", 1)
    for index, call in enumerate(trace["calls"], start=1):
        if call.get("turn", 1) != current_turn:
            # A new user turn: the engine calls reset_tool_history() at the
            # top of every chat(), so the guards start from zero.
            current_turn = call.get("turn", 1)
            manager.reset_tool_history()
        tool, args = call["tool"], call["args"]
        budget_hit = manager.is_tool_budget_exceeded(tool)
        repeat_hit = manager.is_tool_loop_detected(tool, args)

        if budget_hit and verdict["first_budget_trip_index"] is None:
            verdict["first_budget_trip_index"] = index
        if repeat_hit and verdict["first_repeat_trip_index"] is None:
            verdict["first_repeat_trip_index"] = index
        if verdict["first_trip"] is None and (budget_hit or repeat_hit):
            verdict["first_trip"] = {
                "index": index,
                "rule": "budget" if budget_hit else "repeat",
            }

        manager.record_tool_call(tool, args, call["success"])
    return verdict


# ---------------------------------------------------------------------------
# Fixture hygiene
# ---------------------------------------------------------------------------

class TestFixtureSchema:
    """A malformed new fixture must fail loudly, not silently pass."""

    def test_some_traces_exist(self):
        assert TRACES, f"no trace fixtures found under {FIXTURE_DIR}"

    @pytest.mark.parametrize("trace", TRACES, ids=TRACE_IDS)
    def test_trace_has_required_keys(self, trace):
        missing = REQUIRED_KEYS - set(trace)
        assert not missing, f"{trace['_path']}: missing keys {sorted(missing)}"
        assert trace["provenance"] in ("observed", "constructed"), (
            f"{trace['_path']}: provenance must be 'observed' or 'constructed' — "
            "label where a trace came from honestly"
        )
        assert trace["shape"] in KNOWN_SHAPES, (
            f"{trace['_path']}: shape must be one of {KNOWN_SHAPES}"
        )
        assert trace["name"] == Path(trace["_path"]).stem
        assert trace["calls"], f"{trace['_path']}: empty trace"
        for call in trace["calls"]:
            assert {"tool", "args", "success"} <= set(call), (
                f"{trace['_path']}: every call needs tool/args/success"
            )
        turns = [c.get("turn", 1) for c in trace["calls"]]
        assert turns == sorted(turns), f"{trace['_path']}: turns must be ordered"

    def test_no_fixture_claims_reasoning_stagnation_is_detected(self):
        """We detect two of DeepEval's three shapes. Say so in the data.

        A fixture that expected a trip on a reasoning-stagnation trace would
        be claiming a capability neither guard has — the guards only ever see
        (tool, args, outcome), never the model's prose.
        """
        for trace in TRACES:
            if trace["shape"] not in DETECTED_SHAPES:
                assert trace["expect"]["first_trip"] is None, (
                    f"{trace['name']}: nothing in ppxai detects "
                    f"{trace['shape']!r}, so no trip can be expected"
                )


# ---------------------------------------------------------------------------
# GUARD tier — the guards as a pure function over a recorded trace
# ---------------------------------------------------------------------------

class TestGuardTier:
    """Replay each recorded trace straight at ToolManager."""

    @pytest.mark.parametrize("trace", TRACES, ids=TRACE_IDS)
    def test_trace_verdict_matches_fixture(self, trace):
        verdict = replay(trace, manager_for(trace))
        expected = trace["expect"]

        assert verdict["first_trip"] == expected["first_trip"], (
            f"{trace['name']}: expected first trip {expected['first_trip']}, "
            f"got {verdict['first_trip']}"
        )
        assert verdict["first_budget_trip_index"] == expected["first_budget_trip_index"]
        assert verdict["first_repeat_trip_index"] == expected["first_repeat_trip_index"]

    def test_the_2026_09_22_incident_would_now_be_caught(self):
        """The measured incident, called out by name.

        Four of the fifteen queries were byte-identical (calls 2, 7, 10, 14)
        and ten were paraphrases of the same hunt. The trailing-streak rule
        saw no streak of 3 and never fired; the per-turn count fires on call
        14 and the per-turn web_search budget fires earlier still, on call 7.
        """
        trace = incident_trace()
        assert len(trace["calls"]) == 15
        assert all(c["success"] for c in trace["calls"])

        verdict = replay(trace, manager_for(trace))
        assert verdict["first_trip"] == {"index": 11, "rule": "budget"}
        assert verdict["first_repeat_trip_index"] == 14

    def test_trailing_streak_rule_alone_would_have_missed_it(self):
        """Proves the fix is the COUNTING RULE, not the threshold.

        Re-implements the pre-v1.19.3 rule (walk backward, reset on any
        different call) over the same trace: it never reaches 3.
        """
        trace = incident_trace()
        history: list[tuple[str, str]] = []
        manager = ToolManager()
        tripped_at = None
        for index, call in enumerate(trace["calls"], start=1):
            key = (call["tool"], manager._hash_args(call["args"]))
            streak = 0
            for previous in reversed(history):
                if previous == key:
                    streak += 1
                else:
                    break
            if streak >= manager.max_same_tool_calls and tripped_at is None:
                tripped_at = index
            history.append(key)
        assert tripped_at is None, (
            "the old trailing-streak rule should be unable to catch this trace"
        )


class TestGuardEdges:
    """Knobs and resets that no single trace expresses."""

    def test_budget_resets_on_new_turn(self):
        manager = ToolManager()
        for _ in range(manager.get_tool_call_budget("web_search")):
            manager.record_tool_call("web_search", {"query": "x"}, True)
        assert manager.is_tool_budget_exceeded("web_search")

        manager.reset_tool_history()

        assert not manager.is_tool_budget_exceeded("web_search")
        assert not manager.is_tool_loop_detected("web_search", {"query": "x"})

    def test_two_identical_calls_do_not_trip_at_the_default(self):
        manager = ToolManager()
        manager.record_tool_call("read_file", {"path": "a.py"}, True)
        manager.record_tool_call("read_file", {"path": "a.py"}, True)
        assert not manager.is_tool_loop_detected("read_file", {"path": "a.py"})

    def test_repeat_detection_disabled_by_zero_threshold(self):
        manager = ToolManager()
        manager.max_same_tool_calls = 0
        for _ in range(10):
            manager.record_tool_call("read_file", {"path": "a.py"}, True)
        assert not manager.is_tool_loop_detected("read_file", {"path": "a.py"})

    def test_absent_or_zero_budget_is_unlimited(self):
        manager = ToolManager()
        manager.tool_call_budgets = {"web_search": 0}
        for _ in range(50):
            manager.record_tool_call("web_search", {"query": "distinct"}, True)
            manager.record_tool_call("execute_shell_command", {"command": "ls"}, True)
        assert not manager.is_tool_budget_exceeded("web_search")       # explicit 0
        assert not manager.is_tool_budget_exceeded("execute_shell_command")  # absent

    def test_shipped_budgets_cap_retrieval_tools_only(self):
        """The defaults are part of the contract, so pin them here.

        Capping read_file / list_directory / execute_shell_command would
        break ordinary work — a turn that reads twenty files is not a loop.
        """
        assert Default.TOOL_CALL_BUDGETS == {"web_search": 10, "fetch_url": 10}
        manager = ToolManager()
        for uncapped in ("read_file", "list_directory", "execute_shell_command",
                         "write_file", "apply_patch"):
            assert manager.get_tool_call_budget(uncapped) == 0

    def test_non_numeric_budget_is_ignored_not_fatal(self):
        manager = ToolManager()
        manager.tool_call_budgets = {"web_search": "lots"}
        assert manager.get_tool_call_budget("web_search") == 0
        assert not manager.is_tool_budget_exceeded("web_search")

    def test_failed_calls_are_kept_in_history_but_counted_nowhere(self):
        manager = ToolManager()
        for _ in range(9):
            manager.record_tool_call("web_search", {"query": "q"}, False)
        assert len(manager._tool_call_history) == 9
        assert not manager.is_tool_loop_detected("web_search", {"query": "q"})
        assert not manager.is_tool_budget_exceeded("web_search")

    def test_budget_and_repeat_messages_are_different(self):
        manager = ToolManager()
        budget_message = manager.get_budget_message("web_search")
        repeat_message = manager.get_loop_message("web_search")
        assert budget_message != repeat_message
        assert "same arguments" in repeat_message
        assert "refused" in budget_message
        assert "same arguments" not in budget_message


# ---------------------------------------------------------------------------
# LOOP tier — the same traces through the real chat_with_tools() loop
# ---------------------------------------------------------------------------

class StubHandler:
    """Per-tool handler that replays the trace's recorded outcomes in order."""

    def __init__(self, outcomes: list[bool]):
        self._outcomes = list(outcomes)
        self._index = 0

    def __call__(self, **kwargs) -> str:
        succeeded = self._outcomes[self._index] if self._index < len(self._outcomes) else True
        self._index += 1
        return "result body" if succeeded else "Error: simulated transient failure"


class TraceProvider(MockProvider):
    """MockProvider that stops calling tools once the engine stops offering them.

    The scripted-responses contract is `MockProvider`'s; the only addition is
    honouring `tools=None`, which is how the engine withdraws tools for the
    rest of a turn. A provider that kept emitting tool calls after that could
    not tell a working withdrawal from a broken one.
    """

    def __init__(self, trace_calls: list[dict], final_text: str = "Here is what I found."):
        responses = [
            [
                Event(EventType.TOOL_CALL, {
                    "tool": call["tool"],
                    "arguments": call["args"],
                    "tool_call_id": f"call_{i + 1}",
                }),
                Event(EventType.STREAM_END, ""),
            ]
            for i, call in enumerate(trace_calls)
        ]
        responses.append([Event(EventType.STREAM_END, final_text)])
        super().__init__(capabilities=ProviderCapabilities(), responses=responses)
        self.facts = ModelFacts(tool_mode="native")
        self._final_text = final_text

    async def chat(self, messages, model, stream=False, tools=None):
        if tools is None:
            self.chat_calls.append({
                "messages": messages, "model": model,
                "stream": stream, "tools": None,
            })
            yield Event(EventType.STREAM_END, self._final_text)
            return
        async for event in super().chat(messages, model, stream=stream, tools=tools):
            yield event


def turns_of(trace: dict) -> list[list[dict]]:
    """The trace's calls grouped into chat turns (default: one turn)."""
    turns: dict[int, list[dict]] = {}
    for call in trace["calls"]:
        turns.setdefault(call.get("turn", 1), []).append(call)
    return [turns[key] for key in sorted(turns)]


def build_context(trace: dict) -> MockChatContext:
    """A real ToolManager with stub tools for every tool the trace names."""
    manager = manager_for(trace)
    manager.max_iterations = 40  # traces are longer than the shipped default
    for tool_name in dict.fromkeys(call["tool"] for call in trace["calls"]):
        calls = [c for c in trace["calls"] if c["tool"] == tool_name]
        properties = {}
        for call in calls:
            for key in call["args"]:
                properties[key] = {"type": "string"}
        manager.register_function(
            name=tool_name,
            description=f"stub {tool_name}",
            parameters={"type": "object", "properties": properties, "required": []},
            handler=StubHandler([c["success"] for c in calls]),
        )
    return MockChatContext(provider=TraceProvider([]), model="gpt-5.2", tool_manager=manager)


async def drive(ctx: MockChatContext, trace: dict) -> list:
    """Run the trace through the real chat loop, one chat() per turn.

    A multi-turn trace is driven as several real chat() calls, so the
    per-turn reset is the engine's own (`reset_tool_history()` at the top of
    chat_with_tools) and never a hand-cleared list.
    """
    events = []
    for turn_calls in turns_of(trace):
        ctx._provider = TraceProvider(turn_calls)
        ctx.session.add_message(Message("user", "find the thing"))
        events.extend(await collect_events(ctx))
    return events


class TestLoopTier:
    """Prove the guards are consulted by the engine, not merely present."""

    @pytest.mark.parametrize("trace", LOOP_TRACES, ids=LOOP_TRACE_IDS)
    @pytest.mark.asyncio
    async def test_trace_through_real_chat_loop(self, trace):
        ctx = build_context(trace)
        events = await drive(ctx, trace)

        executed = [e for e in events if e.type == EventType.TOOL_CALL]
        info_text = [str(e.data) for e in events if e.type == EventType.INFO]
        expected = trace["expect"]["first_trip"]

        if expected is None:
            assert len(executed) == len(trace["calls"]), (
                f"{trace['name']}: every call should have run"
            )
            assert not [t for t in info_text if "Loop detected" in t or "budget" in t], (
                f"{trace['name']}: no guard should have fired, got {info_text}"
            )
            return

        # Calls before the trip ran; the tripping call did not.
        assert len(executed) == expected["index"] - 1, (
            f"{trace['name']}: expected {expected['index'] - 1} executed calls "
            f"before the trip, got {len(executed)}"
        )

        marker = ("Tool budget exhausted" if expected["rule"] == "budget"
                  else "Loop detected")
        assert any(marker in t for t in info_text), (
            f"{trace['name']}: expected an INFO event containing {marker!r}, "
            f"got {info_text}"
        )

        tripping_tool = trace["calls"][expected["index"] - 1]["tool"]
        injected = [m.content for m in ctx.session.messages if m.role == "user"]
        if expected["rule"] == "budget":
            assert ctx.tool_manager.get_budget_message(tripping_tool) in injected
            assert ctx.tool_manager.get_loop_message(tripping_tool) not in injected
        else:
            assert ctx.tool_manager.get_loop_message(tripping_tool) in injected
            assert ctx.tool_manager.get_budget_message(tripping_tool) not in injected

        # Every exit yields a terminal STREAM_END (engine contract).
        assert events[-1].type == EventType.STREAM_END

    @pytest.mark.asyncio
    async def test_failed_calls_reach_the_manager_as_failures(self):
        """The engine must pass the real outcome to record_tool_call().

        The retry trace is three identical FAILURES then a success. If the
        engine recorded every call as a success, the fourth would be refused
        as a repeat — the exact false positive the outcome argument exists to
        prevent. The zombie circuit breaker is disabled here because three
        consecutive failed iterations are its job, not this guard's.
        """
        trace = next(t for t in TRACES if t["name"] == "tool-repetition-retry-after-failure")
        ctx = build_context(trace)
        with patch("ppxai.engine.chat._get_zombie_threshold", return_value=0):
            events = await drive(ctx, trace)

        executed = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(executed) == len(trace["calls"]), (
            "the retry after three failures must still be allowed to run"
        )
        assert not [e for e in events
                    if e.type == EventType.INFO and "Loop detected" in str(e.data)]
        recorded = ctx.tool_manager._tool_call_history
        assert [r.success for r in recorded] == [c["success"] for c in trace["calls"]]

    @pytest.mark.asyncio
    async def test_refused_tool_stays_refused_for_the_rest_of_the_turn(self):
        """Second reach for a budget-exhausted tool withdraws tools entirely.

        Without this the model can spend every remaining iteration
        rephrasing at a tool that will never run again.
        """
        trace = incident_trace()
        ctx = build_context(trace)
        events = await drive(ctx, trace)

        refusals = [str(e.data) for e in events
                    if e.type == EventType.INFO and "Tool budget exhausted" in str(e.data)]
        assert len(refusals) == 2, (
            f"expected exactly two refusals before tools are withdrawn, got {refusals}"
        )

        withdrawn = [str(e.data) for e in events
                     if e.type == EventType.INFO and "answering from the results" in str(e.data)]
        assert len(withdrawn) == 1, f"expected one synthesis notice, got {withdrawn}"

        # The last provider request carried no tools at all.
        assert ctx.provider.chat_calls[-1]["tools"] is None

        # Ten of fifteen searches ran; the turn ended with an answer, not
        # with five more refusals.
        executed = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(executed) == 10
        assert events[-1].type == EventType.STREAM_END
        assert events[-1].data == "Here is what I found."


class TestPromptBasedPath:
    """The engine is provider-agnostic, and so is the guard.

    Native and prompt-based tool calls converge on ONE list
    (`tool_calls_list` in chat_with_tools), and the guard sits inside the
    loop over that list — so both paths are guarded by construction. This
    test holds that convergence, since a future split would silently leave
    prompt-based models unguarded.
    """

    @pytest.mark.asyncio
    async def test_repeat_guard_fires_on_the_prompt_based_path(self):
        trace = next(t for t in TRACES
                     if t["name"] == "tool-repetition-three-identical-consecutive")
        ctx = build_context(trace)
        call_json = json.dumps({"tool": "read_file", "arguments": {"path": "a.py"}})
        provider = MockProvider(
            capabilities=ProviderCapabilities(),
            responses=[[Event(EventType.STREAM_END, call_json)] for _ in trace["calls"]]
            + [[Event(EventType.STREAM_END, "Here is what I found.")]],
        )
        provider.facts = ModelFacts(tool_mode="prompt_based")
        ctx._provider = provider
        ctx.session.add_message(Message("user", "read a.py"))

        events = await collect_events(ctx)

        executed = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(executed) == 3, "the fourth identical call must be refused"
        assert any("Loop detected" in str(e.data)
                   for e in events if e.type == EventType.INFO)
        assert ctx.tool_manager.get_loop_message("read_file") in [
            m.content for m in ctx.session.messages if m.role == "user"
        ]


class TestRuntimeConfigPath:
    """The budgets travel the same path `max_same_tool_calls` already does."""

    def test_defaults_reach_the_manager_when_tools_are_enabled(self):
        engine = EngineClient()
        engine.enable_tools()
        assert engine.tool_manager.tool_call_budgets == dict(Default.TOOL_CALL_BUDGETS)
        assert engine.get_tools_status()["tool_call_budgets"] == dict(Default.TOOL_CALL_BUDGETS)

    def test_runtime_setter_merges_instead_of_replacing(self):
        engine = EngineClient()
        engine.enable_tools()
        assert engine.set_tool_config("tool_call_budgets", {"web_search": 25})
        budgets = engine.tool_manager.tool_call_budgets
        assert budgets["web_search"] == 25
        assert budgets["fetch_url"] == Default.TOOL_CALL_BUDGETS["fetch_url"]

    def test_runtime_setter_accepts_the_wire_form(self):
        """POST /tools/config types `value` as a str, so JSON must work."""
        engine = EngineClient()
        engine.enable_tools()
        assert engine.set_tool_config("tool_call_budgets", '{"web_search": 0}')
        assert engine.tool_manager.get_tool_call_budget("web_search") == 0

    def test_runtime_setter_rejects_garbage(self):
        engine = EngineClient()
        engine.enable_tools()
        assert not engine.set_tool_config("tool_call_budgets", "not json")
        assert not engine.set_tool_config("tool_call_budgets", {"web_search": "many"})
        assert engine.tool_manager.tool_call_budgets == dict(Default.TOOL_CALL_BUDGETS)

    def test_agent_config_carries_the_budgets(self):
        engine = EngineClient()
        assert engine.get_agent_config()["tool_call_budgets"] == dict(Default.TOOL_CALL_BUDGETS)
