"""
Python ctypes bindings for libghostty-vt.

This module loads the platform-specific shared library and exposes
a Pythonic API for terminal operations. The library is optional —
ppxai falls back to existing terminal detection if not available.

Library search order:
1. ppxai/terminal/lib/<platform>/ (bundled with PyInstaller)
2. System library path (LD_LIBRARY_PATH, DYLD_LIBRARY_PATH)
3. Not found → is_available() returns False, all functions are no-ops
"""

import ctypes
import platform
import sys
from pathlib import Path
from typing import Optional


# Library handle — loaded lazily on first use
_lib: Optional[ctypes.CDLL] = None
_load_attempted = False
_load_error: Optional[str] = None


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
        return _lib
    except OSError as e:
        _load_error = f"Failed to load {path}: {e}"
        return None


def _setup_signatures(lib: ctypes.CDLL) -> None:
    """Define C function signatures for type safety.

    These mirror the declarations in include/ghostty/key.h and other headers.
    Updated when we bump the pinned Ghostty commit.
    """
    # TODO: Define function signatures once C API stabilizes
    # Example (from key.h):
    # lib.ghostty_key_encode.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
    # lib.ghostty_key_encode.restype = ctypes.c_int
    pass


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
    # TODO: Call version function once available in C API
    return "dev"


def get_load_error() -> Optional[str]:
    """Get the error message if library loading failed."""
    _load_lib()  # Ensure load was attempted
    return _load_error


def encode_key(key: int, modifiers: int = 0) -> Optional[bytes]:
    """Encode a key event to the correct VT escape sequence.

    Uses the Kitty keyboard protocol encoder, producing correct
    sequences regardless of host terminal capabilities.

    Args:
        key: Key code (platform-specific mapping TBD)
        modifiers: Modifier mask (shift, ctrl, alt, etc.)

    Returns:
        Escape sequence bytes, or None if library not available
    """
    lib = _load_lib()
    if lib is None:
        return None
    # TODO: Call ghostty_key_encode once C API signatures are defined
    return None
