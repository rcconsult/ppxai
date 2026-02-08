"""
Bootstrap context loading from AGENTS.md / CLAUDE.md files.

v1.14.0: Initial implementation with configurable file aliases and YAML front matter.
v1.14.2: Hierarchical context scopes (global, project, subdir) with merge support.

This module provides:
- BootstrapContext: Parses AGENTS.md with optional YAML front matter for provider/model hints
- find_bootstrap_file(): Discovers bootstrap files using configurable alias list
- find_git_root(): Finds git repository root for project scope
- ContextScope: Enum for scope labels (global, project, subdir)
- Prompt assembly with dynamic provider/model-aware hints

File Format:
```markdown
---
provider_hints:
  ollama:
    - "Complete tasks fully."
  local:
    - "Use tools proactively."
model_hints:
  "deepseek-r1*":
    - "Show reasoning."
---

# Project Instructions
Your content here...
```

Scope Precedence (v1.14.2):
1. ~/.ppxai/AGENTS.md (global defaults)
2. {git_root}/AGENTS.md (project-specific)
3. {cwd}/AGENTS.md (subdirectory overrides)
"""

import os
import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple, Set
from dataclasses import dataclass, field


class ContextScope(Enum):
    """Scope levels for bootstrap context files (v1.14.2)."""
    GLOBAL = "global"      # ~/.ppxai/AGENTS.md
    PROJECT = "project"    # {git_root}/AGENTS.md
    SUBDIR = "subdir"      # {cwd}/AGENTS.md


# Local providers that inherit from 'local' hints
LOCAL_PROVIDERS = {"ollama", "vllm", "lmstudio"}

# Default bootstrap file aliases (checked in order)
DEFAULT_BOOTSTRAP_FILES = ["AGENTS.md", "CLAUDE.md", "INSTRUCTIONS.md"]

# Hint templates file location (v1.14.2)
HINT_TEMPLATES_FILE = Path.home() / ".ppxai" / "hint-templates.yaml"

# Cache for loaded templates
_hint_templates_cache: Optional[Dict[str, List[str]]] = None


def load_hint_templates() -> Dict[str, List[str]]:
    """Load hint templates from ~/.ppxai/hint-templates.yaml (v1.14.2).

    Templates allow defining reusable hint collections:

    ```yaml
    templates:
      tool-heavy:
        - "Use tools proactively."
        - "Don't stop after tool calls."
      reasoning:
        - "Show step-by-step reasoning."
    ```

    Returns:
        Dict mapping template name to list of hints
    """
    global _hint_templates_cache

    if _hint_templates_cache is not None:
        return _hint_templates_cache

    _hint_templates_cache = {}

    if not HINT_TEMPLATES_FILE.exists():
        return _hint_templates_cache

    try:
        import yaml
        content = HINT_TEMPLATES_FILE.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        if isinstance(data, dict) and "templates" in data:
            templates = data["templates"]
            if isinstance(templates, dict):
                for name, hints in templates.items():
                    if isinstance(hints, list):
                        _hint_templates_cache[name] = [str(h) for h in hints]
    except ImportError:
        # YAML not available, try simple parsing
        _hint_templates_cache = _parse_templates_simple(HINT_TEMPLATES_FILE)
    except Exception:
        # Failed to load, return empty
        pass

    return _hint_templates_cache


def _parse_templates_simple(file_path: Path) -> Dict[str, List[str]]:
    """Parse hint templates without YAML library.

    Simple regex-based parsing for the specific format we need.
    """
    result: Dict[str, List[str]] = {}
    content = file_path.read_text(encoding="utf-8")

    # Find templates: section
    templates_match = re.search(r'^templates:\s*\n((?:[ \t]+.*\n?)*)', content, re.MULTILINE)
    if not templates_match:
        return result

    section = templates_match.group(1)
    current_name = None
    current_hints: List[str] = []

    for line in section.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # Check for template name (e.g., "  tool-heavy:")
        name_match = re.match(r'^[ \t]+([a-zA-Z0-9_-]+):\s*$', line)
        if name_match:
            if current_name is not None:
                result[current_name] = current_hints
            current_name = name_match.group(1)
            current_hints = []
            continue

        # Check for hint item
        hint_match = re.match(r'^\s+-\s*["\']?(.+?)["\']?\s*$', line)
        if hint_match and current_name is not None:
            current_hints.append(hint_match.group(1))

    if current_name is not None:
        result[current_name] = current_hints

    return result


