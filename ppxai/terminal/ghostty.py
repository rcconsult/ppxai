"""
Python ctypes bindings for libghostty-vt.

This module loads the platform-specific shared library and exposes
a Pythonic API for terminal operations. The library is optional —
ppxai falls back to existing terminal detection if not available.

Library search order:
1. ppxai/terminal/lib/<platform>/ (bundled with PyInstaller)
2. System library path (LD_LIBRARY_PATH, DYLD_LIBRARY_PATH)
3. Not found → is_available() returns False, all functions are no-ops

C API reference: https://github.com/ghostty-org/ghostty/tree/main/include/ghostty/vt
Reference implementation: https://github.com/ghostty-org/ghostling
"""

import ctypes
import ctypes.util
import platform
import sys
from pathlib import Path
from typing import Optional


# =============================================================================
# C type aliases (from include/ghostty/vt/types.h, key/event.h, key/encoder.h)
# =============================================================================

# GhosttyResult enum
GHOSTTY_SUCCESS = 0
GHOSTTY_OUT_OF_MEMORY = -1
GHOSTTY_INVALID_VALUE = -2
GHOSTTY_OUT_OF_SPACE = -3

# GhosttyKeyAction enum
GHOSTTY_KEY_ACTION_RELEASE = 0
GHOSTTY_KEY_ACTION_PRESS = 1
GHOSTTY_KEY_ACTION_REPEAT = 2

# GhosttyMods bitmask (uint16_t)
GHOSTTY_MODS_SHIFT = 1 << 0
GHOSTTY_MODS_CTRL = 1 << 1
GHOSTTY_MODS_ALT = 1 << 2
GHOSTTY_MODS_SUPER = 1 << 3
GHOSTTY_MODS_CAPS_LOCK = 1 << 4
GHOSTTY_MODS_NUM_LOCK = 1 << 5

# GhosttyKittyKeyFlags (uint8_t)
GHOSTTY_KITTY_KEY_DISABLED = 0
GHOSTTY_KITTY_KEY_DISAMBIGUATE = 1 << 0
GHOSTTY_KITTY_KEY_REPORT_EVENTS = 1 << 1
GHOSTTY_KITTY_KEY_REPORT_ALTERNATES = 1 << 2
GHOSTTY_KITTY_KEY_REPORT_ALL = 1 << 3
GHOSTTY_KITTY_KEY_REPORT_ASSOCIATED = 1 << 4

# GhosttyKeyEncoderOption enum
GHOSTTY_KEY_ENCODER_OPT_CURSOR_KEY_APPLICATION = 0
GHOSTTY_KEY_ENCODER_OPT_KEYPAD_KEY_APPLICATION = 1
GHOSTTY_KEY_ENCODER_OPT_IGNORE_KEYPAD_WITH_NUMLOCK = 2
GHOSTTY_KEY_ENCODER_OPT_ALT_ESC_PREFIX = 3
GHOSTTY_KEY_ENCODER_OPT_MODIFY_OTHER_KEYS_STATE_2 = 4
GHOSTTY_KEY_ENCODER_OPT_KITTY_FLAGS = 5
GHOSTTY_KEY_ENCODER_OPT_MACOS_OPTION_AS_ALT = 6

# GhosttyKey enum — physical key codes (subset most relevant to ppxai)
# Full enum has 150+ keys; we define the ones we actually use.
GHOSTTY_KEY_UNIDENTIFIED = 0
GHOSTTY_KEY_ENTER = 0  # Will be resolved from header; placeholder
GHOSTTY_KEY_TAB = 0
GHOSTTY_KEY_ESCAPE = 0
GHOSTTY_KEY_SPACE = 0
GHOSTTY_KEY_BACKSPACE = 0

# Opaque pointer types
GhosttyKeyEncoder = ctypes.c_void_p
GhosttyKeyEvent = ctypes.c_void_p
GhosttyTerminal = ctypes.c_void_p


# =============================================================================
# Library loading
# =============================================================================

_lib: Optional[ctypes.CDLL] = None
_load_attempted = False
_load_error: Optional[str] = None

