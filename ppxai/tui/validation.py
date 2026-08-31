"""
Input validation utilities for the TUI.

Provides security-focused validation for file paths and sizes
to prevent path traversal attacks and handle large files gracefully.
"""

from pathlib import Path

# File size limits
MAX_TEXT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB for text files
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB for images
MAX_DATA_FILE_SIZE = 5 * 1024 * 1024  # 5 MB for JSON/YAML/TOML


def safe_resolve_path(
    path_str: str,
    base_dir: str | None = None,
    allow_absolute: bool = True,
) -> Path | None:
    """Resolve a path safely, preventing directory traversal attacks.

    Args:
        path_str: The path string to resolve
        base_dir: Base directory for relative paths (defaults to cwd)
        allow_absolute: Whether to allow absolute paths

    Returns:
        Resolved Path if valid and exists, None otherwise

    Security:
        - Relative paths are resolved relative to base_dir
        - Relative paths cannot escape base_dir via ../
        - Absolute paths are allowed only if allow_absolute=True
        - Home directory expansion (~) is supported
    """
    if not path_str or not path_str.strip():
        return None

    path_str = path_str.strip()

    # Handle home directory expansion
    if path_str.startswith("~"):
        expanded = Path(path_str).expanduser()
        if not expanded.exists():
            return None
        return expanded.resolve()

    # Handle absolute paths
    if path_str.startswith("/") or (len(path_str) > 1 and path_str[1] == ":"):
        if not allow_absolute:
            return None
        target = Path(path_str)
        if not target.exists():
            return None
        return target.resolve()

    # Handle relative paths - must stay within base_dir
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    target = (base / path_str).resolve()

    # Security check: ensure target is within base directory
    try:
        target.relative_to(base)
    except ValueError:
        # Path escapes base directory (e.g., via ../)
        return None

    if not target.exists():
        return None

    return target


def validate_file_size(
    path: Path,
    max_size: int = MAX_TEXT_FILE_SIZE,
) -> tuple[bool, int]:
    """Check if a file size is within acceptable limits.

    Args:
        path: Path to the file
        max_size: Maximum allowed size in bytes

    Returns:
        Tuple of (is_valid, actual_size)

    Raises:
        OSError: If file cannot be accessed
    """
    size = path.stat().st_size
    return (size <= max_size, size)


def get_size_limit_for_mode(mode: str) -> int:
    """Get the appropriate file size limit for a display mode.

    Args:
        mode: Display mode ("code", "data", "image", "markdown")

    Returns:
        Size limit in bytes
    """
    limits = {
        "image": MAX_IMAGE_SIZE,
        "data": MAX_DATA_FILE_SIZE,
        "code": MAX_TEXT_FILE_SIZE,
        "markdown": MAX_TEXT_FILE_SIZE,
    }
    return limits.get(mode, MAX_TEXT_FILE_SIZE)


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


def is_safe_filename(filename: str) -> bool:
    """Check if a filename is safe (no path separators or traversal).

    Args:
        filename: The filename to check

    Returns:
        True if filename is safe
    """
    if not filename:
        return False

    # Check for path separators
    if "/" in filename or "\\" in filename:
        return False

    # Check for traversal patterns
    if filename in (".", ".."):
        return False

    # Check for null bytes or other dangerous characters
    dangerous_chars = {"\x00", "\n", "\r"}
    if any(c in filename for c in dangerous_chars):
        return False

    return True
