"""
OSC 8 hyperlink support for ppxaide.

Generates terminal hyperlinks that are clickable in supported terminals
(iTerm2, Windows Terminal, GNOME Terminal, Konsole, etc.).

OSC 8 format: \033]8;;URL\033\\TEXT\033]8;;\033\\
"""

import re
from pathlib import Path

# OSC 8 escape sequences
OSC_START = "\033]8;;"
OSC_END = "\033\\"


def make_file_link(path: str, display_text: str = None, line: int = None, col: int = None) -> str:
    """Create a clickable file link using OSC 8.

    Args:
        path: File path (absolute or relative)
        display_text: Text to display (defaults to path)
        line: Optional line number
        col: Optional column number

    Returns:
        String with OSC 8 escape sequences for terminal hyperlink
    """
    # Convert to absolute path
    abs_path = Path(path).resolve()

    # Build file:// URL
    url = f"file://{abs_path}"
    if line is not None:
        url += f":{line}"
        if col is not None:
            url += f":{col}"

    text = display_text or path
    return f"{OSC_START}{url}{OSC_END}{text}{OSC_START}{OSC_END}"


def make_url_link(url: str, display_text: str = None) -> str:
    """Create a clickable URL link using OSC 8.

    Args:
        url: The URL to link to
        display_text: Text to display (defaults to URL)

    Returns:
        String with OSC 8 escape sequences for terminal hyperlink
    """
    text = display_text or url
    return f"{OSC_START}{url}{OSC_END}{text}{OSC_START}{OSC_END}"


# Patterns for detecting file paths and URLs in text
FILE_PATH_PATTERN = re.compile(
    r'(?:^|[\s\'"(])'  # Start of string or whitespace/quotes/parens
    r'((?:/[\w.-]+)+(?::\d+(?::\d+)?)?)'  # Unix path with optional :line:col
    r'|'
    r'((?:[A-Za-z]:)?(?:\\[\w.-]+)+(?::\d+(?::\d+)?)?)'  # Windows path
    r'(?=[\s\'"),.]|$)'  # End of string or whitespace/quotes/parens
)

URL_PATTERN = re.compile(
    r'(https?://[^\s<>\'")\]]+)'
)


def linkify_paths(text: str, base_dir: str = None) -> str:
    """Convert file paths in text to clickable hyperlinks.

    Args:
        text: Text that may contain file paths
        base_dir: Base directory for resolving relative paths

    Returns:
        Text with file paths converted to OSC 8 hyperlinks
    """
    base = Path(base_dir) if base_dir else Path.cwd()

    def replace_path(match):
        path_str = match.group(1) or match.group(2)
        if not path_str:
            return match.group(0)

        # Parse line:col suffix
        line = None
        col = None
        if ':' in path_str:
            parts = path_str.rsplit(':', 2)
            if len(parts) >= 2 and parts[-1].isdigit():
                if len(parts) == 3 and parts[-2].isdigit():
                    path_str = parts[0]
                    line = int(parts[-2])
                    col = int(parts[-1])
                else:
                    path_str = ':'.join(parts[:-1])
                    line = int(parts[-1])

        # Check if path exists
        path = Path(path_str)
        if not path.is_absolute():
            path = base / path_str

        if path.exists():
            prefix = match.group(0)[:match.start(1) - match.start(0)] if match.group(1) else ""
            original = match.group(1) or match.group(2)
            return prefix + make_file_link(str(path), original, line, col)

        return match.group(0)

    return FILE_PATH_PATTERN.sub(replace_path, text)


def linkify_urls(text: str) -> str:
    """Convert URLs in text to clickable hyperlinks.

    Args:
        text: Text that may contain URLs

    Returns:
        Text with URLs converted to OSC 8 hyperlinks
    """
    def replace_url(match):
        url = match.group(1)
        return make_url_link(url)

    return URL_PATTERN.sub(replace_url, text)


def linkify_all(text: str, base_dir: str = None) -> str:
    """Convert both file paths and URLs to clickable hyperlinks.

    Args:
        text: Text that may contain paths and URLs
        base_dir: Base directory for resolving relative paths

    Returns:
        Text with paths and URLs converted to OSC 8 hyperlinks
    """
    text = linkify_urls(text)
    text = linkify_paths(text, base_dir)
    return text


def strip_hyperlinks(text: str) -> str:
    """Remove OSC 8 hyperlink escape sequences from text.

    Args:
        text: Text with possible OSC 8 sequences

    Returns:
        Plain text without hyperlink escapes
    """
    # Pattern matches OSC 8 sequences
    pattern = re.compile(r'\033\]8;;[^\033]*\033\\([^\033]*)\033\]8;;\033\\')
    return pattern.sub(r'\1', text)
