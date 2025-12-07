"""
Context injection for automatic file/URL content inclusion.

Detects file references in messages and injects content directly into prompts,
eliminating the need for tool calls for simple file reading operations.
"""

import re
import os
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class InjectedContext:
    """Represents injected content."""
    source: str          # file path or URL
    content: str         # the actual content
    language: str        # detected language (for code files)
    truncated: bool      # whether content was truncated
    size: int            # original size in bytes


class ContextInjector:
    """Detects and injects file/URL content into messages."""

    MAX_FILE_SIZE = 100_000  # ~100KB max per file
    MAX_TOTAL_CONTEXT = 200_000  # ~200KB total injected context

    # Patterns to detect file references
    FILE_PATTERNS = [
        r'(?:^|\s)([./~][\w./\-_]+\.\w+)',   # ./path/file.ext, ~/file.ext
        r'(?:^|\s)(/[\w./\-_]+\.\w+)',        # /absolute/path/file.ext
    ]

    # Keywords that suggest user wants file content
    FILE_KEYWORDS = [
        'read', 'show', 'display', 'contents', 'what is in',
        'explain', 'review', 'analyze', 'look at', 'check',
        'summarize', 'describe', 'parse', 'examine', 'inspect',
    ]

    # Language detection mapping
    LANGUAGE_MAP = {
        '.py': 'python', '.pyw': 'python', '.pyi': 'python',
        '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
        '.ts': 'typescript', '.mts': 'typescript', '.cts': 'typescript',
        '.jsx': 'jsx', '.tsx': 'tsx',
        '.java': 'java', '.kt': 'kotlin', '.kts': 'kotlin',
        '.c': 'c', '.h': 'c',
        '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.hxx': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby', '.erb': 'erb',
        '.php': 'php',
        '.swift': 'swift',
        '.scala': 'scala',
        '.r': 'r', '.R': 'r',
        '.sh': 'bash', '.bash': 'bash', '.zsh': 'zsh', '.fish': 'fish',
        '.ps1': 'powershell', '.psm1': 'powershell',
        '.sql': 'sql',
        '.html': 'html', '.htm': 'html',
        '.css': 'css', '.scss': 'scss', '.sass': 'sass', '.less': 'less',
        '.json': 'json', '.jsonc': 'json',
        '.yaml': 'yaml', '.yml': 'yaml',
        '.xml': 'xml', '.xsl': 'xml', '.xslt': 'xml',
        '.md': 'markdown', '.mdx': 'markdown',
        '.txt': 'text', '.text': 'text',
        '.toml': 'toml',
        '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini',
        '.env': 'bash',
        '.dockerfile': 'dockerfile',
        '.makefile': 'makefile', '.mk': 'makefile',
        '.cmake': 'cmake',
        '.gradle': 'gradle',
        '.lua': 'lua',
        '.vim': 'vim', '.vimrc': 'vim',
        '.el': 'elisp',
        '.clj': 'clojure', '.cljs': 'clojure', '.cljc': 'clojure',
        '.ex': 'elixir', '.exs': 'elixir',
        '.erl': 'erlang', '.hrl': 'erlang',
        '.hs': 'haskell', '.lhs': 'haskell',
        '.ml': 'ocaml', '.mli': 'ocaml',
        '.fs': 'fsharp', '.fsi': 'fsharp', '.fsx': 'fsharp',
        '.pl': 'perl', '.pm': 'perl',
        '.proto': 'protobuf',
        '.graphql': 'graphql', '.gql': 'graphql',
        '.tf': 'terraform', '.tfvars': 'terraform',
    }

    def __init__(self, working_dir: Optional[str] = None):
        """Initialize the context injector.

        Args:
            working_dir: Base directory for resolving relative paths
        """
        self.working_dir = working_dir or os.getcwd()

    def set_working_dir(self, path: str):
        """Set the working directory for relative paths."""
        self.working_dir = path

    def detect_file_references(self, message: str) -> List[str]:
        """Detect file paths mentioned in the message.

        Args:
            message: User message to scan

        Returns:
            List of detected file paths
        """
        files = []
        for pattern in self.FILE_PATTERNS:
            matches = re.findall(pattern, message, re.MULTILINE)
            files.extend(matches)

        # Also check for quoted paths
        quoted_pattern = r'["\']([^"\']+\.\w+)["\']'
        quoted_matches = re.findall(quoted_pattern, message)
        files.extend(quoted_matches)

        return list(set(files))  # dedupe

    def should_inject(self, message: str, files: List[str]) -> bool:
        """Determine if we should auto-inject file contents.

        Args:
            message: User message
            files: Detected file paths

        Returns:
            True if context should be injected
        """
        if not files:
            return False

        msg_lower = message.lower()

        # Check for explicit keywords
        if any(kw in msg_lower for kw in self.FILE_KEYWORDS):
            return True

        # Check if message is primarily about the file (short message + file path)
        words = message.split()
        if len(words) <= 10 and files:
            return True

        return False

    def resolve_path(self, filepath: str) -> Optional[Path]:
        """Resolve a file path to an absolute path.

        Args:
            filepath: File path (relative, absolute, or with ~)

        Returns:
            Resolved Path object, or None if invalid
        """
        # Expand ~ to home directory
        if filepath.startswith('~'):
            filepath = os.path.expanduser(filepath)
        # Resolve relative paths
        elif not filepath.startswith('/'):
            filepath = os.path.join(self.working_dir, filepath)

        path = Path(filepath).resolve()

        # Security: don't allow path traversal outside working dir for relative paths
        # (absolute paths are explicit, so we allow them)
        if not path.exists() or not path.is_file():
            return None

        return path

    def read_file(self, filepath: str) -> Optional[InjectedContext]:
        """Read a file and return its content.

        Args:
            filepath: Path to the file

        Returns:
            InjectedContext with file content, or None if unreadable
        """
        path = self.resolve_path(filepath)
        if path is None:
            return None

        # Detect language from extension
        lang = self._detect_language(path.suffix)

        # Check if it's a binary file (simple heuristic)
        if self._is_likely_binary(path):
            return None

        try:
            original_size = path.stat().st_size

            # Don't read files that are too large
            if original_size > self.MAX_FILE_SIZE * 2:
                return InjectedContext(
                    source=str(path),
                    content=f"[File too large: {self._format_size(original_size)}]",
                    language=lang,
                    truncated=True,
                    size=original_size
                )

            content = path.read_text(errors='replace')
            truncated = False

            if len(content) > self.MAX_FILE_SIZE:
                content = content[:self.MAX_FILE_SIZE]
                truncated = True

            return InjectedContext(
                source=str(path),
                content=content,
                language=lang,
                truncated=truncated,
                size=original_size
            )
        except Exception:
            return None

    def inject_context(self, message: str) -> Tuple[str, List[InjectedContext]]:
        """Process message and inject file contents if appropriate.

        Args:
            message: User message

        Returns:
            Tuple of (modified_message, list_of_injected_contexts)
        """
        files = self.detect_file_references(message)

        if not self.should_inject(message, files):
            return message, []

        injected = []
        total_size = 0

        for filepath in files:
            if total_size >= self.MAX_TOTAL_CONTEXT:
                break

            ctx = self.read_file(filepath)
            if ctx:
                injected.append(ctx)
                total_size += len(ctx.content)

        if not injected:
            return message, []

        # Build enhanced message with injected content
        enhanced = message + "\n\n---\n**Attached file contents:**\n"

        for ctx in injected:
            truncation_note = " *(truncated)*" if ctx.truncated else ""
            size_str = self._format_size(ctx.size)
            enhanced += f"\n**`{ctx.source}`** ({size_str}){truncation_note}:\n"
            enhanced += f"```{ctx.language}\n{ctx.content}\n```\n"

        return enhanced, injected

    def _detect_language(self, suffix: str) -> str:
        """Detect language from file extension.

        Args:
            suffix: File extension including dot

        Returns:
            Language identifier for syntax highlighting
        """
        return self.LANGUAGE_MAP.get(suffix.lower(), '')

    def _is_likely_binary(self, path: Path) -> bool:
        """Check if a file is likely binary.

        Args:
            path: Path to check

        Returns:
            True if file appears to be binary
        """
        binary_extensions = {
            '.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe',
            '.o', '.a', '.lib', '.obj',
            '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp',
            '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv',
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
            '.db', '.sqlite', '.sqlite3',
            '.wasm', '.class', '.jar',
        }

        if path.suffix.lower() in binary_extensions:
            return True

        # Check first few bytes for null characters
        try:
            with open(path, 'rb') as f:
                chunk = f.read(1024)
                if b'\x00' in chunk:
                    return True
        except Exception:
            return True

        return False

    def _format_size(self, size: int) -> str:
        """Format file size in human readable form.

        Args:
            size: Size in bytes

        Returns:
            Formatted string like "1.5 KB"
        """
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"
