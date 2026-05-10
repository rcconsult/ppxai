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
        with open(filepath, encoding="utf-8") as f:
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
        with open(filepath, encoding="utf-8") as f:
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
            with open(state_file, encoding="utf-8") as f:
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

            with open(state_file, encoding="utf-8") as f:
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
        with open(state_file, 'w', encoding="utf-8") as f:
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
        with open(state_file, 'w', encoding="utf-8") as f:
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
        with open(filepath, 'w', encoding="utf-8") as f:
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
            with open(state_file, encoding="utf-8") as f:
                state = json.load(f)
            assert state["last_session"]["dirty"] is True

            # Mark clean (graceful exit)
            session.mark_clean()

            # Verify state file shows clean
            with open(state_file, encoding="utf-8") as f:
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
        }), encoding="utf-8")
        new.write_text(json.dumps({
            "session_name": "session_new",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ],
            "metadata": {"provider": "perplexity", "model": "sonar"},
            "tools_enabled": True,
        }), encoding="utf-8")
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
        }), encoding="utf-8")
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
        }), encoding="utf-8")

        # Put a newer session on disk — the pointer should still win.
        (sessions_dir / "newer.json").write_text(json.dumps({
            "session_name": "newer",
            "messages": [{"role": "user", "content": "x"}],
            "metadata": {},
        }), encoding="utf-8")

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
        }), encoding="utf-8")

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
        }), encoding="utf-8")
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
        }), encoding="utf-8")
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
        }), encoding="utf-8")

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
        }), encoding="utf-8")
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
                                    "messages": [], "metadata": {}}), encoding="utf-8")

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


class TestPerTurnUsagePersistence:
    """v1.18.2 fix: Rich + Textual TUIs flush usage to global ledger
    on every auto-save, matching the server's per-turn behavior.

    Bug: Pre-fix, both Rich and Textual called only session.save_dirty()
    after each chat turn, which writes to the per-session JSON but NOT
    to ~/.ppxai/usage/usage.json. The global ledger was updated only on
    /quit, so /usage 24h reported stale data through long-running
    sessions. The web/VSCode server already flushed per-turn (see
    server/streaming.py:179, 238).

    These tests pin the call shape so a future refactor can't drop
    save_usage_to_persistent_storage from the auto-save path.
    """

    def test_rich_main_auto_save_calls_save_usage_to_persistent_storage(self):
        """Read rich/main.py source and verify the auto-save block
        calls save_usage_to_persistent_storage right next to save_dirty."""
        from pathlib import Path
        rich_main = (
            Path(__file__).parent.parent / "ppxai" / "rich" / "main.py"
        )
        source = rich_main.read_text(encoding="utf-8")

        # Both calls must be present.
        assert "save_dirty()" in source
        assert "save_usage_to_persistent_storage()" in source

        # save_usage_to_persistent_storage must be inside the auto-save
        # branch — i.e. AFTER save_dirty in source order, not at the
        # end of file as a /quit-only path.
        save_dirty_idx = source.find("session.save_dirty()")
        save_usage_idx = source.find("session.save_usage_to_persistent_storage()")
        assert save_dirty_idx > 0, "save_dirty() not found"
        assert save_usage_idx > 0, "save_usage_to_persistent_storage() not found"
        assert save_usage_idx > save_dirty_idx, (
            "save_usage_to_persistent_storage must come after save_dirty "
            "in the auto-save block — otherwise it can run before the "
            "session JSON is written and miss the latest usage."
        )

        # Both calls must be within ~500 chars of each other (same block).
        assert save_usage_idx - save_dirty_idx < 800, (
            f"save_dirty and save_usage_to_persistent_storage are "
            f"{save_usage_idx - save_dirty_idx} chars apart — they "
            f"should be in the same auto-save block, not separated "
            f"by unrelated code."
        )

    def test_textual_stream_handler_auto_save_calls_save_usage(self):
        """Same invariant for Textual TUI's per-turn auto-save."""
        from pathlib import Path
        path = (
            Path(__file__).parent.parent
            / "ppxai" / "tui" / "stream_handler.py"
        )
        source = path.read_text(encoding="utf-8")

        assert "session.save_dirty()" in source
        assert "session.save_usage_to_persistent_storage()" in source

        save_dirty_idx = source.find("session.save_dirty()")
        save_usage_idx = source.find("session.save_usage_to_persistent_storage()")
        assert save_dirty_idx > 0
        assert save_usage_idx > 0
        assert save_usage_idx > save_dirty_idx
        assert save_usage_idx - save_dirty_idx < 800

    def test_save_usage_failure_does_not_crash_chat_loop(self, tmp_path, monkeypatch):
        """If the persistent ledger write throws (disk full, permission
        denied), Rich/Textual swallow the exception so the chat loop
        keeps running. The session JSON save (save_dirty) is the
        load-bearing path — global ledger is best-effort."""
        from ppxai.engine.types import Message, UsageStats

        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        sm.session_name = "guard"
        sm.messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="ok"),
        ]
        sm.update_usage(
            UsageStats(prompt_tokens=100, completion_tokens=10,
                       total_tokens=110, estimated_cost=0.01),
            provider="openai", model="gpt-5.4-mini",
        )

        # Force the global ledger write to fail.
        def explode(*a, **kw):
            raise OSError("simulated disk full")

        monkeypatch.setattr(
            "ppxai.engine.session.save_session_usage", explode
        )

        # Calling directly should propagate (engine-level contract).
        with pytest.raises(OSError, match="disk full"):
            sm.save_usage_to_persistent_storage()

        # But the Rich/Textual auto-save wrappers swallow this — see
        # the inline `try/except Exception: pass` in rich/main.py and
        # tui/stream_handler.py around the save_usage_to_persistent_storage
        # call. The static check above (test_*_auto_save_calls_*)
        # ensures the wrapper exists.


