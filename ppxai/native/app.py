"""
NativeApp — main application class for ppxai-native.

Owns the Raylib window, engine integration, and main loop.
Phase 1: Window + input + static message display (no engine yet).
"""

import os
from pathlib import Path
from typing import List, Tuple

import pyray as rl

from ppxai.native import theme
from ppxai.native.layout import calculate_layout
from ppxai.native.renderer import (
    draw_status_bar,
    draw_chat_area,
    draw_input_area,
    draw_scrollbar,
)
from ppxai.native.input_handler import (
    handle_input,
    InsertChar,
    DeleteBack,
    DeleteForward,
    SubmitMessage,
    NewLine,
    Scroll,
    CursorLeft,
    CursorRight,
    CursorHome,
    CursorEnd,
    Cancel,
)


class NativeApp:
    """ppxai native desktop application."""

    def __init__(self) -> None:
        # Chat state
        self.messages: List[Tuple[str, str]] = []  # (role, content)
        self.streaming_text: str = ""
        self.is_streaming: bool = False

        # Input state
        self.input_text: str = ""
        self.cursor_pos: int = 0

        # Scroll state
        self.scroll_offset: float = 0.0
        self.content_height: float = 0.0
        self.auto_scroll: bool = True

        # Provider/model (static for Phase 1)
        self.provider: str = "none"
        self.model: str = "none"

        # Fonts (loaded in run())
        self._font: rl.Font = rl.Font()
        self._font_bold: rl.Font = rl.Font()

    def run(self) -> None:
        """Main application loop."""
        rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_RESIZABLE)
        rl.init_window(theme.DEFAULT_WIDTH, theme.DEFAULT_HEIGHT, b"ppxai-native")
        rl.set_target_fps(theme.TARGET_FPS)
        rl.set_exit_key(rl.KeyboardKey.KEY_NULL)  # Don't exit on Escape

        # Load fonts
        assets_dir = Path(__file__).parent / "assets"
        font_path = str(assets_dir / "JetBrainsMono-Regular.ttf").encode("utf-8")
        font_bold_path = str(assets_dir / "JetBrainsMono-Bold.ttf").encode("utf-8")
        self._font = rl.load_font_ex(font_path, 32, None, 0)
        self._font_bold = rl.load_font_ex(font_bold_path, 32, None, 0)

        # Enable texture filtering for smoother text
        rl.set_texture_filter(self._font.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
        rl.set_texture_filter(self._font_bold.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)

        # Welcome message
        self.messages.append(("system", "Welcome to ppxai-native. Type a message and press Ctrl+Enter to send."))

        while not rl.window_should_close():
            self._handle_input()
            self._draw()

        rl.unload_font(self._font)
        rl.unload_font(self._font_bold)
        rl.close_window()

    def _handle_input(self) -> None:
        """Process input actions."""
        for action in handle_input():
            if isinstance(action, InsertChar):
                self.input_text = (
                    self.input_text[:self.cursor_pos]
                    + action.char
                    + self.input_text[self.cursor_pos:]
                )
                self.cursor_pos += len(action.char)

            elif isinstance(action, NewLine):
                self.input_text = (
                    self.input_text[:self.cursor_pos]
                    + "\n"
                    + self.input_text[self.cursor_pos:]
                )
                self.cursor_pos += 1

            elif isinstance(action, DeleteBack):
                if self.cursor_pos > 0:
                    self.input_text = (
                        self.input_text[:self.cursor_pos - 1]
                        + self.input_text[self.cursor_pos:]
                    )
                    self.cursor_pos -= 1

            elif isinstance(action, DeleteForward):
                if self.cursor_pos < len(self.input_text):
                    self.input_text = (
                        self.input_text[:self.cursor_pos]
                        + self.input_text[self.cursor_pos + 1:]
                    )

            elif isinstance(action, SubmitMessage):
                text = self.input_text.strip()
                if text:
                    self.messages.append(("user", text))
                    self.input_text = ""
                    self.cursor_pos = 0
                    self.auto_scroll = True
                    # Phase 2: submit to engine here

            elif isinstance(action, CursorLeft):
                self.cursor_pos = max(0, self.cursor_pos - 1)

            elif isinstance(action, CursorRight):
                self.cursor_pos = min(len(self.input_text), self.cursor_pos + 1)

            elif isinstance(action, CursorHome):
                self.cursor_pos = 0

            elif isinstance(action, CursorEnd):
                self.cursor_pos = len(self.input_text)

            elif isinstance(action, Scroll):
                self.auto_scroll = False
                self.scroll_offset = max(0, self.scroll_offset + action.pixels)

            elif isinstance(action, Cancel):
                if self.is_streaming:
                    self.is_streaming = False
                    # Phase 2: cancel engine stream

    def _draw(self) -> None:
        """Render one frame."""
        screen_w = rl.get_screen_width()
        screen_h = rl.get_screen_height()
        input_lines = self.input_text.count("\n") + 1

        layout = calculate_layout(screen_w, screen_h, input_lines)

        # Auto-scroll to bottom
        if self.auto_scroll and self.content_height > layout.chat_area.h:
            self.scroll_offset = self.content_height - layout.chat_area.h

        # Clamp scroll
        max_scroll = max(0, self.content_height - layout.chat_area.h)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        rl.begin_drawing()
        rl.clear_background(theme.BG)

        draw_status_bar(self._font, layout, self.provider, self.model)
        self.content_height = draw_chat_area(
            self._font, self._font_bold, layout,
            self.messages, self.streaming_text, self.scroll_offset,
        )
        draw_scrollbar(layout, self.scroll_offset, self.content_height)
        draw_input_area(self._font, layout, self.input_text, self.cursor_pos, self.is_streaming)

        rl.end_drawing()
