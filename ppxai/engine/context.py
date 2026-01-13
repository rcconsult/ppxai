"""
Context injection for automatic file/URL content inclusion.

Detects file references in messages and injects content directly into prompts,
eliminating the need for tool calls for simple file reading operations.

v1.13.9: Configurable max_injection_size via ppxai-config.json
v1.13.10: Content hash deduplication to prevent duplicate injections
"""

import hashlib
import re
import os
from pathlib import Path
from typing import List, Tuple, Optional, Set
from dataclasses import dataclass


@dataclass
class InjectedContext:
    """Represents injected content."""
    source: str          # file path or URL
    content: str         # the actual content
    language: str        # detected language (for code files)
    truncated: bool      # whether content was truncated
    size: int            # original size in bytes
    hash: str = ""       # v1.13.10: content hash for deduplication


def compute_content_hash(content: str) -> str:
    """Compute a short hash of content for deduplication.

    Args:
        content: Content to hash

    Returns:
        12-character MD5 hash (fast, collision-resistant enough for this use)
    """
    return hashlib.md5(content.encode()).hexdigest()[:12]


def _get_max_injection_size() -> int:
    """Get max injection size from config, with fallback.

    Returns:
        Max injection size in characters.
    """
    try:
        from ...config import get_max_injection_size
        return get_max_injection_size()
    except ImportError:
        return 100_000  # Default fallback


# Module-level constant for backwards compatibility
MAX_FILE_SIZE = _get_max_injection_size()


