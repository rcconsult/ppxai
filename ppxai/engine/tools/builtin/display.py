"""
Display tool: display_file in split view.

Allows AI to show files/artifacts in the TUI split panel.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from ..base import BaseTool

if TYPE_CHECKING:
    from ...client import EngineClient
    from ..manager import ToolManager


class DisplayFileTool(BaseTool):
    """Tool to display a file in the TUI split view.

    This allows AI to proactively show generated files, artifacts,
    or relevant code files to the user after completing a task.
    """

    def __init__(self, engine: 'EngineClient'):
        self.engine = engine
        self.name = "display_file"
        self.description = (
            "Display a file in the split view panel. Use this to show generated files, "
            "artifacts, or relevant code files to the user after you've created or modified them. "
            "The file will open in a side panel with syntax highlighting, tree view for "
            "structured data, or image preview as appropriate."
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
        from ppxai.common.logger import get_logger
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


def register_tools(manager: 'ToolManager', engine: 'EngineClient'):
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
