"""Pin WHICH name `runner_builder` resolves to when a child run is built.

`agent_v1.build_task_runner` passes itself as `runner_builder=` to
`SpawnSubagentTool` (agent_v1.py:1365) so a spawned child is constructed by
the same builder. That reference is a **module global resolved at call time
from the globals of the module the function body lives in** — today,
`agent_v1`. Patching `agent_v1.build_task_runner` therefore redirects child
construction as well as top-level.

Once the body moves to an engine module (planned: `ppxai/engine/task_runner.py`),
a re-export keeps the *name* `agent_v1.build_task_runner` importable but the
recursion resolves in the NEW module. Patching the re-export would then
redirect only top-level runs, and a child would be built by the real builder
while a test believed it had installed a stub.

The four existing monkeypatch sites cannot catch that regression
(`test_agent_runs.py:951, 1044, 2624, 2682`): every one replaces the builder
with a stub that returns immediately, so the real `_runner` body never
executes and `:1365` never fires. They stay green through it.

Why this matters beyond hygiene: intercepting child-run construction is how
ppxai-sre applies its PolicyEngine to spawned children, so the patch point is
a supported integration surface and must not move silently.
See docs/handoff-build-task-runner-extraction.md.

**These tests are expected to be GREEN before the extraction and RED after
it** unless the canonical name is deliberately settled. A red here is the
finding, not a broken test — read the docstring before "fixing" it.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from ppxai.server.routes import agent_v1


class _StopAfterCapture(Exception):
    """Abort `_runner` once the spawn tool has been constructed."""


def test_recursion_resolves_in_the_module_that_defines_the_body():
    """Structural form: which globals does the `:1365` reference read?

    `__globals__` IS the namespace a bare global name resolves against, so
    this is the mechanism itself rather than a proxy for it. After the
    extraction this becomes `ppxai.engine.task_runner`'s dict, and the
    assertion fails — which is the intended signal.
    """
    defining_module = agent_v1.build_task_runner.__globals__.get("__name__")
    assert defining_module == "ppxai.server.routes.agent_v1", (
        f"build_task_runner's body now lives in {defining_module!r}, so the "
        f"`runner_builder=build_task_runner` reference at agent_v1.py:1365 "
        f"resolves THERE, not in agent_v1. Patching agent_v1.build_task_runner "
        f"no longer redirects child-run construction. Settle which name is "
        f"canonical and update this test deliberately — see the module "
        f"docstring."
    )
    assert agent_v1.build_task_runner.__globals__ is sys.modules[
        "ppxai.server.routes.agent_v1"
    ].__dict__


def test_patching_the_module_attribute_redirects_child_construction(monkeypatch):
    """Behavioural form: does a patch actually reach `:1365`?

    Runs the REAL builder far enough to construct the spawn tool, then stops.
    Deliberately does not stub the builder itself — that is precisely what
    blinds the existing tests to this code path.
    """
    captured: dict = {}

    def _capture_spawn_tool(**kwargs):
        captured.update(kwargs)
        raise _StopAfterCapture

    sentinel = object()

    # Keep a direct handle BEFORE patching: we need the real body to run while
    # the module attribute it will resolve points at the sentinel.
    real_builder = agent_v1.build_task_runner

    monkeypatch.setattr(agent_v1, "build_task_runner", sentinel)
    monkeypatch.setattr(agent_v1, "SpawnSubagentTool", _capture_spawn_tool)
    monkeypatch.setattr(agent_v1, "EngineClient", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(agent_v1, "compose_agent_system_prompt", lambda s: "sys")
    monkeypatch.setattr(
        agent_v1, "get_execution_task_config",
        lambda: {"consent": {"spawn_consent": "deny", "consent_ttl_s": 300}},
    )

    runner = real_builder(
        _FakeRegistry(),
        provider_name="fakeprov", model="fakemodel", task="t",
        tools=["spawn_subagent"], allow_outbound=[], allow_spawn=True,
    )
    with pytest.raises(_StopAfterCapture):
        asyncio.run(runner(_FakeMeta()))

    assert captured, "SpawnSubagentTool was never constructed — the test no " \
                     "longer reaches agent_v1.py:1365"
    assert captured["runner_builder"] is sentinel, (
        "the child-run builder did NOT resolve to the patched "
        "agent_v1.build_task_runner. If the body has moved to another module, "
        "patching the re-export silently stops redirecting child runs."
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
