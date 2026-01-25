# Image Handler Architecture

**Version:** v1.15.0
**Date:** January 25, 2026
**Status:** Implemented

---

## Overview

The ImageViewer widget uses a **factory/delegation pattern** to dispatch to the appropriate image handler based on both library availability and terminal capabilities. This provides a clean separation of concerns and enables graceful degradation.

## Architecture

### Design Pattern: Strategy + Factory

```
ImageHandlerFactory
    ↓ (creates based on capabilities)
ImageHandler (Protocol)
    ├── FullImageHandler (textual-imageview available + terminal supports images)
    └── FallbackHandler (library missing OR terminal doesn't support images)
        ↓
ImageViewer (delegates all operations to handler)
```

### Decision Tree

```
┌─────────────────────────────────────┐
│  ImageHandlerFactory.create()       │
└─────────────┬───────────────────────┘
              │
              ├─ Library installed? ──No──→ FallbackHandler(reason='library')
              │
              └─ Yes
                 │
                 ├─ Terminal supports images? ──No──→ FallbackHandler(reason='terminal')
                 │
                 └─ Yes
                    │
                    ├─ Create viewer? ──Fail──→ FallbackHandler(reason='error')
                    │
                    └─ Success ──→ FullImageHandler
```

## Components

### 1. ImageHandler Protocol

**File:** `ppxai/tui/widgets/image_handlers.py`

Defines the interface all handlers must implement:

```python
class ImageHandler(Protocol):
    """Protocol defining the interface for image handlers."""

    def compose(self) -> ComposeResult:
        """Compose the handler's UI elements."""
        ...

    def zoom_in(self) -> None:
        """Zoom in (if supported)."""
        ...

    def zoom_out(self) -> None:
        """Zoom out (if supported)."""
        ...

    def zoom_reset(self) -> None:
        """Reset zoom to default (if supported)."""
        ...

    def pan(self, dx: int, dy: int) -> None:
        """Pan the view (if supported)."""
        ...

    def focus(self) -> None:
        """Focus the handler's main widget."""
        ...

    def load(self, path: Path) -> bool:
        """Load a new image."""
        ...
```

### 2. FullImageHandler

**Purpose:** Uses `textual-imageview` library for full image rendering with iTerm2, Kitty, or Sixel protocols.

**Key Features:**
- Delegates all operations to underlying `TextualImageViewer` widget
- Checks for method availability before calling (graceful handling of API differences)
- Exposes `is_available` property to indicate successful creation

**Implementation:**
```python
class FullImageHandler:
    """Handler for full image viewing using textual-imageview."""

    def __init__(self, path: Path, parent: Widget):
        try:
            self._viewer = TextualImageViewer(path)
        except Exception:
            self._viewer = None

    def zoom_in(self) -> None:
        if self._viewer and hasattr(self._viewer, "zoom_in"):
            self._viewer.zoom_in()

    # ... other methods delegate similarly
```

### 3. FallbackHandler

**Purpose:** Displays file information when images can't be rendered.

**Key Features:**
- Shows helpful messages based on reason (library, terminal, or error)
- Displays image metadata (dimensions, size, format) when available
- All interactive operations (zoom, pan) are no-ops
- Always available (graceful degradation)

**Reasons:**
- `library` - textual-imageview not installed
- `terminal` - Terminal doesn't support image protocols
- `error` - Failed to create full viewer

**Implementation:**
```python
class FallbackHandler:
    """Handler for fallback mode when images can't be displayed."""

    def __init__(self, path: Optional[Path], parent: Widget, reason: str):
        self._reason = reason
        # Load metadata if path provided
        # ...

    def compose(self) -> ComposeResult:
        # Shows different message based on reason
        if self._reason == "library":
            info_lines.append("[yellow]Image preview not available.[/yellow]")
            info_lines.append("[dim]Install for image preview:[/dim]")
            info_lines.append("[cyan]pip install ppxai[tui][/cyan]")
        elif self._reason == "terminal":
            info_lines.append(f"[yellow]Terminal: {protocol}[/yellow]")
            info_lines.append("[dim]Requires iTerm2, Kitty, or WezTerm[/dim]")
        # ...
```

### 4. ImageHandlerFactory

**Purpose:** Creates appropriate handler based on library and terminal capabilities.

**Key Method:**
```python
@staticmethod
def create(path: Optional[Path], parent: Widget) -> ImageHandler:
    """Create appropriate image handler.

    Decision tree:
    1. If textual-imageview not installed → FallbackHandler(reason='library')
    2. If terminal doesn't support images → FallbackHandler(reason='terminal')
    3. If both available → FullImageHandler
    4. If FullImageHandler creation fails → FallbackHandler(reason='error')
    """
    # Check library availability
    if not _IMAGEVIEW_AVAILABLE:
        return FallbackHandler(path, parent, reason="library")

    # Check terminal capabilities
    if not can_display_images():
        return FallbackHandler(path, parent, reason="terminal")

    # Both available - try to create full handler
    if path:
        handler = FullImageHandler(path, parent)
        if not handler.is_available:
            return FallbackHandler(path, parent, reason="error")
        return handler

    return FallbackHandler(None, parent, reason="library")
```

### 5. ImageViewer Widget

