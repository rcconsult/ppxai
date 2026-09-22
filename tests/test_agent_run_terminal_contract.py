"""v1.19.3: the Agent Heartbeat terminal-pair contract, made real.

docs/architecture.md §"Agent Heartbeat Primitives" promises exactly one
`AGENT_RUN_START` and exactly one of `AGENT_RUN_COMPLETE` /
`AGENT_RUN_ERROR` on EVERY `chat_with_tools` exit. Three exits broke it —
found while closing debt Item 82 (`tests/test_task_run_degradation_audit.py`,
commit `59702221`):

  (a) the prompt-based fallback on an empty native response (`chat.py`, the
      `facts.fallback_on_empty` branch) — a provider ERROR there was yielded
      then `return`ed bare.
  (b) the "answer from tool results, no more tools" retry-synthesis call —
      same bare-return pattern.
  (c) the tool-interrupt path — `_execute_single_tool` already puts an ERROR
      "Interrupted by user" into its `extra_events`; the caller's
      `if result is None: return` dropped it after that, with no
      AGENT_RUN_ERROR at all.

All three now yield AGENT_RUN_ERROR (same shape as their sibling exits)
before returning. Section A drives each through a REAL `chat_with_tools` via
`EngineClient.chat()`. Section B is a structural fence: every `return`
reachable in `chat_with_tools` must be immediately preceded by a terminal
yield, so a fourth silent exit can't be reintroduced. Section C is the
`task_runner.py` side of the same fix — it used to `raise` the instant it
saw ERROR/PROVIDER_THROTTLED, before the engine's own AGENT_RUN_ERROR (which
now always follows) could reach the `turn_end` persistence branch; it now
remembers the error and keeps consuming ONLY terminal-ish/harmless events,
breaking immediately on anything else (fail-fast: no tool executes once an
ERROR was seen), then raises the identical message after the loop.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from pathlib import Path

from ppxai.engine import chat as chat_module
from ppxai.engine import task_runner
from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.client import EngineClient
from ppxai.engine.model_facts import ModelFacts
from ppxai.engine.types import Event, EventType, ProviderCapabilities
from tests.test_task_run_degradation_audit import (
    CraftedEngine,
    ScriptedEngine,
    ScriptedProvider,
    _of,
)

TURN_END = task_runner.TURN_END_EVENT

# ---------------------------------------------------------------------------
# Section A harness — drive chat_with_tools directly, no server/runner layer.
# Same shape as tests/test_agent_beat_sse.py's MockProvider, without SSE.
# ---------------------------------------------------------------------------


class ByCallProvider:
    """Yields the Nth scripted event list on the Nth `.chat()` invocation,
    regardless of which call SITE made it (primary loop, empty-fallback,
    retry-synthesis all share this one counter — exactly like a real
    provider fields consecutive requests)."""

    def __init__(self, scripted_calls: list[list[Event]], facts: ModelFacts):
        self.capabilities = ProviderCapabilities()
        self._scripts = scripted_calls
        self._idx = 0
        self.facts = facts

    def get_capabilities(self):
        return self.capabilities

    def get_facts_for_model(self, _model):
        return self.facts

    async def chat(self, messages, model, stream=False, tools=None):
        events = self._scripts[min(self._idx, len(self._scripts) - 1)]
        self._idx += 1
        for ev in events:
            yield ev


def _engine_with(provider: ByCallProvider, register_tool: bool = False) -> EngineClient:
    eng = EngineClient()
    eng.tools_enabled = True
    eng.provider = provider
    eng.provider_name = "mock"
    eng.model = "mock-model"
    if register_tool:
        async def _slow_ok(**kwargs):
            eng.interrupt_stream()
            await asyncio.sleep(0.3)
            return "should never reach"

        eng.tool_manager.register_function(
            name="slow_tool",
            description="Interrupts mid-flight.",
            parameters={"type": "object", "properties": {}},
            handler=_slow_ok,
        )
        eng.tool_manager.register_function(
            name="ok_tool",
            description="Always succeeds.",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kwargs: "ok-result",
        )
    return eng


async def _drive(engine: EngineClient, message: str = "hi") -> list[Event]:
    events: list[Event] = []
    async for ev in engine.chat(message, stream=False):
        events.append(ev)
    return events


def _assert_exactly_one_start_and_terminal(events: list[Event]) -> Event:
    """Returns the terminal event."""
    starts = [e for e in events if e.type == EventType.AGENT_RUN_START]
    assert len(starts) == 1, [e.type for e in events]
    terminals = [
        e for e in events
        if e.type in (EventType.AGENT_RUN_COMPLETE, EventType.AGENT_RUN_ERROR)
    ]
    assert len(terminals) == 1, [e.type for e in events]
    return terminals[0]


# ---------------------------------------------------------------------------
# Section A — the three exits, driven for real
# ---------------------------------------------------------------------------


class TestExitAFallbackOnEmptyProviderError:
    """chat.py ~line 877: native returns empty, fallback_on_empty retries
    prompt-based, and THAT call errors."""

    async def test_exactly_one_start_and_error_terminal(self):
        provider = ByCallProvider(
            scripted_calls=[
                [Event(EventType.STREAM_END, "")],           # native: empty
                [Event(EventType.ERROR, {"message": "fallback boom"})],
            ],
            facts=ModelFacts(tool_mode="native", fallback_on_empty=True),
        )
        engine = _engine_with(provider)
        events = await _drive(engine)

        terminal = _assert_exactly_one_start_and_terminal(events)
        assert terminal.type == EventType.AGENT_RUN_ERROR
        assert terminal.data["reason"] == "provider_error"
        assert terminal.data["degraded"] is False
        assert terminal.data["degradation_reasons"] == []
        # The bare ERROR is still there, immediately before the terminal.
        assert events[-2].type == EventType.ERROR
        assert events[-1] is terminal


class TestExitBRetrySynthesisProviderError:
    """chat.py's iteration>1-empty-response retry-synthesis call errors."""

    async def test_exactly_one_start_and_error_terminal(self):
        provider = ByCallProvider(
            scripted_calls=[
                [Event(EventType.TOOL_CALL, {
                    "tool": "ok_tool", "arguments": {}, "tool_call_id": "c1",
                }), Event(EventType.STREAM_END, "")],          # iteration 1: tool call
                [Event(EventType.STREAM_END, "")],              # iteration 2: empty
                [Event(EventType.PROVIDER_THROTTLED, {"message": "429"})],  # retry-synthesis
            ],
            facts=ModelFacts(tool_mode="native", fallback_on_empty=False),
        )
        engine = _engine_with(provider, register_tool=True)
        events = await _drive(engine)

        terminal = _assert_exactly_one_start_and_terminal(events)
        assert terminal.type == EventType.AGENT_RUN_ERROR
        assert terminal.data["reason"] == "provider_throttled"
        assert events[-2].type == EventType.PROVIDER_THROTTLED
        assert events[-1] is terminal