class ContextInjector:
    """Detects and injects file/URL content into messages."""

    MAX_TOTAL_CONTEXT = 200_000  # ~200KB total injected context

    @property
    def MAX_FILE_SIZE(self) -> int:
        """Get configurable max file size."""
        return _get_max_injection_size()

    # Patterns to detect file references
    FILE_PATTERNS = [
        r'@([\w./\-_~]+\.\w+)',               # @/path/file.ext, @./file.ext (explicit reference)
        r'(?:^|\s)([./~][\w./\-_]+\.\w+)',   # ./path/file.ext, ~/file.ext
        r'(?:^|\s)(/[\w./\-_]+\.\w+)',        # /absolute/path/file.ext
    ]

    # Patterns for special context providers
    GIT_PATTERN = r'@git\b'
    TREE_PATTERN = r'@tree\b'

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

        # Check for explicit @ references (always inject these)
        if '@' in message:
            return True

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

    def inject_git_context(self, working_dir: Optional[str] = None) -> Optional[InjectedContext]:
        """Inject git diff (staged + unstaged) as context.

        Args:
            working_dir: Directory to check for git changes (default: self.working_dir)

        Returns:
            InjectedContext with git diff or None if not in git repo
        """
        import subprocess

        work_dir = working_dir or self.working_dir

        try:
            # Get unstaged changes
            unstaged = subprocess.run(
                ['git', 'diff'],
                cwd=work_dir,
                capture_output=True,
                text=True,
                check=False
            )

            # Get staged changes
            staged = subprocess.run(
                ['git', 'diff', '--staged'],
                cwd=work_dir,
                capture_output=True,
                text=True,
                check=False
            )

            # Check if we're in a git repository
            if unstaged.returncode != 0 or staged.returncode != 0:
                return None

            # Combine with headers
            content = ""
            if staged.stdout.strip():
                content += "=== Staged Changes ===\n"
                content += staged.stdout + "\n"

            if unstaged.stdout.strip():
                content += "=== Unstaged Changes ===\n"
                content += unstaged.stdout + "\n"

            if not content:
                content = "No changes in working directory"

            # Truncate if too large (same as regular files)
            original_size = len(content)
            truncated = False
            if len(content) > self.MAX_FILE_SIZE:
                content = content[:self.MAX_FILE_SIZE]
                truncated = True

            return InjectedContext(
                source="@git",
                content=content,
                language="diff",
                truncated=truncated,
                size=original_size
            )

        except (subprocess.CalledProcessError, FileNotFoundError):
            return None  # Not a git repository or git not installed

    def inject_tree_context(self, working_dir: Optional[str] = None, max_depth: int = 3) -> Optional[InjectedContext]:
        """Inject directory tree structure as context.

        Args:
            working_dir: Root directory to tree (default: self.working_dir)
            max_depth: Maximum depth to traverse

        Returns:
            InjectedContext with tree structure
        """
        work_dir = working_dir or self.working_dir
        root_path = Path(work_dir)

        if not root_path.exists() or not root_path.is_dir():
            return None

        def build_tree(path: Path, prefix: str = "", depth: int = 0) -> str:
            """Recursively build tree structure."""
            if depth > max_depth:
                return ""

            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            except PermissionError:
                return ""

            output = []
            # Filter out common ignore patterns
            ignore_patterns = {'.git', '__pycache__', 'node_modules', '.venv',
                             'venv', '.pytest_cache', '.mypy_cache', 'dist', 'build'}

            for i, item in enumerate(items):
                # Skip ignored directories
                if item.name in ignore_patterns:
                    continue

                # Skip hidden files/dirs (except .gitignore, .env.example, etc.)
                if item.name.startswith('.') and item.name not in {'.gitignore', '.env.example',
                                                                    '.env', '.dockerignore'}:
                    continue

                is_last = i == len(items) - 1
                current_prefix = "└── " if is_last else "├── "
                next_prefix = "    " if is_last else "│   "

                if item.is_dir():
                    output.append(f"{prefix}{current_prefix}{item.name}/")
                    subtree = build_tree(item, prefix + next_prefix, depth + 1)
                    if subtree:
                        output.append(subtree)
                else:
                    output.append(f"{prefix}{current_prefix}{item.name}")

            return "\n".join(filter(None, output))

        tree = build_tree(root_path)

        if not tree:
            tree = "(empty or inaccessible directory)"

        # Add header with stats
        tree_lines = tree.split('\n')
        total_files = sum(1 for line in tree_lines if not line.strip().endswith('/'))
        total_dirs = sum(1 for line in tree_lines if line.strip().endswith('/'))

        content = f"Project: {root_path.name}\n"
        content += f"Directories: {total_dirs}, Files: {total_files}\n"
        content += f"Max depth: {max_depth}\n\n"
        content += tree

        # Truncate if too large (v1.13.8)
        truncated = False
        if len(content) > MAX_FILE_SIZE:
            content = content[:MAX_FILE_SIZE] + "\n\n... (tree truncated)"
            truncated = True

        return InjectedContext(
            source="@tree",
            content=content,
            language="text",
            truncated=truncated,
            size=len(content)
        )

    def inject_context(
        self,
        message: str,
        skip_hashes: Optional[Set[str]] = None
    ) -> Tuple[str, List[InjectedContext]]:
        """Process message and inject file/git/tree contents if appropriate.

        Args:
            message: User message
            skip_hashes: v1.13.10 - Set of content hashes to skip (deduplication)

        Returns:
            Tuple of (modified_message, list_of_injected_contexts)
        """
        injected = []
        total_size = 0
        cleaned_message = message
        skip_hashes = skip_hashes or set()

        # Check for @git pattern
        if re.search(self.GIT_PATTERN, message):
            git_ctx = self.inject_git_context()
            if git_ctx:
                # v1.13.10: Compute hash and skip if duplicate
                git_ctx.hash = compute_content_hash(git_ctx.content)
                if git_ctx.hash not in skip_hashes:
                    injected.append(git_ctx)
                    total_size += len(git_ctx.content)
                # Remove @git from message even if skipped (already in context)
                cleaned_message = re.sub(self.GIT_PATTERN, '`git diff`', cleaned_message)

        # Check for @tree pattern
        if re.search(self.TREE_PATTERN, message):
            tree_ctx = self.inject_tree_context()
            if tree_ctx:
                # v1.13.10: Compute hash and skip if duplicate
                tree_ctx.hash = compute_content_hash(tree_ctx.content)
                if tree_ctx.hash not in skip_hashes:
                    injected.append(tree_ctx)
                    total_size += len(tree_ctx.content)
                # Remove @tree from message even if skipped
                cleaned_message = re.sub(self.TREE_PATTERN, '`project tree`', cleaned_message)

        # Check for file references
        files = self.detect_file_references(message)

        if self.should_inject(message, files):
            for filepath in files:
                if total_size >= self.MAX_TOTAL_CONTEXT:
                    break

                ctx = self.read_file(filepath)
                if ctx:
                    # v1.13.10: Compute hash and skip if duplicate
                    ctx.hash = compute_content_hash(ctx.content)
                    if ctx.hash not in skip_hashes:
                        injected.append(ctx)
                        total_size += len(ctx.content)

            # Remove @ file references from message (they've been injected)
            # This prevents the AI from seeing @/path/file.ext and getting confused
            for filepath in files:
                # Remove @filepath patterns
                cleaned_message = re.sub(r'@' + re.escape(filepath) + r'\b', f'`{Path(filepath).name}`', cleaned_message)

        if not injected:
            return message, []

        # Build enhanced message with injected content
        enhanced = cleaned_message + "\n\n---\n**Attached context:**\n"

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
