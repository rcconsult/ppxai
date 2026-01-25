# TUI Side Panel Refactor - Design Document

**Version:** 2.2
**Date:** 2026-01-25
**Status:** Phase 5 Complete - Ready for Engine Integration
**Target Release:** v1.15.0 (comprehensive release, ships when ready)
**Latest:** Image display fixes applied (commit f777028)

## Architectural Constraint: TUI Isolation

**CRITICAL**: The Textual-based TUI (`ppxai/tui/`) is a **completely separate implementation** from the Rich-based TUI (`ppxai/main.py`, `ppxai/ui.py`, etc.).

### Isolation Rules

1. **Zero Cross-Imports**
   - `ppxai/tui/**/*.py` must NEVER import from `ppxai.ui`, `ppxai.ui_components`, `ppxai.markdown_tables`, or `ppxai.utils`
   - Old Rich TUI files must NEVER import from `ppxai.tui.*`

2. **Changes Have Zero Impact**
   - Modifying any Textual TUI code MUST have zero impact on Rich TUI functionality
   - Modifying any Rich TUI code MUST have zero impact on Textual TUI functionality

3. **Shared Infrastructure Only**
   - Both TUIs may import from UI-agnostic modules:
     - `ppxai/config/` - Configuration
     - `ppxai/engine/` - Core business logic
     - `ppxai/commands/` - Command framework
     - `ppxai/common/` - Logging, events
     - `ppxai/prompts.py`, `ppxai/version.py`

4. **Separate Entry Points** (after Phase 0.0)
   - OLD Rich TUI: `ppxai` → `ppxai/rich/main.py` (prompt_toolkit + Rich)
   - NEW Textual TUI: `ppxaide` → `ppxai/tui/__init__.py` (Textual framework)

### Directory Structure (Target - After Phase 0.0)

```
ppxai/
├── rich/                    # OLD Rich TUI (ISOLATED after Phase 0.0)
│   ├── __init__.py
│   ├── main.py              # Entry point (ppxai command)
│   ├── ui.py                # Display functions
│   ├── ui_components.py     # UI components
│   ├── markdown_tables.py   # Markdown rendering
│   ├── themes.py            # Rich themes
│   ├── utils.py             # Utilities
│   └── event_handler.py     # TUIEventHandler
│
├── tui/                     # NEW Textual TUI (ISOLATED)
│   ├── __init__.py          # Textual entry point
│   ├── app.py               # PPXAIDEApp
│   ├── commands.py          # TUI-specific commands
│   ├── widgets/             # Textual widgets
│   ├── screens/             # Textual screens
│   └── themes/              # Textual themes/CSS
│
├── config/                  # SHARED - UI agnostic
├── engine/                  # SHARED - UI agnostic
├── commands/                # SHARED - Framework only
└── common/                  # SHARED - Logger only
```

### Validation

Pre-commit check to enforce isolation (after Phase 0.0):
```bash
# Textual TUI must not import from Rich TUI
! grep -r "from ppxai\.rich" ppxai/tui/

# Rich TUI must not import from Textual TUI
! grep -r "from ppxai\.tui" ppxai/rich/
```

---

## Overview

Refactor the `/show` command and side panel to provide format-aware viewing with consistent UX matching the web app.

## Current State

### Side Panel Modes

| Mode | Widget | Behavior |
|------|--------|----------|
| `code` | `CodeEditor` (read-only) | Syntax highlighting, line numbers |
| `markdown` | `Markdown` in `VerticalScroll` | Rendered markdown |
| `tree` | `TreeViewer` | Expandable tree for JSON/YAML/TOML |
| `image` | `Static` (info text) | Shows metadata, no actual rendering |

### Limitations

