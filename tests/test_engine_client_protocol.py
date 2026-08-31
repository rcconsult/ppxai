"""Sentinel tests pinning `EngineClientProtocol` against the concrete
`EngineClient` (Item 10, v1.18.2).

These tests prevent regressions where a method removed from
`EngineClient` breaks the commands layer at runtime instead of being
caught by the protocol contract. The Protocol-DI pattern only delivers
its consistency benefit if it's actively enforced — `runtime_checkable`
gives us `isinstance()` semantics, but there's no static-typing gate
in CI today, so a sentinel test is the cheapest enforcement available.

Failure modes these tests catch:
- A method renamed/removed from `EngineClient` without updating either
  the protocol or the calling command.
- A new method added to `EngineClient` that becomes a de-facto command
  dependency without anyone updating the protocol — would silently work
  but defeat the abstraction.
- The commands layer slipping back to importing `EngineClient` directly.
"""

from __future__ import annotations

import pytest

from ppxai.engine.types import EngineClientProtocol


class TestProtocolStructure:
    """Pin the protocol's surface so additions are intentional."""

    def test_runtime_checkable(self):
        """isinstance() must work — commands rely on this for adapter wrapping."""
        # This will raise TypeError if the protocol forgot @runtime_checkable.
        # Just calling isinstance against an unrelated object is enough; we
        # don't care about the result, only that it doesn't TypeError.
        try:
            isinstance(object(), EngineClientProtocol)
        except TypeError as e:
            pytest.fail(f"EngineClientProtocol must be @runtime_checkable: {e}")

    def test_minimum_surface_present(self):
        """Catches accidental drops from the protocol.

        The names below are the known commands→engine surface as of
        Item 10. If any disappear, at least one command path breaks.
        """
        required_attrs = {
            # Properties (read-mostly).
            "session", "state", "model", "tools_enabled", "agent_mode",
            "tool_manager", "last_model_switch_reset", "context_injector",
            # Provider/model.
            "set_model", "set_provider",
            # Working dir.
            "get_working_dir", "set_working_dir",
            # Tools/agent.
            "enable_tools", "disable_tools",
            "enable_agent_mode", "disable_agent_mode",
            "get_agent_config", "get_tools_status", "set_tool_config",
            # Bootstrap/context.
            "get_bootstrap_status", "get_active_hints",
            "reload_bootstrap_context", "reload_config",
            "clear_injected_contexts", "get_context_info",
            "get_context_attachments", "remove_context_attachment",
            # Checkpoints.
            "create_checkpoint", "undo_last_checkpoint",
            "get_checkpoint_status", "list_checkpoints",
            "set_checkpoint_backend", "clear_file_checkpoints",
            # Conversation.
            "chat", "restore_session",
        }
        protocol_attrs = {
            name for name in dir(EngineClientProtocol)
            if not name.startswith("_")
        }
        missing = required_attrs - protocol_attrs
        assert not missing, (
            f"EngineClientProtocol is missing surface that commands "
            f"depend on: {sorted(missing)}. Either add them back or "
            f"audit the commands that use them."
        )


class TestEngineClientSatisfiesProtocol:
    """The whole point of the protocol: EngineClient must satisfy it
    structurally without inheriting from it. If this drifts, every
    `ServerCommandContext(engine)` instantiation type-lies.
    """

    def test_engineclient_satisfies_protocol_at_runtime(self):
        """A real EngineClient instance passes `isinstance()` against the
        protocol. This is the strict contract the route layer relies on
        when handing the engine to `ServerCommandContext`.
        """
        from ppxai.engine.client import EngineClient
        # EngineClient.__init__ takes no required args — it pulls config
        # from environment. Use minimal construction.
        engine = EngineClient()
        assert isinstance(engine, EngineClientProtocol), (
            "EngineClient no longer satisfies EngineClientProtocol. "
            "A method was likely renamed/removed without updating the "
            "protocol. Run the test_minimum_surface_present diff to find "
            "which member is missing."
        )

    def test_engineclient_does_not_inherit_protocol(self):
        """Structural satisfaction, not inheritance — the whole point
        of the Protocol-DI pattern. If someone adds explicit
        inheritance, they're misunderstanding the abstraction."""
        from ppxai.engine.client import EngineClient
        assert EngineClientProtocol not in EngineClient.__mro__, (
            "EngineClient should satisfy EngineClientProtocol "
            "structurally, not inherit from it."
        )


class TestCommandsLayerImportHygiene:
    """The commands layer must not slip back to importing the concrete
    EngineClient class — the whole consistency win of Item 10 is
    nominal decoupling at the import boundary.
    """

    def test_protocol_module_does_not_import_concrete_client(self):
        """`commands/protocol.py` must reference only the Protocol."""
        import ppxai.commands.protocol as mod
        source_text = open(mod.__file__, encoding="utf-8").read()
        assert "from ..engine.client import EngineClient" not in source_text
        assert "from ppxai.engine.client import EngineClient" not in source_text

    def test_context_module_does_not_import_concrete_client(self):
        """`commands/context.py` must reference only the Protocol."""
        import ppxai.commands.context as mod
        source_text = open(mod.__file__, encoding="utf-8").read()
        assert "from ..engine.client import EngineClient" not in source_text
        assert "from ppxai.engine.client import EngineClient" not in source_text
