"""`EngineClient.set_working_dir()` is the single choke point for working dir.

It fans out to five places. Before this file, nothing tested that fan-out:
two test modules called the setter, and the rest poked internals directly
(`engine.context_injector.working_dir = ...`, `state.set("working_dir", ...)`,
`engine.session.working_dir = ...`). So any of the five could have silently
stopped firing.

That gap is not theoretical. Because `session.set_working_dir()` persists the
value, a spawned test server restoring a real session inherited the developer's
`$HOME` as its working directory, and `/files/tree` walked it -- the cause of
two "flaky" smoke-test timeouts. The write path is load-bearing; pin it.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ppxai.engine.client import EngineClient
from ppxai.engine.types import EventType


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """A real EngineClient with the expensive collaborators stubbed."""
    monkeypatch.setattr(EngineClient, "load_bootstrap_context", lambda self: None)
    monkeypatch.setattr(EngineClient, "_init_checkpoint_manager", lambda self, p: None)
    client = EngineClient.__new__(EngineClient)
    client.context_injector = MagicMock(working_dir=None)
    client.session = MagicMock()
    client.state = MagicMock()
    client._event_queue = []
    client.enqueue_event = client._event_queue.append
    return client


def _set(engine, path):
    """Drive the choke point the way a client would."""
    EngineClient.set_working_dir(engine, str(path))


class TestSetWorkingDirFansOut:
    def test_updates_context_injector(self, engine, tmp_path):
        _set(engine, tmp_path)
        engine.context_injector.set_working_dir.assert_called_once_with(str(tmp_path))

    def test_updates_app_state(self, engine, tmp_path):
        """AppState is what the 4 clients render; a miss here shows a stale dir."""
        _set(engine, tmp_path)
        engine.state.set.assert_called_once_with("working_dir", str(tmp_path))

    def test_persists_to_session(self, engine, tmp_path):
        """This is the write that leaks host state into later runs -- see the
        module docstring. It must keep happening, but knowing it happens is
        exactly why spawned-server tests must pin their working dir."""
        _set(engine, tmp_path)
        engine.session.set_working_dir.assert_called_once_with(str(tmp_path))

    def test_emits_working_dir_changed_event(self, engine, tmp_path):
        _set(engine, tmp_path)
        assert len(engine._event_queue) == 1
        event = engine._event_queue[0]
        assert event.type == EventType.WORKING_DIR_CHANGED
        assert event.data == {"path": str(tmp_path)}

    def test_all_five_fire_together(self, engine, tmp_path):
        """The point of a choke point: no partial application."""
        _set(engine, tmp_path)
        assert engine.context_injector.set_working_dir.called
        assert engine.state.set.called
        assert engine.session.set_working_dir.called
        assert len(engine._event_queue) == 1


class TestSetWorkingDirNoOpsOnUnchanged:
    """v1.15.3 dedup: re-setting the same dir must not re-emit or re-persist."""

    def test_identical_path_is_a_no_op(self, engine, tmp_path):
        engine.context_injector.working_dir = str(tmp_path)
        _set(engine, tmp_path)
        assert engine._event_queue == []
        assert not engine.state.set.called
        assert not engine.session.set_working_dir.called

    def test_equivalent_path_is_a_no_op(self, engine, tmp_path):
        """Comparison is by resolved path, not string equality."""
        engine.context_injector.working_dir = str(tmp_path)
        _set(engine, Path(str(tmp_path)) / "." )
        assert engine._event_queue == []

    def test_different_path_still_fires(self, engine, tmp_path):
        engine.context_injector.working_dir = str(tmp_path)
        other = tmp_path / "elsewhere"
        other.mkdir()
        _set(engine, other)
        assert len(engine._event_queue) == 1
        assert engine.state.set.called


class TestReadPathIsNotAppState:
    """`get_working_dir()` reads context_injector, NOT AppState.

    AppState is a write-side mirror for clients. Anything that sets
    `context_injector.working_dir` directly (several unit tests do) is
    invisible to AppState but fully visible to /files/tree and friends --
    worth pinning so the asymmetry is not "fixed" by accident.
    """

    def test_get_reads_context_injector(self, engine):
        engine.context_injector.working_dir = "/from/injector"
        engine.state.get = MagicMock(return_value="/from/appstate")
        assert EngineClient.get_working_dir(engine) == "/from/injector"