**Purpose:** High-level widget that delegates to handlers.

**Key Changes:**
- Uses factory to create handler in `__init__`
- All action methods delegate to handler
- Simplified `compose()` method
- Updated `is_imageview_available()` to check both library AND terminal

**Before (conditional logic embedded):**
```python
def compose(self) -> ComposeResult:
    if _IMAGEVIEW_AVAILABLE and self._path:
        try:
            self._textual_viewer = _ImageViewer(self._path)
            yield self._textual_viewer
        except Exception:
            yield from self._compose_fallback()
    else:
        yield from self._compose_fallback()
```

**After (delegation):**
```python
def __init__(self, path: Optional[Path] = None, id: str = None):
    super().__init__(id=id)
    self._handler: ImageHandler = ImageHandlerFactory.create(path, self)
    # ...

def compose(self) -> ComposeResult:
    # Delegate to handler
    yield from self._handler.compose()
    # ...

def action_zoom_in(self) -> None:
    self._handler.zoom_in()  # Simple delegation
```

## Terminal Capability Detection

**Module:** `ppxai/tui/terminal.py`

The factory uses terminal capability detection to determine if image rendering is possible:

```python
def can_display_images() -> bool:
    """Quick check if terminal can display images."""
    return detect_image_protocol() != ImageProtocol.NONE

def detect_image_protocol() -> ImageProtocol:
    """Detect the best available image display protocol."""
    # iTerm2 and compatible
    if term_program in ("iTerm.app", "WezTerm", "mintty"):
        return ImageProtocol.ITERM2

    # Kitty
    if os.environ.get("KITTY_WINDOW_ID"):
        return ImageProtocol.KITTY

    # Sixel support
    if term_program in {"mlterm", "xterm", "foot", "contour"}:
        return ImageProtocol.SIXEL

    return ImageProtocol.NONE
```

## Benefits of This Architecture

### 1. Separation of Concerns
- **Factory:** Handles capability detection and handler creation
- **Handlers:** Implement specific rendering strategies
- **ImageViewer:** Manages UI layout and delegates operations

### 2. Extensibility
Easy to add new handlers:
- **SixelHandler:** Direct Sixel protocol support
- **AsciiHandler:** ASCII art representation
- **LinkHandler:** Display clickable file link

### 3. Testability
Each component can be tested independently:
- Factory logic (capability detection)
- Handler behavior (delegation, no-ops)
- ImageViewer integration

### 4. Graceful Degradation
Clear fallback path at each decision point:
- Library missing → Helpful install instructions
- Terminal unsupported → Terminal compatibility message
- Viewer creation fails → Error message with file info

### 5. Maintainability
- Handler selection logic isolated in factory
- Changes to detection logic don't affect handlers
- Easy to adjust messages and behavior per reason

## Testing

**Test Suite:** `tests/test_image_handlers.py` (21 tests)

Coverage:
- ✅ Factory creates correct handler based on capabilities
- ✅ Handler interface compliance
- ✅ Delegation works correctly
- ✅ Fallback reasons display appropriate messages
- ✅ Full handler delegates to underlying viewer
- ✅ Graceful handling of missing methods
- ✅ ImageViewer integration

**Total Tests:** 275 (254 original + 21 new)
**Status:** All passing

## Usage Example

```python
from ppxai.tui.widgets import ImageViewer
from pathlib import Path

# Create viewer - automatically selects appropriate handler
viewer = ImageViewer(path=Path("image.png"))

# Check if full mode is available
if ImageViewer.is_imageview_available():
    print("Full image rendering available")
else:
    print("Fallback mode (file info only)")

# All operations work regardless of handler
viewer.action_zoom_in()   # Works in full mode, no-op in fallback
viewer.action_pan_up()    # Works in full mode, no-op in fallback
```

## Implementation Notes

### Dependencies
- **Required:** `ppxai.tui.terminal` for capability detection
- **Optional:** `textual-imageview>=0.1.0` for full image rendering

### Install
```bash
# Full image support
pip install ppxai[tui]

# Base TUI only (fallback mode)
pip install ppxai
```

### Terminal Support
| Terminal | Protocol | Status |
|----------|----------|--------|
| iTerm2 | iTerm2 inline images (OSC 1337) | ✅ Supported |
| Kitty | Kitty graphics protocol | ✅ Supported |
| WezTerm | iTerm2 compatible | ✅ Supported |
| xterm (with Sixel) | Sixel graphics | ✅ Supported |
| GNOME Terminal | None | ⚠️ Fallback mode |
| Windows Terminal | None | ⚠️ Fallback mode |

## Related Documentation

- [TUI Side Panel Refactor](tui-side-panel-refactor.md) - Overall design spec
- [Release Plan v1.15.x](../RELEASE-PLAN-v1.15.x.md) - Development roadmap
- [Terminal Capabilities](../../ppxai/tui/terminal.py) - Detection implementation

## Changelog

**v1.15.0 (January 25, 2026)**
- Initial implementation of factory/delegation pattern
- Separated handler creation from ImageViewer
- Added terminal capability detection to handler selection
- Created comprehensive test suite (21 tests)
- Updated documentation

---

**Author:** Claude Sonnet 4.5 + Human
**Review Status:** Ready for review
