# Release Notes: v1.16.1

**Release Date:** 2026-03-01
**Branch:** feature/v1.16.1
**Focus:** FileTree browser, CommandFactory server pattern, unified session restore, pre-release tech debt

---

## Overview

v1.16.1 adds a Norton Commander-style file tree to ppxaide, unifies command execution
across all clients via the CommandFactory server pattern, centralises session restore
into a single engine method, and completes a comprehensive pre-release tech debt pass
covering lazy imports, regex robustness, and defensive bug fixes.

**Key Numbers:**
- 1,624 tests passing (up from 1,536 in v1.16.0)
- 88 new tests (+28 FileTree, +20 regex/parsing edge cases, +40 other)
- 45 tracked tech debt items — all resolved
- 0 lazy imports remaining in engine layer

---

## New Features

### FileTree Widget — Norton Commander Browser (`Ctrl+B`)

ppxaide now has a permanently-available file tree on the left side (25% width), toggled
with `Ctrl+B`. The tree integrates with the existing chat + side panel layout.

**Key bindings (when file tree focused):**

| Key | Action |
|-----|--------|
| `Ctrl+B` | Toggle file tree show/hide |
| `Enter` | Preview file read-only in side panel |
| `Ctrl+Enter` | Open file for editing in side panel |
| `Space` | Inject `@file:path ` at cursor in chat input |
| `Escape` | Return focus to chat input |
| `F6` / `Ctrl+Tab` | Cycle focus: input → file tree → side panel → input |
| `-` / `=` | Resize file tree / chat-panel split |

**Features:**
- Displays `cwd` in header; re-roots automatically when working directory changes
- Filters `.git`, `__pycache__`, `.venv`, `node_modules` and other hidden dirs
- `Space` appends `@file:path ` to the chat input so context injection works immediately
- Side panel opens in read-only preview mode (`Enter`) or editable mode (`Ctrl+Enter`)
- 28 unit tests in `tests/test_file_tree.py` covering messages, bindings, filter_paths, actions

### CommandFactory Server Pattern — Unified `/usage` via `POST /command`

The HTTP server now exposes a `POST /command` endpoint that routes to the same
`CommandFactory` used by the TUI and Rich CLI. `/usage` was the first command migrated.

**Before:** `/usage` was only available in the TUI. VSCode/Web clients had no equivalent.

**After:** Any client can call `POST /command {"command": "/usage"}` and receive the
same structured `UsageResult` that the TUI renders locally.

This is the foundation for unifying all slash commands across clients without duplicating
logic.

### Unified Session Restore — `EngineClient.restore_session()`

Session save/load/restore now has a single authoritative implementation in
`EngineClient.restore_session()` that covers all engine-level state:

1. Reload config (provider/model lists current)
2. Load session (messages, metadata, command history, tools_enabled, working_dir)
3. Restore provider (validate against providers_config)
4. Restore model (strict=True, fallback to provider default)
5. Restore tools enabled/disabled
6. Restore working directory

**Fixes:** The JSON-RPC server previously never restored provider/model on session load.
All 5 clients (ppxaide TUI, ppxai Rich CLI, HTTP `/sessions/load`, HTTP `/sessions/restore`,
JSON-RPC `load_session`) now use the same restore path.

---

## Bug Fixes

### Codex / Responses API — `TypeError: 'bool' object is not iterable`

`_non_stream_responses()` in `openai_native.py` iterated `item.content` assuming it was
always a list. Some Responses API event types return `content=True` (a bool). The fix
guards with `isinstance(item_content, list)` and logs a warning for unexpected types.

### SSE Exception Handler — Full Traceback Logging

`sse_event_generator` and `sse_coding_task_generator` in `http.py` now log the full
Python traceback (via `traceback.format_exc()`) on exception, unconditionally (not gated
by debug mode). The coding task generator previously had no exception logging at all.

### Pre-flight Alternation Validation

`validate_and_fix_alternation()` is now called in both `chat_simple()` and
`chat_with_tools()` before sending messages to the provider. This prevents recurring 400
errors from Perplexity and other strict providers when session history has consecutive
same-role messages from prior failures.

