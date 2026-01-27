"""
File type detection using filetype library with fallback to extension-based detection.

This module provides accurate file type detection for the /show and /edit commands,
enabling proper widget selection (TreeViewer, TableViewer, Markdown, CodeEditor, ImageViewer).

Uses the pure-Python 'filetype' library for magic byte detection, which works reliably
with PyInstaller on Windows (no native DLL dependencies like python-magic).

Usage:
    from ppxai.common.file_type import detect_file_type, FileType

    file_type = detect_file_type(Path("config.json"))
    if file_type == FileType.JSON:
        # Use TreeViewer
    elif file_type == FileType.CSV:
        # Use TableViewer
"""

import mimetypes
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# Initialize mimetypes
mimetypes.init()


class FileType(Enum):
    """Detected file type for widget selection."""
    # Structured data (TreeViewer)
    JSON = auto()
    YAML = auto()
    TOML = auto()
    HCL = auto()
    XML = auto()

    # Tabular data (TableViewer)
    CSV = auto()
    TSV = auto()

    # Rich text (MarkdownViewer)
    MARKDOWN = auto()

    # Images (ImageViewer)
    IMAGE = auto()

    # Code/text (CodeEditor)
    CODE = auto()
    TEXT = auto()

    # Binary (not viewable)
    BINARY = auto()

    # Unknown
    UNKNOWN = auto()


# MIME type to FileType mapping
MIME_TO_FILETYPE = {
    # Structured data
    "application/json": FileType.JSON,
    "text/json": FileType.JSON,
    "application/yaml": FileType.YAML,
    "text/yaml": FileType.YAML,
    "text/x-yaml": FileType.YAML,
    "application/x-yaml": FileType.YAML,
    "application/toml": FileType.TOML,
    "text/x-toml": FileType.TOML,
    "text/xml": FileType.XML,
    "application/xml": FileType.XML,

    # Tabular
    "text/csv": FileType.CSV,
    "text/tab-separated-values": FileType.TSV,

    # Markdown
    "text/markdown": FileType.MARKDOWN,
    "text/x-markdown": FileType.MARKDOWN,

    # Images
    "image/png": FileType.IMAGE,
    "image/jpeg": FileType.IMAGE,
    "image/gif": FileType.IMAGE,
    "image/webp": FileType.IMAGE,
    "image/bmp": FileType.IMAGE,
    "image/tiff": FileType.IMAGE,
    "image/x-icon": FileType.IMAGE,
    "image/svg+xml": FileType.IMAGE,

    # Code (common types)
    "text/x-python": FileType.CODE,
    "text/x-script.python": FileType.CODE,
    "application/x-python-code": FileType.CODE,
    "text/javascript": FileType.CODE,
    "application/javascript": FileType.CODE,
    "text/x-java": FileType.CODE,
    "text/x-c": FileType.CODE,
    "text/x-c++": FileType.CODE,
    "text/x-go": FileType.CODE,
    "text/x-rust": FileType.CODE,
    "text/x-ruby": FileType.CODE,
    "text/x-php": FileType.CODE,
    "text/x-shellscript": FileType.CODE,
    "application/x-shellscript": FileType.CODE,
    "text/x-sh": FileType.CODE,
    "text/html": FileType.CODE,
    "text/css": FileType.CODE,
    "application/sql": FileType.CODE,

    # Note: text/plain is intentionally NOT mapped here to allow
    # extension-based detection (e.g., .md files are often detected as text/plain)

    # Binary
    "application/octet-stream": FileType.BINARY,
    "application/x-executable": FileType.BINARY,
    "application/x-sharedlib": FileType.BINARY,
}

# Extension to FileType mapping (fallback when magic fails)
EXTENSION_TO_FILETYPE = {
    # Structured data
    ".json": FileType.JSON,
    ".yaml": FileType.YAML,
    ".yml": FileType.YAML,
    ".toml": FileType.TOML,
    ".hcl": FileType.HCL,
    ".tf": FileType.HCL,
    ".xml": FileType.XML,

    # Tabular
    ".csv": FileType.CSV,
    ".tsv": FileType.TSV,

    # Markdown
    ".md": FileType.MARKDOWN,
    ".markdown": FileType.MARKDOWN,
    ".mdown": FileType.MARKDOWN,

    # Images
    ".png": FileType.IMAGE,
    ".jpg": FileType.IMAGE,
    ".jpeg": FileType.IMAGE,
    ".gif": FileType.IMAGE,
    ".webp": FileType.IMAGE,
    ".bmp": FileType.IMAGE,
    ".tiff": FileType.IMAGE,
    ".tif": FileType.IMAGE,
    ".ico": FileType.IMAGE,
    ".svg": FileType.IMAGE,

    # Code
    ".py": FileType.CODE,
    ".pyw": FileType.CODE,
    ".pyi": FileType.CODE,
    ".js": FileType.CODE,
    ".mjs": FileType.CODE,
    ".cjs": FileType.CODE,
    ".ts": FileType.CODE,
    ".tsx": FileType.CODE,
    ".jsx": FileType.CODE,
    ".java": FileType.CODE,
    ".c": FileType.CODE,
    ".h": FileType.CODE,
    ".cpp": FileType.CODE,
    ".hpp": FileType.CODE,
    ".cc": FileType.CODE,
    ".cxx": FileType.CODE,
    ".go": FileType.CODE,
    ".rs": FileType.CODE,
    ".rb": FileType.CODE,
    ".php": FileType.CODE,
    ".sh": FileType.CODE,
    ".bash": FileType.CODE,
    ".zsh": FileType.CODE,
    ".fish": FileType.CODE,
    ".ps1": FileType.CODE,
    ".bat": FileType.CODE,
    ".cmd": FileType.CODE,
    ".html": FileType.CODE,
    ".htm": FileType.CODE,
    ".css": FileType.CODE,
    ".scss": FileType.CODE,
    ".sass": FileType.CODE,
    ".less": FileType.CODE,
    ".sql": FileType.CODE,
    ".lua": FileType.CODE,
    ".r": FileType.CODE,
    ".swift": FileType.CODE,
    ".kt": FileType.CODE,
    ".kts": FileType.CODE,
    ".scala": FileType.CODE,
    ".clj": FileType.CODE,
    ".ex": FileType.CODE,
    ".exs": FileType.CODE,
    ".erl": FileType.CODE,
    ".hs": FileType.CODE,
    ".ml": FileType.CODE,
    ".fs": FileType.CODE,
    ".vue": FileType.CODE,
    ".svelte": FileType.CODE,

    # Config/text (treat as code for syntax highlighting)
    ".ini": FileType.CODE,
    ".cfg": FileType.CODE,
    ".conf": FileType.CODE,
    ".env": FileType.CODE,
    ".properties": FileType.CODE,
    ".gitignore": FileType.CODE,
    ".dockerignore": FileType.CODE,
    ".editorconfig": FileType.CODE,

    # Plain text
    ".txt": FileType.TEXT,
    ".text": FileType.TEXT,
    ".log": FileType.TEXT,
    ".readme": FileType.TEXT,
}