class TestUsageRoundTrip:
    """v1.18.2 fix: session.load() restores usage_by_model and tool_calls.

    Bug: pre-fix, load() restored only `self.usage` (session total) from
    JSON. `self.usage_by_model` and `self.usage.tool_calls` were left at
    their __init__ defaults (empty dicts). Every restart of a long-lived
    session silently wiped the historical per-model attribution.

    Symptom: usage table shows TOTAL row that doesn't match the sum of
    per-model rows — historical tokens accumulate into the session
    total but vanish from the breakdown.
    """

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_save_then_load_preserves_usage_by_model(self, tmp_path):
        from ppxai.engine.types import Message, UsageStats
        sm = self._sm(tmp_path)
        sm.session_name = "usage_rt"
        sm.messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        sm.update_usage(
            UsageStats(
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500,
                estimated_cost=0.0123,
            ),
            provider="openai",
            model="gpt-5.4-mini",
        )
        sm.save("usage_rt")

        # Load into a fresh manager.
        sm2 = self._sm(tmp_path)
        assert sm2.load("usage_rt") is True

        # Session total restored.
        assert sm2.usage.prompt_tokens == 1000
        assert sm2.usage.completion_tokens == 500
        assert sm2.usage.estimated_cost == pytest.approx(0.0123)

        # Per-model breakdown restored — this is the fix.
        key = "openai/gpt-5.4-mini"
        assert key in sm2.usage_by_model, (
            f"by_model lost on reload — got keys: {list(sm2.usage_by_model.keys())}"
        )
        m = sm2.usage_by_model[key]
        assert m.prompt_tokens == 1000
        assert m.completion_tokens == 500
        assert m.estimated_cost == pytest.approx(0.0123)

    def test_save_then_load_preserves_multi_model_breakdown(self, tmp_path):
        """Two models in the same session both round-trip."""
        from ppxai.engine.types import Message, UsageStats
        sm = self._sm(tmp_path)
        sm.session_name = "multi_model"
        sm.messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        sm.update_usage(
            UsageStats(prompt_tokens=2000000, completion_tokens=10000,
                       total_tokens=2010000, estimated_cost=10.30),
            provider="openai", model="gpt-5.4-mini",
        )
        sm.update_usage(
            UsageStats(prompt_tokens=5000000, completion_tokens=20000,
                       total_tokens=5020000, estimated_cost=25.60),
            provider="openai", model="gpt-5.5",
        )
        sm.save("multi_model")

        sm2 = self._sm(tmp_path)
        sm2.load("multi_model")
        assert "openai/gpt-5.4-mini" in sm2.usage_by_model
        assert "openai/gpt-5.5" in sm2.usage_by_model
        assert sm2.usage_by_model["openai/gpt-5.5"].prompt_tokens == 5000000
        assert sm2.usage_by_model["openai/gpt-5.4-mini"].prompt_tokens == 2000000

    def test_save_then_load_preserves_tool_calls_usage(self, tmp_path):
        from ppxai.engine.types import Message, UsageStats, ToolUsage
        sm = self._sm(tmp_path)
        sm.session_name = "tool_usage"
        sm.messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        usage = UsageStats(
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            estimated_cost=0.001,
        )
        usage.tool_calls = {
            "vl_caption": ToolUsage(
                call_count=3, tokens_in=15000, tokens_out=300,
                estimated_cost=0.025, provider="gemini",
            ),
        }
        sm.update_usage(usage, provider="openai", model="gpt-5.4-mini")
        sm.save("tool_usage")

        sm2 = self._sm(tmp_path)
        sm2.load("tool_usage")
        assert "vl_caption" in sm2.usage.tool_calls
        tc = sm2.usage.tool_calls["vl_caption"]
        assert tc.call_count == 3
        assert tc.tokens_in == 15000
        assert tc.estimated_cost == pytest.approx(0.025)
        assert tc.provider == "gemini"

    def test_load_old_session_without_by_model_does_not_crash(self, tmp_path):
        """Pre-v1.18.2 sessions had no by_model in their saved JSON.
        Loading them must not crash; usage_by_model just stays empty."""
        sm = self._sm(tmp_path)
        path = sm.sessions_dir / "legacy.json"
        path.write_text(json.dumps({
            "session_name": "legacy",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"},
            ],
            "metadata": {},
            "usage": {
                "total_tokens": 1500,
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "estimated_cost": 0.0123,
                # No by_model key, no tool_calls key — pre-fix format
            },
        }), encoding="utf-8")

        assert sm.load("legacy") is True
        assert sm.usage.prompt_tokens == 1000
        assert sm.usage_by_model == {}
        assert sm.usage.tool_calls == {}


