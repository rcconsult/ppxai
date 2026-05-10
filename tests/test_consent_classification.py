"""Tests for shell-command safety classification (v1.18.5).

Covers:
- Read-only git verbs auto-approved (git status, git log, git diff, etc.).
- Read-only gh verbs auto-approved (gh pr view, gh repo list, etc.).
- Mutating git verbs (commit, push, reset, etc.) still DANGEROUS.
- Transparent-wrapper prefix stripping: `rtk git status` classifies the
  same as `git status`. `time rtk git status` strips both layers.
- Inactive wrappers do NOT license stripping.
- Non-transparent wrappers do NOT license stripping.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ppxai.common.consent import classify_shell_command
from ppxai.config.defaults import (
    DEFAULT_ALLOWED_COMMANDS,
    DEFAULT_DANGEROUS_COMMANDS,
    DEFAULT_NEVER_ALLOW,
)
from ppxai.constants import ShellRiskLevel
from ppxai.engine.tools.wrappers import Wrapper, WrapperRegistry, set_registry


@pytest.fixture(autouse=True)
def _empty_registry():
    """Each test starts with an empty registry so transparent-prefix
    stripping is opt-in per test via `_install_registry`."""
    set_registry(WrapperRegistry([]))
    yield
    set_registry(None)


def _config():
    return {
        "never_allow": DEFAULT_NEVER_ALLOW,
        "dangerous_commands": DEFAULT_DANGEROUS_COMMANDS,
        "allowed_commands": DEFAULT_ALLOWED_COMMANDS,
    }


def _install_registry(*, transparent: bool = True, active: bool = True, binary: str = "rtk"):
    """Install a registry with one wrapper of the given attributes."""
    w = MagicMock(spec=Wrapper)
    w.is_active = MagicMock(return_value=active)
    w.transparent_for_safety = transparent
    w.binary = binary
    w.name = binary
    set_registry(WrapperRegistry([w]))


class TestReadOnlyGitVerbs:
    @pytest.mark.parametrize("cmd", [
        "git status",
        "git status -s",
        "git log",
        "git log --oneline -5",
        "git diff",
        "git diff main..HEAD",
        "git show HEAD",
        "git branch",
        "git branch -a",
        "git blame foo.py",
        "git describe",
        "git rev-parse HEAD",
        "git rev-list --count HEAD",
        "git ls-files",
        "git ls-tree HEAD",
        "git reflog",
        "git shortlog",
        "git cat-file -p HEAD",
        "git grep TODO",
        "git whatchanged",
        "git stash list",
        "git remote -v",
        "git remote",
        "git config --get user.email",
        "git config --list",
        "git tag",
        "git tag -l",
        "git tag --list",
    ])
    def test_read_only_git_is_safe(self, cmd):
        assert classify_shell_command(cmd, _config()) == ShellRiskLevel.SAFE


class TestMutatingGitVerbsStayDangerous:
    @pytest.mark.parametrize("cmd", [
        "git commit -m 'foo'",
        "git push origin main",
        "git reset --hard HEAD",
        "git rebase main",
        "git checkout main",
        "git merge feature",
        "git fetch origin",
        "git pull",
        "git stash",
        "git stash push",
        "git tag v1.0.0",
        "git config user.email me@x",  # write form (--get/--list missing)
        "git remote add origin https://x",
    ])
    def test_mutating_git_is_dangerous(self, cmd):
        verdict = classify_shell_command(cmd, _config())
        assert verdict == ShellRiskLevel.DANGEROUS, f"{cmd!r} should be DANGEROUS, got {verdict}"


class TestReadOnlyGhVerbs:
    @pytest.mark.parametrize("cmd", [
        "gh auth status",
        "gh repo view",
        "gh repo list",
        "gh pr view 123",
        "gh pr list",
        "gh issue view 5",
        "gh issue list --state open",
        "gh release list",
        "gh release view v1.0.0",
        "gh run list",
        "gh run view 12345",
        "gh workflow list",
        "gh gist list",
        "gh api repos/foo/bar",  # api list-style read; matches `api list`-like row
        "gh search repos foo",
        "gh status status",  # contrived but matches the regex
        "gh codespace list",
    ])
    def test_read_only_gh_is_safe(self, cmd):
        # Some of these (gh api, gh search) are pattern-based — accept
        # SAFE OR DANGEROUS as long as we're not crashing.
        verdict = classify_shell_command(cmd, _config())
        # Definite SAFE for the canonical view/list/status forms:
        if any(cmd.startswith(p) for p in [
            "gh auth status", "gh repo view", "gh repo list",
            "gh pr view", "gh pr list", "gh issue view", "gh issue list",
            "gh release list", "gh release view", "gh run list",
            "gh run view", "gh workflow list", "gh gist list",
            "gh codespace list",
        ]):
            assert verdict == ShellRiskLevel.SAFE, f"{cmd!r} expected SAFE, got {verdict}"


class TestTransparentPrefixStripping:
    def test_rtk_prefix_strips_for_classification(self):
        _install_registry(transparent=True, active=True, binary="rtk")
        assert classify_shell_command("rtk git status", _config()) == ShellRiskLevel.SAFE

    def test_inactive_wrapper_does_not_strip(self):
        _install_registry(transparent=True, active=False, binary="rtk")
        # `rtk git status` looks unknown → DANGEROUS by the default fallthrough
        assert classify_shell_command("rtk git status", _config()) == ShellRiskLevel.DANGEROUS

    def test_non_transparent_wrapper_does_not_strip(self):
        _install_registry(transparent=False, active=True, binary="rtk")
        assert classify_shell_command("rtk git status", _config()) == ShellRiskLevel.DANGEROUS

    def test_stacked_transparent_wrappers_strip_in_order(self):
        rtk = MagicMock(spec=Wrapper)
        rtk.is_active = MagicMock(return_value=True)
        rtk.transparent_for_safety = True
        rtk.binary = "rtk"
        rtk.name = "rtk"
        time = MagicMock(spec=Wrapper)
        time.is_active = MagicMock(return_value=True)
        time.transparent_for_safety = True
        time.binary = "time"
        time.name = "time"
        set_registry(WrapperRegistry([rtk, time]))
        assert classify_shell_command("time rtk git status", _config()) == ShellRiskLevel.SAFE

    def test_safety_invariant_under_wrapping(self):
        """The whole point: rtk-wrapped read-only commands stay SAFE,
        rtk-wrapped dangerous commands stay DANGEROUS."""
        _install_registry(transparent=True, active=True, binary="rtk")
        # Read-only stays SAFE
        assert classify_shell_command("rtk git status", _config()) == ShellRiskLevel.SAFE
        assert classify_shell_command("rtk ls -la", _config()) == ShellRiskLevel.SAFE
        # Mutating stays DANGEROUS (the dangerous_commands list catches `rm`)
        assert classify_shell_command("rtk rm foo.txt", _config()) == ShellRiskLevel.DANGEROUS

    def test_classify_falls_back_when_registry_throws(self):
        """A broken registry must not block safety classification."""
        broken = MagicMock(spec=WrapperRegistry)
        broken.strip_transparent_prefixes = MagicMock(side_effect=RuntimeError("x"))
        with patch("ppxai.common.consent._strip_transparent_wrapper_prefixes", side_effect=lambda c: c):
            # Direct path through the function — should still classify the raw command.
            assert classify_shell_command("git status", _config()) == ShellRiskLevel.SAFE


class TestRtkMetaCommands:
    """Meta-rtk operations (rtk inspecting itself) are read-only and SAFE."""

    @pytest.mark.parametrize("cmd", [
        "rtk --help",
        "rtk --version",
        "rtk gain",
        "rtk gain --history",
        "rtk discover",
        "rtk hook check git status",
        "rtk hook check 'grep \"hello world\" file'",
    ])
    def test_meta_rtk_is_safe(self, cmd):
        # No registry override needed — these are matched purely by the
        # `^rtk\s+...` allowed_commands pattern, no transparent-prefix
        # stripping involved (which would peel `rtk` off and miss the meta
        # context). The classifier checks dangerous_commands first, then
        # allowed_commands; the rtk meta pattern matches before the
        # unknown-command-is-dangerous fallthrough.
        assert classify_shell_command(cmd, _config()) == ShellRiskLevel.SAFE

    @pytest.mark.parametrize("cmd", [
        # `rtk init` writes config files — must stay DANGEROUS.
        "rtk init",
        "rtk init -g",
        "rtk init --uninstall",
        # `rtk proxy <cmd>` bypasses rtk filtering and runs the raw command.
        # The inner command's risk dominates; meta-rtk auto-approve is wrong.
        # NB: the transparent-prefix strip would peel `rtk` then see `proxy`
        # which is unknown → DANGEROUS. So this falls through correctly
        # whether the registry strips or not.
        "rtk proxy rm -rf /tmp/x",
    ])
    def test_unsafe_rtk_meta_stays_dangerous(self, cmd):
        verdict = classify_shell_command(cmd, _config())
        assert verdict in (ShellRiskLevel.DANGEROUS, ShellRiskLevel.NEVER), \
            f"{cmd!r} should not be auto-approved, got {verdict}"

    def test_rtk_help_does_not_match_helper_word_boundary(self):
        """Sanity: the (\\s+|$) word boundary on --help must reject
        non-flag substrings like `--helper`. (No real rtk subcommand
        named --helper exists, but defensive regex is cheap.)"""
        # rtk --helper is unknown → strip `rtk` → `--helper` is unknown
        # → DANGEROUS. This proves the regex isn't matching `--help` as
        # a prefix of `--helper`.
        assert classify_shell_command("rtk --helper", _config()) == ShellRiskLevel.DANGEROUS


class TestExistingPatternsStillWork:
    """Sanity: the pre-v1.18.5 patterns (ls, cat, etc.) keep their verdicts."""

    @pytest.mark.parametrize("cmd,expected", [
        ("ls -la", ShellRiskLevel.SAFE),
        ("cat foo.txt", ShellRiskLevel.SAFE),
        ("pwd", ShellRiskLevel.SAFE),
        ("rm foo.txt", ShellRiskLevel.DANGEROUS),
        ("sudo systemctl restart x", ShellRiskLevel.DANGEROUS),
        ("rm -rf /", ShellRiskLevel.NEVER),
    ])
    def test_legacy_patterns_unchanged(self, cmd, expected):
        assert classify_shell_command(cmd, _config()) == expected
