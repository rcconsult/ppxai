# Release Notes: v1.16.2

**Release Date:** 2026-03-07
**Branch:** bugfix/1.16.2
**Focus:** Web app RightPanelFrame, file tree sidebar, inline images, web refactor, server fixes

---

## Overview

v1.16.2 is a major web app iteration and bugfix release. The web app gains a full view
stack navigator (`RightPanelFrame`) with five file-type-aware view classes, a collapsible
file tree sidebar, and inline image rendering with lightbox zoom. The app.js god class has
been refactored into focused modules (ApiClient, CommandDispatcher, StreamHandler, AppState,
virtual scroll), cutting it roughly in half. Server-side fixes address stale session
pointers, default working directory, and file API path handling.

**Key Numbers:**
- 1,639 unit tests passing (up from 1,624 in v1.16.1)
- 200 Playwright E2E tests passing (up from ~115 in v1.16.1; +85 new web tests)
- app.js reduced from ~4,264 to ~2,100 lines via modular extraction

---

## New Features

### RightPanelFrame — View Stack Navigator

The right panel in the web app is now managed by `RightPanelFrame`, a full view stack:

- **LRU stack** (configurable depth, default 10) — least-recently-used view evicted when full
- **Deduplication** — opening an already-stacked file bumps it to top without duplicating
- **Back/forward navigation** — Cmd+← / Cmd+→ (macOS) or Alt+← / Alt+→ (Windows/Linux)
- **Pin** — pinned views are exempt from LRU eviction (📌 in dropdown)
- **State restore** — scroll position and editor cursor preserved on back/forward
- **Stack persistence** — optional `localStorage` persistence across page reload (off by default)
- **Position indicator** — `3/7` style counter in frame chrome
- **Dirty state** — `●` in title when file has unsaved changes

**View types by file extension:**

| Extension | View | Modes |
|-----------|------|-------|
| `.md`, `.rst` | `MarkdownFileView` | Rendered ↔ View Source ↔ Edit Source |
| `.csv`, `.tsv` | `DataFileView` | Table ↔ View Source ↔ Edit Source |
| `.json`, `.yaml`, `.toml`, `.hcl` | `DataFileView` | Tree ↔ View Source ↔ Edit Source |
| `.png`, `.jpg`, `.gif`, `.svg`, `.webp` | `ImageFileView` | Image + zoom (view only) |
| `.pdf` | `PdfFileView` | Embedded iframe (view only) |
| everything else | `CodeEditorView` | View ↔ Edit (single CodeMirror 6 instance) |

**New files:**
- `ppxai/web/components/right-panel-frame.js`
- `ppxai/web/components/views/base-view.js`
- `ppxai/web/components/views/code-editor-view.js`
- `ppxai/web/components/views/markdown-file-view.js`
- `ppxai/web/components/views/data-file-view.js`
- `ppxai/web/components/views/image-file-view.js`
- `ppxai/web/components/views/pdf-file-view.js`
- `ppxai/web/styles/right-panel-frame.css`

**Deleted:** `ppxai/web/components/editor-controller.js` (408 lines, replaced by `CodeEditorView`)

### Web App: Collapsible File Tree Sidebar

VSCode-style file browser in the web app (left of chat):

- Click `🗂` in the header to open/close
- Lazy-loads directory contents via `GET /files/list`
- Expand/collapse directories; state persists to `localStorage`
- Left-click file → opens in right panel (preview mode)
- Right-click file → injects `@file:path` at cursor in chat input
- Drag right edge of sidebar to resize
- Auto-refreshes when working directory changes

**Directory navigation (cd) interactions:**

| Action | Dirs | Files | `..` entry |
|--------|------|-------|-----------|
| Single-click | Expand / collapse | Preview (right panel) | cd to parent |
| Double-click | **cd into dir** (new working dir root) | Open for editing | — |
| Right-click | **cd here** (same as dbl-click) | Inject `@file:path` | — |

- `..` entry at top of tree lets you navigate up to the parent directory
- `..` is hidden when the server reports `at_fs_root: true` (filesystem root)
- cd actions fire `handleCdCommand` → server `setWorkingDir` → `working_dir_changed` SSE → folder badge + tree both update

### Web App: Inline Image Preview + Lightbox

Images served by the AI (via `display_file` or tool results) now render inline in chat bubbles:
- `<img>` thumbnails in chat messages instead of plain file links
- Click any image to open a lightbox zoom overlay
- Lightbox supports Escape or click-outside to dismiss

### Web App Refactor (Items 5–10)

`app.js` has been modularised into focused files:

| Module | Lines extracted | Purpose |
|--------|---------------:|---------|
| `shared/api-client.js` | ~180 | All `fetch()` calls with timeout and error shape |
| `shared/command-dispatcher.js` + `shared/commands/` | ~1,500 | Slash command routing |
| `shared/stream-handler.js` | ~250 | SSE buffer, RAF rendering, typed events |
| `components/editor-controller.js` (→ deleted in Phase 5) | ~340 | CodeMirror lifecycle |
| `shared/app-state.js` | — | Centralised state with listener notifications |
| Virtual scroll | — | 60-message DOM window with height sentinel |

---

## Bug Fixes