def clear_templates_cache() -> None:
    """Clear the templates cache (for testing/reload)."""
    global _hint_templates_cache
    _hint_templates_cache = None


@dataclass
class BootstrapContext:
    """Parsed bootstrap context from AGENTS.md or similar files.

    Attributes:
        source_file: Path to the source file
        base_instructions: Content below the YAML front matter
        provider_hints: Provider-specific hints (provider_id -> list of hints)
        model_hints: Model-specific hints (regex pattern -> list of hints)
        raw_content: Original file content
    """
    source_file: str = ""
    base_instructions: str = ""
    provider_hints: Dict[str, List[str]] = field(default_factory=dict)
    model_hints: Dict[str, List[str]] = field(default_factory=dict)
    raw_content: str = ""

    # Include directive settings (v1.14.2)
    MAX_INCLUDE_DEPTH = 5
    INCLUDE_PATTERN = re.compile(r'<!--\s*include:\s*([^\s>]+)\s*-->', re.IGNORECASE)

    @classmethod
    def from_file(cls, file_path: Path) -> "BootstrapContext":
        """Parse a bootstrap file and return BootstrapContext.

        Processes include directives (v1.14.2):
        <!-- include: ./path/to/file.md -->

        Args:
            file_path: Path to AGENTS.md or similar file

        Returns:
            Parsed BootstrapContext instance
        """
        content = file_path.read_text(encoding="utf-8", errors="replace")
        # Process include directives (v1.14.2)
        content = cls._process_includes(content, file_path.parent, set(), 0)
        return cls.from_content(content, str(file_path))

    @classmethod
    def _process_includes(
        cls,
        content: str,
        base_dir: Path,
        visited: Set[Path],
        depth: int
    ) -> str:
        """Process include directives in content (v1.14.2).

        Replaces <!-- include: path --> with file contents.

        Args:
            content: Content to process
            base_dir: Base directory for resolving relative paths
            visited: Set of already-visited paths (cycle detection)
            depth: Current include depth

        Returns:
            Content with includes expanded
        """
        if depth >= cls.MAX_INCLUDE_DEPTH:
            return content

        def replace_include(match: re.Match) -> str:
            include_path_str = match.group(1)

            # Resolve path relative to base_dir
            include_path = (base_dir / include_path_str).resolve()

            # Security: prevent path traversal outside base_dir ancestors
            # Allow includes from anywhere under home or working directory
            try:
                # Just ensure it's a real file, not a symlink attack
                if not include_path.is_file():
                    return f"<!-- include error: {include_path_str} not found -->"
            except (OSError, ValueError):
                return f"<!-- include error: invalid path {include_path_str} -->"

            # Cycle detection
            if include_path in visited:
                return f"<!-- include error: circular include {include_path_str} -->"

            # Read and recursively process
            try:
                included_content = include_path.read_text(encoding="utf-8", errors="replace")
                new_visited = visited | {include_path}
                included_content = cls._process_includes(
                    included_content,
                    include_path.parent,
                    new_visited,
                    depth + 1
                )
                # Add source marker for debugging
                return f"\n<!-- begin: {include_path_str} -->\n{included_content}\n<!-- end: {include_path_str} -->\n"
            except Exception as e:
                return f"<!-- include error: {include_path_str}: {e} -->"

        return cls.INCLUDE_PATTERN.sub(replace_include, content)

    @classmethod
    def from_content(cls, content: str, source: str = "") -> "BootstrapContext":
        """Parse bootstrap content string.

        Args:
            content: Raw file content
            source: Source identifier (file path or description)

        Returns:
            Parsed BootstrapContext instance
        """
        ctx = cls(source_file=source, raw_content=content)
        ctx._parse(content)
        return ctx

    def _parse(self, content: str) -> None:
        """Parse content, extracting YAML front matter if present."""
        # Check for YAML front matter (starts with ---)
        front_matter_pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(front_matter_pattern, content, re.DOTALL)

        if match:
            yaml_content = match.group(1)
            self.base_instructions = match.group(2).strip()
            self._parse_yaml_front_matter(yaml_content)
        else:
            # No front matter, entire content is instructions
            self.base_instructions = content.strip()

    def _parse_yaml_front_matter(self, yaml_content: str) -> None:
        """Parse YAML front matter for provider/model hints.

        Uses simple regex-based parsing to avoid YAML library dependency.
        Supports the specific format we need without full YAML complexity.
        """
        # Parse provider_hints section
        provider_section = self._extract_section(yaml_content, "provider_hints")
        if provider_section:
            self.provider_hints = self._parse_hints_section(provider_section)

        # Parse model_hints section
        model_section = self._extract_section(yaml_content, "model_hints")
        if model_section:
            self.model_hints = self._parse_hints_section(model_section)

    def _extract_section(self, yaml_content: str, section_name: str) -> Optional[str]:
        """Extract a section from YAML content.

        Args:
            yaml_content: YAML content string
            section_name: Name of section to extract (e.g., "provider_hints")

        Returns:
            Section content or None if not found
        """
        # Match section_name: followed by indented content
        pattern = rf'^{section_name}:\s*\n((?:[ \t]+.*\n?)*)'
        match = re.search(pattern, yaml_content, re.MULTILINE)
        if match:
            return match.group(1)
        return None

    def _parse_hints_section(self, section: str) -> Dict[str, List[str]]:
        """Parse a hints section into dict of key -> list of hints.

        Expects format:
          key:
            - "hint 1"
            - "hint 2"
            - template: template-name  # v1.14.2: expands to template hints

        Template references are expanded using ~/.ppxai/hint-templates.yaml
        """
        result: Dict[str, List[str]] = {}
        current_key = None
        current_hints: List[str] = []

        # Load templates for expansion (v1.14.2)
        templates = load_hint_templates()

        for line in section.split('\n'):
            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            # Check for new key (e.g., "ollama:" or '"pattern":')
            key_match = re.match(r'^[\s]*["\']?([^"\':\s]+)["\']?\s*:\s*$', line)
            if key_match and not line.strip().startswith('-'):
                # Save previous key's hints
                if current_key is not None:
                    result[current_key] = current_hints
                current_key = key_match.group(1)
                current_hints = []
                continue

            # Check for template reference (v1.14.2): - template: name
            template_match = re.match(r'^\s*-\s*template:\s*([a-zA-Z0-9_-]+)\s*$', line)
            if template_match and current_key is not None:
                template_name = template_match.group(1)
                if template_name in templates:
                    current_hints.extend(templates[template_name])
                # Silently skip unknown templates
                continue

            # Check for hint item (e.g., '- "hint text"')
            hint_match = re.match(r'^\s*-\s*["\'](.+)["\']$', line)
            if hint_match and current_key is not None:
                current_hints.append(hint_match.group(1))
                continue

            # Also support unquoted hints
            hint_match_unquoted = re.match(r'^\s*-\s*(.+)$', line)
            if hint_match_unquoted and current_key is not None:
                hint_text = hint_match_unquoted.group(1).strip().strip('"\'')
                if hint_text:
                    current_hints.append(hint_text)

        # Don't forget the last key
        if current_key is not None:
            result[current_key] = current_hints

        return result

    def get_prompt_for(self, provider: str, model: str) -> str:
        """Build system prompt for current provider/model.

        Args:
            provider: Current provider ID (e.g., "ollama", "gemini")
            model: Current model ID (e.g., "llama3.2:3b", "gemini-2.0-flash")

        Returns:
            Assembled prompt string with base instructions and applicable hints
        """
        parts = []

        # Add base instructions
        if self.base_instructions:
            parts.append(self.base_instructions)

        # Add provider hints (with 'local' inheritance)
        hints = self._get_provider_hints(provider)
        if hints:
            parts.append("\n## Provider Guidance\n" + "\n".join(f"- {h}" for h in hints))

        # Add model hints (regex match)
        model_hints = self._get_model_hints(model)
        if model_hints:
            parts.append("\n## Model Guidance\n" + "\n".join(f"- {h}" for h in model_hints))

        return "\n".join(parts)

    def _get_provider_hints(self, provider: str) -> List[str]:
        """Get hints for provider, with 'local' inheritance.

        Args:
            provider: Provider ID

        Returns:
            List of applicable hints (local hints + provider-specific hints)
        """
        hints: List[str] = []

        # Add 'local' hints first for local providers
        if provider in LOCAL_PROVIDERS and "local" in self.provider_hints:
            hints.extend(self.provider_hints["local"])

        # Add provider-specific hints
        if provider in self.provider_hints:
            hints.extend(self.provider_hints[provider])

        return hints

    def _get_model_hints(self, model: str) -> List[str]:
        """Get hints matching model via regex patterns.

        Args:
            model: Model ID to match

        Returns:
            List of all matching hints (patterns can overlap)
        """
        hints: List[str] = []

        for pattern, pattern_hints in self.model_hints.items():
            # Convert glob-style pattern to regex
            regex = pattern.replace("*", ".*")
            try:
                if re.match(regex, model, re.IGNORECASE):
                    hints.extend(pattern_hints)
            except re.error:
                # Invalid regex, skip
                continue

        return hints

    def get_active_hints_for(self, provider: str, model: str) -> Dict[str, Any]:
        """Get detailed breakdown of active hints for provider/model.

        Args:
            provider: Current provider ID
            model: Current model ID

        Returns:
            Dict with:
            - provider_hints: List of (source, hint) tuples
            - model_hints: List of (pattern, hint) tuples
            - inherited_local: bool - whether 'local' hints were inherited
            - matched_patterns: List of matched model patterns
        """
        result: Dict[str, Any] = {
            "provider_hints": [],
            "model_hints": [],
            "inherited_local": False,
            "matched_patterns": [],
        }

        # Check for 'local' inheritance
        if provider in LOCAL_PROVIDERS and "local" in self.provider_hints:
            result["inherited_local"] = True
            for hint in self.provider_hints["local"]:
                result["provider_hints"].append(("local", hint))

        # Provider-specific hints
        if provider in self.provider_hints:
            for hint in self.provider_hints[provider]:
                result["provider_hints"].append((provider, hint))

        # Model hints with pattern tracking
        for pattern, pattern_hints in self.model_hints.items():
            regex = pattern.replace("*", ".*")
            try:
                if re.match(regex, model, re.IGNORECASE):
                    result["matched_patterns"].append(pattern)
                    for hint in pattern_hints:
                        result["model_hints"].append((pattern, hint))
            except re.error:
                continue

        return result

    @property
    def char_count(self) -> int:
        """Get total character count of base instructions."""
        return len(self.base_instructions)

    @property
    def has_hints(self) -> bool:
        """Check if any provider or model hints are defined."""
        return bool(self.provider_hints or self.model_hints)