1. **Images**: Cannot render inline (terminal protocols don't work in Textual widgets)
2. **Structured data**: No toggle between tree and source view
3. **No unified viewer widget**: Logic scattered in `SidePanel.show_file()`

## Proposed Architecture

### New Widget: `DataViewer`

A composite widget for JSON/YAML/TOML with tree/source toggle.

```
┌─────────────────────────────────────┐
│ config.json (tree)     [Ctrl+V: source] │  ← Header with mode indicator
├─────────────────────────────────────┤
│                                     │
│  ▼ root                             │  ← TreeViewer (tree mode)
│    ▼ settings                       │
│        theme: "dark"                │
│        timeout: 30                  │
│                                     │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ config.json (source)   [Ctrl+V: tree]   │  ← Header with mode indicator
├─────────────────────────────────────┤
│  1│ {                               │  ← CodeEditor (source mode)
│  2│   "settings": {                 │
│  3│     "theme": "dark",            │
│  4│     "timeout": 30               │
│  5│   }                             │
│  6│ }                               │
└─────────────────────────────────────┘
```

### New Widget: `ImageViewer`

A widget that uses `textual-image` when available, with factory pattern for graceful degradation.

**Library:** [textual-image](https://pypi.org/project/textual-image/) provides:
- Terminal image display via iTerm2, Kitty, or Sixel protocols
- Auto-scaling to container width
- Aspect ratio preservation

**Note:** Uses `Image` widget class (not `AutoImage`)

```
┌─────────────────────────────────────┐
│ diagram.png (image)    [+/- zoom]   │
├─────────────────────────────────────┤
│                                     │
│     ┌───────────────────┐           │  ← Rendered image (zoom/pan enabled)
│     │                   │           │
│     │   [Image here]    │           │
│     │                   │           │
│     └───────────────────┘           │
│                                     │
│  3500x2274 · 885.6 KB · 100%        │  ← Info bar with zoom level
└─────────────────────────────────────┘
```

**Controls:**
- `+` / `-` or scroll: Zoom in/out
- `W`/`A`/`S`/`D` or drag: Pan
- `0` or `Home`: Reset to fit-to-view

**Fallback (no textual-imageview):**
```
┌─────────────────────────────────────┐
│ diagram.png (image)                 │
├─────────────────────────────────────┤
│                                     │
│         diagram.png                 │
│                                     │
│     Size: 885.6 KB                  │
│     Dimensions: 3500x2274           │
│                                     │
│     [textual-imageview not installed]│
│     pip install textual-imageview   │
│                                     │
└─────────────────────────────────────┘
```

**Large File Handling:**
- Files ≤ 20MB: Load immediately
- Files > 20MB: Show warning dialog, require user confirmation

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `ppxai/tui/widgets/base.py` | SafeQueryMixin for defensive widget queries |
| `ppxai/tui/widgets/content_factory.py` | File display mode detection and constants |
| `ppxai/tui/validation.py` | Path traversal and file size validation |
| `ppxai/tui/widgets/data_viewer.py` | DataViewer widget (tree/source toggle) |
| `ppxai/tui/widgets/image_viewer.py` | ImageViewer widget (textual-imageview + fallback) |

### Modified Files

| File | Changes |
|------|---------|
| `ppxai/tui/widgets/__init__.py` | Export new widgets |
| `ppxai/tui/widgets/side_panel.py` | Use new widgets, simplify show_file() |
| `ppxai/tui/themes/layout.tcss` | CSS for new widgets |
| `pyproject.toml` | Optional dependency: `textual-image` |

### Unchanged Files

| File | Reason |
|------|--------|
| `ppxai/tui/commands.py` | No changes needed, calls `show_file_in_panel()` |
| `ppxai/tui/widgets/code_editor.py` | Already works well |
| `ppxai/tui/widgets/tree_viewer.py` | Reused inside DataViewer |

## Widget Specifications

### DataViewer

```python
class DataViewer(Widget):
    """Viewer for structured data (JSON/YAML/TOML) with tree/source toggle."""

    BINDINGS = [
        Binding("ctrl+v", "toggle_view", "Toggle View", show=True),
    ]

    def __init__(
        self,
        content: str,
        format: str,  # "json", "yaml", "toml"
        filename: str,
        id: str = None,
    ):
        ...

    @property
    def view_mode(self) -> str:
        """Current view mode: 'tree' or 'source'"""
        ...

    def action_toggle_view(self) -> None:
        """Toggle between tree and source view."""
        ...

    def _get_source_line_for_tree_node(self, node_path: list) -> int:
        """Get source line number for a tree node path."""
        ...
```

**Internal Structure:**
- Header: `Static` showing filename and current mode
- Content: `ContentSwitcher` containing:
  - `TreeViewer` (id="tree-view")
  - `CodeEditor` (id="source-view", read_only=True)

**State Preservation:**
- Tree expand/collapse state is preserved when toggling views
- When switching tree → source: cursor jumps to line corresponding to selected tree node
- When switching source → tree: expand tree to show node at cursor line (if mappable)

**Cursor Sync Algorithm:**
1. For JSON: Parse with line tracking, map JSON path to line numbers
2. For YAML: Use ruamel.yaml with round-trip loader for line info
3. For TOML: Use tomli with position tracking (if available) or line estimation

### ImageViewer

```python
class ImageViewer(Widget):
    """Image viewer with textual-imageview support and graceful fallback."""

    BINDINGS = [
        Binding("plus", "zoom_in", "Zoom In", show=False),
        Binding("minus", "zoom_out", "Zoom Out", show=False),
        Binding("0", "zoom_reset", "Reset", show=False),
        Binding("w", "pan_up", "Pan Up", show=False),
        Binding("s", "pan_down", "Pan Down", show=False),
        Binding("a", "pan_left", "Pan Left", show=False),
        Binding("d", "pan_right", "Pan Right", show=False),
    ]

    # Large file threshold (20MB)
    LARGE_FILE_THRESHOLD = 20 * 1024 * 1024

    def __init__(
        self,
        path: Path,
        id: str = None,
    ):
        ...

    @staticmethod
    def is_supported() -> bool:
        """Check if textual-imageview is available."""
        try:
            from textual_imageview import ImageViewer as TIVImageViewer
            return True
        except ImportError:
            return False

    @property
    def zoom_level(self) -> int:
        """Current zoom percentage."""
        ...
```

**Behavior:**
1. Check file size - if > 20MB, emit confirmation message before loading
2. Check if `textual-imageview` is installed
3. If yes: wrap `textual_imageview.ImageViewer` with zoom/pan controls
4. If no: show info panel with install instructions

## Keybindings

### Side Panel (existing)

| Key | Action | Context |
|-----|--------|---------|
| `Escape` | Close panel | All modes |
| `Ctrl+L` | Cycle language | Code mode only |
| `Ctrl+W` | Close panel | Global |
| `Ctrl+S` | Save | Edit mode only |

### DataViewer (new)

| Key | Action | Context |
|-----|--------|---------|
| `Ctrl+V` | Toggle tree/source | DataViewer only |

### ImageViewer (new)

| Key | Action | Context |
|-----|--------|---------|
| `+` / scroll up | Zoom in | ImageViewer only |
| `-` / scroll down | Zoom out | ImageViewer only |
| `0` / `Home` | Reset to fit | ImageViewer only |
| `W` / `A` / `S` / `D` | Pan up/left/down/right | ImageViewer only |
| Mouse drag | Pan | ImageViewer only |

### Side Panel Header Updates

The header should show the current mode and available actions:

```
# Code mode
 main.py (view)                              (python)

# Data mode - tree
 config.json (tree)                     [Ctrl+V: source]

# Data mode - source
 config.json (source)                     [Ctrl+V: tree]

# Image mode
 diagram.png (image)

# Markdown mode
 README.md (view)
```

## CSS Additions

```css
/* DataViewer */
DataViewer {
    height: 1fr;
    layout: vertical;
}

DataViewer #data-header {
    height: 1;
    background: $panel;
    padding: 0 1;
}

DataViewer #data-filename {
    width: 1fr;
}

DataViewer #data-mode-hint {
    width: auto;
    color: $text-muted;
}

DataViewer ContentSwitcher {
    height: 1fr;
}

DataViewer TreeViewer {
    height: 1fr;
    border: none;
}

DataViewer CodeEditor {
    height: 1fr;
    border: none;
}

/* ImageViewer */
ImageViewer {
    height: 1fr;
    align: center middle;
}

ImageViewer #image-info {
    height: 1;
    dock: bottom;
    background: $panel;
    color: $text-muted;
    text-align: center;
}

ImageViewer #image-fallback {
    padding: 2;
    text-align: center;
}
```

## Dependencies

### Required (already installed)
- `textual` >= 0.40.0
- `pillow` (for image dimension detection)

### Optional (new)
- `textual-imageview` >= 0.2.0 (for image rendering with zoom/pan)

**pyproject.toml addition:**
```toml
[project.optional-dependencies]
images = ["textual-imageview>=0.2.0"]
```

**Note:** `textual-imageview` internally uses `pillow` for image processing.

## Release Strategy

**v1.15.0** is a comprehensive release that ships when ready. It includes all phases below.
**v1.15.1+** will be bug fix releases only.

**Philosophy:** Validate the Textual UI framework thoroughly before connecting to the proven engine layer.
The engine (EngineClient, streaming, providers) is already battle-tested in Rich TUI, Web App, and VSCode.
What's new and unproven is the Textual UI - so we validate that first.

```
Order of work:
  Foundation (Phase 0) → Visual Validation (Phase 1) → Data Widgets (Phase 2-3)
  → Side Panel (Phase 4) → E2E Validation (Phase 5) → Engine Integration (Phase 6)
```

---

## Implementation Order

### Phase 0.0: Rich TUI Isolation Refactor (FIRST - Defensive Measure)

**CRITICAL PREREQUISITE**: Before ANY Textual TUI work, physically isolate the Rich TUI codebase to guarantee zero impact.

#### Goal

Move all Rich TUI code to `ppxai/rich/` subdirectory to make cross-imports impossible and ensure changes to Textual TUI cannot break Rich TUI.

#### Files to Move

| From | To |
|------|-----|
| `ppxai/main.py` | `ppxai/rich/main.py` |
| `ppxai/ui.py` | `ppxai/rich/ui.py` |
| `ppxai/ui_components.py` | `ppxai/rich/ui_components.py` |
| `ppxai/markdown_tables.py` | `ppxai/rich/markdown_tables.py` |
| `ppxai/utils.py` | `ppxai/rich/utils.py` |
| `ppxai/themes.py` | `ppxai/rich/themes.py` |
| `ppxai/common/event_handler.py` | `ppxai/rich/event_handler.py` |

#### Import Updates Required

| Location | Changes |
|----------|---------|
| **Within moved files** | ~15 changes: `.config` → `..config`, `.commands` → `..commands`, etc. |
| `ppxai/commands/agent.py` | Update `TUIEventHandler` import path |
| `ppxai/common/__init__.py` | Remove/redirect `EventHandler` export |
| `pyproject.toml` | Entry point: `ppxai.main:main` → `ppxai.rich.main:main` |
| **Tests (4 files)** | `test_ui.py`, `test_markdown_tables.py`, `test_common_event_handler.py`, `test_reasoning_tokens.py` |

#### Resulting Structure

```
ppxai/
├── rich/                    # OLD Rich TUI (ISOLATED)
│   ├── __init__.py
│   ├── main.py              # Entry point (ppxai command)
│   ├── ui.py                # Display functions
│   ├── ui_components.py     # UI components
│   ├── markdown_tables.py   # Markdown rendering
│   ├── themes.py            # Rich themes
│   ├── utils.py             # Utilities
│   └── event_handler.py     # TUIEventHandler
│
├── tui/                     # NEW Textual TUI (ISOLATED)
│   └── ...
│
├── config/                  # SHARED - UI agnostic
├── engine/                  # SHARED - UI agnostic
├── commands/                # SHARED - Framework only
└── common/                  # SHARED - Logger only (EventHandler removed)
```

#### Verification Steps

1. **After refactor, run tests:**
   ```bash
   uv run pytest tests/test_ui.py tests/test_markdown_tables.py -v
   ```

2. **Test Rich TUI manually:**
   ```bash
   uv run ppxai
   # Verify: welcome screen, /help, /status, send message, /quit
   ```

3. **Test Textual TUI unchanged:**
   ```bash
   uv run ppxaide
   # Verify: launches, /help, /show, themes work
   ```

4. **Verify isolation:**
   ```bash
   # Must return no matches
   grep -r "from ppxai\.rich" ppxai/tui/
   grep -r "from ppxai\.tui" ppxai/rich/
   ```

#### Acceptance Criteria

- [ ] All Rich TUI files moved to `ppxai/rich/`
- [ ] `ppxai` command launches Rich TUI correctly
- [ ] `ppxaide` command launches Textual TUI correctly
- [ ] All existing tests pass
- [ ] User manual verification: Rich TUI works identically to before
- [ ] Zero cross-imports between `ppxai/rich/` and `ppxai/tui/`

**⚠️ GATE: Do NOT proceed to Phase 0.1 until Rich TUI is verified working by user.**

---

### Phase 0.1: Technical Debt Cleanup (Prerequisites)

Before implementing new widgets, address critical technical debt to ensure a clean foundation.

#### 0.1.1 Error Handling Cleanup (HIGH PRIORITY)

**Problem:** 38+ bare-except blocks with silent `pass` statements mask failures.

**Files to fix:**
- `widgets/message_box.py` - 1 bare-except
- `widgets/status_bar.py` - 3 bare-except
- `widgets/code_editor.py` - 5 bare-except
- `widgets/side_panel.py` - 4 bare-except
- `screens/editor.py` - 3 bare-except

**Action:**
1. Replace `except Exception: pass` with specific exceptions
2. Add logging: `self.log.warning(f"Failed to {action}: {e}")`
3. Use `from textual.css.query import NoMatches` for query failures

**Example fix:**
```python
# Before
try:
    editor = self.query_one("#panel-editor", CodeEditor)
    editor.language = new_lang
except Exception:
    pass

# After
from textual.css.query import NoMatches
try:
    editor = self.query_one("#panel-editor", CodeEditor)
    editor.language = new_lang
except NoMatches:
    self.log.debug("CodeEditor not mounted, skipping language update")
```

#### 0.1.2 CSS Consolidation (MEDIUM PRIORITY)

**Problem:** CSS split between `layout.tcss` and inline `DEFAULT_CSS` in `side_panel.py`.

**Action:**
1. Move `SidePanel.DEFAULT_CSS` (lines 26-76) to `layout.tcss`
2. Remove `DEFAULT_CSS` from `side_panel.py`
3. Add section comments to `layout.tcss` for organization

#### 0.1.3 Create Safe Query Helper (MEDIUM PRIORITY)

**Problem:** Repeated try-except wrapping around `query_one()` calls.

**Action:** Add helper method to base widget or mixin:

```python
# ppxai/tui/widgets/base.py (new file)
from typing import TypeVar, Optional, Callable
from textual.widget import Widget
from textual.css.query import NoMatches

T = TypeVar('T', bound=Widget)

class SafeQueryMixin:
    """Mixin providing safe widget query methods."""

    def safe_query_one(
        self,
        selector: str,
        widget_type: type[T],
        action: Optional[Callable[[T], None]] = None
    ) -> Optional[T]:
        """Query for widget, optionally execute action, handle missing gracefully."""
        try:
            widget = self.query_one(selector, widget_type)
            if action:
                action(widget)
            return widget
        except NoMatches:
            self.log.debug(f"Widget not found: {selector}")
            return None
```

#### 0.1.4 Extract File Display Factory (MEDIUM PRIORITY)

**Problem:** File display logic duplicated in 3 locations.

**Action:** Create centralized factory:

```python
# ppxai/tui/widgets/content_factory.py (new file)
from pathlib import Path
from typing import Tuple, Optional
from textual.widget import Widget

# File type detection
DATA_FORMATS = {'.json', '.yaml', '.yml', '.toml'}
IMAGE_FORMATS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.tiff', '.tif'}
MARKDOWN_FORMATS = {'.md', '.markdown'}

def detect_display_mode(path: Path) -> str:
    """Detect appropriate display mode for a file."""
    ext = path.suffix.lower()
    if ext in DATA_FORMATS:
        return "data"
    elif ext in IMAGE_FORMATS:
        return "image"
    elif ext in MARKDOWN_FORMATS:
        return "markdown"
    return "code"

def get_data_format(path: Path) -> Optional[str]:
    """Get specific data format (json/yaml/toml) for a path."""
    ext = path.suffix.lower()
    if ext == '.json':
        return 'json'
    elif ext in ('.yaml', '.yml'):
        return 'yaml'
    elif ext == '.toml':
        return 'toml'
    return None
```

#### 0.1.5 Input Validation (LOW-MEDIUM PRIORITY)

**Problem:** Path traversal and file size not validated.

**Action:** Add validation helpers:

```python
# ppxai/tui/validation.py (new file)
from pathlib import Path
from typing import Optional

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB for text files
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB for images

def safe_resolve_path(path_str: str, base_dir: str) -> Optional[Path]:
    """Resolve path safely, preventing traversal attacks."""
    base = Path(base_dir).resolve()
    target = (base / path_str).resolve()

    # Ensure target is within base or is absolute path explicitly given
    if path_str.startswith('/') or path_str.startswith('~'):
        return target if target.exists() else None

    # For relative paths, ensure within working directory
    try:
        target.relative_to(base)
        return target if target.exists() else None
    except ValueError:
        return None  # Path traversal attempt

def validate_file_size(path: Path, max_size: int = MAX_FILE_SIZE) -> bool:
    """Check if file size is within limits."""
    return path.stat().st_size <= max_size
```

#### Phase 0.1 Checklist

- [ ] Replace bare-except blocks with specific exceptions (16+ files)
- [ ] Add logging to exception handlers
- [ ] Move SidePanel CSS to layout.tcss
- [ ] Create `widgets/base.py` with SafeQueryMixin
- [ ] Create `widgets/content_factory.py` with display mode detection
- [ ] Create `validation.py` with path/size validation
- [ ] Update existing widgets to use new helpers
- [ ] Run tests to verify no regressions

---

### Phase 1: Core Visual Validation

**Goal:** Prove Textual's core widgets work reliably for our use cases before adding complexity.

#### 1.1 StatusBar Stress Test

**Validates:** Reactive updates, badge rendering, theme integration

| Test | Description |
|------|-------------|
| Rapid updates | Update provider/model 100x in quick succession |
| Long text | Provider/model names that exceed expected width |
| Theme switching | All 17+ themes render badges correctly |
| Edge cases | Empty values, None values, special characters |

#### 1.2 ChatView Scrolling

**Validates:** Large message lists, auto-scroll behavior

| Test | Description |
|------|-------------|
| 1000+ messages | Performance with large conversation history |
| Auto-scroll | New messages scroll into view |
| Manual scroll | User scroll position preserved when reviewing history |
| Long messages | Single message with 1000+ lines |

#### 1.3 InputBox Edge Cases

**Validates:** Multi-line input, paste handling, history

| Test | Description |
|------|-------------|
| Multi-line paste | Paste 100+ lines of text |
| History navigation | Up/down arrow through 50+ history items |
| Unicode | Emoji, CJK characters, RTL text |
| Large input | Type/paste 10KB of text |

#### 1.4 Theme Switching

**Validates:** All themes render all widgets correctly

| Test | Description |
|------|-------------|
| All built-in themes | 17+ Textual themes tested |
| Custom themes | tron-legacy, matrix themes |
| Dynamic switching | Ctrl+T cycles without visual glitches |
| Widget consistency | All widgets use theme colors correctly |

#### 1.5 Keybinding Conflicts

**Validates:** No keybinding collisions between widgets

| Test | Description |
|------|-------------|
| Global bindings | Ctrl+C, Ctrl+L, Ctrl+T work everywhere |
| Focus-specific | Escape, Enter behave correctly per context |
| No dead-ends | Can always navigate away from any widget |

**Phase 1 Deliverable:** Confidence that core shell is production-ready.

---

### Phase 2: DataViewer Widget

**Goal:** Complex widget for structured data with tree/source toggle.

#### 2.1 DataViewer (Tree Mode)

1. Create `ppxai/tui/widgets/data_viewer.py`
2. Wrap `TreeViewer` for JSON/YAML/TOML display
3. Header shows filename and "(tree)" mode indicator
4. Add CSS to `layout.tcss`

#### 2.2 DataViewer (Source Mode)

1. Add `CodeEditor` (read-only) as alternate view
2. Syntax highlighting for json/yaml/toml
3. Header shows "(source)" mode indicator

#### 2.3 Tree ↔ Source Toggle

1. Implement `Ctrl+V` to toggle views
2. Use `ContentSwitcher` for smooth transitions
3. Header hint: `[Ctrl+V: source]` or `[Ctrl+V: tree]`

#### 2.4 State Preservation

1. Tree expand/collapse state preserved on toggle
2. Tree → source: cursor jumps to line of selected node
3. Source → tree: tree expands to show node at cursor line

#### 2.5 Large File Handling

1. Test with 10K+ node JSON files
2. Lazy loading for deep trees
3. Performance benchmarks

**Phase 2 Deliverable:** DataViewer widget matching Web App functionality.

---

### Phase 3: ImageViewer Widget

**Goal:** Terminal image support with graceful degradation.

#### 3.1 ImageViewer (Fallback)

1. Create `ppxai/tui/widgets/image_viewer.py`
2. Display file info when `textual-imageview` not installed
3. Show: filename, dimensions, file size, install instructions

#### 3.2 ImageViewer (Full)

1. Detect and wrap `textual-imageview` library
2. Fit-to-view on initial display
3. Info bar showing dimensions and zoom level

#### 3.3 Zoom/Pan Controls

1. `+`/`-` keys for zoom in/out
2. `W`/`A`/`S`/`D` keys for pan
3. `0` key to reset to fit-to-view
4. Mouse scroll for zoom
5. Mouse drag for pan

#### 3.4 Large Image Handling

1. Files > 20MB show confirmation dialog
2. Loading indicator during decode
3. Memory-efficient display

**Phase 3 Deliverable:** ImageViewer with optional library support.

---

### Phase 4: Side Panel Integration

**Goal:** Unified file viewing experience with all viewers.

#### 4.1 `/show` Command Polish

1. Use content factory for file type detection
2. Route to appropriate viewer (CodeEditor, DataViewer, ImageViewer, Markdown)
3. Consistent header format across all modes

#### 4.2 `/edit` Command

1. CodeEditor in edit mode (read_only=False)
2. Modified indicator in header
3. Ctrl+S to save
4. Unsaved changes warning on close

#### 4.3 Split Pane UX

1. Ctrl+[ / Ctrl+] to resize split
2. F6 / Ctrl+Tab to switch focus
3. Smooth transitions

#### 4.4 Panel State Management

1. Track open/close state
2. Remember last file shown
3. Clean state on close

**Phase 4 Deliverable:** Complete file viewing/editing in split view.

---

### Phase 5: End-to-End Validation

**Goal:** Prove the UI shell works perfectly WITHOUT engine connection.

#### Test Categories

| Category | Coverage |
|----------|----------|
| Widget lifecycle | Mount/unmount, focus, events |
| Theme consistency | All 17+ themes, all widgets |
| Keyboard navigation | No dead-ends, expected behavior |
| Mouse interaction | Click, scroll, drag where applicable |
| Edge cases | Empty states, error states, long content |
| Performance | 1000+ messages, large files, rapid theme switching |

#### Validation Criteria

- [ ] All widgets mount/unmount cleanly
- [ ] No memory leaks on long sessions
- [ ] Theme switching works for all widgets
- [ ] All keybindings documented and working
- [ ] Performance acceptable on reference hardware
- [ ] Test suite covers all critical paths

**Phase 5 Deliverable:** Comprehensive test suite proving UI reliability.

---

### Phase 6: Engine Integration

**Goal:** Connect validated UI to proven backend.

**Rationale for placing this last:**
- Engine layer is already proven (Rich TUI, Web App, VSCode)
- Integration is mechanical once UI is stable
- Don't want engine bugs masking UI bugs (or vice versa)

#### 6.1 Factory Pattern

1. Add `PPXAIDEApp.initialize()` class method
2. Load config: `get_default_provider()`, `get_default_model()`
3. Return configured app instance

#### 6.2 EngineClient Composition

1. Create `EngineClient` in `initialize()`
2. Store as `self._engine_client`
3. Subscribe to engine events

#### 6.3 Streaming Responses

1. Handle `EventType.STREAMING_*` events
2. Progressive rendering in ChatView
3. Loading indicators during response

#### 6.4 Provider/Model Switching

1. Connect `/provider` and `/model` commands
2. Reactive StatusBar updates
3. Re-initialize engine client on switch

#### 6.5 Command Handlers

1. Port all slash commands from Rich TUI
2. `/agent`, `/tools`, `/consent` support
3. `/session`, `/save`, `/load`, `/export`
4. `/checkpoint`, `/undo`
5. `/context`, `/usage`, `/config`

#### 6.6 Full Feature Parity

1. Token usage display
2. Cost estimation
3. Context injection (@file, @git, @tree)
4. Tool execution display

**Phase 6 Deliverable:** Fully functional AI assistant matching Rich TUI capabilities.

---

### Phase 7: Polish & Release

**Goal:** Production-ready v1.15.0 release.

#### Tasks

1. Performance optimization
2. Accessibility review
3. Documentation update
4. Cross-platform testing (Linux, macOS, Windows)
5. Binary builds (PyInstaller)
6. Release notes

**Phase 7 Deliverable:** v1.15.0 release.

## Testing Checklist

### DataViewer
- [ ] JSON file loads in tree view by default
- [ ] YAML file loads in tree view by default
- [ ] TOML file loads in tree view by default
- [ ] Ctrl+V toggles to source view
- [ ] Ctrl+V toggles back to tree view
- [ ] Source view has correct syntax highlighting
- [ ] Header updates to show current mode
- [ ] Theme changes propagate to source view
- [ ] Tree expand/collapse state preserved on toggle
- [ ] Tree → source: cursor jumps to corresponding line
- [ ] Source → tree: tree expands to show node at cursor

### ImageViewer
- [ ] PNG displays with textual-imageview (if installed)
- [ ] JPG displays with textual-imageview (if installed)
- [ ] Fallback shows info when textual-imageview missing
- [ ] Image dimensions displayed correctly
- [ ] File size displayed correctly
- [ ] Zoom in/out with +/- keys works
- [ ] Pan with W/A/S/D keys works
- [ ] Mouse scroll zoom works
- [ ] Mouse drag pan works
- [ ] Reset to fit with 0 key works
- [ ] Files > 20MB show confirmation dialog

### Integration
- [ ] `/show config.json` opens DataViewer
- [ ] `/show image.png` opens ImageViewer
- [ ] `/show main.py` opens CodeEditor (unchanged)
- [ ] `/show README.md` opens Markdown (unchanged)
- [ ] Escape closes panel from all modes
- [ ] Theme cycling works for all viewers

## Design Decisions

1. **Tree view expand state**: ✅ **Preserve state + cursor sync**
   - Expand/collapse state is preserved when toggling views
   - When switching tree → source: cursor jumps to line of selected tree node
   - When switching source → tree: tree expands to show node at cursor line
   - This enables seamless navigation between structural and textual views

2. **Image scaling**: ✅ **Fit-to-view with zoom/pan controls**
   - Initial view: fit image to available space, maintain aspect ratio
   - Zoom: `+`/`-` keys or mouse scroll
   - Pan: `W`/`A`/`S`/`D` keys or mouse drag
   - Reset: `0` key returns to fit-to-view
   - Using `textual-imageview` library for implementation

3. **Large files**: ✅ **20MB threshold with confirmation**
   - Files ≤ 20MB: Load immediately without warning
   - Files > 20MB: Show confirmation dialog before loading
   - Rationale: Modern systems handle 10-20MB images easily; high-DPI screenshots can be large

## Appendix: Side Panel Mode Matrix

| File Extension | Mode | Widget | Toggle Available |
|----------------|------|--------|------------------|
| `.py`, `.js`, `.ts`, etc. | code | CodeEditor | No (Ctrl+L for lang) |
| `.md`, `.markdown` | markdown | Markdown | No |
| `.json` | data | DataViewer | Yes (Ctrl+V) |
| `.yaml`, `.yml` | data | DataViewer | Yes (Ctrl+V) |
| `.toml` | data | DataViewer | Yes (Ctrl+V) |
| `.png`, `.jpg`, `.gif`, etc. | image | ImageViewer | No |

---

**Document History:**
- v1.0 (2026-01-24): Initial draft
- v1.1 (2026-01-24): Approved with decisions on cursor sync, zoom/pan, file size threshold
- v1.2 (2026-01-24): Added Phase 0 technical debt cleanup prerequisites
- v1.3 (2026-01-24): Added architectural isolation constraint (Rich TUI ↔ Textual TUI separation)
- v1.4 (2026-01-24): Added Phase 0.0 Rich TUI isolation refactor as defensive prerequisite
- v1.5 (2026-01-25): Phase 0.0 complete, Phase 0.1.1 complete
- v1.6 (2026-01-25): Phase 0.1.2 complete (CSS consolidation)
- v1.7 (2026-01-25): Phase 0.1.3 complete (SafeQueryMixin)
- v1.8 (2026-01-25): Phase 0.1.4 complete (content factory)
- v2.0 (2026-01-25): Major restructure - consolidated all work into v1.15.0, added Phases 1-7
- v2.1 (2026-01-25): Phase 0.1.5 complete (input validation)
- v2.2 (2026-01-25): Phase 5 complete + Image display fixes (CSS, aspect ratio, centering)

**Release Strategy:**
- **v1.15.0**: Comprehensive release including all phases (0-7). Ships when ready.
- **v1.15.1+**: Bug fix releases only.

**Completed Phases:**
1. ~~Phase 0.0: Rich TUI isolation refactor~~ ✅
2. ~~Phase 0.1.1: Error handling cleanup~~ ✅
3. ~~Phase 0.1.2: CSS consolidation~~ ✅
4. ~~Phase 0.1.3: Safe query helper~~ ✅
5. ~~Phase 0.1.4: Content factory~~ ✅
6. ~~Phase 0.1.5: Input validation~~ ✅
7. ~~Phase 1: Core Visual Validation~~ ✅
8. ~~Phase 2: DataViewer widget (tree/source toggle)~~ ✅
9. ~~Phase 3: ImageViewer widget (with textual-image support)~~ ✅
10. ~~Phase 4: Side Panel Integration (/show, /edit, split pane UX)~~ ✅
11. ~~Phase 4.5: TableViewer widget (CSV/TSV)~~ ✅
12. ~~Phase 5: End-to-End Validation (comprehensive test suite)~~ ✅
13. **Phase 6: Engine Integration (EngineClient, streaming, commands)** ← NEXT
14. Phase 7: Polish & Release (performance, accessibility, docs, binaries)

**Latest Accomplishment (Jan 25, 2026):**
- Image display fixes: CSS selector (`AutoImage` → `Image`), aspect ratio (`height: auto`), vertical centering (`Center` container)
- Commit f777028 pushed to feature/new-tui-command branch
- 275 tests passing (254 platform + 21 image handlers)
- Ready for Phase 6: Engine Integration

**Sources:**
- [textual-image](https://pypi.org/project/textual-image/) - Terminal image widget (used in implementation)
- [Image Handler Architecture](image-handler-architecture.md) - Factory/delegation pattern design doc
- [Textual Images Discussion](https://github.com/Textualize/textual/discussions/4345) - Community discussion on image support
