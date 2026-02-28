# TODO — v1.16.1: Norton Commander File Tree

## Overview

Transform ppxaide from a two-pane layout (chat | optional side panel) into a
Norton Commander style: a permanently visible (Ctrl+B togglable) file tree on
the left, with the existing chat + side panel on the right.

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
| `Ctrl+[` / `Ctrl+]` | Resize panes (extended to include file tree) |

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

### Step 1.2 — Unit tests (`tests/test_file_tree.py`)

```python
# Test FilePreview message emitted on Enter
# Test FileEdit message emitted on Ctrl+Enter
# Test FileInject message emitted on Space
# Test action_dismiss focuses InputBox
# Test _selected_path updated on file selection
```

**Status:** ⏳ Pending

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

**Status:** ⏳ Pending

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

**Status:** ⏳ Pending

---

## Phase 4 — Polish

### Step 4.1 — FileTree header with current directory

Show truncated cwd path at top of file tree pane:
```css
#file-tree-header {
    height: 1;
    background: $panel;
    color: $text-muted;
    padding: 0 1;
    dock: top;
}
```

### Step 4.2 — Ctrl+[/] resize for file tree

Extend `action_resize_panel()` to also resize file tree when focused:
- When focus is in file tree: Ctrl+[ shrinks tree, Ctrl+] grows tree
- Current behavior (resize chat vs side panel) when focus is elsewhere

### Step 4.3 — Theme auto-sync

`DirectoryTree` uses Textual's CSS variable system (`$surface`, `$primary`, etc.)
so it auto-syncs with app theme changes. No extra `watch_theme()` needed.

### Step 4.4 — Footer binding display

Add `Ctrl+B` to the visible footer bindings list.

**Status:** ⏳ Pending

---

## Phase 5 — Tests and Docs

### Step 5.1 — Integration tests

```python
# tests/test_file_tree_integration.py
# Test: Enter on file → SidePanel.show_file called with read_only=True
# Test: Ctrl+Enter → SidePanel.show_file called with read_only=False
# Test: Space → InputBox contains "@file:path"
# Test: Ctrl+B → file tree hidden/shown
# Test: F6 cycle: input → tree → panel → input
```

### Step 5.2 — Update ROADMAP.md

Mark v1.16.1 file tree tasks as done as each phase completes.

**Status:** ⏳ Pending

---

## Critical Files

| File | Change |
|------|--------|
| `ppxai/tui/widgets/file_tree.py` | **CREATE** — new FileTree widget |
| `ppxai/tui/app.py` | compose(), bindings, focus, event handlers |
| `ppxai/tui/themes/layout.tcss` | FileTree CSS, split ratio updates |
| `ppxai/tui/widgets/input_box.py` | Add `inject_text()` method |
| `ppxai/tui/widgets/side_panel.py` | No changes — reuse `show_file()` as-is |
| `tests/test_file_tree.py` | **CREATE** — unit tests |

## Reused Infrastructure (No Changes Needed)

- `SidePanel.show_file(path, content, mode, read_only)` — called directly
- `_apply_split_ratio()` — extended, not rewritten
- `action_toggle_focus()` / `action_cancel()` — extended with FileTree branch
- `Ctrl+[/]` resize — extended for file tree resize

## Out of Scope (v1.17.0+)

- File tree in web app or Rich CLI
- Create / rename / delete from tree
- Git status markers (modified / untracked files)
- Bookmarks / pinned directories
