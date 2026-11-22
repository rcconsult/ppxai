"""A cancel stops a /task's running tool, and every tool ends with a
`tool_result` run event (owner request 2026-11-22: "user asking stop we
stop"; follows option B, docs/analysis-chat-streaming-and-interrupts.md
section C).

Before: a cancel waited for the tool to finish (30 s of web_search in tai's
retest), and no event said when a tool ended.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ppxai.engine.client as client_mod
import ppxai.server.state as server_state
from ppxai.config import execution as exec_cfg
from ppxai.engine import task_authorizer as authz
from ppxai.engine import task_runner
from ppxai.engine.agent_runs import (
    AgentRunRegistry,
    FilesystemAgentRunStore,
    RunCancelledDuringCall,
    RunControl,
)
from ppxai.engine.call_stop import current_interrupter, install_interrupter
from ppxai.engine.chat import _execute_single_tool
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
from ppxai.engine.tools.builtin.shell import ShellExecuteTool
from ppxai.engine.types import Event, EventType
from ppxai.server.routes import agent_v1

# --- RunControl.stop_tool -----------------------------------------------------


class TestStopTool:
    @pytest.mark.asyncio
    async def test_the_tool_is_cancelled_and_cleans_up_then_the_run_ends(self):
        cleaned = []

        async def tool():
            try:
                await asyncio.sleep(30)
            finally:
                await asyncio.sleep(0.05)   # cleanup takes a moment
                cleaned.append(True)

        task = asyncio.ensure_future(tool())
        await asyncio.sleep(0)
        t0 = time.monotonic()
        with pytest.raises(RunCancelledDuringCall) as err:
            await RunControl(run_id="r").stop_tool(task, tool="slow")
        assert time.monotonic() - t0 < 1.0
        assert cleaned == [True], "the tool's cleanup ran before the run ended"
        assert err.value.resumable is True
        assert "'slow'" in err.value.reason and "tool call" in err.value.reason

    @pytest.mark.asyncio
    async def test_a_tool_that_ignores_the_cancel_does_not_hold_the_run(self):
        release = asyncio.Event()

        async def stubborn():
            while not release.is_set():
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    continue   # refuses to stop (until the test lets it go)

        task = asyncio.ensure_future(stubborn())
        await asyncio.sleep(0)
        t0 = time.monotonic()
        with pytest.raises(RunCancelledDuringCall):
            await RunControl(run_id="r").stop_tool(task, tool="stubborn", grace_s=0.2)
        assert time.monotonic() - t0 < 1.0
        assert not task.done()   # still running; the run ended without it
        release.set()
        task.cancel()
        await asyncio.wait({task}, timeout=1)


# --- the engine's tool step -----------------------------------------------------


class _TM:
    def __init__(self, execute):
        self._execute = execute

    async def execute_tool(self, name, **kwargs):
        return await self._execute(**kwargs)

    def get_tool_display_limit(self, name, args=None):
        return 1000


class _Ctx:
    is_interrupted = False
    turn_sources = None

    def __init__(self, execute):
        self.tool_manager = _TM(execute)


class _Validator:
    def __init__(self):
        self.calls = []

    def record_tool_call(self, **kw):
        self.calls.append(kw)


class TestExecuteSingleTool:
    @pytest.mark.asyncio
    async def test_a_cancel_during_the_tool_ends_the_run_not_as_a_tool_error(self):
        async def slow(**_kw):
            await asyncio.sleep(30)
            return "never"

        ctl = RunControl(run_id="r")
        validator = _Validator()

        async def step():
            with install_interrupter(ctl):
                return await _execute_single_tool(_Ctx(slow), "slow", {}, validator, 1)

        task = asyncio.ensure_future(step())
        await asyncio.sleep(0.1)
        ctl.cancel_requested = True
        with pytest.raises(RunCancelledDuringCall) as err:
            await asyncio.wait_for(task, 2.0)
        assert err.value.resumable is True
        assert validator.calls == [], "a stopped tool is not recorded as a failed call"

    @pytest.mark.asyncio
    async def test_outside_a_run_nothing_changes_and_the_result_says_it_succeeded(self):
        async def quick(**_kw):
            return "ok text"

        result, success, events = await _execute_single_tool(
            _Ctx(quick), "quick", {}, _Validator(), 1)
        assert (result, success) == ("ok text", True)
        [ev] = [e for e in events if e.type == EventType.TOOL_RESULT]
        assert ev.data == {"tool": "quick", "result": "ok text", "success": True}

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX process check (os.kill(pid, 0))")
    @pytest.mark.asyncio
    async def test_a_cancelled_shell_command_is_killed(self, tmp_path):
        """The real shell tool: its process is gone right after the cancel."""
        pid_file = tmp_path / "pid"
        engine = type("E", (), {})()
        engine.get_working_dir = lambda: str(tmp_path)
        engine.request_shell_consent = AsyncMock(return_value=True)
        engine.register_subprocess = lambda proc: None
        engine.unregister_subprocess = lambda proc: None
        shell = ShellExecuteTool(engine)
        command = (f"python3 -c \"import os, time; open({str(pid_file)!r}, 'w')"
                   f".write(str(os.getpid())); time.sleep(30)\"")
        ctl = RunControl(run_id="r")

        async def step():
            with install_interrupter(ctl):
                return await _execute_single_tool(
                    _Ctx(lambda **kw: shell.execute(**kw)), "shell_execute",
                    {"command": command}, _Validator(), 1)

        with patch("ppxai.engine.tools.builtin.shell._get_shell_config",
                   return_value={"timeout": 60, "interactive_commands": [],
                                 "non_interactive_with_args": []}):
            task = asyncio.ensure_future(step())
            for _ in range(100):
                if pid_file.exists() and pid_file.read_text():
                    break
                await asyncio.sleep(0.05)
            pid = int(pid_file.read_text())
            t0 = time.monotonic()
            ctl.cancel_requested = True
            with pytest.raises(RunCancelledDuringCall):
                await asyncio.wait_for(task, 10.0)
        assert time.monotonic() - t0 < 5.0
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail(f"the shell command's process {pid} is still running")


# --- the runner's tool_result events -----------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(server_state, "_agent_run_registry", reg)
    real = exec_cfg.get_execution_task_config
    monkeypatch.setattr(exec_cfg, "get_execution_task_config",
                        lambda: {**real(), "enabled": True})

    class _P(OpenAICompatibleProvider):
        def __init__(self):  # bypass real provider construction
            pass

    monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
    monkeypatch.setattr(authz, "validate_provider_or_error", lambda name: None)
    app = FastAPI()
    app.include_router(agent_v1.router)
    with TestClient(app) as c:
        yield c


def _use_engine(monkeypatch, chat):
    class _TMStub:
        max_iterations = 3

        async def execute_tool(self, name, **kw):
            return "ran"

    class _Engine:
        def __init__(self):
            self.tool_manager = _TMStub()

        def set_provider(self, p): pass
        def set_model(self, m): pass
        def set_working_dir(self, d): pass
        def enable_tools(self): pass

        async def chat(self, task, stream=False, **_kw):
            async for ev in chat():
                yield ev

    stub = _Engine()
    monkeypatch.setattr(client_mod, "EngineClient", lambda: stub)
    monkeypatch.setattr(task_runner, "EngineClient", lambda: stub, raising=False)


_TERMINAL = ("completed", "completed_pending_ack", "finalized", "failed",
             "cancelled", "interrupted")


def _poll(c, rid, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        one = c.get(f"/v1/agent/runs/{rid}").json()
        if one["status"] in _TERMINAL:
            return one
        time.sleep(0.02)
    raise AssertionError(f"run {rid} did not finish: {one}")


def _launch(c):
    resp = c.post("/v1/agent/task", json={
        "task": "t", "tools": ["read_file"], "provider": "p", "model": "m"})
    assert resp.status_code == 200, resp.text
    return resp.json()["run_id"]


def _tool_events(c, rid):
    return [e for e in c.get(f"/v1/agent/runs/{rid}/events?category=tool").json()["events"]
            if e["type"] in ("tool_call", "tool_result")]


class TestToolResultEvents:
    def test_each_tool_gets_a_result_event_with_its_status(self, client, monkeypatch):
        async def chat():
            yield Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"p": "a"}})
            yield Event(EventType.TOOL_RESULT, {"tool": "read_file", "result": "text", "success": True})
            yield Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"p": "b"}})
            yield Event(EventType.TOOL_RESULT, {"tool": "read_file", "result": "Error: no such file",
                                                "success": False})
            yield Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {"p": "c"}})
            yield Event(EventType.TOOL_ERROR, {"tool": "read_file", "error": "boom"})
            yield Event(EventType.STREAM_END, "done")

        _use_engine(monkeypatch, chat)
        rid = _launch(client)
        assert _poll(client, rid)["status"] in ("completed", "completed_pending_ack")
        evs = _tool_events(client, rid)
        assert [e["type"] for e in evs] == ["tool_call", "tool_result"] * 3
        ok, failed, raised = (e["data"] for e in evs if e["type"] == "tool_result")
        assert ok["status"] == "ok" and ok["result"] == "text" and ok["tool"] == "read_file"
        assert failed["status"] == "error" and failed["result"].startswith("Error:")
        assert raised["status"] == "error" and raised["error"] == "boom"
        assert all(isinstance(d["duration_s"], float) for d in (ok, failed, raised))

    def test_a_cancel_stops_the_running_tool_and_says_so(self, client, monkeypatch):
        started = asyncio.Event()

        async def chat():
            # What the engine's tool step does (engine/chat.py::_execute_single_tool).
            yield Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {}})
            interrupter = current_interrupter()
            tool = asyncio.ensure_future(asyncio.sleep(30))
            started.set()
            while not tool.done():
                if interrupter.cancel_requested:
                    await interrupter.stop_tool(tool, tool="read_file")
                await asyncio.sleep(0.02)
            yield Event(EventType.STREAM_END, "never")

        _use_engine(monkeypatch, chat)
        rid = _launch(client)
        deadline = time.monotonic() + 5
        while not _tool_events(client, rid) and time.monotonic() < deadline:
            time.sleep(0.02)
        t0 = time.monotonic()
        assert client.post(f"/v1/agent/runs/{rid}/cancel").json()["status"] == "cancelling"
        one = _poll(client, rid)
        assert time.monotonic() - t0 < 2.0
        assert one["status"] == "cancelled" and one["resumable"] is True
        assert one["result"] is None
        assert "during the tool call 'read_file'" in one["error"]
        evs = _tool_events(client, rid)
        assert [e["type"] for e in evs] == ["tool_call", "tool_result"]
        assert evs[1]["data"]["status"] == "cancelled"
        assert evs[1]["data"]["tool"] == "read_file"

    def test_a_cancel_before_the_tool_starts_emits_no_result(self, client, monkeypatch):
        """check() at TOOL_CALL stops the run before the tool runs: there is
        a tool_call event, and no tool_result for a tool that never ran."""
        gate = asyncio.Event()

        async def chat():
            yield Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {}})
            yield Event(EventType.TOOL_RESULT, {"tool": "read_file", "result": "x", "success": True})
            while not current_interrupter().cancel_requested:
                await asyncio.sleep(0.02)
            yield Event(EventType.TOOL_CALL, {"tool": "read_file", "arguments": {}})
            await gate.wait()

        _use_engine(monkeypatch, chat)
        rid = _launch(client)
        deadline = time.monotonic() + 5
        while len(_tool_events(client, rid)) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        client.post(f"/v1/agent/runs/{rid}/cancel")
        one = _poll(client, rid)
        assert one["status"] == "cancelled"
        assert [e["type"] for e in _tool_events(client, rid)] == ["tool_call", "tool_result"]

