"""
Display tool: display_file in split view.

Allows AI to show files/artifacts in the TUI split panel.
"""

from pathlib import Path

from ppxai.common.logger import get_logger

from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool


class DisplayFileTool(BaseTool):
    """Tool to display a file in the TUI split view.

    This allows AI to proactively show generated files, artifacts,
    or relevant code files to the user after completing a task.
    """

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "display_file"
        self.description = (
            "Open a file in the user's side panel viewer. "
            "ONLY call this when the user explicitly asks to see, view, preview, or open a file. "
            "Do NOT call this after writing or editing files - the user can see changes in their editor. "
            "Do NOT call this to show your work or results - just describe what you did in text. "
            "This tool is for user-requested file viewing only."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Path to the file to display (relative to working directory or absolute path)"
                }
            },
            "required": ["filepath"]
        }

    async def execute(self, filepath: str, **kwargs) -> str:
        """Display a file in the built-in viewer/editor.

        After successful execution, chat.py emits a DISPLAY_FILE event that clients handle:
        - ppxaide (Textual TUI): Opens file in side panel with syntax highlighting
        - ppxai (Rich TUI): Displays file with syntax highlighting via /show command
        - VSCode: Opens file in native editor
        - Web: Opens file in Monaco editor

        Args:
            filepath: Path to the file to display

        Returns:
            Success message or error
        """
        logger = get_logger("tui")

        try:
            # Resolve path
            working_dir_str = self.engine.get_working_dir()
            working_dir = Path(working_dir_str) if working_dir_str else Path.cwd()
            logger.debug(f"[display_file tool] filepath={filepath}, working_dir={working_dir}")
            path = Path(filepath).expanduser()

            if not path.is_absolute():
                path = working_dir / filepath

            path = path.resolve()
            logger.debug(f"[display_file tool] resolved_path={path}, exists={path.exists()}, is_file={path.is_file() if path.exists() else 'N/A'}")

            if not path.exists():
                msg = f"Error: File not found: {filepath}"
                logger.debug(f"[display_file tool] returning: {msg}")
                return msg

            if not path.is_file():
                msg = f"Error: Not a file: {filepath}"
                logger.debug(f"[display_file tool] returning: {msg}")
                return msg

            # DISPLAY_FILE event is emitted by chat.py after tool execution (v1.15.1)
            # This allows the event to be properly yielded in the event stream
            msg = f"Opening {path.name} in viewer"
            logger.debug(f"[display_file tool] returning success: {msg}")
            return msg

        except Exception as e:
            msg = f"Error displaying file: {str(e)}"
            logger.debug(f"[display_file tool] exception: {msg}")
            return msg


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol):
    """Register display tools.

    Args:
        manager: ToolManager instance
        engine: EngineClient instance

    Note:
        v1.15.1: After successful tool execution, chat.py emits DISPLAY_FILE
        events which clients handle by executing their /show command handlers.
        Works across all clients (TUI/VSCode/Web).
    """
    if engine is not None:
        manager.register_tool(DisplayFileTool(engine))
