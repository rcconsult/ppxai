"""
Tests for ppxai/common/logger.py

Tests the unified Logger class.
"""

from pathlib import Path

import pytest

from ppxai.common.logger import Logger, get_logger


@pytest.fixture(autouse=True)
def _isolate_debug_env(monkeypatch):
    """Strip PPXAI_DEBUG from the environment for every test in this module.

    Without this fixture, `test_logger_enable`, `test_logger_disable`, and
    `test_logger_log_methods_when_disabled` all fail when the developer's
    home `~/.ppxai/ppxai-config.json` has `tui.debug_log: true`. The
    failure chain (verified 2026-05-15):

      1. `tests/conftest.py::pytest_configure` calls `ppxai.config.initialize()`
      2. `config/__init__.py:210` reads `tui.debug_log` from user config
         and runs `os.environ.setdefault("PPXAI_DEBUG", "1")`
      3. From that point on, every fresh `Logger(...)` constructed in any
         test sees `PPXAI_DEBUG=1` in `os.getenv` and self-enables —
         breaking the "default disabled" assumption these tests pin.

    The flake doesn't fire on CI (CI doesn't have a user config) but
    bites every developer who has `/debug-log on` enabled. Surfaced
    while running the suite for ADR 0006 Phase 1.

    The fixture is autouse + module-scoped so individual tests don't
    have to opt in. Doesn't touch the user's actual config file —
    `monkeypatch.delenv` only mutates the test-process environment.
    """
    monkeypatch.delenv("PPXAI_DEBUG", raising=False)
    # Per-component env vars too — Logger.__init__ checks both
    # PPXAI_DEBUG (universal) and PPXAI_<NAME>_DEBUG (per-component).
    # Nothing in test names today collides with real component names but
    # covering all of them keeps the isolation robust.
    for name in ["TUI", "SERVER", "ENGINE", "TEST_ENABLE", "TEST_DISABLE_AFTER",
                 "TEST_DISABLED_METHODS", "TEST_LOGFILE", "TEST_METHODS",
                 "TEST_USER_MSG", "TEST_ASSISTANT_MSG", "TEST_COMMAND",
                 "TEST_TOOL_CALL", "TEST_API_ERROR", "TEST_HTTP_REQ",
                 "TEST_CLEAR", "TEST_TRUNCATE"]:
        monkeypatch.delenv(f"PPXAI_{name}_DEBUG", raising=False)


def test_get_logger_singleton():
    """Test that get_logger returns same instance for same name."""
    logger1 = get_logger("test")
    logger2 = get_logger("test")

    assert logger1 is logger2


def test_get_logger_different_names():
    """Test that different names create different loggers."""
    logger_tui = get_logger("tui")
    logger_server = get_logger("server")

    assert logger_tui is not logger_server
    assert logger_tui.name == "tui"
    assert logger_server.name == "server"


def test_logger_initially_disabled():
    """Test that logger is disabled by default (no PPXAI_DEBUG env)."""
    # Create logger without env var
    with pytest.MonkeyPatch.context() as m:
        m.setenv("PPXAI_DEBUG", "")
        logger = Logger("test_disabled")

    assert logger.enabled is False


def test_logger_enable():
    """Test that logger can be enabled programmatically."""
    logger = Logger("test_enable")

    assert logger.enabled is False

    logger.enable()

    assert logger.enabled is True
    assert logger.log_file is not None
    assert logger.log_file.exists()


def test_logger_disable():
    """Test that logger can be disabled after being enabled."""
    logger = Logger("test_disable_after")

    logger.enable()
    assert logger.enabled is True

    logger.disable()
    assert logger.enabled is False


def test_logger_log_file_creation():
    """Test that log file is created in correct location."""
    logger = Logger("test_logfile")
    logger.enable()

    expected_path = Path.home() / '.ppxai' / 'logs' / 'test_logfile-debug.log'
    assert logger.log_file == expected_path
    assert logger.log_file.exists()


def test_logger_log_methods():
    """Test that log methods work when enabled."""
    logger = Logger("test_methods")
    logger.enable()

    # Should not raise exceptions
    logger.info("Info message")
    logger.debug("Debug message")
    logger.warning("Warning message")
    logger.error("Error message")

    # Check log file contains messages
    log_content = logger.log_file.read_text(encoding="utf-8")
    assert "Info message" in log_content
    assert "Debug message" in log_content
    assert "Warning message" in log_content
    assert "Error message" in log_content


def test_logger_log_methods_when_disabled():
    """Test that log methods are no-op when disabled."""
    logger = Logger("test_disabled_methods")

    # Should not raise exceptions
    logger.info("Should not appear")
    logger.debug("Should not appear")

    # Log file should not exist
    assert logger.log_file is None or not logger.log_file.exists()


def test_logger_user_message():
    """Test log_user_message helper."""
    logger = Logger("test_user_msg")
    logger.enable()

    logger.log_user_message("User input test")

    log_content = logger.log_file.read_text(encoding="utf-8")
    assert "USER INPUT: User input test" in log_content


def test_logger_assistant_message():
    """Test log_assistant_message helper."""
    logger = Logger("test_assistant_msg")
    logger.enable()

    logger.log_assistant_message("Assistant response test")

    log_content = logger.log_file.read_text(encoding="utf-8")
    assert "ASSISTANT RESPONSE: Assistant response test" in log_content


def test_logger_command():
    """Test log_command helper."""
    logger = Logger("test_command")
    logger.enable()

    logger.log_command("/tools enable")

    log_content = logger.log_file.read_text(encoding="utf-8")
    assert "COMMAND: /tools enable" in log_content


def test_logger_tool_call():
    """Test log_tool_call helper."""
    logger = Logger("test_tool_call")
    logger.enable()

    logger.log_tool_call("list_directory", {"path": "/"})

    log_content = logger.log_file.read_text(encoding="utf-8")
    assert "TOOL CALL: list_directory" in log_content
    assert "Arguments: {'path': '/'}" in log_content


def test_logger_api_error():
    """Test log_api_error helper."""
    logger = Logger("test_api_error")
    logger.enable()

    logger.log_api_error(500, "Internal Server Error")

    log_content = logger.log_file.read_text(encoding="utf-8")
    assert "API ERROR 500: Internal Server Error" in log_content


def test_logger_http_request():
    """Test log_http_request helper (server-specific)."""
    logger = Logger("test_http_req")
    logger.enable()

    logger.log_http_request("POST", "/api/chat", "client123")

    log_content = logger.log_file.read_text(encoding="utf-8")
    assert "HTTP POST /api/chat from client123" in log_content


def test_logger_clear():
    """Test that clear() empties log file."""
    logger = Logger("test_clear")
    logger.enable()

    logger.info("Message 1")
    assert "Message 1" in logger.log_file.read_text(encoding="utf-8")

    logger.clear()
    log_content = logger.log_file.read_text(encoding="utf-8")

    # Should have session start but not old message
    assert "DEBUG SESSION STARTED" in log_content
    assert "Message 1" not in log_content


def test_logger_truncates_long_messages():
    """Test that long messages are truncated in logs."""
    logger = Logger("test_truncate")
    logger.enable()

    long_message = "A" * 500
    logger.log_user_message(long_message)

    log_content = logger.log_file.read_text(encoding="utf-8")
    # Should only log first 200 chars
    assert long_message[:200] in log_content
    assert len(long_message) > 200  # Confirm it was long
