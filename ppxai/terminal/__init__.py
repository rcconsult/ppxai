"""
ppxai.terminal — Native terminal library bindings via libghostty-vt.

Provides Python bindings to libghostty-vt for:
- Kitty keyboard protocol encoding (fixes Ctrl+Enter across all terminals)
- Terminal capability detection
- VT sequence generation

The shared library (libghostty_vt.so/.dylib/.dll) is bundled with
PyInstaller builds and loaded at runtime via ctypes. No build tools
or headers are needed at runtime.

Build artifacts are published via the build-ghostty-vt.yml CI workflow
and stored as GitHub release assets tagged libghostty-<date>.
"""

from ppxai.terminal.ghostty import is_available, get_version, encode_key, cleanup

__all__ = ["is_available", "get_version", "encode_key", "cleanup"]
