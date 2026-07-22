"""Unresolved-grant detection on ScopedToolManager (v1.19.1 Item 50).

A `/task` grant naming a tool that does not exist used to be accepted: the run
was created, started, burned an LLM call, and the model was silently offered
fewer tools than the caller believed it granted. Observed live 2026-07-22 —
`--tools "weather, web_search"` ran happily although the tool is `get_weather`.

The check lives on `ScopedToolManager` because that object already holds BOTH
halves of the question: the grant, and the base manager with every tool
actually registered for the run. That placement matters — editor/shell/
container/display tools register only when an engine is present, so a registry
rebuilt without one reports a misleading subset and would falsely reject valid
names (`apply_patch` was rejected by exactly that mistake during development).
"""

from __future__ import annotations

import pytest

from ppxai.engine.agent_scoped_tools import ScopedToolManager
from ppxai.engine.client import EngineClient
from ppxai.engine.tools.builtin import register_all_builtin_tools


@pytest.fixture
def base_manager():
    """A FULLY registered tool manager (engine present → all tools)."""
    engine = EngineClient()
    register_all_builtin_tools(engine.tool_manager, provider="gemini", engine=engine)
    return engine.tool_manager


class TestUnresolvedGrant:
    def test_unknown_tool_is_reported(self, base_manager):
        mgr = ScopedToolManager(base_manager, ["weather", "web_search"])
        assert mgr.unresolved_grant() == ["weather"]

    def test_valid_grant_is_clean(self, base_manager):
        mgr = ScopedToolManager(base_manager, ["get_weather", "web_search", "read_file"])
        assert mgr.unresolved_grant() == []
        assert mgr.unresolved_grant_message() is None

    def test_engine_gated_tools_are_not_falsely_rejected(self, base_manager):
        """Regression: editor/container/display tools register only with an
        engine. A validator built on an engine-less registry rejected these."""
        mgr = ScopedToolManager(
            base_manager,
            ["apply_patch", "write_file", "replace_block", "display_file"],
        )
        assert mgr.unresolved_grant() == []

    def test_message_suggests_the_near_miss(self, base_manager):
        mgr = ScopedToolManager(base_manager, ["weather"])
        msg = mgr.unresolved_grant_message()
        assert "weather" in msg
        assert "get_weather" in msg  # substring fallback catches this one

    def test_message_handles_a_name_with_no_near_miss(self, base_manager):
        mgr = ScopedToolManager(base_manager, ["zzz_not_a_tool"])
        msg = mgr.unresolved_grant_message()
        assert "zzz_not_a_tool" in msg

    def test_multiple_unknowns_are_sorted_and_deduped(self, base_manager):
        mgr = ScopedToolManager(base_manager, ["zeta_nope", "alpha_nope", "zeta_nope"])
        assert mgr.unresolved_grant() == ["alpha_nope", "zeta_nope"]

    def test_empty_grant_has_nothing_unresolved(self, base_manager):
        assert ScopedToolManager(base_manager, []).unresolved_grant() == []


class TestGrantEnforcementStillWorks:
    """The new method must not disturb the AC-1 allowlist behaviour."""

    def test_offered_set_is_still_filtered_to_the_grant(self, base_manager):
        mgr = ScopedToolManager(base_manager, ["read_file"])
        assert {t.name for t in mgr.get_available_tools()} == {"read_file"}

    def test_off_grant_lookup_still_denied(self, base_manager):
        mgr = ScopedToolManager(base_manager, ["read_file"])
        assert mgr.get_tool("write_file") is None
        assert mgr.get_tool("read_file") is not None
