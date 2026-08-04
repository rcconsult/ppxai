"""Tests for the /reload command.

``CommandFactory.reload_user_commands()`` shipped with the custom-command
feature but had no caller anywhere in the codebase, which left
``~/.ppxai/commands/*.py`` unreachable from every client -- the feature was
documented but not invocable. ``/reload`` is that caller.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import ResultStatus
import ppxai.commands.utility  # noqa: F401  -- triggers registration


class _Ctx:
    """Minimal CommandContext stand-in; /reload is process-global."""
    engine_client = None


class TestReloadCommandRegistration:
    def test_reload_is_registered(self):
        spec = CommandFactory.get("reload")
        assert spec is not None, "/reload is not registered"
        assert spec.category == "utility"
        assert spec.usage == "/reload"

    def test_reload_appears_in_command_listing(self):
        assert "reload" in CommandFactory.list_all()


class TestReloadCommandBehavior:
    def test_reports_module_count_on_success(self):
        spec = CommandFactory.get("reload")
        with patch.object(CommandFactory, "reload_user_commands", return_value=3), \
             patch.object(Path, "exists", return_value=True):
            result = spec.handler(_Ctx(), "")
        assert result.status == ResultStatus.SUCCESS
        assert "3 modules" in result.message
        assert result.details["modules_loaded"] == 3

    def test_missing_directory_is_informational_not_an_error(self):
        """A user who never created ~/.ppxai/commands/ should get guidance,
        not a scary error."""
        spec = CommandFactory.get("reload")
        with patch.object(CommandFactory, "reload_user_commands", return_value=0), \
             patch.object(Path, "exists", return_value=False):
            result = spec.handler(_Ctx(), "")
        assert result.status == ResultStatus.INFO
        assert result.details["directory_exists"] is False

    def test_loader_failure_surfaces_as_error(self):
        spec = CommandFactory.get("reload")
        with patch.object(
            CommandFactory, "reload_user_commands", side_effect=RuntimeError("boom")
        ):
            result = spec.handler(_Ctx(), "")
        assert result.status == ResultStatus.ERROR
        assert "boom" in result.message

    def test_arguments_are_ignored(self):
        """/reload takes no args; passing some must not change behavior."""
        spec = CommandFactory.get("reload")
        with patch.object(CommandFactory, "reload_user_commands", return_value=1), \
             patch.object(Path, "exists", return_value=True):
            bare = spec.handler(_Ctx(), "")
            noisy = spec.handler(_Ctx(), "some junk")
        assert bare.status == noisy.status
        assert bare.message == noisy.message


class TestReloadUserCommandsStaysWired:
    """Regression fence: the loader must keep having a caller."""

    def test_reload_user_commands_has_a_production_caller(self):
        root = Path(__file__).parent.parent / "ppxai"
        callers = [
            p.relative_to(root).as_posix()
            for p in root.rglob("*.py")
            if "reload_user_commands()" in p.read_text(encoding="utf-8", errors="ignore")
            and p.name != "factory.py"
        ]
        assert callers, (
            "CommandFactory.reload_user_commands() has no caller again — "
            "custom commands in ~/.ppxai/commands/ are unreachable."
        )
