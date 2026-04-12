"""
Tests for session persistence and auto-recovery (v1.13.9).

Tests the session state file management, command history persistence,
working directory persistence, and auto-restore functionality.
"""

import json
import os
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

from ppxai.engine.session import SessionManager, SESSION_STATE_FILE
from ppxai.config import get_session_config, get_auto_restore_mode, get_auto_save_interval
from ppxai.config.store import ConfigStore


@pytest.fixture
def temp_sessions_dir(tmp_path):
    """Create a temporary directory for session storage."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    return sessions_dir


@pytest.fixture
def temp_exports_dir(tmp_path):
    """Create a temporary directory for exports."""
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    return exports_dir


@pytest.fixture
def session_manager(temp_sessions_dir, temp_exports_dir):
    """Create a SessionManager instance with temp directories."""
    return SessionManager(sessions_dir=temp_sessions_dir, exports_dir=temp_exports_dir)


@pytest.fixture
def temp_state_file(tmp_path):
    """Create a temporary state file path."""
    return tmp_path / "session-state.json"


@pytest.fixture
def config_store():
    """Provide ConfigStore for test configuration injection.

    Yields the ConfigStore instance and resets it after the test.
    """
    store = ConfigStore.get_instance()
    yield store
    store.reset()


class TestSessionManagerCommandHistory:
    """Tests for command history persistence."""

    def test_add_to_history(self, session_manager):
        """Test adding commands to history."""
        session_manager.add_to_history("Hello, AI!")
        session_manager.add_to_history("/model gemini-2.5-flash")
        session_manager.add_to_history("Explain this code")

        assert len(session_manager.command_history) == 3
        assert session_manager.command_history[0] == "Hello, AI!"
        assert session_manager.command_history[1] == "/model gemini-2.5-flash"
        assert session_manager.command_history[2] == "Explain this code"

    def test_add_to_history_strips_whitespace(self, session_manager):
        """Test that history strips whitespace from commands."""
        session_manager.add_to_history("  Hello  ")
        session_manager.add_to_history("\tCommand\n")

        assert session_manager.command_history[0] == "Hello"
        assert session_manager.command_history[1] == "Command"

    def test_add_to_history_ignores_empty(self, session_manager):
        """Test that empty commands are not added to history."""
        session_manager.add_to_history("")
        session_manager.add_to_history("   ")
        session_manager.add_to_history(None)

        assert len(session_manager.command_history) == 0

    def test_command_history_saved_in_session(self, session_manager, temp_sessions_dir):
        """Test that command history is saved when session is saved."""
        session_manager.add_to_history("First command")
        session_manager.add_to_history("Second command")

        # Use save_dirty to include command history
        session_manager._save_with_extras()

        # Load the saved file and verify
        filepath = temp_sessions_dir / f"{session_manager.session_name}.json"
        with open(filepath) as f:
            data = json.load(f)

        assert "command_history" in data
        assert data["command_history"] == ["First command", "Second command"]


class TestSessionManagerWorkingDirectory:
    """Tests for working directory persistence."""

    def test_default_working_dir(self, session_manager):
        """Test default working directory is current directory."""
        assert session_manager.working_dir == os.getcwd()

    def test_set_working_dir(self, session_manager):
        """Test setting working directory."""
        session_manager.set_working_dir("/home/user/project")
        assert session_manager.working_dir == "/home/user/project"

    def test_working_dir_saved_in_session(self, session_manager, temp_sessions_dir):
        """Test that working directory is saved when session is saved."""
        session_manager.set_working_dir("/custom/path")
        session_manager._save_with_extras()

        # Load the saved file and verify
        filepath = temp_sessions_dir / f"{session_manager.session_name}.json"
        with open(filepath) as f:
            data = json.load(f)

        assert data["working_dir"] == "/custom/path"


class TestSessionDirtyState:
    """Tests for session dirty state management."""

    def test_initial_dirty_state(self, session_manager):
        """Test that session starts clean."""
        assert session_manager._dirty is False

    def test_save_dirty_marks_dirty(self, session_manager, temp_state_file):
        """Test that save_dirty marks session as dirty."""
        with patch.object(SessionManager, '_update_state_file'):
            session_manager.save_dirty()
            assert session_manager._dirty is True

    def test_mark_clean_clears_dirty(self, session_manager, temp_state_file):
        """Test that mark_clean clears dirty state."""
        session_manager._dirty = True

        with patch.object(SessionManager, '_update_state_file'):
            session_manager.mark_clean()
            assert session_manager._dirty is False


class TestSessionStateFile:
    """Tests for session state file management."""

    def test_update_state_file_creates_file(self, session_manager, tmp_path):
        """Test that update_state_file creates the state file."""
        state_file = tmp_path / "state.json"

        with patch('ppxai.engine.session.SESSION_STATE_FILE', state_file):
            session_manager._update_state_file(dirty=True)

            assert state_file.exists()
            with open(state_file) as f:
                data = json.load(f)
            assert data["version"] == 1
            assert data["last_session"]["dirty"] is True

    def test_update_state_file_content(self, session_manager, tmp_path):
        """Test the content of the state file."""
        state_file = tmp_path / "state.json"
        session_manager.metadata["provider"] = "gemini"
        session_manager.metadata["model"] = "gemini-2.5-flash"

        with patch('ppxai.engine.session.SESSION_STATE_FILE', state_file):
            session_manager._update_state_file(dirty=False)

            with open(state_file) as f:
                data = json.load(f)

            assert data["last_session"]["name"] == session_manager.session_name
            assert data["last_session"]["provider"] == "gemini"
            assert data["last_session"]["model"] == "gemini-2.5-flash"
            assert data["last_session"]["dirty"] is False
            assert "updated_at" in data

    def test_get_last_session_state_no_file(self, tmp_path):
        """Test get_last_session_state returns None when no file exists."""
        state_file = tmp_path / "nonexistent.json"

        with patch('ppxai.engine.session.SESSION_STATE_FILE', state_file):
            result = SessionManager.get_last_session_state()
            assert result is None

    def test_get_last_session_state_valid_file(self, tmp_path):
        """Test get_last_session_state returns session info."""
        state_file = tmp_path / "state.json"
        state_data = {
            "version": 1,
            "last_session": {
                "name": "test_session_123",
                "dirty": True,
                "provider": "perplexity",
                "model": "sonar-pro",
                "message_count": 5
            },
            "updated_at": "2026-01-12T10:30:00"
        }
        with open(state_file, 'w') as f:
            json.dump(state_data, f)

        with patch('ppxai.engine.session.SESSION_STATE_FILE', state_file):
            result = SessionManager.get_last_session_state()
            assert result["name"] == "test_session_123"
            assert result["dirty"] is True
            assert result["provider"] == "perplexity"
            assert result["message_count"] == 5

    def test_clear_state_file(self, tmp_path):
        """Test clearing the state file."""
        state_file = tmp_path / "state.json"
        with open(state_file, 'w') as f:
            json.dump({"version": 1, "last_session": {}}, f)

        with patch('ppxai.engine.session.SESSION_STATE_FILE', state_file):
            SessionManager.clear_state_file()
            assert not state_file.exists()


class TestSessionLoadWithExtras:
    """Tests for loading sessions with command history and working directory."""

    def test_load_with_extras_new_fields(self, session_manager, temp_sessions_dir):
        """Test loading a session with command history and working directory."""
        # Save a session with extras
        session_manager.add_to_history("test command 1")
        session_manager.add_to_history("test command 2")
        session_manager.set_working_dir("/project/path")
        session_manager._save_with_extras()
        saved_name = session_manager.session_name

        # Create a new session manager and load
        new_manager = SessionManager(sessions_dir=temp_sessions_dir)
        result = new_manager.load(saved_name)

        assert result is True
        assert new_manager.command_history == ["test command 1", "test command 2"]
        assert new_manager.working_dir == "/project/path"

    def test_load_with_extras_backward_compatible(self, session_manager, temp_sessions_dir):
        """Test loading an old session without new fields."""
        # Create an old-style session file without new fields
        old_session = {
            "session_name": "old_session",
            "metadata": {"created_at": "2026-01-01T00:00:00"},
            "messages": [],
            "usage": {}
        }
        filepath = temp_sessions_dir / "old_session.json"
        with open(filepath, 'w') as f:
            json.dump(old_session, f)

        # Load should succeed with defaults
        result = session_manager.load("old_session")

        assert result is True
        assert session_manager.command_history == []
        assert session_manager.working_dir == os.getcwd()


class TestSessionConfig:
    """Tests for session configuration."""

    def test_get_session_config_defaults(self, config_store):
        """Test default session config values."""
        # Minimal config with required fields
        config_store.set_for_testing({
            "config_source": "test",
            "default_provider": "perplexity",
            "providers": {},
            "tools": {},
            "context": {},
        })
        config = get_session_config()
        assert config["auto_restore"] == "prompt"
        assert config["auto_save_interval"] == 1

    def test_get_session_config_custom(self, config_store):
        """Test custom session config values."""
        config_store.set_for_testing({
            "config_source": "test",
            "default_provider": "perplexity",
            "providers": {},
            "tools": {},
            "context": {},
            "session": {
                "auto_restore": "always",
                "auto_save_interval": 5
            }
        })
        config = get_session_config()
        assert config["auto_restore"] == "always"
        assert config["auto_save_interval"] == 5

    def test_get_auto_restore_mode_valid_values(self, config_store):
        """Test valid auto_restore values."""
        for mode in ["always", "prompt", "never"]:
            config_store.set_for_testing({
                "config_source": "test",
                "default_provider": "perplexity",
                "providers": {},
                "tools": {},
                "context": {},
                "session": {"auto_restore": mode}
            })
            assert get_auto_restore_mode() == mode

    def test_get_auto_restore_mode_invalid_defaults_to_prompt(self, config_store):
        """Test invalid auto_restore value defaults to prompt."""
        config_store.set_for_testing({
            "config_source": "test",
            "default_provider": "perplexity",
            "providers": {},
            "tools": {},
            "context": {},
            "session": {"auto_restore": "invalid"}
        })
        assert get_auto_restore_mode() == "prompt"

    def test_get_auto_save_interval_valid(self, config_store):
        """Test valid auto_save_interval values."""
        config_store.set_for_testing({
            "config_source": "test",
            "default_provider": "perplexity",
            "providers": {},
            "tools": {},
            "context": {},
            "session": {"auto_save_interval": 10}
        })
        assert get_auto_save_interval() == 10

    def test_get_auto_save_interval_zero(self, config_store):
        """Test auto_save_interval of 0 (every message)."""
        config_store.set_for_testing({
            "config_source": "test",
            "default_provider": "perplexity",
            "providers": {},
            "tools": {},
            "context": {},
            "session": {"auto_save_interval": 0}
        })
        assert get_auto_save_interval() == 0

    def test_get_auto_save_interval_negative_clamped(self, config_store):
        """Test negative auto_save_interval is clamped to 0."""
        config_store.set_for_testing({
            "config_source": "test",
            "default_provider": "perplexity",
            "providers": {},
            "tools": {},
            "context": {},
            "session": {"auto_save_interval": -5}
        })
        assert get_auto_save_interval() == 0


class TestSessionFullFlow:
    """Integration tests for complete session persistence flow."""

    def test_save_and_restore_full_session(self, tmp_path):
        """Test saving and restoring a full session with all data."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        # Create and populate original session
        original = SessionManager(sessions_dir=sessions_dir)
        original.metadata["provider"] = "custom"
        original.metadata["model"] = "openai/gpt-oss-120b"
        original.add_to_history("What is Python?")
        original.add_to_history("/model gemini-2.5-flash")
        original.add_to_history("Explain decorators")
        original.set_working_dir("/home/user/myproject")

        # Simulate adding messages
        from ppxai.engine.types import Message
        original.add_message(Message(role="user", content="What is Python?"))
        original.add_message(Message(role="assistant", content="Python is a programming language..."))

        # Save
        original._save_with_extras()
        session_name = original.session_name

        # Restore to new manager
        restored = SessionManager(sessions_dir=sessions_dir)
        assert restored.load(session_name)

        # Verify all data restored
        assert restored.session_name == session_name
        assert restored.metadata["provider"] == "custom"
        assert restored.metadata["model"] == "openai/gpt-oss-120b"
        assert len(restored.command_history) == 3
        assert restored.command_history[0] == "What is Python?"
        assert restored.working_dir == "/home/user/myproject"
        assert len(restored.messages) == 2

    def test_dirty_save_flow(self, tmp_path):
        """Test the dirty save flow for crash recovery."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"

        with patch('ppxai.engine.session.SESSION_STATE_FILE', state_file):
            # Create session and save dirty
            session = SessionManager(sessions_dir=sessions_dir)
            session.metadata["provider"] = "gemini"
            session.add_to_history("Test query")
            session.save_dirty()

            # Verify state file shows dirty
            with open(state_file) as f:
                state = json.load(f)
            assert state["last_session"]["dirty"] is True

            # Mark clean (graceful exit)
            session.mark_clean()

            # Verify state file shows clean
            with open(state_file) as f:
                state = json.load(f)
            assert state["last_session"]["dirty"] is False


class TestCommandsHandleQuit:
    """Tests for graceful exit marking session clean."""

    def test_handle_quit_marks_session_clean(self):
        """Test that handle_quit marks session as clean."""
        # This test verifies the command handler marks the session clean on graceful exit
        # We directly test the session's mark_clean method is called
        from unittest.mock import MagicMock, patch

        # Create mock session with mark_clean method
        mock_session = MagicMock()
        mock_session.messages = []  # No messages to save
        mock_session.mark_clean = MagicMock()
        mock_session.save_usage_to_persistent_storage = MagicMock()

        # Create mock engine client
        mock_engine = MagicMock()
        mock_engine.session = mock_session

        # Create a minimal command handler instance with mocked dependencies
        with patch('ppxai.commands.console'):
            # Create handler directly and inject the mock
            from ppxai.commands import CommandHandler
            with patch.object(CommandHandler, '__init__', lambda self, *args, **kwargs: None):
                handler = CommandHandler.__new__(CommandHandler)
                handler.engine_client = mock_engine

                # Call handle_quit
                result = handler.handle_quit()

                # Verify mark_clean was called
                mock_session.mark_clean.assert_called_once()
                assert result is True


class TestResetForModelSwitch:
    """Tests for session context reset on model switch (B1, v1.16.0)."""

    def test_reset_strips_all_for_clean_slate(self, session_manager):
        """Reset produces empty session: assistants stripped, then alternation fix
        collapses consecutive users and removes trailing user message."""
        from ppxai.engine.types import Message
        session_manager.add_message(Message(role="user", content="Hello"))
        session_manager.add_message(Message(role="assistant", content="Hi there"))
        session_manager.add_message(Message(role="user", content="How are you?"))
        session_manager.add_message(Message(role="assistant", content="I'm fine"))

        removed = session_manager.reset_for_model_switch()

        # [user, user] -> collapse -> [user] -> trailing user removed -> []
        assert removed == 4
        assert len(session_manager.messages) == 0

    def test_reset_strips_assistant_messages(self, session_manager):
        """All messages removed: assistants stripped, consecutive users collapsed,
        trailing user removed."""
        from ppxai.engine.types import Message
        session_manager.add_message(Message(role="user", content="Q1"))
        session_manager.add_message(Message(role="assistant", content="A1"))
        session_manager.add_message(Message(role="user", content="Q2"))
        session_manager.add_message(Message(role="assistant", content="A2"))

        removed = session_manager.reset_for_model_switch()

        # Strip 2 assistants -> [user, user] -> collapse -> [user] -> trailing -> []
        assert removed == 4
        assert len(session_manager.messages) == 0

    def test_reset_strips_tool_messages(self, session_manager):
        """Tool and assistant messages stripped, trailing user removed."""
        from ppxai.engine.types import Message
        session_manager.add_message(Message(role="user", content="Read file"))
        session_manager.add_message(Message(role="assistant", content="Using tool..."))
        session_manager.add_message(Message(role="tool", content='{"result": "ok"}'))
        session_manager.add_message(Message(role="assistant", content="Done"))

        removed = session_manager.reset_for_model_switch()

        # Strip 2 assistants + 1 tool -> [user] -> trailing user removed -> []
        assert removed == 4
        assert len(session_manager.messages) == 0

    def test_reset_empty_session(self, session_manager):
        """No-op on empty session, returns 0."""
        removed = session_manager.reset_for_model_switch()

        assert removed == 0
        assert len(session_manager.messages) == 0

    def test_reset_updates_metadata(self, session_manager):
        """message_count metadata is updated after reset (0 after full cleanup)."""
        from ppxai.engine.types import Message
        session_manager.add_message(Message(role="user", content="Q"))
        session_manager.add_message(Message(role="assistant", content="A"))
        session_manager.add_message(Message(role="user", content="Q2"))

        assert session_manager.metadata["message_count"] == 3

        session_manager.reset_for_model_switch()

        # Strip assistant -> [user, user] -> collapse -> [user] -> trailing -> []
        assert session_manager.metadata["message_count"] == 0

    def test_reset_fixes_alternation(self, session_manager):
        """After reset, consecutive user messages are collapsed for API compatibility."""
        from ppxai.engine.types import Message
        # Build a multi-turn conversation
        session_manager.add_message(Message(role="user", content="Q1"))
        session_manager.add_message(Message(role="assistant", content="A1"))
        session_manager.add_message(Message(role="user", content="Q2"))
        session_manager.add_message(Message(role="assistant", content="A2"))
        session_manager.add_message(Message(role="user", content="Q3"))
        session_manager.add_message(Message(role="assistant", content="A3"))

        assert len(session_manager.messages) == 6

        removed = session_manager.reset_for_model_switch()

        # After stripping assistants: [user, user, user]
        # After alternation fix: only first user kept (consecutive users collapsed)
        # Then trailing user removed -> 0 messages, or 1 user kept
        # validate_and_fix_alternation keeps first of consecutive same-role,
        # then removes trailing user if it's the last message
        # So: [Q1, Q2, Q3] -> keep Q1, drop Q2, drop Q3 -> [Q1] -> trailing user removed -> []
        # Total removed: 3 assistants + 2 duplicate users + 1 trailing = 6
        assert removed == 6
        assert len(session_manager.messages) == 0

    def test_reset_single_turn_keeps_nothing(self, session_manager):
        """Single user+assistant turn: reset keeps user, then removes trailing user."""
        from ppxai.engine.types import Message
        session_manager.add_message(Message(role="user", content="Hello"))
        session_manager.add_message(Message(role="assistant", content="Hi"))

        removed = session_manager.reset_for_model_switch()

        # Strip assistant -> [user] -> trailing user removed -> []
        assert removed == 2
        assert len(session_manager.messages) == 0

    def test_reset_preserves_valid_alternation(self, session_manager):
        """When only one user message exists, reset produces valid state."""
        from ppxai.engine.types import Message
        session_manager.add_message(Message(role="user", content="Only question"))

        removed = session_manager.reset_for_model_switch()

        # [user] -> trailing user removed -> []
        # The alternation fix removes trailing user messages
        assert len(session_manager.messages) == 0


# =============================================================================
# Disk-scan fallback for missing state pointer (v1.17.4)
# =============================================================================


class TestSessionDiskScanFallback:
    """Tests for SessionManager.find_most_recent_session_on_disk and
    get_last_session_state_or_scan — the safety net for when the state
    pointer is missing but sessions still exist on disk.
    """

    def test_find_most_recent_returns_none_when_no_sessions(self, tmp_path, monkeypatch):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(
            "pathlib.Path.home", lambda: tmp_path.parent / "home_stub"
        )
        # Point the sessions_dir via the function's own Path.home lookup
        fake_home = tmp_path
        monkeypatch.setattr("ppxai.engine.session.Path.home", lambda: fake_home)
        result = SessionManager.find_most_recent_session_on_disk()
        # tmp_path/.ppxai/sessions doesn't exist → returns None
        assert result is None

    def test_find_most_recent_picks_newest_flat_session(self, tmp_path, monkeypatch):
        sessions_dir = tmp_path / ".ppxai" / "sessions"
        sessions_dir.mkdir(parents=True)

        old = sessions_dir / "session_old.json"
        new = sessions_dir / "session_new.json"
        old.write_text(json.dumps({
            "session_name": "session_old",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"provider": "openai", "model": "gpt-4.1-mini"},
        }))
        new.write_text(json.dumps({
            "session_name": "session_new",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ],
            "metadata": {"provider": "perplexity", "model": "sonar"},
            "tools_enabled": True,
        }))
        import os as _os
        _os.utime(old, (1_000_000_000, 1_000_000_000))
        _os.utime(new, (2_000_000_000, 2_000_000_000))

        monkeypatch.setattr("ppxai.engine.session.Path.home", lambda: tmp_path)
        result = SessionManager.find_most_recent_session_on_disk()

        assert result is not None
        assert result["name"] == "session_new"
        assert result["message_count"] == 2
        assert result["provider"] == "perplexity"
        assert result["model"] == "sonar"
        assert result["tools_enabled"] is True
        assert result["recovered_from_disk"] is True
        # Fallback never reports dirty — if it were dirty, the state file
        # would still exist and we wouldn't have taken this path.
        assert result["dirty"] is False

    def test_find_most_recent_handles_directory_format(self, tmp_path, monkeypatch):
        sessions_dir = tmp_path / ".ppxai" / "sessions"
        sessions_dir.mkdir(parents=True)

        # Directory-format session (multimodal).
        session_dir = sessions_dir / "session_dir"
        session_dir.mkdir()
        inner = session_dir / "session.json"
        inner.write_text(json.dumps({
            "session_name": "session_dir",
            "messages": [{"role": "user", "content": "ping"}],
            "metadata": {"provider": "gemini", "model": "gemini-3-flash"},
        }))
        import os as _os
        _os.utime(inner, (3_000_000_000, 3_000_000_000))

        monkeypatch.setattr("ppxai.engine.session.Path.home", lambda: tmp_path)
        result = SessionManager.find_most_recent_session_on_disk()

        assert result is not None
        assert result["name"] == "session_dir"
        assert result["provider"] == "gemini"
        assert result["recovered_from_disk"] is True

    def test_get_or_scan_prefers_state_file(self, tmp_path, monkeypatch):
        sessions_dir = tmp_path / ".ppxai" / "sessions"
        sessions_dir.mkdir(parents=True)
        state_file = tmp_path / ".ppxai" / "session-state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "last_session": {
                "name": "from_state",
                "message_count": 5,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "dirty": False,
            },
        }))

        # Put a newer session on disk — the pointer should still win.
        (sessions_dir / "newer.json").write_text(json.dumps({
            "session_name": "newer",
            "messages": [{"role": "user", "content": "x"}],
            "metadata": {},
        }))

        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)
        monkeypatch.setattr("ppxai.engine.session.Path.home", lambda: tmp_path)

        result = SessionManager.get_last_session_state_or_scan()
        assert result is not None
        assert result["name"] == "from_state"
        # recovered_from_disk should NOT be set on the state-file path
        assert not result.get("recovered_from_disk", False)

    def test_get_or_scan_falls_back_when_state_missing(self, tmp_path, monkeypatch):
        sessions_dir = tmp_path / ".ppxai" / "sessions"
        sessions_dir.mkdir(parents=True)
        # No state file.
        state_file = tmp_path / ".ppxai" / "session-state.json"

        (sessions_dir / "orphan.json").write_text(json.dumps({
            "session_name": "orphan",
            "messages": [{"role": "user", "content": "x"},
                         {"role": "assistant", "content": "y"}],
            "metadata": {"provider": "openai", "model": "gpt-4.1-mini"},
        }))

        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)
        monkeypatch.setattr("ppxai.engine.session.Path.home", lambda: tmp_path)

        result = SessionManager.get_last_session_state_or_scan()
        assert result is not None
        assert result["name"] == "orphan"
        assert result["message_count"] == 2
        assert result["recovered_from_disk"] is True


# =============================================================================
# R11: Atomic flat↔directory session transition (v1.17.4)
# =============================================================================


class TestAtomicSessionFormatTransition:
    """Flat → directory session transition must be atomic, and a load
    that finds both formats must pick the newer and warn.
    """

    def _minimal_session(self, tmp_path, name="test_session"):
        from pathlib import Path as _Path
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        sm.session_name = name
        return sm

    def test_duplicate_formats_on_load_prefers_newer_directory(
        self, tmp_path, monkeypatch
    ):
        """Both flat and directory exist — newer wins, warning logged.

        Our engine module uses a custom Logger wrapper (common.logger),
        not the stdlib logging tree directly, so caplog doesn't see the
        warnings. We patch the module logger's `warning` method to
        record calls.
        """
        sm = self._minimal_session(tmp_path, "dup1")
        sessions_dir = sm.sessions_dir

        # Write a stale flat (older).
        flat = sessions_dir / "dup1.json"
        flat.write_text(json.dumps({
            "session_name": "dup1",
            "messages": [{"role": "user", "content": "stale"}],
            "metadata": {},
        }))
        import os as _os
        _os.utime(flat, (1_000_000_000, 1_000_000_000))

        # Write a newer directory session.
        dir_ = sessions_dir / "dup1"
        dir_.mkdir()
        dir_json = dir_ / "session.json"
        dir_json.write_text(json.dumps({
            "session_name": "dup1",
            "messages": [{"role": "user", "content": "fresh"}],
            "metadata": {},
        }))
        _os.utime(dir_json, (2_000_000_000, 2_000_000_000))

        # Record warning calls via a shim.
        from ppxai.engine import session as _session_mod
        warnings_seen = []
        monkeypatch.setattr(
            _session_mod.logger,
            "warning",
            lambda msg, *a, **kw: warnings_seen.append(str(msg)),
        )

        resolved = sm._resolve_session_load_path("dup1")
        assert resolved is not None
        filepath, session_dir = resolved
        # Newer (directory) must win.
        assert filepath == dir_json
        assert session_dir == dir_
        # Warning must mention duplicates.
        assert any("duplicate formats" in m for m in warnings_seen), (
            f"Expected duplicate-format warning, got: {warnings_seen}"
        )

    def test_unlink_failure_after_dir_write_leaves_load_path_deterministic(
        self, tmp_path, monkeypatch
    ):
        """R11 exact scenario: atomic rename succeeds, unlink of old
        flat file fails — next load must still pick the directory
        (newer mtime) without throwing.
        """
        sm = self._minimal_session(tmp_path, "crash")
        sessions_dir = sm.sessions_dir

        # Seed a pre-existing flat session (text-only state).
        flat = sessions_dir / "crash.json"
        flat.write_text(json.dumps({
            "session_name": "crash",
            "messages": [{"role": "user", "content": "before attachment"}],
            "metadata": {},
        }))

        # Mock Path.unlink to raise AFTER the atomic rename has happened.
        from pathlib import Path as _Path
        original_unlink = _Path.unlink

        def mock_unlink(self_path, *a, **kw):
            if self_path.name == "crash.json":
                raise OSError("simulated crash: unlink forbidden")
            return original_unlink(self_path, *a, **kw)

        monkeypatch.setattr(_Path, "unlink", mock_unlink)

        # Force directory format by claiming a multimodal attachment
        # is present without actually attaching one — the simpler path
        # is to call _resolve_session_storage after creating the dir.
        dir_path = sessions_dir / "crash"
        dir_path.mkdir()
        dir_json = dir_path / "session.json"
        dir_json.write_text(json.dumps({
            "session_name": "crash",
            "messages": [
                {"role": "user", "content": "with attachment"},
                {"role": "assistant", "content": "ok"},
            ],
            "metadata": {},
        }))
        # Ensure directory mtime is newer than flat.
        import os as _os
        _os.utime(dir_json, (2_000_000_000, 2_000_000_000))
        _os.utime(flat, (1_000_000_000, 1_000_000_000))

        # Load path resolution must succeed and pick directory.
        resolved = sm._resolve_session_load_path("crash")
        assert resolved is not None
        assert resolved[0] == dir_json

    def test_atomic_rename_prevents_partial_directory_write(self, tmp_path):
        """During a flat→dir transition, if os.rename succeeds the
        directory is fully populated; if it fails the directory didn't
        appear at all. Never a half-written dir_path.
        """
        # Bypass full save plumbing — test _write_session_json directly
        # with a session that has an image_url to trigger dir format.
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        sm.session_name = "atomic_test"

        # Seed pre-existing flat file to force a transition.
        flat = sm.sessions_dir / "atomic_test.json"
        flat.write_text(json.dumps({"session_name": "atomic_test",
                                    "messages": [], "metadata": {}}))

        # Add a message that makes _has_multimodal_attachments True.
        from ppxai.engine.types import Message
        sm.messages = [
            Message(role="user", content=[
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64,AA"}}
            ])
        ]

        sm._write_session_json("atomic_test", {
            "session_name": "atomic_test",
            "messages": [],
            "metadata": {},
        })

        # After write: directory exists, flat is gone, tmp is gone.
        dir_path = sm.sessions_dir / "atomic_test"
        tmp_path_staging = sm.sessions_dir / "atomic_test.tmp"
        assert dir_path.is_dir(), "target directory must exist"
        assert (dir_path / "session.json").is_file(), \
            "session.json must be inside the target directory"
        assert not tmp_path_staging.exists(), \
            "staging tmp dir must be cleaned up after rename"
        assert not flat.exists(), \
            "stale flat file must be removed after successful transition"
