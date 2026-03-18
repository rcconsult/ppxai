# ppxaide Key Bindings Cleanup — Implementation Plan

**Status:** Done
**Priority:** Low — current state works, just messy
**Target:** v1.17.0 polish pass
**Created:** 2026-03-18
**Textual version:** 8.1.1 (upgraded from 7.4.0 on 2026-03-18)

---

## Context

Key binding management in ppxaide is scattered across 9 files with no single source of truth. App-level bindings live in `app.py:76-96`, widget bindings in `on_key()` handlers and per-widget `BINDINGS` lists, and terminal workarounds are documented in docstrings. A display-only `ctrl+enter` binding uses an empty action string hack. There's no way to see effective bindings at runtime.

**Goal:** Centralize all key definitions into a single registry module, clean up hacks, add a `/keys` command, and document the Kitty protocol situation. No user-visible behavior changes.

---

## Current State Audit

### App-level bindings (`ppxai/tui/app.py:76-96`)

14 bindings in `BINDINGS` list:

| Key | Action | Show | Notes |
|-----|--------|:----:|-------|
| ctrl+enter | `""` (empty) | Yes | Display-only hack — actual handling in ChatTextArea.on_key() and FileTree.action_edit() |
| ctrl+c | action_quit | Yes | Double-press confirmation |
| ctrl+b | action_toggle_file_tree | Yes | |
| ctrl+l | action_clear | Yes | |
| ctrl+t | action_cycle_theme | Yes | |
| ctrl+w | action_close_panel | No | |
| ctrl+s | action_save_panel | No | |
| f6 | action_toggle_focus | No | |
| ctrl+tab | action_toggle_focus | No | |
| escape | action_cancel | No | Priority: help panel > modal > file tree focus > side panel |
| q | action_hide_help_panel | No | |
| minus | action_resize_panel('left') | No | Primary resize (works in all terminals) |
| equals | action_resize_panel('right') | No | Primary resize |
| ctrl+[ | action_resize_panel('left') | No | Fallback — sends ESC in most terminals, unreliable |
| ctrl+] | action_resize_panel('right') | No | Fallback — Ghostty/Kitty only |

### Widget-level key handling

**ChatTextArea** (`ppxai/tui/widgets/input_box.py:14-58`)
- Uses `on_key()` (not `_on_key()` — intentional, allows Escape to bubble to app)
- `SUBMIT_KEYS = {"ctrl+enter", "ctrl+j"}`
- Consumes: ctrl+enter, ctrl+j (`event.prevent_default()` + `event.stop()`)
- Bubbles: everything else (Enter, Escape, etc.)
- Debug logging to `~/.ppxai/logs/keys.log` when `/debug-log on`

**InputBox** (`ppxai/tui/widgets/input_box.py:60-342`)
- Uses `on_key()` handler
- Consumes: tab (`prevent_default` + `stop`, for autocomplete)
- Partially consumes: up/down (`prevent_default` only, no `stop` — history navigation)
- Bubbles: everything else

**FileTree** (`ppxai/tui/widgets/file_tree.py:31-35`)
- `BINDINGS`: ctrl+enter → action_edit, space → action_inject, escape → action_dismiss_tree
- `on_directory_tree_file_selected`: Enter on file → `event.stop()`, posts FilePreview
- `on_click`: Ctrl+Click on file → `event.stop()`, posts FileEdit
- No `on_key` handler — relies on BINDINGS + DirectoryTree defaults

**SidePanel** (`ppxai/tui/widgets/side_panel.py:33-36`)
- `BINDINGS`: escape → action_close_panel, ctrl+l → action_cycle_language

**Other widgets with BINDINGS:**
- TableViewer (`table_viewer.py:156-158`): v → toggle_view
- EditorScreen (`screens/editor.py:26-29`): ctrl+s → save, escape → close
- ConfirmCloseScreen (`screens/editor.py:147-151`): y → save, n → discard, escape → cancel
- ViewerScreen (`screens/viewer.py:58-61`): escape/q → close
- MessageBox (`message_box.py`): `on_button_pressed` with `event.stop()` (copy button only)

### Known binding conflicts (all resolved by Textual focus system)

| Key | App action | Widget action | Resolution |
|-----|-----------|--------------|------------|
| ctrl+w | close_panel | TextArea delete-word-left | TextArea wins when focused |
| f6 | toggle_focus | TextArea select-line | TextArea wins when focused |
| ctrl+c | quit | TextArea copy | TextArea wins when focused |
| ctrl+l | clear | SidePanel cycle_language | SidePanel wins when focused |

These are **intentional** — Textual dispatches bindings to the focused widget first, app bindings are fallback.

### Textual 8.1.1 notes

Upgraded from 7.4.0 on 2026-03-18. Relevant changes for key bindings:

