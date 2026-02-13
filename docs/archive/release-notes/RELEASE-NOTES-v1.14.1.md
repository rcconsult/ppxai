# Release Notes - v1.14.1

**Release Date:** January 21, 2026

## Summary

v1.14.1 adds the `/edit` command for VSCode and Web App interfaces, enabling an edit-test-save workflow for tuning AGENTS.md bootstrap context. The TUI `/edit` command was cancelled for the Rich TUI; ppxaide (Textual TUI) provides full file editing via its CodeEditor widget.

## New Features

### `/edit` Command (VSCode)
- Opens files in native VSCode editor with full language support
- Supports `file:line:col` syntax for precise positioning
- Split pane alongside chat panel
- Inherits all installed VSCode extensions (syntax highlighting, linting, etc.)

### `/edit` Command (Web App)
- Monaco-style editor with syntax highlighting
- Line numbers and Ctrl+S save support
- Auto-detects language from file extension
- Split-pane layout with chat

### `/context reload` Command
- Refresh AGENTS.md/CLAUDE.md from disk without restarting
- Available in TUI, VSCode, and Web App
- Useful after editing bootstrap files externally

### Auto-Reload on Save
- Editing AGENTS.md or CLAUDE.md via `/edit` automatically offers to reload bootstrap context
- Streamlines the edit-test-save workflow

### `POST /files/write` Endpoint
- Server-side file write support for VSCode and Web editors
- Enables save functionality from browser-based editors

## Bug Fixes

### Gemini Provider Error Handling
- Added missing `_format_error` and `_log_error_traceback` methods to GeminiProvider
- Fixes "object has no attribute '_format_error'" errors during API failures

## Deferred

### TUI `/edit` Command
- Deferred to v1.15.x
- Simple line editor approach had UX issues (stacked views, no horizontal cursor movement)
- Will implement proper Textual-based editor in future release

## Upgrade Notes

No breaking changes. Upgrade by downloading new binaries or running:

```bash
# Linux/macOS
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash

# Windows PowerShell
irm https://raw.githubusercontent.com/rcconsult/ppxai/master/scripts/install.ps1 | iex
```

## Full Changelog

See [CHANGELOG.md](../CHANGELOG.md) for complete list of changes.
