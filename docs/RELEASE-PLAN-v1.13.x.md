# Release Plan: v1.13.x Series

**Created:** January 3, 2026
**Last Updated:** January 5, 2026
**Status:** v1.13.2 Released (Series Complete)
**Branch:** `master`

---

## Theme: Custom Provider Parity & Desktop Web App

**Tagline:** Premium features for all providers, standalone desktop experience

## Overview

The v1.13.x series focused on two main areas:
1. **Custom Provider Parity** - Premium web search and tool calling for custom vLLM/Ollama endpoints
2. **Desktop Web App** - Standalone web UI with working directory context and file operations

## Release History

### v1.13.0 - Custom Provider Parity ✅ RELEASED

**Released:** January 3, 2026

**Scope:**
- Premium web search tool for custom providers (vLLM, Ollama)
- Priority fallback: Perplexity Sonar → Gemini Grounding → DuckDuckGo
- SSL_VERIFY environment variable for corporate proxy support
- `native_tool_calling` capability for vLLM endpoints
- `ToolUsage` dataclass for per-tool usage tracking
- Enhanced tool parsing with dispatcher pattern
- 525 tests passing (119 new tests)

See [RELEASE-NOTES-v1.13.0.md](RELEASE-NOTES-v1.13.0.md) for full details.

---

### v1.13.1 - Desktop Web App ✅ RELEASED

**Released:** January 4, 2026

**Scope:**
- Desktop Web App improvements with working directory context
- Folder badge in UI header showing current working directory
- `/show` command with fuzzy file search
- Filesystem tools respecting `engine.get_working_dir()` context
- `WORKING_DIR_CHANGED` event for UI notification
- Gemini Native Grounding fix for PyInstaller builds
- Build system fixes for Linux

**Key Features:**
- Working directory context persists across file operations
- `/show` command with fuzzy matching for file search
- Filesystem tool classes (`SetWorkingDirectoryTool`, `GetWorkingDirectoryTool`, etc.)
- HTTP endpoints for context management (`/context/working_dir`, `/files/read`, `/files/search`)

See [RELEASE-NOTES-v1.13.1.md](RELEASE-NOTES-v1.13.1.md) for full details.

---

### v1.13.2 - Bugfix Release ✅ RELEASED

**Released:** January 5, 2026

**Scope:**
- Fixed markdown rendering in Desktop Web App and VSCode extension
- Windows compatibility improvements
- Shared modules for feature parity across UIs

**Key Fixes:**
- **Markdown Bullet Lists:** Changed Unicode `•` to standard `-` for marked.js compatibility
- **`/usage` Tables:** Both UIs now display formatted tables with usage statistics
- **marked.js Update:** Web App upgraded from v9.1.6 to v11.1.1
- **Auto-detect Server URL:** Web UI uses `window.location.origin` instead of hardcoded URL
- **Favicon:** Added PNG favicon to Desktop Web App
- **Windows Tests:** Use `tempfile.gettempdir()` instead of hardcoded `/tmp`
- **PEP 735 Migration:** Migrated to `[dependency-groups].dev` format

**New Shared Modules:**
```
ppxai/web/shared/
├── commands.js      # Command definitions
├── formatters.js    # Response formatters
├── api-client.js    # HTTP client
└── index.js         # Module exports

vscode-extension/src/shared/
├── commands.ts      # TypeScript command definitions
├── formatters.ts    # TypeScript formatters
└── index.ts         # Module exports
```

See [RELEASE-NOTES-v1.13.2.md](RELEASE-NOTES-v1.13.2.md) for full details.

---

## Series Summary

| Version | Theme | Key Features |
|---------|-------|--------------|
| v1.13.0 | Custom Provider Parity | Premium web search, tool usage tracking |
| v1.13.1 | Desktop Web App | Working directory, file operations |
| v1.13.2 | Bugfix | Markdown rendering, Windows compat |

**Total New Tests:** 147+ across the series
**Final Test Count:** 553 passing

---

## Deferred to v1.14.x

The following features originally planned for v1.13.x have been moved to the v1.14.x series:

- **AGENTS.md/CLAUDE.md Support** - Auto-load project context from working directory
- **File Precedence** - Global, project, and subdirectory context hierarchy
- **`/context` Commands** - User control over loaded context
- **Context Enhancements** - Conditional sections, include directives

See [RELEASE-PLAN-v1.14.x.md](RELEASE-PLAN-v1.14.x.md) for the updated roadmap.

---

## References

- [v1.13.0 Release Notes](RELEASE-NOTES-v1.13.0.md)
- [v1.13.1 Release Notes](RELEASE-NOTES-v1.13.1.md)
- [v1.13.2 Release Notes](RELEASE-NOTES-v1.13.2.md)
- [ROADMAP.md](../ROADMAP.md)
- [v1.14.x Release Plan](RELEASE-PLAN-v1.14.x.md)