class TestExitCToolInterrupt:
    """A tool call in flight when the user interrupts: `_execute_single_tool`
    returns `(None, False, [ERROR])`; the caller used to drop the terminal."""

    async def test_exactly_one_start_and_error_terminal(self):
        provider = ByCallProvider(
            scripted_calls=[
                [Event(EventType.TOOL_CALL, {
                    "tool": "slow_tool", "arguments": {}, "tool_call_id": "c1",
                }), Event(EventType.STREAM_END, "")],
            ],
            facts=ModelFacts(tool_mode="native"),
        )
        engine = _engine_with(provider, register_tool=True)
        events = await _drive(engine)

        terminal = _assert_exactly_one_start_and_terminal(events)
        assert terminal.type == EventType.AGENT_RUN_ERROR
        assert terminal.data["reason"] == "interrupted"
        # The ERROR came from _execute_single_tool's extra_events, not a
        # second one added by the fix — exactly one ERROR on the stream.
        errors = [e for e in events if e.type == EventType.ERROR]
        assert len(errors) == 1
        assert errors[0].data == "Interrupted by user"
        assert events[-1] is terminal


# ---------------------------------------------------------------------------
# Section B — structural fence: no silent exit can be reintroduced
# ---------------------------------------------------------------------------

_RUN_TERMINAL_ATTRS = {"AGENT_RUN_ERROR", "AGENT_RUN_COMPLETE"}


def _is_event_yield(stmt: ast.stmt, attrs: set[str]) -> bool:
    """True if `stmt` is `yield Event(EventType.<one of attrs>, ...)`."""
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Yield):
        return False
    call = stmt.value.value
    if not isinstance(call, ast.Call):
        return False
    if not (isinstance(call.func, ast.Name) and call.func.id == "Event"):
        return False
    if not call.args:
        return False
    first = call.args[0]
    return isinstance(first, ast.Attribute) and first.attr in attrs


def _is_terminal_yield(stmt: ast.stmt) -> bool:
    return _is_event_yield(stmt, _RUN_TERMINAL_ATTRS)


_SCOPE_BOUNDARY = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _stmt_lists(node: ast.AST, *, is_root: bool = True):
    """Yield every statement LIST reachable from `node` (its own body plus
    every nested compound statement's), so each list can be scanned for a
    `return` whose immediately preceding sibling is not a terminal yield.

    Does NOT descend into a nested `def`/`async def`/`class` (other than
    `node` itself, when it IS one — `is_root`): chat_with_tools defines a
    closure (`_native_tool_call`) whose own `return` belongs to THAT
    function's contract, not the outer generator's.
    """
    if not is_root and isinstance(node, _SCOPE_BOUNDARY):
        return
    for field in ("body", "orelse", "finalbody"):
        lst = getattr(node, field, None)
        if isinstance(lst, list):
            yield lst
            for child in lst:
                yield from _stmt_lists(child, is_root=False)
    if isinstance(node, ast.Try):
        for handler in node.handlers:
            yield handler.body
            for child in handler.body:
                yield from _stmt_lists(child, is_root=False)