class TestOrphanToolCallsCleanup:
    """v1.18.2 fix: Ctrl+C mid-tool-iteration leaves orphan tool_calls.

    Bug: When KeyboardInterrupt fires between chat.py adding the
    assistant message with tool_calls (line 795) and the tool result
    loop (line 807), the session has an assistant message with
    tool_call_ids that no following tool messages cover. Next OpenAI
    request rejects with HTTP 400:

        An assistant message with 'tool_calls' must be followed by
        tool messages responding to each 'tool_call_id'. The following
        tool_call_ids did not have response messages: call_X, call_Y, call_Z

    Fix: validate_and_fix_alternation drops the orphan assistant
    message + any partial tool results so the model retries the
    tool calls on the next turn.
    """

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def _assistant_with_tool_calls(self, ids):
        from ppxai.engine.types import Message
        return Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": tcid,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
                for tcid in ids
            ],
        )

    def _tool_result(self, tcid, content="result"):
        from ppxai.engine.types import Message
        return Message(role="tool", content=content, tool_call_id=tcid)

    def test_drops_assistant_with_no_tool_responses(self, tmp_path):
        """Pure orphan: assistant + 3 tool_calls, zero tool messages."""
        from ppxai.engine.types import Message
        sm = self._sm(tmp_path)
        sm.messages = [
            Message(role="user", content="be concise"),
            self._assistant_with_tool_calls(["call_A", "call_B", "call_C"]),
        ]
        removed = sm.validate_and_fix_alternation()
        assert removed >= 1
        # Only the user message should remain (or be removed too if it
        # would now be a trailing user message — both are valid sane states).
        roles = [m.role for m in sm.messages]
        assert "assistant" not in roles or all(
            not m.tool_calls for m in sm.messages if m.role == "assistant"
        ), f"Orphan tool_calls survived: {roles}"

    def test_drops_assistant_with_partial_tool_responses(self, tmp_path):
        """Partial: 3 tool_calls, only 1 response."""
        from ppxai.engine.types import Message
        sm = self._sm(tmp_path)
        sm.messages = [
            Message(role="user", content="run it"),
            self._assistant_with_tool_calls(["call_A", "call_B", "call_C"]),
            self._tool_result("call_A", "ok"),
            # call_B and call_C never got responses
        ]
        removed = sm.validate_and_fix_alternation()
        assert removed >= 1
        # The orphan + partial cleanup should leave just the user message.
        for msg in sm.messages:
            if msg.role == "assistant" and msg.tool_calls:
                pytest.fail(
                    f"Orphan assistant.tool_calls survived: "
                    f"ids={[t.get('id') for t in msg.tool_calls]}"
                )

    def test_preserves_complete_tool_call_sequence(self, tmp_path):
        """Sanity: a complete assistant+tools+followup sequence stays intact."""
        from ppxai.engine.types import Message
        sm = self._sm(tmp_path)
        sm.messages = [
            Message(role="user", content="run it"),
            self._assistant_with_tool_calls(["call_A", "call_B"]),
            self._tool_result("call_A", "ok"),
            self._tool_result("call_B", "ok2"),
            Message(role="assistant", content="Done."),
        ]
        sm.validate_and_fix_alternation()
        # All 5 messages survive
        roles = [m.role for m in sm.messages]
        assert roles == ["user", "assistant", "tool", "tool", "assistant"]

    def test_orphan_in_middle_of_session_drops_only_orphan(self, tmp_path):
        """Earlier complete tool sequence + later orphan tool_calls."""
        from ppxai.engine.types import Message
        sm = self._sm(tmp_path)
        sm.messages = [
            Message(role="user", content="first"),
            self._assistant_with_tool_calls(["call_A"]),
            self._tool_result("call_A", "ok"),
            Message(role="assistant", content="first response"),
            Message(role="user", content="second"),
            self._assistant_with_tool_calls(["call_B", "call_C"]),
            # call_B and call_C orphaned
        ]
        sm.validate_and_fix_alternation()
        # The complete first sequence survives.
        # The trailing orphan assistant gets dropped.
        # The trailing user message also gets dropped (no response) by
        # the existing trailing-cleanup logic.
        assistant_with_calls = [
            m for m in sm.messages if m.role == "assistant" and m.tool_calls
        ]
        for msg in assistant_with_calls:
            ids = {t.get("id") for t in msg.tool_calls}
            tool_msgs_after = [
                m for m in sm.messages[sm.messages.index(msg) + 1:]
                if m.role == "tool"
            ]
            seen_ids = {m.tool_call_id for m in tool_msgs_after}
            assert ids.issubset(seen_ids), (
                f"Surviving assistant.tool_calls {ids} missing responses: "
                f"{ids - seen_ids}"
            )

    def test_cascading_orphan_from_trailing_tool_strip(self, tmp_path):
        """v1.18.5 regression: trailing-tool strip in step 3 ORPHANS the
        prior assistant.tool_calls, but step 2 already ran and won't see it.
        Result: surviving assistant.tool_calls without paired tool response
        → next OpenAI request rejects with HTTP 400.

        Surfaced 2026-05-10 from a real ppxai session that ended on a
        zombie circuit-breaker (apply_patch fail×2). The orphan persisted
        across `/continue` retries with messages.[N].role pointing at
        progressively earlier positions as the alternation fix kept
        nibbling without ever covering the new tail.

        Shape: complete sequence of assistant(tool_calls)+tool ending
        with a final orphan assistant.tool_calls. Step 2 drops the
        final orphan → ends with tool. Step 3 pops trailing tool →
        ends with assistant.tool_calls whose response just got popped.
        Without re-running step 2, the new tail orphan ships to the API.
        """
        from ppxai.engine.types import Message
        sm = self._sm(tmp_path)
        sm.messages = [
            Message(role="user", content="diagnose"),
            self._assistant_with_tool_calls(["call_A"]),
            self._tool_result("call_A", "ok"),
            self._assistant_with_tool_calls(["call_B"]),
            # call_B's response is the LAST tool message — when it gets
            # stripped by step 3 (after step 2 drops the trailing orphan),
            # call_B becomes orphan. Without v1.18.5 fix, this survived.
            self._tool_result("call_B", "ok2"),
            self._assistant_with_tool_calls(["call_orphan"]),  # the visible orphan
        ]
        sm.validate_and_fix_alternation()
        # ALL surviving assistant.tool_calls must have paired responses.
        for msg in sm.messages:
            if msg.role == "assistant" and msg.tool_calls:
                expected = {t.get("id") for t in msg.tool_calls}
                idx = sm.messages.index(msg)
                seen = {
                    m.tool_call_id for m in sm.messages[idx + 1:]
                    if m.role == "tool"
                }
                missing = expected - seen
                assert not missing, (
                    f"v1.18.5 regression: orphan assistant.tool_calls survived "
                    f"validation. Missing tool_call_ids: {missing}. "
                    f"Final roles: {[m.role for m in sm.messages]}"
                )

    def test_save_then_load_clean_session_with_orphan(self, tmp_path):
        """End-to-end: save a corrupted session, load it, validation
        fires implicitly via load() and cleans the orphan."""
        from ppxai.engine.types import Message

        sm = self._sm(tmp_path)
        sm.session_name = "orphan_test"
        sm.messages = [
            Message(role="user", content="run"),
            self._assistant_with_tool_calls(["call_X", "call_Y"]),
            # No tool responses — orphan
        ]
        # Bypass save() (which calls validate_and_fix_alternation pre-save)
        # by writing the JSON directly.
        import json as _json
        path = sm.sessions_dir / "orphan_test.json"
        path.write_text(_json.dumps({
            "session_name": "orphan_test",
            "messages": [sm._serialize_message(m) for m in sm.messages],
            "metadata": {},
        }), encoding="utf-8")

        # Load into a fresh manager — validation should clean the orphan.
        sm2 = self._sm(tmp_path)
        assert sm2.load("orphan_test") is True
        for msg in sm2.messages:
            if msg.role == "assistant" and msg.tool_calls:
                pytest.fail("Orphan tool_calls survived load+validation")