def find_bootstrap_file(
    directory: Path,
    aliases: Optional[List[str]] = None
) -> Optional[Path]:
    """Find first matching bootstrap file in directory.

    Args:
        directory: Directory to search
        aliases: List of filenames to check (in order). Defaults to DEFAULT_BOOTSTRAP_FILES.

    Returns:
        Path to first matching file, or None if no match
    """
    if aliases is None:
        aliases = DEFAULT_BOOTSTRAP_FILES

    if not aliases:
        return None  # Empty list means bootstrap is disabled

    for filename in aliases:
        path = directory / filename
        if path.is_file():
            return path

    return None


def get_bootstrap_files_config() -> List[str]:
    """Get bootstrap file aliases from config.

    Returns:
        List of filenames to search for, or default list
    """
    try:
        from ..config import get_bootstrap_config
        config = get_bootstrap_config()
        return config.get("files", DEFAULT_BOOTSTRAP_FILES)
    except ImportError:
        return DEFAULT_BOOTSTRAP_FILES


def is_bootstrap_enabled() -> bool:
    """Check if bootstrap context loading is enabled.

    Returns:
        True if bootstrap is enabled in config
    """
    try:
        from ..config import get_bootstrap_config
        config = get_bootstrap_config()
        return config.get("enabled", True)
    except ImportError:
        return True


