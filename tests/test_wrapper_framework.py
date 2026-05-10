"""Tests for the v1.18.5 shell-wrapper framework.

Covers:
- Base class contract: detection caching, is_active gating, failure
  marker heuristic.
- ProbeWrapper / AlwaysWrapper happy/sad/timeout/spawn-error paths.
- Factory: dispatch on `type`, required-field validation, prompt
  block resolution from package / user dir / absolute path.
- Registry: first-match-wins rewrite, prompt-block composition,
  transparent-prefix stripping (single + stacked), thread-safe
  singleton lazy init, set_registry override for tests.
- Config integration: defaults yield rtk; user wrappers merge by
  name; back-compat shim from `use_rtk` / `use_rtk_prompt_hint`.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ppxai.engine.tools.wrappers import (
    AlwaysWrapper,
    ProbeWrapper,
    Wrapper,
    WrapperConfigError,
    WrapperRegistry,
    get_registry,
    make_wrapper,
    set_registry,
)


@pytest.fixture(autouse=True)
def _reset_registry_singleton():
    set_registry(None)
    yield
    set_registry(None)


def _mock_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class TestBaseWrapper:
    def test_detection_returns_true_when_binary_on_path(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["hook", "check"])
            assert w.is_available() is True

    def test_detection_returns_false_when_binary_absent(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value=None):
            w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["hook", "check"])
            assert w.is_available() is False

    def test_detection_caches_after_first_call(self):
        which = MagicMock(return_value="/x/rtk")
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", which):
            w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["hook", "check"])
            for _ in range(5):
                w.is_available()
        assert which.call_count == 1

    def test_is_active_auto_requires_binary_present(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value=None):
            w = ProbeWrapper(name="rtk", binary="rtk", enabled="auto", probe_args=["x"])
            assert w.is_active() is False

    def test_is_active_always_ignores_binary(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value=None):
            w = ProbeWrapper(name="rtk", binary="rtk", enabled="always", probe_args=["x"])
            assert w.is_active() is True

    def test_is_active_never_always_false(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            w = ProbeWrapper(name="rtk", binary="rtk", enabled="never", probe_args=["x"])
            assert w.is_active() is False

    def test_failure_markers_match(self):
        w = ProbeWrapper(
            name="rtk", binary="rtk", probe_args=["x"],
            failure_markers=["rtk: error:", "rtk panicked"],
        )
        assert w.is_wrapper_side_failure("rtk: error: bad arg\n", 1) is True
        assert w.is_wrapper_side_failure("thread main rtk panicked\n", 101) is True
        assert w.is_wrapper_side_failure("fatal: not a git repository\n", 128) is False
        assert w.is_wrapper_side_failure("rtk: error: x\n", 0) is False  # zero exit
        assert w.is_wrapper_side_failure("", 1) is False  # empty stderr

    def test_failure_markers_empty_means_never_attribute(self):
        w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["x"], failure_markers=[])
        assert w.is_wrapper_side_failure("anything", 1) is False

    def test_thread_safe_lazy_detection(self):
        """Two threads racing on is_available() should produce one PATH lookup
        AND identical results."""
        which = MagicMock(return_value="/x/rtk")
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", which):
            w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["x"])
            results = []

            def worker():
                results.append(w.is_available())

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert all(r is True for r in results)
        assert which.call_count == 1


# ---------------------------------------------------------------------------
# ProbeWrapper
# ---------------------------------------------------------------------------


class TestProbeWrapper:
    @pytest.mark.asyncio
    async def test_returns_rewritten_on_exit_zero(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            with patch(
                "ppxai.engine.tools.wrappers.base.asyncio.create_subprocess_exec",
                AsyncMock(return_value=_mock_proc(0, b"rtk git status\n")),
            ):
                w = ProbeWrapper(
                    name="rtk", binary="rtk",
                    probe_args=["hook", "check"],
                    no_rewrite_marker="No rewrite for:",
                )
                assert await w.maybe_rewrite("git status") == "rtk git status"

    @pytest.mark.asyncio
    async def test_returns_none_on_no_rewrite_marker(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            with patch(
                "ppxai.engine.tools.wrappers.base.asyncio.create_subprocess_exec",
                AsyncMock(return_value=_mock_proc(1, b"No rewrite for: npm install\n")),
            ):
                w = ProbeWrapper(
                    name="rtk", binary="rtk",
                    probe_args=["hook", "check"],
                    no_rewrite_marker="No rewrite for:",
                )
                assert await w.maybe_rewrite("npm install") is None

    @pytest.mark.asyncio
    async def test_returns_none_when_binary_absent(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value=None):
            spawn = AsyncMock()
            with patch(
                "ppxai.engine.tools.wrappers.base.asyncio.create_subprocess_exec",
                spawn,
            ):
                w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["x"])
                assert await w.maybe_rewrite("git status") is None
        spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_on_spawn_error(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            with patch(
                "ppxai.engine.tools.wrappers.base.asyncio.create_subprocess_exec",
                AsyncMock(side_effect=FileNotFoundError("disappeared")),
            ):
                w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["x"])
                assert await w.maybe_rewrite("git status") is None

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout_and_kills_process(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.kill = MagicMock()
            with patch(
                "ppxai.engine.tools.wrappers.base.asyncio.create_subprocess_exec",
                AsyncMock(return_value=mock_proc),
            ):
                with patch(
                    "ppxai.engine.tools.wrappers.base.asyncio.wait_for",
                    side_effect=asyncio.TimeoutError,
                ):
                    w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["x"])
                    assert await w.maybe_rewrite("anything") is None
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_full_command_as_single_arg(self):
        """rtk hook check needs the whole command as one positional arg —
        splitting on whitespace would break quoted multi-word arguments."""
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            spawn = AsyncMock(return_value=_mock_proc(0, b'rtk grep "hello world" file\n'))
            with patch(
                "ppxai.engine.tools.wrappers.base.asyncio.create_subprocess_exec",
                spawn,
            ):
                w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["hook", "check"])
                await w.maybe_rewrite('grep "hello world" file')
        args = spawn.await_args.args
        assert args[0] == "/x/rtk"
        assert args[1:3] == ("hook", "check")
        assert args[3] == 'grep "hello world" file'  # single positional

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_stdout(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            with patch(
                "ppxai.engine.tools.wrappers.base.asyncio.create_subprocess_exec",
                AsyncMock(return_value=_mock_proc(0, b"")),
            ):
                w = ProbeWrapper(name="rtk", binary="rtk", probe_args=["x"])
                assert await w.maybe_rewrite("git status") is None


# ---------------------------------------------------------------------------
# AlwaysWrapper
# ---------------------------------------------------------------------------


class TestAlwaysWrapper:
    @pytest.mark.asyncio
    async def test_prepends_prefix_when_binary_present(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/usr/bin/time"):
            w = AlwaysWrapper(name="time", binary="time", prefix="time")
            assert await w.maybe_rewrite("git status") == "time git status"

    @pytest.mark.asyncio
    async def test_returns_none_when_binary_absent(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value=None):
            w = AlwaysWrapper(name="time", binary="time", prefix="time")
            assert await w.maybe_rewrite("git status") is None

    def test_empty_prefix_rejected(self):
        with pytest.raises(ValueError):
            AlwaysWrapper(name="x", binary="x", prefix="   ")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_probe_wrapper_from_config(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/rtk"):
            w = make_wrapper({
                "name": "rtk",
                "type": "probe",
                "binary": "rtk",
                "probe_args": ["hook", "check"],
                "no_rewrite_marker": "No rewrite for:",
                "transparent_for_safety": True,
                "enabled": "auto",
            })
        assert isinstance(w, ProbeWrapper)
        assert w.name == "rtk" and w.binary == "rtk"
        assert w.probe_args == ("hook", "check")
        assert w.no_rewrite_marker == "No rewrite for:"

    def test_always_wrapper_from_config(self):
        with patch("ppxai.engine.tools.wrappers.base.shutil.which", return_value="/x/time"):
            w = make_wrapper({
                "name": "time",
                "type": "always",
                "binary": "time",
                "prefix": "time",
                "transparent_for_safety": True,
            })
        assert isinstance(w, AlwaysWrapper)
        assert w.prefix == "time"

    def test_missing_name_rejected(self):
        with pytest.raises(WrapperConfigError, match="missing required 'name'"):
            make_wrapper({"type": "probe", "binary": "rtk", "probe_args": ["x"]})

    def test_unknown_type_rejected(self):
        with pytest.raises(WrapperConfigError, match="'type' must be one of"):
            make_wrapper({"name": "rtk", "type": "magic", "binary": "rtk"})

    def test_missing_binary_rejected(self):
        with pytest.raises(WrapperConfigError, match="missing required 'binary'"):
            make_wrapper({"name": "rtk", "type": "probe", "probe_args": ["x"]})

    def test_probe_missing_args_rejected(self):
        with pytest.raises(WrapperConfigError, match="missing required 'probe_args'"):
            make_wrapper({"name": "rtk", "type": "probe", "binary": "rtk"})

    def test_always_missing_prefix_rejected(self):
        with pytest.raises(WrapperConfigError, match="missing required 'prefix'"):
            make_wrapper({"name": "time", "type": "always", "binary": "time"})

    def test_loads_prompt_block_from_package(self):
        """RTK.md ships in ppxai/engine/tools/wrappers/. Factory finds it."""
        w = make_wrapper({
            "name": "rtk",
            "type": "probe",
            "binary": "rtk",
            "probe_args": ["hook", "check"],
            "prompt_block_path": "RTK.md",
        })
        assert w.prompt_block is not None
        assert "rtk-compressed" in w.prompt_block

    def test_loads_prompt_block_from_absolute_path(self, tmp_path):
        block = tmp_path / "MYPERF.md"
        block.write_text("custom block content here", encoding="utf-8")
        w = make_wrapper({
            "name": "myperf",
            "type": "probe",
            "binary": "myperf",
            "probe_args": ["dry-run"],
            "prompt_block_path": str(block),
        })
        assert w.prompt_block == "custom block content here"

    def test_missing_prompt_block_logged_not_raised(self):
        w = make_wrapper({
            "name": "rtk",
            "type": "probe",
            "binary": "rtk",
            "probe_args": ["x"],
            "prompt_block_path": "/non/existent/file.md",
        })
        assert w.prompt_block is None  # silently absent

    def test_failure_markers_pass_through(self):
        w = make_wrapper({
            "name": "rtk", "type": "probe", "binary": "rtk", "probe_args": ["x"],
            "failure_markers": ["rtk: error:", "panicked"],
            "retry_raw_on_failure": True,
        })
        assert w.failure_markers == ("rtk: error:", "panicked")
        assert w.retry_raw_on_failure is True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    @pytest.mark.asyncio
    async def test_first_match_wins(self):
        first = MagicMock(spec=Wrapper)
        first.is_active = MagicMock(return_value=True)
        first.maybe_rewrite = AsyncMock(return_value="A wrapped")
        first.binary = "a"
        first.transparent_for_safety = True
        first.prompt_block = None
        first.name = "a"
        second = MagicMock(spec=Wrapper)
        second.is_active = MagicMock(return_value=True)
        second.maybe_rewrite = AsyncMock(return_value="B wrapped")
        second.binary = "b"
        second.transparent_for_safety = True
        second.prompt_block = None
        second.name = "b"

        reg = WrapperRegistry([first, second])
        result = await reg.find_first_rewrite("the cmd")
        assert result == "A wrapped"
        first.maybe_rewrite.assert_awaited_once()
        second.maybe_rewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_through_when_first_returns_none(self):
        first = MagicMock(spec=Wrapper)
        first.is_active = MagicMock(return_value=True)
        first.maybe_rewrite = AsyncMock(return_value=None)
        first.name = "first"
        second = MagicMock(spec=Wrapper)
        second.is_active = MagicMock(return_value=True)
        second.maybe_rewrite = AsyncMock(return_value="B wrapped")
        second.name = "second"

        reg = WrapperRegistry([first, second])
        assert await reg.find_first_rewrite("cmd") == "B wrapped"

    @pytest.mark.asyncio
    async def test_skips_inactive_wrappers(self):
        active = MagicMock(spec=Wrapper)
        active.is_active = MagicMock(return_value=True)
        active.maybe_rewrite = AsyncMock(return_value="ok")
        active.name = "a"
        inactive = MagicMock(spec=Wrapper)
        inactive.is_active = MagicMock(return_value=False)
        inactive.maybe_rewrite = AsyncMock(return_value="never seen")
        inactive.name = "i"

        reg = WrapperRegistry([inactive, active])
        assert await reg.find_first_rewrite("cmd") == "ok"
        inactive.maybe_rewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_swallows_wrapper_exceptions(self):
        bad = MagicMock(spec=Wrapper)
        bad.is_active = MagicMock(return_value=True)
        bad.maybe_rewrite = AsyncMock(side_effect=RuntimeError("kaboom"))
        bad.name = "bad"
        good = MagicMock(spec=Wrapper)
        good.is_active = MagicMock(return_value=True)
        good.maybe_rewrite = AsyncMock(return_value="recovery")
        good.name = "good"

        reg = WrapperRegistry([bad, good])
        assert await reg.find_first_rewrite("cmd") == "recovery"

    def test_compose_prompt_blocks_concatenates_active(self):
        a = MagicMock(spec=Wrapper)
        a.is_active = MagicMock(return_value=True)
        a.prompt_block = "block A content"
        a.name = "alpha"
        b = MagicMock(spec=Wrapper)
        b.is_active = MagicMock(return_value=True)
        b.prompt_block = "block B content"
        b.name = "beta"
        out = WrapperRegistry([a, b]).compose_prompt_blocks()
        assert "alpha" in out and "beta" in out
        assert "block A content" in out and "block B content" in out

    def test_compose_prompt_blocks_returns_none_when_empty(self):
        w = MagicMock(spec=Wrapper)
        w.is_active = MagicMock(return_value=True)
        w.prompt_block = None
        w.name = "x"
        assert WrapperRegistry([w]).compose_prompt_blocks() is None

    def test_strip_transparent_prefix_single(self):
        w = MagicMock(spec=Wrapper)
        w.is_active = MagicMock(return_value=True)
        w.transparent_for_safety = True
        w.binary = "rtk"
        w.name = "rtk"
        reg = WrapperRegistry([w])
        assert reg.strip_transparent_prefixes("rtk git status") == "git status"

    def test_strip_transparent_prefix_stacked(self):
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
        reg = WrapperRegistry([rtk, time])
        assert reg.strip_transparent_prefixes("time rtk git status") == "git status"

    def test_strip_only_active_wrappers(self):
        w = MagicMock(spec=Wrapper)
        w.is_active = MagicMock(return_value=False)  # disabled
        w.transparent_for_safety = True
        w.binary = "rtk"
        w.name = "rtk"
        # Inactive wrapper does NOT license stripping.
        assert WrapperRegistry([w]).strip_transparent_prefixes("rtk git status") == "rtk git status"

    def test_strip_skips_non_transparent(self):
        w = MagicMock(spec=Wrapper)
        w.is_active = MagicMock(return_value=True)
        w.transparent_for_safety = False
        w.binary = "rtk"
        w.name = "rtk"
        assert WrapperRegistry([w]).strip_transparent_prefixes("rtk git status") == "rtk git status"

    def test_strip_no_match_passes_through(self):
        assert WrapperRegistry([]).strip_transparent_prefixes("git status") == "git status"

    def test_find_active_wrapper_by_prefix(self):
        w = MagicMock(spec=Wrapper)
        w.is_active = MagicMock(return_value=True)
        w.binary = "rtk"
        w.name = "rtk"
        reg = WrapperRegistry([w])
        assert reg.find_active_wrapper_by_prefix("rtk git status") is w
        assert reg.find_active_wrapper_by_prefix("git status") is None

    def test_singleton_thread_safe(self):
        """Multiple threads racing on get_registry() yield one instance."""
        set_registry(None)
        results = []

        def worker():
            results.append(get_registry())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = results[0]
        assert all(r is first for r in results)


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    def test_default_config_yields_rtk_wrapper(self):
        """With no user config, the registry contains exactly the rtk default."""
        from ppxai.config.tools import _resolve_wrappers
        merged = _resolve_wrappers({})
        assert len(merged) == 1
        assert merged[0]["name"] == "rtk"
        assert merged[0]["type"] == "probe"

    def test_user_entry_overrides_default_by_name(self):
        from ppxai.config.tools import _resolve_wrappers
        merged = _resolve_wrappers({
            "wrappers": [
                {"name": "rtk", "enabled": "never"},
            ],
        })
        rtk = next(e for e in merged if e["name"] == "rtk")
        assert rtk["enabled"] == "never"
        # Default fields not touched by the user remain
        assert rtk["type"] == "probe"
        assert rtk["binary"] == "rtk"

    def test_user_entry_with_new_name_appends(self):
        from ppxai.config.tools import _resolve_wrappers
        merged = _resolve_wrappers({
            "wrappers": [
                {"name": "myperf", "type": "always", "binary": "myperf", "prefix": "myperf -q"},
            ],
        })
        names = [e["name"] for e in merged]
        assert names == ["rtk", "myperf"]

    def test_legacy_use_rtk_shim(self):
        from ppxai.config.tools import _resolve_wrappers
        merged = _resolve_wrappers({"use_rtk": "never"})
        rtk = next(e for e in merged if e["name"] == "rtk")
        assert rtk["enabled"] == "never"

    def test_legacy_use_rtk_prompt_hint_disables_block(self):
        from ppxai.config.tools import _resolve_wrappers
        merged = _resolve_wrappers({"use_rtk_prompt_hint": False})
        rtk = next(e for e in merged if e["name"] == "rtk")
        assert rtk["prompt_block_path"] is None

    def test_malformed_user_entry_skipped(self):
        from ppxai.config.tools import _resolve_wrappers
        merged = _resolve_wrappers({
            "wrappers": [
                {"name": "rtk", "enabled": "never"},
                "not a dict",                   # skipped
                {"no_name_field": True},        # skipped
            ],
        })
        # Only rtk is present (with enabled=never override applied)
        assert len(merged) == 1
        assert merged[0]["enabled"] == "never"
