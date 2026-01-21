# Release Plan: v1.14.x Series

**Created:** January 5, 2026
**Last Updated:** January 21, 2026
**Status:** v1.14.0 complete, v1.14.1 complete
**Branch:** `feature/agents-bootstrap-context` (v1.14.0), `feature/editor-command-support` (v1.14.1+)

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

### v1.14.1 - `/edit` Command & Context Reload

**Goal:** Enable edit-test-save workflow for bootstrap context tuning

**Design Principles:**
- Follow current refactored architecture (EventBus, handlers, IoC) - minimize new technical debt
- Unify `/edit` and `/show` backends where possible (single editor component, read-write vs read-only modes)
- Keep dependencies minimal - no large preview frameworks

| Feature | Description |
|---------|-------------|
| `/edit` command | Open file in editor (all interfaces) |
| `/context reload` | Refresh AGENTS.md from disk |
| Auto-reload on save | `/edit AGENTS.md` + save triggers context reload |
| `POST /files/write` | Server endpoint for file writes |

**Implementation by Interface:**

| Interface | `/edit` Implementation |
|-----------|------------------------|
| **VSCode** | Delegate to `vscode.window.showTextDocument()` with proper language mode |
| **TUI (Rich)** | Simple line editor (prompt-based, no terminal takeover) |
| **Web App** | CodeMirror 6 split-pane editor (unified with `/show` preview) |

**TUI Simple Line Editor:**

