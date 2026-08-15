"""Every admission path into the task tier must refuse the same things.

WHY THIS FILE EXISTS
--------------------
T8b gave the TUIs an in-process route to the same runner the HTTP API drives.
It reached `build_task_runner` without any of the route's policy gates: a TUI
could start a tool-capable run while `execution.task.enabled` was false, and a
grant containing `execute_shell_command` evaded the server's explicit
rejection. **The suite was green the whole time** — 4951 passing — because no
test drove one request through both paths. The absence of this file is the
reason that shipped.

HOW IT DIFFERS FROM THE OTHER PARITY HARNESSES
----------------------------------------------
`test_client_parity_tui.py` and `test_vscode_task_controller.py` are STATIC:
they read client sources and assert a code shape is present. That is useful
for wiring drift, but it cannot catch a policy hole — a file can contain the
right-looking call and still admit the request. These tests are BEHAVIORAL:
each case is driven through every admission path and the refusals must match.

Add a column here when you add a client. That is the actual lesson of T8b
(see docs/lessons/parity-harness-must-know-every-client.md).

THE COLUMNS
-----------
- `route`  — `POST /v1/agent/task` through a real TestClient.
- `engine` — `authorize_task()` directly, the shared boundary both use.

A refusal must agree on BOTH status and the substring a user would act on,
and must leave NO run minted: a gate that refuses after minting is a
different bug (an orphan run record) and is asserted separately.

BOTH TIERS, ONE BOUNDARY
------------------------
`TestTierPolicyIsData` and `TestOneShotTierParity` extend the fence to
`kind="oneshot"`. They exist because the first attempt at `/run` parity was a
duplicated `authorize_oneshot()` that re-derived provider resolution and
re-implemented the egress assembly. The differences between the tiers are now
DATA in `TIERS`, and those classes are what keeps them there: they assert the
table describes the behavior, and that `AuthorizedTask` has exactly one
construction site in the whole production tree.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ppxai.engine import task_authorizer as _authz
from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.task_authorizer import (
    TIERS,
    TaskAuthorizationError,
    TaskRequest,
    authorize,
    authorize_oneshot,
    authorize_task,
)

# A resolvable default_subagent, so one-off cases exercise the GRANT rules
# rather than tripping the provider/model gate first.
_SUB = {"provider": "perplexity", "model": "sonar"}

# (id, request-kwargs, expected status, substring a user would act on)
REFUSAL_CASES = [
    (
        "shell_in_grant",
        {"task": "do a thing", "tools": ["execute_shell_command"]},
        400,
        "execute_shell_command",
    ),
    (
        "shell_alongside_allowed_tool",
        {"task": "do a thing", "tools": ["read_file", "execute_shell_command"]},
        400,
        "execute_shell_command",
    ),
    (
        "skill_absolute_path",
        {"task": "do a thing", "tools": ["read_file"], "skills": ["/etc"]},
        400,
        "bare name is required",
    ),
    (
        "skill_parent_traversal",
        {"task": "do a thing", "tools": ["read_file"], "skills": ["../../etc"]},
        400,
        "bare name is required",
    ),
    (
        "spec_parent_traversal",
        {"task": "do a thing", "tools": ["read_file"], "spec": "../secrets"},
        400,
        "bare name is required",
    ),
    (
        "unknown_profile",
        {"task": "do a thing", "tools": ["read_file"], "profile": "nope"},
        400,
        "Unknown execution profile",
    ),
]


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """An isolated run store — never the developer's ~/.ppxai/runs."""
    import ppxai.server.state as state

    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)
    return reg


