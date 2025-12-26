"""
Shared command handling for ppxai clients.

Provides a client-agnostic command parser and executor that returns structured
results. Clients are responsible for rendering these results in their own UI.

Architecture:
- CommandHandler: Parses and executes commands
- CommandResult: Structured result that clients can render
- No direct UI dependencies (Rich, console, etc.)

Version: v1.11.7
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable
from enum import Enum


class CommandStatus(Enum):
    """Status codes for command execution."""
    SUCCESS = "success"
    ERROR = "error"
    INFO = "info"
    WARNING = "warning"


@dataclass
class CommandResult:
    """
    Structured result from command execution.

    Clients render this according to their UI (Rich for TUI, JSON for HTTP, etc.)
    """
    status: CommandStatus
    message: str
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "message": self.message,
            "data": self.data or {}
        }


class CommandHandler:
    """
    Client-agnostic command handler.

    Parses slash commands and executes them, returning structured results.
    UI rendering is delegated to the client.

    Usage:
        handler = CommandHandler(engine_client)
        result = handler.execute("/tools enable")

        # TUI renders with Rich
        if result.status == CommandStatus.SUCCESS:
            console.print(f"[green]{result.message}[/green]")

        # Server returns JSON
        return result.to_dict()
    """

    def __init__(
        self,
        engine_client=None,
        callbacks: Optional[Dict[str, Callable]] = None
    ):
        """
        Initialize command handler.

        Args:
            engine_client: EngineClient instance for AI operations
            callbacks: Optional dict of client-specific callbacks:
                - save_session: () -> str (returns filepath)
                - load_session: (name: str) -> bool
                - clear_session: () -> None
                - get_history: () -> list
        """
        self.engine_client = engine_client
        self.callbacks = callbacks or {}

    def parse_command(self, input_str: str) -> tuple[str, str]:
        """
        Parse command string into command and arguments.

        Args:
            input_str: Command string (e.g., "/tools enable")

        Returns:
            tuple: (command, args) e.g., ("tools", "enable")
        """
        parts = input_str.strip().split(maxsplit=1)
        if not parts:
            return ("", "")

        command = parts[0].lstrip('/')
        args = parts[1] if len(parts) > 1 else ""

        return (command, args)

    def execute(self, input_str: str) -> CommandResult:
        """
        Execute a command and return structured result.

        Args:
            input_str: Full command string (e.g., "/tools enable")

        Returns:
            CommandResult: Structured result for client to render
        """
        command, args = self.parse_command(input_str)

        # Route to appropriate handler
        if command in ['quit', 'exit']:
            return self._handle_quit()
        elif command == 'help':
            return self._handle_help(args)
        elif command == 'clear':
            return self._handle_clear()
        elif command == 'save':
            return self._handle_save(args)
        elif command == 'export':
            return self._handle_export(args)
        elif command == 'load':
            return self._handle_load(args)
        elif command == 'sessions':
            return self._handle_sessions()
        elif command == 'tools':
            return self._handle_tools(args)
        elif command == 'model':
            return self._handle_model(args)
        elif command == 'provider':
            return self._handle_provider(args)
        elif command == 'debug-log':
            return self._handle_debug_log(args)
        else:
            return CommandResult(
                status=CommandStatus.ERROR,
                message=f"Unknown command: /{command}. Type /help for available commands."
            )

    def _handle_quit(self) -> CommandResult:
        """Handle quit command."""
        return CommandResult(
            status=CommandStatus.SUCCESS,
            message="quit",
            data={"action": "quit"}
        )

    def _handle_help(self, args: str) -> CommandResult:
        """Handle help command."""
        if args == "editing":
            return CommandResult(
                status=CommandStatus.INFO,
                message="file_editing_help",
                data={"topic": "editing"}
            )

        # Return list of commands for client to format
        commands = {
            "/help": "Show available commands",
            "/clear": "Clear conversation history",
            "/save": "Save session to JSON",
            "/export [filename]": "Export last answer to markdown",
            "/load <name>": "Load a saved session",
            "/sessions": "List saved sessions",
            "/tools [enable|disable|status|list]": "Manage AI tools",
            "/model [list|<model_id>]": "Switch or list models",
            "/provider [list|<provider_id>]": "Switch or list providers",
            "/debug-log [on|off|show|clear]": "Control debug logging",
            "/quit": "Exit the application",
        }

        return CommandResult(
            status=CommandStatus.INFO,
            message="Available commands",
            data={"commands": commands}
        )

    def _handle_clear(self) -> CommandResult:
        """Handle clear command."""
        if "clear_session" in self.callbacks:
            self.callbacks["clear_session"]()

        return CommandResult(
            status=CommandStatus.SUCCESS,
            message="Conversation history cleared"
        )

    def _handle_save(self, args: str) -> CommandResult:
        """Handle save command."""
        if "save_session" not in self.callbacks:
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Save functionality not available"
            )

        try:
            filepath = self.callbacks["save_session"]()
            return CommandResult(
                status=CommandStatus.SUCCESS,
                message=f"Session saved",
                data={"filepath": str(filepath)}
            )
        except Exception as e:
            return CommandResult(
                status=CommandStatus.ERROR,
                message=f"Error saving session: {e}"
            )

    def _handle_export(self, args: str) -> CommandResult:
        """Handle export command."""
        if "export_answer" not in self.callbacks:
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Export functionality not available"
            )

        try:
            filename = args.strip() if args else None
            filepath = self.callbacks["export_answer"](filename)
            return CommandResult(
                status=CommandStatus.SUCCESS,
                message=f"Answer exported",
                data={"filepath": str(filepath)}
            )
        except Exception as e:
            return CommandResult(
                status=CommandStatus.ERROR,
                message=f"Error exporting answer: {e}"
            )

    def _handle_load(self, args: str) -> CommandResult:
        """Handle load command."""
        if not args:
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Usage: /load <session_name>"
            )

        if "load_session" not in self.callbacks:
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Load functionality not available"
            )

        try:
            success = self.callbacks["load_session"](args)
            if success:
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message=f"Session '{args}' loaded"
                )
            else:
                return CommandResult(
                    status=CommandStatus.ERROR,
                    message=f"Session '{args}' not found"
                )
        except Exception as e:
            return CommandResult(
                status=CommandStatus.ERROR,
                message=f"Error loading session: {e}"
            )

    def _handle_sessions(self) -> CommandResult:
        """Handle sessions command."""
        if "list_sessions" not in self.callbacks:
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Sessions list not available"
            )

        try:
            sessions = self.callbacks["list_sessions"]()
            return CommandResult(
                status=CommandStatus.INFO,
                message="Saved sessions",
                data={"sessions": sessions}
            )
        except Exception as e:
            return CommandResult(
                status=CommandStatus.ERROR,
                message=f"Error listing sessions: {e}"
            )

    def _handle_tools(self, args: str) -> CommandResult:
        """Handle tools command."""
        if not self.engine_client:
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Tools require engine client"
            )

        subcommand = args.split()[0] if args else "status"

        if subcommand == "enable":
            self.engine_client.enable_tools()
            return CommandResult(
                status=CommandStatus.SUCCESS,
                message="AI tools enabled"
            )
        elif subcommand == "disable":
            self.engine_client.disable_tools()
            return CommandResult(
                status=CommandStatus.SUCCESS,
                message="AI tools disabled"
            )
        elif subcommand == "status":
            enabled = self.engine_client.tools_enabled
            tool_count = len(self.engine_client.list_tools()) if enabled else 0
            return CommandResult(
                status=CommandStatus.INFO,
                message=f"Tools: {'enabled' if enabled else 'disabled'}",
                data={"enabled": enabled, "count": tool_count}
            )
        elif subcommand == "list":
            tools = self.engine_client.list_tools()
            return CommandResult(
                status=CommandStatus.INFO,
                message="Available tools",
                data={"tools": [t.to_dict() for t in tools]}
            )
        else:
            return CommandResult(
                status=CommandStatus.ERROR,
                message=f"Unknown tools subcommand: {subcommand}"
            )

    def _handle_model(self, args: str) -> CommandResult:
        """Handle model command."""
        if not self.engine_client:
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Model switching requires engine client"
            )

        if not args or args == "list":
            models = self.engine_client.list_models()
            current = self.engine_client.model
            return CommandResult(
                status=CommandStatus.INFO,
                message="Available models",
                data={"models": models, "current": current}
            )
        else:
            try:
                self.engine_client.set_model(args)
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message=f"Switched to model: {args}"
                )
            except Exception as e:
                return CommandResult(
                    status=CommandStatus.ERROR,
                    message=f"Error switching model: {e}"
                )

    def _handle_provider(self, args: str) -> CommandResult:
        """Handle provider command."""
        if not self.engine_client:
            return CommandResult(
                status=CommandStatus.ERROR,
                message="Provider switching requires engine client"
            )

        if not args or args == "list":
            providers = self.engine_client.list_providers()
            current = self.engine_client.provider_name
            return CommandResult(
                status=CommandStatus.INFO,
                message="Available providers",
                data={"providers": providers, "current": current}
            )
        else:
            try:
                self.engine_client.set_provider(args)
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    message=f"Switched to provider: {args}"
                )
            except Exception as e:
                return CommandResult(
                    status=CommandStatus.ERROR,
                    message=f"Error switching provider: {e}"
                )

    def _handle_debug_log(self, args: str) -> CommandResult:
        """Handle debug-log command."""
        from ppxai.common.logger import get_logger
        logger = get_logger("tui")  # TUI-specific for now

        subcommand = args.strip().lower() if args else "status"

        if subcommand == "on":
            logger.enable()
            return CommandResult(
                status=CommandStatus.SUCCESS,
                message=f"Debug logging enabled: {logger.log_file}"
            )
        elif subcommand == "off":
            logger.disable()
            return CommandResult(
                status=CommandStatus.SUCCESS,
                message="Debug logging disabled"
            )
        elif subcommand == "clear":
            logger.clear()
            return CommandResult(
                status=CommandStatus.SUCCESS,
                message="Debug log cleared"
            )
        elif subcommand == "show":
            if logger.log_file and logger.log_file.exists():
                content = logger.log_file.read_text()
                return CommandResult(
                    status=CommandStatus.INFO,
                    message="Debug log contents",
                    data={"content": content}
                )
            else:
                return CommandResult(
                    status=CommandStatus.WARNING,
                    message="No debug log found"
                )
        else:  # status
            return CommandResult(
                status=CommandStatus.INFO,
                message=f"Debug logging: {'enabled' if logger.enabled else 'disabled'}",
                data={"enabled": logger.enabled, "log_file": str(logger.log_file) if logger.log_file else None}
            )
