"""In-process run lifecycle via `InProcessTaskBackend` (T8b embed half).

These exercise the embed path with NO server: a real `AgentRunRegistry` over a
tmp filesystem store, driven directly. That is the thing the TUI port depends
on, and until now the only evidence the runner could be driven in-process was
that it had no HTTP coupling — an absence, not a demonstration.

Patch target note: `build_task_runner` is patched on `task_backend`, because
that is the module whose globals the backend resolves it from. Patching
`engine.task_runner` would work too (it is the canonical name and the backend
imported FROM it, so the binding here is separate). This file patches the
binding the code under test actually reads — the discipline that the
extraction made unavoidable.
"""

from __future__ import annotations

import asyncio

import pytest

from ppxai.engine import task_backend
from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.task_backend import InProcessTaskBackend, collect_holds


@pytest.fixture
def backend(tmp_path):
    """A backend over an isolated run store — never the user's ~/.ppxai/runs."""
    registry = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    return InProcessTaskBackend(registry)


def _stub_runner(text="ok"):
    async def _runner(meta):
        return text
    return lambda *a, **k: _runner


async def _poll(backend, run_id, terminal, timeout=5.0):
    """Wait for a run to reach one of `terminal`, or fail loudly."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        meta = backend.get_run(run_id)
        if meta is not None and meta.status in terminal:
            return meta
        await asyncio.sleep(0.02)
    got = backend.get_run(run_id)
    raise AssertionError(
        f"run {run_id} never reached {terminal}; last status="
        f"{getattr(got, 'status', None)!r}"
    )


# ── launch + lifecycle ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_launch_runs_to_completion_without_a_server(backend, monkeypatch):
    """The whole point of the embed path: no HTTP anywhere in this test."""
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner("done"))
    monkeypatch.setattr(task_backend, "collect_holds", lambda: False)

    meta = backend.launch("do a thing", tools=["read_file"],
                          provider="p", model="m")
    assert meta.run_id.startswith("run_")

    final = await _poll(backend, meta.run_id, {"completed", "failed"})
    assert final.status == "completed", final.error
    assert final.result == "done"


@pytest.mark.asyncio
async def test_launch_returns_immediately(backend, monkeypatch):
    """Non-blocking by construction — the caller gets an id, not a result.

    A slow runner must not delay the launch call, or a TUI would freeze for
    the duration of the run and the whole 'chat stays usable' promise fails.
    """
    started = asyncio.Event()

    def _slow(*a, **k):
        async def _runner(meta):
            started.set()
            await asyncio.sleep(0.3)
            return "late"
        return _runner

    monkeypatch.setattr(task_backend, "build_task_runner", _slow)
    meta = backend.launch("slow", tools=[], provider="p", model="m")

    # The run has not finished; the call already returned.
    assert backend.get_run(meta.run_id).status in {"pending", "running"}
    await asyncio.wait_for(started.wait(), timeout=2.0)
    assert backend.get_run(meta.run_id).result is None


@pytest.mark.asyncio
async def test_held_result_needs_collect(backend, monkeypatch):
    """U4/T6: with execution.collect="yes" the result is HELD until collected."""
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner("held"))
    monkeypatch.setattr(task_backend, "collect_holds", lambda: True)

    meta = backend.launch("hold me", tools=[], provider="p", model="m")
    held = await _poll(backend, meta.run_id, {"completed_pending_ack", "failed"})
    assert held.status == "completed_pending_ack"

    ok, _ = backend.collect(meta.run_id)
    assert ok
    assert backend.get_run(meta.run_id).status == "finalized"


@pytest.mark.asyncio
async def test_cancel_stops_a_cooperating_run(backend, monkeypatch):
    """Cancellation is COOPERATIVE — the runner has to poll for it.

    `cancel_run` flips a flag and moves the run to `cancelling`; the runner
    observes it at its next `control.check()` and raises, so the stop lands at
    a clean checkpoint and never mid-tool-call. This stub therefore polls the
    way the real runner does at each tool-loop boundary.

    Corollary worth knowing: a runner that never polls is NOT force-killed.
    An earlier version of this test used a plain `asyncio.sleep(30)` stub and
    hung — the test was wrong, not the code.
    """
    def _cooperative(*a, **k):
        async def _runner(meta):
            control = backend.registry.get_control(meta.run_id)
            for _ in range(500):
                if control is not None:
                    control.check(now=asyncio.get_event_loop().time())
                await asyncio.sleep(0.01)
            return "never"
        return _runner

    monkeypatch.setattr(task_backend, "build_task_runner", _cooperative)
    meta = backend.launch("long", tools=[], provider="p", model="m")
    await _poll(backend, meta.run_id, {"running"})

    assert backend.cancel(meta.run_id) is True
    final = await _poll(backend, meta.run_id,
                        {"cancelled", "failed", "interrupted"})
    assert final.status == "cancelled", final.status
    assert final.result != "never", "the runner completed despite the cancel"


# ── observation ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_runs_is_kind_filtered(backend, monkeypatch):
    """`/task ls` shows task runs, `/run ls` shows oneshots (U3)."""
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner())
    monkeypatch.setattr(task_backend, "collect_holds", lambda: False)

    t = backend.launch("a task", tools=[], provider="p", model="m", kind="task")
    o = backend.launch("a oneshot", tools=[], provider="p", model="m",
                       kind="oneshot")
    for rid in (t.run_id, o.run_id):
        await _poll(backend, rid, {"completed", "failed"})

    assert [r.run_id for r in backend.list_runs(kind="task")] == [t.run_id]
    assert [r.run_id for r in backend.list_runs(kind="oneshot")] == [o.run_id]
    assert len(backend.list_runs()) == 2


@pytest.mark.asyncio
async def test_events_are_recorded_for_a_run(backend, monkeypatch):
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner())
    monkeypatch.setattr(task_backend, "collect_holds", lambda: False)
    meta = backend.launch("x", tools=[], provider="p", model="m")
    await _poll(backend, meta.run_id, {"completed", "failed"})
    assert backend.events(meta.run_id), "no events recorded for the run"


# ── refusals ────────────────────────────────────────────────────────────────

def test_resume_refuses_unknown_run(backend):
    ok, reason = backend.resume("run_ffffffffffff")
    assert ok is False and "unknown" in reason


@pytest.mark.asyncio
async def test_resume_refuses_a_completed_run(backend, monkeypatch):
    """The 409 contract, in-process: a conclusive run is not resumable.

    Resuming a finished run would execute it twice — the refusal is the
    safety property, not a convenience.
    """
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner())
    monkeypatch.setattr(task_backend, "collect_holds", lambda: False)
    meta = backend.launch("y", tools=[], provider="p", model="m")
    await _poll(backend, meta.run_id, {"completed", "failed"})

    ok, reason = backend.resume(meta.run_id)
    assert ok is False and reason


# ── grant derivation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_allow_spawn_is_derived_from_the_grant(backend, monkeypatch):
    """Depth cannot be widened by asking — it follows the grant.

    `allow_spawn` is not a backend parameter: a caller who wants a child run
    must hold `spawn_subagent` in its own grant, which is the structural
    depth cap the runner relies on.
    """
    seen = {}

    def _capture(*a, **k):
        seen.update(k)
        async def _runner(meta):
            return "ok"
        return _runner

    monkeypatch.setattr(task_backend, "build_task_runner", _capture)
    monkeypatch.setattr(task_backend, "collect_holds", lambda: False)

    backend.launch("no spawn", tools=["read_file"], provider="p", model="m")
    assert seen["allow_spawn"] is False

    backend.launch("may spawn", tools=["read_file", "spawn_subagent"],
                   provider="p", model="m")
    assert seen["allow_spawn"] is True


def test_collect_holds_maps_execution_collect(monkeypatch):
    import ppxai.config.execution as execution_cfg

    monkeypatch.setattr(execution_cfg, "get_execution_collect", lambda: "yes")
    assert collect_holds() is True
    monkeypatch.setattr(execution_cfg, "get_execution_collect", lambda: "auto")
    assert collect_holds() is False
    monkeypatch.setattr(execution_cfg, "get_execution_collect", lambda: "no")
    assert collect_holds() is False

    def _boom():
        raise RuntimeError("bad config")

    # A broken config must not block a launch; it falls back to holding.
    monkeypatch.setattr(execution_cfg, "get_execution_collect", _boom)
    assert collect_holds() is True