The trailing user message is popped before the check and re-inserted after, so the fix
only cleans up history without removing the current request.

### Gemini — `thinking_budget` Deprecated

`GeminiProvider` replaced the deprecated `thinking_budget` parameter with `thinking_level`
as required by the updated google-genai SDK.

### `ppxai-server` Binary — `prompt_toolkit` Import Error

`ppxai-server.spec` had `prompt_toolkit` in the PyInstaller `excludes` list. The transitive
import chain `commands/__init__.py` → `handler.py` → `from prompt_toolkit import prompt`
caused the server binary to crash on startup with `ModuleNotFoundError`.

### Side Panel Save Prompt on Close

The side panel now prompts "Save changes?" when closed with unsaved edits (was silently discarding).

### Ctrl+Enter in FileTree

App-level `priority=True` on the `ctrl+enter` submit binding was intercepting the FileTree's
`ctrl+enter` (open for editing) before the widget could handle it. Fixed by making the
FileTree binding higher-priority within its focused context.

### Duplicate Model/Provider Switch Logging

Command handlers were logging model/provider switches twice (once in the command, once in
the engine). Consolidated to a single log entry per switch.

### `STREAM_START` Missing in `chat_simple`

`chat_simple()` was not emitting `STREAM_START` in all code paths, causing the TUI to
show a spinner indefinitely on some simple (non-tool) responses.

---

## Tech Debt

### Lazy Import Elimination (Engine Layer)

All lazy imports (inline `from X import Y` inside function bodies) have been removed from
the engine layer in compliance with the no-lazy-imports / DAG-style import rule:

| File | Imports moved to module top |
|------|-----------------------------|
| `engine/context.py` | `subprocess`, `re`, `BootstrapContext`, `find_bootstrap_files_by_scope`, config helpers; optional `httpx`/`pyperclip`/`trafilatura` via `try/except` at module level |
| `engine/session.py` | `save_session_usage`, duplicate `datetime` |
| `server/http.py` | `PROVIDERS`, `get_default_model` (were imported inside endpoint functions) |
| `server/jsonrpc.py` | Config helpers |
| `rich/` client | Various lazy imports across TUI/handler modules |

### Regex Robustness (6 Improvements)

| Location | Old regex | Problem | Fix |
|----------|-----------|---------|-----|
| `validator.py` filename detection | `[^\s]+\.\w{1,5}` | Missed `.env`, `config.backup.json` | `(?:\.[\w\-]+\|[^\s]*\w(?:\.\w+)+)` |
| `markdown_tables.py` link parser | `[([^\]]+)]\(([^)]+)\)` | Broke on `[API [v2]](url)` and `[docs](url/f(v2))` | Bracket/paren depth counter `_extract_markdown_links()` |
| `validator.py` success claims | 10 regex alternations | False positive "I can create files"; slow | Keyword set + 60-char proximity window |
| `validator.py` tool JSON detection | `\{[^{}]*"tool"[^{}]*\}` | Failed on nested `{}` in arguments | `_find_json_objects()` from `parser.py` |
| `chat_view.py` Rich markup stripping | `\[/?[^\]]*\]` | Stripped citation markers `[1]`, `[2]` | Identifier-based tag pattern only |
| `markdown_tables.py` inline formatter | Multi-alternation regex | Broke on adjacent `**a** **b**`, overlapping spans | Linear pass: code > bold > italic |

### ConsentResult and PromptResult Renderers

`RichRenderer` (ppxai Rich CLI) was missing renderers for `ConsentResult` and `PromptResult`,
causing those result types to silently produce no output.

### DAG-Compliant Context Adapters

Context adapter modules were calling private methods across module boundaries, violating
the DAG import structure. Refactored to use only public methods and explicit interfaces.

---

## Test Summary

| Category | Count |
|----------|-------|
| FileTree widget tests | 28 |
| Regex / parsing edge cases | 20 |
| Non-stream Responses API content extraction | 4 |
| All other tests (v1.16.0 baseline) | 1,572 |
| **Total** | **1,624** |

All tests passing on macOS (Python 3.12).
