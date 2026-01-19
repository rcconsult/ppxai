# Release Plan: v1.14.x Series

**Created:** January 5, 2026
**Last Updated:** January 19, 2026
**Status:** Planning (after v1.13.10 completion)
**Branch:** TBD

---

## Theme: Session Bootstrap

**Tagline:** Reproducible starting point for every session

## Overview

The v1.14.x series introduces "Session Bootstrap" - the ability to automatically load project-specific context (instructions, rules, coding standards) from AGENTS.md or CLAUDE.md files. This enables:

- **Teams:** Share project context via version control
- **Consistency:** Same AI behavior across all team members
- **Zero friction:** Works automatically, no configuration needed

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     User Message                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   EngineClient                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  _bootstrap_context: str (cached)                   │    │
│  │  _bootstrap_sources: List[str]                      │    │
│  │                                                     │    │
│  │  load_bootstrap_context() ──────────────────────────┼────┤
│  │  get_bootstrap_status() → {loaded, sources, chars}  │    │
│  │  _build_system_messages() ──────────┐               │    │
│  └─────────────────────────────────────┼───────────────┘    │
│                                        │                    │
│                                        ▼                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              System Prompt                          │    │
│  │  ┌───────────────────────────────────────────────┐  │    │
│  │  │ PROJECT CONTEXT:                              │  │    │
│  │  │ {bootstrap_context from AGENTS.md}            │  │    │
│  │  │                                               │  │    │
│  │  │ ---                                           │  │    │
│  │  │                                               │  │    │
│  │  │ TOOLS:                                        │  │    │
│  │  │ {tool_prompt from ToolManager}                │  │    │
│  │  └───────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                 ContextInjector                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  find_bootstrap_files() → List[Path]                │    │
│  │                                                     │    │
│  │  Search order:                                      │    │
│  │  1. ~/.ppxai/AGENTS.md (global)                     │    │
│  │  2. {project_root}/AGENTS.md                        │    │
│  │  3. {cwd}/AGENTS.md                                 │    │
│  │                                                     │    │
│  │  Priority: AGENTS.md > CLAUDE.md                    │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites (Already Implemented)

**System Prompt Support (v1.13.6):**
The system prompt infrastructure is already in place:
- `ppxai/config.py:get_system_prompt()` - retrieves system prompt from config
- `ppxai/config.py:get_system_prompt_mode()` - retrieves mode (prepend/append/replace)
- `ppxai/engine/client.py:1171-1186` - assembles final prompt with tool instructions
- Config: `system_prompt` (global) and `providers.<name>.system_prompt` (per-provider)

**No Conflicts:** Bootstrap context will be injected *before* the existing system prompt,
so it works alongside user-configured prompts without breaking existing behavior.

---

## Release Schedule

### v1.14.0 - AGENTS.md Support with Provider Hints (Core)

**Goal:** Load project context from working directory with provider/model-aware hints

| Feature | File | Description |
|---------|------|-------------|
| `BootstrapContext` class | `ppxai/engine/bootstrap.py` | Parse AGENTS.md with YAML front matter |
| `find_bootstrap_files()` | `ppxai/engine/context.py` | Discover bootstrap files with configurable aliases |
| `load_bootstrap_context()` | `ppxai/engine/client.py` | Load and cache BootstrapContext |
| Dynamic prompt assembly | `ppxai/engine/client.py` | Rebuild on provider/model switch |
| `get_bootstrap_status()` | `ppxai/engine/client.py` | Status API for UI |
| Configurable file aliases | `ppxai-config.json` | User-defined fallback filenames |

**Design Decision: Configurable Bootstrap File Aliases**

By default, ppxai looks for `AGENTS.md` first, then falls back to `CLAUDE.md`. Users can customize this list via `ppxai-config.json` to support other naming conventions (e.g., `COPILOT.md`, `AI.md`, `CURSOR.md`).

