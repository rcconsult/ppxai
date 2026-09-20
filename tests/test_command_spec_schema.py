"""CommandSpec client-handling schema tests (ADR 0007 step 1a).

Step 1a is SCHEMA ONLY: `CommandSpec` gains `subcommands`, `clients`,
`client_action`, `client_action_clients` plus validation at registration,
and `CompletionCommandInfo` is widened to carry them. No new commands are
registered by production code in this step and no client behaviour
changes — see docs/plan-adr-0007-completion-service.md §Step 1.

These tests register throwaway probe specs directly against the real,
global `CommandFactory` registry (the same idiom as the `stub_command`
fixture in test_command_envelope.py) rather than `CommandFactory.clear()`,
which would drop every built-in registration for the whole process. Each
probe uses a unique name and is unregistered in teardown so nothing leaks
between tests or into other test modules.
"""

from __future__ import annotations

import pytest

from ppxai.commands.factory import (
    CLIENT_ACTIONS,
    KNOWN_CLIENTS,
    CommandFactory,
    CommandSpec,
)


def _noop_handler(ctx, args):
    return None


@pytest.fixture
def register_spec():
    """Register a CommandSpec and unregister it in teardown.

    Only for specs expected to register successfully. A spec expected to
    fail validation is never added to the registry, so it needs no
    cleanup — assert directly with `pytest.raises` instead of using this
    fixture for those cases.
    """
    registered: list[str] = []

    def _register(spec: CommandSpec) -> CommandSpec:
        CommandFactory.register(spec)
        registered.append(spec.name)
        return spec

    yield _register

    for name in registered:
        CommandFactory.unregister(name)


# ---------------------------------------------------------------------------
# Registration validation
# ---------------------------------------------------------------------------


class TestRegistrationValidation:
    def test_neither_handler_nor_client_action_rejected(self):
        spec = CommandSpec(name="_schema_probe_neither", description="d")
        with pytest.raises(ValueError, match="_schema_probe_neither"):
            CommandFactory.register(spec)

    def test_unknown_client_action_rejected(self):
        spec = CommandSpec(
            name="_schema_probe_unknown_action",
            description="d",
            client_action="not.a.real.action",
        )
        with pytest.raises(ValueError, match="_schema_probe_unknown_action"):
            CommandFactory.register(spec)

    def test_client_action_clients_without_client_action_rejected(self):
        spec = CommandSpec(
            name="_schema_probe_orphan_clients",
            description="d",
            handler=_noop_handler,
            client_action_clients=frozenset({"web"}),
        )
        with pytest.raises(ValueError, match="_schema_probe_orphan_clients"):
            CommandFactory.register(spec)

    def test_unknown_client_in_clients_rejected(self):
        spec = CommandSpec(
            name="_schema_probe_bad_clients",
            description="d",
            handler=_noop_handler,
            clients=frozenset({"web", "carrier-pigeon"}),
        )
        with pytest.raises(ValueError, match="_schema_probe_bad_clients"):
            CommandFactory.register(spec)

    def test_unknown_client_in_client_action_clients_rejected(self):
        spec = CommandSpec(
            name="_schema_probe_bad_action_clients",
            description="d",
            client_action="app.quit",
            client_action_clients=frozenset({"web", "carrier-pigeon"}),
        )
        with pytest.raises(ValueError, match="_schema_probe_bad_action_clients"):
            CommandFactory.register(spec)

    def test_client_action_clients_not_subset_of_clients_rejected(self):
        spec = CommandSpec(
            name="_schema_probe_not_subset",
            description="d",
            client_action="token.manage",
            clients=frozenset({"web"}),
            client_action_clients=frozenset({"web", "vscode"}),
        )
        with pytest.raises(ValueError, match="_schema_probe_not_subset"):
            CommandFactory.register(spec)

    def test_legacy_handler_only_spec_still_registers(self, register_spec):
        spec = register_spec(
            CommandSpec(
                name="_schema_probe_legacy",
                description="legacy, handler only",
                handler=_noop_handler,
            )
        )
        assert CommandFactory.get("_schema_probe_legacy") is spec
        assert spec.is_client_handled is False

    def test_client_action_clients_subset_of_clients_registers(self, register_spec):
        spec = register_spec(
            CommandSpec(
                name="_schema_probe_valid_subset",
                description="d",
                client_action="token.manage",
                clients=frozenset({"web", "vscode"}),
                client_action_clients=frozenset({"web"}),
            )
        )
        assert CommandFactory.get("_schema_probe_valid_subset") is spec

    def test_known_clients_and_client_actions_are_as_measured(self):
        # These are the exact ids measured against callers of
        # engine.completion.complete(client=...) and the owner-approved
        # client_action vocabulary (2026-09-20): the pure client-handled
        # pair from step 1 (`token.manage`, `app.quit`) plus the seven
        # hybrid names declared in step 2.5.
        assert KNOWN_CLIENTS == frozenset({"rich", "textual", "web", "vscode"})
        assert CLIENT_ACTIONS == frozenset({
            "token.manage",
            "app.quit",
            "task.controller",
            "run.controller",
            "auto.loop",
            "coding.stream",
            "coding.convert",
            "preview.panel",
            "help.augment",
        })

    def test_every_client_action_is_used_by_at_least_one_registered_spec(self):
        # No orphan names in CLIENT_ACTIONS: each one is bound to a real
        # spec, not just declared in the vocabulary.
        used = {
            spec.client_action
            for name in CommandFactory.list_all()
            if (spec := CommandFactory.get(name)).client_action is not None
        }
        assert used == CLIENT_ACTIONS

    def test_every_registered_client_action_is_in_the_vocabulary(self):
        # No orphan names on specs either: a spec cannot bind to a
        # client_action the vocabulary does not list (also enforced at
        # registration — this re-asserts it against the live registry).
        for name in CommandFactory.list_all():
            spec = CommandFactory.get(name)
            if spec.client_action is not None:
                assert spec.client_action in CLIENT_ACTIONS, name


