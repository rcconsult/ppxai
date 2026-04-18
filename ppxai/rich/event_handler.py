"""
Shared event handling for all ppxai clients.

This module provides a unified way to process engine events across different clients
(TUI, VSCode, etc.) by delegating rendering to client-specific callbacks.

Architecture:
- EventHandler processes events from EngineClient
- Callbacks are provided by the client for rendering
- Business logic is centralized, UI is delegated

Version: v1.17.5
"""

from datetime import datetime
from typing import AsyncIterator, Callable, Optional, Any, Dict
from ppxai.engine.types import Event, EventType
from ppxai.rich.themes import get_theme, DEFAULT_THEME
from ppxai.rich.ui_components import render_message
from ppxai.commands.factory import CommandFactory
from ppxai.rendering.rich_renderer import RichRenderer


class EventHandler:
    """
    Base event handler that all clients can use.

    Handles engine events in a client-agnostic way by delegating
    rendering to client-specific callbacks.

    Usage:
        # In TUI
        handler = EventHandler(
            on_stream_start=lambda: console.print("\\n[bold cyan]Assistant:[/bold cyan]"),
            on_stream_chunk=lambda chunk: full_response += chunk,
            on_stream_end=lambda response: render_markdown(response),
            on_tool_call=lambda tool: console.print(f"→ Calling: {tool['tool']}"),
            on_error=lambda error: console.print(f"[red]Error: {error}[/red]")
        )

        async for event in engine.chat(prompt):
            await handler.handle_event(event)
    """

    def __init__(
        self,
        on_stream_start: Optional[Callable[[], None]] = None,
        on_stream_chunk: Optional[Callable[[str], None]] = None,
        on_reasoning_chunk: Optional[Callable[[str], None]] = None,
        on_stream_end: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_tool_result: Optional[Callable[[Any], None]] = None,
        on_tool_error: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_consent_request: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ):
        """
        Initialize event handler with callbacks.

        Args:
            on_stream_start: Called when streaming starts (no args)
            on_stream_chunk: Called for each chunk with chunk text
            on_reasoning_chunk: Called for reasoning tokens (DeepSeek R1, GPT-OSS 120B) (v1.13.9)
            on_stream_end: Called when streaming ends with full response
            on_tool_call: Called when tool is invoked with {tool, arguments}
            on_tool_result: Called when tool returns with result data
            on_tool_error: Called when tool execution fails with error message
            on_error: Called on errors with error message
            on_consent_request: Called to request file editing consent, returns bool
        """
        self.on_stream_start = on_stream_start or (lambda: None)
        self.on_stream_chunk = on_stream_chunk or (lambda x: None)
        self.on_reasoning_chunk = on_reasoning_chunk or (lambda x: None)
        self.on_stream_end = on_stream_end or (lambda x: None)
        self.on_tool_call = on_tool_call or (lambda x: None)
        self.on_tool_result = on_tool_result or (lambda x: None)
        self.on_tool_error = on_tool_error or (lambda x: None)
        self.on_error = on_error or (lambda x: None)
        self.on_consent_request = on_consent_request or (lambda x: False)

        # Internal state for accumulation
        self._full_response = ""
        self._reasoning_response = ""
        self._should_break = False

    # Strategy dispatch table: EventType → (handler_method_name, returns)
    # Handlers return True to continue, False to break the event loop.
    _EVENT_DISPATCH = {
        EventType.STREAM_START: ("_handle_stream_start", True),
        EventType.REASONING_CHUNK: ("_handle_reasoning_chunk", True),
        EventType.STREAM_CHUNK: ("_handle_stream_chunk", True),
        EventType.TOOL_CALL: ("_handle_tool_call", True),
        EventType.TOOL_RESULT: ("_handle_tool_result", True),
        EventType.TOOL_ERROR: ("_handle_tool_error", True),
        EventType.CONTEXT_INJECTED: (None, True),  # no-op, continue
        EventType.CONSENT_REQUEST: ("_handle_consent_request", True),
        EventType.STREAM_END: ("_handle_stream_end", False),
        EventType.ERROR: ("_handle_error", False),
    }

    async def handle_event(self, event: Event) -> bool:
        """Handle a single event from the engine.

        Uses strategy dispatch table for O(1) lookup instead of if/elif chain.

        Returns:
            bool: True if event loop should continue, False if should break
        """
        entry = self._EVENT_DISPATCH.get(event.type)
        if entry is None:
            return True  # Unknown event type — continue

        method_name, should_continue = entry
        if method_name is not None:
            getattr(self, method_name)(event)
        return should_continue

    def _handle_stream_start(self, event: Event) -> None:
        self._full_response = ""
        self._reasoning_response = ""
        self._should_break = False
        self.on_stream_start()

    def _handle_reasoning_chunk(self, event: Event) -> None:
        self._reasoning_response += event.data
        self.on_reasoning_chunk(event.data)

    def _handle_stream_chunk(self, event: Event) -> None:
        self._full_response += event.data
        self.on_stream_chunk(event.data)

    def _handle_tool_call(self, event: Event) -> None:
        tool_data = {
            'tool': event.data.get('tool', 'unknown') if isinstance(event.data, dict) else 'unknown',
            'arguments': event.data.get('arguments', {}) if isinstance(event.data, dict) else {}
        }
        self.on_tool_call(tool_data)

    def _handle_tool_result(self, event: Event) -> None:
        self.on_tool_result(event.data)

    def _handle_tool_error(self, event: Event) -> None:
        if isinstance(event.data, dict):
            tool_name = event.data.get('tool', 'unknown')
            error_msg = f"({tool_name}): {event.data.get('error', str(event.data))}"
        else:
            error_msg = str(event.data)
        self.on_tool_error(error_msg)

    def _handle_consent_request(self, event: Event) -> None:
        if event.data and isinstance(event.data, dict):
            self.on_consent_request(event.data)

    def _handle_stream_end(self, event: Event) -> None:
        final_response = event.data if event.data else self._full_response
        self.on_stream_end(final_response)

    def _handle_error(self, event: Event) -> None:
        self.on_error(str(event.data))

    async def process_events(self, event_stream: AsyncIterator[Event]) -> str:
        """
        Process all events from an async iterator.

        Convenience method that handles the entire event loop.

        Args:
            event_stream: Async iterator of Event objects

        Returns:
            str: The final accumulated response
        """
        async for event in event_stream:
            should_continue = await self.handle_event(event)
            if not should_continue:
                break

        return self._full_response

    def get_response(self) -> str:
        """
        Get the accumulated response text.

        Returns:
            str: Full response accumulated from chunks
        """
        return self._full_response

    def reset(self):
        """Reset internal state for next conversation turn."""
        self._full_response = ""
        self._should_break = False


