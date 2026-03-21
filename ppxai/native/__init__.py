"""
ppxai-native — Native desktop application using Raylib + libghostty-vt.

Renders a chat interface directly using Raylib 2D drawing, bypassing both
browser and terminal emulator dependencies. Uses the same EngineClient as
ppxaide for AI communication.
"""


def main() -> None:
    """Entry point for ppxai-native."""
    from ppxai.native.app import NativeApp
    app = NativeApp()
    app.run()