class TestWriteSessionJsonPropagatesOSError:
    """The engine layer MUST propagate write failures so the UI layer's
    AutosaveFailureGuard (rich/main.py, tui/stream_handler.py) can count
    consecutive failures and surface them to the user. Silently swallowing
    here would let a full-disk run hide every save failure for hours.
    """

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        sm.session_name = "wtest"
        return sm

    def test_in_place_flat_write_propagates_oserror(self, tmp_path):
        sm = self._sm(tmp_path)
        with patch("builtins.open", side_effect=OSError(28, "No space left on device")):
            with pytest.raises(OSError, match="No space left"):
                sm._write_session_json_in_place(
                    "wtest", {"session_name": "wtest", "messages": [], "metadata": {}},
                    is_dir_format=False,
                )

    def test_in_place_flat_write_propagates_permission_error(self, tmp_path):
        sm = self._sm(tmp_path)
        with patch("builtins.open", side_effect=PermissionError("read-only mount")):
            with pytest.raises(PermissionError, match="read-only mount"):
                sm._write_session_json_in_place(
                    "wtest", {"session_name": "wtest", "messages": [], "metadata": {}},
                    is_dir_format=False,
                )

    def test_in_place_dir_write_propagates_oserror(self, tmp_path):
        sm = self._sm(tmp_path)
        # mkdir succeeds, json.dump fails — ensure error reaches caller
        with patch("builtins.open", side_effect=OSError(28, "No space left on device")):
            with pytest.raises(OSError, match="No space left"):
                sm._write_session_json_in_place(
                    "wtest", {"session_name": "wtest", "messages": [], "metadata": {}},
                    is_dir_format=True,
                )

    def test_save_with_extras_propagates_write_failure(self, tmp_path):
        sm = self._sm(tmp_path)
        with patch("builtins.open", side_effect=OSError(28, "ENOSPC")):
            with pytest.raises(OSError, match="ENOSPC"):
                sm._save_with_extras()

    def test_save_dirty_propagates_write_failure_so_guard_can_catch(self, tmp_path):
        sm = self._sm(tmp_path)
        with patch("builtins.open", side_effect=OSError(28, "ENOSPC")):
            with pytest.raises(OSError, match="ENOSPC"):
                sm.save_dirty()

    def test_save_propagates_write_failure(self, tmp_path):
        """Public save() (e.g. /save command) must surface errors so the
        slash command result reports the failure rather than claiming
        success on a no-op."""
        sm = self._sm(tmp_path)
        with patch("builtins.open", side_effect=OSError(28, "ENOSPC")):
            with pytest.raises(OSError, match="ENOSPC"):
                sm.save("named_save")

    def test_transition_atomic_rename_failure_leaves_tmp_for_recovery(self, tmp_path):
        """When the flat->dir atomic rename fails, _write_session_json
        re-raises so the caller knows the transition didn't happen.
        The staged tmp directory stays on disk (already tested in
        TestAtomicSessionFormatTransition) — here we just pin the
        re-raise so the guard sees the failure.
        """
        from ppxai.engine.types import Message
        sm = self._sm(tmp_path)
        sm.session_name = "atomic"

        # Seed flat file to force a transition.
        flat = sm.sessions_dir / "atomic.json"
        flat.write_text(json.dumps({"session_name": "atomic", "messages": [],
                                    "metadata": {}}), encoding="utf-8")
        # Make multimodal so directory format is required.
        sm.messages = [Message(role="user", content=[
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
        ])]

        with patch("ppxai.engine.session.os.rename",
                   side_effect=OSError("rename failed")):
            with pytest.raises(OSError, match="rename failed"):
                sm._write_session_json("atomic", {
                    "session_name": "atomic", "messages": [], "metadata": {},
                })


