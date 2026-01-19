"""
Bootstrap context loading from AGENTS.md / CLAUDE.md files.

v1.14.0: Initial implementation with configurable file aliases and YAML front matter.

This module provides:
- BootstrapContext: Parses AGENTS.md with optional YAML front matter for provider/model hints
- find_bootstrap_file(): Discovers bootstrap files using configurable alias list
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
"""

import re
from pathlib import Path
from typing import Any, Optional, Dict, List
from dataclasses import dataclass, field


# Local providers that inherit from 'local' hints
LOCAL_PROVIDERS = {"ollama", "vllm", "lmstudio"}

# Default bootstrap file aliases (checked in order)
DEFAULT_BOOTSTRAP_FILES = ["AGENTS.md", "CLAUDE.md"]


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

    @classmethod
    def from_file(cls, file_path: Path) -> "BootstrapContext":
        """Parse a bootstrap file and return BootstrapContext.

        Args:
            file_path: Path to AGENTS.md or similar file

        Returns:
            Parsed BootstrapContext instance
        """
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return cls.from_content(content, str(file_path))

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
        """
        result: Dict[str, List[str]] = {}
        current_key = None
        current_hints: List[str] = []

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
