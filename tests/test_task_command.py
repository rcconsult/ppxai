"""`/task` and `/run` as CommandFactory commands (T8b).

These pin the client-facing behaviour: U2 verb dispatch, the `/run` no-flags
rule, the verbs a one-off run cannot have, and — the part that decides which
clients get what — the event-loop gate.

Every test drives a backend over a tmp run store. `get_task_backend()` is a
process singleton over the real `~/.ppxai/runs/`, so patching it is not
optional hygiene: without it these tests would mint runs in the user's own
registry (see the persistence-pollution lesson in this suite).
"""

from __future__ import annotations

import pytest

from ppxai.commands import task as task_cmd
from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import ErrorResult, NotificationResult, TableResult
from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.task_backend import InProcessTaskBackend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    b = InProcessTaskBackend(
        AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    )
    monkeypatch.setattr(task_cmd, "get_task_backend", lambda: b)
    return b


class _Ctx:
    """Minimal CommandContext stand-in — the handlers read only these."""
    provider = "fakeprov"
    current_model = "fakemodel"


def _stub_runner(text="ok"):
    async def _runner(meta):
        return text
    return lambda *a, **k: _runner


# ── registration ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["task", "run"])
def test_commands_are_registered(name):
    """The T8b hole: neither was in CommandFactory before v1.19.1."""
    CommandFactory._ensure_loaded()
    spec = CommandFactory.get(name)
    assert spec is not None and spec.name == name


# ── verb parity (the T8a sentinel pattern, applied to the TUIs) ─────────────

def test_every_grammar_verb_is_handled(backend):
    """No verb in the shared grammar may fall through unhandled.

    Closes the last link of the chain. `test_task_grammar_parity.py` pins the
    web client's `TASK_VERBS` against `engine/task_grammar.py`; this pins
    `task_grammar` against what the TUI command actually *does*. Without it a
    verb could be added to the grammar, complete in the UI, and then answer
    "Unsupported verb" — which is exactly the "taught users to type commands
    that answered Unknown command" failure the client gating was introduced to
    fix (Item 40).

    Same shape as `tests/test_vscode_task_controller.py`'s verb-parity
    sentinel, which pins VSCode against the web verb set.
    """
    from ppxai.engine.task_grammar import TASK_VERBS

    meta = backend.registry.start_run(task="t", tools=[], provider="p", model="m")
    unhandled = []
    for verb in sorted(TASK_VERBS):
        result = task_cmd.handle_task(_Ctx(), f"{verb} {meta.run_id}")
        if "Unsupported verb" in (result.message or ""):
            unhandled.append(verb)
    assert not unhandled, f"/task does not handle: {unhandled}"


def test_run_handles_every_verb_it_claims(backend):
    """`/run` handles the shared set minus the two a oneshot cannot have."""
    from ppxai.engine.task_grammar import RUN_ONLY_EXCLUDED_VERBS, TASK_VERBS

    meta = backend.registry.start_run(task="t", kind="oneshot", tools=[],
                                      provider="p", model="m")
    for verb in sorted(TASK_VERBS - RUN_ONLY_EXCLUDED_VERBS):
        result = task_cmd.handle_run(_Ctx(), f"{verb} {meta.run_id}")
        assert "Unsupported verb" not in (result.message or ""), verb


def test_excluded_verbs_are_refused_not_unhandled(backend):
    """respond/resume on /run must explain, not fall through.

    "Unsupported verb" would be true but useless; the user needs to know a
    one-off run never parks, so there is nothing to respond to.
    """
    from ppxai.engine.task_grammar import RUN_ONLY_EXCLUDED_VERBS

    for verb in sorted(RUN_ONLY_EXCLUDED_VERBS):
        result = task_cmd.handle_run(_Ctx(), f"{verb} run_0123456789ab")
        assert "never parks" in result.message, verb


# ── the event-loop gate, both directions ────────────────────────────────────

def test_launch_without_a_loop_is_refused_clearly(backend):
    """Sync context = no running loop. A run would mint and never advance.

    The failure mode this prevents is the worst kind: apparent success. The
    message must name the cause, not just decline.
    """
    result = task_cmd.handle_task(_Ctx(), '"do a thing" --tools read_file')
    assert isinstance(result, ErrorResult)
    assert "event loop" in result.message
    assert "ppxaide" in (result.error_details or "")


@pytest.mark.asyncio
async def test_launch_with_a_loop_succeeds(backend, monkeypatch):
    monkeypatch.setattr("ppxai.engine.task_backend.build_task_runner",
                        _stub_runner())
    result = task_cmd.handle_task(_Ctx(), '"do a thing" --tools read_file')
    assert isinstance(result, NotificationResult)
    assert "run_" in result.message
    assert len(backend.list_runs(kind="task")) == 1


def test_read_verbs_work_without_a_loop(backend):
    """Listing only reads the registry, so it must NOT be gated.

    Gating the whole command on the loop would have denied Rich verbs that
    work perfectly — which is why the gate is per-verb on the capability.
    """
    result = task_cmd.handle_task(_Ctx(), "ls")
    assert not isinstance(result, ErrorResult)


# ── U2 dispatch ─────────────────────────────────────────────────────────────

def test_empty_args_is_help(backend):
    assert "/task" in task_cmd.handle_task(_Ctx(), "").message


