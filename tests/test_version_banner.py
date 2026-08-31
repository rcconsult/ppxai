"""Tests for ppxai/version.py runtime-info helpers.

These pin the contract that every running ppxai process can produce
a one-line banner with version + git commit + source mtime, and that
the same banner is written to the debug log header. Critical for
correlating runtime behavior with code state — particularly under
editable installs where a stale Python process can keep running old
code while the on-disk source has moved on.
"""

from __future__ import annotations

import re
from unittest.mock import patch

from ppxai.version import (
    __version__,
    format_version_banner,
    get_runtime_version_info,
)


class TestRuntimeVersionInfo:
    def test_returns_all_required_keys(self):
        info = get_runtime_version_info()
        assert set(info.keys()) >= {
            "version", "commit", "source_mtime", "python", "platform"
        }

    def test_version_field_matches_dunder_version(self):
        info = get_runtime_version_info()
        assert info["version"] == __version__

    def test_python_field_is_x_y_z(self):
        info = get_runtime_version_info()
        # Format: "3.11.11" — three integers separated by dots.
        assert re.match(r"^\d+\.\d+\.\d+$", info["python"]), info["python"]

    def test_platform_field_combines_system_and_machine(self):
        info = get_runtime_version_info()
        # darwin-x86_64, linux-aarch64, windows-amd64, etc.
        assert "-" in info["platform"]

    def test_commit_field_is_short_hash_or_na(self):
        info = get_runtime_version_info()
        # Short git hash (7-12 chars hex) or "n/a" when not in a repo.
        assert info["commit"] == "n/a" or re.match(
            r"^[0-9a-f]{7,12}$", info["commit"]
        ), info["commit"]

    def test_source_mtime_is_datetime_string_or_na(self):
        info = get_runtime_version_info()
        # YYYY-MM-DD HH:MM:SS or "n/a".
        assert info["source_mtime"] == "n/a" or re.match(
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", info["source_mtime"]
        ), info["source_mtime"]

    def test_all_values_are_strings(self):
        """Banner formatters use string interpolation. Non-string
        values would crash the banner generation."""
        info = get_runtime_version_info()
        for key, value in info.items():
            assert isinstance(value, str), f"{key}={value!r} is not a string"


class TestFormatVersionBanner:
    def test_contains_version(self):
        banner = format_version_banner()
        assert f"v{__version__}" in banner

    def test_contains_commit_label(self):
        banner = format_version_banner()
        assert "commit " in banner

    def test_contains_source_label(self):
        banner = format_version_banner()
        assert "source " in banner

    def test_contains_python_label(self):
        banner = format_version_banner()
        assert "python " in banner

    def test_starts_with_ppxai(self):
        banner = format_version_banner()
        assert banner.startswith("ppxai v")

    def test_is_single_line(self):
        banner = format_version_banner()
        assert "\n" not in banner

    def test_under_200_chars(self):
        """Long banners wrap awkwardly in narrow terminals — keep it
        scannable in a single line at typical 80-column widths."""
        banner = format_version_banner()
        assert len(banner) < 200, (
            f"banner too long ({len(banner)} chars): {banner}"
        )


class TestGitCommitFallback:
    def test_returns_na_when_git_unavailable(self):
        from ppxai import version as ver_mod
        # Force the subprocess to raise FileNotFoundError as if `git`
        # binary isn't installed.
        with patch("ppxai.version.subprocess.run",
                   side_effect=FileNotFoundError("git not found")):
            info = ver_mod.get_runtime_version_info()
        assert info["commit"] == "n/a"

    def test_returns_na_when_git_command_fails(self):
        from ppxai import version as ver_mod

        class FakeResult:
            returncode = 128
            stdout = ""

        with patch("ppxai.version.subprocess.run", return_value=FakeResult()):
            info = ver_mod.get_runtime_version_info()
        assert info["commit"] == "n/a"

    def test_returns_na_on_subprocess_timeout(self):
        import subprocess as sp

        from ppxai import version as ver_mod
        with patch("ppxai.version.subprocess.run",
                   side_effect=sp.TimeoutExpired(cmd="git", timeout=2)):
            info = ver_mod.get_runtime_version_info()
        assert info["commit"] == "n/a"


class TestBuildInfoInjection:
    """v1.18.2 Item 8: when scripts/write_build_info.py has generated
    `ppxai/_build_info.py`, the runtime banner reads from it instead of
    falling back to git rev-parse + source-mtime probes.

    PyInstaller binaries lose access to git and the source tree, so
    pre-fix they reported `commit n/a, source n/a`. Build-time
    injection lets shipped binaries display the real commit + build
    time — the diagnostic data the v1.18.2 banner feature was for.
    """

    def test_build_info_takes_precedence_when_present(self):
        """When `_build_info.py` exists, its values win over runtime
        probes — even when git rev-parse would succeed."""
        # Stand up a fake _build_info module and inject it.
        import sys
        import types

        from ppxai import version as ver_mod

        fake = types.ModuleType("ppxai._build_info")
        fake.BUILD_COMMIT = "deadbee"
        fake.BUILD_MTIME = "2026-04-28 20:00:00 UTC"
        sys.modules["ppxai._build_info"] = fake
        try:
            info = ver_mod.get_runtime_version_info()
            assert info["commit"] == "deadbee"
            assert info["source_mtime"] == "2026-04-28 20:00:00 UTC"
        finally:
            del sys.modules["ppxai._build_info"]

    def test_falls_back_to_runtime_probes_when_absent(self):
        """No _build_info.py → existing git rev-parse + mtime probes."""
        import sys

        from ppxai import version as ver_mod
        # Defensively remove the module if a previous test left one.
        sys.modules.pop("ppxai._build_info", None)
        # The runtime path returns either real values or "n/a"
        # depending on whether the test runs from a git checkout.
        info = ver_mod.get_runtime_version_info()
        # Either resolved to real values or fell through to "n/a".
        # Both are acceptable; what's NOT acceptable is the build-info
        # leaking into the runtime path.
        assert info["commit"] != "deadbee"

    def test_partial_build_info_falls_through(self):
        """If `_build_info.py` is malformed (missing BUILD_MTIME) the
        runtime path takes over — we don't ship a half-populated banner."""
        import sys
        import types

        from ppxai import version as ver_mod

        fake = types.ModuleType("ppxai._build_info")
        fake.BUILD_COMMIT = "deadbee"
        # Deliberately omit BUILD_MTIME.
        sys.modules["ppxai._build_info"] = fake
        try:
            info = ver_mod.get_runtime_version_info()
            # Must NOT use the partial commit — fall through to runtime.
            assert info["commit"] != "deadbee"
        finally:
            del sys.modules["ppxai._build_info"]


class TestLoggerBannerIntegration:
    def test_logger_writes_version_banner_at_session_start(self, tmp_path, monkeypatch):
        """The Logger.enable() session-start banner must include the
        version line so log readers can correlate with running code state."""
        # Redirect log dir to tmp_path.
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        from ppxai.common.logger import Logger
        # Drop the cached singleton so the new home dir takes effect.
        Logger._instances.clear()
        log = Logger("banner-test")
        log.enable()

        # Force flush.
        for h in log._logger.handlers:
            h.flush()

        log_file = tmp_path / ".ppxai" / "logs" / "banner-test-debug.log"
        assert log_file.exists(), f"log file not created at {log_file}"

        content = log_file.read_text(encoding="utf-8")
        assert f"v{__version__}" in content, (
            f"version banner missing from log file:\n{content[:500]}"
        )
        assert "commit " in content
        assert "python " in content
