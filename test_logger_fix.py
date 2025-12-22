#!/usr/bin/env python3
"""Test that the logger can be enabled at runtime."""

import sys
from pathlib import Path

# Add ppxai to path
sys.path.insert(0, str(Path(__file__).parent))

from ppxai.tui_logger import get_logger

def test_logger_enable():
    """Test that logger can be enabled after initialization."""

    # Get logger (should be disabled initially since PPXAI_DEBUG not set)
    logger = get_logger()

    print(f"1. Initial state - Enabled: {logger.enabled}")
    assert not logger.enabled, "Logger should be disabled initially"

    # Enable logger
    print("2. Calling logger.enable()...")
    logger.enable()

    print(f"3. After enable() - Enabled: {logger.enabled}")
    assert logger.enabled, "Logger should be enabled after enable()"

    # Check if log file was created
    log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
    print(f"4. Log file exists: {log_file.exists()}")
    assert log_file.exists(), f"Log file should exist at {log_file}"

    # Test logging
    print("5. Testing log methods...")
    logger.log_user_message("Test user message")
    logger.log_command("/test command")
    logger.log_api_request(1, [])

    # Verify log content
    log_content = log_file.read_text()
    print(f"6. Log content preview:\n{log_content[:500]}")

    assert "TUI DEBUG SESSION STARTED" in log_content
    assert "USER INPUT: Test user message" in log_content
    assert "COMMAND: /test command" in log_content
    assert "API REQUEST: iteration=1" in log_content

    print("\n✓ All tests passed!")
    print(f"✓ Log file created at: {log_file}")

    # Clean up
    logger.disable()

    return True

if __name__ == "__main__":
    try:
        test_logger_enable()
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
