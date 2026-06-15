"""Tests for ScopedToolManager — per-run tool allowlist (ADR 0003 §4, AC-1, Inc 4).

The security core of the tool-capable agent tier: a run may call ONLY the
tools in its grant. Two layers — filtered offered set (model never sees
off-grant tools) and the execute_tool chokepoint (off-grant never reaches
the real tool). The chokepoint test IS the named AC-1 acceptance criterion.
"""

from __future__ import annotations

import pytest

from ppxai.engine.agent_scoped_tools import ScopedToolManager


class _FakeTool:
    def __init__(self, name):
        self.name = name


class _FakeBase:
    """Minimal ToolManager stand-in recording what actually executed."""

    def __init__(self):
        self.executed = []
        self.some_delegated_attr = "from_base"

    def get_available_tools(self):
        return [_FakeTool("read_file"), _FakeTool("write_file"), _FakeTool("shell")]

    def list_tools(self):
        return [{"name": "read_file"}, {"name": "write_file"}, {"name": "shell"}]

    def get_tools_openai_format(self):
        return [
            {"type": "function", "function": {"name": n}}
            for n in ("read_file", "write_file", "shell")
        ]

    def get_tools_prompt(self, working_dir=None):
        return "read_file: ...\nwrite_file: ...\nshell: ..."

    def get_tool(self, name):
        return _FakeTool(name)

    async def execute_tool(self, name, **kwargs):
        self.executed.append(name)
        return f"ran {name}"


@pytest.fixture
def base():
    return _FakeBase()


# ---------------------------------------------------------------------------
# Filtered offered set — model never SEES off-grant tools
# ---------------------------------------------------------------------------


class TestOfferedSetFiltered:
    def test_available_tools_only_granted(self, base):
        s = ScopedToolManager(base, ["read_file"])
        assert [t.name for t in s.get_available_tools()] == ["read_file"]

    def test_list_tools_only_granted(self, base):
        s = ScopedToolManager(base, ["read_file", "shell"])
        assert {t["name"] for t in s.list_tools()} == {"read_file", "shell"}

    def test_openai_format_only_granted(self, base):
        s = ScopedToolManager(base, ["read_file"])
        names = [spec["function"]["name"] for spec in s.get_tools_openai_format()]
        assert names == ["read_file"]

    def test_get_tool_off_grant_returns_none(self, base):
        s = ScopedToolManager(base, ["read_file"])
        assert s.get_tool("read_file").name == "read_file"
        assert s.get_tool("write_file") is None

    def test_prompt_enumerates_only_granted_tools(self, base):
        # AC-1 (codex HIGH): the prompt-based / native-fallback path uses
        # get_tools_prompt to tell the model which tools exist — it MUST
        # enumerate only granted tools, not merely append a note while still
        # listing every tool. Uses a real ToolManager so the base renderer
        # runs against the scoped get_available_tools().
        from ppxai.engine.tools.manager import ToolManager
        from ppxai.engine.tools.base import FunctionTool

        real = ToolManager()
        for n in ("read_file", "write_file", "shell"):
            real.register_tool(FunctionTool(
                name=n, description=f"{n} desc",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=lambda **k: "x",
            ))
        s = ScopedToolManager(real, ["read_file"])
        prompt = s.get_tools_prompt()
        # Assert on the per-tool rendered HEADING ("### <name>"), not bare
        # substrings — the base prompt's shell-wrapper context mentions the
        # word "shell" in unrelated prose, so a substring check is wrong.
        assert "### read_file" in prompt          # granted: enumerated
        assert "### write_file" not in prompt     # off-grant: ABSENT (the fix)
        assert "### shell" not in prompt
        assert "you may ONLY call: read_file" in prompt  # note still reinforces

    def test_prompt_no_off_grant_shell_references(self):
        # AC-1 (codex MEDIUM): with no shell tool granted, the prompt must
        # contain NO execute_shell_command reference — neither the gated
        # instruction line (base renderer) nor the shell-wrapper context
        # block (rtk etc.). Both are off-grant guidance.
        from ppxai.engine.tools.manager import ToolManager
        from ppxai.engine.tools.base import FunctionTool

        real = ToolManager()
        for n in ("read_file", "execute_shell_command"):
            real.register_tool(FunctionTool(
                name=n, description=f"{n} desc",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=lambda **k: "x",
            ))
        # grant WITHOUT shell
        p = ScopedToolManager(real, ["read_file"]).get_tools_prompt()
        assert "execute_shell_command" not in p
        assert "Shell wrapper context" not in p
        assert "### read_file" in p  # but the granted tool is still there

    def test_prompt_keeps_shell_guidance_when_granted(self):
        from ppxai.engine.tools.manager import ToolManager
        from ppxai.engine.tools.base import FunctionTool

        real = ToolManager()
        for n in ("read_file", "execute_shell_command"):
            real.register_tool(FunctionTool(
                name=n, description=f"{n} desc",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=lambda **k: "x",
            ))
        # grant WITH shell -> guidance is relevant, must be present
        p = ScopedToolManager(real, ["read_file", "execute_shell_command"]).get_tools_prompt()
        assert "### execute_shell_command" in p

    def test_empty_grant_yields_empty_prompt(self, base):
        from ppxai.engine.tools.manager import ToolManager
        from ppxai.engine.tools.base import FunctionTool

        real = ToolManager()
        real.register_tool(FunctionTool(
            name="read_file", description="d",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda **k: "x",
        ))
        # no granted tools -> no offered tools -> empty prompt (not a note over
        # a full enumeration)
        assert ScopedToolManager(real, []).get_tools_prompt() == ""


# ---------------------------------------------------------------------------
# execute_tool chokepoint — AC-1: off-grant tool NEVER executes
# ---------------------------------------------------------------------------


class TestExecuteEnforcement:
    @pytest.mark.asyncio
    async def test_granted_tool_executes_via_base(self, base):
        s = ScopedToolManager(base, ["read_file"])
        out = await s.execute_tool("read_file")
        assert out == "ran read_file"
        assert base.executed == ["read_file"]

    @pytest.mark.asyncio
    async def test_ac1_off_grant_tool_never_reaches_base(self, base):
        # THE AC-1 INVARIANT: an off-grant tool call does not execute.
        s = ScopedToolManager(base, ["read_file"])
        out = await s.execute_tool("write_file")
        assert "not permitted" in out          # model-readable denial
        assert base.executed == []             # write_file NEVER ran

    @pytest.mark.asyncio
    async def test_on_deny_callback_fires(self, base):
        denied = []
        s = ScopedToolManager(base, ["read_file"], on_deny=denied.append)
        await s.execute_tool("shell")
        assert denied == ["shell"]
        assert base.executed == []

    @pytest.mark.asyncio
    async def test_empty_grant_denies_everything(self, base):
        s = ScopedToolManager(base, [])
        await s.execute_tool("read_file")
        assert base.executed == []  # nothing permitted


# ---------------------------------------------------------------------------
# Delegation — everything else passes through to the base manager
# ---------------------------------------------------------------------------


class TestDelegation:
    def test_unknown_attr_delegates(self, base):
        s = ScopedToolManager(base, ["read_file"])
        assert s.some_delegated_attr == "from_base"
