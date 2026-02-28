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

**Status:** ✅ Done (3d1a57f) — 18 tests in tests/rendering/test_rich_interactive.py

---

### 8.7 — Client passes (sequential, after 8.1–8.6 tested)

Each client analysed in order. Each pass:
1. Scan for tech debt (TODOs, dead code, duplication, config issues)
2. Write implementation plan in this document
3. Implement + test
4. Commit before moving to next client

| Order | Client | Status |
|-------|--------|--------|
| 1 | **ppxai** (Rich TUI — `ppxai/rich/`) | ✅ Done (450b69a) — 8 fixes: 7 lazy imports→top, unused _render_markdown field, unused CODING_MODEL+web_premium imports, lazy normalize_consent_response, dead unreachable guard, no-op while loop |
| 2 | **ppxaide** (Textual TUI — `ppxai/tui/`) | ✅ Done (2bbdd10) — 5 files: 7 lazy imports in __init__.py main(), can_display_images in app.py, Path in input_box on_key(), os/logging/terminal symbols in image_handlers |
| 3 | **server** (`ppxai/server/` — incl. CommandFactory generalisation) | ✅ Done — http.py: removed StaticFiles, moved 28 lazy imports to top, extracted is_path_allowed()+MIME_TYPES+DEFAULT_HOST/PORT to module level, removed dead check_idle_shutdown(); session_manager.py: moved EngineClient+get_available_providers+os to module top, removed TYPE_CHECKING guard |
| 4 | **web app** (`ppxai/web/`) | ✅ Done — removed duplicate `generateUUID()` method from app.js (global from api-client.js used instead); extracted `escapeHtml()` to shared/formatters.js (removed from app.js, table-viewer.js, tree-viewer.js); updated test harness HTMLs to load formatters.js before components; 83 Playwright tests pass |
| 5 | **VSCode extension** (`vscode-extension/`) | ✅ Done — deleted dead backend.ts + aiClient.ts (735 lines, never imported); replaced hand-rolled generateUUID() in httpClient.ts with crypto.randomUUID() (Node.js stdlib); TS compile clean |

---

## Phase 10 — Regex Audit: Replace Fragile Patterns with Robust Parsers

**Background:** The codebase already contains a proven hand-written JSON subset parser
(`_find_json_objects()` in `parser.py`) after regex was found insufficient for nested
tool call structures. This phase applies the same principle across the remaining regex
usage: identify instances where regex is doing work that a proper parser would do more
reliably.

---

### 10.1 — Fix file modification claims detection in `validator.py`

**Severity:** 🔴 High (false negatives in hallucination detection)
**File:** `ppxai/engine/tools/validator.py:272-281`
**Effort:** ~30 min

Pattern `[^\s\`\"']+\.\w{1,5}` fails on:
- Multi-dot filenames: `config.backup.json` → captures only `json`
- Dot-only names: `.env`, `.gitignore` (no name part before the dot)
- Long-ish extensions: `.backup`, `.min.js`

These are all common in real tool results, so false negatives are frequent.

**Fix:** Replace with two-pass extraction:
1. Extract quoted/backtick-delimited filenames first (highest confidence)
2. Fall back to action-verb proximity scan (detect word near "saved"/"created"/etc.)
3. Validate candidates against filesystem if working_dir is available

**Status:** ✅ Done — commit `8937c33`

---

### 10.2 — Replace regex markdown link parsing with bracket-counting parser

**Severity:** 🔴 High (silently drops valid links in rendered output)
**File:** `ppxai/rendering/markdown_tables.py:54-90`
**Effort:** ~45 min

Patterns `([^\]]+)` and `([^)]+)` break on:
- Link text with nested brackets: `[API [v2]](url)` → misparses entirely
- URLs with parentheses: `[docs](https://example.com/func(v2))` → truncates URL
- Escaped chars inside either component

**Fix:** Replace both patterns with a character-level state machine (same approach as
`_find_json_objects()` in `parser.py`): scan forward tracking bracket/paren depth,
stop at the matching close character. This handles all valid markdown link syntax.

**Status:** ✅ Done — commit `8937c33`

---

### 10.3 — Simplify success-claim detection in `validator.py`