def find_git_root(start_path: Optional[Path] = None) -> Optional[Path]:
    """Find the git repository root starting from a given path.

    Walks up the directory tree looking for a .git directory.
    Falls back to `git rev-parse --show-toplevel` if needed.

    Args:
        start_path: Starting directory (default: current working directory)

    Returns:
        Path to git root, or None if not in a git repository
    """
    if start_path is None:
        start_path = Path.cwd()

    start_path = Path(start_path).resolve()

    # Method 1: Walk up looking for .git directory (fast, no subprocess)
    current = start_path
    while current != current.parent:
        git_dir = current / ".git"
        if git_dir.exists():
            return current
        current = current.parent

    # Check root as well
    if (current / ".git").exists():
        return current

    # Method 2: Fall back to git command (handles worktrees, submodules)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start_path),
            capture_output=True,
            text=True,
            check=False,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return None


def get_global_config_dir() -> Path:
    """Get the global ppxai config directory.

    Returns:
        Path to ~/.ppxai/
    """
    return Path.home() / ".ppxai"


def find_bootstrap_files_by_scope(
    working_dir: Path,
    aliases: Optional[List[str]] = None
) -> List[Tuple[Path, ContextScope]]:
    """Find bootstrap files across all scopes (v1.14.2).

    Searches in precedence order:
    1. Global: ~/.ppxai/AGENTS.md
    2. Project: {git_root}/AGENTS.md
    3. Subdir: {cwd}/AGENTS.md (if different from git root)

    Args:
        working_dir: Current working directory
        aliases: List of filenames to check (default: DEFAULT_BOOTSTRAP_FILES)

    Returns:
        List of (path, scope) tuples in precedence order (global first).
        Only includes files that exist. Each scope returns at most one file.
    """
    if aliases is None:
        aliases = get_bootstrap_files_config()

    if not aliases:
        return []  # Bootstrap disabled

    results: List[Tuple[Path, ContextScope]] = []
    seen_paths: set[Path] = set()  # Avoid duplicates

    working_dir = Path(working_dir).resolve()

    # 1. Global scope: ~/.ppxai/
    global_dir = get_global_config_dir()
    if global_dir.exists() and global_dir.is_dir():
        global_file = find_bootstrap_file(global_dir, aliases)
        if global_file:
            resolved = global_file.resolve()
            results.append((resolved, ContextScope.GLOBAL))
            seen_paths.add(resolved)

    # 2. Project scope: git root
    git_root = find_git_root(working_dir)
    if git_root:
        project_file = find_bootstrap_file(git_root, aliases)
        if project_file:
            resolved = project_file.resolve()
            if resolved not in seen_paths:
                results.append((resolved, ContextScope.PROJECT))
                seen_paths.add(resolved)

    # 3. Subdir scope: working directory (if different from git root)
    # Only add if cwd is different from git root
    if working_dir != git_root:
        subdir_file = find_bootstrap_file(working_dir, aliases)
        if subdir_file:
            resolved = subdir_file.resolve()
            if resolved not in seen_paths:
                results.append((resolved, ContextScope.SUBDIR))
                seen_paths.add(resolved)

    return results