**Configuration (ppxai-config.json):**
```json
{
  "bootstrap": {
    "files": ["AGENTS.md", "CLAUDE.md", "COPILOT.md", "AI.md"],
    "enabled": true
  }
}
```

**Behavior:**
- Files are checked in order; first match wins (no merging at same directory level)
- Default: `["AGENTS.md", "CLAUDE.md"]` if not configured
- Case-sensitive on Linux/macOS, case-insensitive on Windows
- Empty list `[]` or `enabled: false` disables bootstrap file loading entirely

**Lookup Algorithm:**
```python
def find_bootstrap_file(directory: Path, aliases: list[str]) -> Path | None:
    """Find first matching bootstrap file in directory."""
    for filename in aliases:
        path = directory / filename
        if path.is_file():
            return path
    return None
```

**Design Decision: YAML Front Matter Format**

The problem: When switching from Gemini to Ollama mid-session, the system prompt needs to adapt:
- **Ollama/local models** need: "Complete tasks fully, don't stop on empty responses"
- **Gemini** needs: "Use Google Search grounding for current information"
- **DeepSeek R1** needs: "Show reasoning before taking actions"

**AGENTS.md File Format:**
```markdown
---
# Provider-specific hints (appended when provider is active)
provider_hints:
  ollama:
    - "Complete tasks fully. Don't stop after tool calls - synthesize results."
    - "If a tool returns empty output, explain what you tried and continue."
  local:  # Applies to all local providers (ollama, vllm, lmstudio)
    - "Use tools proactively. Don't ask for permission - just execute."
  gemini:
    - "Use your built-in web search for current information."

# Pattern-matched against model ID (regex)
model_hints:
  "deepseek-r1*":
    - "Show <think> reasoning before actions."
  "qwen2.5-coder*":
    - "Prefer edit_file over apply_patch for modifications."
  "llama*":
    - "Always provide complete file contents, not diffs."
---

# MyProject Development Guide

## Code Standards
- Python 3.11+, type hints required
- pytest for testing, 80% coverage minimum
```

**BootstrapContext Class:**
```python
# ppxai/engine/bootstrap.py

class BootstrapContext:
    def __init__(self, agents_md_path: str):
        self.base_instructions: str = ""
        self.provider_hints: dict[str, list[str]] = {}
        self.model_hints: dict[str, list[str]] = {}  # regex patterns
        self._parse(agents_md_path)

    def get_prompt_for(self, provider: str, model: str) -> str:
        """Build system prompt for current provider/model."""
        parts = [self.base_instructions]

        # Add provider hints (with 'local' inheritance)
        hints = self._get_provider_hints(provider)
        if hints:
            parts.append("\n## Provider Guidance\n" + "\n".join(f"- {h}" for h in hints))

        # Add model hints (regex match)
        for pattern, model_hints in self.model_hints.items():
            if re.match(pattern.replace("*", ".*"), model):
                parts.append("\n## Model Guidance\n" + "\n".join(f"- {h}" for h in model_hints))

        return "\n".join(parts)

    def _get_provider_hints(self, provider: str) -> list[str]:
        """Get hints for provider, with 'local' inheritance."""
        LOCAL_PROVIDERS = {"ollama", "vllm", "lmstudio"}
        hints = list(self.provider_hints.get(provider, []))
        if provider in LOCAL_PROVIDERS and "local" in self.provider_hints:
            hints = self.provider_hints["local"] + hints
        return hints
```

**Prompt Assembly Order:**
```
1. [Bootstrap base_instructions (below ---)]
2. [Matching provider_hints]
3. [Matching model_hints]
4. [Config system_prompt (from ppxai-config.json)]
5. [Tool prompt (if tools enabled)]
```

**Behavior Rules:**
- `local` provider hints apply to: ollama, vllm, lmstudio (inheritance)
- Both provider AND model hints concatenate (additive, not override)
- On `/provider` or `/model` switch: immediate prompt rebuild
- On `/context reload`: re-parse AGENTS.md and rebuild

