# Release Notes - v1.14.2

**Release Date:** 2026-01-23

## Summary

v1.14.2 introduces **hierarchical context scopes** for bootstrap files and **enhanced context providers** (merged from planned v1.14.3). Define global defaults, project-specific instructions, and subdirectory overrides that merge automatically. Plus new `@clipboard` and `@url` providers, include directives, and hint templates.

## Highlights

### 🌐 Global Context Defaults

Create `~/.ppxai/AGENTS.md` to define defaults that apply across all your projects:

```markdown
---
provider_hints:
  local:
    - "Complete tasks fully without stopping."
model_hints:
  "deepseek*":
    - "Show reasoning before taking actions."
---

# Global Preferences
- Use modern language features
- Prefer type hints when available
```

### 📁 Project and Subdirectory Overrides

Bootstrap files are loaded in precedence order and merged:

1. `~/.ppxai/AGENTS.md` (global)
2. `{git_root}/AGENTS.md` (project)
3. `{cwd}/AGENTS.md` (subdirectory)

Hints are **additive** - later scopes add to earlier ones, not replace them.

### 📋 `/context show` Command

New command to display the bootstrap context hierarchy:

```
/context show

Bootstrap Context

Sources: (2 files)
1. /Users/you/.ppxai/AGENTS.md
   [🌐 global] 1.4 KB
2. /Users/you/project/AGENTS.md
   [📁 project] 3.9 KB

Total: 5.3 KB (~1,325 tokens)

Hints Defined:
  Provider: local, ollama, perplexity
  Model: deepseek*, qwen*
```

## New Features

### Hierarchical Scopes
- **Global context** - `~/.ppxai/AGENTS.md` loaded for all projects
- **Project context** - `{git_root}/AGENTS.md` for repository-wide settings
- **Subdirectory context** - `{cwd}/AGENTS.md` for directory-specific overrides
- **`/context show`** - Display bootstrap sources with scope labels (TUI, Web, VSCode)
- **`GET /context/bootstrap`** - HTTP endpoint for scoped bootstrap status

### Enhanced Context Providers (merged from v1.14.3)
- **`@clipboard`** - Inject clipboard text content: `explain this error @clipboard`
- **`@url`** - Fetch and inject web content: `summarize @https://docs.example.com/api.md`
- **Include directive** - Compose AGENTS.md from multiple files:
  ```markdown
  <!-- include: ./docs/coding-standards.md -->
  <!-- include: ./docs/api-conventions.md -->
  ```
- **Hint templates** - Define reusable hint sets in `~/.ppxai/hint-templates.yaml`:
  ```yaml
  templates:
    tool-heavy:
      - "Use tools proactively without asking."
      - "Execute multiple tool calls in sequence."
  ```
  Reference in AGENTS.md:
  ```yaml
  provider_hints:
    ollama:
      - template: tool-heavy
      - "Custom project hint"
  ```

## Changes

- Provider/model hints from all scopes are combined (not replaced)
- `/context reload` now reloads from all scopes with improved feedback
- Bootstrap status API returns full scope information

## Scope Precedence

Files are discovered in this order:
1. **Global** (`~/.ppxai/`) - User-wide defaults
2. **Project** (git root) - Repository-specific
3. **Subdirectory** (cwd) - Directory-specific

Each scope adds to the previous - hints merge, base instructions concatenate with source markers.

## Upgrade Notes

- No breaking changes
- Existing single-file AGENTS.md setups continue to work
- New global config directory `~/.ppxai/` is searched automatically

## Files Changed

### Hierarchical Scopes
- `ppxai/engine/bootstrap.py` - `ContextScope`, `find_git_root()`, `find_bootstrap_files_by_scope()`
- `ppxai/engine/context.py` - `ScopedBootstrapSource`, `load_bootstrap_context_merged()`
- `ppxai/engine/client.py` - Updated bootstrap loading and status methods
- `ppxai/commands/utility.py` - `/context show` command
- `ppxai/server/http.py` - `GET /context/bootstrap` endpoint
- `ppxai/web/app.js` - Web app `/context show` handler
- `vscode-extension/src/chatPanel.ts` - VSCode `/context show` handler
- `vscode-extension/src/httpClient.ts` - `getBootstrapStatus()` method

### Enhanced Context Providers
- `ppxai/engine/context.py` - `inject_clipboard_context()`, `inject_url_context()`, `@clipboard`/`@url` patterns
- `ppxai/engine/bootstrap.py` - `_process_includes()`, `load_hint_templates()`, template expansion
- `pyproject.toml` - Added `pyperclip>=1.8.0` dependency

## New Dependencies

- **pyperclip** - Cross-platform clipboard access (text only)
