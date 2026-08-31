"""
Context injection for automatic file/URL content inclusion.

Detects file references in messages and injects content directly into prompts,
eliminating the need for tool calls for simple file reading operations.

v1.13.9: Configurable max_injection_size via ppxai-config.json
v1.13.10: Content hash deduplication to prevent duplicate injections
v1.14.0: Bootstrap context loading from AGENTS.md/CLAUDE.md
v1.14.2: Hierarchical context scopes (global, project, subdir)
"""

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional, Set, Dict

from .bootstrap import BootstrapContext, find_bootstrap_files_by_scope
from ..common.logger import get_logger
from ..config import get_bootstrap_files, get_max_injection_size, is_bootstrap_enabled

import httpx
import pyperclip

logger = get_logger("tui")

try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]  # Truly optional, not in any extras group


@dataclass
class InjectedContext:
    """Represents injected content."""
    source: str          # file path or URL
    content: str         # the actual content
    language: str        # detected language (for code files)
    truncated: bool      # whether content was truncated
    size: int            # original size in bytes
    hash: str = ""       # content hash for deduplication


@dataclass
class ScopedBootstrapSource:
    """Bootstrap file with scope information (v1.14.2)."""
    path: Path           # Full path to bootstrap file
    scope: str           # "global", "project", or "subdir"
    size: int            # File size in bytes
    content: str = ""    # File content (loaded on demand)


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
        return get_max_injection_size()
    except Exception:
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

    # Default bootstrap file aliases (v1.14.0)
    DEFAULT_BOOTSTRAP_FILES = ["AGENTS.md", "CLAUDE.md"]

    # Patterns for special context providers
    GIT_PATTERN = r'@git\b'
    TREE_PATTERN = r'@tree\b'
    CLIPBOARD_PATTERN = r'@clipboard\b'  # v1.14.2: clipboard content injection
    URL_PATTERN = r'@(https?://[^\s<>\"\']+)'  # v1.14.2: URL content injection

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

    def __init__(
        self,
        working_dir: Optional[str] = None,
        bootstrap_files: Optional[List[str]] = None
    ):
        """Initialize the context injector.

        Args:
            working_dir: Base directory for resolving relative paths
            bootstrap_files: List of filenames to search for bootstrap context (v1.14.0)
        """
        self.working_dir = working_dir or os.getcwd()
        self._bootstrap_files = bootstrap_files  # None = use config default

    def set_working_dir(self, path: str):
        """Set the working directory for relative paths."""
        self.working_dir = path

    @property
    def bootstrap_files(self) -> List[str]:
        """Get bootstrap file aliases (from init or config).

        Returns:
            List of filenames to search for bootstrap context
        """
        if self._bootstrap_files is not None:
            return self._bootstrap_files
        # Load from config if not explicitly set
        try:
            return get_bootstrap_files()
        except Exception:
            return self.DEFAULT_BOOTSTRAP_FILES

    def find_bootstrap_files(self) -> List[Path]:
        """Find bootstrap files (AGENTS.md, CLAUDE.md, etc.) in working directory.

        Searches for files in the configured alias list, returning the first match.
        Only one file is returned per directory (first match wins).

        NOTE: This is the legacy method for backwards compatibility.
        For hierarchical scopes, use find_bootstrap_files_with_scopes() instead.

        Returns:
            List containing the first matching bootstrap file, or empty list
        """
        # Check if bootstrap is enabled
        try:
            if not is_bootstrap_enabled():
                return []
        except Exception as e:
            logger.debug(f"Bootstrap enabled check failed: {e}")

        aliases = self.bootstrap_files
        if not aliases:
            return []

        work_dir = Path(self.working_dir)
        if not work_dir.exists() or not work_dir.is_dir():
            return []

        # Find first matching file
        for filename in aliases:
            path = work_dir / filename
            if path.is_file():
                return [path]

        return []

    def find_bootstrap_files_with_scopes(self) -> List[ScopedBootstrapSource]:
        """Find bootstrap files across all scopes (v1.14.2).

        Searches in precedence order:
        1. Global: ~/.ppxai/AGENTS.md
        2. Project: {git_root}/AGENTS.md
        3. Subdir: {cwd}/AGENTS.md (if different from git root)

        Returns:
            List of ScopedBootstrapSource in precedence order (global first)
        """
        # Check if bootstrap is enabled
        try:
            if not is_bootstrap_enabled():
                return []
        except Exception as e:
            logger.debug(f"Bootstrap enabled check failed (merged): {e}")

        work_dir = Path(self.working_dir)
        if not work_dir.exists() or not work_dir.is_dir():
            return []

        scoped_files = find_bootstrap_files_by_scope(work_dir, self.bootstrap_files)

        results: List[ScopedBootstrapSource] = []
        for path, scope in scoped_files:
            try:
                size = path.stat().st_size
                results.append(ScopedBootstrapSource(
                    path=path,
                    scope=scope.value,
                    size=size
                ))
            except OSError:
                continue

        return results

    def load_bootstrap_context(self) -> Optional[BootstrapContext]:
        """Load and parse bootstrap context from working directory.

        Returns:
            BootstrapContext if found, None otherwise
        """
        files = self.find_bootstrap_files()
        if not files:
            return None

        try:
            return BootstrapContext.from_file(files[0])
        except Exception:
            return None

    def load_bootstrap_context_merged(self) -> Tuple[Optional[BootstrapContext], List[ScopedBootstrapSource]]:
        """Load and merge bootstrap context from all scopes (v1.14.2).

        Merges files from global → project → subdir:
        - Provider/model hints are combined (additive)
        - Base instructions are concatenated with source markers

        Returns:
            Tuple of (merged BootstrapContext, list of ScopedBootstrapSource)
        """
        sources = self.find_bootstrap_files_with_scopes()
        if not sources:
            return None, []

        # Parse each file individually to preserve YAML front matter parsing
        parsed_contexts: List[Tuple[BootstrapContext, ScopedBootstrapSource]] = []
        for source in sources:
            try:
                source.content = source.path.read_text(encoding="utf-8", errors="replace")
                ctx = BootstrapContext.from_content(source.content, str(source.path))
                parsed_contexts.append((ctx, source))
            except OSError:
                continue

        if not parsed_contexts:
            return None, []

        # Merge provider_hints, model_hints, and tool_calling_overrides (additive)
        merged_provider_hints: Dict[str, List[str]] = {}
        merged_model_hints: Dict[str, List[str]] = {}
        merged_tc_overrides: Dict[str, Dict] = {}

        # Combine base instructions with source markers
        instruction_parts: List[str] = []

        for ctx, source in parsed_contexts:
            # Add provider hints (merge lists, don't overwrite)
            for provider, hints in ctx.provider_hints.items():
                if provider not in merged_provider_hints:
                    merged_provider_hints[provider] = []
                merged_provider_hints[provider].extend(hints)

            # Add model hints (merge lists, don't overwrite)
            for pattern, hints in ctx.model_hints.items():
                if pattern not in merged_model_hints:
                    merged_model_hints[pattern] = []
                merged_model_hints[pattern].extend(hints)

            # Add tool_calling overrides (merge dicts, later scopes override)
            for pattern, overrides in ctx.tool_calling_overrides.items():
                if pattern not in merged_tc_overrides:
                    merged_tc_overrides[pattern] = {}
                merged_tc_overrides[pattern].update(overrides)

            # Add base instructions with source marker
            if ctx.base_instructions:
                marker = f"<!-- Source: {source.path} [{source.scope}] -->"
                instruction_parts.append(f"{marker}\n{ctx.base_instructions}")

        # Build merged context
        merged_instructions = "\n\n---\n\n".join(instruction_parts) if instruction_parts else ""

        # Create final merged context
        merged_ctx = BootstrapContext(
            source_file=f"merged ({len(parsed_contexts)} files)",
            base_instructions=merged_instructions,
            provider_hints=merged_provider_hints,
            model_hints=merged_model_hints,
            tool_calling_overrides=merged_tc_overrides,
            raw_content=merged_instructions,
        )

        return merged_ctx, sources

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

            content = path.read_text(errors='replace', encoding="utf-8")
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

    def inject_clipboard_context(self) -> Optional[InjectedContext]:
        """Inject clipboard text content (v1.14.2).

        Returns:
            InjectedContext with clipboard content or None if empty/unavailable
        """
        if pyperclip is None:
            return None

        try:
            content = pyperclip.paste()
        except Exception:
            # Clipboard access failed (no display, etc.)
            return None

        if not content or not content.strip():
            return None

        # Truncate if too large
        truncated = False
        original_size = len(content)
        if len(content) > self.MAX_FILE_SIZE:
            content = content[:self.MAX_FILE_SIZE] + "\n\n... (clipboard content truncated)"
            truncated = True

        # Try to detect language from content
        language = self._detect_clipboard_language(content)

        return InjectedContext(
            source="@clipboard",
            content=content,
            language=language,
            truncated=truncated,
            size=original_size
        )

    def _detect_clipboard_language(self, content: str) -> str:
        """Detect programming language from clipboard content.

        Uses simple heuristics to guess the language.

        Args:
            content: Clipboard text content

        Returns:
            Language identifier or empty string
        """
        content_lower = content.strip().lower()
        first_line = content.strip().split('\n')[0] if content.strip() else ""

        # Check for common patterns
        if first_line.startswith('#!/usr/bin/env python') or first_line.startswith('#!/usr/bin/python'):
            return 'python'
        if first_line.startswith('#!/bin/bash') or first_line.startswith('#!/bin/sh'):
            return 'bash'
        if 'def ' in content and ':' in content:
            return 'python'
        if 'function ' in content and ('{' in content or '=>' in content):
            return 'javascript'
        if content_lower.startswith('{') and content_lower.rstrip().endswith('}'):
            return 'json'
        if content_lower.startswith('<?xml') or content_lower.startswith('<html'):
            return 'xml' if '<?xml' in content_lower else 'html'

        return 'text'

    def inject_url_context(self, url: str) -> Optional[InjectedContext]:
        """Fetch and inject URL content (v1.14.2).

        Args:
            url: URL to fetch

        Returns:
            InjectedContext with page content or None on error
        """
        if httpx is None:
            return InjectedContext(
                source=url,
                content="Error fetching URL: httpx is not installed",
                language="text",
                truncated=False,
                size=0
            )

        try:
            # Fetch with reasonable timeout and headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; ppxai/1.14.2; +https://github.com/rcconsult/ppxai)'
            }
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                content = response.text
        except Exception as e:
            # Return error context so user knows fetch failed
            return InjectedContext(
                source=url,
                content=f"Error fetching URL: {e}",
                language="text",
                truncated=False,
                size=0
            )

        # Convert HTML to plain text if needed
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' in content_type:
            content = self._html_to_text(content)
            language = 'text'
        elif 'application/json' in content_type:
            language = 'json'
        elif 'text/markdown' in content_type:
            language = 'markdown'
        else:
            # Detect from URL extension
            language = self._detect_language(Path(url.split('?')[0]).suffix)

        # Truncate if too large
        truncated = False
        original_size = len(content)
        if len(content) > self.MAX_FILE_SIZE:
            content = content[:self.MAX_FILE_SIZE] + "\n\n... (content truncated)"
            truncated = True

        return InjectedContext(
            source=url,
            content=content,
            language=language or 'text',
            truncated=truncated,
            size=original_size
        )

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to readable plain text.

        Simple extraction - removes tags, scripts, styles.
        For better extraction, install trafilatura.

        Args:
            html: HTML content

        Returns:
            Plain text content
        """
        # Try trafilatura if available (better extraction)
        if trafilatura is not None:
            text = trafilatura.extract(html)
            if text:
                return text

        # Fallback: simple regex-based extraction
        # Remove script and style elements
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML comments
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

        # Replace common block elements with newlines
        text = re.sub(r'<(br|p|div|h[1-6]|li|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)

        # Remove all remaining tags
        text = re.sub(r'<[^>]+>', '', text)

        # Decode common HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")

        # Clean up whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        return text.strip()

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
                # Compute hash and skip if duplicate
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
                # Compute hash and skip if duplicate
                tree_ctx.hash = compute_content_hash(tree_ctx.content)
                if tree_ctx.hash not in skip_hashes:
                    injected.append(tree_ctx)
                    total_size += len(tree_ctx.content)
                # Remove @tree from message even if skipped
                cleaned_message = re.sub(self.TREE_PATTERN, '`project tree`', cleaned_message)

        # Check for @clipboard pattern (v1.14.2)
        if re.search(self.CLIPBOARD_PATTERN, message):
            clip_ctx = self.inject_clipboard_context()
            if clip_ctx:
                clip_ctx.hash = compute_content_hash(clip_ctx.content)
                if clip_ctx.hash not in skip_hashes:
                    injected.append(clip_ctx)
                    total_size += len(clip_ctx.content)
                cleaned_message = re.sub(self.CLIPBOARD_PATTERN, '`clipboard`', cleaned_message)

        # Check for @url patterns (v1.14.2)
        url_matches = re.findall(self.URL_PATTERN, message)
        for url in url_matches:
            if total_size >= self.MAX_TOTAL_CONTEXT:
                break
            url_ctx = self.inject_url_context(url)
            if url_ctx:
                url_ctx.hash = compute_content_hash(url_ctx.content)
                if url_ctx.hash not in skip_hashes:
                    injected.append(url_ctx)
                    total_size += len(url_ctx.content)
                # Replace @url with markdown link
                cleaned_message = cleaned_message.replace(f'@{url}', f'[{url}]({url})')

        # Check for file references
        files = self.detect_file_references(message)

        if self.should_inject(message, files):
            for filepath in files:
                if total_size >= self.MAX_TOTAL_CONTEXT:
                    break

                ctx = self.read_file(filepath)
                if ctx:
                    # Compute hash and skip if duplicate
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