This respects the existing `system_prompt_mode` for config prompts.

**Test Cases:**
```python
# tests/test_bootstrap_context.py

def test_finds_agents_md_in_working_dir():
    """AGENTS.md in cwd should be discovered."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Project rules")
        injector = ContextInjector(working_dir=str(d))
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "AGENTS.md"

def test_finds_claude_md_as_fallback():
    """CLAUDE.md used when no AGENTS.md exists."""
    with temp_dir() as d:
        (d / "CLAUDE.md").write_text("Claude instructions")
        injector = ContextInjector(working_dir=str(d))
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "CLAUDE.md"

def test_agents_md_takes_priority():
    """When both exist, AGENTS.md wins (first in alias list)."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Agents rules")
        (d / "CLAUDE.md").write_text("Claude rules")
        injector = ContextInjector(working_dir=str(d))
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "AGENTS.md"

def test_custom_alias_list():
    """User-configured alias list is respected."""
    with temp_dir() as d:
        (d / "COPILOT.md").write_text("Copilot rules")
        (d / "CLAUDE.md").write_text("Claude rules")
        # Custom order: COPILOT.md first
        injector = ContextInjector(
            working_dir=str(d),
            bootstrap_files=["COPILOT.md", "CLAUDE.md", "AGENTS.md"]
        )
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "COPILOT.md"

def test_custom_alias_fallback_order():
    """Falls back through alias list in order."""
    with temp_dir() as d:
        (d / "AI.md").write_text("AI rules")  # Third in list
        injector = ContextInjector(
            working_dir=str(d),
            bootstrap_files=["AGENTS.md", "CLAUDE.md", "AI.md"]
        )
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "AI.md"

def test_empty_alias_list_disables_bootstrap():
    """Empty bootstrap_files list disables loading."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Should be ignored")
        injector = ContextInjector(working_dir=str(d), bootstrap_files=[])
        files = injector.find_bootstrap_files()
        assert len(files) == 0

def test_context_injected_into_system_prompt():
    """Bootstrap context appears in messages sent to LLM."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Always use TypeScript")
        engine = EngineClient(working_dir=str(d))
        messages = engine._build_system_messages()
        assert "Always use TypeScript" in messages[0].content

def test_context_cached_between_chat_calls():
    """Context is loaded once, not on every chat."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Rules")
        engine = EngineClient(working_dir=str(d))
        engine.load_bootstrap_context()
        # Modify file - should NOT be reflected
        (d / "AGENTS.md").write_text("New rules")
        assert "Rules" in engine._bootstrap_context
        assert "New rules" not in engine._bootstrap_context

def test_no_bootstrap_file_is_fine():
    """Missing bootstrap files should not cause errors."""
    with temp_dir() as d:
        engine = EngineClient(working_dir=str(d))
        engine.load_bootstrap_context()
        assert engine._bootstrap_context is None
        assert engine._bootstrap_sources == []
```

---

### v1.14.1 - File Precedence

**Goal:** Support global, project, and subdirectory contexts

| Feature | Description |
|---------|-------------|
| Global context | Load from `~/.ppxai/AGENTS.md` |
| Project context | Load from git root AGENTS.md |
| Subdirectory context | Load from cwd AGENTS.md |
| Merge strategy | Concatenate with separator |

**Precedence Order:**
```
1. ~/.ppxai/AGENTS.md          (global defaults)
2. {git_root}/AGENTS.md        (project-specific)
3. {cwd}/AGENTS.md             (subdirectory overrides)
```

**Merge Behavior:**
```python
def _merge_contexts(self, files: List[Path]) -> str:
    """Merge multiple context files."""
    contents = []
    for f in files:
        content = f.read_text(errors='replace')
        source = str(f)
        contents.append(f"<!-- Source: {source} -->\n{content}")
    return "\n\n---\n\n".join(contents)
```