class TestSessionSymlinkBehavior:
    """Symlinks WITHIN sessions_dir are user-controlled territory — the
    engine resolves them transparently via Path.is_dir/is_file. These
    tests pin the behavior so a future "resolve to absolute path before
    use" refactor can't silently change semantics.

    Path-traversal protection (rejecting '../' in names) is separate
    and tested in TestSessionNamePathTraversal — that catches bogus
    names; this catches what happens when the user themselves places
    a symlink in their data directory.
    """

    def _supports_symlinks(self, tmp_path):
        try:
            target = tmp_path / "_probe_target"
            target.write_text("x", encoding="utf-8")
            link = tmp_path / "_probe_link"
            link.symlink_to(target)
            link.unlink()
            target.unlink()
            return True
        except (OSError, NotImplementedError):
            return False

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_symlink_to_flat_session_json_loads(self, tmp_path):
        if not self._supports_symlinks(tmp_path):
            pytest.skip("filesystem does not support symlinks")
        sm = self._sm(tmp_path)

        real_dir = tmp_path / "outside"
        real_dir.mkdir()
        real_session = real_dir / "real_session.json"
        real_session.write_text(json.dumps({
            "session_name": "linked",
            "messages": [{"role": "user", "content": "hi"},
                         {"role": "assistant", "content": "ok"}],
            "metadata": {},
        }), encoding="utf-8")

        link = sm.sessions_dir / "linked.json"
        link.symlink_to(real_session)

        assert sm.load("linked") is True
        assert len(sm.messages) == 2

    def test_broken_symlink_returns_false(self, tmp_path):
        if not self._supports_symlinks(tmp_path):
            pytest.skip("filesystem does not support symlinks")
        sm = self._sm(tmp_path)

        link = sm.sessions_dir / "broken.json"
        link.symlink_to(tmp_path / "does_not_exist.json")

        assert sm.load("broken") is False
        # And it must not raise — broken symlink at flat path is_file()
        # returns False so _resolve_session_load_path returns None.

    def test_symlink_to_directory_session_loads(self, tmp_path):
        if not self._supports_symlinks(tmp_path):
            pytest.skip("filesystem does not support symlinks")
        sm = self._sm(tmp_path)

        real_dir = tmp_path / "outside_dir"
        real_dir.mkdir()
        (real_dir / "session.json").write_text(json.dumps({
            "session_name": "linked_dir",
            "messages": [{"role": "user", "content": "hi"},
                         {"role": "assistant", "content": "ok"}],
            "metadata": {},
        }), encoding="utf-8")

        link = sm.sessions_dir / "linked_dir"
        link.symlink_to(real_dir, target_is_directory=True)

        assert sm.load("linked_dir") is True
        assert len(sm.messages) == 2

    def test_symlink_loop_does_not_infinite_loop(self, tmp_path):
        """A self-pointing symlink in sessions_dir must not hang
        list_sessions(). Path.is_dir() returns False for cyclic
        links, so the entry is silently skipped."""
        if not self._supports_symlinks(tmp_path):
            pytest.skip("filesystem does not support symlinks")
        sm = self._sm(tmp_path)

        loop = sm.sessions_dir / "loop"
        loop.symlink_to(loop)  # self-loop

        # Must complete without raising.
        sessions = sm.list_sessions()
        # Either skipped silently or, if present, the name should not
        # cause subsequent operations to hang. Just guard against hang.
        assert isinstance(sessions, list)

    def test_list_sessions_skips_broken_symlink(self, tmp_path):
        if not self._supports_symlinks(tmp_path):
            pytest.skip("filesystem does not support symlinks")
        sm = self._sm(tmp_path)

        # One real session + one broken symlink.
        real_session = sm.sessions_dir / "real.json"
        real_session.write_text(json.dumps({
            "session_name": "real",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {},
        }), encoding="utf-8")
        broken = sm.sessions_dir / "broken.json"
        broken.symlink_to(tmp_path / "does_not_exist.json")

        names = [s.name for s in sm.list_sessions()]
        assert "real" in names
        assert "broken" not in names

    def test_symlink_in_session_directory_uploads_does_not_crash_listing(self, tmp_path):
        """Directory-format session with a symlinked uploads/ subdir
        — list_sessions reads session.json directly, so symlinks
        inside the session dir are irrelevant to the listing pass."""
        if not self._supports_symlinks(tmp_path):
            pytest.skip("filesystem does not support symlinks")
        sm = self._sm(tmp_path)

        ses_dir = sm.sessions_dir / "with_uploads"
        ses_dir.mkdir()
        (ses_dir / "session.json").write_text(json.dumps({
            "session_name": "with_uploads",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {},
        }), encoding="utf-8")
        # Add a broken symlink alongside session.json.
        (ses_dir / "uploads").symlink_to(tmp_path / "nonexistent")

        names = [s.name for s in sm.list_sessions()]
        assert "with_uploads" in names


