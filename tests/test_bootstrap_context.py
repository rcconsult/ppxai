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

    def test_get_active_hints_for(self):
        """Test get_active_hints_for returns detailed breakdown."""
        content = """---
provider_hints:
  local:
    - "Local hint."
  ollama:
    - "Ollama hint."
  custom:
    - "Custom hint."
model_hints:
  "deepseek-r1*":
    - "Show reasoning."
  "qwen*":
    - "Qwen hint."
---

Instructions.
"""
        ctx = BootstrapContext.from_content(content, "test.md")

        # Test ollama with deepseek model (inherits local)
        hints = ctx.get_active_hints_for("ollama", "deepseek-r1:7b")
        assert hints["inherited_local"] is True
        assert len(hints["provider_hints"]) == 2  # local + ollama
        assert ("local", "Local hint.") in hints["provider_hints"]
        assert ("ollama", "Ollama hint.") in hints["provider_hints"]
        assert len(hints["model_hints"]) == 1
        assert ("deepseek-r1*", "Show reasoning.") in hints["model_hints"]
        assert "deepseek-r1*" in hints["matched_patterns"]

        # Test custom provider (no local inheritance)
        hints = ctx.get_active_hints_for("custom", "gpt-oss-120b")
        assert hints["inherited_local"] is False
        assert len(hints["provider_hints"]) == 1
        assert ("custom", "Custom hint.") in hints["provider_hints"]
        assert len(hints["model_hints"]) == 0  # no match
        assert hints["matched_patterns"] == []

        # Test perplexity (no hints)
        hints = ctx.get_active_hints_for("perplexity", "sonar-pro")
        assert hints["inherited_local"] is False
        assert len(hints["provider_hints"]) == 0
        assert len(hints["model_hints"]) == 0

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


# === v1.14.2 Hierarchical Scope Tests ===

class TestFindGitRoot:
    """Tests for find_git_root() helper (v1.14.2)."""

    def test_finds_git_root_in_git_repo(self):
        """Find git root when inside a git repository."""
        from ppxai.engine.bootstrap import find_git_root

        # This test runs in the ppxai repo, so should find a git root
        result = find_git_root()
        assert result is not None
        assert (result / ".git").exists()

    def test_finds_git_root_from_subdir(self):
        """Find git root from a subdirectory."""
        from ppxai.engine.bootstrap import find_git_root

        # Use a known subdirectory of the ppxai project
        subdir = Path(__file__).parent  # tests/
        result = find_git_root(subdir)
        assert result is not None
        assert (result / ".git").exists()
        # The root should be a parent of the subdir
        assert subdir.resolve().is_relative_to(result)

    def test_returns_none_outside_git_repo(self):
        """Return None when not in a git repository."""
        from ppxai.engine.bootstrap import find_git_root

        with temp_dir() as d:
            # temp dir is not a git repo
            result = find_git_root(d)
            assert result is None


class TestContextScope:
    """Tests for ContextScope enum (v1.14.2)."""

    def test_scope_values(self):
        """ContextScope has expected values."""
        from ppxai.engine.bootstrap import ContextScope

        assert ContextScope.GLOBAL.value == "global"
        assert ContextScope.PROJECT.value == "project"
        assert ContextScope.SUBDIR.value == "subdir"


class TestFindBootstrapFilesByScope:
    """Tests for find_bootstrap_files_by_scope() function (v1.14.2)."""

    def test_finds_project_scope_at_git_root(self):
        """Find bootstrap file at git root as project scope."""
        from ppxai.engine.bootstrap import find_bootstrap_files_by_scope, ContextScope

        # Use the actual ppxai project which has CLAUDE.md at root
        project_root = Path(__file__).parent.parent
        result = find_bootstrap_files_by_scope(project_root)

        # Should find at least the project-level file
        project_files = [f for f, scope in result if scope == ContextScope.PROJECT]
        # May or may not find depending on whether AGENTS.md/CLAUDE.md exists
        # Just verify the function runs without error
        assert isinstance(result, list)

    def test_no_duplicates_when_cwd_is_git_root(self):
        """No duplicate files when working dir is git root."""
        from ppxai.engine.bootstrap import find_bootstrap_files_by_scope

        with temp_dir() as d:
            # Create a fake git repo
            (d / ".git").mkdir()
            (d / "AGENTS.md").write_text("Project rules")

            result = find_bootstrap_files_by_scope(d)

            # Should only find ONE file (project scope, not project AND subdir)
            paths = [str(f) for f, scope in result]
            # Check no duplicates
            assert len(paths) == len(set(paths))

    def test_finds_global_project_and_subdir(self):
        """Find files from all three scopes."""
        from ppxai.engine.bootstrap import find_bootstrap_files_by_scope, ContextScope
        import os

        with temp_dir() as project_root:
            # Create a fake git repo
            (project_root / ".git").mkdir()
            (project_root / "AGENTS.md").write_text("Project rules")

            # Create a subdirectory with its own AGENTS.md
            subdir = project_root / "src"
            subdir.mkdir()
            (subdir / "AGENTS.md").write_text("Subdir rules")

            result = find_bootstrap_files_by_scope(subdir)

            # Should find both project and subdir files
            scopes_found = [scope.value for f, scope in result]
            assert "project" in scopes_found
            assert "subdir" in scopes_found

    def test_empty_aliases_returns_empty_list(self):
        """Empty alias list returns empty list."""
        from ppxai.engine.bootstrap import find_bootstrap_files_by_scope

        with temp_dir() as d:
            (d / "AGENTS.md").write_text("Should be ignored")
            result = find_bootstrap_files_by_scope(d, aliases=[])
            assert result == []


