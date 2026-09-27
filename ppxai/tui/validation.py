"""
Input validation utilities for the TUI.

Provides security-focused validation for file paths and sizes
to prevent path traversal attacks and handle large files gracefully.
"""


# File size limits
MAX_TEXT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB for text files
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB for images
MAX_DATA_FILE_SIZE = 5 * 1024 * 1024  # 5 MB for JSON/YAML/TOML


def format_file_size(size_bytes: int) -> str:
    """Format a file size in human-readable form.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 MB", "256 KB")
    """
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes} bytes"