**Severity:** 🟡 Medium (performance + false positives)
**File:** `ppxai/engine/tools/validator.py:74-85`
**Effort:** ~20 min

The current 10-alternation regex `(created|written|saved|modified|updated|...)` is:
- Slow on every validation call
- Matches capability statements: "I can create files" (not a claim)
- Misses natural variants: "file generation completed", "write operation succeeded"

**Fix:** Replace regex alternation with keyword set + 50-char proximity window:
```python
SUCCESS_VERBS = {'created', 'written', 'saved', 'modified', 'updated', 'completed', 'generated', 'deleted'}
CLAIM_SIGNALS = {"i've", "i have", "successfully", "has been", "was", "were"}
# Claim = SUCCESS_VERB within 50 chars of a CLAIM_SIGNAL in lowercased text
```
Faster, tunable without regex knowledge, and separable from capability statements.

**Status:** ✅ Done — commit `8937c33`

---

### 10.4 — Use `_find_json_objects()` for tool JSON detection in `validator.py`

**Severity:** 🟡 Medium (duplication — robust parser exists but isn't used here)
**File:** `ppxai/engine/tools/validator.py:101-105`
**Effort:** ~15 min

The validator uses regex to detect tool call JSON in response text:
```python
re.search(r'\{[^{}]*"tool"[^{}]*\}', text)
```
This fails for any tool call with nested arguments (common). `_find_json_objects()` in
`parser.py` already handles full nested JSON correctly.

**Fix:** Import and call `_find_json_objects()` instead. The validator and parser are both
in `ppxai/engine/tools/` so no circular dependency.

**Status:** ✅ Done — commit `8937c33`

---

### 10.5 — Tighten Rich markup stripping in `chat_view.py`

**Severity:** 🟡 Medium (strips user content like `[1]` citation markers)
**File:** `ppxai/tui/widgets/chat_view.py:14`
**Effort:** ~20 min

Pattern `[/?[^\]]*]` strips every `[...]` token including:
- `[1]`, `[2]` — inline citation markers from Perplexity responses
- `[DONE]` — visible to users if it leaks
- Any bracketed user text

**Fix:** Match only valid Rich tag syntax (tag names are identifiers, optionally with
`/` prefix and `=value` suffix):
```python
re.compile(r'\[/?[a-zA-Z][a-zA-Z0-9_\- ]*(?:=[^\]]+)?\]')
```
Preserves `[1]`, `[2]`, `[DONE]` since they don't match identifier syntax.

**Status:** ✅ Done — commit `8937c33`

---

### 10.6 — Replace inline markdown formatting regex with linear pass

**Severity:** 🟢 Low (edge cases only, main use cases work)
**File:** `ppxai/rendering/markdown_tables.py:116-152`
**Effort:** ~30 min

The multi-alternation pattern for bold/italic/code formatting can't handle:
- Overlapping spans: `**bold _and italic_**`
- Adjacent same-type spans: `**a** **b**`
- Escaped markers: `\*not italic\*`

**Fix:** Single linear pass with explicit priority order: code spans first (highest
priority, no nesting), then bold, then italic. Each consumes its markers so the
others can't re-match.

**Status:** ✅ Done — commit `8937c33`

---

### Testing

Each fix should include edge-case tests covering the failure patterns documented above.
Key test cases:
- `.env`, `config.backup.json`, `styles.min.css` for 10.1
- `[API [v2]](url)`, `[docs](https://example.com/func(v2))` for 10.2
- `"I can create files"` (should NOT match) for 10.3
- Nested tool call JSON for 10.4

---

### Testing gate between phases

After 8.1–8.6 are done:
```bash
uv run pytest tests/ -x -q   # must be 0 failures before client passes begin
```

---

## Phase 9 — Bug Fixes from Web Debug Log Review

Items found by analysing `~/.ppxai/logs/server-debug.log` from a live web session.

---

### 9.1 — Fix `TypeError: 'bool' object is not iterable` in Codex/Responses API

**Severity:** 🔴 Critical (complete chat failure for gpt-5.1-codex and gpt-5.1-codex-mini)
**File:** `ppxai/engine/providers/openai_native.py:620`
**Effort:** ~10 min

`_non_stream_responses()` iterates `getattr(item, "content", [])` for Responses API
message output items. When `item.content` exists but holds a bool `True` (seen on some
Codex model variants), the fallback `[]` is never used and iterating a bool raises
`TypeError: 'bool' object is not iterable`.

```python
# BEFORE (line 620):
for part in getattr(item, "content", []):

# AFTER:
item_content = getattr(item, "content", None)
if isinstance(item_content, list):
    for part in item_content:
        if getattr(part, "type", None) == "output_text":
            content += getattr(part, "text", "")
elif isinstance(item_content, str):
    content += item_content
```

**Status:** ✅ Done — `isinstance` guard on `item_content`; 4 regression tests in `test_tool_messages.py::TestNonStreamResponsesContentExtraction`

---

### 9.2 — Add traceback logging to SSE event generator exception handler

**Severity:** 🟡 Medium (diagnostic quality — errors surface as bare messages with no stack)
**File:** `ppxai/server/http.py:452-453`
**Effort:** ~5 min

The SSE `except Exception as e:` handler only logs `str(e)`. Without the traceback
the root cause of errors like the `datetime` NameError (now fixed) took hours to trace.

```python
# BEFORE:
except Exception as e:
    logger.error(f"Exception in SSE event generator: {e}")

# AFTER:
except Exception as e:
    import traceback
    logger.error(f"Exception in SSE event generator: {e}\n{traceback.format_exc()}")
```

Note: `import traceback` should move to module top (no-lazy-imports rule).

**Status:** ✅ Done — `traceback` imported at module top; both `sse_event_generator` and `sse_coding_task_generator` now log full tracebacks on exception

---

### 9.3 — Fix lazy imports in `context.py`

**Severity:** 🟡 Medium (violates no-lazy-imports rule — 8 inline imports inside methods)
**File:** `ppxai/engine/context.py`
**Effort:** ~20 min

Lazy imports found:
- `import subprocess` inside `inject_git_context()` (line ~494)
- `import pyperclip` inside `inject_clipboard_context()` (line ~643)
- `import httpx` inside `inject_url_context()` (line ~712)
- `import re` inside `inject_url_context()` (line ~773)
- `import trafilatura` inside `inject_url_context()` (line ~777)
- `from ...config import get_max_injection_size` inside `_get_max_injection_size()` (line ~64)
- Several `from .bootstrap import ...` inside instance methods

**Fix:** Move all to module top. Guard optional deps (`pyperclip`, `trafilatura`, `httpx`)
with try/except at module level and check for `None` at call sites.

**Status:** ✅ Done — commit `d16ea8a`

---

### 9.4 — Fix lazy imports in `session.py`

**Severity:** 🟡 Medium (violates no-lazy-imports rule)
**File:** `ppxai/engine/session.py:691-692`
**Effort:** ~5 min

`save_usage_to_persistent_storage()` contains:
```python
from datetime import datetime        # already imported at line 12 — duplicate
from ..usage import save_session_usage  # lazy
```

`datetime` is already imported at module level (line 12) — the lazy import is redundant.
`save_session_usage` should be imported at module top.

**Status:** ✅ Done — commit `704ba1c`

---

### 9.5 — Validate message alternation before sending to provider

**Severity:** 🟡 Medium (prevents recurring 400 errors from Perplexity and other strict providers)
**File:** `ppxai/engine/chat.py`
**Effort:** ~30 min

Message alternation violations occur 6+ times in the log (400 from Perplexity `sonar`).
The existing `validate_and_fix_alternation()` in session.py is called on *save* (after the
error). It should also run *before* messages are sent to the provider at the start of each
`chat_with_tools` iteration.

```python
# In chat_with_tools(), before: async for event in ctx.provider.chat(...)
messages = ctx.session.get_messages()
fixed = ctx.session.validate_and_fix_alternation()
if fixed:
    logger.info(f"Pre-flight alternation fix: removed {fixed} messages")
    messages = ctx.session.get_messages()  # re-fetch after fix
```

**Status:** ✅ Done — commit `704ba1c` (also applied to `chat_simple`; trailing user message
is popped before fix and re-inserted after, so the current request is never removed)