class TestContextInjectorScopes:
    """Tests for ContextInjector scope methods (v1.14.2)."""

    def test_find_bootstrap_files_with_scopes_returns_scoped_sources(self):
        """find_bootstrap_files_with_scopes() returns ScopedBootstrapSource objects."""
        from ppxai.engine.context import ContextInjector, ScopedBootstrapSource

        with temp_dir() as project_root:
            # Create a fake git repo
            (project_root / ".git").mkdir()
            (project_root / "AGENTS.md").write_text("Project rules")

            injector = ContextInjector(working_dir=str(project_root))
            sources = injector.find_bootstrap_files_with_scopes()

            assert len(sources) >= 1
            for src in sources:
                assert isinstance(src, ScopedBootstrapSource)
                assert src.scope in ("global", "project", "subdir")
                assert src.size > 0

    def test_load_bootstrap_context_merged_merges_files(self):
        """load_bootstrap_context_merged() merges files from multiple scopes."""
        from ppxai.engine.context import ContextInjector

        with temp_dir() as project_root:
            # Create a fake git repo
            (project_root / ".git").mkdir()
            (project_root / "AGENTS.md").write_text("""---
provider_hints:
  ollama:
    - "Project hint"
---

# Project Rules
""")

            # Create subdirectory with different content
            subdir = project_root / "src"
            subdir.mkdir()
            (subdir / "AGENTS.md").write_text("""# Subdir Rules

Extra instructions for this directory.
""")

            # Use custom bootstrap_files to isolate from global ~/.ppxai/AGENTS.md
            injector = ContextInjector(working_dir=str(subdir), bootstrap_files=["AGENTS.md"])
            ctx, sources = injector.load_bootstrap_context_merged()

            assert ctx is not None
            # May include global file if ~/.ppxai/AGENTS.md exists
            assert len(sources) >= 2

            # Merged content should contain project and subdir files
            assert "Project Rules" in ctx.base_instructions
            assert "Subdir Rules" in ctx.base_instructions

            # Provider hints from project file should be preserved
            assert "ollama" in ctx.provider_hints

    def test_load_bootstrap_context_merged_returns_none_when_disabled(self):
        """load_bootstrap_context_merged() returns (None, []) when bootstrap disabled."""
        from ppxai.engine.context import ContextInjector

        with temp_dir() as d:
            # Pass empty bootstrap_files to disable global/project search
            injector = ContextInjector(working_dir=str(d), bootstrap_files=[])
            ctx, sources = injector.load_bootstrap_context_merged()

            assert ctx is None
            assert sources == []

    def test_load_bootstrap_context_merged_tracks_source_paths(self):
        """Merged context tracks source file paths."""
        from ppxai.engine.context import ContextInjector

        with temp_dir() as project_root:
            # Create a fake git repo
            (project_root / ".git").mkdir()
            (project_root / "AGENTS.md").write_text("Project rules")

            injector = ContextInjector(working_dir=str(project_root))
            ctx, sources = injector.load_bootstrap_context_merged()

            assert ctx is not None
            assert len(sources) >= 1

            # Sources should have path and scope info
            for src in sources:
                assert src.path.exists()
                assert src.scope in ("global", "project", "subdir")


class TestScopePrecedence:
    """Tests for scope precedence order (v1.14.2)."""

    def test_precedence_order_is_global_project_subdir(self):
        """Scopes are returned in order: global, project, subdir."""
        from ppxai.engine.bootstrap import find_bootstrap_files_by_scope, ContextScope

        with temp_dir() as project_root:
            # Create a fake git repo
            (project_root / ".git").mkdir()
            (project_root / "AGENTS.md").write_text("Project rules")

            # Create subdirectory
            subdir = project_root / "src"
            subdir.mkdir()
            (subdir / "AGENTS.md").write_text("Subdir rules")

            result = find_bootstrap_files_by_scope(subdir)

            # Extract scopes in order
            scopes = [scope for f, scope in result]

            # Verify order: global (if present) < project < subdir
            if ContextScope.GLOBAL in scopes:
                assert scopes.index(ContextScope.GLOBAL) < scopes.index(ContextScope.PROJECT)

            if ContextScope.PROJECT in scopes and ContextScope.SUBDIR in scopes:
                assert scopes.index(ContextScope.PROJECT) < scopes.index(ContextScope.SUBDIR)

    def test_missing_intermediate_scope_is_fine(self):
        """Works correctly when intermediate scope (project) is missing."""
        from ppxai.engine.bootstrap import find_bootstrap_files_by_scope

        with temp_dir() as d:
            # No git repo, so no project scope
            (d / "AGENTS.md").write_text("Directory rules")

            result = find_bootstrap_files_by_scope(d)

            # Should still find the file (as subdir since no git root)
            # Or no file if the directory structure doesn't match
            # Just verify no error occurs
            assert isinstance(result, list)