**Test Cases:**
```python
def test_global_context_loaded():
    """~/.ppxai/AGENTS.md is loaded."""

def test_project_root_detected():
    """Git root is correctly identified."""

def test_precedence_order():
    """Global + Project + Subdir are concatenated in order."""

def test_missing_intermediate_is_fine():
    """Works if only global and subdir exist, no project."""
```

---

### v1.14.2 - `/context` Commands for Bootstrap

**Goal:** User control over bootstrap context (AGENTS.md/CLAUDE.md)

**Note:** v1.13.9 implemented `/context` and `/context clear` for **injected context** (@file/@git/@tree).
This release extends `/context` to also manage **bootstrap context**.

| Command | Description |
|---------|-------------|
| `/context` | Show bootstrap sources alongside injected context (extends v1.13.9) |
| `/context reload` | Refresh AGENTS.md from disk |
| `/context edit` | Open AGENTS.md in editor (platform-dependent behavior) |
| Integration | Unified view: bootstrap + injected context in one output |

**`/context edit` Platform Behavior:**

| Platform | Behavior |
|----------|----------|
| **VSCode** | Opens AGENTS.md in a native editor tab (straightforward) |
| **Web App** | Shows file path + copy-to-clipboard button (browser security prevents direct file system access) |
| **TUI** | Shows file path + instructions to edit externally |

**TUI Constraints (Design Decision):**

The TUI intentionally disables interactive commands. This is a technical design choice based on Rich SDK limitations:

1. **Rich is output-only** - The Rich library provides formatting/rendering but has no built-in editor widget
2. **No editor subprocess** - Launching `$EDITOR` would conflict with Rich's terminal control (it manages the entire screen state)
3. **Alternatives rejected** - Textual or prompt_toolkit would require major architectural changes

**TUI `/context edit` implementation:**
```
/context edit

  Bootstrap file: /path/to/project/AGENTS.md

  Edit this file externally, then run:
    /context reload

  Tip: VS Code users can open with:
    code /path/to/project/AGENTS.md
```

This approach:
- Maintains Rich SDK compatibility
- Provides a clear workflow (edit → reload)
- Works consistently across all terminal emulators
- Avoids the complexity of terminal editor integration

**Files to Modify:**

| File | Changes |
|------|---------|
| `ppxai/commands.py` | Add `handle_context_command()` |
| `ppxai/common/commands.py` | Add to COMMANDS list |
| `ppxai/server/http.py` | Add `/context` endpoints |
| `vscode-extension/src/httpClient.ts` | Add context API |

**HTTP Endpoints:**
```
GET  /context         → {loaded, sources, char_count, preview}
POST /context/reload  → {success, sources}
POST /context/clear   → {success}
```

**TUI Output Example:**
```
/context show
Bootstrap Context:
  Sources:
    1. ~/.ppxai/AGENTS.md (1.2 KB)
    2. /project/AGENTS.md (3.4 KB)

  Total: 4.6 KB (~1,200 tokens)

  Preview:
  ─────────────────────────────
  <!-- Source: ~/.ppxai/AGENTS.md -->
  # Global Defaults
  - Use TypeScript for all new code
  - Follow ESLint rules
  ...
```

---

### v1.14.3 - Enhanced Context Providers

**Goal:** Advanced context features and external source injection

| Feature | Description |
|---------|-------------|
| `@url` provider | Fetch and inject web content into context |
| `@clipboard` provider | Inject clipboard contents |
| Include directive | `<!-- include: ./docs/style.md -->` in AGENTS.md |
| Hint templates | Reusable hint sets: `hints: [tool-heavy, reasoning]` |
| Token count display | Show context size in status bar |
| Context caching | Cache fetched URLs for session duration |

**Note:** Provider/model-specific conditionals are handled via YAML front matter (v1.14.0).

**Include Directive:**
```markdown
# Project Rules

<!-- include: ./docs/coding-standards.md -->
<!-- include: ./docs/api-conventions.md -->

## Additional Notes
...
```