def _exit_is_terminated(stmts: list[ast.stmt], i: int) -> bool:
    """True if an exit at position `i` of `stmts` (a `return` there, or
    falling off the end when `i == len(stmts)`) follows a run terminal."""
    preceding = stmts[i - 1] if i > 0 else None
    if preceding is None:
        return False
    if _is_terminal_yield(preceding):
        return True
    # The zombie / max-iterations shape: the run terminal, then
    # bookkeeping, then a final STREAM_END carrying the text. A STREAM_END
    # alone is NOT a terminal — the run pair must appear earlier in the
    # same block.
    return (
        _is_event_yield(preceding, {"STREAM_END"})
        and any(_is_terminal_yield(s) for s in stmts[:i - 1])
    )


def _returns_without_terminal(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[int]:
    """Line numbers of exits NOT preceded (in the same block) by a run
    terminal: every explicit `return`, plus falling off the end of the
    function body (the max-iterations exit has no `return`), reported at
    the body's last line."""
    violations = []
    for stmt_list in _stmt_lists(func):
        for i, stmt in enumerate(stmt_list):
            if isinstance(stmt, ast.Return) and not _exit_is_terminated(stmt_list, i):
                violations.append(stmt.lineno)
    body = func.body
    if body and not isinstance(body[-1], ast.Return) and not _exit_is_terminated(body, len(body)):
        violations.append(body[-1].lineno)
    return violations


def _parse_function(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(textwrap.dedent(source))
    (func,) = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return func


class TestNoSilentExitFence:

    def test_every_return_in_chat_with_tools_is_preceded_by_a_terminal_yield(self):
        source = inspect.getsource(chat_module.chat_with_tools)
        func = _parse_function(source)
        violations = _returns_without_terminal(func)
        assert violations == [], (
            f"chat_with_tools has a bare exit at line offset(s) {violations} "
            "inside the function — a `return` with no AGENT_RUN_ERROR / "
            "AGENT_RUN_COMPLETE immediately above it (or earlier in the block, "
            "before a final STREAM_END) breaks the "
            "Agent Heartbeat 'every exit has a terminal' contract "
            "(docs/architecture.md §\"Agent Heartbeat Primitives\")."
        )

    def test_planted_violation_is_caught(self):
        """Control: a hand-written function with the SAME shape of bug (a
        bare ERROR + return, no AGENT_RUN_ERROR) must be flagged. Proves the
        checker isn't vacuously passing."""
        bad_source = """
        async def broken():
            yield Event(EventType.AGENT_RUN_START, {})
            if True:
                yield Event(EventType.ERROR, "x")
                return
        """
        func = _parse_function(bad_source)
        violations = _returns_without_terminal(func)
        assert violations != []

    def test_planted_good_shape_is_not_flagged(self):
        """Sanity: the fixed shape (terminal immediately before return) does
        NOT trip the fence — the checker isn't over-eager either."""
        good_source = """
        async def fine():
            yield Event(EventType.AGENT_RUN_START, {})
            if True:
                yield Event(EventType.ERROR, "x")
                yield Event(EventType.AGENT_RUN_ERROR, {})
                return
            yield Event(EventType.AGENT_RUN_COMPLETE, {})
        """
        func = _parse_function(good_source)
        assert _returns_without_terminal(func) == []

    def test_stream_end_alone_is_not_a_terminal(self):
        """Control: a final STREAM_END before `return` counts only when the
        run terminal appears earlier in the same block (the zombie exit's
        shape). STREAM_END by itself ends the text, not the run."""
        bad_source = """
        async def broken():
            yield Event(EventType.AGENT_RUN_START, {})
            if True:
                yield Event(EventType.STREAM_END, "x")
                return
        """
        assert _returns_without_terminal(_parse_function(bad_source)) != []
        zombie_shape = """
        async def fine():
            yield Event(EventType.AGENT_RUN_START, {})
            if True:
                yield Event(EventType.AGENT_RUN_ERROR, {})
                note = "x"
                yield Event(EventType.STREAM_END, note)
                return
            yield Event(EventType.AGENT_RUN_COMPLETE, {})
        """
        assert _returns_without_terminal(_parse_function(zombie_shape)) == []

    def test_falling_off_the_end_is_an_exit_too(self):
        """Control: chat_with_tools' max-iterations exit has no `return` —
        it falls off the end. Removing its AGENT_RUN_COMPLETE must trip the
        fence exactly as a bare `return` would."""
        bad_source = """
        async def broken():
            yield Event(EventType.AGENT_RUN_START, {})
            for _ in range(3):
                pass
            yield Event(EventType.STREAM_END, "limit reached")
        """
        assert _returns_without_terminal(_parse_function(bad_source)) != []
        good_source = """
        async def fine():
            yield Event(EventType.AGENT_RUN_START, {})
            for _ in range(3):
                pass
            yield Event(EventType.AGENT_RUN_COMPLETE, {"max_iterations_reached": True})
            note = "x"
            yield Event(EventType.STREAM_END, note)
        """
        assert _returns_without_terminal(_parse_function(good_source)) == []


# ---------------------------------------------------------------------------
# Section C — task_runner.py: fail-fast without raising too early
# ---------------------------------------------------------------------------


async def _run_and_load_meta(tmp_path: Path, monkeypatch, engine: EngineClient):
    registry = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(task_runner, "EngineClient", lambda: engine)
    runner = task_runner.build_task_runner(
        registry, provider_name="mock", model="mock-model", task="do it",
        tools=["ok_tool"], allow_outbound=[],
    )
    meta = registry.start_run("do it", tools=["ok_tool"], provider="mock", model="mock-model")
    registry.run_in_background(meta, runner)
    await registry.get_run_task(meta.run_id)

    path = tmp_path / "runs" / meta.run_id / "agent-0" / "events.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    # `run_in_background` mutates THIS SAME meta object in place
    # (`finish_run` sets .status/.error on it) — no separate reload needed.
    return rows, meta


class TestRunnerNoLongerRaisesBeforeTheTerminal:

    async def test_error_immediately_followed_by_terminal_persists_turn_end(self, tmp_path, monkeypatch):
        engine = ScriptedEngine(ScriptedProvider([
            [Event(EventType.TOOL_CALL, {
                "tool": "ok_tool", "arguments": {}, "tool_call_id": "c1",
            }), Event(EventType.STREAM_END, "")],
            [Event(EventType.ERROR, {"message": "downstream boom"})],
        ]))
        rows, meta = await _run_and_load_meta(tmp_path, monkeypatch, engine)

        (end,) = _of(rows, TURN_END)
        assert end["level"] == "warning"
        assert end["data"]["engine_event"] == "agent_run_error"

        assert meta.status == "failed"
        assert meta.error is not None and "downstream boom" in meta.error
        (registry_err,) = _of(rows, "agent_run_error")
        assert registry_err["data"]["error"] == meta.error


class TestRunnerRaisesAfterTheLoopEndsEvenWithoutASubsequentTerminal:
    """The coordinator's required regression test: a fake engine that yields
    ERROR and then its generator simply ENDS — no AGENT_RUN_ERROR /
    AGENT_RUN_COMPLETE after it at all (an engine bug, or a future exit this
    fence hasn't caught yet). The run must still end FAILED with the exact
    error message, never COMPLETED with an empty result — that guarantee is
    what the old immediate `raise` existed to give, and moving the raise to
    after the `async for` (so it covers both a normal loop end AND a
    `break`) must not lose it."""

    async def test_run_fails_with_the_message_even_with_no_terminal_after_error(self, tmp_path, monkeypatch):
        engine = CraftedEngine([
            Event(EventType.ERROR, {"message": "no terminal follows"}),
            # Deliberately nothing else — the generator just ends here.
        ])
        rows, meta = await _run_and_load_meta(tmp_path, monkeypatch, engine)

        assert meta.status == "failed"
        assert meta.error is not None
        assert "no terminal follows" in meta.error
        assert meta.status != "completed"
        (registry_err,) = _of(rows, "agent_run_error")
        assert "no terminal follows" in registry_err["data"]["error"]
        # No turn_end — the engine never said how the turn ended.
        assert _of(rows, TURN_END) == []


class TestRunnerFailFastNoToolAfterError:
    """A malformed/buggy engine that yields ERROR and then, instead of a
    terminal, a TOOL_CALL: the runner must stop consuming at that TOOL_CALL —
    the tool is never executed/persisted — and still fail the run with the
    ERROR's message."""

    async def test_tool_call_after_error_is_not_persisted_and_run_fails(self, tmp_path, monkeypatch):
        engine = CraftedEngine([
            Event(EventType.ERROR, {"message": "provider hiccup"}),
            Event(EventType.TOOL_CALL, {
                "tool": "ok_tool", "arguments": {}, "tool_call_id": "should-not-run",
            }),
            Event(EventType.STREAM_END, "should not be reached either"),
        ])
        rows, meta = await _run_and_load_meta(tmp_path, monkeypatch, engine)

        assert meta.status == "failed"
        assert meta.error is not None and "provider hiccup" in meta.error
        assert _of(rows, "tool_call") == []
        assert _of(rows, TURN_END) == []