The TUI cannot delegate to external editors (would conflict with Rich's terminal control).
Instead, we provide a prompt-based line editor:

```
/edit src/main.py:42
───────────────────────────────────────────────────────
 Editing: src/main.py (line 42)
───────────────────────────────────────────────────────
  40 │ def process_data(items):
  41 │     """Process a list of items."""
► 42 │     for item in items:
  43 │         result = transform(item)
  44 │         yield result
───────────────────────────────────────────────────────
 [r]eplace line | [i]nsert after | [d]elete | [↑↓/jk] navigate | [s]ave | [q]uit
───────────────────────────────────────────────────────
> r
Enter new line 42: for item in items:
───────────────────────────────────────────────────────
 Saved: src/main.py
───────────────────────────────────────────────────────
```

**VSCode Extension Details:**

The `/edit` command delegates to VSCode's native editor with proper language support:

```typescript
// vscode-extension/src/handlers/edit.ts
async function handleEditCommand(filePath: string, line?: number) {
    const uri = vscode.Uri.file(filePath);
    const doc = await vscode.workspace.openTextDocument(uri);

    // VSCode auto-detects language from file extension
    // User's installed extensions (Python, Go, etc.) provide full IDE support
    const editor = await vscode.window.showTextDocument(doc, {
        viewColumn: vscode.ViewColumn.Beside,  // Split pane
        preview: false,  // Keep tab open
        selection: line ? new vscode.Range(line - 1, 0, line - 1, 0) : undefined
    });
}
```

**Benefits:**
- Full language support from user's installed extensions
- Syntax highlighting, IntelliSense, linting, formatting
- Native VSCode experience (no custom editor needed)
- Split pane alongside chat panel

---

**Web App CodeMirror 6 Editor:**

**Separate Commands - No Migration:**

- `/show` → **Unchanged** - Keep existing viewers (DataTableViewer, DataTreeViewer, image, PDF)
- `/edit` → **New** - CodeMirror 6 editor with read-write capability

This approach:
- Avoids breaking existing `/show` functionality
- Adds editing capability without disrupting preview workflows
- Simpler implementation (no refactoring needed)

```
┌────────────────────────────┬─────────────────────────────────┐
│  Chat messages...          │  AGENTS.md                  [×] │
│                            │─────────────────────────────────│
│  You: /edit AGENTS.md      │  ---                            │
│                            │  provider_hints:                │
│  System: Opened in editor  │    ollama:                      │
│                            │      - "Complete tasks fully."  │
│                            │  ---                            │
│                            │  # Project Rules                │
│                            │                                 │
│  [input field]             │  [Save] [Save As...] [Discard]  │
└────────────────────────────┴─────────────────────────────────┘
```

**Markdown Preview (optional, within `/edit`):**

For markdown files, offer a preview toggle using existing marked.js:

```
┌────────────────────────────┬─────────────────────────────────┐
│  Chat messages...          │  README.md    [Preview] [×]     │
│                            │─────────────────────────────────│
│  You: /edit README.md      │  # Project Title                │
│                            │                                 │
│  System: Opened in editor  │  This is **bold** text.         │
│                            │                                 │
│                            │  - List item 1                  │
│                            │  - List item 2                  │
│  [input field]             │  [Save] [Save As...] [Discard]  │
└────────────────────────────┴─────────────────────────────────┘
```

When [Preview] is clicked, renders markdown in place (toggle back with [Source]).

**CodeMirror 6 Language Support:**

| Category | Languages | Package |
|----------|-----------|---------|
| **Config** | Markdown, YAML, JSON | `@codemirror/lang-markdown`, `lang-yaml`, `lang-json` |
| **Code** | Python, JavaScript/TypeScript, Go, C/C++ | `lang-python`, `lang-javascript`, `lang-go`, `lang-cpp` |
| **Shell** | Bash/Shell | `@codemirror/legacy-modes` (shell mode) |
| **Other** | TOML, HCL, Perl | `@codemirror/legacy-modes` |

**Bundle size:** ~200KB (core + priority languages, others loaded on demand)

**Server Endpoint:**
```python
@app.post("/files/write")
async def write_file(request: Request):
    """Write content to file (with path validation)."""
    data = await request.json()
    path = Path(data["path"])
    content = data["content"]

    # Security: validate path is within working directory
    working_dir = Path(session_manager.working_dir)
    resolved = path.resolve()
    if not resolved.is_relative_to(working_dir):
        raise HTTPException(403, "Path outside working directory")

    resolved.write_text(content, encoding="utf-8")
    return {"status": "saved", "path": str(resolved)}
```

**Files to Modify:**

| File | Changes |
|------|---------|
| `ppxai/server/http.py` | Add `POST /files/write` endpoint |
| `ppxai/commands.py` | Add `/edit` command handler |
| `ppxai/engine/client.py` | Add `reload_bootstrap_context()` method |
| `ppxai/web/app.js` | Add CodeMirror 6 editor component |
| `ppxai/web/lib/` | Add CodeMirror 6 modules |
| `vscode-extension/src/chatPanel.ts` | Add `/edit` → showTextDocument() |

**Test Cases:**
```python
def test_edit_opens_file_in_editor():
    """TUI /edit displays line editor UI."""

def test_context_reload_refreshes_hints():
    """/context reload re-parses AGENTS.md."""

def test_file_write_validates_path():
    """POST /files/write rejects paths outside working dir."""

def test_auto_reload_on_agents_md_save():
    """Saving AGENTS.md triggers context reload."""
```

---

### v1.14.2 - File Precedence & Merge

**Goal:** Support global, project, and subdirectory contexts

| Feature | Description |
|---------|-------------|
| Global context | Load from `~/.ppxai/AGENTS.md` |
| Project context | Load from git root AGENTS.md |
| Subdirectory context | Load from cwd AGENTS.md |
| Merge strategy | Concatenate with separator |
| `/context show` | Display AGENTS.md sources with hierarchy |

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

**TUI Output Example:**
```
/context show
Bootstrap Context:
  Sources:
    1. ~/.ppxai/AGENTS.md (1.2 KB) [global]
    2. /project/AGENTS.md (3.4 KB) [project]
    3. /project/src/AGENTS.md (0.5 KB) [subdir]

  Total: 5.1 KB (~1,300 tokens)

  Active Hints (ollama + deepseek-r1:7b):
    Provider: 3 hints (2 from local, 1 from ollama)
    Model: 1 hint (deepseek-r1*)
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

### v1.14.3 - Enhanced Context Providers

**Goal:** Advanced context features and external source injection

**Note:** v1.13.9 implemented `/context` and `/context clear` for **injected context** (@file/@git/@tree).
v1.14.3 extends context providers with additional sources.

| Feature | Description |
|---------|-------------|
| `@url` provider | Fetch and inject web content into context |
| `@clipboard` provider | Inject clipboard contents |
| Include directive | `<!-- include: ./docs/style.md -->` in AGENTS.md |
| Hint templates | Reusable hint sets: `hints: [tool-heavy, reasoning]` |
| Token count display | Show context size in status bar |
| Context caching | Cache fetched URLs for session duration |

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

### v1.14.0 ✅ Complete
- [x] Create `ppxai/engine/bootstrap.py` with `BootstrapContext` class
- [x] Implement YAML front matter parsing (provider_hints, model_hints)
- [x] Add `find_bootstrap_files()` to ContextInjector with configurable aliases
- [x] Add `bootstrap_files` config option to `ppxai/config/` (default: `["AGENTS.md", "CLAUDE.md"]`)
- [x] Add `get_bootstrap_files()` helper function to config module
- [x] Add `_bootstrap_context: BootstrapContext` to EngineClient
- [x] Add `load_bootstrap_context()` method
- [x] Add `get_bootstrap_status()` method
- [x] Implement `get_prompt_for(provider, model)` with dynamic hints
- [x] Implement `local` provider inheritance (ollama, vllm, lmstudio)
- [x] Modify `_build_system_messages()` to use BootstrapContext
- [x] Trigger prompt rebuild in `set_provider()` and `set_model()`
- [x] Call `load_bootstrap_context()` in `__init__`
- [x] Call `load_bootstrap_context()` in `set_working_dir()`
- [x] Create `tests/test_bootstrap_context.py`
- [x] Add tests for custom alias list configuration
- [x] Add tests for empty alias list (disabled bootstrap)
- [x] Update `/status` to show bootstrap info
- [x] Add `/context hints` command (TUI, VSCode, Web)
- [x] Add `GET /context/hints` HTTP endpoint
- [x] Add CSS table word-wrap fix for VSCode/Web
- [x] Fix session alternation bugs (Perplexity "messages must alternate")
- [x] Test provider switching with different hints
- [x] Test in TUI, VSCode, and Web app

### v1.14.1 - `/edit` Command & Context Reload

**Architecture Notes:**
- Follow EventBus/handlers/IoC patterns from v1.13.10 refactoring
- Minimize new technical debt - use existing abstractions
- `/edit` is new (CodeMirror 6), `/show` stays unchanged (existing viewers)

**Implementation Order:**

| Stage | Interface | Approach | Rationale |
|-------|-----------|----------|-----------|
| **1** | VSCode | Delegate to native editor | Simplest - leverage VSCode's full IDE |
| **2** | Web App | CodeMirror 6 editor | Full-featured browser editor |
| **3** | TUI | TBD (research alternatives) | Review options after 1 & 2 complete |

---

#### Stage 1: VSCode Extension (First Priority)

**Goal:** Quick win - delegate to VSCode's native editor

- [ ] Add `/edit` command handler in `handlers/edit.ts`
- [ ] Delegate to `vscode.window.showTextDocument()` with proper options
- [ ] Ensure file opens with correct language mode (auto-detected from extension)
- [ ] Support line number: `/edit file.py:42` jumps to line 42
- [ ] Add `POST /files/write` server endpoint (shared with Web App)
- [ ] Add `/context reload` command
- [ ] Add `POST /context/reload` HTTP endpoint
- [ ] Tests for VSCode `/edit` command

**Deliverable:** `/edit` working in VSCode extension

---

#### Stage 2: Web App (Second Priority)

**Goal:** Full-featured editor with CodeMirror 6

- [ ] Add CodeMirror 6 core modules to `ppxai/web/lib/`
- [ ] Add priority language modules (markdown, yaml, json, python, javascript)
- [ ] Add legacy modes for shell, toml, hcl, perl (on-demand loading)
- [ ] Create `/edit` editor component (separate from `/show`)
  - [ ] Read-write mode with Save/Save As/Discard buttons
  - [ ] Optional markdown preview toggle (reuse existing marked.js)
- [ ] Keep existing `/show` viewers unchanged
- [ ] Wire up `/context reload` in Web App
- [ ] Tests for Web App `/edit` command

**Deliverable:** `/edit` working in Web App with syntax highlighting

---

#### Stage 3: TUI (Third Priority - Research Phase)

**Goal:** Determine best approach for terminal-based editing

**Options to Evaluate:**

| Option | Pros | Cons |
|--------|------|------|
| **Simple line editor** | No dependencies, works everywhere | Limited UX, no syntax highlighting |
| **Delegate to $EDITOR** | Use vim/nano/emacs | Conflicts with Rich terminal control |
| **Textual widget** | Rich TUI editing | Heavy dependency, may defer to v1.15.x |
| **External file + watch** | Open in system editor, watch for changes | Platform-specific, complexity |

**Decision:** Review after Stage 1 & 2 complete. May defer full TUI editor to v1.15.x (ppxaide with Textual).

- [ ] Research TUI editing alternatives
- [ ] Prototype preferred approach
- [ ] Implement `/edit` for TUI
- [ ] Tests for TUI `/edit` command

**Deliverable:** `/edit` working in TUI (or documented deferral to v1.15.x)

---

#### Shared Components (All Stages)

**Server:**
- [ ] Add `POST /files/write` server endpoint with path validation
- [ ] Add `POST /context/reload` HTTP endpoint

**Engine:**
- [ ] Add `reload_bootstrap_context()` method to EngineClient
- [ ] Implement auto-reload when AGENTS.md saved via `/edit`

**Tests:**
- [ ] Add tests for `/context reload`
- [ ] Add tests for file write path validation (security)

### v1.14.2 - File Precedence & Merge
- [ ] Add global path search (`~/.ppxai/AGENTS.md`)
- [ ] Add git root detection for project context
- [ ] Implement merge strategy (global → project → subdir)
- [ ] Add source tracking for each file
- [ ] Extend `/context show` to display hierarchy
- [ ] Add tests for precedence order
- [ ] Add tests for missing intermediate files

### v1.14.3 - Enhanced Context Providers
- [ ] Implement `@url` context provider
- [ ] Implement `@clipboard` context provider
- [ ] Implement include directive (`<!-- include: path -->`)
- [ ] Implement hint templates (`hint_templates:` + `templates: [...]`)
- [ ] Add token counting to `/context` output
- [ ] Add context size to status bar
- [ ] Add URL content caching
- [ ] Add timeout/error handling for URL fetch
- [ ] Add tests for context providers

### v1.14.4 - Documentation Site (GitHub Pages)
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