**Hint Templates:**
Reusable hint sets that can be referenced by name:
```yaml
---
# Define reusable hint templates
hint_templates:
  tool-heavy:
    - "Use tools proactively for file operations"
    - "Don't ask permission - just execute safe operations"
  reasoning:
    - "Show step-by-step reasoning before complex decisions"
    - "Explain your approach before implementing"

# Apply templates to providers
provider_hints:
  ollama:
    templates: [tool-heavy, reasoning]
  gemini:
    - "Use Google Search grounding"
---
```

---

### v1.14.4 - Documentation Site (GitHub Pages)

**Goal:** Professional documentation site with versioning and search

| Feature | Description |
|---------|-------------|
| MkDocs setup | `mkdocs.yml` with Material theme configuration |
| Auto-deploy workflow | GitHub Actions deploys on release tag |
| Versioned docs | `mike` plugin for version selector |
| Full-text search | Built-in search across all documentation |
| Release integration | Docs deploy automatically as part of release |

**Technology Stack:**
- **MkDocs** - Static site generator that uses existing markdown files
- **Material for MkDocs** - Theme with dark mode, search, code highlighting
- **mike** - Versioning plugin (each release archives its docs)
- **GitHub Pages** - Hosting at `rcconsult.github.io/ppxai`

**File Structure:**
```
ppxai/
├── docs/                      # Existing - source markdown
│   ├── INSTALLATION.md
│   ├── AGENT_MODE_GUIDE.md
│   └── ...
├── mkdocs.yml                 # NEW: Site configuration
└── .github/workflows/
    └── docs.yml               # NEW: Auto-deploy workflow
```

**mkdocs.yml Configuration:**
```yaml
site_name: ppxai Documentation
site_url: https://rcconsult.github.io/ppxai/
repo_url: https://github.com/rcconsult/ppxai

theme:
  name: material
  palette:
    - scheme: slate
      primary: blue
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
    - scheme: default
      primary: blue
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
  features:
    - navigation.instant
    - navigation.sections
    - search.highlight
    - content.code.copy

nav:
  - Home: index.md
  - Getting Started:
    - Installation: INSTALLATION.md
    - Quick Start: ../README.md
  - User Guides:
    - Agent Mode: AGENT_MODE_GUIDE.md
    - Checkpoint & Undo: CHECKPOINT_GUIDE.md
    - Provider Setup: PROVIDER_SETUP.md
  - Development:
    - Custom Tools: CUSTOM_TOOL_DEVELOPMENT_GUIDE.md
    - VSCode Extension: ../vscode-extension/README.md
  - Release Notes:
    - v1.14.x: RELEASE-NOTES-v1.14.0.md

plugins:
  - search
  - mike:
      version_selector: true

markdown_extensions:
  - pymdownx.highlight
  - pymdownx.superfences
  - admonition
  - toc:
      permalink: true
```

**GitHub Actions Workflow (`.github/workflows/docs.yml`):**
```yaml
name: Deploy Documentation

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:
    inputs:
      version:
        description: 'Version to deploy'
        required: true

permissions:
  contents: write
  pages: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install mkdocs-material mike

      - name: Configure git
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

      - name: Deploy docs
        run: |
          VERSION=${GITHUB_REF#refs/tags/v}
          mike deploy --push --update-aliases $VERSION latest
          mike set-default --push latest
```

**URL Structure:**
```
https://rcconsult.github.io/ppxai/
├── /                      # Latest version (alias)
├── /1.14.4/              # Specific version
├── /1.13.10/             # Previous version
└── /getting-started/     # Navigation sections
```

**Benefits:**
- Zero changes to existing markdown docs
- Automatic versioning per release
- Full-text search
- Dark/light mode toggle
- Mobile responsive
- Professional appearance

---

## Implementation Checklist

