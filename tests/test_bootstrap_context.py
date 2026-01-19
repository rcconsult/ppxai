"""
Tests for bootstrap context loading from AGENTS.md/CLAUDE.md files.

v1.14.0: Initial implementation
"""

import pytest
import tempfile
from pathlib import Path
from contextlib import contextmanager

from ppxai.engine.bootstrap import (
    BootstrapContext,
    find_bootstrap_file,
    DEFAULT_BOOTSTRAP_FILES,
    LOCAL_PROVIDERS,
)
from ppxai.engine.context import ContextInjector
from ppxai.config import (
    get_bootstrap_config,
    get_bootstrap_files,
    is_bootstrap_enabled,
    DEFAULT_BOOTSTRAP_FILES as CONFIG_DEFAULT_BOOTSTRAP_FILES,
)


@contextmanager
def temp_dir():
    """Create a temporary directory context manager."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestBootstrapContext:
    """Tests for BootstrapContext class."""

    def test_parse_simple_content(self):
        """Parse simple content without YAML front matter."""
        content = """# Project Rules

- Use TypeScript
- Follow ESLint rules
"""
        ctx = BootstrapContext.from_content(content, "test.md")
        assert ctx.base_instructions == content.strip()
        assert ctx.provider_hints == {}
        assert ctx.model_hints == {}
        assert not ctx.has_hints

    def test_parse_yaml_front_matter(self):
        """Parse content with YAML front matter."""
        content = """---
provider_hints:
  ollama:
    - "Complete tasks fully."
    - "Don't stop on empty responses."
  gemini:
    - "Use native search."
model_hints:
  "deepseek-r1*":
    - "Show reasoning."
---

# Project Rules

- Use TypeScript
"""
        ctx = BootstrapContext.from_content(content, "test.md")
        assert "Project Rules" in ctx.base_instructions
        assert "Use TypeScript" in ctx.base_instructions
        assert "ollama" in ctx.provider_hints
        assert len(ctx.provider_hints["ollama"]) == 2
        assert "Complete tasks fully." in ctx.provider_hints["ollama"]
        assert "gemini" in ctx.provider_hints
        assert "deepseek-r1*" in ctx.model_hints
        assert ctx.has_hints

    def test_parse_yaml_with_local_provider(self):
        """Parse YAML with 'local' provider hints."""
        content = """---
provider_hints:
  local:
    - "Use tools proactively."
  ollama:
    - "Ollama-specific hint."
---

Instructions here.
"""
        ctx = BootstrapContext.from_content(content, "test.md")
        assert "local" in ctx.provider_hints
        assert "ollama" in ctx.provider_hints

    def test_get_prompt_for_no_hints(self):
        """Get prompt when no hints match."""
        content = "# Project Rules\n\nUse TypeScript."
        ctx = BootstrapContext.from_content(content, "test.md")

        prompt = ctx.get_prompt_for("perplexity", "sonar-pro")
        assert prompt == "# Project Rules\n\nUse TypeScript."

    def test_get_prompt_for_provider_match(self):
        """Get prompt with provider hints."""
        content = """---
provider_hints:
  ollama:
    - "Complete tasks fully."
---

# Project Rules
"""
        ctx = BootstrapContext.from_content(content, "test.md")

        prompt = ctx.get_prompt_for("ollama", "llama3.2:3b")
        assert "Project Rules" in prompt
        assert "Provider Guidance" in prompt
        assert "Complete tasks fully." in prompt

    def test_get_prompt_for_local_inheritance(self):
        """Local provider hints apply to ollama, vllm, lmstudio."""
        content = """---
provider_hints:
  local:
    - "Local hint."
  ollama:
    - "Ollama hint."
---

Instructions.
"""
        ctx = BootstrapContext.from_content(content, "test.md")

        # Ollama should get both local and ollama hints
        prompt = ctx.get_prompt_for("ollama", "llama3.2:3b")
        assert "Local hint." in prompt
        assert "Ollama hint." in prompt

        # vLLM should get only local hints
        prompt = ctx.get_prompt_for("vllm", "some-model")
        assert "Local hint." in prompt
        assert "Ollama hint." not in prompt

        # Perplexity should get neither
        prompt = ctx.get_prompt_for("perplexity", "sonar-pro")
        assert "Local hint." not in prompt

    def test_get_prompt_for_model_regex_match(self):
        """Model hints use regex patterns."""
        content = """---
model_hints:
  "deepseek-r1*":
    - "Show reasoning."
  "qwen2.5-coder*":
    - "Prefer edit_file."
---