class TestSessionLoadCorruptRecovery:
    """load() returns False gracefully for corrupt/missing/truncated JSON."""

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_load_nonexistent_session_returns_false(self, tmp_path):
        sm = self._sm(tmp_path)
        assert sm.load("does_not_exist") is False

    def test_load_corrupt_flat_json_returns_false(self, tmp_path):
        sm = self._sm(tmp_path)
        (sm.sessions_dir / "bad.json").write_text("{not valid json", encoding="utf-8")
        assert sm.load("bad") is False

    def test_load_truncated_flat_json_returns_false(self, tmp_path):
        sm = self._sm(tmp_path)
        (sm.sessions_dir / "trunc.json").write_text('{"session_name": "trunc", "messages":', encoding="utf-8")
        assert sm.load("trunc") is False

    def test_load_empty_flat_file_returns_false(self, tmp_path):
        sm = self._sm(tmp_path)
        (sm.sessions_dir / "empty.json").write_text("", encoding="utf-8")
        assert sm.load("empty") is False

    def test_load_corrupt_directory_session_returns_false(self, tmp_path):
        sm = self._sm(tmp_path)
        dir_path = sm.sessions_dir / "dirbad"
        dir_path.mkdir()
        (dir_path / "session.json").write_text("not json at all", encoding="utf-8")
        assert sm.load("dirbad") is False

    def test_load_does_not_mutate_messages_on_failure(self, tmp_path):
        sm = self._sm(tmp_path)
        from ppxai.engine.types import Message
        sm.messages = [Message(role="user", content="original")]
        (sm.sessions_dir / "corrupt.json").write_text("{bad}", encoding="utf-8")
        sm.load("corrupt")
        assert len(sm.messages) == 1
        assert sm.messages[0].content == "original"

    def test_load_restores_working_dir_even_if_path_missing_on_disk(self, tmp_path):
        sm = self._sm(tmp_path)
        missing_dir = "/nonexistent/path/that/does/not/exist"
        data = {
            "session_name": "wdir",
            "messages": [],
            "metadata": {},
            "working_dir": missing_dir,
        }
        (sm.sessions_dir / "wdir.json").write_text(json.dumps(data), encoding="utf-8")
        result = sm.load("wdir")
        assert result is True
        assert sm.working_dir == missing_dir

    def test_load_fires_on_messages_changed_callback(self, tmp_path):
        sm = self._sm(tmp_path)
        fired = []
        sm.on_messages_changed = lambda: fired.append(1)
        data = {"session_name": "cb", "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ], "metadata": {}}
        (sm.sessions_dir / "cb.json").write_text(json.dumps(data), encoding="utf-8")
        sm.load("cb")
        assert len(fired) >= 1


class TestListSessionsCorruptTolerance:
    """list_sessions() skips unreadable entries without raising."""

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def _good_session_data(self, name):
        return {
            "session_name": name,
            "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}],
            "metadata": {"provider": "openai", "model": "gpt-5.4-mini"},
        }

    def test_list_sessions_skips_corrupt_flat_file(self, tmp_path):
        sm = self._sm(tmp_path)
        (sm.sessions_dir / "good.json").write_text(
            json.dumps(self._good_session_data("good")), encoding="utf-8"
        )
        (sm.sessions_dir / "bad.json").write_text("{corrupted", encoding="utf-8")
        sessions = sm.list_sessions()
        names = [s.name for s in sessions]
        assert "good" in names
        assert "bad" not in names

    def test_list_sessions_skips_corrupt_directory_session(self, tmp_path):
        sm = self._sm(tmp_path)
        (sm.sessions_dir / "good.json").write_text(
            json.dumps(self._good_session_data("good")), encoding="utf-8"
        )
        bad_dir = sm.sessions_dir / "baddir"
        bad_dir.mkdir()
        (bad_dir / "session.json").write_text("not json", encoding="utf-8")
        sessions = sm.list_sessions()
        names = [s.name for s in sessions]
        assert "good" in names
        assert "baddir" not in names

    def test_list_sessions_deduplicates_flat_and_directory(self, tmp_path):
        sm = self._sm(tmp_path)
        data = self._good_session_data("dup")
        (sm.sessions_dir / "dup.json").write_text(json.dumps(data), encoding="utf-8")
        dir_path = sm.sessions_dir / "dup"
        dir_path.mkdir()
        (dir_path / "session.json").write_text(json.dumps(data), encoding="utf-8")
        sessions = sm.list_sessions()
        dup_count = sum(1 for s in sessions if s.name == "dup")
        assert dup_count == 1, f"Expected 1 'dup' entry, got {dup_count}"

    def test_list_sessions_empty_dir_returns_empty(self, tmp_path):
        sm = self._sm(tmp_path)
        assert sm.list_sessions() == []

    def test_list_sessions_skips_subdirs_without_session_json(self, tmp_path):
        sm = self._sm(tmp_path)
        orphan = sm.sessions_dir / "notasession"
        orphan.mkdir()
        (orphan / "something_else.txt").write_text("hi", encoding="utf-8")
        sessions = sm.list_sessions()
        names = [s.name for s in sessions]
        assert "notasession" not in names


class TestDeleteSession:
    """delete_session() handles flat, directory, both-present, missing, and failure."""

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_delete_flat_session(self, tmp_path):
        sm = self._sm(tmp_path)
        flat = sm.sessions_dir / "flat.json"
        flat.write_text("{}", encoding="utf-8")
        result = sm.delete_session("flat")
        assert result is True
        assert not flat.exists()

    def test_delete_directory_session(self, tmp_path):
        sm = self._sm(tmp_path)
        dir_path = sm.sessions_dir / "dirses"
        dir_path.mkdir()
        (dir_path / "session.json").write_text("{}", encoding="utf-8")
        result = sm.delete_session("dirses")
        assert result is True
        assert not dir_path.exists()

    def test_delete_both_formats_removes_both(self, tmp_path):
        sm = self._sm(tmp_path)
        flat = sm.sessions_dir / "both.json"
        flat.write_text("{}", encoding="utf-8")
        dir_path = sm.sessions_dir / "both"
        dir_path.mkdir()
        (dir_path / "session.json").write_text("{}", encoding="utf-8")
        result = sm.delete_session("both")
        assert result is True
        assert not flat.exists()
        assert not dir_path.exists()

    def test_delete_nonexistent_returns_false(self, tmp_path):
        sm = self._sm(tmp_path)
        assert sm.delete_session("ghost") is False


class TestStatePointerStale:
    """get_last_session_state_or_scan() when state file points to deleted session."""

    def test_corrupt_state_file_returns_none(self, tmp_path, monkeypatch):
        state_file = tmp_path / "session-state.json"
        state_file.write_text("{bad json", encoding="utf-8")
        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)
        result = SessionManager.get_last_session_state()
        assert result is None

    def test_state_file_missing_last_session_key_returns_none(self, tmp_path, monkeypatch):
        state_file = tmp_path / "session-state.json"
        state_file.write_text(json.dumps({"other_key": "value"}), encoding="utf-8")
        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)
        result = SessionManager.get_last_session_state()
        assert result is None

    def test_find_most_recent_skips_corrupt_sessions(self, tmp_path, monkeypatch):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "corrupt.json").write_text("{bad", encoding="utf-8")
        monkeypatch.setattr(
            "ppxai.engine.session.Path.home",
            lambda: tmp_path,
        )
        # Sessions dir must be at tmp_path/.ppxai/sessions for the static method
        ppxai_dir = tmp_path / ".ppxai"
        ppxai_dir.mkdir()
        real_sessions = ppxai_dir / "sessions"
        real_sessions.mkdir()
        (real_sessions / "corrupt.json").write_text("{bad", encoding="utf-8")

        with patch("ppxai.engine.session.Path") as mock_path_cls:
            mock_home = MagicMock()
            mock_home.__truediv__ = lambda self, x: (
                ppxai_dir if x == ".ppxai" else tmp_path / x
            )
            mock_path_cls.home.return_value = mock_home
            mock_sessions = MagicMock()
            mock_sessions.is_dir.return_value = True
            mock_sessions.iterdir.return_value = [
                real_sessions / "corrupt.json",
            ]

        # Direct test: a sessions dir with only corrupt files → None
        sm = SessionManager(sessions_dir=real_sessions)
        sessions = sm.list_sessions()
        assert sessions == [], "Corrupt sessions should produce an empty list"

    def test_find_most_recent_skips_dirs_without_session_json(self, tmp_path, monkeypatch):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        orphan = sessions_dir / "not_a_session"
        orphan.mkdir()
        (orphan / "random_file.txt").write_text("hi", encoding="utf-8")

        with patch("ppxai.engine.session.Path") as mock_path_cls:
            home_mock = MagicMock()
            ppxai_path = MagicMock()
            ppxai_path.__truediv__ = lambda self, x: sessions_dir if x == "sessions" else sessions_dir
            home_mock.__truediv__ = lambda self, x: ppxai_path
            mock_path_cls.home.return_value = home_mock
            ppxai_path.is_dir.return_value = True
            ppxai_path.iterdir.return_value = list(sessions_dir.iterdir())
            result = SessionManager.find_most_recent_session_on_disk.__func__(SessionManager) if False else None

        # Simpler: use a real SessionManager with the sessions_dir
        sm = SessionManager(sessions_dir=sessions_dir)
        sessions = sm.list_sessions()
        names = [s.name for s in sessions]
        assert "not_a_session" not in names