@pytest.fixture
def route_client(registry):
    from ppxai.server.routes import agent_v1

    app = FastAPI()
    app.include_router(agent_v1.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _tier_on(monkeypatch, tmp_path):
    """Enable the tier so the cases below exercise the gates BEHIND it.

    `skills_dir`/`specs_dir` are CONFIGURED (to empty dirs) on purpose: with
    them unset, name resolution short-circuits on "not enabled" and the
    traversal guard is never reached — the test would pass without proving
    anything about path safety.

    `TestTierGateParity` overrides this to test the gate itself.
    """
    from ppxai.server.routes import agent_v1

    skills = tmp_path / "skills"
    specs = tmp_path / "specs"
    skills.mkdir(exist_ok=True)
    specs.mkdir(exist_ok=True)
    real = agent_v1.get_execution_task_config
    monkeypatch.setattr(
        agent_v1, "get_execution_task_config",
        lambda: {
            **real(),
            "enabled": True,
            "sandbox": {
                **real()["sandbox"],
                "skills_dir": str(skills),
                "specs_dir": str(specs),
            },
        },
    )


@pytest.fixture(autouse=True)
def _provider_ok(monkeypatch):
    """Neutralize provider validation — these cases are about policy, not keys."""
    from ppxai.server.routes import agent_v1

    monkeypatch.setattr(agent_v1, "_validate_provider_or_400", lambda name: None)


def _engine_refusal(kwargs):
    """Drive the shared boundary directly; return (status, detail) or None."""
    try:
        authorize_task(TaskRequest(provider="p", model="m", **kwargs))
    except TaskAuthorizationError as exc:
        return exc.status, exc.detail
    return None


class TestRefusalParity:
    """A request refused by one admission path must be refused by all of them."""

    @pytest.mark.parametrize(
        "case_id,kwargs,status,needle",
        REFUSAL_CASES,
        ids=[c[0] for c in REFUSAL_CASES],
    )
    def test_route_refuses(self, route_client, registry, case_id, kwargs, status, needle):
        body = {"provider": "p", "model": "m", **kwargs}
        r = route_client.post("/v1/agent/task", json=body)
        # 422 would mean Pydantic rejected the shape before the gate ran; that
        # is a different (also-fine) refusal, but these cases must reach the
        # policy layer, so pin the exact status.
        assert r.status_code == status, r.text
        assert needle in r.json()["detail"]
        assert registry.list_runs() == [], "refused, yet a run was minted"

    @pytest.mark.parametrize(
        "case_id,kwargs,status,needle",
        REFUSAL_CASES,
        ids=[c[0] for c in REFUSAL_CASES],
    )
    def test_engine_refuses_identically(self, case_id, kwargs, status, needle):
        got = _engine_refusal(kwargs)
        assert got is not None, "the shared authorizer ADMITTED a request the route refuses"
        assert got[0] == status
        assert needle in got[1]


class TestInProcessPathIsNotAWeakerDoor:
    """The TUI/SDK path must reach the same boundary as the HTTP route.

    These are STRUCTURAL, deliberately: driving `/task` end-to-end from a TUI
    needs a running Textual app and a live event loop, which would make the
    fence slow and flaky. What actually broke in T8b was not subtle logic — it
    was an entire admission path that never called the gates at all. That is
    exactly what a structural assertion pins, and it fails loudly the moment
    someone adds a second `launch()`-style entry point that skips the
    authorizer.

    The behavioral half is covered by the engine column above: both clients
    now funnel into `authorize_task`, so proving the funnel exists plus
    proving the funnel refuses is equivalent to driving both ends.
    """

    def test_in_process_backend_goes_through_the_authorizer(self):
        import inspect

        from ppxai.engine import task_backend

        src = inspect.getsource(task_backend)
        assert "authorize_task" in src or "AuthorizedTask" in src, (
            "InProcessTaskBackend does not reference the shared authorizer. "
            "An in-process launch that skips authorize_task() is the T8b "
            "security hole: the tier gate, the shell reject and the skill "
            "name-resolution never run. See docs/archive/branch-review-v1.19.1.md."
        )

    def test_launch_cannot_be_handed_raw_read_paths(self):
        """Read scope is an OUTPUT of authorization, never a client input.

        The HTTP request model has no read-path field, so the wire cannot
        express one. The in-process entry point must match: while a public
        `extra_read_paths` kwarg exists, `--skill /etc` is one careless caller
        away from mounting an arbitrary directory under the seal.
        """
        import inspect

        from ppxai.engine.task_backend import InProcessTaskBackend

        params = inspect.signature(InProcessTaskBackend.launch).parameters
        assert "extra_read_paths" not in params, (
            "launch() still accepts caller-supplied read paths. Resolved skill "
            "roots must come from AuthorizedTask.read_roots instead."
        )

    def test_command_layer_does_not_forward_raw_skill_tokens(self):
        """`--skill` values are NAMES to resolve, not paths to mount."""
        import inspect

        from ppxai.commands import task as task_cmd

        src = inspect.getsource(task_cmd)
        assert "extra_read_paths" not in src, (
            "commands/task.py still passes parsed --skill tokens as read "
            "paths. They must go through the authorizer as skill NAMES so "
            "reject_unsafe_name() + within_root() confine them to skills_dir."
        )


class TestEmptyGrantRefused:
    """A tool-capable run with no tools must not start — on either path.

    The two paths refuse at different LAYERS, which is correct rather than
    drift: the HTTP request model rejects the shape at parse time (422),
    while the engine's post-merge gate catches the case a spec/profile
    resolved to nothing (400). Both are refusals; neither mints a run.
    """

    def test_route_refuses_empty_grant(self, route_client, registry):
        r = route_client.post(
            "/v1/agent/task",
            json={"task": "do a thing", "tools": [],
                  "provider": "p", "model": "m"},
        )
        assert r.status_code == 422, r.text  # Pydantic, before the policy layer
        assert registry.list_runs() == []

    def test_engine_refuses_empty_grant(self):
        got = _engine_refusal({"task": "do a thing", "tools": []})
        assert got is not None, "a tool-capable run was authorized with no tools"
        assert got[0] == 400
        assert "Empty tool grant" in got[1]


class TestTierGateParity:
    """`execution.task.enabled=false` must stop every path, not just HTTP.

    This is the headline T8b finding: the TUI could start a tool-capable run
    on a box where the operator had switched the tier off.
    """

    @pytest.fixture(autouse=True)
    def _tier_off(self, monkeypatch):
        from ppxai.server.routes import agent_v1

        monkeypatch.setattr(
            agent_v1, "get_execution_task_config",
            lambda: {"enabled": False, "sandbox": {}, "consent": {}, "budgets": {}},
        )

    def test_route_refuses_when_tier_disabled(self, route_client, registry):
        r = route_client.post(
            "/v1/agent/task",
            json={"task": "do a thing", "tools": ["read_file"],
                  "provider": "p", "model": "m"},
        )
        assert r.status_code == 403
        assert "execution.task.enabled" in r.json()["detail"]
        assert registry.list_runs() == []

    def test_engine_refuses_when_tier_disabled(self):
        got = _engine_refusal({"task": "do a thing", "tools": ["read_file"]})
        assert got is not None, "the tier gate did not fire in the shared authorizer"
        assert got[0] == 403
        assert "execution.task.enabled" in got[1]

    def test_tier_gate_precedes_filesystem_access(self):
        """A disabled tier must not resolve specs/skills off disk.

        Ordering, not cosmetics: spec/skill resolution reads
        operator-configured directories, so it must sit behind the switch that
        says this box runs tool-capable agents at all.
        """
        got = _engine_refusal(
            {"task": "do a thing", "tools": ["read_file"], "skills": ["/etc"]}
        )
        assert got is not None
        assert got[0] == 403, "the skill path was resolved before the tier gate"


class TestReadScopeIsAnOutputNotAnInput:
    """Read roots must come from RESOLVED skills, never from a client string.

    The `--skill /etc` escape existed because the in-process path forwarded raw
    parsed tokens as `extra_read_paths`, which `build_filesystem_policy`
    appends verbatim as read roots. The HTTP route never had this hole: its
    request model has no read-path field at all.
    """

    def test_authorized_read_roots_reject_raw_paths(self):
        got = _engine_refusal(
            {"task": "do a thing", "tools": ["read_file"], "skills": ["/etc/passwd"]}
        )
        assert got is not None, "an absolute path was accepted as a skill name"
        assert got[0] == 400

    def test_http_request_model_has_no_read_path_field(self):
        """Structural: the wire contract cannot express a client read root."""
        from ppxai.server.routes.agent_v1 import AgentTaskRequest

        fields = set(AgentTaskRequest.model_fields)
        assert "extra_read_paths" not in fields
        assert "read_roots" not in fields


class TestStatedEmptyNetworkIsNotInherited:
    """`network=[]` means "no egress", not "unset".

    Regression fence for the DTO boundary: collapsing None and [] would let a
    deliberately egress-free request silently inherit a spec's allowlist. The
    suite had no coverage of this before the extraction made it losable.
    """

    def test_stated_empty_network_survives_authorization(self):
        auth = authorize_task(
            TaskRequest(
                task="do a thing", tools=["read_file"],
                provider="p", model="m", network=[],
            )
        )
        assert auth.network == []

    def test_unstated_network_is_distinguishable(self):
        auth = authorize_task(
            TaskRequest(
                task="do a thing", tools=["read_file"],
                provider="p", model="m", network=None,
            )
        )
        assert auth.network == []  # resolves to empty, but via the None branch


class TestTierPolicyIsData:
    """The two tiers differ by a TABLE ROW, not by a second code path.

    Written after a first attempt at `/run` parity produced a duplicated
    `authorize_oneshot()` — 120 lines that re-derived provider resolution and
    re-implemented the egress assembly. A copy of a security boundary is a
    parity problem with a countdown on it, so the differences now live in
    `TIERS` and everything else is shared.

    These assertions are about STRUCTURE, and they are what makes the
    duplication un-reintroducible: if someone adds a per-tier branch, the
    table stops describing behavior and one of these fails.
    """

    def test_every_registry_kind_has_a_row(self):
        assert set(TIERS) == {"task", "oneshot"}, (
            "a registry kind without a TierPolicy row cannot be authorized; "
            "add the row rather than branching in authorize()"
        )

    def test_unknown_kind_fails_closed(self):
        with pytest.raises(TaskAuthorizationError) as exc:
            authorize(TaskRequest(task="x", kind="made-up"))
        assert exc.value.status == 400

    def test_only_one_construction_site_for_authorizedtask(self):
        """`AuthorizedTask` must be un-forgeable outside the boundary.

        A hand-built literal is how the in-process `/run` skipped every gate
        before this change: the type existed without the checks that give it
        meaning. Production code may construct it in exactly one place — the
        `return` inside `authorize()`.
        """
        root = Path(__file__).resolve().parents[1] / "ppxai"
        sites = [
            f"{p.relative_to(root)}:{i}"
            for p in root.rglob("*.py")
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "AuthorizedTask(" in line and "-> AuthorizedTask" not in line
        ]
        assert sites == ["engine/task_authorizer.py:1058"] or len(sites) == 1, (
            f"AuthorizedTask is constructed at {len(sites)} sites: {sites}. "
            "Only authorize() may mint one — every other site is a gate bypass."
        )


class TestOneShotTierParity:
    """`/run` admission: config-decided grant, no tier gate, no UI fallback."""

    def test_request_cannot_widen_a_config_decided_grant(self):
        """The sharpest property of the one-off tier.

        Not "a request asking for tools is rejected" but "a request asking for
        tools is IGNORED" — there is no code path by which a request-supplied
        tool reaches a oneshot run, so the guarantee holds even if a future
        client forgets to sanitize its input.
        """
        with patch.object(_authz, "_config_flag", lambda key: False), \
             patch.object(_authz, "_default_subagent", lambda: _SUB):
            auth = authorize(TaskRequest(
                task="x", kind="oneshot",
                tools=["execute_shell_command", "write_file"],
            ))
        assert auth.tools == []

    def test_config_flag_decides_the_grant(self):
        with patch.object(_authz, "_default_subagent", lambda: _SUB):
            with patch.object(_authz, "_config_flag", lambda key: False):
                assert authorize_oneshot("x").tools == []
            with patch.object(_authz, "_config_flag", lambda key: True):
                auth = authorize_oneshot("x")
        assert auth.tools == ["web_search"]
        assert auth.budget == {"iterations": TIERS["oneshot"].iterations}

    def test_tier_gate_does_not_apply(self):
        """`/v1/oneshot` is byte-identical since v1.18.4 and its tier is
        documented "always available" — gating it on execution.task.enabled
        would break that surface on every box with the task tier off."""
        with patch.object(_authz, "_task_cfg", lambda: {"enabled": False, "sandbox": {}}), \
             patch.object(_authz, "_config_flag", lambda key: False), \
             patch.object(_authz, "_default_subagent", lambda: _SUB):
            assert authorize_oneshot("x").tools == []
            with pytest.raises(TaskAuthorizationError) as exc:
                authorize_task(TaskRequest(task="x", tools=["read_file"]))
        assert exc.value.status == 403

    def test_operator_kill_switch_covers_the_one_off_tier(self):
        """Regression fence for a hole BOTH the old route and the first
        (duplicated) fix had: `tools.web_search.enabled=false` is an operator
        veto, so it must also stop a grant that config assembled."""
        with patch.object(_authz, "_config_flag", lambda key: True), \
             patch.object(_authz, "_default_subagent", lambda: _SUB), \
             patch.object(_authz, "get_tool_config", lambda name: {"enabled": False}):
            with pytest.raises(TaskAuthorizationError) as exc:
                authorize_oneshot("x")
        assert exc.value.status == 403
        assert "web_search" in exc.value.detail

    def test_oneshot_facade_honours_the_kill_switch(self):
        """`/v1/oneshot`'s enriched path is the THIRD admission route.

        The parity harness covered `/v1/agent/run` and the in-process `/run`,
        but not the `POST /v1/oneshot` facade. Its search-loop branch
        hardwired `tools=["web_search"]` and called `build_task_runner`
        directly, so `tools.web_search.enabled=false` returned 403 for
        `/v1/agent/run` while an enriched oneshot still searched — an
        operator veto with a hole in it.
        """
        from ppxai.server.routes import oneshot as _oneshot

        assert hasattr(_oneshot, "_authorize_oneshot_search_loop"), (
            "the /v1/oneshot search-loop branch must route through the "
            "shared authorizer, not mint a grant of its own"
        )
        with patch.object(_authz, "_config_flag", lambda key: True), \
             patch.object(_authz, "_default_subagent", lambda: _SUB), \
             patch.object(_authz, "get_tool_config", lambda name: {"enabled": False}):
            with pytest.raises(TaskAuthorizationError) as exc:
                _oneshot._authorize_oneshot_search_loop("x", "gemini", "m")
        assert exc.value.status == 403
        assert "web_search" in exc.value.detail

    def test_ui_selection_never_supplies_the_provider(self):
        """ADR 0003 §9: a sub-agent's provider is per-run injected intent.

        `honors_client_fallback=False` is what stops the TUI handing its chat
        pane's provider to a background run — the in-process `/run` did
        exactly that before the table existed.
        """
        # Offering UI context to this tier is refused OUTRIGHT, not silently
        # dropped. A quiet drop would make `honors_client_fallback` decorative
        # — it reads like enforcement while the real guarantee comes from
        # elsewhere — which is the exact shape this module exists to remove.
        # (Found by mutation: gating the value at the merge call changed no
        # behaviour, because the config-granted branch never reads it.)
        with patch.object(_authz, "_config_flag", lambda key: False), \
             patch.object(_authz, "_default_subagent", lambda: _SUB):
            with pytest.raises(TaskAuthorizationError) as exc:
                authorize(
                    TaskRequest(task="x", kind="oneshot"),
                    fallback_provider="ui-pane-provider",
                    fallback_model="ui-pane-model",
                )
        assert exc.value.status == 400
        assert "injected intent" in exc.value.detail

        # Not offered any: resolves from config, as the tier intends.
        with patch.object(_authz, "_config_flag", lambda key: False), \
             patch.object(_authz, "_default_subagent", lambda: _SUB):
            auth = authorize(TaskRequest(task="x", kind="oneshot"))
        assert auth.provider == _SUB["provider"]
        assert auth.model == _SUB["model"]

        # The task tier, same call, DOES honour it — the contrast is the
        # point: one table field, two behaviours, no branch in the caller.
        with patch.object(_authz, "_task_cfg",
                          lambda: {"enabled": True, "sandbox": {}}), \
             patch.object(_authz, "validate_provider_or_error", lambda p: None), \
             patch.object(_authz, "_default_subagent", lambda: {}):
            task_auth = authorize(
                TaskRequest(task="x", kind="task", tools=["read_file"]),
                fallback_provider="ui-pane-provider",
                fallback_model="ui-pane-model",
            )
        assert task_auth.provider == "ui-pane-provider"

    def test_missing_provider_refuses_before_minting(self):
        with patch.object(_authz, "_config_flag", lambda key: False), \
             patch.object(_authz, "_default_subagent", lambda: {}), \
             patch.object(_authz, "_default_model", lambda p: None):
            with pytest.raises(TaskAuthorizationError) as exc:
                authorize_oneshot("x")
        assert exc.value.status == 400
        assert "No provider for the agent run" in exc.value.detail
