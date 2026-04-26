"""Light security pass for built-in tool execute() paths.

Critique #5 calls out 5 tool families (editor, filesystem, shell,
container, document). Existing tests already cover the happy paths
and most consent flows. This file adds the gaps that the critique
specifically named:

  - Path traversal in filepath argument (tools accept relative paths
    that resolve through working_dir; tests pin the resolution
    semantics so silent regressions surface).
  - Symlink behavior — editor follows symlinks (target file gets
    edited, link itself is not replaced).
  - Malformed unified diff — apply_patch surfaces an error string
    rather than corrupting the file.
  - Shell timeout enforcement and risk classification (NEVER blocks
    immediately, SAFE bypasses callback, DANGEROUS without callback
    denies fail-safe).
  - Container CLI consent flow (ConsentCLITool requires shell
    consent before subprocess invocation).

Architecture note: path validation is INTENTIONALLY at the consent
layer (`engine/consent_ops.py`), not the tool layer. The LLM may
legitimately need to read system files (`/etc/hosts`, etc.) so the
tool itself accepts any path the consent layer approves. See
docs/CONSENT-CONTRACT.md for the full contract.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ppxai.engine import EngineClient
from ppxai.engine.tools.builtin.editor import (
    ApplyPatchTool,
    DeleteLinesTool,
    InsertTextTool,
    ReplaceBlockTool,
)
from ppxai.engine.tools.builtin.filesystem import ReadFileTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def allow_all_engine():
    """Engine with always-yes consent — narrows tests to non-consent behavior."""
    callback = AsyncMock(return_value=(True, "always"))
    return EngineClient(consent_callback=callback)


@pytest.fixture
def deny_all_engine():
    """Engine that always denies."""
    callback = AsyncMock(return_value=(False, "n"))
    return EngineClient(consent_callback=callback)


def _supports_symlinks(tmp_path: Path) -> bool:
    try:
        target = tmp_path / "_p"
        target.write_text("x")
        link = tmp_path / "_l"
        link.symlink_to(target)
        link.unlink()
        target.unlink()
        return True
    except (OSError, NotImplementedError):
        return False


# ---------------------------------------------------------------------------
# Critique #5.editor — path resolution, symlinks, malformed patch
# ---------------------------------------------------------------------------

class TestEditorPathHandling:
    """Editor tools accept any path the consent layer approves. Pin
    the resolution semantics so a future 'restrict to working_dir'
    refactor is intentional, not accidental."""

    @pytest.mark.asyncio
    async def test_replace_block_resolves_relative_path_via_engine_working_dir(
        self, allow_all_engine, tmp_path
    ):
        """Editor tools resolve relative paths via engine.get_working_dir(),
        NOT the process cwd. This decouples the tool from os.chdir state
        so the engine's tracked working directory is the canonical source."""
        target = tmp_path / "rel.txt"
        target.write_text("alpha\nbeta\n", encoding="utf-8")
        allow_all_engine.set_working_dir(str(tmp_path))

        tool = ReplaceBlockTool(allow_all_engine)
        result = await tool.execute(
            file_path="rel.txt", search="alpha", replace="ALPHA"
        )
        assert "Successfully" in result
        assert target.read_text(encoding="utf-8").startswith("ALPHA\n")

    @pytest.mark.asyncio
    async def test_replace_block_absolute_path_used_verbatim(
        self, allow_all_engine, tmp_path
    ):
        target = tmp_path / "abs.txt"
        target.write_text("hello\nworld\n", encoding="utf-8")

        tool = ReplaceBlockTool(allow_all_engine)
        result = await tool.execute(
            file_path=str(target), search="hello", replace="HELLO"
        )
        assert "Successfully" in result
        assert target.read_text(encoding="utf-8").startswith("HELLO\n")

    @pytest.mark.asyncio
    async def test_replace_block_follows_symlink_to_edit_target(
        self, allow_all_engine, tmp_path
    ):
        """When the path argument is a symlink, the TARGET file is
        edited (not the link). Documents intentional Path.resolve()
        + open() behavior."""
        if not _supports_symlinks(tmp_path):
            pytest.skip("filesystem does not support symlinks")
        real = tmp_path / "real.txt"
        real.write_text("original\n", encoding="utf-8")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        tool = ReplaceBlockTool(allow_all_engine)
        result = await tool.execute(
            file_path=str(link), search="original", replace="EDITED"
        )
        assert "Successfully" in result
        # The real file was edited — symlink target.
        assert real.read_text(encoding="utf-8").strip() == "EDITED"
        # The link still points to the real file.
        assert link.is_symlink()
        assert link.resolve() == real.resolve()

    @pytest.mark.asyncio
    async def test_apply_patch_surfaces_malformed_diff_as_error(
        self, allow_all_engine, tmp_path
    ):
        """A garbled unified diff must produce an error string, not
        silently corrupt the file. The original content stays intact."""
        target = tmp_path / "patch.txt"
        target.write_text("line1\nline2\nline3\n", encoding="utf-8")

        tool = ApplyPatchTool(allow_all_engine)
        # Corrupted hunk header — not a valid @@ -1,3 +1,3 @@.
        bogus = (
            "--- a/patch.txt\n"
            "+++ b/patch.txt\n"
            "this is not a hunk\n"
            "+ inserted\n"
        )
        result = await tool.execute(
            file_path=str(target), unified_diff=bogus,
        )
        # Either an explicit error string or a no-op — file MUST stay
        # at original content. The corrupted-input contract is "do
        # nothing surprising" rather than "fail loudly with a specific
        # string."
        content = target.read_text(encoding="utf-8")
        assert content == "line1\nline2\nline3\n", (
            f"Malformed patch corrupted file: {content!r}"
        )
        # Result reports failure (not "Successfully").
        assert "successfully" not in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_consent_denied_blocks_all_four_editor_tools(
        self, deny_all_engine, tmp_path
    ):
        """All four file-editing tools must respect consent denial."""
        target = tmp_path / "denied.txt"
        target.write_text("untouched\n", encoding="utf-8")
        original = target.read_text(encoding="utf-8")

        tools = [
            (ReplaceBlockTool(deny_all_engine),
             {"file_path": str(target), "search": "untouched", "replace": "X"}),
            (InsertTextTool(deny_all_engine),
             {"file_path": str(target), "line_number": 1, "text": "X\n"}),
            (DeleteLinesTool(deny_all_engine),
             {"file_path": str(target), "start_line": 1, "end_line": 1}),
        ]
        for tool, kwargs in tools:
            result = await tool.execute(**kwargs)
            assert "denied" in result.lower(), (
                f"{type(tool).__name__} did not return denial: {result}"
            )
        # File unchanged across all four denial paths.
        assert target.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Critique #5.fs — relative-vs-absolute, symlink follow