# ---------------------------------------------------------------------------
# is_client_handled
# ---------------------------------------------------------------------------


class TestIsClientHandled:
    def test_true_when_no_handler_and_client_action_set(self):
        spec = CommandSpec(
            name="_schema_probe_ich_true",
            description="d",
            client_action="app.quit",
        )
        assert spec.is_client_handled is True

    def test_false_when_handler_and_client_action_both_set(self):
        spec = CommandSpec(
            name="_schema_probe_ich_hybrid",
            description="d",
            handler=_noop_handler,
            client_action="app.quit",
        )
        assert spec.is_client_handled is False

    def test_false_when_only_handler_set(self):
        spec = CommandSpec(
            name="_schema_probe_ich_handler_only",
            description="d",
            handler=_noop_handler,
        )
        assert spec.is_client_handled is False


# ---------------------------------------------------------------------------
# dispatches_in_client truth table
# ---------------------------------------------------------------------------


class TestDispatchesInClient:
    def test_no_client_action_is_always_false(self):
        spec = CommandSpec(name="x", description="d", handler=_noop_handler)
        assert spec.dispatches_in_client("web") is False
        assert spec.dispatches_in_client("rich") is False
        assert spec.dispatches_in_client(None) is False

    def test_client_action_clients_set_membership(self):
        spec = CommandSpec(
            name="x",
            description="d",
            handler=_noop_handler,
            client_action="app.quit",
            client_action_clients=frozenset({"web", "vscode"}),
        )
        assert spec.dispatches_in_client("web") is True
        assert spec.dispatches_in_client("vscode") is True
        assert spec.dispatches_in_client("rich") is False
        assert spec.dispatches_in_client("textual") is False
        # client=None is not a member of an explicit set either.
        assert spec.dispatches_in_client(None) is False

    def test_absent_client_action_clients_with_universal_clients(self):
        # Generic case, no longer the real /quit shape (that command is
        # now gated to {rich, textual}, owner decision 2026-09-20): no
        # `clients` restriction, no `client_action_clients` -> every
        # client that can see the command dispatches to it.
        spec = CommandSpec(
            name="x",
            description="d",
            client_action="app.quit",
        )
        assert spec.dispatches_in_client("web") is True
        assert spec.dispatches_in_client("rich") is True
        assert spec.dispatches_in_client("textual") is True
        assert spec.dispatches_in_client("vscode") is True

    def test_absent_client_action_clients_with_bounded_clients(self):
        # /token shape: clients={web, vscode}, no client_action_clients.
        # (/quit is now bounded the same way, to {rich, textual}.)
        spec = CommandSpec(
            name="x",
            description="d",
            client_action="token.manage",
            clients=frozenset({"web", "vscode"}),
        )
        assert spec.dispatches_in_client("web") is True
        assert spec.dispatches_in_client("vscode") is True
        assert spec.dispatches_in_client("rich") is False
        assert spec.dispatches_in_client("textual") is False

    def test_client_none_with_absent_set_true_only_when_no_handler(self):
        client_handled = CommandSpec(
            name="x",
            description="d",
            client_action="app.quit",
        )
        assert client_handled.dispatches_in_client(None) is True

        hybrid = CommandSpec(
            name="x",
            description="d",
            handler=_noop_handler,
            client_action="app.quit",
        )
        assert hybrid.dispatches_in_client(None) is False


# ---------------------------------------------------------------------------
# iter_completion_specs() carries the widened fields
# ---------------------------------------------------------------------------


class TestIterCompletionSpecsWidening:
    def test_canonical_and_alias_carry_new_fields(self, register_spec):
        spec = register_spec(
            CommandSpec(
                name="_schema_probe_wide",
                description="widened probe",
                handler=_noop_handler,
                usage="/_schema_probe_wide <arg>",
                category="probe",
                aliases=["_schema_probe_wide_alias"],
                subcommands=[("status", "show status"), ("set", "set value")],
                clients=frozenset({"web", "vscode"}),
            )
        )

        infos = {info.name: info for info in CommandFactory.iter_completion_specs()}

        canonical = infos["_schema_probe_wide"]
        assert canonical.is_alias is False
        assert canonical.canonical == "_schema_probe_wide"
        assert canonical.usage == spec.usage
        assert canonical.category == "probe"
        assert canonical.subcommands == [
            ("status", "show status"),
            ("set", "set value"),
        ]
        assert canonical.clients == frozenset({"web", "vscode"})
        assert canonical.client_action is None
        assert canonical.client_action_clients is None
        assert canonical.client_handled is False

        alias = infos["_schema_probe_wide_alias"]
        assert alias.is_alias is True
        assert alias.canonical == "_schema_probe_wide"
        # Alias entries inherit the canonical command's values.
        assert alias.usage == spec.usage
        assert alias.category == "probe"
        assert alias.subcommands == canonical.subcommands
        assert alias.clients == canonical.clients
        assert alias.client_handled is False

    def test_client_handled_flag_reaches_the_snapshot(self, register_spec):
        register_spec(
            CommandSpec(
                name="_schema_probe_ch",
                description="client handled probe",
                client_action="app.quit",
            )
        )
        infos = {info.name: info for info in CommandFactory.iter_completion_specs()}
        assert infos["_schema_probe_ch"].client_handled is True
        assert infos["_schema_probe_ch"].client_action == "app.quit"
