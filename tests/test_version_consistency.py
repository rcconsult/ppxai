"""Sentinel test: no version-string drift between releases.

Pre-2026-05 the release script patched 13 places. Most have since been
collapsed: runtime banners read from ``ppxai.__version__``, markdown
docs link to ``releases/latest`` instead of carrying a literal string,
READMEs use a ``<version>`` placeholder. This test pins the result.

Positive direction: every surviving location of the version string MUST
match ``pyproject.toml``.

Negative direction: every retired location MUST NOT contain a hardcoded
``vX.Y.Z`` / ``X.Y.Z`` pattern that the release script would once have
patched. This catches the failure mode of a contributor adding a new
"Current Version: v1.x.y" line in a doc, which would silently re-
introduce a drift point.

The sentinel runs in CI on every commit, so drift becomes a build
failure on the PR that introduced it — not a "we noticed the wrong
version is published" surprise during release. ``scripts/validate-release.py``
remains as a pre-tag fail-safe.
"""

import json
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _pyproject_version() -> str:
    """Read the canonical version from pyproject.toml."""
    content = _read("pyproject.toml")
    match = re.search(r'^version\s*=\s*"([\d.]+)"', content, re.MULTILINE)
    assert match, "pyproject.toml has no `version = \"X.Y.Z\"` line"
    return match.group(1)


# ---------------------------------------------------------------------------
# Positive: every surviving SoT must match pyproject.toml
# ---------------------------------------------------------------------------


class TestVersionsAgree:
    """Files that legitimately carry a literal version string must match
    pyproject.toml. Drift here breaks `pip install`, npm install, the
    runtime banner, or shields.io badges — all user-visible failures."""

    def test_pyproject_is_canonical(self):
        # Sanity: the SoT itself parses.
        assert re.fullmatch(r"\d+\.\d+\.\d+", _pyproject_version())

    def test_python_runtime_version_matches(self):
        """`ppxai/version.py::__version__` is the Python runtime SoT.
        `ppxai/__init__.py` re-exports it."""
        v = _pyproject_version()
        version_py = _read("ppxai/version.py")
        match = re.search(r'^__version__\s*=\s*"([\d.]+)"', version_py, re.MULTILINE)
        assert match, "ppxai/version.py has no `__version__` line"
        assert match.group(1) == v, f"ppxai/version.py says {match.group(1)}, pyproject.toml says {v}"

    def test_npm_package_version_matches(self):
        v = _pyproject_version()
        pkg = json.loads(_read("vscode-extension/package.json"))
        assert pkg["version"] == v

    def test_npm_package_lock_version_matches(self):
        v = _pyproject_version()
        lock = json.loads(_read("vscode-extension/package-lock.json"))
        assert lock["version"] == v
        # npm v7+ also stores the version in `packages[""]`.
        if "packages" in lock and "" in lock["packages"]:
            assert lock["packages"][""]["version"] == v

    def test_readme_version_badge_matches(self):
        v = _pyproject_version()
        readme = _read("README.md")
        # Pattern: img.shields.io/badge/version-X.Y.Z-blue
        match = re.search(r"badge/version-([\d.]+)-blue", readme)
        if match is None:
            pytest.skip("README.md does not currently carry a version badge")
        assert match.group(1) == v, f"README.md badge says {match.group(1)}, pyproject says {v}"


# ---------------------------------------------------------------------------
# Negative: retired locations must NOT carry a hardcoded version
# ---------------------------------------------------------------------------


class TestRetiredLocationsStayClean:
    """These files used to be patched on every release. They were
    consolidated to derive from a single source. If a contributor adds a
    hardcoded ``v1.x.y`` here, the next release will silently ship the
    wrong string — the sentinel makes that a CI failure on the
    contributing PR instead."""

    def test_init_re_exports_does_not_hardcode(self):
        """ppxai/__init__.py must not declare its own __version__ — it
        must `from .version import __version__`."""
        content = _read("ppxai/__init__.py")
        # Allowed: `from .version import __version__`
        # Disallowed: `__version__ = "x.y.z"`
        assert not re.search(
            r'^__version__\s*=\s*"[\d.]+"', content, re.MULTILINE
        ), "ppxai/__init__.py hardcodes __version__; it should re-export from .version"

    def test_event_handler_has_no_version_banner(self):
        content = _read("ppxai/rich/event_handler.py")
        assert not re.search(
            r"^Version:\s+v[\d.]+", content, re.MULTILINE
        ), "event_handler.py reintroduced a hardcoded `Version: vX.Y.Z` docstring line"

    def test_logger_has_no_version_banner(self):
        content = _read("ppxai/common/logger.py")
        assert not re.search(
            r"^Version:\s+v[\d.]+", content, re.MULTILINE
        ), "logger.py reintroduced a hardcoded `Version: vX.Y.Z` docstring line"

    @pytest.mark.parametrize(
        "filepath",
        [
            "CLAUDE.md",
            "AGENTS.md",
            "docs/README.md",
        ],
    )
    def test_markdown_no_current_version_header(self, filepath):
        """The "Current Version: vX.Y.Z" pattern in these docs was
        retired in favour of a link to releases/latest. A new occurrence
        would re-introduce a drift point."""
        content = _read(filepath)
        # Match all common variants:
        # - **Current Version:** v1.2.3
        # - **Current Version**: v1.2.3
        # - ### Current Version: v1.2.3
        match = re.search(
            r"\bCurrent\s+Version[:\s*]*v[\d.]+",
            content,
        )
        assert match is None, (
            f"{filepath} reintroduced a hardcoded `Current Version: vX.Y.Z` "
            f"pattern at: {match.group(0) if match else '?'!r}. "
            f"Replace with a link to https://github.com/rcconsult/ppxai/releases/latest."
        )

    def test_roadmap_no_quoted_current_version_header(self):
        """ROADMAP's `> **Current Version**: vX.Y.Z (Month YYYY)` was
        retired. Don't reintroduce."""
        content = _read("ROADMAP.md")
        assert not re.search(
            r"^>\s+\*\*Current\s+Version\*\*:\s+v[\d.]+", content, re.MULTILINE
        ), "ROADMAP.md reintroduced a hardcoded current-version block"

    @pytest.mark.parametrize(
        "filepath",
        [
            "README.md",
            "vscode-extension/README.md",
        ],
    )
    def test_readmes_use_version_placeholder_not_literal(self, filepath):
        """READMEs reference the VSIX as `ppxai-<version>.vsix`. A
        literal `ppxai-1.2.3.vsix` would drift between releases."""
        content = _read(filepath)
        # Look for hardcoded ppxai-<digits>.vsix
        match = re.search(r"ppxai-(\d+\.\d+\.\d+)\.vsix", content)
        assert match is None, (
            f"{filepath} reintroduced a literal `ppxai-{match.group(1)}.vsix` "
            f"reference. Use `ppxai-<version>.vsix` placeholder instead."
        ) if match else None