Instructions.
"""
        ctx = BootstrapContext.from_content(content, "test.md")

        # Should match
        prompt = ctx.get_prompt_for("ollama", "deepseek-r1:7b")
        assert "Show reasoning." in prompt

        # Should match
        prompt = ctx.get_prompt_for("ollama", "qwen2.5-coder:3b")
        assert "Prefer edit_file." in prompt

        # Should not match
        prompt = ctx.get_prompt_for("ollama", "llama3.2:3b")
        assert "Show reasoning." not in prompt
        assert "Prefer edit_file." not in prompt

    def test_char_count(self):
        """Test character count property."""
        content = "Hello world!"
        ctx = BootstrapContext.from_content(content, "test.md")
        assert ctx.char_count == len("Hello world!")

    def test_from_file(self):
        """Test loading from file."""
        with temp_dir() as d:
            (d / "AGENTS.md").write_text("Project rules here.")
            ctx = BootstrapContext.from_file(d / "AGENTS.md")
            assert ctx.base_instructions == "Project rules here."
            assert ctx.source_file == str(d / "AGENTS.md")


class TestFindBootstrapFile:
    """Tests for find_bootstrap_file function."""

    def test_finds_agents_md(self):
        """Find AGENTS.md in directory."""
        with temp_dir() as d:
            (d / "AGENTS.md").write_text("Rules")
            result = find_bootstrap_file(d)
            assert result is not None
            assert result.name == "AGENTS.md"

    def test_finds_claude_md_as_fallback(self):
        """Find CLAUDE.md when AGENTS.md doesn't exist."""
        with temp_dir() as d:
            (d / "CLAUDE.md").write_text("Rules")
            result = find_bootstrap_file(d)
            assert result is not None
            assert result.name == "CLAUDE.md"

    def test_agents_md_takes_priority(self):
        """AGENTS.md is preferred over CLAUDE.md."""
        with temp_dir() as d:
            (d / "AGENTS.md").write_text("AGENTS rules")
            (d / "CLAUDE.md").write_text("CLAUDE rules")
            result = find_bootstrap_file(d)
            assert result is not None
            assert result.name == "AGENTS.md"

    def test_custom_alias_list(self):
        """Custom alias list is respected."""
        with temp_dir() as d:
            (d / "COPILOT.md").write_text("Copilot rules")
            (d / "CLAUDE.md").write_text("Claude rules")
            result = find_bootstrap_file(d, ["COPILOT.md", "CLAUDE.md", "AGENTS.md"])
            assert result is not None
            assert result.name == "COPILOT.md"

    def test_custom_alias_fallback_order(self):
        """Falls back through alias list in order."""
        with temp_dir() as d:
            (d / "AI.md").write_text("AI rules")
            result = find_bootstrap_file(d, ["AGENTS.md", "CLAUDE.md", "AI.md"])
            assert result is not None
            assert result.name == "AI.md"

    def test_empty_alias_list_returns_none(self):
        """Empty alias list disables bootstrap."""
        with temp_dir() as d:
            (d / "AGENTS.md").write_text("Should be ignored")
            result = find_bootstrap_file(d, [])
            assert result is None

    def test_no_match_returns_none(self):
        """Returns None when no files match."""
        with temp_dir() as d:
            result = find_bootstrap_file(d)
            assert result is None

    def test_invalid_directory_returns_none(self):
        """Returns None for invalid directory."""
        result = find_bootstrap_file(Path("/nonexistent/path"))
        assert result is None


class TestContextInjector:
    """Tests for ContextInjector bootstrap methods."""

    def test_find_bootstrap_files_default(self):
        """Find bootstrap files with default aliases."""
        with temp_dir() as d:
            (d / "AGENTS.md").write_text("Project rules")
            injector = ContextInjector(working_dir=str(d))
            files = injector.find_bootstrap_files()
            assert len(files) == 1
            assert files[0].name == "AGENTS.md"

    def test_find_bootstrap_files_claude_fallback(self):
        """Fall back to CLAUDE.md."""
        with temp_dir() as d:
            (d / "CLAUDE.md").write_text("Claude instructions")
            injector = ContextInjector(working_dir=str(d))
            files = injector.find_bootstrap_files()
            assert len(files) == 1
            assert files[0].name == "CLAUDE.md"

    def test_find_bootstrap_files_agents_priority(self):
        """AGENTS.md takes priority over CLAUDE.md."""
        with temp_dir() as d:
            (d / "AGENTS.md").write_text("Agents rules")
            (d / "CLAUDE.md").write_text("Claude rules")
            injector = ContextInjector(working_dir=str(d))
            files = injector.find_bootstrap_files()
            assert len(files) == 1
            assert files[0].name == "AGENTS.md"

    def test_find_bootstrap_files_custom_aliases(self):
        """Custom alias list is respected."""
        with temp_dir() as d:
            (d / "COPILOT.md").write_text("Copilot rules")
            (d / "CLAUDE.md").write_text("Claude rules")
            injector = ContextInjector(
                working_dir=str(d),
                bootstrap_files=["COPILOT.md", "CLAUDE.md", "AGENTS.md"]
            )
            files = injector.find_bootstrap_files()
            assert len(files) == 1
            assert files[0].name == "COPILOT.md"

    def test_find_bootstrap_files_empty_aliases(self):
        """Empty alias list disables bootstrap."""
        with temp_dir() as d:
            (d / "AGENTS.md").write_text("Should be ignored")
            injector = ContextInjector(working_dir=str(d), bootstrap_files=[])
            files = injector.find_bootstrap_files()
            assert len(files) == 0

    def test_load_bootstrap_context(self):
        """Load and parse bootstrap context."""
        with temp_dir() as d:
            (d / "AGENTS.md").write_text("""---
provider_hints:
  ollama:
    - "Test hint."
---

# Rules
""")
            injector = ContextInjector(working_dir=str(d))
            ctx = injector.load_bootstrap_context()
            assert ctx is not None
            assert "Rules" in ctx.base_instructions
            assert "ollama" in ctx.provider_hints

    def test_load_bootstrap_context_no_file(self):
        """Returns None when no bootstrap file exists."""
        with temp_dir() as d:
            injector = ContextInjector(working_dir=str(d))
            ctx = injector.load_bootstrap_context()
            assert ctx is None


