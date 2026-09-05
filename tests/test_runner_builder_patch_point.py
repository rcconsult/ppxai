"""Pin WHICH name `runner_builder` resolves to when a child run is built.

**Canonical patch point: `ppxai.engine.task_runner.build_task_runner`.**

`build_task_runner` passes ITSELF as `runner_builder=` to `SpawnSubagentTool`
so a spawned child is constructed by the same builder. That reference is a
module global resolved at call time from the globals of the module the
function BODY lives in — since the v1.19.1 extraction, `engine.task_runner`.

For one patch to redirect BOTH top-level and child construction, every caller
must reach the builder through the module attribute rather than a from-import
binding. `agent_v1` and `oneshot` therefore call
`_task_runner.build_task_runner(...)`. `agent_v1.build_task_runner` still
exists as an import alias for source compatibility, but **patching that name
is inert** — it is a second binding to the same object, and rebinding it
changes nothing `task_runner` resolves. The third test below pins exactly
that, so the alias cannot quietly become a false patch point again.

These tests were written BEFORE the extraction, when the body lived in
`agent_v1`, and were green then. The move turned them red on arrival exactly
as predicted, which is why they were updated deliberately here rather than
being discovered after the fact. If they go red again, the resolution point
has moved: settle where it should be and update this file on purpose.

Intercepting child-run construction is how ppxai-sre applies its PolicyEngine
to spawned children, so this is a supported integration surface, not internal
detail. See docs/archive/handoff-build-task-runner-extraction.md.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from ppxai.engine import task_runner
from ppxai.server.routes import agent_v1
from ppxai.config import execution as _exec_cfg


class _StopAfterCapture(Exception):
    """Abort `_runner` once the spawn tool has been constructed."""


def test_recursion_resolves_in_the_module_that_defines_the_body():
    """Structural form: which globals does the self-reference read?

    `__globals__` IS the namespace a bare global name resolves against, so
    this is the mechanism itself rather than a proxy for it.
    """
    defining = task_runner.build_task_runner.__globals__.get("__name__")
    assert defining == "ppxai.engine.task_runner", (
        f"build_task_runner's body now lives in {defining!r}, so the "
        f"`runner_builder=build_task_runner` self-reference resolves THERE. "
        f"Patching ppxai.engine.task_runner.build_task_runner would no longer "
        f"redirect child-run construction. Settle which name is canonical and "
        f"update this test deliberately — see the module docstring."
    )
    assert task_runner.build_task_runner.__globals__ is sys.modules[
        "ppxai.engine.task_runner"
    ].__dict__


def test_patching_the_canonical_name_redirects_child_construction(monkeypatch):
    """Behavioural form: does a patch actually reach the spawn registration?

    Runs the REAL builder far enough to construct the spawn tool, then stops.
    Deliberately does not stub the builder itself — that is precisely what
    blinds the other monkeypatch sites in this suite to this code path.
    """
    captured: dict = {}

    def _capture_spawn_tool(**kwargs):
        captured.update(kwargs)
        raise _StopAfterCapture

    sentinel = object()
    real_builder = task_runner.build_task_runner  # handle taken BEFORE patching

    monkeypatch.setattr(task_runner, "build_task_runner", sentinel)
    _install_runner_stubs(monkeypatch, _capture_spawn_tool)

    runner = real_builder(
        _FakeRegistry(),
        provider_name="fakeprov", model="fakemodel", task="t",
        tools=["spawn_subagent"], allow_outbound=[], allow_spawn=True,
    )
    with pytest.raises(_StopAfterCapture):
        asyncio.run(runner(_FakeMeta()))

    assert captured, ("SpawnSubagentTool was never constructed — this test no "
                      "longer reaches the spawn registration")
    assert captured["runner_builder"] is sentinel, (
        "the child-run builder did NOT resolve to the patched "
        "task_runner.build_task_runner"
    )


def test_the_agent_v1_alias_is_not_a_patch_point(monkeypatch):
    """Patching the compat alias must NOT redirect child construction.

    Documented behaviour, pinned so it cannot silently become a trap: someone
    patching `agent_v1.build_task_runner` should get a loudly wrong result
    here rather than a quietly wrong one in production, where a child would be
    built by the real builder while a test believed it had installed a stub.
    """
    assert agent_v1.build_task_runner is task_runner.build_task_runner, (
        "the compat alias no longer points at the canonical builder"
    )

    captured: dict = {}

    def _capture_spawn_tool(**kwargs):
        captured.update(kwargs)
        raise _StopAfterCapture

    real_builder = task_runner.build_task_runner
    monkeypatch.setattr(agent_v1, "build_task_runner", object())  # the inert one
    _install_runner_stubs(monkeypatch, _capture_spawn_tool)

    runner = real_builder(
        _FakeRegistry(),
        provider_name="p", model="m", task="t",
        tools=["spawn_subagent"], allow_outbound=[], allow_spawn=True,
    )
    with pytest.raises(_StopAfterCapture):
        asyncio.run(runner(_FakeMeta()))

    assert captured["runner_builder"] is real_builder, (
        "patching agent_v1.build_task_runner appears to have redirected child "
        "construction. Either the alias became load-bearing or the callers "
        "stopped resolving through the module — both change the documented "
        "patch point."
    )


def _install_runner_stubs(monkeypatch, spawn_tool):
    """Neutralise everything the runner touches before the spawn registration."""
    monkeypatch.setattr(task_runner, "SpawnSubagentTool", spawn_tool)
    monkeypatch.setattr(task_runner, "EngineClient", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(task_runner, "compose_agent_system_prompt", lambda s: "sys")
    monkeypatch.setattr(
        _exec_cfg, "get_execution_task_config",
        lambda: {"consent": {"spawn_consent": "deny", "consent_ttl_s": 300}},
    )


class _FakeMeta:
    run_id = "run_0123456789ab"
    owner = None


class _FakeRegistry:
    def emit_event(self, *a, **k):
        pass

    async def park_run(self, *a, **k):
        return {"approved": False}

    def get_control(self, *a, **k):
        return None


class _FakeEngine:
    def __init__(self):
        self.tool_manager = _FakeToolManager()
        self.system_prompt_override = None

    def set_provider(self, *a, **k):
        pass

    def set_model(self, *a, **k):
        pass

    def enable_tools(self, *a, **k):
        pass


class _FakeToolManager:
    def register_tool(self, *a, **k):
        pass
