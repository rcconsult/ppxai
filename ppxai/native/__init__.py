"""
ppxai-native — Native desktop terminal emulator using Raylib + libghostty-vt.

Spawns ppxai Rich TUI inside a PTY and renders the VT output as a cell grid
using libghostty-vt for parsing and Raylib for drawing. Full Rich formatting
(markdown, syntax highlighting, tables, panels) works unchanged.

macOS/Linux only. Windows uses the direct chat UI fallback (Phase 1-6).
"""


def main() -> None:
    """Entry point for ppxai-native."""
    from ppxai.native.app import NativeApp
    app = NativeApp()
    app.run()
