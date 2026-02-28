# TODO — v1.16.1: Norton Commander File Tree + CommandFactory Server Pattern

## Overview

Transform ppxaide from a two-pane layout (chat | optional side panel) into a
Norton Commander style: a permanently visible (Ctrl+B togglable) file tree on
the left, with the existing chat + side panel on the right.

Also: unify command execution across all clients via CommandFactory server pattern.

**Reference:** [ROADMAP.md — v1.16.1](../ROADMAP.md)

## Target Layout

```
┌──────────────────┬──────────────────────────────────────────┐
│  FileTree (25%)  │  chat-pane + side-panel (75%)            │
│                  │  ┌──────────────────────┬─────────────┐  │
│  DirectoryTree   │  │ ChatView (1fr)        │  SidePanel  │  │
│                  │  │                      │  (optional) │  │
│  Ctrl+B = toggle │  ├──────────────────────┴─────────────┤  │
│                  │  │ InputBox (always at bottom)         │  │
└──────────────────┴──────────────────────────────────────────┘
```

**Width rules:**
- File tree visible: `#file-tree 25%`, chat+panel share remaining 75%
- File tree hidden: chat+panel share 100% (existing behavior unchanged)
- Side panel open: splits the available space using existing `SPLIT_RATIOS` logic

## Key Bindings (new / changed)

| Key | Action |
|-----|--------|
| `Ctrl+B` | Toggle file tree show/hide |
| `Enter` (in file tree) | Open file preview in side panel (read-only) |
| `Ctrl+Enter` (in file tree) | Open file editor in side panel (editable) |
| `Space` (in file tree) | Inject `@file:path ` at cursor in chat input |
| `Escape` (in file tree) | Return focus to chat input |
| `F6` / `Ctrl+Tab` | Cycle focus: input → file tree → side panel → input |
| `↑↓` (in file tree) | Navigate files/dirs (free from Textual DirectoryTree) |
| `→` / `←` (in file tree) | Expand / collapse directory |
| `-` / `=` | Resize panes (file tree when focused, or chat/panel split) |
| `V` (in DataViewer/TableViewer) | Toggle tree/table ↔ source view |
| `E` (in DataViewer) | Expand all tree nodes |
| `C` (in DataViewer) | Collapse all tree nodes |

---

## Phase 1 — FileTree Widget

**Goal:** Self-contained widget with correct key bindings and messages.
No layout changes yet — mount it temporarily for isolated testing.

### Step 1.1 — Create `ppxai/tui/widgets/file_tree.py`

New widget extending Textual's `DirectoryTree`:

```python
from textual.widgets import DirectoryTree
from textual.binding import Binding
from textual.message import Message
from pathlib import Path

class FileTree(DirectoryTree):

    class FilePreview(Message):
        def __init__(self, path: Path) -> None: ...

    class FileEdit(Message):
        def __init__(self, path: Path) -> None: ...

    class FileInject(Message):
        def __init__(self, path: Path) -> None: ...

    BINDINGS = [
        Binding("enter",      "preview", "Preview", show=True),
        Binding("ctrl+enter", "edit",    "Edit",    show=True),
        Binding("space",      "inject",  "@file",   show=True),
        Binding("escape",     "dismiss", "Back",    show=False),
    ]

    # Track currently selected path
    _selected_path: Path | None = None

    def on_directory_tree_file_selected(self, event): ...
    def action_preview(self): ...   # post FilePreview
    def action_edit(self): ...      # post FileEdit
    def action_inject(self): ...    # post FileInject
    def action_dismiss(self): ...   # focus InputBox
```

Key behaviors:
- `on_directory_tree_file_selected` stores path but does NOT open anything
  (prevents double-open on Enter — handled by `action_preview`)
- Arrow/expand/collapse are native DirectoryTree behavior (no custom code)
- Root path: `Path(os.getcwd())` — passed at construction from `app.py`

**Status:** ✅ Done (0e032fa)

### Step 1.2 — Unit tests (`tests/test_file_tree.py`)

```python
# Test FilePreview message emitted on Enter
# Test FileEdit message emitted on Ctrl+Enter
# Test FileInject message emitted on Space
# Test action_dismiss focuses InputBox
# Test _selected_path updated on file selection
# Test filter_paths excludes _HIDDEN_DIRS
# Test _get_cursor_file_path handles DirEntry and Path
```

**Status:** ✅ Done (6d86194) — 28 tests: messages, bindings, filter_paths, mount, _get_cursor_file_path, FilePreview/Edit/Inject actions, dismiss

---

## Phase 2 — Layout Integration

**Goal:** Mount FileTree in the app, update CSS and split ratio logic.

