"""
NativeApp — PTY + pyte terminal emulator for ppxai-native.

Spawns ppxai Rich TUI inside a PTY, uses pyte to parse VT output
into a screen buffer, and renders the cell grid with Raylib.
Full Rich formatting (markdown tables, syntax highlighting, panels)
works unchanged.

Thread model:
- Main thread: Raylib draw loop (sync, 60fps)
  - Reads PTY output (non-blocking)
  - Feeds VT data to pyte Stream → Screen
  - Draws cell grid from Screen.buffer
  - Encodes keyboard input via ghostty → writes to PTY
- Child process: ppxai Rich TUI (separate process via pty.fork())

Keyboard encoding uses libghostty-vt key encoder for correct escape sequences.
Screen buffer uses pyte (pure Python VT100 emulator) for cell-level access.

macOS/Linux only. Windows lacks pty.fork() — use the chat UI fallback.
"""

import codecs
import ctypes
import platform
import sys
from pathlib import Path
from typing import Optional

import pyte
import pyray as rl

from ppxai.native import theme
from ppxai.native.cell_renderer import draw_cursor, draw_screen
from ppxai.native.pty_io import (
    close_master,
    is_child_alive,
    kill_child,
    pty_read,
    pty_resize,
    pty_write,
    spawn_ppxai,
)
from ppxai.terminal import ghostty


# Raylib key code → (ghostty_key, utf8_bytes, ghostty_mods)
# Maps Raylib KEY_* constants to ghostty key encoder inputs.
# Writing system keys (a-z, 0-9, symbols) go through get_char_pressed() instead.
_RAYLIB_KEY_MAP = {
    rl.KeyboardKey.KEY_ENTER: (ghostty.GHOSTTY_KEY_ENTER, b"\r", 0),
    rl.KeyboardKey.KEY_KP_ENTER: (ghostty.GHOSTTY_KEY_ENTER, b"\r", 0),
    rl.KeyboardKey.KEY_TAB: (ghostty.GHOSTTY_KEY_TAB, b"\t", 0),
    rl.KeyboardKey.KEY_BACKSPACE: (ghostty.GHOSTTY_KEY_BACKSPACE, b"\x7f", 0),
    rl.KeyboardKey.KEY_DELETE: (ghostty.GHOSTTY_KEY_DELETE, None, 0),
    rl.KeyboardKey.KEY_ESCAPE: (ghostty.GHOSTTY_KEY_ESCAPE, b"\x1b", 0),
    rl.KeyboardKey.KEY_UP: (ghostty.GHOSTTY_KEY_ARROW_UP, None, 0),
    rl.KeyboardKey.KEY_DOWN: (ghostty.GHOSTTY_KEY_ARROW_DOWN, None, 0),
    rl.KeyboardKey.KEY_LEFT: (ghostty.GHOSTTY_KEY_ARROW_LEFT, None, 0),
    rl.KeyboardKey.KEY_RIGHT: (ghostty.GHOSTTY_KEY_ARROW_RIGHT, None, 0),
    rl.KeyboardKey.KEY_HOME: (ghostty.GHOSTTY_KEY_HOME, None, 0),
    rl.KeyboardKey.KEY_END: (ghostty.GHOSTTY_KEY_END, None, 0),
    rl.KeyboardKey.KEY_PAGE_UP: (ghostty.GHOSTTY_KEY_PAGE_UP, None, 0),
    rl.KeyboardKey.KEY_PAGE_DOWN: (ghostty.GHOSTTY_KEY_PAGE_DOWN, None, 0),
    rl.KeyboardKey.KEY_INSERT: (ghostty.GHOSTTY_KEY_INSERT, None, 0),
    rl.KeyboardKey.KEY_SPACE: (ghostty.GHOSTTY_KEY_SPACE, b" ", 0),
    rl.KeyboardKey.KEY_F1: (ghostty.GHOSTTY_KEY_F1, None, 0),
}

# Raylib KEY_A..KEY_Z → ghostty key codes (writing system keys start at 4 in ghostty)
# Only used for ctrl+key combinations; normal typing uses get_char_pressed()
_GHOSTTY_KEY_A = 4
_KEY_A = rl.KeyboardKey.KEY_A


