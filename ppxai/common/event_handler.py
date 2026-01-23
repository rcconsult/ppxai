"""
Shared event handling for all ppxai clients.

This module provides a unified way to process engine events across different clients
(TUI, VSCode, etc.) by delegating rendering to client-specific callbacks.

Architecture:
- EventHandler processes events from EngineClient
- Callbacks are provided by the client for rendering
- Business logic is centralized, UI is delegated

Version: v1.14.2
"""

from datetime import datetime
from typing import AsyncIterator, Callable, Optional, Any, Dict
from ppxai.engine.types import Event, EventType


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

    async def handle_event(self, event: Event) -> bool:
        """
        Handle a single event from the engine.

        Args:
            event: Event object from EngineClient

        Returns:
            bool: True if event loop should continue, False if should break
        """
        if event.type == EventType.STREAM_START:
            self._full_response = ""
            self._reasoning_response = ""
            self._should_break = False
            self.on_stream_start()
            return True

        elif event.type == EventType.REASONING_CHUNK:
            # Reasoning tokens from DeepSeek R1, GPT-OSS 120B
            self._reasoning_response += event.data
            self.on_reasoning_chunk(event.data)
            return True

        elif event.type == EventType.STREAM_CHUNK:
            self._full_response += event.data
            self.on_stream_chunk(event.data)
            return True

        elif event.type == EventType.TOOL_CALL:
            tool_data = {
                'tool': event.data.get('tool', 'unknown') if isinstance(event.data, dict) else 'unknown',
                'arguments': event.data.get('arguments', {}) if isinstance(event.data, dict) else {}
            }
            self.on_tool_call(tool_data)
            return True

        elif event.type == EventType.TOOL_RESULT:
            self.on_tool_result(event.data)
            return True

        elif event.type == EventType.TOOL_ERROR:
            # event.data is {tool: "...", error: "..."} object
            if isinstance(event.data, dict):
                tool_name = event.data.get('tool', 'unknown')
                error_msg = f"({tool_name}): {event.data.get('error', str(event.data))}"
            else:
                error_msg = str(event.data)
            self.on_tool_error(error_msg)
            return True

        elif event.type == EventType.CONTEXT_INJECTED:
            # File/git/tree context was auto-injected (v1.11.4)
            # Just continue - the client can choose to display or ignore
            return True

        elif event.type == EventType.CONSENT_REQUEST:
            # Consent is typically handled by engine's callback
            # This is just for logging/notification purposes
            if event.data and isinstance(event.data, dict):
                self.on_consent_request(event.data)
            return True

        elif event.type == EventType.STREAM_END:
            # Use the final response from event data if available
            final_response = event.data if event.data else self._full_response
            self.on_stream_end(final_response)
            return False  # Signal to break the loop

        elif event.type == EventType.ERROR:
            error_str = str(event.data)
            self.on_error(error_str)
            return False  # Signal to break the loop

        # Unknown event type - continue
        return True

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

    def __init__(self, console, logger, verbose: bool = False, theme_name: str = None, emoji_mode: bool = False):
        """
        Initialize TUI-specific event handler.

        Args:
            console: Rich console instance for rendering
            logger: Logger instance for debug logging
            verbose: Whether to show verbose tool output
            theme_name: Theme name for styled rendering (optional, uses config default)
            emoji_mode: Whether to show original emojis (True) or convert to text symbols (False)
        """
        from ppxai.markdown_tables import render_markdown_with_tables
        from ppxai.themes import get_theme, DEFAULT_THEME
        from ppxai.config import get_tui_theme

        self.console = console
        self.logger = logger
        self.verbose = verbose
        self.emoji_mode = emoji_mode  # emoji rendering mode
        self._render_markdown = render_markdown_with_tables

        # Get theme (from arg, config, or default)
        if theme_name:
            self.theme = get_theme(theme_name)
            self.theme_name = theme_name
        else:
            self.theme_name = get_tui_theme()
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

    async def handle_event(self, event: Event) -> bool:
        """Override to handle CONTEXT_INJECTED and AGENT_* events for TUI display."""
        if event.type == EventType.CONTEXT_INJECTED:
            # Collect injected contexts
            self._injected_contexts.append(event.data)
            # Display what was injected
            if event.data and isinstance(event.data, dict):
                source = event.data.get('source', 'unknown')
                size = event.data.get('size', 0)
                # Format size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"

                # Show what was injected
                self.console.print(f"[dim]→ Injected context: {source} ({size_str})[/dim]")
            return True

        # Status messages (v1.12.0 - checkpoint notifications, etc.)
        elif event.type == EventType.STATUS:
            # Display status/notification messages
            msg = str(event.data) if event.data else ""
            if msg:
                self.console.print(f"[cyan]{msg}[/cyan]")
            return True

        # Working directory changed (v1.13.2)
        elif event.type == EventType.WORKING_DIR_CHANGED:
            path = event.data.get("path", "") if isinstance(event.data, dict) else str(event.data)
            if path:
                self.console.print(f"[cyan]📁 Working directory: {path}[/cyan]")
            return True

        # Agent loop events (v1.11.8)
        elif event.type == EventType.AGENT_ITERATION:
            iteration = event.data.get("iteration", 0) if isinstance(event.data, dict) else 0
            max_iter = event.data.get("max", 5) if isinstance(event.data, dict) else 5
            self.console.print(f"\n[yellow]━━━ Iteration {iteration}/{max_iter} ━━━[/yellow]\n")
            return True

        elif event.type == EventType.AGENT_COMPLETE:
            summary = event.data.get("summary", "") if isinstance(event.data, dict) else ""
            self.console.print(f"\n[green]✅ Task completed![/green]")
            if summary:
                self.console.print(f"[dim]Summary: {summary}[/dim]\n")
            return False  # Signal completion

        elif event.type == EventType.AGENT_MAX_ITERATIONS:
            max_iter = event.data.get("iterations", 5) if isinstance(event.data, dict) else 5
            self.console.print(f"\n[yellow]⚠️  Max iterations ({max_iter}) reached[/yellow]")
            self.console.print("[dim]Task may be incomplete. Review output above.[/dim]\n")
            return False  # Signal completion

        # Delegate to parent for all other event types
        return await super().handle_event(event)

    def _on_stream_start(self):
        """Handle stream start for TUI."""
        # Reset reasoning state for new turn (v1.13.9)
        self._reasoning_started = False
        # With themed panels, we show header after content is complete
        pass

    def _on_reasoning_chunk(self, chunk: str):
        """Handle reasoning chunk for TUI (v1.13.9 - DeepSeek R1, GPT-OSS 120B)."""
        # Show reasoning header on first chunk
        if not self._reasoning_started:
            self._reasoning_started = True
            self.console.print("[dim italic]💭 Thinking...[/dim italic]")
        # Stream reasoning in dim italic style
        self.console.print(f"[dim italic]{chunk}[/dim italic]", end="")

    def _on_stream_chunk(self, chunk: str):
        """Handle stream chunk for TUI (silent accumulation for final render)."""
        # If we were in reasoning mode, add separator before content
        if self._reasoning_started and self._full_response == "":
            self.console.print()  # Newline after reasoning
            self.console.print("[dim]───[/dim]")  # Separator
            self._reasoning_started = False  # Reset for next turn
        # Accumulate silently - render at end with proper formatting
        pass

    def _on_stream_end(self, response: str):
        """Handle stream end for TUI with themed panel."""
        from datetime import datetime
        from ppxai.ui_components import render_message

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