### Step 2.1 — Update `ppxai/tui/app.py` compose()

Change:
```python
with Horizontal(id="main-content"):
    with Vertical(id="chat-pane"):
        yield ChatView(id="chat-view")
        yield InputBox(id="input-box")
    yield SidePanel(id="side-panel")
```

To:
```python
with Horizontal(id="main-content"):
    yield FileTree(Path(os.getcwd()), id="file-tree")
    with Vertical(id="chat-pane"):
        yield ChatView(id="chat-view")
        yield InputBox(id="input-box")
    yield SidePanel(id="side-panel")
```

Also add import:
```python
from ppxai.tui.widgets.file_tree import FileTree
```

### Step 2.2 — Add `#file-tree` CSS to `layout.tcss`

```css
FileTree {
    width: 25%;
    height: 100%;
    border-right: solid $surface-lighten-1;
    background: $surface;
}

FileTree.hidden {
    display: none;
}

FileTree DirectoryTree {
    background: $surface;
    scrollbar-background: $surface;
    scrollbar-color: $panel;
    scrollbar-color-hover: $primary;
}
```

### Step 2.3 — Add `_file_tree_visible` state to `PPXAIDEApp.__init__()`

```python
self._file_tree_visible: bool = True
```

### Step 2.4 — Add `action_toggle_file_tree()` and `Ctrl+B` binding

```python
# In BINDINGS:
Binding("ctrl+b", "toggle_file_tree", "Files", show=True),

# New method:
def action_toggle_file_tree(self) -> None:
    file_tree = self.query_one("#file-tree", FileTree)
    self._file_tree_visible = not self._file_tree_visible
    if self._file_tree_visible:
        file_tree.remove_class("hidden")
    else:
        file_tree.add_class("hidden")
    # No need to call _apply_split_ratio() — CSS handles it via 1fr
```

### Step 2.5 — Update `_apply_split_ratio()` for 3-pane awareness

The chat pane and side panel split logic is unchanged — they share whatever
space is left after the file tree's 25% CSS width. The `styles.width`
assignments in `_apply_split_ratio()` remain as percentages of total,
but when file tree is visible they should sum to 75%.

Update to:
```python
def _apply_split_ratio(self) -> None:
    available = 75 if self._file_tree_visible else 100
    chat_pct = int(self.SPLIT_RATIOS[self._split_index] * available / 100)
    panel_pct = available - chat_pct
    chat_pane.styles.width = f"{chat_pct}%"
    side_panel.styles.width = f"{panel_pct}%"
```

**Status:** ✅ Done (0e032fa)

---

## Phase 3 — Key Bindings and Event Handlers

### Step 3.1 — Update `action_toggle_focus()` for 3-stop cycle

```python
def action_toggle_focus(self) -> None:
    file_tree = self.query_one("#file-tree", FileTree)
    side_panel = self.query_one("#side-panel", SidePanel)
    input_box = self.query_one("#input-box", InputBox)
    focused = self.focused

    if focused and input_box in focused.ancestors_with_self:
        # input → file tree (if visible) or side panel (if open)
        if self._file_tree_visible:
            file_tree.focus()
        elif side_panel.is_open:
            side_panel.focus()
    elif focused and file_tree in focused.ancestors_with_self:
        # file tree → side panel (if open) or back to input
        if side_panel.is_open:
            side_panel.focus()
        else:
            input_box.focus()
    else:
        # side panel or anywhere else → input
        input_box.focus()
```

### Step 3.2 — Update `action_cancel()` for file tree escape

Add before the side panel check:
```python
file_tree = self.query_one("#file-tree", FileTree)
focused = self.focused
if focused and file_tree in focused.ancestors_with_self:
    self.query_one("#input-box", InputBox).focus()
    return
```

### Step 3.3 — Add event handlers in `app.py`

```python
async def on_file_tree_file_preview(self, event: FileTree.FilePreview) -> None:
    """Enter on file: open read-only preview in side panel."""
    path = event.path
    content = path.read_text(encoding="utf-8", errors="replace")
    side_panel = self.query_one("#side-panel", SidePanel)
    await side_panel.show_file(str(path), content, read_only=True)

async def on_file_tree_file_edit(self, event: FileTree.FileEdit) -> None:
    """Ctrl+Enter on file: open editable in side panel."""
    path = event.path
    content = path.read_text(encoding="utf-8", errors="replace")
    side_panel = self.query_one("#side-panel", SidePanel)
    await side_panel.show_file(str(path), content, read_only=False)

def on_file_tree_file_inject(self, event: FileTree.FileInject) -> None:
    """Space on file: inject @file:path into chat input."""
    rel = Path(event.path).relative_to(Path(os.getcwd()))
    input_box = self.query_one("#input-box", InputBox)
    input_box.inject_text(f"@file:{rel} ")
```

