"""
Clipboard integration for ppxaide.

Provides copy/paste functionality using pyperclip for cross-platform
clipboard access. Note: Only text is supported (no images or binary data).
"""


import pyperclip  # Required dependency (in pyproject.toml)

CLIPBOARD_AVAILABLE = True


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard.

    Args:
        text: Text to copy

    Returns:
        True if successful, False if clipboard unavailable
    """
    if not CLIPBOARD_AVAILABLE:
        return False
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def paste_from_clipboard() -> str | None:
    """Paste text from the system clipboard.

    Returns:
        Clipboard text, or None if unavailable/empty
    """
    if not CLIPBOARD_AVAILABLE:
        return None
    try:
        text = pyperclip.paste()
        return text if text else None
    except Exception:
        return None


def is_clipboard_available() -> bool:
    """Check if clipboard functionality is available.

    Returns:
        True if pyperclip is installed and working
    """
    if not CLIPBOARD_AVAILABLE:
        return False
    try:
        # Try a simple operation to verify it works
        pyperclip.paste()
        return True
    except Exception:
        return False