- **No breaking changes to BINDINGS API** — `App.BINDINGS`, `Widget.BINDINGS`, `Binding()`, `on_key()`, `_on_key()` all unchanged.
- **No Kitty keyboard protocol improvements** — issue [#6074](https://github.com/Textualize/textual/issues/6074) remains open. Progressive enhancement (`\x1b[>1u`) still not auto-negotiated. Ctrl+Enter/Ctrl+J dual-key strategy remains necessary.
- **DirectoryTree threading fixes** (8.0.1) — reduces micro-freezes in FileTree. No key handling changes.
- **New `App.mode_change_signal` / `App.screen_change_signal`** (8.0.0) — could be used in future to react to screen pushes, but not needed for key binding cleanup.
- **New themes** (8.0.0) — Catppuccin Frappe and Macchiato added. The `/keys` command and key registry are theme-independent.

---

## Commit 1: Create key registry module

**New file: `ppxai/tui/keys.py`** — leaf module, no ppxai imports (only `textual.binding.Binding`)

- `KeyDef` dataclass: `key`, `action`, `description`, `owner` (app/widget name), `show`, `context` (when active), `notes`, `is_binding` (True for Textual BINDINGS, False for on_key handlers)
- `ALL_KEYS: list[KeyDef]` — complete inventory of all bindings grouped by owner:
  - App (14): ctrl+enter, ctrl+c, ctrl+b, ctrl+l, ctrl+t, ctrl+w, ctrl+s, f6, ctrl+tab, escape, q, minus, equals, ctrl+[, ctrl+]
  - ChatTextArea (2): ctrl+enter, ctrl+j (`is_binding=False` — on_key handler)
  - InputBox (3): tab, up, down (`is_binding=False` — on_key handler)
  - FileTree (3): ctrl+enter, space, escape
  - SidePanel (2): escape, ctrl+l
  - TableViewer (1): v
  - EditorScreen (2): ctrl+s, escape
  - ConfirmCloseScreen (3): y, n, escape
  - ViewerScreen (2): escape, q
- `get_app_bindings() -> list[Binding]` — generates app BINDINGS from registry
- `get_widget_bindings(owner: str) -> list[Binding]` — generates widget BINDINGS from registry
- `get_keys_table() -> str` — formatted table for `/keys` output
- `get_conflicts_table() -> str` — documents known conflicts

**Modify: `ppxai/tui/app.py`**
- Replace inline `BINDINGS = [...]` (lines 76-96) with `BINDINGS = get_app_bindings()`
- Import `from ppxai.tui.keys import get_app_bindings`
- Move comments about ctrl+[/] unreliability into `keys.py`

---

## Commit 2: Migrate widget BINDINGS to registry

Replace hardcoded `BINDINGS` lists with `get_widget_bindings()` calls:

| File | Class | Current BINDINGS |
|------|-------|-----------------|
| `ppxai/tui/widgets/file_tree.py` | FileTree | ctrl+enter, space, escape |
| `ppxai/tui/widgets/side_panel.py` | SidePanel | escape, ctrl+l |
| `ppxai/tui/widgets/table_viewer.py` | TableViewer | v |
| `ppxai/tui/screens/editor.py` | EditorScreen | ctrl+s, escape |
| `ppxai/tui/screens/editor.py` | ConfirmCloseScreen | y, n, escape |
| `ppxai/tui/screens/viewer.py` | ViewerScreen | escape, q |

**NOT migrated** (intentional):
- `ChatTextArea.SUBMIT_KEYS` — a set used in `on_key()`, not a Textual BINDINGS list
- `InputBox.on_key()` tab/up/down — `on_key()` handlers, not BINDINGS
- These are documented in the registry as `owner="ChatTextArea"` / `owner="InputBox"` with `is_binding=False`

---

## Commit 3: Clean up display-only ctrl+enter hack

**Problem:** `Binding("ctrl+enter", "", "Send", show=True)` uses empty action string — works but confusing.

**Fix:**
- In `keys.py`: set ctrl+enter app binding action to `"noop"`
- In `app.py`: add `def action_noop(self) -> None: pass` with docstring explaining display-only pattern
- In `keys.py`: add `notes` field: "Display-only. Actual handling: ChatTextArea.on_key() and FileTree.action_edit()"

---

## Commit 4: Add `/keys` command

**Modify: `ppxai/commands/system.py`**

```python
def handle_keys(context: CommandContext, args: str) -> CommandResult:
    from ppxai.tui.keys import get_keys_table, get_conflicts_table
    if args.strip().lower() == "conflicts":
        return TextResult(status=ResultStatus.INFO, message=get_conflicts_table())
    return TextResult(status=ResultStatus.INFO, message=get_keys_table())

CommandFactory.register(CommandSpec(
    name="keys",
    description="Show keyboard shortcuts",
    handler=handle_keys,
    category="system",
    usage="/keys [conflicts]"
))
```

**Output format** (`/keys`):
```
Keyboard Shortcuts

  App-Level (always active)
  ─────────────────────────────────
  Ctrl+C        Quit (double-press)
  Ctrl+B        Toggle file tree
  Ctrl+L        Clear chat
  Ctrl+T        Cycle theme
  Ctrl+W        Close side panel
  Ctrl+S        Save side panel
  F6            Switch pane focus
  Ctrl+Tab      Switch pane focus
  Escape        Cancel / close panel
  -/=           Resize panel

  Chat Input
  ─────────────────────────────────
  Ctrl+Enter    Send message
  Ctrl+J        Send message (fallback)
  Tab           Autocomplete
  Up/Down       History navigation

  File Tree
  ─────────────────────────────────
  Enter         Preview file
  Ctrl+Enter    Edit file
  Space         Inject @file reference
  Escape        Return to input

  Side Panel
  ─────────────────────────────────
  Escape        Close panel
  Ctrl+L        Cycle language
```

Note: `/keys` uses a lazy import for `ppxai.tui.keys` since this is a command handler. This is the standard pattern in `ppxai/commands/system.py` where handlers already use lazy imports for TUI-specific modules (e.g., `handle_terminal` imports from `ppxai.tui.terminal`).

---

## Commit 5: Document Kitty protocol status

**Documentation only — no code changes.**

**Modify: `ppxai/tui/keys.py`** — add module-level docstring section:
```
Kitty Keyboard Protocol (Textual 8.x)
──────────────────────────────────────
Textual 8.1.1 does NOT auto-negotiate Kitty keyboard protocol (issue #6074 open).
Progressive enhancement (\x1b[>1u) is not enabled — it breaks printable char recognition.
- Ctrl+Enter: only works in Kitty (native), Ghostty (explicit keybind),
  WezTerm (enable_kitty_keyboard). Fallback: Ctrl+J.
- Ctrl+[: sends ESC in non-Kitty terminals. Primary resize: minus/equals.
No changes planned — fallback keys cover all terminals.
```

**Modify: `CLAUDE.md`** — add "Kitty Protocol" note under ppxaide Key Bindings section.

**Modify: `docs/TODO-v1.17.0.md`** — mark key bindings cleanup item as done.

---

## Commit sequence and dependencies

```
Commit 1: keys.py + app.py BINDINGS migration
    ↓
Commit 2: Widget BINDINGS migration (depends on keys.py)
    ↓
Commit 3: Display-only hack cleanup (depends on keys.py)
    ↓
Commit 4: /keys command (depends on keys.py get_keys_table)
    ↓
Commit 5: Kitty protocol docs (independent, placed last)
```

Commits 3 and 4 are independent of each other (both depend only on 1-2). Ordered 3→4 for logical flow.

---

## Files Modified

| File | Commits | Change |
|------|---------|--------|
| `ppxai/tui/keys.py` | 1,3,4,5 | **NEW** — central registry |
| `ppxai/tui/app.py` | 1,3 | Replace BINDINGS, add action_noop |
| `ppxai/tui/widgets/file_tree.py` | 2 | BINDINGS → get_widget_bindings() |
| `ppxai/tui/widgets/side_panel.py` | 2 | BINDINGS → get_widget_bindings() |
| `ppxai/tui/widgets/table_viewer.py` | 2 | BINDINGS → get_widget_bindings() |
| `ppxai/tui/screens/editor.py` | 2 | BINDINGS → get_widget_bindings() |
| `ppxai/tui/screens/viewer.py` | 2 | BINDINGS → get_widget_bindings() |
| `ppxai/commands/system.py` | 4 | Add /keys handler + registration |
| `CLAUDE.md` | 5 | Kitty protocol note |
| `docs/TODO-v1.17.0.md` | 5 | Mark done |

---

## Verification

1. **Unit tests:** `uv run pytest tests/test_tui.py -v` — existing TUI tests pass
2. **Registry tests:** Add `TestKeyRegistry` in `tests/test_tui.py`:
   - `test_app_bindings_count` — get_app_bindings() returns 14 bindings
   - `test_widget_bindings` — each widget gets correct binding count
   - `test_no_empty_actions` — no binding has action=""
   - `test_keys_table_output` — get_keys_table() returns non-empty string
3. **Manual smoke test:** Launch `uv run ppxaide`, verify:
   - All key bindings work as before (Ctrl+B, Ctrl+T, Escape, F6, etc.)
   - `/keys` shows formatted table
   - `/keys conflicts` shows conflict documentation
   - Ctrl+Enter submits in Kitty/Ghostty, Ctrl+J submits everywhere
4. **Import check:** `python -c "from ppxai.tui.keys import get_app_bindings, get_widget_bindings"` — no circular imports