# FileType to view mode mapping (for renderer)
FILETYPE_TO_VIEW_MODE = {
    FileType.JSON: "tree",
    FileType.YAML: "tree",
    FileType.TOML: "tree",
    FileType.HCL: "tree",
    FileType.XML: "code",  # XML can be large, show as code
    FileType.CSV: "table",
    FileType.TSV: "table",
    FileType.MARKDOWN: "markdown",
    FileType.IMAGE: "image",
    FileType.CODE: "code",
    FileType.TEXT: "code",
    FileType.BINARY: "binary",
    FileType.UNKNOWN: "code",
}

# FileType to syntax language mapping (for CodeEditor)
FILETYPE_TO_LANGUAGE = {
    FileType.JSON: "json",
    FileType.YAML: "yaml",
    FileType.TOML: "toml",
    FileType.XML: "xml",
    FileType.MARKDOWN: "markdown",
    FileType.CODE: None,  # Determined by extension
    FileType.TEXT: None,
}


def detect_file_type(path: Path, content: Optional[str] = None) -> FileType:
    """Detect file type using filetype library with extension fallback.

    Args:
        path: Path to the file
        content: Optional file content (if already read)

    Returns:
        FileType enum indicating the detected type
    """
    # Try filetype-based detection first (magic byte detection)
    try:
        import filetype
        kind = filetype.guess(str(path))
        if kind is not None:
            mime = kind.mime
            if mime in MIME_TO_FILETYPE:
                return MIME_TO_FILETYPE[mime]

            # Check for image types not in our mapping
            if mime.startswith("image/"):
                return FileType.IMAGE

            # Check for binary types
            if mime.startswith("application/") and mime not in (
                "application/json", "application/xml", "application/yaml",
                "application/toml", "application/javascript"
            ):
                return FileType.BINARY

    except ImportError:
        # filetype not installed, use fallback
        pass
    except Exception:
        # Detection failed, use fallback
        pass

    # Fallback to extension-based detection
    ext = path.suffix.lower()
    if ext in EXTENSION_TO_FILETYPE:
        return EXTENSION_TO_FILETYPE[ext]

    # Check if file is readable as text
    if content is not None:
        # Content provided, assume text
        return FileType.TEXT

    try:
        # Try to read a small portion to check if text
        with open(path, 'rb') as f:
            chunk = f.read(8192)
            # Check for null bytes (binary indicator)
            if b'\x00' in chunk:
                return FileType.BINARY
            # Try to decode as UTF-8
            try:
                chunk.decode('utf-8')
                return FileType.TEXT
            except UnicodeDecodeError:
                return FileType.BINARY
    except Exception:
        return FileType.UNKNOWN

    return FileType.UNKNOWN


def get_view_mode(file_type: FileType) -> str:
    """Get the view mode for a file type.

    Args:
        file_type: Detected FileType

    Returns:
        View mode string: "tree", "table", "markdown", "image", "code", "binary"
    """
    return FILETYPE_TO_VIEW_MODE.get(file_type, "code")


def get_language_for_extension(ext: str) -> Optional[str]:
    """Get syntax highlighting language for file extension.

    Args:
        ext: File extension (e.g., ".py")

    Returns:
        Language name for syntax highlighting, or None
    """
    EXTENSION_TO_LANGUAGE = {
        ".py": "python",
        ".pyw": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".jsx": "jsx",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".md": "markdown",
        ".markdown": "markdown",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".scss": "scss",
        ".sass": "sass",
        ".less": "less",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".fish": "fish",
        ".ps1": "powershell",
        ".sql": "sql",
        ".xml": "xml",
        ".java": "java",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".cc": "cpp",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".lua": "lua",
        ".r": "r",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".hs": "haskell",
        ".ex": "elixir",
        ".exs": "elixir",
        ".erl": "erlang",
        ".clj": "clojure",
        ".vue": "vue",
        ".svelte": "svelte",
        ".hcl": "hcl",
        ".tf": "hcl",
        ".ini": "ini",
        ".cfg": "ini",
        ".conf": "ini",
    }
    return EXTENSION_TO_LANGUAGE.get(ext.lower())
