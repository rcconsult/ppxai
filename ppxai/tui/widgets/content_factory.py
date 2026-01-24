"""
Content display mode detection for file viewing.

Provides utilities to detect the appropriate display mode for files
based on their extension.
"""

from pathlib import Path
from typing import Optional

from ..images import IMAGE_EXTENSIONS


# File type detection constants
DATA_FORMATS = {'.json', '.yaml', '.yml', '.toml'}
MARKDOWN_FORMATS = {'.md', '.markdown'}


def detect_display_mode(path: Path) -> str:
    """Detect appropriate display mode for a file.

    Args:
        path: Path to the file

    Returns:
        Display mode: "data", "image", "markdown", or "code"
    """
    ext = path.suffix.lower()
    if ext in DATA_FORMATS:
        return "data"
    elif ext in IMAGE_EXTENSIONS:
        return "image"
    elif ext in MARKDOWN_FORMATS:
        return "markdown"
    return "code"


def get_data_format(path: Path) -> Optional[str]:
    """Get specific data format (json/yaml/toml) for a path.

    Args:
        path: Path to the file

    Returns:
        Data format name or None if not a data file
    """
    ext = path.suffix.lower()
    if ext == '.json':
        return 'json'
    elif ext in ('.yaml', '.yml'):
        return 'yaml'
    elif ext == '.toml':
        return 'toml'
    return None


def is_data_file(path: Path) -> bool:
    """Check if a file is a structured data file (JSON/YAML/TOML).

    Args:
        path: Path to check

    Returns:
        True if file has a data format extension
    """
    return path.suffix.lower() in DATA_FORMATS


def is_markdown_file(path: Path) -> bool:
    """Check if a file is a markdown file.

    Args:
        path: Path to check

    Returns:
        True if file has a markdown extension
    """
    return path.suffix.lower() in MARKDOWN_FORMATS
