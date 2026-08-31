"""TUI renderer gap-fix tests (v1.18.5).

Pre-fix, both `rendering/rich_renderer.py::render_preview` and
`rendering/textual_renderer.py::render_preview` ignored
`result.metadata["mode"]` and unconditionally started a static-file
PreviewServer regardless of `--serve` / `--proxy` flags. The flags
were parsed by `commands/display.py::handle_preview` and packaged
into the metadata, then silently dropped here. Slash help text
advertised "autostart backend" but TUI sessions did nothing of the
sort.

This file pins the post-fix contract: `mode=served` triggers
`start_served_backend`; `mode=proxied` triggers `start_proxied_backend`;
`mode=static` (or absent) keeps the pre-fix behavior. `close` action
stops both static and backend.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ppxai.rendering.rich_renderer as rr  # noqa: E402
import ppxai.rendering.textual_renderer as tr  # noqa: E402

# Import ppxai.tui.app FIRST so its `from ppxai.rendering.textual_renderer
# import TextualRenderer` line fully populates textual_renderer's module
# namespace before our own import of textual_renderer kicks in. Without
# this, textual_renderer's `from ..tui.widgets.dialog import ...` walks
# back into ppxai.tui/__init__ → ppxai.tui.app → textual_renderer (still
# loading), and the cycle fails with ImportError. The normal app boot
# path doesn't hit this because ppxaide.py imports ppxai.tui first.
import ppxai.tui.app  # noqa: E402,F401
from ppxai.commands.results import PreviewResult, ResultStatus
from ppxai.engine.preview_backend import PreviewBackend, PreviewBackendError


def _backend_stub(pid: int = 12345, port: int = 8000, mode: str = "served") -> PreviewBackend:
    """Construct a PreviewBackend dataclass without a real subprocess."""
    proc = MagicMock()
    proc.pid = pid
    proc.returncode = None
    return PreviewBackend(
        process=proc if mode == "served" else None,
        port=port,
        command="python main.py" if mode == "served" else "(external — proxied)",
        url=f"http://localhost:{port}",
        working_dir="/tmp/wd",
        log_path=Path(f"/tmp/preview-backend-{pid}.log") if mode == "served" else None,
        drain_task=None,
        mode=mode,
    )


def _result(mode: str, command: str = None, port: int = None, action: str = None) -> PreviewResult:
    """Construct a PreviewResult mirroring what handle_preview would emit."""
    metadata = {"working_dir": "/tmp/wd", "mode": mode}
    if command is not None:
        metadata["command"] = command
    if port is not None:
        metadata["port"] = port
    if action is not None:
        metadata["action"] = action
    return PreviewResult(
        status=ResultStatus.SUCCESS,
        message="Preview test",
        filepath="/tmp/wd/index.html",
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Rich renderer
# ---------------------------------------------------------------------------


class TestRichRendererMode:
    """`render_preview` in rich_renderer.py honors mode flag."""

    @pytest.fixture(autouse=True)
    def _reset_module_state(self):
        rr._active_preview = None
        rr._active_preview_backend = None
        yield
        rr._active_preview = None
        rr._active_preview_backend = None

    def test_served_mode_calls_start_served_backend(self):
        backend = _backend_stub(mode="served")
        with patch.object(rr, "start_served_backend", AsyncMock(return_value=backend)) as srv, \
             patch.object(rr, "PreviewServer") as static_server_cls:
            static_server = MagicMock()
            static_server.start = MagicMock(return_value="http://localhost:50000/")
            static_server_cls.return_value = static_server
            rr.render_preview(_result(mode="served", command="python main.py"))
        srv.assert_awaited_once()
        assert rr._active_preview_backend is backend
        assert rr._active_preview is static_server  # static server also started

    def test_proxied_mode_calls_start_proxied_backend(self):
        backend = _backend_stub(mode="proxied")
        with patch.object(rr, "start_proxied_backend", AsyncMock(return_value=backend)) as prx, \
             patch.object(rr, "PreviewServer") as static_server_cls:
            static_server = MagicMock()
            static_server.start = MagicMock(return_value="http://localhost:50000/")
            static_server_cls.return_value = static_server
            rr.render_preview(_result(mode="proxied", port=8000))
        prx.assert_awaited_once()
        assert rr._active_preview_backend is backend

    def test_static_mode_skips_backend(self):
        with patch.object(rr, "start_served_backend", AsyncMock()) as srv, \
             patch.object(rr, "start_proxied_backend", AsyncMock()) as prx, \
             patch.object(rr, "PreviewServer") as static_server_cls:
            static_server = MagicMock()
            static_server.start = MagicMock(return_value="http://localhost:50000/")
            static_server_cls.return_value = static_server
            rr.render_preview(_result(mode="static"))
        srv.assert_not_called()
        prx.assert_not_called()
        assert rr._active_preview_backend is None

    def test_close_action_stops_both(self):
        # Prime module-level state with a fake active static + backend
        rr._active_preview = MagicMock()
        rr._active_preview.is_running = True
        rr._active_preview_backend = _backend_stub(mode="served")

        with patch.object(rr, "stop_backend", AsyncMock()) as stop_mock:
            rr.render_preview(_result(mode="static", action="close"))

        stop_mock.assert_awaited_once()
        assert rr._active_preview is None
        assert rr._active_preview_backend is None

    def test_served_backend_failure_does_not_start_static(self):
        """If the backend fails to spawn, don't open a browser at a URL
        whose fetches will all fail. PreviewServer must not be started."""
        with patch.object(rr, "start_served_backend", AsyncMock(
            side_effect=PreviewBackendError("backend died", status_code=500)
        )), \
             patch.object(rr, "PreviewServer") as static_server_cls:
            rr.render_preview(_result(mode="served", command="python main.py"))
        static_server_cls.assert_not_called()
        assert rr._active_preview_backend is None


# ---------------------------------------------------------------------------
# Textual renderer
# ---------------------------------------------------------------------------


class TestTextualRendererMode:
    """`render_preview` in textual_renderer.py honors mode flag."""

    @pytest.fixture(autouse=True)
    def _reset_module_state(self):
        tr._active_preview = None
        tr._active_preview_backend = None
        yield
        tr._active_preview = None
        tr._active_preview_backend = None

    def _make_renderer(self):
        """Make a minimal TextualRenderer-like mock for testing."""
        renderer = MagicMock()
        chat_view = MagicMock()
        chat_view.add_system_message = MagicMock()
        renderer._get_chat_view = MagicMock(return_value=chat_view)
        return renderer, chat_view

    @pytest.mark.asyncio
    async def test_served_mode_calls_start_served_backend(self):
        renderer, chat_view = self._make_renderer()
        backend = _backend_stub(mode="served")
        with patch.object(tr, "start_served_backend", AsyncMock(return_value=backend)) as srv, \
             patch.object(tr, "PreviewServer") as static_server_cls:
            static_server = MagicMock()
            static_server.start = MagicMock(return_value="http://localhost:50000/")
            static_server_cls.return_value = static_server
            await tr.render_preview(renderer, _result(mode="served", command="python main.py"))
        srv.assert_awaited_once()
        assert tr._active_preview_backend is backend
        assert tr._active_preview is static_server

    @pytest.mark.asyncio
    async def test_proxied_mode_calls_start_proxied_backend(self):
        renderer, chat_view = self._make_renderer()
        backend = _backend_stub(mode="proxied")
        with patch.object(tr, "start_proxied_backend", AsyncMock(return_value=backend)) as prx, \
             patch.object(tr, "PreviewServer") as static_server_cls:
            static_server = MagicMock()
            static_server.start = MagicMock(return_value="http://localhost:50000/")
            static_server_cls.return_value = static_server
            await tr.render_preview(renderer, _result(mode="proxied", port=8000))
        prx.assert_awaited_once()
        assert tr._active_preview_backend is backend

    @pytest.mark.asyncio
    async def test_static_mode_skips_backend(self):
        renderer, chat_view = self._make_renderer()
        with patch.object(tr, "start_served_backend", AsyncMock()) as srv, \
             patch.object(tr, "start_proxied_backend", AsyncMock()) as prx, \
             patch.object(tr, "PreviewServer") as static_server_cls:
            static_server = MagicMock()
            static_server.start = MagicMock(return_value="http://localhost:50000/")
            static_server_cls.return_value = static_server
            await tr.render_preview(renderer, _result(mode="static"))
        srv.assert_not_called()
        prx.assert_not_called()
        assert tr._active_preview_backend is None

    @pytest.mark.asyncio
    async def test_close_action_stops_both(self):
        renderer, chat_view = self._make_renderer()
        tr._active_preview = MagicMock()
        tr._active_preview.is_running = True
        tr._active_preview_backend = _backend_stub(mode="served")

        with patch.object(tr, "stop_backend", AsyncMock()) as stop_mock:
            await tr.render_preview(renderer, _result(mode="static", action="close"))

        stop_mock.assert_awaited_once()
        assert tr._active_preview is None
        assert tr._active_preview_backend is None

    @pytest.mark.asyncio
    async def test_served_backend_failure_does_not_start_static(self):
        renderer, chat_view = self._make_renderer()
        with patch.object(tr, "start_served_backend", AsyncMock(
            side_effect=PreviewBackendError("backend died", status_code=500)
        )), \
             patch.object(tr, "PreviewServer") as static_server_cls:
            await tr.render_preview(renderer, _result(mode="served", command="python main.py"))
        static_server_cls.assert_not_called()
        assert tr._active_preview_backend is None
