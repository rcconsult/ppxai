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

    @staticmethod
    def _poll_terminal(c, run_id, timeout_s=5.0):
        """Poll GET until the run reaches a terminal status (Inc 2 is async)."""
        import time as _t

        deadline = _t.monotonic() + timeout_s
        while _t.monotonic() < deadline:
            one = c.get(f"/v1/agent/runs/{run_id}").json()
            if one["status"] in ("completed", "failed"):
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

    def test_unsupported_provider_400_no_run_created(self, client, monkeypatch):
        # Carve-out runs BEFORE minting -> unsupported provider 400, no run.
        c, reg = client
        from ppxai.server.routes import agent_v1

        monkeypatch.setattr(agent_v1, "_build_provider", lambda name: object())

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