class TestBootstrapConfig:
    """Tests for bootstrap configuration."""

    def test_get_bootstrap_config_default(self):
        """Get default bootstrap config."""
        config = get_bootstrap_config()
        assert "files" in config
        assert "enabled" in config
        assert config["enabled"] is True
        assert config["files"] == CONFIG_DEFAULT_BOOTSTRAP_FILES

    def test_get_bootstrap_files_default(self):
        """Get default bootstrap files list."""
        files = get_bootstrap_files()
        assert files == CONFIG_DEFAULT_BOOTSTRAP_FILES
        assert "AGENTS.md" in files
        assert "CLAUDE.md" in files

    def test_is_bootstrap_enabled_default(self):
        """Bootstrap is enabled by default."""
        assert is_bootstrap_enabled() is True

    def test_default_bootstrap_files_match(self):
        """Bootstrap module and config have same defaults."""
        assert DEFAULT_BOOTSTRAP_FILES == CONFIG_DEFAULT_BOOTSTRAP_FILES


class TestLocalProviderInheritance:
    """Tests for LOCAL_PROVIDERS constant."""

    def test_local_providers_include_expected(self):
        """LOCAL_PROVIDERS includes ollama, vllm, lmstudio."""
        assert "ollama" in LOCAL_PROVIDERS
        assert "vllm" in LOCAL_PROVIDERS
        assert "lmstudio" in LOCAL_PROVIDERS

    def test_local_providers_exclude_cloud(self):
        """LOCAL_PROVIDERS does not include cloud providers."""
        assert "perplexity" not in LOCAL_PROVIDERS
        assert "openai" not in LOCAL_PROVIDERS
        assert "gemini" not in LOCAL_PROVIDERS


class TestYAMLParsing:
    """Tests for edge cases in YAML front matter parsing."""

    def test_parse_empty_front_matter(self):
        """Handle empty front matter (treated as no front matter)."""
        content = """---
---

# Content
"""
        ctx = BootstrapContext.from_content(content, "test.md")
        # Empty front matter is not detected (regex needs content between delimiters)
        # This is acceptable behavior - empty front matter is not useful anyway
        assert "# Content" in ctx.base_instructions
        assert ctx.provider_hints == {}
        assert ctx.model_hints == {}

    def test_parse_comments_in_yaml(self):
        """Handle comments in YAML."""
        content = """---
# This is a comment
provider_hints:
  # Another comment
  ollama:
    - "Hint"
---

Content.
"""
        ctx = BootstrapContext.from_content(content, "test.md")
        assert "ollama" in ctx.provider_hints

    def test_parse_quoted_patterns(self):
        """Handle quoted model patterns."""
        content = """---
model_hints:
  "deepseek-r1*":
    - "Hint for deepseek"
  'qwen*':
    - "Hint for qwen"
---

Content.
"""
        ctx = BootstrapContext.from_content(content, "test.md")
        assert "deepseek-r1*" in ctx.model_hints
        assert "qwen*" in ctx.model_hints

    def test_parse_unquoted_hints(self):
        """Handle unquoted hint values."""
        content = """---
provider_hints:
  ollama:
    - Unquoted hint here
    - "Quoted hint here"
---

Content.
"""
        ctx = BootstrapContext.from_content(content, "test.md")
        assert "Unquoted hint here" in ctx.provider_hints["ollama"]
        assert "Quoted hint here" in ctx.provider_hints["ollama"]

    def test_no_front_matter_delimiter(self):
        """Handle content without front matter delimiter."""
        content = """# Just a regular markdown file

No YAML here.
"""
        ctx = BootstrapContext.from_content(content, "test.md")
        assert ctx.base_instructions == content.strip()
        assert not ctx.has_hints
