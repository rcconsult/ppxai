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