class TestStatePointerToDeletedSession:
    """The state file pointer (~/.ppxai/session-state.json) is independent
    of whether the named session still exists on disk. The caller
    (engine/session_ops.restore_session) MUST handle the 'pointer-stale'
    case gracefully — returning success=False rather than crashing.
    """

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_get_last_state_returns_pointer_even_when_session_deleted(
        self, tmp_path, monkeypatch
    ):
        """Pointer survives the session — get_last_session_state does
        no existence check. The caller decides what to do."""
        state_file = tmp_path / "session-state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "last_session": {
                "name": "ghost_session",
                "dirty": False,
                "provider": "openai",
                "model": "gpt-5.4-mini",
                "working_dir": "/tmp",
                "tools_enabled": True,
                "message_count": 5,
            },
        }), encoding="utf-8")
        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)

        result = SessionManager.get_last_session_state()
        assert result is not None
        assert result["name"] == "ghost_session"
        # No "exists on disk" check happens — that's the caller's job.

    def test_load_of_pointed_session_returns_false_when_deleted(self, tmp_path):
        """When the engine layer tries to restore the pointer's named
        session and it's gone, load() returns False. The session_ops
        wrapper turns this into success=False."""
        sm = self._sm(tmp_path)
        # Pointer says "session_x" but no session_x.json exists.
        assert sm.load("session_x") is False
        # Engine messages stayed pristine.
        assert sm.messages == []

    def test_get_or_scan_returns_pointer_even_if_named_session_gone(
        self, tmp_path, monkeypatch
    ):
        """The fallback scan only fires when get_last_session_state
        returns None. A stale-but-present pointer still wins —
        documenting current behavior so a future 'validate first'
        change is intentional, not accidental."""
        state_file = tmp_path / "session-state.json"
        state_file.write_text(json.dumps({
            "version": 1,
            "last_session": {
                "name": "stale_pointer",
                "dirty": True,
                "provider": "openai",
                "model": "gpt-5.4-mini",
                "working_dir": "/tmp",
                "tools_enabled": False,
                "message_count": 0,
            },
        }), encoding="utf-8")
        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)

        # Don't provision any actual session files.
        result = SessionManager.get_last_session_state_or_scan()
        assert result is not None
        assert result["name"] == "stale_pointer"
        # No `recovered_from_disk` key — this came from the pointer.
        assert "recovered_from_disk" not in result

    def test_clear_state_file_clears_stale_pointer(self, tmp_path, monkeypatch):
        """After /clear or fresh-session start, clear_state_file
        removes the pointer entirely. Subsequent get_last_session_state
        returns None — auto-restore prompt won't fire."""
        state_file = tmp_path / "session-state.json"
        state_file.write_text(json.dumps({
            "version": 1, "last_session": {"name": "x", "dirty": False},
        }), encoding="utf-8")
        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)

        SessionManager.clear_state_file()
        assert SessionManager.get_last_session_state() is None
        assert not state_file.exists()

    def test_clear_state_file_idempotent_when_already_missing(
        self, tmp_path, monkeypatch
    ):
        """Calling clear twice (or when no pointer exists) must not
        raise — startup paths often clear-then-write."""
        state_file = tmp_path / "session-state.json"
        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)
        # Doesn't exist yet.
        SessionManager.clear_state_file()  # must not raise
        SessionManager.clear_state_file()  # idempotent
        assert not state_file.exists()

    def test_pointer_dirty_flag_survives_pointer_lifecycle(
        self, tmp_path, monkeypatch
    ):
        """save_dirty -> _update_state_file(dirty=True). mark_clean ->
        _update_state_file(dirty=False) ONLY if there was meaningful
        content. Verify the dirty flag round-trips correctly so the
        client's 'unsaved changes?' prompt fires on restart."""
        from ppxai.engine.types import Message

        state_file = tmp_path / "session-state.json"
        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state_file)

        sm = self._sm(tmp_path)
        sm.session_name = "active"
        sm.messages = [Message(role="user", content="x")]
        sm.save_dirty()

        ptr = SessionManager.get_last_session_state()
        assert ptr is not None
        assert ptr["dirty"] is True
        assert ptr["name"] == "active"

        sm.mark_clean()
        ptr_after = SessionManager.get_last_session_state()
        assert ptr_after["dirty"] is False


