"""
NativeApp — main application class for ppxai-native.

Owns the Raylib window, engine integration, and main loop.

Thread model (same as ppxaide app.py:919-936):
- Main thread: Raylib draw loop (sync, 60fps), drains event queue
- Engine thread: asyncio loop, runs EngineClient.chat() async generator
- Communication: queue.Queue for events, threading.Event for consent
"""

import asyncio
import os
import queue
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import pyray as rl

from ppxai.config import get_default_model, get_default_provider, initialize
from ppxai.engine import EngineClient
from ppxai.engine.types import EventType
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
        self._cancel_requested: bool = False

        # Input state
        self.input_text: str = ""
        self.cursor_pos: int = 0

        # Scroll state
        self.scroll_offset: float = 0.0
        self.content_height: float = 0.0
        self.auto_scroll: bool = True

        # Engine
        self._engine: Optional[EngineClient] = None
        self.provider: str = ""
        self.model: str = ""
        self.status_text: str = ""

        # Thread communication
        self._event_queue: queue.Queue = queue.Queue()

        # Consent bridge
        self._consent_pending: Optional[dict] = None
        self._consent_result: Optional[Tuple[bool, str]] = None
        self._consent_event: threading.Event = threading.Event()

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
        rl.set_texture_filter(self._font.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
        rl.set_texture_filter(self._font_bold.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)

        # Initialize engine
        self._initialize_engine()

        while not rl.window_should_close():
            self._handle_input()
            self._process_events()
            self._draw()

        rl.unload_font(self._font)
        rl.unload_font(self._font_bold)
        rl.close_window()

    # =========================================================================
    # Engine initialization (mirrors ppxaide app.py:280-346)
    # =========================================================================

    def _initialize_engine(self) -> None:
        """Initialize EngineClient with provider/model from config."""
        initialize()

        self.provider = get_default_provider()
        self.model = get_default_model(self.provider)

        self._engine = EngineClient(
            consent_callback=self._consent_file_handler,
            shell_consent_callback=self._consent_shell_handler,
        )

        try:
            self._engine.set_provider(self.provider)
            self._engine.set_model(self.model, reset_context=False)
        except Exception as e:
            self.messages.append(("system", f"Engine init error: {e}"))
            self.provider = "error"
            self.model = str(e)[:40]
            return

        self._engine.set_working_dir(os.getcwd())
        self.messages.append(("system",
            f"Connected to {self.provider}/{self.model}. "
            "Type a message and press Ctrl+Enter to send."))

    # =========================================================================
    # Consent callbacks (called from engine thread, block until main thread responds)
    # =========================================================================

    async def _consent_file_handler(self, file_path: str) -> Tuple[bool, str]:
        """File edit consent — blocks engine thread, renders dialog in main thread."""
        self._consent_pending = {"type": "file", "path": file_path}
        self._consent_event.clear()
        self._consent_event.wait(timeout=300)
        result = self._consent_result or (False, "n")
        self._consent_pending = None
        self._consent_result = None
        return result

    async def _consent_shell_handler(self, command: str, working_dir: str = ".") -> Tuple[bool, str]:
        """Shell command consent — blocks engine thread, renders dialog in main thread."""
        self._consent_pending = {"type": "shell", "command": command, "cwd": working_dir}
        self._consent_event.clear()
        self._consent_event.wait(timeout=300)
        result = self._consent_result or (False, "n")
        self._consent_pending = None
        self._consent_result = None
        return result

    # =========================================================================
    # Engine thread (mirrors ppxaide app.py:919-1045)
    # =========================================================================

    def _submit_to_engine(self, text: str) -> None:
        """Submit a message to the engine in a background thread."""
        if self._engine is None or self.is_streaming:
            return

        self.is_streaming = True
        self._cancel_requested = False
        self.streaming_text = ""
        self.status_text = "thinking..."

        thread = threading.Thread(
            target=self._engine_thread,
            args=(text,),
            daemon=True,
        )
        thread.start()

    def _engine_thread(self, message: str) -> None:
        """Worker thread: run async engine chat in its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._stream_response(message))
        except Exception as e:
            self._event_queue.put(("ERROR", str(e)))
        finally:
            self._event_queue.put(("DONE", None))
            loop.close()

    async def _stream_response(self, message: str) -> None:
        """Stream AI response, pushing events to the queue."""
        async for event in self._engine.chat(message, stream=True):
            if self._cancel_requested:
                self._event_queue.put(("CANCELLED", None))
                return
            self._event_queue.put((event.type.name, event.data))

    # =========================================================================
    # Event processing (main thread, called each frame)
    # =========================================================================

    def _process_events(self) -> None:
        """Drain the event queue and update state."""
        while not self._event_queue.empty():
            try:
                event_type, event_data = self._event_queue.get_nowait()
            except queue.Empty:
                break

            if event_type == "DONE":
                if self.streaming_text:
                    self.messages.append(("assistant", self.streaming_text))
                    self.streaming_text = ""
                self.is_streaming = False
                self._cancel_requested = False
                self.status_text = ""
                self.auto_scroll = True

            elif event_type == "CANCELLED":
                self.messages.append(("system", "Stream cancelled"))
                self.streaming_text = ""
                self.is_streaming = False
                self._cancel_requested = False
                self.status_text = ""

            elif event_type == "ERROR":
                self.messages.append(("system", f"Error: {event_data}"))
                self.streaming_text = ""
                self.is_streaming = False
                self.status_text = ""

            elif event_type == EventType.STREAM_CHUNK.name:
                self.streaming_text += event_data or ""
                self.auto_scroll = True

            elif event_type == EventType.STREAM_END.name:
                # Usage stats in event_data (dict with tokens, cost, etc.)
                if isinstance(event_data, dict):
                    tokens = event_data.get("total_tokens", 0)
                    if tokens:
                        self.status_text = f"{tokens} tokens"

            elif event_type == EventType.TOOL_CALL.name:
                if isinstance(event_data, dict):
                    tool_name = event_data.get("name", "unknown")
                    self.messages.append(("tool", f"Calling: {tool_name}"))
                    self.status_text = f"tool: {tool_name}"

            elif event_type == EventType.TOOL_RESULT.name:
                if isinstance(event_data, dict):
                    result = event_data.get("result", "")
                    # Truncate long tool results
                    if len(result) > 500:
                        result = result[:500] + "..."
                    self.messages.append(("tool", result))
                elif isinstance(event_data, str):
                    result = event_data[:500] + "..." if len(event_data) > 500 else event_data
                    self.messages.append(("tool", result))

            elif event_type == EventType.TOOL_ERROR.name:
                self.messages.append(("system", f"Tool error: {event_data}"))

            elif event_type == EventType.REASONING_CHUNK.name:
                # Show reasoning in streaming text with dimmed prefix
                pass  # Phase 3: render reasoning separately

            elif event_type == EventType.ERROR.name:
                self.messages.append(("system", f"Error: {event_data}"))

        # Handle consent dialog input
        if self._consent_pending:
            self._handle_consent_input()

    def _handle_consent_input(self) -> None:
        """Check for Y/N input when consent dialog is showing."""
        if rl.is_key_pressed(rl.KeyboardKey.KEY_Y):
            self._consent_result = (True, "y")
            self._consent_event.set()
        elif rl.is_key_pressed(rl.KeyboardKey.KEY_N) or rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
            self._consent_result = (False, "n")
            self._consent_event.set()
        elif rl.is_key_pressed(rl.KeyboardKey.KEY_A):
            self._consent_result = (True, "always")
            self._consent_event.set()

    # =========================================================================
    # Input handling
    # =========================================================================

    def _handle_input(self) -> None:
        """Process input actions."""
        # Skip normal input when consent dialog is showing
        if self._consent_pending:
            return

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
                if text and not self.is_streaming:
                    self.messages.append(("user", text))
                    self.input_text = ""
                    self.cursor_pos = 0
                    self.auto_scroll = True
                    self._submit_to_engine(text)

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
                    self._cancel_requested = True

    # =========================================================================
    # Drawing
    # =========================================================================

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

        draw_status_bar(self._font, layout, self.provider, self.model, self.status_text)
        self.content_height = draw_chat_area(
            self._font, self._font_bold, layout,
            self.messages, self.streaming_text, self.scroll_offset,
        )
        draw_scrollbar(layout, self.scroll_offset, self.content_height)
        draw_input_area(self._font, layout, self.input_text, self.cursor_pos, self.is_streaming)

        # Consent dialog overlay
        if self._consent_pending:
            self._draw_consent_overlay(screen_w, screen_h)

        rl.end_drawing()

    def _draw_consent_overlay(self, screen_w: int, screen_h: int) -> None:
        """Draw consent dialog as modal overlay."""
        # Semi-transparent background
        rl.draw_rectangle(0, 0, screen_w, screen_h, rl.Color(0, 0, 0, 160))

        # Dialog box
        dialog_w = min(600, screen_w - 40)
        dialog_h = 160
        dialog_x = (screen_w - dialog_w) // 2
        dialog_y = (screen_h - dialog_h) // 2

        rl.draw_rectangle_rounded(
            rl.Rectangle(dialog_x, dialog_y, dialog_w, dialog_h),
            0.02, 4, theme.INPUT_BG
        )
        rl.draw_rectangle_rounded_lines_ex(
            rl.Rectangle(dialog_x, dialog_y, dialog_w, dialog_h),
            0.02, 4, 1.0, theme.ACCENT
        )

        # Title
        consent = self._consent_pending
        if consent["type"] == "file":
            title = "File Edit Consent"
            detail = consent.get("path", "unknown file")
        else:
            title = "Shell Command Consent"
            detail = consent.get("command", "unknown command")

        y = dialog_y + theme.PADDING
        rl.draw_text_ex(self._font, title.encode("utf-8"),
                        rl.Vector2(dialog_x + theme.PADDING, y),
                        theme.FONT_SIZE, 1, theme.ACCENT)

        y += theme.LINE_HEIGHT + 4
        # Truncate detail if too long
        if len(detail) > 60:
            detail = detail[:57] + "..."
        rl.draw_text_ex(self._font, detail.encode("utf-8"),
                        rl.Vector2(dialog_x + theme.PADDING, y),
                        theme.FONT_SIZE, 1, theme.TEXT)

        y += theme.LINE_HEIGHT + 12
        rl.draw_text_ex(self._font, b"[Y] Allow  [N] Deny  [A] Always allow  [Esc] Deny",
                        rl.Vector2(dialog_x + theme.PADDING, y),
                        theme.FONT_SIZE_SMALL, 1, theme.TEXT_DIM)
