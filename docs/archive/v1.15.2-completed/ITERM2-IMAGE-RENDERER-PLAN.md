# iTerm2 Image Renderer Implementation Plan

## Problem Statement

WezTerm on Windows doesn't work with textual-image library because:
1. textual-image's "TGP" is Kitty Graphics Protocol (with placeholders), not iTerm2
2. WezTerm uses iTerm2 inline images protocol
3. Sixel queries fail on WezTerm (doesn't respond to DA1 query)

Meanwhile, Windows Terminal works because it responds to Sixel terminal queries.

## Goal

Implement native iTerm2 inline image protocol support for ppxaide that works with WezTerm.

## iTerm2 Protocol Specification

```
ESC ] 1337 ; File = [arguments] : <base64-data> BEL
```

Arguments (semicolon-separated):
- `inline=1` - display inline (required for display)
- `width=auto|N|Npx|N%` - display width
- `height=auto|N|Npx|N%` - display height
- `preserveAspectRatio=1` - maintain aspect ratio
- `size=N` - file size in bytes (optional, for progress)
- `name=<base64>` - filename (optional)

Example:
```python
ESC = '\x1b'
BEL = '\x07'
f"{ESC}]1337;File=inline=1;width=auto:{base64_data}{BEL}"
```

## Architecture

### Components to Create

```
ppxai/tui/
├── renderable/
│   ├── __init__.py
│   └── iterm2.py          # iTerm2 Rich Renderable
└── widgets/
    └── image_handlers.py  # Update to use iTerm2Renderable
```

### 1. iTerm2 Rich Renderable (`ppxai/tui/renderable/iterm2.py`)

```python
"""iTerm2 inline image protocol Rich Renderable."""

import base64
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console, ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.style import Style

if TYPE_CHECKING:
    from PIL import Image as PILImage


class ITerm2Image:
    """Rich Renderable that outputs iTerm2 inline image escape sequences.

    Works with terminals that support iTerm2 protocol:
    - iTerm2 (macOS)
    - WezTerm (cross-platform)
    - mintty (Windows)
    """

    ESC = '\x1b'
    BEL = '\x07'

    def __init__(
        self,
        image: "Path | bytes | PILImage",
        width: str = "auto",
        height: str = "auto",
        preserve_aspect_ratio: bool = True,
    ):
        """Initialize iTerm2 image.

        Args:
            image: Path to image file, raw bytes, or PIL Image
            width: Width spec (auto, N cells, Npx, N%)
            height: Height spec (auto, N cells, Npx, N%)
            preserve_aspect_ratio: Whether to preserve aspect ratio
        """
        self._width = width
        self._height = height
        self._preserve_aspect = preserve_aspect_ratio

        # Load image data
        if isinstance(image, Path):
            self._data = image.read_bytes()
            self._name = image.name
        elif isinstance(image, bytes):
            self._data = image
            self._name = "image"
        else:
            # PIL Image - convert to PNG bytes
            import io
            buf = io.BytesIO()
            image.save(buf, format='PNG')
            self._data = buf.getvalue()
            self._name = "image.png"

    def _build_escape_sequence(self) -> str:
        """Build the iTerm2 escape sequence."""
        b64_data = base64.b64encode(self._data).decode('ascii')
        b64_name = base64.b64encode(self._name.encode()).decode('ascii')

        args = [
            f"name={b64_name}",
            f"size={len(self._data)}",
            f"width={self._width}",
            f"height={self._height}",
            f"preserveAspectRatio={'1' if self._preserve_aspect else '0'}",
            "inline=1",
        ]

        return f"{self.ESC}]1337;File={';'.join(args)}:{b64_data}{self.BEL}"

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        """Render the image using iTerm2 protocol."""
        escape_seq = self._build_escape_sequence()

        # Output the escape sequence as a control segment
        # Rich will pass this through to the terminal
        yield Segment(escape_seq, Style(), control=True)

        # Add newline after image
        yield Segment("\n")
```

### 2. Textual Widget Wrapper

```python
"""iTerm2 Image Textual Widget."""

from pathlib import Path
from typing import Union

from rich.console import RenderableType
from textual.widget import Widget

from .iterm2 import ITerm2Image


class ITerm2ImageWidget(Widget):
    """Textual widget for iTerm2 inline images."""

    def __init__(
        self,
        image: Union[Path, bytes],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self._image_path = image
        self._renderable: ITerm2Image | None = None

    def on_mount(self) -> None:
        """Create renderable on mount."""
        # Calculate size based on widget dimensions
        width = self.size.width
        height = self.size.height

        self._renderable = ITerm2Image(
            self._image_path,
            width=f"{width}",  # cells
            height=f"{height}",
        )

    def render(self) -> RenderableType:
        """Render the image."""
        if self._renderable:
            return self._renderable
        return ""

    @property
    def image(self) -> Path | bytes:
        """Get current image."""
        return self._image_path

    @image.setter
    def image(self, value: Path | bytes) -> None:
        """Set new image."""
        self._image_path = value
        self._renderable = None
        self.on_mount()  # Recreate renderable
        self.refresh()
```

### 3. Update Image Handler Factory

```python
# In image_handlers.py

def _get_image_widget_class():
    """Get the best image widget class for the current terminal."""
    import os

    term_program = os.environ.get("TERM_PROGRAM", "").lower()

    # WezTerm, iTerm2, mintty: Use our native iTerm2 implementation
    if term_program in ("wezterm", "iterm.app", "mintty"):
        from ppxai.tui.widgets.iterm2_widget import ITerm2ImageWidget
        return ITerm2ImageWidget

    # Kitty: Use TGP
    if os.environ.get("KITTY_WINDOW_ID"):
        if _TGPImage is not None:
            return _TGPImage

    # Others: auto-detection (Sixel on Windows Terminal, etc.)
    return _TextualImage
```

## Implementation Steps

### Phase 1: Core Renderable (1-2 hours)
1. Create `ppxai/tui/renderable/` directory
2. Implement `ITerm2Image` Rich Renderable
3. Test with simple script outside Textual

### Phase 2: Textual Integration (1-2 hours)
4. Create `ITerm2ImageWidget` Textual Widget
5. Handle sizing based on widget dimensions
6. Test within Textual app

### Phase 3: Handler Integration (30 min)
7. Update `_get_image_widget_class()` to use ITerm2ImageWidget
8. Ensure fallback to textual-image for other terminals

### Phase 4: Testing (1 hour)
9. Test in WezTerm (Windows)
10. Test in Windows Terminal (should still use Sixel)
11. Test in plain terminal (should fallback gracefully)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Escape sequence buffering by Textual | Image not displayed | Use `control=True` segment |
| Size calculation incorrect | Image too big/small | Use terminal cell size query |
| Image flicker on refresh | Poor UX | Cache rendered escape sequence |
| Large images slow | Performance | Implement lazy loading / thumbnail |

## Testing Commands

```bash
# Test in WezTerm
cd c:/git/utils/ppxai
.uv/uv run python -c "
from ppxai.tui.renderable.iterm2 import ITerm2Image
from rich.console import Console
from pathlib import Path

console = Console()
img = ITerm2Image(Path('docs/future-agentic-flow.png'))
console.print(img)
"
```

## Success Criteria

1. `wezterm imgcat image.png` quality matches ppxaide `/show image.png`
2. No corruption or artifacts
3. Proper sizing within side panel
4. Falls back gracefully on unsupported terminals

## References

- [iTerm2 Inline Images Protocol](https://iterm2.com/documentation-images.html)
- [WezTerm iTerm Image Protocol](https://wezterm.org/imgcat.html)
- [Rich Console Protocol](https://rich.readthedocs.io/en/latest/protocol.html)
- [python-imgcat implementation](https://github.com/wookayin/python-imgcat)