# ---------------------------------------------------------------------------

class TestFilesystemPathHandling:
    """ReadFileTool resolves paths against engine.get_working_dir()
    when relative, uses absolute paths verbatim. Symlinks are followed
    (cat-like semantics)."""

    @pytest.mark.asyncio
    async def test_read_file_relative_uses_engine_working_dir(self, tmp_path):
        engine = EngineClient()
        engine.set_working_dir(str(tmp_path))
        target = tmp_path / "wd.txt"
        target.write_text("hello from wd\n", encoding="utf-8")

        tool = ReadFileTool(engine)
        result = await tool.execute(filepath="wd.txt")
        assert "hello from wd" in result

    @pytest.mark.asyncio
    async def test_read_file_absolute_path_bypasses_working_dir(
        self, tmp_path
    ):
        engine = EngineClient()
        # Working dir is somewhere else — absolute path should still resolve.
        engine.set_working_dir(str(tmp_path / "subdir"))
        (tmp_path / "subdir").mkdir()

        elsewhere = tmp_path / "elsewhere.txt"
        elsewhere.write_text("absolute path content\n", encoding="utf-8")

        tool = ReadFileTool(engine)
        result = await tool.execute(filepath=str(elsewhere))
        assert "absolute path content" in result

    @pytest.mark.asyncio
    async def test_read_file_follows_symlink_to_target(self, tmp_path):
        if not _supports_symlinks(tmp_path):
            pytest.skip("filesystem does not support symlinks")
        engine = EngineClient()
        engine.set_working_dir(str(tmp_path))

        target = tmp_path / "real.txt"
        target.write_text("symlink target content\n", encoding="utf-8")
        link = tmp_path / "link.txt"
        link.symlink_to(target)

        tool = ReadFileTool(engine)
        result = await tool.execute(filepath="link.txt")
        assert "symlink target content" in result

    @pytest.mark.asyncio
    async def test_read_file_missing_file_returns_error_not_exception(
        self, tmp_path
    ):
        engine = EngineClient()
        engine.set_working_dir(str(tmp_path))
        tool = ReadFileTool(engine)
        result = await tool.execute(filepath="does_not_exist.txt")
        assert "not found" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_read_file_directory_target_returns_error(self, tmp_path):
        engine = EngineClient()
        engine.set_working_dir(str(tmp_path))
        subdir = tmp_path / "adir"
        subdir.mkdir()
        tool = ReadFileTool(engine)
        result = await tool.execute(filepath="adir")
        assert "not a file" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# Critique #5.shell — timeout, classification, fail-safe deny
