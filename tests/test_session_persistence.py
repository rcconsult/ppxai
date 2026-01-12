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


class TestSessionManagerCommandHistory:
    """Tests for command history persistence."""

    def test_add_to_history(self, session_manager):
        """Test adding commands to history."""
        session_manager.add_to_history("Hello, AI!")
        session_manager.add_to_history("/model gemini-2.0-flash")
        session_manager.add_to_history("Explain this code")

        assert len(session_manager.command_history) == 3
        assert session_manager.command_history[0] == "Hello, AI!"
        assert session_manager.command_history[1] == "/model gemini-2.0-flash"
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
        session_manager.metadata["model"] = "gemini-2.0-flash"

        with patch('ppxai.engine.session.SESSION_STATE_FILE', state_file):
            session_manager._update_state_file(dirty=False)

            with open(state_file) as f:
                data = json.load(f)

            assert data["last_session"]["name"] == session_manager.session_name
            assert data["last_session"]["provider"] == "gemini"
            assert data["last_session"]["model"] == "gemini-2.0-flash"
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
        result = new_manager.load_with_extras(saved_name)

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
        result = session_manager.load_with_extras("old_session")

        assert result is True
        assert session_manager.command_history == []
        assert session_manager.working_dir == os.getcwd()


class TestSessionConfig:
    """Tests for session configuration."""

    def test_get_session_config_defaults(self):
        """Test default session config values."""
        with patch('ppxai.config._config', {}):
            config = get_session_config()
            assert config["auto_restore"] == "prompt"
            assert config["auto_save_interval"] == 1

    def test_get_session_config_custom(self):
        """Test custom session config values."""
        with patch('ppxai.config._config', {
            "session": {
                "auto_restore": "always",
                "auto_save_interval": 5
            }
        }):
            config = get_session_config()
            assert config["auto_restore"] == "always"
            assert config["auto_save_interval"] == 5

    def test_get_auto_restore_mode_valid_values(self):
        """Test valid auto_restore values."""
        for mode in ["always", "prompt", "never"]:
            with patch('ppxai.config._config', {"session": {"auto_restore": mode}}):
                assert get_auto_restore_mode() == mode

    def test_get_auto_restore_mode_invalid_defaults_to_prompt(self):
        """Test invalid auto_restore value defaults to prompt."""
        with patch('ppxai.config._config', {"session": {"auto_restore": "invalid"}}):
            assert get_auto_restore_mode() == "prompt"

    def test_get_auto_save_interval_valid(self):
        """Test valid auto_save_interval values."""
        with patch('ppxai.config._config', {"session": {"auto_save_interval": 10}}):
            assert get_auto_save_interval() == 10

    def test_get_auto_save_interval_zero(self):
        """Test auto_save_interval of 0 (every message)."""
        with patch('ppxai.config._config', {"session": {"auto_save_interval": 0}}):
            assert get_auto_save_interval() == 0

    def test_get_auto_save_interval_negative_clamped(self):
        """Test negative auto_save_interval is clamped to 0."""
        with patch('ppxai.config._config', {"session": {"auto_save_interval": -5}}):
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
        original.add_to_history("/model gemini-2.0-flash")
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
        assert restored.load_with_extras(session_name)

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