class TUIEventHandler(EventHandler):
    """
    Specialized event handler for TUI with Rich console.

    This is a convenience class that provides sensible defaults for TUI rendering.

    Usage:
        handler = TUIEventHandler(console, logger, verbose=False)
        async for event in engine.chat(prompt):
            await handler.handle_event(event)
    """

    def __init__(self, console, logger, verbose: bool = False, theme_name: str = None, emoji_mode: bool = False, engine_client=None):
        """
        Initialize TUI-specific event handler.

        Args:
            console: Rich console instance for rendering
            logger: Logger instance for debug logging
            verbose: Whether to show verbose tool output
            theme_name: Theme name for styled rendering (optional, uses config default)
            emoji_mode: Whether to show original emojis (True) or convert to text symbols (False)
            engine_client: Engine client instance (for DISPLAY_FILE event handler)
        """
        self.console = console
        self.logger = logger
        self.verbose = verbose
        self.emoji_mode = emoji_mode  # emoji rendering mode
        self.engine_client = engine_client  # for /show command in DISPLAY_FILE handler

        # Get theme (from arg, config, or default)
        if theme_name:
            self.theme = get_theme(theme_name)
            self.theme_name = theme_name
        else:
            self.theme_name = DEFAULT_THEME
            self.theme = get_theme(self.theme_name)

        super().__init__(
            on_stream_start=self._on_stream_start,
            on_stream_chunk=self._on_stream_chunk,
            on_reasoning_chunk=self._on_reasoning_chunk,
            on_stream_end=self._on_stream_end,
            on_tool_call=self._on_tool_call,
            on_tool_result=self._on_tool_result,
            on_tool_error=self._on_tool_error,
            on_error=self._on_error,
        )

        # Track injected contexts for display
        self._injected_contexts = []
        # Track reasoning state for collapsible display
        self._reasoning_started = False
        # Track if thinking indicator was shown (v1.15.0)
        self._thinking_shown = False

    # TUI-specific event dispatch — extends base class dispatch table.
    # Entries: EventType → (method_name, should_continue)
    _TUI_EVENT_DISPATCH = {
        EventType.CONTEXT_INJECTED: ("_tui_context_injected", True),
        EventType.STATUS: ("_tui_status", True),
        EventType.WORKING_DIR_CHANGED: ("_tui_working_dir_changed", True),
        EventType.AGENT_ITERATION: ("_tui_agent_iteration", True),
        EventType.AGENT_COMPLETE: ("_tui_agent_complete", False),
        EventType.AGENT_MAX_ITERATIONS: ("_tui_agent_max_iterations", False),
        EventType.DISPLAY_FILE: ("_tui_display_file", True),
        EventType.TOOL_GROUP_START: ("_tui_tool_group_start", True),
        EventType.TOOL_GROUP_END: ("_tui_tool_group_end", True),
    }

    async def handle_event(self, event: Event) -> bool:
        """Handle TUI-specific events, delegate rest to base class."""
        entry = self._TUI_EVENT_DISPATCH.get(event.type)
        if entry is not None:
            method_name, should_continue = entry
            getattr(self, method_name)(event)
            return should_continue
        return await super().handle_event(event)

    def _tui_context_injected(self, event: Event) -> None:
        self._injected_contexts.append(event.data)
        if event.data and isinstance(event.data, dict):
            source = event.data.get('source', 'unknown')
            size = event.data.get('size', 0)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            self.console.print(f"[dim]→ Injected context: {source} ({size_str})[/dim]")

    def _tui_status(self, event: Event) -> None:
        msg = str(event.data) if event.data else ""
        if msg:
            self.console.print(f"[cyan]{msg}[/cyan]")

    def _tui_working_dir_changed(self, event: Event) -> None:
        path = event.data.get("path", "") if isinstance(event.data, dict) else str(event.data)
        if path:
            self.console.print(f"[cyan]📁 Working directory: {path}[/cyan]")

    def _tui_agent_iteration(self, event: Event) -> None:
        iteration = event.data.get("iteration", 0) if isinstance(event.data, dict) else 0
        max_iter = event.data.get("max", 5) if isinstance(event.data, dict) else 5
        self.console.print(f"\n[yellow]━━━ Iteration {iteration}/{max_iter} ━━━[/yellow]\n")

    def _tui_agent_complete(self, event: Event) -> None:
        summary = event.data.get("summary", "") if isinstance(event.data, dict) else ""
        self.console.print(f"\n[green]✅ Task completed![/green]")
        if summary:
            self.console.print(f"[dim]Summary: {summary}[/dim]\n")

    def _tui_agent_max_iterations(self, event: Event) -> None:
        max_iter = event.data.get("iterations", 5) if isinstance(event.data, dict) else 5
        self.console.print(f"\n[yellow]⚠️  Max iterations ({max_iter}) reached[/yellow]")
        self.console.print("[dim]Task may be incomplete. Review output above.[/dim]\n")

    def _tui_display_file(self, event: Event) -> None:
        filepath = event.data.get("filepath") if isinstance(event.data, dict) else None
        if not filepath:
            return
        spec = CommandFactory.get('show')
        if not spec:
            return
        try:
            class SimpleContext:
                def __init__(self, console, engine_client):
                    self.console = console
                    self.engine_client = engine_client
            context = SimpleContext(self.console, self.engine_client)
            result = spec.handler(context, filepath)
            RichRenderer.render(result)
        except Exception as e:
            self.logger.error(f"Error displaying file: {e}")
            self.console.print(f"[red]Error displaying file: {e}[/red]")

    def _tui_tool_group_start(self, event: Event) -> None:
        iteration = event.data.get("iteration", 0) if isinstance(event.data, dict) else 0
        count = event.data.get("count", 0) if isinstance(event.data, dict) else 0
        self.console.print(f"[dim]─── Iteration {iteration} ({count} tool{'s' if count != 1 else ''}) ───[/dim]")

    def _tui_tool_group_end(self, event: Event) -> None:
        if isinstance(event.data, dict):
            all_ok = event.data.get("all_succeeded", True)
            tools = event.data.get("tools", [])
            tool_list = ", ".join(tools) if tools else ""
        else:
            all_ok = True
            tool_list = ""
        status = "[green]✓[/green]" if all_ok else "[red]✗[/red]"
        suffix = f" {tool_list}" if tool_list else ""
        self.console.print(f"[dim]───{suffix} {status} ───[/dim]")

    def _on_stream_start(self):
        """Handle stream start for TUI."""
        # Reset state for new turn
        self._reasoning_started = False
        self._thinking_shown = True
        # Show thinking indicator while waiting for response (v1.15.0)
        self.console.print("[dim italic]⏳ Thinking...[/dim italic]", end="\r")

    def _on_reasoning_chunk(self, chunk: str):
        """Handle reasoning chunk for TUI (v1.13.9 - DeepSeek R1, GPT-OSS 120B)."""
        # Show reasoning header on first chunk
        if not self._reasoning_started:
            self._reasoning_started = True
            # Clear "Thinking..." and show reasoning header (v1.15.0)
            if self._thinking_shown:
                self.console.print(" " * 20, end="\r")  # Clear line
                self._thinking_shown = False
            self.console.print("[dim italic]💭 Thinking...[/dim italic]")
        # Stream reasoning in dim italic style
        self.console.print(f"[dim italic]{chunk}[/dim italic]", end="")

    def _on_stream_chunk(self, chunk: str):
        """Handle stream chunk for TUI (silent accumulation for final render)."""
        # Clear thinking indicator on first content chunk (v1.15.0)
        if self._thinking_shown:
            self.console.print(" " * 20, end="\r")  # Clear line
            self._thinking_shown = False
        # If we were in reasoning mode, add separator before content
        if self._reasoning_started and self._full_response == "":
            self.console.print()  # Newline after reasoning
            self.console.print("[dim]───[/dim]")  # Separator
            self._reasoning_started = False  # Reset for next turn
        # Accumulate silently - render at end with proper formatting
        pass

    def _on_stream_end(self, response: str):
        """Handle stream end for TUI with themed panel."""
        # Clear thinking indicator if still showing (v1.15.0)
        if self._thinking_shown:
            self.console.print(" " * 20, end="\r")
            self._thinking_shown = False

        self.logger.log_assistant_message(response)
        if response.strip():
            # Render response in a themed panel with rounded corners
            # normalize_emojis: True = convert to text symbols, False = keep original emojis
            # emoji_mode: True = show original, False = use text symbols
            panel = render_message(
                content=response,
                role="assistant",
                theme=self.theme,
                timestamp=datetime.now(),
                show_timestamp=True,
                normalize_emojis=not self.emoji_mode,  # Invert: emoji_mode=True means don't normalize
            )
            self.console.print(panel)
        self.console.print()  # Blank line after response

    def _on_tool_call(self, tool_data: Dict[str, Any]):
        """Handle tool call for TUI."""
        tool_name = tool_data['tool']
        tool_args = tool_data['arguments']
        self.console.print(f"[cyan]→ Calling tool: {tool_name}[/cyan]")
        self.logger.log_tool_call(tool_name, tool_args)

        if self.verbose:
            self.console.print(f"[dim]  Arguments: {tool_args}[/dim]")

    def _on_tool_result(self, result: Any):
        """Handle tool result for TUI."""
        tool_name = result.get('tool', 'unknown') if isinstance(result, dict) else 'unknown'
        result_str = str(result) if result else ''
        self.logger.log_tool_result(tool_name, result_str)

        if self.verbose:
            self.console.print(f"[dim]  Result: {result}[/dim]")

    def _on_tool_error(self, error: str):
        """Handle tool error for TUI."""
        self.console.print(f"[red]✗ Tool error: {error}[/red]")
        # Extract tool name if possible
        tool_name = 'unknown'
        self.logger.log_tool_error(tool_name, error)

    def _on_error(self, error: str):
        """Handle error for TUI."""
        self.console.print(f"[red]Error: {error}[/red]")

        # Parse error code if present
        if "Error code:" in error:
            try:
                error_code = int(error.split("Error code:")[1].split()[0])
                self.logger.log_api_error(error_code, error)
            except (ValueError, IndexError):
                self.logger.error(f"API Error: {error}")
        else:
            self.logger.error(f"Error: {error}")