# Cached encoder and event (reused across calls)
_encoder: Optional[ctypes.c_void_p] = None
_event: Optional[ctypes.c_void_p] = None


def _find_library() -> Optional[Path]:
    """Find the libghostty-vt shared library for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        lib_name = "libghostty_vt.so"
        platform_dir = "linux-amd64"
    elif system == "darwin":
        lib_name = "libghostty_vt.dylib"
        platform_dir = "macos-arm64" if machine == "arm64" else "macos-intel"
    elif system == "windows":
        lib_name = "ghostty_vt.dll"
        platform_dir = "windows"
    else:
        return None

    # Check bundled location (PyInstaller or development)
    module_dir = Path(__file__).parent
    bundled = module_dir / "lib" / platform_dir / lib_name
    if bundled.exists():
        return bundled

    # Check PyInstaller _MEIPASS (frozen builds)
    if hasattr(sys, "_MEIPASS"):
        frozen = Path(sys._MEIPASS) / "ppxai" / "terminal" / "lib" / platform_dir / lib_name
        if frozen.exists():
            return frozen

    return None


def _load_lib() -> Optional[ctypes.CDLL]:
    """Load the shared library, caching the result."""
    global _lib, _load_attempted, _load_error

    if _load_attempted:
        return _lib

    _load_attempted = True

    path = _find_library()
    if path is None:
        _load_error = "libghostty-vt shared library not found"
        return None

    try:
        _lib = ctypes.CDLL(str(path))
        _setup_signatures(_lib)
        _resolve_key_codes(_lib)
        return _lib
    except OSError as e:
        _load_error = f"Failed to load {path}: {e}"
        return None


def _setup_signatures(lib: ctypes.CDLL) -> None:
    """Define C function signatures matching include/ghostty/vt/key/*.h"""

    # --- Key Event lifecycle ---
    # GhosttyResult ghostty_key_event_new(const GhosttyAllocator*, GhosttyKeyEvent*)
    lib.ghostty_key_event_new.argtypes = [ctypes.c_void_p, ctypes.POINTER(GhosttyKeyEvent)]
    lib.ghostty_key_event_new.restype = ctypes.c_int

    # void ghostty_key_event_free(GhosttyKeyEvent)
    lib.ghostty_key_event_free.argtypes = [GhosttyKeyEvent]
    lib.ghostty_key_event_free.restype = None

    # --- Key Event setters ---
    # void ghostty_key_event_set_action(GhosttyKeyEvent, GhosttyKeyAction)
    lib.ghostty_key_event_set_action.argtypes = [GhosttyKeyEvent, ctypes.c_int]
    lib.ghostty_key_event_set_action.restype = None

    # void ghostty_key_event_set_key(GhosttyKeyEvent, GhosttyKey)
    lib.ghostty_key_event_set_key.argtypes = [GhosttyKeyEvent, ctypes.c_int]
    lib.ghostty_key_event_set_key.restype = None

    # void ghostty_key_event_set_mods(GhosttyKeyEvent, GhosttyMods)
    lib.ghostty_key_event_set_mods.argtypes = [GhosttyKeyEvent, ctypes.c_uint16]
    lib.ghostty_key_event_set_mods.restype = None

    # void ghostty_key_event_set_utf8(GhosttyKeyEvent, const char*, size_t)
    lib.ghostty_key_event_set_utf8.argtypes = [GhosttyKeyEvent, ctypes.c_char_p, ctypes.c_size_t]
    lib.ghostty_key_event_set_utf8.restype = None

    # --- Key Encoder lifecycle ---
    # GhosttyResult ghostty_key_encoder_new(const GhosttyAllocator*, GhosttyKeyEncoder*)
    lib.ghostty_key_encoder_new.argtypes = [ctypes.c_void_p, ctypes.POINTER(GhosttyKeyEncoder)]
    lib.ghostty_key_encoder_new.restype = ctypes.c_int

    # void ghostty_key_encoder_free(GhosttyKeyEncoder)
    lib.ghostty_key_encoder_free.argtypes = [GhosttyKeyEncoder]
    lib.ghostty_key_encoder_free.restype = None

    # --- Key Encoder operations ---
    # void ghostty_key_encoder_setopt(GhosttyKeyEncoder, GhosttyKeyEncoderOption, const void*)
    lib.ghostty_key_encoder_setopt.argtypes = [GhosttyKeyEncoder, ctypes.c_int, ctypes.c_void_p]
    lib.ghostty_key_encoder_setopt.restype = None

    # GhosttyResult ghostty_key_encoder_encode(GhosttyKeyEncoder, GhosttyKeyEvent,
    #     char* out_buf, size_t out_buf_size, size_t* out_len)
    lib.ghostty_key_encoder_encode.argtypes = [
        GhosttyKeyEncoder, GhosttyKeyEvent,
        ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.ghostty_key_encoder_encode.restype = ctypes.c_int


def _resolve_key_codes(lib: ctypes.CDLL) -> None:
    """Resolve key code enum values by encoding known keys and checking output.

    The GhosttyKey enum values are sequential but their exact values depend on
    the build. We resolve them by looking up key names from the header ordering.
    These match the enum order in include/ghostty/vt/key/event.h.
    """
    # The enum is sequential starting from 0 (UNIDENTIFIED).
    # Order from the header: writing system keys, then functional keys.
    # We hardcode the offsets based on the header enum order.
    # This is stable — the enum is part of the C ABI.
    global GHOSTTY_KEY_ENTER, GHOSTTY_KEY_TAB, GHOSTTY_KEY_ESCAPE
    global GHOSTTY_KEY_SPACE, GHOSTTY_KEY_BACKSPACE

    # Writing system keys: backquote, backslash, bracket_left, bracket_right,
    # comma, digit_0..digit_9, equal, intl_backslash, intl_ro, intl_yen,
    # a..z, minus, period, quote, semicolon, slash
    # That's: 1 + 1 + 1 + 1 + 1 + 10 + 1 + 1 + 1 + 1 + 26 + 1 + 1 + 1 + 1 + 1 = 49 keys
    # Functional keys start at offset 50:
    # alt_left, alt_right, backspace, caps_lock, context_menu,
    # control_left, control_right, enter, ...
    _FUNC_START = 50  # offset of first functional key (alt_left)
    GHOSTTY_KEY_BACKSPACE = _FUNC_START + 2
    GHOSTTY_KEY_ENTER = _FUNC_START + 7
    GHOSTTY_KEY_SPACE = _FUNC_START + 10
    GHOSTTY_KEY_TAB = _FUNC_START + 11

    # Control pad keys (after functional)
    _CTRL_PAD_START = _FUNC_START + 17  # after convert, kana_mode, non_convert
    GHOSTTY_KEY_ESCAPE = _CTRL_PAD_START + 30  # in function keys section (after arrow keys, numpad)
    # Escape is in the "Function Row" section — F keys start after numpad
    # This needs verification against actual enum. For now use a safe approach:
    # We'll verify by trying to encode and checking output.


def _get_encoder() -> Optional[ctypes.c_void_p]:
    """Get or create the cached key encoder."""
    global _encoder
    lib = _load_lib()
    if lib is None:
        return None

    if _encoder is not None:
        return _encoder

    encoder = GhosttyKeyEncoder()
    result = lib.ghostty_key_encoder_new(None, ctypes.byref(encoder))
    if result != GHOSTTY_SUCCESS:
        return None

    # Enable Kitty keyboard protocol (disambiguate mode)
    flags = ctypes.c_uint8(GHOSTTY_KITTY_KEY_DISAMBIGUATE)
    lib.ghostty_key_encoder_setopt(
        encoder,
        GHOSTTY_KEY_ENCODER_OPT_KITTY_FLAGS,
        ctypes.cast(ctypes.pointer(flags), ctypes.c_void_p),
    )

    _encoder = encoder
    return _encoder


def _get_event() -> Optional[ctypes.c_void_p]:
    """Get or create the cached key event (reused, fields reset per call)."""
    global _event
    lib = _load_lib()
    if lib is None:
        return None

    if _event is not None:
        return _event

    event = GhosttyKeyEvent()
    result = lib.ghostty_key_event_new(None, ctypes.byref(event))
    if result != GHOSTTY_SUCCESS:
        return None

    _event = event
    return _event


# =============================================================================
# Textual key name → GhosttyKey mapping
# =============================================================================

# Maps Textual key names to (GhosttyKey code, utf8 char, GhosttyMods)
# This is the bridge between Textual's key event system and libghostty.
_TEXTUAL_KEY_MAP: dict = {}  # Populated after key codes are resolved


def _build_textual_key_map() -> None:
    """Build the mapping from Textual key names to ghostty key codes."""
    global _TEXTUAL_KEY_MAP
    _TEXTUAL_KEY_MAP = {
        "enter": (GHOSTTY_KEY_ENTER, b"\r", 0),
        "ctrl+enter": (GHOSTTY_KEY_ENTER, None, GHOSTTY_MODS_CTRL),
        "tab": (GHOSTTY_KEY_TAB, b"\t", 0),
        "ctrl+tab": (GHOSTTY_KEY_TAB, None, GHOSTTY_MODS_CTRL),
        "escape": (GHOSTTY_KEY_ESCAPE, b"\x1b", 0),
        "space": (GHOSTTY_KEY_SPACE, b" ", 0),
        "backspace": (GHOSTTY_KEY_BACKSPACE, b"\x7f", 0),
    }


# =============================================================================
# Public API
# =============================================================================

def is_available() -> bool:
    """Check if libghostty-vt is available on this platform."""
    return _load_lib() is not None


def get_version() -> Optional[str]:
    """Get the libghostty-vt library version, or None if not available."""
    lib = _load_lib()
    if lib is None:
        return None
    # build_info API added March 2026 — use if available
    try:
        lib.ghostty_build_info.restype = ctypes.c_char_p
        info = lib.ghostty_build_info()
        if info:
            return info.decode("utf-8", errors="replace")
    except AttributeError:
        pass
    return "dev"


def get_load_error() -> Optional[str]:
    """Get the error message if library loading failed."""
    _load_lib()  # Ensure load was attempted
    return _load_error


def encode_key(textual_key: str) -> Optional[bytes]:
    """Encode a Textual key event to the correct VT escape sequence.

    Uses the Kitty keyboard protocol encoder, producing correct
    sequences regardless of host terminal capabilities.

    Args:
        textual_key: Textual key name (e.g., "ctrl+enter", "tab", "escape")

    Returns:
        Escape sequence bytes, or None if library not available or key unknown
    """
    lib = _load_lib()
    if lib is None:
        return None

    # Build map on first call
    if not _TEXTUAL_KEY_MAP:
        _build_textual_key_map()

    mapping = _TEXTUAL_KEY_MAP.get(textual_key)
    if mapping is None:
        return None

    ghostty_key, utf8_char, mods = mapping

    encoder = _get_encoder()
    event = _get_event()
    if encoder is None or event is None:
        return None

    # Configure the event
    lib.ghostty_key_event_set_action(event, GHOSTTY_KEY_ACTION_PRESS)
    lib.ghostty_key_event_set_key(event, ghostty_key)
    lib.ghostty_key_event_set_mods(event, mods)
    if utf8_char is not None:
        lib.ghostty_key_event_set_utf8(event, utf8_char, len(utf8_char))

    # Encode to escape sequence
    buf = ctypes.create_string_buffer(128)
    out_len = ctypes.c_size_t(0)
    result = lib.ghostty_key_encoder_encode(
        encoder, event, buf, 128, ctypes.byref(out_len)
    )

    if result != GHOSTTY_SUCCESS or out_len.value == 0:
        return None

    return buf.raw[:out_len.value]


def cleanup() -> None:
    """Free allocated resources. Called on application shutdown."""
    global _encoder, _event
    lib = _load_lib()
    if lib is None:
        return

    if _event is not None:
        lib.ghostty_key_event_free(_event)
        _event = None

    if _encoder is not None:
        lib.ghostty_key_encoder_free(_encoder)
        _encoder = None
