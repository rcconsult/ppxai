# Release Plan: v1.14.x Series

**Created:** January 5, 2026
**Last Updated:** January 11, 2026
**Status:** Planning (after v1.13.8 completion)
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

### v1.14.0 - AGENTS.md Support (Core)

**Goal:** Load project context from working directory

| Feature | File | Description |
|---------|------|-------------|
| `find_bootstrap_files()` | `ppxai/engine/context.py` | Discover AGENTS.md/CLAUDE.md |
| `load_bootstrap_context()` | `ppxai/engine/client.py` | Load and cache content |
| Modify prompt assembly | `ppxai/engine/client.py:1171-1186` | Prepend bootstrap to system prompt |
| `get_bootstrap_status()` | `ppxai/engine/client.py` | Status API for UI |

**Prompt Assembly Order:**
```
[Bootstrap Context (AGENTS.md)]
---
[Config System Prompt (if any)]
---
[Tool Instructions (if tools enabled)]
```
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
    """When both exist, AGENTS.md wins."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Agents rules")
        (d / "CLAUDE.md").write_text("Claude rules")
        injector = ContextInjector(working_dir=str(d))
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "AGENTS.md"

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

### v1.14.2 - `/context` Commands

**Goal:** User control over loaded context

| Command | Description |
|---------|-------------|
| `/context show` | Display loaded sources and content preview |
| `/context reload` | Refresh from disk |
| `/context edit` | Open context file in editor |
| `/context clear` | Temporarily disable context |

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

### v1.14.3 - Context Enhancements

**Goal:** Advanced context features

| Feature | Description |
|---------|-------------|
| Token count display | Show in status bar |
| Conditional sections | Provider-specific rules |
| Include directive | Reference other files |

**Conditional Syntax:**
```markdown
<!-- if provider:gemini -->
Use Google Search Grounding for real-time information.
Always cite sources from grounding results.
<!-- endif -->

<!-- if provider:perplexity -->
Cite sources using [1], [2] notation from citations array.
<!-- endif -->

<!-- if tools:enabled -->
Prefer using tools over asking the user for information.
<!-- endif -->
```

**Include Directive:**
```markdown
# Project Rules

<!-- include: ./docs/coding-standards.md -->
<!-- include: ./docs/api-conventions.md -->

## Additional Notes
...
```

---

### v1.14.4 - Enhanced Context Providers

**Goal:** Advanced context injection from external sources

| Feature | Description |
|---------|-------------|
| `@url` provider | Fetch and inject web content into context |
| `@clipboard` provider | Inject clipboard contents |
| Context caching | Cache fetched URLs for session duration |
| Error handling | Graceful fallback when sources unavailable |

**Note:** Installation & server control features originally planned here were completed in v1.13.x:
- ✅ `install.sh` and `install.ps1` (v1.13.2)
- ✅ VSCode server badge (v1.13.1)
- ✅ docs/INSTALLATION.md (v1.13.2)

---

## Implementation Checklist

### v1.14.0
- [ ] Add `find_bootstrap_files()` to ContextInjector
- [ ] Add `_bootstrap_context` to EngineClient
- [ ] Add `load_bootstrap_context()` method
- [ ] Add `get_bootstrap_status()` method
- [ ] Modify `_build_system_messages()` to include context
- [ ] Call `load_bootstrap_context()` in `__init__`
- [ ] Call `load_bootstrap_context()` in `set_working_dir()`
- [ ] Create `tests/test_bootstrap_context.py`
- [ ] Update `/status` to show bootstrap info
- [ ] Test in TUI
- [ ] Test in VSCode extension

### v1.14.1
- [ ] Add global path search (`~/.ppxai/`)
- [ ] Add git root detection
- [ ] Implement merge strategy
- [ ] Add source tracking for each file
- [ ] Add tests for precedence

### v1.14.2
- [ ] Add `/context` command handler
- [ ] Implement `show` subcommand
- [ ] Implement `reload` subcommand
- [ ] Implement `edit` subcommand
- [ ] Implement `clear` subcommand
- [ ] Add tab autocomplete
- [ ] Add HTTP endpoints
- [ ] Update VSCode extension

### v1.14.3
- [ ] Add token counting
- [ ] Implement conditional parsing
- [ ] Implement include directive
- [ ] Add context size to status bar

### v1.14.4
- [ ] Implement `@url` context provider
- [ ] Implement `@clipboard` context provider
- [ ] Add URL content caching
- [ ] Add timeout/error handling for URL fetch
- [ ] Add tests for context providers

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