### v1.14.0
- [ ] Create `ppxai/engine/bootstrap.py` with `BootstrapContext` class
- [ ] Implement YAML front matter parsing (provider_hints, model_hints)
- [ ] Add `find_bootstrap_files()` to ContextInjector with configurable aliases
- [ ] Add `bootstrap_files` config option to `ppxai/config/` (default: `["AGENTS.md", "CLAUDE.md"]`)
- [ ] Add `get_bootstrap_files()` helper function to config module
- [ ] Add `_bootstrap_context: BootstrapContext` to EngineClient
- [ ] Add `load_bootstrap_context()` method
- [ ] Add `get_bootstrap_status()` method
- [ ] Implement `get_prompt_for(provider, model)` with dynamic hints
- [ ] Implement `local` provider inheritance (ollama, vllm, lmstudio)
- [ ] Modify `_build_system_messages()` to use BootstrapContext
- [ ] Trigger prompt rebuild in `set_provider()` and `set_model()`
- [ ] Call `load_bootstrap_context()` in `__init__`
- [ ] Call `load_bootstrap_context()` in `set_working_dir()`
- [ ] Create `tests/test_bootstrap_context.py`
- [ ] Add tests for custom alias list configuration
- [ ] Add tests for empty alias list (disabled bootstrap)
- [ ] Update `/status` to show bootstrap info
- [ ] Test provider switching with different hints
- [ ] Test in TUI, VSCode, and Web app

### v1.14.1
- [ ] Add global path search (`~/.ppxai/`)
- [ ] Add git root detection
- [ ] Implement merge strategy
- [ ] Add source tracking for each file
- [ ] Add tests for precedence

### v1.14.2
- [x] Add `/context` command handler (v1.13.9 - for injected context)
- [x] Implement context display (v1.13.9 - shows injected files + usage)
- [ ] Extend to show bootstrap sources (AGENTS.md)
- [ ] Implement `reload` subcommand (for AGENTS.md)
- [ ] Implement `edit` subcommand
- [x] Implement `clear` subcommand (v1.13.9 - clears injected context)
- [x] Add tab autocomplete (v1.13.9)
- [x] Add HTTP endpoints (v1.13.9 - /context, /context/clear)
- [x] Update VSCode extension (v1.13.9 - context badge + /context command)

### v1.14.3
- [ ] Implement `@url` context provider
- [ ] Implement `@clipboard` context provider
- [ ] Implement include directive (`<!-- include: path -->`)
- [ ] Implement hint templates (`hint_templates:` + `templates: [...]`)
- [ ] Add token counting to `/context` output
- [ ] Add context size to status bar
- [ ] Add URL content caching
- [ ] Add timeout/error handling for URL fetch
- [ ] Add tests for context providers

### v1.14.4
- [ ] Create `mkdocs.yml` configuration file
- [ ] Create `docs/index.md` landing page
- [ ] Create `.github/workflows/docs.yml` workflow
- [ ] Enable GitHub Pages in repository settings
- [ ] Test local preview with `mkdocs serve`
- [ ] Deploy initial version with `mike`
- [ ] Verify versioned docs work correctly
- [ ] Add docs deployment step to release script
- [ ] Update README with docs site link

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Large context files | Warn if > 50KB, truncate if > 100KB |
| Circular includes | Track visited files, max depth = 3 |
| Performance on startup | Cache aggressively, lazy load if needed |
| Security (code injection) | Context is instructions only, not executed |

## Success Metrics

- [ ] Existing CLAUDE.md in ppxai project is automatically loaded
- [ ] `/status` shows loaded context
- [ ] Context visible in system prompt sent to LLM
- [ ] No performance regression (< 50ms added to startup)
- [ ] Works identically in TUI and VSCode

---

## References

- [Claude Code CLAUDE.md format](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/memory)
- [v1.11.0 Agentic Workflow Plan](v1.11.0-agentic-workflow-plan.md)
- [ROADMAP.md v1.14.x section](../ROADMAP.md)
- [v1.13.x Release Plan](RELEASE-PLAN-v1.13.x.md) (completed series)
