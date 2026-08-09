"""`execution.egress_ceiling` is an ENGINE guarantee, not a route control.

Until v1.19.1 `apply_egress_ceiling` had exactly one caller —
`agent_v1._enriched_oneshot_egress_or_400`, a route-level helper — and
`NetworkPolicy.__init__` never applied it. So any in-process caller of
`build_task_runner` got **no ceiling at all**, not a weakened one.

The gap arrived with the extraction (the ceiling stayed at the route while the
runner became independently callable) and went live with the T8b in-process
backend, where `/task --allow <host>` from a TUI would have escaped a
deployment-wide cap the operator believed was un-raisable.

Found by the ppxai-sre session while checking a claim I had explicitly flagged
as a belief rather than a fact — I had assumed "the check routes through
NetworkPolicy". It does not: it is applied to the allowlist *before*
NetworkPolicy is constructed. Skip the route, skip the ceiling.

These tests drive `build_task_runner` DIRECTLY, never through an HTTP route,
because a test that goes through the route would pass while proving nothing
about the path that matters.
"""

from __future__ import annotations

import asyncio

import pytest

import ppxai.config.execution as execution_cfg
from ppxai.engine import task_runner

CEILING = ["api.corp.internal"]


class _Stop(Exception):
    """Abort the runner once the egress policy has been constructed."""


class _FakeMeta:
    run_id = "run_0123456789ab"
    owner = None


class _FakeRegistry:
    def __init__(self):
        self.events = []

    def emit_event(self, run_id, event, *, level="info", category="", data=None):
        self.events.append((event, data or {}))

    def get_control(self, run_id):
        return None


class _FakeToolManager:
    def register_tool(self, *a, **k):
        pass


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


@pytest.fixture
def captured(monkeypatch):
    """Run the real builder until NetworkPolicy is constructed, capturing it."""
    seen = {}

    class _CapturingPolicy:
        def __init__(self, allow, provider_name=None):
            seen["allow"] = list(allow)
            raise _Stop

    # The REAL apply_egress_ceiling runs; only the config it reads is faked,
    # so this exercises the actual intersection rather than a stand-in.
    # `apply_egress_ceiling` imports the accessor INSIDE the function, so it
    # resolves from config.execution at call time — patching network_policy's
    # namespace would be inert (the same module-global lesson as everywhere
    # else in this suite).
    monkeypatch.setattr(execution_cfg, "get_execution_egress_ceiling",
                        lambda: CEILING)
    monkeypatch.setattr(task_runner, "NetworkPolicy", _CapturingPolicy)
    monkeypatch.setattr(task_runner, "EngineClient", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(task_runner, "compose_agent_system_prompt", lambda s: "sys")
    monkeypatch.setattr(
        task_runner, "get_execution_task_config",
        lambda: {"consent": {"spawn_consent": "deny", "consent_ttl_s": 300},
                 "sandbox": {"enforcement": "off"}},
    )
    return seen


def _drive(registry, allow_outbound):
    runner = task_runner.build_task_runner(
        registry,
        provider_name="p", model="m", task="t",
        tools=[], allow_outbound=allow_outbound,
    )
    with pytest.raises(_Stop):
        asyncio.run(runner(_FakeMeta()))


def test_ceiling_applies_to_an_embedded_run(captured):
    """The regression itself: an in-process run cannot exceed the ceiling."""
    reg = _FakeRegistry()
    _drive(reg, ["evil.example.com", "api.corp.internal"])

    assert captured["allow"] == ["api.corp.internal"], (
        "an embedded run kept a host the deployment ceiling forbids — the "
        "ceiling is not being applied outside the HTTP route"
    )


def test_ceiling_strip_is_not_silent(captured):
    """A narrowed run must be distinguishable from one that never asked.

    Without the event, an operator ceiling quietly removing a host looks
    identical to a run whose allowlist never contained it — and the failure
    surfaces later as an unexplained egress denial.
    """
    reg = _FakeRegistry()
    _drive(reg, ["evil.example.com"])

    names = [e for e, _ in reg.events]
    assert "egress_ceiling_applied" in names, names
    payload = dict(reg.events[names.index("egress_ceiling_applied")][1])
    assert "evil.example.com" in str(payload.get("stripped"))


def test_no_event_when_nothing_is_stripped(captured):
    """Guard the negative case, so the event can't become noise on every run."""
    reg = _FakeRegistry()
    _drive(reg, ["api.corp.internal"])

    assert captured["allow"] == ["api.corp.internal"]
    assert "egress_ceiling_applied" not in [e for e, _ in reg.events]


def test_empty_allowlist_stays_empty(captured):
    """Fail-closed baseline: no request for egress must not become egress."""
    reg = _FakeRegistry()
    _drive(reg, [])
    assert captured["allow"] == []