def _build_codepoints() -> list:
    """Build Unicode codepoint list for font loading.

    Focused on characters Rich TUI actually uses: ASCII, Latin,
    box-drawing, block elements, and common symbols. Kept small
    to ensure all glyphs fit comfortably in the font atlas.
    """
    cps = []
    cps.extend(range(0x0020, 0x007F))  # Basic ASCII (95)
    cps.extend(range(0x00A0, 0x0100))  # Latin-1 Supplement (96)
    cps.extend(range(0x2010, 0x2030))  # General Punctuation: dashes, bullets (32)
    cps.extend(range(0x2190, 0x21A0))  # Arrows: basic 16
    cps.extend(range(0x2500, 0x2580))  # Box Drawing (128)
    cps.extend(range(0x2580, 0x25A0))  # Block Elements (32)
    # Specific symbols Rich uses
    cps.extend([
        0x25A0, 0x25A1,  # Black/white square
        0x25B2, 0x25B6, 0x25BC, 0x25C0,  # Triangles
        0x25CB, 0x25CF,  # Circles
        0x2713, 0x2714, 0x2717, 0x2718,  # Check marks, crosses
        0x26A0,  # Warning sign
        0x2022,  # Bullet
    ])
    return cps


class NativeApp:
    """ppxai native desktop application — terminal emulator mode."""

    def __init__(self) -> None:
        # PTY state
        self._child_pid: int = 0
        self._master_fd: int = -1

        # pyte screen buffer + VT stream parser
        self._screen: Optional[pyte.HistoryScreen] = None
        self._stream: Optional[pyte.Stream] = None
        # Incremental UTF-8 decoder — buffers partial multi-byte sequences
        # across pty_read() calls so box-drawing chars (3-byte UTF-8) don't
        # get split and replaced with U+FFFD
        self._utf8_decoder = codecs.getincrementaldecoder("utf-8")("replace")

        # Cell grid dimensions
        self._cols: int = 0
        self._rows: int = 0
        self._cell_w: float = 0.0
        self._cell_h: float = 0.0

        # Fonts
        self._font: rl.Font = rl.Font()
        self._font_bold: rl.Font = rl.Font()

        # Window tracking for resize detection
        self._last_screen_w: int = 0
        self._last_screen_h: int = 0

    def run(self) -> None:
        """Main application loop."""
        if platform.system() == "Windows":
            print("ppxai-native terminal emulator requires macOS or Linux.")
            print("On Windows, use ppxai-native with the chat UI (Phase 1-6).")
            sys.exit(1)

        if not ghostty.is_available():
            print(f"libghostty-vt not found: {ghostty.get_load_error()}")
            print("ppxai-native requires libghostty-vt for keyboard encoding.")
            sys.exit(1)

        # Initialize Raylib window
        rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_RESIZABLE)
        rl.init_window(theme.DEFAULT_WIDTH, theme.DEFAULT_HEIGHT, b"ppxai-native")
        rl.set_target_fps(theme.TARGET_FPS)
        rl.set_exit_key(rl.KeyboardKey.KEY_NULL)  # Don't exit on Escape

        # Load monospace fonts with Unicode codepoints for box-drawing etc.
        assets_dir = Path(__file__).parent / "assets"
        font_path = str(assets_dir / "JetBrainsMono-Regular.ttf").encode("utf-8")
        font_bold_path = str(assets_dir / "JetBrainsMono-Bold.ttf").encode("utf-8")
        codepoints = _build_codepoints()
        cp_arr = rl.ffi.new("int[]", codepoints)
        cp_ptr = rl.ffi.cast("int *", cp_arr)
        # Rasterize at 48px to avoid "size is bigger than expected" clipping
        # for box-drawing/block element glyphs that extend beyond the em square
        self._font = rl.load_font_ex(font_path, 48, cp_ptr, len(codepoints))
        self._font_bold = rl.load_font_ex(font_bold_path, 48, cp_ptr, len(codepoints))
        rl.set_texture_filter(self._font.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
        rl.set_texture_filter(self._font_bold.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)

        # Calculate cell dimensions from font metrics
        m_size = rl.measure_text_ex(self._font, b"M", theme.FONT_SIZE_TERMINAL, 0)
        self._cell_w = m_size.x
        self._cell_h = m_size.y + 2  # Small vertical padding between rows

        # Calculate grid dimensions
        screen_w = rl.get_screen_width()
        screen_h = rl.get_screen_height()
        self._cols, self._rows = self._calculate_grid(screen_w, screen_h)
        self._last_screen_w = screen_w
        self._last_screen_h = screen_h

        # Create pyte screen buffer + VT stream parser
        self._screen = pyte.HistoryScreen(self._cols, self._rows, history=10000)
        self._screen.set_mode(pyte.modes.LNM)  # Line feed mode
        self._stream = pyte.Stream(self._screen)

        # Spawn ppxai Rich TUI in PTY
        self._child_pid, self._master_fd = spawn_ppxai(self._cols, self._rows)

        # Main loop
        try:
            while not rl.window_should_close():
                # Check if child is still alive
                if not is_child_alive(self._child_pid):
                    break

                # Handle window resize
                self._handle_resize()

                # Read PTY output and feed to pyte
                self._read_pty()

                # Handle keyboard input → encode → write to PTY
                self._handle_keyboard()

                # Handle mouse (scroll)
                self._handle_mouse()

                # Draw
                self._draw()
        finally:
            self._cleanup()

    def _calculate_grid(self, screen_w: int, screen_h: int) -> tuple:
        """Calculate terminal grid dimensions (cols, rows) from screen size."""
        pad = theme.CELL_PADDING
        usable_w = screen_w - 2 * pad
        usable_h = screen_h - 2 * pad
        cols = max(20, int(usable_w / self._cell_w))
        rows = max(5, int(usable_h / self._cell_h))
        return cols, rows

    def _handle_resize(self) -> None:
        """Detect window resize and update pyte screen + PTY dimensions."""
        if not rl.is_window_resized():
            return

        screen_w = rl.get_screen_width()
        screen_h = rl.get_screen_height()

        if screen_w == self._last_screen_w and screen_h == self._last_screen_h:
            return

        self._last_screen_w = screen_w
        self._last_screen_h = screen_h

        new_cols, new_rows = self._calculate_grid(screen_w, screen_h)
        if new_cols == self._cols and new_rows == self._rows:
            return

        self._cols = new_cols
        self._rows = new_rows

        # Resize pyte screen
        self._screen.resize(self._rows, self._cols)

        # Resize PTY (sends SIGWINCH to child)
        pty_resize(self._master_fd, self._cols, self._rows)

    def _read_pty(self) -> None:
        """Read available data from PTY and feed to pyte stream."""
        data = pty_read(self._master_fd)
        if not data:
            return

        # Handle CPR (Cursor Position Report) requests from Rich
        # Rich sends ESC[6n to query cursor position; we must respond
        if b"\x1b[6n" in data:
            row = self._screen.cursor.y + 1
            col = self._screen.cursor.x + 1
            response = f"\x1b[{row};{col}R".encode("ascii")
            pty_write(self._master_fd, response)

        # Incremental decode: buffers partial multi-byte UTF-8 sequences
        # (e.g., box-drawing ╇ = 3 bytes that may split across reads)
        text = self._utf8_decoder.decode(data)
        if text:
            self._stream.feed(text)

    def _handle_keyboard(self) -> None:
        """Process keyboard input: encode via ghostty and write to PTY."""
        lib = ghostty._load_lib()
        if lib is None:
            return

        encoder = ghostty._get_encoder()
        event = ghostty._get_event()
        if encoder is None or event is None:
            return

        ctrl = (
            rl.is_key_down(rl.KeyboardKey.KEY_LEFT_CONTROL)
            or rl.is_key_down(rl.KeyboardKey.KEY_RIGHT_CONTROL)
        )
        shift = (
            rl.is_key_down(rl.KeyboardKey.KEY_LEFT_SHIFT)
            or rl.is_key_down(rl.KeyboardKey.KEY_RIGHT_SHIFT)
        )
        alt = (
            rl.is_key_down(rl.KeyboardKey.KEY_LEFT_ALT)
            or rl.is_key_down(rl.KeyboardKey.KEY_RIGHT_ALT)
        )

        mods = 0
        if ctrl:
            mods |= ghostty.GHOSTTY_MODS_CTRL
        if shift:
            mods |= ghostty.GHOSTTY_MODS_SHIFT
        if alt:
            mods |= ghostty.GHOSTTY_MODS_ALT

        # Handle special keys (Enter, Tab, arrows, etc.)
        for rl_key, (gk, utf8, base_mods) in _RAYLIB_KEY_MAP.items():
            if rl.is_key_pressed(rl_key) or rl.is_key_pressed_repeat(rl_key):
                combined_mods = mods | base_mods
                seq = self._encode_ghostty_key(
                    lib, encoder, event, gk, utf8, combined_mods,
                )
                if seq:
                    pty_write(self._master_fd, seq)

        # Handle Ctrl+letter combinations (Ctrl+C, Ctrl+D, Ctrl+Z, etc.)
        if ctrl:
            for offset in range(26):  # A..Z
                rl_letter = _KEY_A + offset
                if rl.is_key_pressed(rl_letter):
                    gk = _GHOSTTY_KEY_A + offset
                    seq = self._encode_ghostty_key(
                        lib, encoder, event, gk, None, mods,
                    )
                    if seq:
                        pty_write(self._master_fd, seq)

        # Handle regular character input (typing)
        # Only process if no ctrl modifier (ctrl combos handled above)
        if not ctrl:
            while True:
                ch = rl.get_char_pressed()
                if ch == 0:
                    break
                # Send UTF-8 encoded character directly to PTY
                char_bytes = chr(ch).encode("utf-8")
                pty_write(self._master_fd, char_bytes)

    def _encode_ghostty_key(
        self, lib, encoder, event,
        ghostty_key: int, utf8: Optional[bytes], mods: int,
    ) -> Optional[bytes]:
        """Encode a single key event through ghostty key encoder."""
        lib.ghostty_key_event_set_action(event, ghostty.GHOSTTY_KEY_ACTION_PRESS)
        lib.ghostty_key_event_set_key(event, ghostty_key)
        lib.ghostty_key_event_set_mods(event, mods)
        if utf8 is not None:
            lib.ghostty_key_event_set_utf8(event, utf8, len(utf8))

        out_buf = ctypes.create_string_buffer(128)
        out_len = ctypes.c_size_t(0)
        result = lib.ghostty_key_encoder_encode(
            encoder, event, out_buf, 128, ctypes.byref(out_len),
        )
        if result != ghostty.GHOSTTY_SUCCESS or out_len.value == 0:
            return None
        return out_buf.raw[:out_len.value]

    def _handle_mouse(self) -> None:
        """Handle mouse wheel — scroll pyte's HistoryScreen scrollback."""
        wheel = rl.get_mouse_wheel_move()
        if wheel == 0:
            return
        if wheel > 0:
            self._screen.prev_page()
        else:
            self._screen.next_page()

    def _draw(self) -> None:
        """Render one frame: draw cell grid from pyte screen buffer."""
        rl.begin_drawing()

        # Clear with background color
        rl.clear_background(theme.BG)

        # Draw cell grid
        pad = theme.CELL_PADDING
        draw_screen(
            self._font, self._font_bold,
            self._screen,
            self._cell_w, self._cell_h,
            pad, pad,
            theme.FONT_SIZE_TERMINAL,
        )

        # Draw cursor
        cursor = self._screen.cursor
        draw_cursor(
            self._cell_w, self._cell_h,
            cursor.x, cursor.y,
            pad, pad,
            self._screen.cursor.hidden,
        )

        rl.end_drawing()

    def _cleanup(self) -> None:
        """Clean up all resources."""
        # Kill child process
        if self._child_pid > 0:
            kill_child(self._child_pid)

        # Close PTY
        if self._master_fd >= 0:
            close_master(self._master_fd)

        ghostty.cleanup()

        # Unload fonts and close window
        rl.unload_font(self._font)
        rl.unload_font(self._font_bold)
        rl.close_window()