### Step 3.4 — Add `inject_text()` to `InputBox`

In `ppxai/tui/widgets/input_box.py`:
```python
def inject_text(self, text: str) -> None:
    """Insert text at cursor position in ChatTextArea."""
    text_area = self.query_one(ChatTextArea)
    text_area.insert(text)
    text_area.focus()
```

**Status:** ✅ Done (0e032fa)

---

## Phase 4 — Polish

### Step 4.1 — FileTree header with current directory

Root node label shows truncated cwd (last 2 path components) via `_short_path()`.
`update_root_path()` method syncs label when working directory changes.
`app.py:_on_working_dir_changed()` calls `file_tree.update_root_path()`.

**Status:** ✅ Done

### Step 4.2 — Resize keys for file tree and side panel

Primary keys: `-` (shrink) / `=` (grow) — work in all terminals.
Ctrl+[/] kept as fallback but unreliable (Ctrl+[ = ESC in most terminals).
`action_resize_panel()` detects focus in file tree and resizes tree width.
`TREE_WIDTHS = [15, 20, 25, 30, 35]` with default index 2 (25%).
`_apply_tree_width()` sets CSS width on file tree.
`_apply_split_ratio()` uses dynamic `TREE_WIDTHS[index]` instead of hardcoded 25%.

**Side panel fast path:** `side_panel.show_file()` reuses existing CodeEditor
for code-to-code transitions via `load_text()` instead of destroy+remount.
Avoids tree-sitter re-initialization overhead when browsing files.

**Status:** ✅ Done

### Step 4.3 — Theme auto-sync

`DirectoryTree` uses Textual's CSS variable system (`$surface`, `$primary`, etc.)
so it auto-syncs with app theme changes. No extra `watch_theme()` needed.

**Status:** ✅ Done (inherits from DirectoryTree CSS variables)

### Step 4.4 — Footer binding display

Add `Ctrl+B` to the visible footer bindings list.

**Status:** ✅ Done (0e032fa) — `show=True` in binding

---

## Phase 5 — Docs

### Step 5.1 — Update ROADMAP.md

Mark v1.16.1 file tree tasks as done as each phase completes.

**Status:** ✅ Done

---

## Phase 6 — Bug Fixes and Improvements

Items discovered during code review and test runs.

### Step 6.1 — Fix 4 failing tests

**Severity:** High | **Effort:** ~30m

- 2 Perplexity model config tests: swapped coding_model/default_model expectations
  to match v1.14.2 config change (sonar-pro is now default, sonar is coding)
- 2 shell tool tests: Windows `cmd.exe` doesn't support single quotes in arguments;
  use platform-aware quoting (`_Q` helper)

**Status:** ✅ Done (d29333a+)

### Step 6.2 — Side panel save prompt

**Severity:** Medium | **Effort:** ~15m

Reuses existing `ConfirmCloseScreen` from `screens/editor.py`.
`close()` now shows Y/N/Esc dialog when `_modified` is True.
`_do_close()` extracted for the actual close logic.

**File:** `ppxai/tui/widgets/side_panel.py`
**Status:** ✅ Done

### Step 6.3 — Textual renderer artifact tabs

**Severity:** Medium | **Effort:** N/A (deferred)

`CompositeResult` is never instantiated by any command — no real usage exists.
`ArtifactPanel` widget is ready; wiring deferred until a command produces composite output.
Removed TODO comment from renderer, added note explaining the situation.

**File:** `ppxai/rendering/textual_renderer.py`
**Status:** ✅ Done (deferred — no real usage)

### Step 6.4 — Print to logger migration

**Severity:** Low | **Effort:** ~5m

2 consent error `print()` calls → `logger.error()`.

**File:** `ppxai/engine/client.py`
**Status:** ✅ Done

### Step 6.5 — Gemini 3 action items cleanup

**Severity:** Low | **Effort:** ~15m

Updated ROADMAP.md action items: 5 items marked done (pricing, thinking_level,
model profiles, deprecations, SDK pin). 2 items assessed and deferred:
- Thought signatures: transparent; SDK handles propagation. No ppxai changes needed.
- Multimodal tool responses: text-only pipeline; deferred to v1.17.0+.

**File:** `ROADMAP.md`
**Status:** ✅ Done

---

## Critical Files

| File | Change |
|------|--------|
| `ppxai/tui/widgets/file_tree.py` | **CREATE** — new FileTree widget |
| `ppxai/tui/app.py` | compose(), bindings, focus, event handlers |
| `ppxai/tui/themes/layout.tcss` | FileTree CSS, split ratio updates |
| `ppxai/tui/widgets/input_box.py` | Add `inject_text()` method |
| `ppxai/tui/widgets/side_panel.py` | Save prompt on close (Step 6.2) |
| `ppxai/rendering/textual_renderer.py` | Artifact tabs (Step 6.3) |
| `ppxai/engine/client.py` | Print → logger (Step 6.4) |
| `tests/test_file_tree.py` | ✅ Done — 28 unit tests |
| `tests/test_file_tree_integration.py` | **CREATE** — integration tests |

## Reused Infrastructure (No Changes Needed)

- `SidePanel.show_file(path, content, mode, read_only)` — called directly
- `_apply_split_ratio()` — extended, not rewritten
- `action_toggle_focus()` / `action_cancel()` — extended with FileTree branch
- `Ctrl+[/]` resize — extended for file tree resize

## Phase 7 — CommandFactory Server Pattern (POC: /usage)

**Goal:** Single command implementation serves all clients. Only rendering differs.

### Architecture

```
User: /usage [args]
        │
        ▼
  handle_usage(context, args) → CommandResult   ← SINGLE implementation
        │           │           │           │
    ppxai(Rich)  ppxaide     server       web/vscode
    RichRenderer TextualRenderer to_dict()  formatTableResult()
```

### Step 7.1 — Add `to_dict()` to CommandResult types

Serialization for HTTP/JSON transport on `TableResult`, `ConfirmationResult`,
`KeyValueResult`, `ErrorResult`.

**File:** `ppxai/commands/results.py`
**Status:** ✅ Done (d29333a)

### Step 7.2 — Add `ServerCommandContext` adapter

Wraps `EngineClient` for server-side command execution. Uses public methods only.

**File:** `ppxai/commands/context.py`
**Status:** ✅ Done (f2b2171, d29333a)

### Step 7.3 — Add generic command execution endpoint

`POST /command/{name}` — 10-line generic dispatcher via CommandFactory.

**File:** `ppxai/server/http.py`
**Status:** ✅ Done (d29333a)

### Step 7.4 — Replace web app `handleUsageCommand()` with server call

Single `fetch()` + `renderCommandResult()` dispatcher.

**File:** `ppxai/web/app.js`
**Status:** ✅ Done (d29333a)

### Step 7.5 — Add shared formatters for CommandResult types

`formatTableResult()` with usage-aware rich rendering (bullet summary + table).
`formatKeyValueResult()` for key-value pairs.
No-cache headers on `/shared/` route.

**Files:** `ppxai/web/shared/formatters.js`, `vscode-extension/src/shared/formatters.ts`
**Status:** ✅ Done (d29333a)

### Step 7.6 — Replace VSCode `handleUsageCommand()` with server call

`executeCommand()` in httpClient.ts + `renderCommandResult()` in chatPanel.ts.

**Files:** `vscode-extension/src/httpClient.ts`, `vscode-extension/src/chatPanel.ts`
**Status:** ✅ Done (d29333a)

### Step 7.7 — Structured metadata for rich rendering

Usage `TableResult` includes structured metadata (total_tokens, prompt_tokens, etc.)
so formatters can render bullet-point summaries above the table.

**File:** `ppxai/commands/tools.py`
**Status:** ✅ Done (d29333a)

### Step 7.8 — Integration tests

18 tests validating counter values across 3 real providers (Perplexity, Gemini, OpenAI).
Tests compare table row values against raw `session.get_usage()` data.

**File:** `tests/test_usage_integration.py`
**Status:** ✅ Done (d29333a)

### Future: Generalize to all commands

`POST /command/{name}` already works for ANY registered command. Next steps:
- Migrate `/provider`, `/model`, `/tools`, `/status` to use same pattern
- Remove bespoke server endpoints as clients migrate
- Web app and VSCode switch statements shrink to just `renderCommandResult()`

---

## Out of Scope (v1.17.0+)

- File tree in web app or Rich CLI
- Create / rename / delete from tree
- Git status markers (modified / untracked files)
- Bookmarks / pinned directories

---

## Phase 8 — Pre-Release Technical Debt: Shared/Common Codebase

**Goal:** Fix confirmed bugs, remove dead code, and eliminate duplication in the shared engine/commands/rendering layer before touching any client. All items tested before moving to client passes.

---

### 8.1 — Fix duplicate checkpoint manager init in `set_working_dir()`

**Severity:** 🔴 High (bug — checkpoint ID restore is silently skipped)
**File:** `ppxai/engine/client.py:211-218`
**Effort:** ~5 min

`set_working_dir()` calls `self._init_checkpoint_manager(path)` on line 209, then immediately re-executes the identical 8-line block inline (lines 211-218), overwriting the checkpoint manager without running the checkpoint-ID-restore logic from `_init_checkpoint_manager`. The inline block is dead duplication.

**Fix:** Delete lines 211-218 (the inline block). The method call on line 209 is correct.

**Status:** ✅ Done (c47dd61)

---

### 8.2 — Fix duplicate model-switch context-reset in `set_model()`

**Severity:** 🟡 Medium (duplication, not a bug — both branches are correct, just verbose)
**File:** `ppxai/engine/client.py:557-561 and 572-576`
**Effort:** ~10 min

The 5-line block:
```python
if reset_context and self.session.messages:
    removed = self.session.reset_for_model_switch()
    self.last_model_switch_reset = removed
    if removed:
        logger.info(f"Reset context for model switch to {model_id}: removed {removed} messages")
```
appears verbatim twice — once for models in the list (lines 557-561) and once for the flexible fallback (lines 572-576). Both branches then call `self._log_model_hints_transition(model_id)` and `return True`.

**Fix:** Extract the repeated block + final two lines into `_apply_model_switch(model_id, reset_context)`, call from both branches. Reduces `set_model()` by ~12 lines.

**Status:** ✅ Done (c47dd61)

---

### 8.3 — Remove unused `asdict` import in `client.py`

**Severity:** 🟢 Low
**File:** `ppxai/engine/client.py:12`
**Effort:** ~1 min

`from dataclasses import asdict` — imported but never called anywhere in the file.

**Fix:** Delete the import line.

**Status:** ✅ Done (c47dd61)

---

### 8.4 — Standardise `set_*` vs `switch_*` method naming

**Severity:** 🟡 Medium (API inconsistency, causes adapter boilerplate)
**Files:** `ppxai/commands/handler.py`, `ppxai/commands/context.py`
**Effort:** ~30 min

`CommandHandler` uses `switch_provider()` / `switch_model()`, while `EngineClient` and `CommandContext` protocol use `set_provider()` / `set_model()`. The `RichCommandContext` adapter (context.py lines 71-72) exists solely to bridge this mismatch.

**Fix:** Rename `CommandHandler.switch_provider()` → `set_provider()` and `switch_model()` → `set_model()` throughout `handler.py`. Remove the bridging aliases from `context.py`.

**Status:** ✅ Done (c47dd61)

---

### 8.5 — Remove redundant session alternation validation in `_save_with_extras()`

**Severity:** 🟢 Low (double-validation, no bug)
**File:** `ppxai/engine/session.py`
**Effort:** ~5 min

`_save_with_extras()` calls `validate_and_fix_alternation()` before saving (line ~800), but `_save_with_extras` is always called via `save()` which also calls it (line ~516). Validation runs twice.

**Fix:** Remove the `validate_and_fix_alternation()` call from `_save_with_extras()`. Validation in `save()` is sufficient.

**Status:** ✅ Done (c47dd61)

---

### 8.6 — Rich renderer: complete `ConsentResult` and `PromptResult`

**Severity:** 🟡 Medium (feature gap — interactive prompts fall back to placeholder text)
**File:** `ppxai/rendering/rich_renderer.py`
**Effort:** ~1h

Two renderers have TODO placeholders:
- `ConsentResult` renderer: shows options as text instead of interactive prompt
- `PromptResult` renderer: prints "not yet implemented"

**Fix:** Implement both using `prompt_toolkit` or Rich's `Prompt.ask()`.

**Status:** ⏳ Pending

---

### 8.7 — Client passes (sequential, after 8.1–8.6 tested)

Each client analysed in order. Each pass:
1. Scan for tech debt (TODOs, dead code, duplication, config issues)
2. Write implementation plan in this document
3. Implement + test
4. Commit before moving to next client

| Order | Client | Status |
|-------|--------|--------|
| 1 | **ppxai** (Rich TUI — `ppxai/rich/`) | ⏳ Not started |
| 2 | **ppxaide** (Textual TUI — `ppxai/tui/`) | ⏳ Not started |
| 3 | **server** (`ppxai/server/` — incl. CommandFactory generalisation) | ⏳ Not started |
| 4 | **web app** (`ppxai/web/`) | ⏳ Not started |
| 5 | **VSCode extension** (`vscode-extension/`) | ⏳ Not started |

---

### Testing gate between phases

After 8.1–8.6 are done:
```bash
uv run pytest tests/ -x -q   # must be 0 failures before client passes begin
```