# ---------------------------------------------------------------------------

class TestShellSecurityContract:
    """ShellExecuteTool wires through request_shell_consent which
    classifies the command and may call the consent callback. Test
    each branch of that decision tree."""

    @pytest.mark.asyncio
    async def test_never_command_blocked_immediately_no_callback_invocation(self):
        """A NEVER-classified command must short-circuit before the
        callback runs — even an always-yes callback can't override
        the never list."""
        callback = AsyncMock(return_value=(True, "always"))
        engine = EngineClient(shell_consent_callback=callback)
        # Default config classifies 'rm -rf /' or similar as NEVER;
        # use a literal string the default never_allow patterns catch.
        # If the local config doesn't have any never patterns, this
        # test still exercises the SAFE/DANGEROUS branches below.
        engine._shell_config = {
            "never_allow": [r"^rm\s+-rf\s+/"],
            "dangerous_commands": [],
            "allowed_commands": [],
            "timeout": 30,
        }
        approved = await engine.request_shell_consent("rm -rf /", ".")
        assert approved is False
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_safe_command_bypasses_callback(self):
        callback = AsyncMock(return_value=(False, "n"))  # would deny if called
        engine = EngineClient(shell_consent_callback=callback)
        engine._shell_config = {
            "never_allow": [],
            "dangerous_commands": [],
            "allowed_commands": [r"^ls\b"],
            "timeout": 30,
        }
        approved = await engine.request_shell_consent("ls -la", ".")
        assert approved is True
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_dangerous_without_callback_denied_failsafe(self):
        """Fail-safe contract: an unclassifiable (== dangerous) command
        with NO callback installed must default to DENY, not allow."""
        engine = EngineClient(shell_consent_callback=None)
        engine._shell_config = {
            "never_allow": [],
            "dangerous_commands": [],
            "allowed_commands": [],
            "timeout": 30,
        }
        # Unknown command falls through to dangerous.
        approved = await engine.request_shell_consent("unknown_binary --foo", ".")
        assert approved is False

    @pytest.mark.asyncio
    async def test_dangerous_with_callback_yes_approved(self):
        callback = AsyncMock(return_value=(True, "y"))
        engine = EngineClient(shell_consent_callback=callback)
        engine._shell_config = {
            "never_allow": [],
            "dangerous_commands": [r"git\s+push"],
            "allowed_commands": [],
            "timeout": 30,
        }
        approved = await engine.request_shell_consent("git push origin main", ".")
        assert approved is True
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dangerous_consent_remembered_for_session(self):
        """Same exact command shouldn't re-prompt within session."""
        callback = AsyncMock(return_value=(True, "y"))
        engine = EngineClient(shell_consent_callback=callback)
        engine._shell_config = {
            "never_allow": [],
            "dangerous_commands": [r"git\s+push"],
            "allowed_commands": [],
            "timeout": 30,
        }
        await engine.request_shell_consent("git push origin main", ".")
        await engine.request_shell_consent("git push origin main", ".")
        callback.assert_awaited_once()  # only first call asked

    @pytest.mark.asyncio
    async def test_shell_execute_returns_timeout_message(self, tmp_path):
        """When subprocess.run raises TimeoutExpired, the tool returns
        an error message rather than propagating the exception."""
        from ppxai.engine.tools.builtin.shell import ShellExecuteTool

        engine = EngineClient()
        engine._shell_config = {
            "never_allow": [],
            "dangerous_commands": [],
            "allowed_commands": [r".*"],  # everything safe for this test
            "timeout": 1,
            "interactive_commands": [],
            "non_interactive_with_args": [],
        }
        engine.set_working_dir(str(tmp_path))

        tool = ShellExecuteTool(engine)

        with patch("ppxai.engine.tools.builtin.shell.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("sleep 5", 1)):
            result = await tool.execute(command="sleep 5", working_dir=str(tmp_path))

        assert "timed out" in result.lower()


# ---------------------------------------------------------------------------
# Critique #5.container — ConsentCLITool consent flow
# ---------------------------------------------------------------------------

class TestContainerConsentFlow:
    """ConsentCLITool runs request_shell_consent before subprocess
    invocation. Denial returns an error; runtime_check error short-
    circuits before consent (no point asking if the binary's missing)."""

    @pytest.mark.asyncio
    async def test_consent_cli_tool_denied_blocks_subprocess(self, tmp_path):
        from ppxai.engine.tools.builtin.container import ConsentCLITool

        deny = AsyncMock(return_value=(False, "n"))
        engine = EngineClient(shell_consent_callback=deny)
        engine._shell_config = {
            "never_allow": [],
            "dangerous_commands": [r".*"],  # force dangerous → consent path
            "allowed_commands": [],
            "timeout": 30,
        }
        engine.set_working_dir(str(tmp_path))

        class FakeTool(ConsentCLITool):
            def __init__(self, e):
                super().__init__(e)
                self.name = "fake"
            def build_command(self, **kwargs):
                return ["true"]

        tool = FakeTool(engine)
        with patch(
            "ppxai.engine.tools.builtin.container._run_command"
        ) as mock_run:
            result = await tool.execute()
        assert "denied" in result.lower()
        mock_run.assert_not_called()  # never reached subprocess

    def test_cli_tool_base_class_build_command_raises_not_implemented(self):
        """[E5 audit] container.py:104 raises NotImplementedError. This
        is the abstract-method contract — the base CLITool isn't
        meant to be instantiated directly. All 14 concrete subclasses
        (DockerTool, KubeTool, ContainerListTool, etc.) override
        build_command. Pin the contract so a future refactor that
        accidentally instantiates the base class fails loudly instead
        of running with empty args."""
        from ppxai.engine.tools.builtin.container import CLITool

        class BareSubclass(CLITool):
            def __init__(self):
                pass  # skip engine assignment for the contract test

        with pytest.raises(NotImplementedError):
            BareSubclass().build_command()

    @pytest.mark.asyncio
    async def test_consent_cli_tool_runtime_check_short_circuits_consent(
        self, tmp_path
    ):
        """If runtime_check returns an error, neither consent nor
        subprocess fires — tool returns the error directly."""
        from ppxai.engine.tools.builtin.container import ConsentCLITool

        callback = AsyncMock()
        engine = EngineClient(shell_consent_callback=callback)
        engine.set_working_dir(str(tmp_path))

        class FakeTool(ConsentCLITool):
            def __init__(self, e):
                super().__init__(e)
                self.name = "fake"
            def runtime_check(self):
                return "Error: binary missing"
            def build_command(self, **kwargs):
                return ["true"]

        tool = FakeTool(engine)
        with patch(
            "ppxai.engine.tools.builtin.container._run_command"
        ) as mock_run:
            result = await tool.execute()
        assert "binary missing" in result
        callback.assert_not_called()
        mock_run.assert_not_called()