def test_ls_empty_then_populated(backend):
    empty = task_cmd.handle_task(_Ctx(), "ls")
    assert isinstance(empty, NotificationResult)

    backend.registry.start_run(task="t", tools=[], provider="p", model="m")
    listed = task_cmd.handle_task(_Ctx(), "ls")
    assert isinstance(listed, TableResult)
    assert listed.columns[0] == "Run" and len(listed.rows) == 1


def test_ls_is_kind_filtered(backend):
    backend.registry.start_run(task="t", kind="task", tools=[],
                               provider="p", model="m")
    backend.registry.start_run(task="o", kind="oneshot", tools=[],
                               provider="p", model="m")
    assert len(task_cmd.handle_task(_Ctx(), "ls").rows) == 1
    assert len(task_cmd.handle_run(_Ctx(), "ls").rows) == 1


def test_near_miss_run_id_fails_loud(backend):
    """A truncated id must not become a run whose prompt is the typo."""
    result = task_cmd.handle_task(_Ctx(), "cancel run_012345")
    assert isinstance(result, ErrorResult)
    assert "run_012345" in result.message


def test_get_unknown_run(backend):
    result = task_cmd.handle_task(_Ctx(), "get run_0123456789ab")
    assert isinstance(result, ErrorResult) and "Unknown run" in result.message


def test_get_reports_status_and_grant(backend):
    meta = backend.registry.start_run(task="inspect me", tools=["read_file"],
                                      provider="p", model="m")
    out = task_cmd.handle_task(_Ctx(), f"get {meta.run_id}")
    assert "inspect me" in out.message and "read_file" in out.message


def test_cancel_a_run_that_is_not_in_flight(backend):
    meta = backend.registry.start_run(task="t", tools=[], provider="p", model="m")
    out = task_cmd.handle_task(_Ctx(), f"cancel {meta.run_id}")
    assert "not in flight" in out.message


# ── /run-specific rules ─────────────────────────────────────────────────────

def test_run_rejects_flags(backend):
    """`/run` takes no flags by design — the grant is config-decided.

    Rejecting beats silently feeding `--tools x` into the prompt text.
    """
    result = task_cmd.handle_run(_Ctx(), "summarize this --tools read_file")
    assert isinstance(result, ErrorResult) and "no flags" in result.message


@pytest.mark.parametrize("verb", ["respond", "resume"])
def test_run_has_no_parking_verbs(backend, verb):
    """A oneshot never parks, so it can be neither responded to nor resumed."""
    result = task_cmd.handle_run(_Ctx(), f"{verb} run_0123456789ab")
    assert isinstance(result, ErrorResult) and "never parks" in result.message


def test_task_reports_parse_errors(backend):
    result = task_cmd.handle_task(_Ctx(), 'x --nope y')
    assert isinstance(result, ErrorResult) and "unknown flag" in result.message


def test_task_requires_a_description(backend):
    result = task_cmd.handle_task(_Ctx(), "--tools read_file")
    assert isinstance(result, ErrorResult) and "needs a description" in result.message


# ── respond ─────────────────────────────────────────────────────────────────

def test_respond_needs_a_decision(backend):
    meta = backend.registry.start_run(task="t", tools=[], provider="p", model="m")
    result = task_cmd.handle_task(_Ctx(), f"respond {meta.run_id}")
    assert isinstance(result, ErrorResult) and "approve|deny" in result.message


def test_respond_on_a_run_that_is_not_waiting(backend):
    meta = backend.registry.start_run(task="t", tools=[], provider="p", model="m")
    result = task_cmd.handle_task(_Ctx(), f"respond {meta.run_id} approve")
    assert isinstance(result, ErrorResult) and "not waiting" in result.message


# ── panel rows are actionable ───────────────────────────────────────────────

def test_ls_declares_a_row_command(backend):
    """Selecting a run in the panel must DO something.

    Live trial (2026-08-09) found the run list inert: the cursor moved and
    Enter did nothing, which reads as a broken widget rather than a list.
    The command declares what activation means — same pattern as
    `focus_panel` — and `{0}` is the Run column.
    """
    backend.registry.start_run(task="t", tools=[], provider="p", model="m")
    result = task_cmd.handle_task(_Ctx(), "ls")
    assert result.metadata["row_command"] == "/task get {0}"
    assert result.columns[0] == "Run", (
        "row_command formats {0} from the first column — it must be the run id"
    )


def test_run_ls_declares_its_own_family(backend):
    backend.registry.start_run(task="t", kind="oneshot", tools=[],
                               provider="p", model="m")
    assert task_cmd.handle_run(_Ctx(), "ls").metadata["row_command"] == "/run get {0}"


def test_row_command_formats_to_a_working_command(backend):
    """The template must produce a command the handler actually accepts."""
    meta = backend.registry.start_run(task="inspect me", tools=[],
                                      provider="p", model="m")
    listed = task_cmd.handle_task(_Ctx(), "ls")
    run_id = listed.rows[0][0]
    command = listed.metadata["row_command"].format(run_id)
    assert command == f"/task get {meta.run_id}"

    # Feed it back through the handler exactly as the app would.
    verb_and_args = command[len("/task "):]
    out = task_cmd.handle_task(_Ctx(), verb_and_args)
    assert "inspect me" in out.message
