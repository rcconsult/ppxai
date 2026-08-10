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
from ppxai.engine.task_authorizer import AuthorizedTask
from ppxai.engine.task_backend import InProcessTaskBackend, collect_holds


@pytest.fixture
def backend(tmp_path):
    """A backend over an isolated run store — never the user's ~/.ppxai/runs."""
    registry = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    return InProcessTaskBackend(registry)


def _authorized(task="do a thing", *, tools=(), provider="p", model="m", **kw):
    """An already-authorized launch, for tests about LIFECYCLE not admission.

    `launch()` takes an `AuthorizedTask` by design: the only way to get one in
    production is `authorize_task()`, so the in-process path cannot skip the
    tier gate / shell reject / skill name-resolution the way it used to.
    These tests exercise what happens AFTER admission, so they construct the
    approved value directly. Admission itself is pinned in
    tests/test_task_authorization_parity.py.
    """
    return AuthorizedTask(
        task=task, tools=list(tools), provider=provider, model=model,
        system=kw.get("system"), budget=kw.get("budget") or {},
        network=kw.get("network") or [], read_roots=kw.get("read_roots") or [],
        workdir=kw.get("workdir"), workdir_ignored=False,
        enrichment=False, enrichment_layer=None, tools_layer=None, stripped=[],
    )


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

    meta = backend.launch(_authorized("do a thing", tools=["read_file"]))
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
    meta = backend.launch(_authorized("slow"))

    # The run has not finished; the call already returned.
    assert backend.get_run(meta.run_id).status in {"pending", "running"}
    await asyncio.wait_for(started.wait(), timeout=2.0)
    assert backend.get_run(meta.run_id).result is None


@pytest.mark.asyncio
async def test_held_result_needs_collect(backend, monkeypatch):
    """U4/T6: with execution.collect="yes" the result is HELD until collected."""
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner("held"))
    monkeypatch.setattr(task_backend, "collect_holds", lambda: True)

    meta = backend.launch(_authorized("hold me"))
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
    meta = backend.launch(_authorized("long"))
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

    t = backend.launch(_authorized("a task"), kind="task")
    o = backend.launch(_authorized("a oneshot"), kind="oneshot")
    for rid in (t.run_id, o.run_id):
        await _poll(backend, rid, {"completed", "failed"})

    assert [r.run_id for r in backend.list_runs(kind="task")] == [t.run_id]
    assert [r.run_id for r in backend.list_runs(kind="oneshot")] == [o.run_id]
    assert len(backend.list_runs()) == 2


@pytest.mark.asyncio
async def test_events_are_recorded_for_a_run(backend, monkeypatch):
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner())
    monkeypatch.setattr(task_backend, "collect_holds", lambda: False)
    meta = backend.launch(_authorized("x"))
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
    meta = backend.launch(_authorized("y"))
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

    backend.launch(_authorized("no spawn", tools=["read_file"]))
    assert seen["allow_spawn"] is False

    backend.launch(_authorized("may spawn",
                               tools=["read_file", "spawn_subagent"]))
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


# ── U4 merge: how a run's result reaches the conversation ───────────────────

class _FakeSession:
    def __init__(self):
        self.messages = []

    def add_message(self, m):
        self.messages.append(m)


@pytest.fixture
def backend_with_session(tmp_path):
    session = _FakeSession()
    registry = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    b = InProcessTaskBackend(registry, session_provider=lambda: session)
    return b, session


@pytest.mark.asyncio
async def test_collect_merges_the_result_as_a_pair(backend_with_session, monkeypatch):
    """THE regression: collect used to finalize and never merge.

    Web and VSCode both ack THEN merge. Doing only the first leaves the run
    finalized and the conversation unchanged — which is why every TUI session
    was message-less and session restore had nothing to restore.
    """
    backend, session = backend_with_session
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner("the answer"))
    monkeypatch.setattr(task_backend, "collect_holds", lambda: True)

    meta = backend.launch(_authorized("what is the answer"))
    await _poll(backend, meta.run_id, {"completed_pending_ack", "failed"})

    ok, _ = backend.collect(meta.run_id)
    assert ok
    assert len(session.messages) == 2, (
        "the merge must be a user->assistant PAIR — validate_and_fix_alternation "
        "drops a lone message of either role"
    )
    assert session.messages[0].role == "user"
    assert session.messages[0].content == "what is the answer"
    assert session.messages[1].role == "assistant"
    assert session.messages[1].content == "the answer"


def test_merge_refused_when_collect_disabled(backend_with_session, monkeypatch):
    """`execution.collect="no"` must SAY so, not silently drop the result."""
    import ppxai.config.execution as execution_cfg

    backend, session = backend_with_session
    monkeypatch.setattr(execution_cfg, "get_execution_collect", lambda: "no")
    ok, reason = backend.merge_result("run_0123456789ab")
    assert ok is False
    assert "Collect is disabled" in reason
    assert session.messages == []


def test_merge_without_a_session_provider_is_reported(tmp_path):
    """A backend with no session (Rich today, tests) must not pretend."""
    b = InProcessTaskBackend(AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "r")))
    ok, reason = b.merge_result("run_0123456789ab")
    assert ok is False and "session" in reason


@pytest.mark.asyncio
async def test_collect_reports_when_the_merge_fails(backend_with_session, monkeypatch):
    """The run IS collected even if the merge isn't — say both, lose neither."""
    backend, session = backend_with_session
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner("x"))
    monkeypatch.setattr(task_backend, "collect_holds", lambda: True)
    meta = backend.launch(_authorized("t"))
    await _poll(backend, meta.run_id, {"completed_pending_ack", "failed"})

    backend._session_provider = lambda: None  # session vanished
    ok, reason = backend.collect(meta.run_id)
    assert ok is True and "not merged" in reason


@pytest.mark.asyncio
async def test_auto_merge_only_in_auto_mode(backend_with_session, monkeypatch):
    """Under "auto" nothing holds the result, so the watcher must merge it."""
    import ppxai.config.execution as execution_cfg

    backend, session = backend_with_session
    monkeypatch.setattr(task_backend, "build_task_runner", _stub_runner("auto result"))
    monkeypatch.setattr(task_backend, "collect_holds", lambda: False)
    meta = backend.launch(_authorized("t"))
    await _poll(backend, meta.run_id, {"completed", "failed"})

    monkeypatch.setattr(execution_cfg, "get_execution_collect", lambda: "yes")
    assert backend.auto_merge_if_configured(meta.run_id)[0] is False
    assert session.messages == [], "under 'yes' the user collects; do not auto-merge"

    monkeypatch.setattr(execution_cfg, "get_execution_collect", lambda: "auto")
    assert backend.auto_merge_if_configured(meta.run_id)[0] is True
    assert len(session.messages) == 2


def test_configure_is_idempotent(tmp_path, monkeypatch):
    """Called on every /task dispatch — must not sweep twice or stack hooks."""
    registry = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    shared = InProcessTaskBackend(registry)
    monkeypatch.setattr(task_backend, "_shared", shared)

    sweeps = []
    hooks = []
    monkeypatch.setattr(registry, "sweep_orphans", lambda: sweeps.append(1))
    monkeypatch.setattr(registry, "on_change", lambda cb: hooks.append(cb))

    for _ in range(3):
        task_backend.configure_task_backend(
            session_provider=lambda: None, on_change=lambda: None
        )
    assert sweeps == [1], "swept more than once"
    assert len(hooks) == 1, "stacked change hooks"