### Web App: Side Panel Saves to Wrong Path

When the AI opened `subdir/file.py` via `display_file`, saving wrote to `file.py` (root).

**Root cause (two-part):**
1. `/files/read` returned `path.name` (basename only) in the `filename` field
2. `app.js` used `data.filename` (basename) over the original `filepath` when opening the editor

**Fix:** `/files/read` now returns `path.relative_to(working_dir)`. `app.js` now prefers `filepath || data.filename` so the directory prefix is preserved.

### Validator False Positive on Apology

The validator fired `claim_without_action` on responses like:
> "You are absolutely right. My apologies. I missed the `uv.lock` file. Let's correct that."

**Fix:** `_claims_success()` in `validator.py` now returns `False` immediately if any apology
signal phrase is found (`"apologies"`, `"you are right"`, `"i missed"`, `"my bad"`, etc.)
via a `APOLOGY_SIGNALS` frozenset check before the main proximity-window heuristic runs.

### Inline `<think>` Block Parsing (Qwen3 / vLLM)

Qwen3 models served via vLLM with streaming emit thinking content as inline `<think>...</think>` blocks
within the assistant message. These were previously passed through as raw text.

**Fix:** `engine/chat.py` now detects inline `<think>` blocks in streaming chunks and routes them
to `REASONING_CHUNK` events (same path as DeepSeek R1 reasoning tokens), so they render in the
collapsible thinking panel rather than polluting the response text.

### Shell: Configurable Shell Binary and Login Mode

New `tools.shell` config keys in `ppxai-config.json`:

```json
"shell": {
  "shell_bin": "/bin/zsh",
  "login_shell": true
}
```

- `shell_bin` — path to the shell binary (`/bin/bash`, `/bin/zsh`, `/bin/sh`, etc.)
  When set, ppxai invokes commands as `[shell_bin, -c, command]` instead of relying on Python's default system shell.
- `login_shell` — when `true`, adds the `-l` flag (`[shell_bin, -l, -c, command]`), causing the shell to source the user's login profile (`~/.zprofile`, `~/.bash_profile`, etc.).
  This gives the subprocess the same PATH and environment as an interactive terminal session, making tools like `uv`, `nvm`, `pyenv`, `conda`, etc. available without requiring system-wide installation.

Both default to `null`/`false` for backwards compatibility — existing behaviour is unchanged.

### Post-Release Bug Fixes

| Bug | Fix |
|-----|-----|
| `Key.ctrl` binding removed (Textual deprecation) | Replaced with `ctrl+` string bindings |
| `initResizeHandle` null crash when sidebar absent | Added null guard before accessing element |
| Stale file tree paths after working dir change | Tree now re-roots on `working_dir_changed` event |
| Inline image disappears after `stream_end` | `stream_end` now appends inline image markdown instead of overwriting `fullContent` |
| Redundant `display_file` tool result bubble | `showToolResult` skips bubble when `data.tool === 'display_file'`; image/file already visible |
| Stale `expandedDirs` after cd | `refresh(clearExpanded=true)` collapses old subpaths on working dir change; fixes 404 storms |
| File tree flickers on every chat send | `working_dir_changed` debounce skips refresh when path unchanged (session restore replays same cwd) |
| AI text inserted above inline image | `stream_end` renders image before text, matching the order shown during streaming |

### Server: Stale Session Pointer

If a session file was deleted externally, the server's last-session pointer still pointed to the
deleted file, causing errors on auto-restore. The pointer is now cleared when the file no longer exists.

### Server: Absolute and Home Paths in File API

`/files/list` and `/files/tree` now accept:
- Absolute paths (`/home/user/project`)
- `~`-prefixed paths (`~/projects/myapp`)

### Server: Default Working Directory

Engine working directory is now initialised to `Path.home()` on session creation.
Previously it inherited the binary's CWD (often `/` when launched as a service), causing
`/files/list` to list the root filesystem.

### Redundant `set_model` Calls on `/provider` Switch

A single `/provider gemini` command triggered 3–4 redundant `set_model` calls, causing
model hint matching to run multiple times. The provider switch path is now idempotent:
duplicate calls with unchanged provider+model are no-ops.

---

## AGENTS.md Updates

- **Qwen3-4B model hints** — new `"Qwen3-4B*"` section with 8 calibrated hints
- **`local` provider hints** — expanded from 3 generic hints to 10 specific hints covering apply_patch, visible response, multi-strategy file search
- **`asusai-vllm` provider hints** — added "COMPLETE ALL STEPS" and "Explore thoroughly" hints
- **Removed "Make ONE tool call" anti-pattern** — this phrasing caused -21.4% regression in Qwen3-4B tool_calling; replaced with "avoid duplicates" + "chain different calls"
- **Global preferences** — reorganized code style, tool usage, and communication preferences

---

## Test Summary

| Category | Count |
|----------|-------|
| Unit tests (pytest) | 1,639 |
| Playwright E2E tests | 200 |
| New E2E: RightPanelFrame | +34 |
| New E2E: DataFileView | +29 |
| New E2E: MarkdownFileView | +22 |
| Other new E2E | ~15 |

All tests passing on macOS (Python 3.12, Node 20).