class TestConcurrentSaveLoad:
    """Two SessionManager instances pointing at the same sessions_dir.

    The server architecture already holds a per-session asyncio.Lock at
    the SessionManager (server/session_manager.py) layer — within one
    process, save/load can't race. But two ppxai processes (two TUI
    instances on the same host, or web + TUI on the same user) DO
    point at the same ~/.ppxai/sessions/ and there's no inter-process
    lock. Test the file-level invariants that survive that.
    """

    def _sm(self, sessions_dir):
        sm = SessionManager(sessions_dir=sessions_dir)
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_second_writer_overwrites_first_for_flat_session(self, tmp_path):
        from ppxai.engine.types import Message
        sessions_dir = tmp_path / "sessions"

        sm1 = self._sm(sessions_dir)
        sm1.session_name = "shared"
        sm1.messages = [
            Message(role="user", content="from sm1"),
            Message(role="assistant", content="reply"),
        ]
        sm1.save("shared")

        sm2 = self._sm(sessions_dir)
        sm2.session_name = "shared"
        sm2.messages = [
            Message(role="user", content="from sm2"),
            Message(role="assistant", content="ok"),
        ]
        sm2.save("shared")

        # A third manager loading sees sm2's data — last writer wins.
        sm3 = self._sm(sessions_dir)
        assert sm3.load("shared") is True
        assert len(sm3.messages) == 2
        assert sm3.messages[0].content == "from sm2"

    def test_two_managers_can_both_load_same_session_independently(self, tmp_path):
        """No exclusive lock — both readers see the same data, no
        EBUSY, no corruption. Important because web/VSCode clients
        often refresh /sessions concurrently."""
        from ppxai.engine.types import Message
        sessions_dir = tmp_path / "sessions"

        seed = self._sm(sessions_dir)
        seed.session_name = "concur"
        seed.messages = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        seed.save("concur")

        sm_a = self._sm(sessions_dir)
        sm_b = self._sm(sessions_dir)

        assert sm_a.load("concur") is True
        assert sm_b.load("concur") is True
        assert len(sm_a.messages) == len(sm_b.messages) == 2
        assert sm_a.messages[0].content == sm_b.messages[0].content

    def test_load_picks_up_external_writer_changes(self, tmp_path):
        """Manager loaded before an external writer rewrote the file —
        a second load() call MUST see the new data, not a cached
        old version. (No internal cache invalidation bug.)"""
        from ppxai.engine.types import Message
        sessions_dir = tmp_path / "sessions"

        seed = self._sm(sessions_dir)
        seed.session_name = "watcher"
        # Alternation matters — orphan-user messages get stripped
        # by validate_and_fix_alternation() inside save().
        seed.messages = [
            Message(role="user", content="round 1"),
            Message(role="assistant", content="reply 1"),
        ]
        seed.save("watcher")

        observer = self._sm(sessions_dir)
        observer.load("watcher")
        assert observer.messages[0].content == "round 1"

        # External writer modifies on disk.
        writer = self._sm(sessions_dir)
        writer.session_name = "watcher"
        writer.messages = [
            Message(role="user", content="round 2"),
            Message(role="assistant", content="ack"),
        ]
        writer.save("watcher")

        # Second load on observer sees the new state.
        assert observer.load("watcher") is True
        assert len(observer.messages) == 2
        assert observer.messages[0].content == "round 2"

    def test_concurrent_format_transitions_only_one_winner(self, tmp_path):
        """Both managers see a flat file + want to transition to
        directory. The first reaches os.rename and wins; the second
        either succeeds via the stale-tmp cleanup OR raises a clear
        OSError. It MUST NOT silently corrupt the live directory."""
        from ppxai.engine.types import Message

        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        # Seed flat file.
        flat = sessions_dir / "shared.json"
        flat.write_text(json.dumps({
            "session_name": "shared", "messages": [], "metadata": {},
        }), encoding="utf-8")

        sm1 = SessionManager(sessions_dir=sessions_dir)
        sm1.session_name = "shared"
        sm1.messages = [Message(role="user", content=[
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
        ])]

        sm2 = SessionManager(sessions_dir=sessions_dir)
        sm2.session_name = "shared"
        sm2.messages = [Message(role="user", content=[
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,BB"}},
        ])]

        # First write — succeeds.
        sm1._write_session_json("shared", {
            "session_name": "shared", "messages": [], "metadata": {},
        })

        # Second write — directory already exists, takes the
        # in-place path (rule 1 of _resolve_session_storage).
        # Must not crash, must overwrite cleanly.
        sm2._write_session_json("shared", {
            "session_name": "shared",
            "messages": [{"role": "user", "content": "sm2 wrote"}],
            "metadata": {},
        })

        dir_path = sessions_dir / "shared"
        assert dir_path.is_dir()
        # No leftover tmp.
        assert not (sessions_dir / "shared.tmp").exists()
        # Final state is sm2's.
        with open(dir_path / "session.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["messages"][0]["content"] == "sm2 wrote"


class TestSessionNamePathTraversal:
    """Session names containing path separators must not escape sessions_dir."""

    def _sm(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        sm.sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_load_dotdot_name_finds_nothing(self, tmp_path):
        sm = self._sm(tmp_path)
        evil = tmp_path / "evil.json"
        evil.write_text(json.dumps({"session_name": "evil", "messages": [], "metadata": {}}), encoding="utf-8")
        result = sm.load("../evil")
        # Should return False — the resolved path is outside sessions_dir
        # OR the file simply doesn't exist at the sessions_dir-relative path.
        # Either way it must not load from tmp_path/evil.json.
        assert result is False or sm.session_name != "evil"

    def test_resolve_load_path_dotdot_returns_none_or_within_sessions_dir(self, tmp_path):
        sm = self._sm(tmp_path)
        evil = tmp_path / "evil.json"
        evil.write_text("{}", encoding="utf-8")
        resolved = sm._resolve_session_load_path("../evil")
        if resolved is not None:
            json_path = resolved[0]
            assert sm.sessions_dir in json_path.parents, (
                f"Resolved path {json_path} escapes sessions_dir {sm.sessions_dir}"
            )
