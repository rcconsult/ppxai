"""Tests for ppxai.server.state — session resolution, preview backend
registry, kill helper.

These cover the un-tested parts of state.py flagged by the
code-review-graph (Session/get_or_create_session/get_session_or_query
risk 0.7-0.85, 19 untested nodes).

with_drained_events() is covered separately in
test_rest_event_piggyback.py — not duplicated here.
"""

from __future__ import annotations

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from ppxai.server import state as state_mod
from ppxai.server.state import (
    PreviewBackend,
    all_preview_backends,
    get_or_create_session,
    get_preview_backend,
    get_session_or_query,
    kill_preview_backend,
    remove_preview_backend,
    set_preview_backend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def restore_session_manager():
    """Snapshot state_mod.session_manager and restore it after the test.

    Each test that mutates the singleton MUST use this fixture so it
    doesn't bleed into the next test.
    """
    original = state_mod.session_manager
    yield
    state_mod.session_manager = original


@pytest.fixture
def clean_preview_registry():
    """Snapshot the preview backend registry and restore after."""
    snapshot = dict(state_mod._preview_backends)
    state_mod._preview_backends.clear()
    yield state_mod._preview_backends
    state_mod._preview_backends.clear()
    state_mod._preview_backends.update(snapshot)


def _make_manager(initialized: bool, engine=None, raises: Exception | None = None):
    """Build a mock SessionManager for state-layer tests."""
    manager = MagicMock()
    manager.is_initialized = initialized
    if raises is not None:
        manager.get_or_create_session = AsyncMock(side_effect=raises)
    else:
        lock = asyncio.Lock()
        eng = engine or MagicMock()
        eng.reload_config = MagicMock()
        manager.get_or_create_session = AsyncMock(
            return_value=("default", eng, lock)
        )
    return manager


# ---------------------------------------------------------------------------
# Critique #2.a + #2.b — get_or_create_session
# ---------------------------------------------------------------------------

class TestGetOrCreateSession:
    """The state-layer wrapper around SessionManager.get_or_create_session."""

    @pytest.mark.asyncio
    async def test_returns_503_when_session_manager_is_none(self, restore_session_manager):
        state_mod.session_manager = None
        with pytest.raises(HTTPException) as ei:
            await get_or_create_session(None)
        assert ei.value.status_code == 503
        assert "not initialized" in str(ei.value.detail).lower()

    @pytest.mark.asyncio
    async def test_returns_503_when_manager_not_initialized(self, restore_session_manager):
        state_mod.session_manager = _make_manager(initialized=False)
        with pytest.raises(HTTPException) as ei:
            await get_or_create_session(None)
        assert ei.value.status_code == 503
        assert "not initialized" in str(ei.value.detail).lower()

    @pytest.mark.asyncio
    async def test_returns_503_when_inner_raises_runtime_error(self, restore_session_manager):
        state_mod.session_manager = _make_manager(
            initialized=True,
            raises=RuntimeError("session limit exceeded"),
        )
        with pytest.raises(HTTPException) as ei:
            await get_or_create_session("sess-1")
        assert ei.value.status_code == 503
        assert "session limit exceeded" in str(ei.value.detail)

    @pytest.mark.asyncio
    async def test_delegates_to_manager_with_session_id(self, restore_session_manager):
        manager = _make_manager(initialized=True)
        state_mod.session_manager = manager
        await get_or_create_session("custom-sid")
        manager.get_or_create_session.assert_awaited_once_with("custom-sid")

    @pytest.mark.asyncio
    async def test_delegates_to_manager_with_none_id_for_default(self, restore_session_manager):
        manager = _make_manager(initialized=True)
        state_mod.session_manager = manager
        await get_or_create_session(None)
        manager.get_or_create_session.assert_awaited_once_with(None)

    @pytest.mark.asyncio
    async def test_calls_engine_reload_config_on_success(self, restore_session_manager):
        engine = MagicMock()
        engine.reload_config = MagicMock()
        manager = _make_manager(initialized=True, engine=engine)
        state_mod.session_manager = manager
        sid, returned_engine, lock = await get_or_create_session(None)
        engine.reload_config.assert_called_once()
        assert returned_engine is engine
        assert sid == "default"
        assert isinstance(lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_does_not_call_reload_config_when_503(self, restore_session_manager):
        state_mod.session_manager = None
        with pytest.raises(HTTPException):
            await get_or_create_session(None)


# ---------------------------------------------------------------------------
# Critique #2.c — get_session_or_query (header beats query)
# ---------------------------------------------------------------------------

class TestGetSessionOrQuery:
    """X-Session-Id header takes precedence over ?session= query param."""

    @pytest.mark.asyncio
    async def test_header_used_when_only_header_provided(self, restore_session_manager):
        manager = _make_manager(initialized=True)
        state_mod.session_manager = manager
        await get_session_or_query(x_session_id="from-header", session=None)
        manager.get_or_create_session.assert_awaited_once_with("from-header")

    @pytest.mark.asyncio
    async def test_query_used_when_only_query_provided(self, restore_session_manager):
        manager = _make_manager(initialized=True)
        state_mod.session_manager = manager
        await get_session_or_query(x_session_id=None, session="from-query")
        manager.get_or_create_session.assert_awaited_once_with("from-query")

    @pytest.mark.asyncio
    async def test_header_beats_query_when_both_provided(self, restore_session_manager):
        manager = _make_manager(initialized=True)
        state_mod.session_manager = manager
        await get_session_or_query(
            x_session_id="from-header", session="from-query"
        )
        manager.get_or_create_session.assert_awaited_once_with("from-header")

    @pytest.mark.asyncio
    async def test_none_when_neither_provided(self, restore_session_manager):
        manager = _make_manager(initialized=True)
        state_mod.session_manager = manager
        await get_session_or_query(x_session_id=None, session=None)
        manager.get_or_create_session.assert_awaited_once_with(None)

    @pytest.mark.asyncio
    async def test_returns_session_dataclass_with_id_engine_lock(self, restore_session_manager):
        engine = MagicMock()
        engine.reload_config = MagicMock()
        manager = _make_manager(initialized=True, engine=engine)
        state_mod.session_manager = manager
        s = await get_session_or_query(x_session_id="sid-1", session=None)
        assert s.id == "default"  # mock returns "default" regardless of input
        assert s.engine is engine
        assert isinstance(s.lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# Critique #2.e — preview backend registry lifecycle
# ---------------------------------------------------------------------------

class TestPreviewBackendRegistry:
    """Module-level dict registry: set/get/remove/all behaviors."""

    def _backend(self, port=3000):
        return PreviewBackend(
            process=MagicMock(),
            port=port,
            command="npm start",
            url=f"http://127.0.0.1:{port}",
            working_dir="/tmp",
        )

    def test_get_returns_none_for_unknown_session(self, clean_preview_registry):
        assert get_preview_backend("does-not-exist") is None

    def test_set_then_get_returns_same_backend(self, clean_preview_registry):
        backend = self._backend()
        set_preview_backend("sid-1", backend)
        assert get_preview_backend("sid-1") is backend

    def test_set_overwrites_existing_entry(self, clean_preview_registry):
        first = self._backend(port=3000)
        second = self._backend(port=3001)
        set_preview_backend("sid-1", first)
        set_preview_backend("sid-1", second)
        assert get_preview_backend("sid-1") is second

    def test_remove_returns_value_and_clears_entry(self, clean_preview_registry):
        backend = self._backend()
        set_preview_backend("sid-1", backend)
        removed = remove_preview_backend("sid-1")
        assert removed is backend
        assert get_preview_backend("sid-1") is None

    def test_remove_unknown_returns_none(self, clean_preview_registry):
        assert remove_preview_backend("ghost") is None

    def test_all_includes_set_entries(self, clean_preview_registry):
        b1 = self._backend(port=3000)
        b2 = self._backend(port=3001)
        set_preview_backend("a", b1)
        set_preview_backend("b", b2)
        registry = all_preview_backends()
        assert registry["a"] is b1
        assert registry["b"] is b2
        assert len(registry) == 2

    def test_all_returns_live_dict_reflects_subsequent_changes(self, clean_preview_registry):
        registry = all_preview_backends()
        assert registry == {}
        set_preview_backend("a", self._backend())
        assert "a" in registry  # same dict reference, not snapshot

    def test_preview_backend_last_seen_defaults_to_now(self, clean_preview_registry):
        import time
        before = time.time()
        backend = self._backend()
        after = time.time()
        assert before <= backend.last_seen <= after


# ---------------------------------------------------------------------------
# Critique #2.f — kill_preview_backend (already-dead + timeout paths)
# ---------------------------------------------------------------------------

class TestKillPreviewBackend:
    """All branches of the SIGTERM → wait → kill chain."""

    def _backend_with_process(self):
        proc = MagicMock()
        proc.pid = 12345
        proc.wait = AsyncMock()
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        backend = PreviewBackend(
            process=proc,
            port=3000,
            command="npm start",
            url="http://127.0.0.1:3000",
            working_dir="/tmp",
        )
        return backend, proc

    @pytest.mark.asyncio
    async def test_unix_sends_sigterm_to_process_group(self):
        backend, proc = self._backend_with_process()
        with patch("ppxai.server.state.platform.system", return_value="Linux"), \
             patch("ppxai.server.state.os.getpgid", return_value=12345) as gp, \
             patch("ppxai.server.state.os.killpg") as kp:
            await kill_preview_backend(backend)
        gp.assert_called_once_with(12345)
        kp.assert_called_once_with(12345, signal.SIGTERM)
        proc.wait.assert_awaited()

    @pytest.mark.asyncio
    async def test_windows_calls_process_terminate(self):
        backend, proc = self._backend_with_process()
        with patch("ppxai.server.state.platform.system", return_value="Windows"):
            await kill_preview_backend(backend)
        proc.terminate.assert_called_once()
        proc.wait.assert_awaited()

    @pytest.mark.asyncio
    async def test_already_dead_process_lookup_swallowed(self):
        """getpgid raising ProcessLookupError must not surface."""
        backend, proc = self._backend_with_process()
        with patch("ppxai.server.state.platform.system", return_value="Linux"), \
             patch("ppxai.server.state.os.getpgid",
                   side_effect=ProcessLookupError("no such process")):
            await kill_preview_backend(backend)  # must not raise
        proc.wait.assert_awaited()

    @pytest.mark.asyncio
    async def test_killpg_oserror_swallowed(self):
        """os.killpg raising OSError (e.g. EPERM) must not surface."""
        backend, proc = self._backend_with_process()
        with patch("ppxai.server.state.platform.system", return_value="Linux"), \
             patch("ppxai.server.state.os.getpgid", return_value=12345), \
             patch("ppxai.server.state.os.killpg",
                   side_effect=OSError("permission denied")):
            await kill_preview_backend(backend)
        proc.wait.assert_awaited()

    @pytest.mark.asyncio
    async def test_wait_timeout_triggers_hard_kill(self):
        """If wait() times out, fall through to process.kill()."""
        backend, proc = self._backend_with_process()
        proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("ppxai.server.state.platform.system", return_value="Linux"), \
             patch("ppxai.server.state.os.getpgid", return_value=12345), \
             patch("ppxai.server.state.os.killpg"):
            await kill_preview_backend(backend)

        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_kill_after_wait_swallows_dead_process(self):
        """If process died between wait-timeout and kill(), don't raise."""
        backend, proc = self._backend_with_process()
        proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        proc.kill = MagicMock(side_effect=ProcessLookupError("died"))

        with patch("ppxai.server.state.platform.system", return_value="Linux"), \
             patch("ppxai.server.state.os.getpgid", return_value=12345), \
             patch("ppxai.server.state.os.killpg"):
            await kill_preview_backend(backend)

        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_processlookuperror_treated_as_already_dead(self):
        """Some kernels surface a dead-process wait as ProcessLookupError;
        kill_preview_backend must treat this as success, not crash."""
        backend, proc = self._backend_with_process()
        proc.wait = AsyncMock(side_effect=ProcessLookupError("already dead"))

        with patch("ppxai.server.state.platform.system", return_value="Linux"), \
             patch("ppxai.server.state.os.getpgid", return_value=12345), \
             patch("ppxai.server.state.os.killpg"):
            await kill_preview_backend(backend)  # must not raise

    @pytest.mark.asyncio
    async def test_wait_uses_2_second_timeout(self):
        """Doc says timeout=2 — guard against silent regression."""
        backend, proc = self._backend_with_process()

        captured = {}

        async def wait_for_capture(coro, timeout):
            captured["timeout"] = timeout
            return await coro

        with patch("ppxai.server.state.platform.system", return_value="Linux"), \
             patch("ppxai.server.state.os.getpgid", return_value=12345), \
             patch("ppxai.server.state.os.killpg"), \
             patch("ppxai.server.state.asyncio.wait_for", side_effect=wait_for_capture):
            await kill_preview_backend(backend)

        assert captured["timeout"] == 2
