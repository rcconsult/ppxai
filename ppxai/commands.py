"""
Command handlers for the ppxai application.
"""

import os
import asyncio
from datetime import datetime
from typing import Optional

from rich.console import Console
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.validation import Validator, ValidationError

from .config import CODING_MODEL, get_coding_model, get_provider_config, get_api_key, get_base_url, PROVIDERS
from .prompts import CODING_PROMPTS
from .utils import read_file_content
from .ui import (
    console,
    display_welcome,
    display_spec_help,
    display_file_editing_help,
    display_tool_help,
    select_model,
    select_provider,
    display_sessions,
    display_usage,
    display_global_usage,
    display_tools_table,
)
from .themes import get_theme, list_themes, Theme, DEFAULT_THEME
from .ui_components import render_theme_list


class ConsentValidator(Validator):
    """Validator for file edit consent responses."""

    def validate(self, document):
        text = document.text.strip().lower()
        if text not in ['y', 'n', 'yes', 'no', 'always', 'never']:
            raise ValidationError(
                message="Please enter: y (yes), n (no), always, or never",
                cursor_position=len(document.text)
            )


async def tui_consent_handler(file_path: str) -> tuple[bool, str]:
    """
    Handle file edit consent request in TUI.

    Prompts user with options:
    - y/yes: Allow editing this file (this session)
    - n/no: Deny editing this file
    - always: Allow editing all files (this session)
    - never: Deny all file edits (this session)

    Args:
        file_path: Path to file that needs editing

    Returns:
        tuple: (approved: bool, response: str)
    """
    console.print(f"\n[bold yellow]⚠️  File Edit Request[/bold yellow]")
    console.print(f"[cyan]AI wants to edit:[/cyan] {file_path}")
    console.print("[dim]Options: y (yes), n (no), always (all files), never (block all)[/dim]")

    try:
        # Use prompt_toolkit for input with validation
        response = await asyncio.to_thread(
            pt_prompt,
            "Allow edit? ",
            validator=ConsentValidator(),
            validate_while_typing=False
        )
        response = response.strip().lower()

        # Normalize response
        if response in ['yes', 'y']:
            response = 'y'
            approved = True
            console.print("[green]✓ Edit approved for this file[/green]\n")
        elif response == 'always':
            approved = True
            console.print("[green]✓ All file edits approved for this session[/green]\n")
        elif response == 'never':
            approved = False
            response = 'never'
            console.print("[yellow]✗ All file edits blocked for this session[/yellow]\n")
        else:  # 'no', 'n'
            approved = False
            response = 'n'
            console.print("[yellow]✗ Edit denied for this file[/yellow]\n")

        return (approved, response)

    except (KeyboardInterrupt, EOFError):
        # User cancelled - deny for safety
        console.print("\n[yellow]✗ Edit cancelled[/yellow]\n")
        return (False, 'n')


async def tui_shell_consent_handler(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """
    Handle shell command consent request in TUI (v1.11.2).

    Prompts user with options:
    - y/yes: Allow executing this command (this session)
    - n/no: Deny executing this command
    - always: Allow all shell commands (this session)
    - never: Deny all shell commands (this session)

    Args:
        command: Shell command that needs execution
        working_dir: Working directory for the command
        risk_level: Risk level classification (safe, dangerous, never)

    Returns:
        tuple: (approved: bool, response: str)
    """
    # Determine risk color
    risk_color = {
        "never": "red",
        "dangerous": "yellow",
        "safe": "green"
    }.get(risk_level, "yellow")

    console.print(f"\n[bold {risk_color}]⚠️  Shell Command Request[/bold {risk_color}]")
    console.print(f"[cyan]Command:[/cyan] {command}")
    console.print(f"[dim]Directory:[/dim] {working_dir}")
    console.print(f"[dim]Risk Level:[/dim] [{risk_color}]{risk_level.upper()}[/{risk_color}]")
    console.print("[dim]Options: y (yes), n (no), always (all commands), never (block all)[/dim]")

    try:
        # Use prompt_toolkit for input with validation
        response = await asyncio.to_thread(
            pt_prompt,
            "Allow command? ",
            validator=ConsentValidator(),
            validate_while_typing=False
        )
        response = response.strip().lower()

        # Normalize response
        if response in ['yes', 'y']:
            response = 'y'
            approved = True
            console.print("[green]✓ Command approved[/green]\n")
        elif response == 'always':
            approved = True
            console.print("[green]✓ All shell commands approved for this session[/green]\n")
        elif response == 'never':
            approved = False
            response = 'never'
            console.print("[yellow]✗ All shell commands blocked for this session[/yellow]\n")
        else:  # 'no', 'n'
            approved = False
            response = 'n'
            console.print("[yellow]✗ Command denied[/yellow]\n")

        return (approved, response)

    except (KeyboardInterrupt, EOFError):
        # User cancelled - deny for safety
        console.print("\n[yellow]✗ Command cancelled[/yellow]\n")
        return (False, 'n')


def send_coding_task(handler: 'CommandHandler', task_type: str, user_message: str, model: str, provider: str = None) -> Optional[str]:
    """Send a coding task with appropriate system prompt and optional auto-routing.

    v1.12.0: Updated to use handler.auto_route and engine client.
    """
    if task_type not in CODING_PROMPTS:
        console.print(f"[red]Unknown task type: {task_type}[/red]")
        return None

    # Auto-route to coding model if enabled (use provider-specific coding model)
    coding_model = get_coding_model(provider)
    if handler.auto_route and model != coding_model:
        model = coding_model
        console.print(f"[dim]Auto-routed to {coding_model} for coding task (disable with /autoroute off)[/dim]")

    # Create a temporary message with system instruction
    system_prompt = CODING_PROMPTS[task_type]
    full_message = f"{system_prompt}\n\n{user_message}"

    # v1.12.0: Use engine client for coding tasks
    import asyncio
    from .engine.types import EventType
    from .markdown_tables import render_markdown_with_tables

    async def run_coding_task():
        content = ""
        # Temporarily switch model for coding task if auto-routed
        original_model = handler.engine_client.model
        if model != original_model:
            handler.engine_client.set_model(model)

        try:
            async for event in handler.engine_client.chat(full_message, stream=True):
                if event.type == EventType.STREAM_CHUNK:
                    chunk = event.data
                    console.print(chunk, end="")
                    content += chunk
                elif event.type == EventType.ERROR:
                    console.print(f"\n[red]Error: {event.data}[/red]")
        finally:
            # Restore original model
            if model != original_model:
                handler.engine_client.set_model(original_model)

        # Render final content with markdown
        if content:
            console.print()  # New line after streaming
        return content

    return asyncio.run(run_coding_task())


class CommandHandler:
    """Handles all slash commands for the application."""

    def __init__(self, client_or_api_key, api_key_or_model: str = None, current_model_or_base_url: str = None, base_url_or_provider: str = None, provider_or_none: str = None):
        """Initialize CommandHandler.

        v1.12.0: Supports both old and new signatures for backward compatibility.

        New signature (v1.12.0+):
            CommandHandler(api_key, current_model, base_url=None, provider=None)

        Legacy signature (deprecated):
            CommandHandler(client, api_key, current_model, base_url, provider)
            The client parameter is ignored - all operations use EngineClient.
        """
        from ppxai.config import get_default_provider, get_base_url

        # Detect signature based on first argument type
        # If first arg is a string, it's the new signature (api_key first)
        # If first arg is not a string, it's the old signature (client first)
        if isinstance(client_or_api_key, str):
            # New signature: (api_key, current_model, base_url, provider)
            self.api_key = client_or_api_key
            self.current_model = api_key_or_model
            base_url = current_model_or_base_url
            provider = base_url_or_provider
        else:
            # Legacy signature: (client, api_key, current_model, base_url, provider)
            # client is ignored in v1.12.0
            self.api_key = api_key_or_model
            self.current_model = current_model_or_base_url
            base_url = base_url_or_provider
            provider = provider_or_none
        # v1.11.2.2: Use configurable default provider instead of hardcoded "perplexity"
        actual_provider = provider or get_default_provider()
        self.provider = actual_provider
        self.base_url = base_url or get_base_url(actual_provider)
        self.tools_verbose = False  # v1.11.1: Verbose tool execution logging

        # v1.12.0: EngineClient is REQUIRED for all operations
        # No legacy client fallback - engine handles everything
        from ppxai.engine import EngineClient
        import os

        # Create engine client with consent callbacks
        self.engine_client = EngineClient(
            consent_callback=tui_consent_handler,
            shell_consent_callback=tui_shell_consent_handler
        )
        self.engine_client.set_provider(self.provider)
        self.engine_client.set_model(self.current_model)
        # Set working directory for context injection
        self.engine_client.set_working_dir(os.getcwd())

        # v1.12.0: tools_available is always True (engine has builtin tools)
        self.tools_available = True

        # v1.12.0: auto_route flag is now on engine client
        # Default to enabled for coding task auto-routing
        self.auto_route = True

        # v1.12.0: TUI theme support - load from config
        from ppxai.config import get_tui_theme
        try:
            config_theme = get_tui_theme()
            self.current_theme_name = config_theme
            self.theme = get_theme(config_theme)
        except ValueError:
            # Fallback to default if config theme is invalid
            self.current_theme_name = DEFAULT_THEME
            self.theme = get_theme(DEFAULT_THEME)

        # v1.12.1: Emoji mode - convert emojis to text symbols for panel alignment
        # True = show original emojis (may cause misalignment in some terminals)
        # False = convert emojis to text symbols (guaranteed alignment)
        self.emoji_mode = False  # Default: text symbols for reliable alignment

        # v1.12.1: Initialize logger for agent mode event handling
        from ppxai.common.logger import get_logger
        self.logger = get_logger("tui")

    def handle_quit(self) -> bool:
        """Handle /quit or /exit command. Returns True if should exit."""
        # v1.12.0: Use engine session for conversation history
        if self.engine_client.session.messages:
            try:
                self.engine_client.session.save()
                console.print(f"[dim]Session saved: {self.engine_client.session.session_name}[/dim]")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not save session: {e}[/yellow]")

        # v1.12.3: Save usage to persistent storage for time-based analytics
        try:
            self.engine_client.session.save_usage_to_persistent_storage()
        except Exception as e:
            # Non-critical - don't fail on usage persistence errors
            pass

        console.print("\n[yellow]Goodbye![/yellow]")
        return True

    def handle_save(self, args: str):
        """Handle /save command - saves session to JSON."""
        try:
            # v1.12.0: Use engine session for save
            session_name = self.engine_client.session.save()
            filepath = self.engine_client.session.sessions_dir / f"{session_name}.json"
            console.print(f"\n[green]Session saved to:[/green] {filepath}\n")
        except Exception as e:
            console.print(f"[red]Error saving session: {e}[/red]\n")

    def handle_export(self, args: str):
        """Handle /export command - exports last answer to markdown."""
        try:
            # v1.12.0: Use engine session for conversation history
            last_assistant_msg = None
            for msg in reversed(self.engine_client.session.messages):
                if msg.role == 'assistant':
                    last_assistant_msg = msg.content
                    break

            if not last_assistant_msg:
                console.print("[yellow]No assistant response to export yet.[/yellow]\n")
                return

            # Generate filename with timestamp
            filename = args.strip() if args else None
            if not filename:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"answer_{timestamp}.md"

            if not filename.endswith('.md'):
                filename += '.md'

            # v1.12.0: Use engine session's exports directory
            filepath = self.engine_client.session.exports_dir / filename

            # Write content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(last_assistant_msg)

            console.print(f"\n[green]Answer exported to:[/green] {filepath}\n")
        except Exception as e:
            console.print(f"[red]Error exporting answer: {e}[/red]\n")

    def handle_sessions(self):
        """Handle /sessions command."""
        # v1.12.0: Use engine session for listing sessions
        sessions = self.engine_client.session.list_sessions()
        # Convert SessionInfo objects to dicts for display function
        session_dicts = [
            {
                "name": s.name,
                "created_at": s.created_at,
                "saved_at": s.saved_at,
                "provider": s.provider,
                "model": s.model,
                "message_count": s.message_count
            }
            for s in sessions
        ]
        display_sessions(session_dicts)

    def handle_load(self, args: str):
        """Handle /load command."""
        if not args:
            console.print("[red]Please specify a session name: /load <session_name>[/red]\n")
            sessions = self.engine_client.session.list_sessions()
            session_dicts = [
                {
                    "name": s.name,
                    "created_at": s.created_at,
                    "saved_at": s.saved_at,
                    "provider": s.provider,
                    "model": s.model,
                    "message_count": s.message_count
                }
                for s in sessions
            ]
            display_sessions(session_dicts)
            return

        try:
            # v1.12.0: Use engine session for loading
            if self.engine_client.session.load(args.strip()):
                self.current_model = self.engine_client.session.metadata.get("model", self.current_model)
                # Update engine client model
                self.engine_client.set_model(self.current_model)
                console.print(f"\n[green]Session loaded:[/green] {self.engine_client.session.session_name}")
                console.print(f"[dim]Messages: {len(self.engine_client.session.messages)}[/dim]\n")
            else:
                console.print(f"[red]Session not found: {args.strip()}[/red]\n")
        except Exception as e:
            console.print(f"[red]Error loading session: {e}[/red]\n")

    def handle_usage(self, args: str = ""):
        """Handle /usage command with sub-commands.

        Sub-commands:
            /usage              - Show session usage totals
            /usage 24h          - Show usage for last 24 hours (v1.12.3)
            /usage week         - Show usage for last 7 days (v1.12.3)
            /usage month        - Show usage for last 30 days (v1.12.3)
            /usage year         - Show usage for last 365 days (v1.12.3)
            /usage all          - Show all-time usage (v1.12.3)
            /usage show session - Status line shows session totals (default)
            /usage show provider - Status line shows current provider totals
            /usage show model   - Status line shows current model totals
            /usage show off     - Hide usage from status line
            /usage reset        - Reset all usage counters
        """
        args = args.strip().lower()

        if not args:
            # Default: show session totals with per-model breakdown
            self._display_usage_report()
            return

        parts = args.split()
        sub_command = parts[0]

        # v1.12.3: Time-based usage reports
        time_periods = {"24h", "week", "month", "year", "all"}
        if sub_command in time_periods:
            self._display_global_usage_report(sub_command)
            return

        if sub_command == "show":
            if len(parts) < 2:
                console.print("\n[yellow]Usage: /usage show <session|provider|model|off>[/yellow]")
                console.print(f"  Current mode: [cyan]{self.engine_client.session.usage_display_mode}[/cyan]\n")
                return

            mode = parts[1]
            valid_modes = {"session", "provider", "model", "off"}
            if mode not in valid_modes:
                console.print(f"\n[red]Invalid mode: {mode}[/red]")
                console.print(f"  Valid modes: {', '.join(valid_modes)}\n")
                return

            if self.engine_client.session.set_usage_display_mode(mode):
                mode_descriptions = {
                    "session": "session totals",
                    "provider": f"current provider ({self.provider}) totals",
                    "model": f"current model ({self.current_model}) totals",
                    "off": "hidden"
                }
                console.print(f"\n[green]Usage display set to: {mode_descriptions[mode]}[/green]\n")
            else:
                console.print(f"\n[red]Failed to set display mode[/red]\n")

        elif sub_command == "reset":
            self.engine_client.session.reset_usage()
            console.print("\n[green]Usage counters reset to zero.[/green]\n")

        else:
            console.print(f"\n[red]Unknown sub-command: {sub_command}[/red]")
            console.print("  Available: 24h, week, month, year, all, show, reset\n")

    def _display_usage_report(self):
        """Display detailed usage report with per-model breakdown."""
        from rich.table import Table

        usage = self.engine_client.session.get_usage()

        # Session totals
        console.print()
        console.print("[bold cyan]Session Usage Statistics[/bold cyan]")
        console.print(f"  Total tokens: {usage['total_tokens']:,} ({usage['prompt_tokens']:,}↓ / {usage['completion_tokens']:,}↑)")
        console.print(f"  Estimated cost: ${usage['estimated_cost']:.4f}")

        # Per-model breakdown if available
        by_model = usage.get("by_model", {})
        if by_model:
            console.print()
            table = Table(title="Usage by Model", show_header=True, header_style="bold magenta")
            table.add_column("Provider", style="cyan")
            table.add_column("Model", style="cyan")
            table.add_column("In", justify="right", style="green")
            table.add_column("Out", justify="right", style="green")
            table.add_column("Cost", justify="right", style="yellow")

            for key, stats in sorted(by_model.items()):
                parts = key.split("/", 1)
                provider = parts[0]
                model = parts[1] if len(parts) > 1 else key
                table.add_row(
                    provider,
                    model,
                    f"{stats['prompt_tokens']:,}",
                    f"{stats['completion_tokens']:,}",
                    f"${stats['estimated_cost']:.4f}"
                )

            # Add totals row
            table.add_row(
                "[bold]TOTAL[/bold]",
                "",
                f"[bold]{usage['prompt_tokens']:,}[/bold]",
                f"[bold]{usage['completion_tokens']:,}[/bold]",
                f"[bold]${usage['estimated_cost']:.4f}[/bold]"
            )

            console.print(table)

        # v1.13.4: Tool usage breakdown
        tool_calls = usage.get("tool_calls", {})
        if tool_calls:
            console.print()
            tool_table = Table(title="Tool Usage", show_header=True, header_style="bold magenta")
            tool_table.add_column("Tool", style="cyan")
            tool_table.add_column("Provider", style="cyan")
            tool_table.add_column("Calls", justify="right", style="green")
            tool_table.add_column("Tokens In", justify="right", style="green")
            tool_table.add_column("Tokens Out", justify="right", style="green")
            tool_table.add_column("Cost", justify="right", style="yellow")

            total_tool_cost = 0.0
            for tool_name, tool_stats in sorted(tool_calls.items()):
                provider = tool_stats.get("provider", "unknown")
                tool_table.add_row(
                    tool_name,
                    provider.title() if provider != "duckduckgo" else "DuckDuckGo",
                    f"{tool_stats.get('call_count', 0)}",
                    f"{tool_stats.get('tokens_in', 0):,}",
                    f"{tool_stats.get('tokens_out', 0):,}",
                    f"${tool_stats.get('estimated_cost', 0.0):.4f}"
                )
                total_tool_cost += tool_stats.get('estimated_cost', 0.0)

            console.print(tool_table)
            total_cost = usage['estimated_cost'] + total_tool_cost
            console.print(f"\n[bold cyan]Total Session Cost:[/bold cyan] [bold yellow]${total_cost:.4f}[/bold yellow]")
            console.print(f"  Model cost: ${usage['estimated_cost']:.4f}")
            console.print(f"  Tool cost: ${total_tool_cost:.4f}")
        else:
            console.print(f"\n[bold cyan]Total Session Cost:[/bold cyan] [bold yellow]${usage['estimated_cost']:.4f}[/bold yellow]")

        # Display mode
        display_mode = usage.get("display_mode", "session")
        console.print(f"\n  Status line display: [cyan]{display_mode}[/cyan]")
        console.print("  (Change with /usage show <session|provider|model|off>)\n")

    def _display_global_usage_report(self, period: str):
        """Display usage report for a time period (v1.12.3).

        Args:
            period: One of "24h", "week", "month", "year", "all"
        """
        from rich.table import Table
        from .usage import get_usage_report

        report = get_usage_report(period)

        # Header with period info
        period_labels = {
            "24h": "Last 24 Hours",
            "week": "Last 7 Days",
            "month": "Last 30 Days",
            "year": "Last 365 Days",
            "all": "All Time"
        }
        console.print()
        console.print(f"[bold cyan]Usage Report: {period_labels.get(period, period)}[/bold cyan]")

        if report["start_date"]:
            console.print(f"[dim]Period: {report['start_date']} to {report['end_date']}[/dim]")
        else:
            console.print(f"[dim]Period: All recorded sessions[/dim]")

        # Summary stats
        console.print(f"\n  Sessions: [cyan]{report['session_count']}[/cyan]")
        console.print(f"  Total tokens: [cyan]{report['total_tokens']:,}[/cyan]")
        console.print(f"  Estimated cost: [yellow]${report['total_cost']:.4f}[/yellow]")

        # By provider breakdown
        by_provider = report.get("by_provider", {})
        if by_provider:
            console.print()
            table = Table(title="By Provider", show_header=True, header_style="bold magenta")
            table.add_column("Provider", style="cyan")
            table.add_column("Tokens", justify="right", style="green")
            table.add_column("Cost", justify="right", style="yellow")
            table.add_column("Sessions", justify="right", style="dim")

            for provider, stats in sorted(by_provider.items()):
                table.add_row(
                    provider,
                    f"{stats['total_tokens']:,}",
                    f"${stats['estimated_cost']:.4f}",
                    str(stats['session_count'])
                )

            console.print(table)

        # By model breakdown
        by_model = report.get("by_model", {})
        if by_model:
            console.print()
            table = Table(title="By Model", show_header=True, header_style="bold magenta")
            table.add_column("Provider", style="cyan")
            table.add_column("Model", style="cyan")
            table.add_column("In", justify="right", style="green")
            table.add_column("Out", justify="right", style="green")
            table.add_column("Cost", justify="right", style="yellow")

            for key, stats in sorted(by_model.items()):
                parts = key.split("/", 1)
                provider = parts[0]
                model = parts[1] if len(parts) > 1 else key
                table.add_row(
                    provider,
                    model,
                    f"{stats['prompt_tokens']:,}",
                    f"{stats['completion_tokens']:,}",
                    f"${stats['estimated_cost']:.4f}"
                )

            console.print(table)

        # Recent sessions (limit to 5)
        sessions = report.get("sessions", [])[:5]
        if sessions:
            console.print()
            console.print("[bold]Recent Sessions:[/bold]")
            for s in sessions:
                ended = s.get("ended_at", "")[:16].replace("T", " ")
                console.print(f"  [dim]{ended}[/dim] - {s.get('total_tokens', 0):,} tokens, ${s.get('total_cost', 0):.4f}")

        console.print()

    def handle_clear(self):
        """Handle /clear command."""
        # v1.12.0: Use engine session for clear
        self.engine_client.session.clear()
        console.print("\n[green]Conversation history cleared.[/green]\n")

    def handle_model(self, args: str = ""):
        """Handle /model command."""
        args = args.strip().lower()

        if args == "list":
            # List available models
            from .config import get_provider_config
            config = get_provider_config(self.provider)
            models = config.get("models", {})

            console.print(f"\n[bold cyan]Available Models ({self.provider}):[/bold cyan]")
            for num, info in models.items():
                model_id = info.get("id", num)
                is_current = " [green]✓[/green]" if model_id == self.current_model else ""
                console.print(f"  • [bold]{model_id}[/bold]{is_current} - {info.get('description', '')}")
            console.print()
        elif args:
            # Direct model selection by ID
            from .config import get_provider_config
            config = get_provider_config(self.provider)
            models = config.get("models", {})

            # Find model by ID
            found = False
            for num, info in models.items():
                model_id = info.get("id", num)
                if model_id == args:
                    self.current_model = model_id
                    # v1.12.0: Update engine client and session
                    self.engine_client.set_model(self.current_model)
                    self.engine_client.session.set_model(self.current_model)
                    console.print(f"[green]✓ Switched to model: {model_id}[/green]\n")
                    found = True
                    break

            if not found:
                console.print(f"[red]Model not found: {args}[/red]")
                console.print("[dim]Use /model list to see available models[/dim]\n")
        else:
            # Interactive selection
            self.current_model = select_model(self.provider)
            # v1.12.0: Update engine client and session
            self.engine_client.set_model(self.current_model)
            self.engine_client.session.set_model(self.current_model)
            console.print()

    def handle_provider(self, args: str = ""):
        """Handle /provider command - switch between providers."""
        args = args.strip().lower()

        if args == "list":
            # List available providers
            console.print(f"\n[bold cyan]Available Providers:[/bold cyan]")
            for provider_id, config in PROVIDERS.items():
                has_key = bool(get_api_key(provider_id))
                is_current = " [green]✓[/green]" if provider_id == self.provider else ""
                key_status = "" if has_key else " [dim](no API key)[/dim]"
                console.print(f"  • [bold]{provider_id}[/bold]{is_current} - {config.get('name', provider_id)}{key_status}")
            console.print()
            return

        if args and args != "list":
            # Direct provider selection by ID
            if args not in PROVIDERS:
                console.print(f"[red]Provider not found: {args}[/red]")
                console.print("[dim]Use /provider list to see available providers[/dim]\n")
                return

            new_provider = args
        else:
            # Interactive selection
            console.print(f"\n[cyan]Current provider:[/cyan] {self.provider}")
            new_provider = select_provider()

        if new_provider == self.provider:
            console.print("[dim]Same provider selected, no change needed.[/dim]\n")
            return

        # Check if new provider has API key configured
        new_api_key = get_api_key(new_provider)
        if not new_api_key:
            config = get_provider_config(new_provider)
            console.print(f"[red]Error: {config['api_key_env']} not configured.[/red]")
            console.print("[yellow]Please add the API key to your .env file.[/yellow]\n")
            return

        # v1.12.0: Check if tools are currently enabled
        tools_were_enabled = self.engine_client.tools_enabled

        # Switch to new provider
        new_base_url = get_base_url(new_provider)
        new_config = get_provider_config(new_provider)

        # v1.12.0: Update engine client with new provider (engine only)
        self.api_key = new_api_key
        self.base_url = new_base_url
        self.provider = new_provider
        self.engine_client.set_provider(new_provider)
        self.engine_client.session.set_provider(new_provider)

        # Select model for new provider (auto-select default if direct switch)
        if args:
            self.current_model = new_config.get("default_model", "")
        else:
            self.current_model = select_model(new_provider)
        self.engine_client.set_model(self.current_model)
        self.engine_client.session.set_model(self.current_model)

        console.print(f"\n[green]Switched to:[/green] {new_config['name']} (model: {self.current_model})")

        # Re-enable tools if they were enabled before switching
        if tools_were_enabled:
            console.print("[dim]Re-enabling tools for new provider...[/dim]")
            self._enable_tools()
        else:
            console.print()

    def handle_help(self):
        """Handle /help command."""
        display_welcome()

    def handle_theme(self, args: str):
        """Handle /theme command for switching TUI themes and emoji mode.

        Usage:
            /theme              - List available themes and settings
            /theme list         - List available themes
            /theme <name>       - Switch to named theme
            /theme emoji        - Show current emoji mode
            /theme emoji on     - Show original emojis (may cause panel misalignment)
            /theme emoji off    - Convert emojis to text symbols (reliable alignment)
        """
        args = args.strip().lower() if args else ""

        # Handle emoji subcommand
        if args.startswith("emoji"):
            emoji_args = args[5:].strip()  # Get text after "emoji"

            if not emoji_args:
                # Show current emoji mode
                mode = "on (original emojis)" if self.emoji_mode else "off (text symbols)"
                console.print(f"[cyan]Emoji mode:[/cyan] {mode}")
                console.print("[dim]Use /theme emoji on|off to change[/dim]\n")
                return

            if emoji_args == "on":
                self.emoji_mode = True
                console.print("[green]* Emoji mode: ON[/green]")
                console.print("[dim]Original emojis will be shown (may cause panel misalignment in some terminals)[/dim]\n")
            elif emoji_args == "off":
                self.emoji_mode = False
                console.print("[green]* Emoji mode: OFF[/green]")
                console.print("[dim]Emojis converted to text symbols for reliable panel alignment[/dim]\n")
            else:
                console.print("[red]Invalid option. Use: /theme emoji on|off[/red]\n")
            return

        if not args or args == "list":
            # Show available themes and current settings
            console.print(render_theme_list(self.current_theme_name))
            emoji_status = "on" if self.emoji_mode else "off"
            console.print(f"[dim]Emoji mode: {emoji_status}[/dim]")
            console.print("[dim]Usage: /theme <name> | /theme emoji on|off[/dim]\n")
            return

        # Try to switch to the specified theme
        try:
            new_theme = get_theme(args)
            self.theme = new_theme
            self.current_theme_name = args
            console.print(f"[green]* Theme switched to: {new_theme.name}[/green]\n")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            console.print("[dim]Use /theme list to see available themes[/dim]\n")

    def handle_generate(self, args: str):
        """Handle /generate command."""
        if not args:
            console.print("[red]Please provide a description: /generate <description>[/red]")
            console.print("[yellow]Example: /generate a function to validate email addresses in Python[/yellow]\n")
            return

        console.print(f"\n[cyan]Generating code for:[/cyan] {args}\n")
        send_coding_task(self, "generate", args, self.current_model, self.provider)

    def handle_test(self, args: str):
        """Handle /test command."""
        if not args:
            console.print("[red]Please provide a file path: /test <file>[/red]")
            console.print("[yellow]Example: /test ./src/utils.py[/yellow]\n")
            return

        file_content = read_file_content(args.strip())
        if file_content:
            console.print(f"\n[cyan]Generating tests for:[/cyan] {args}\n")
            task_message = f"Generate comprehensive unit tests for the following code:\n\n```\n{file_content}\n```"
            send_coding_task(self, "test", task_message, self.current_model, self.provider)

    def handle_docs(self, args: str):
        """Handle /docs command."""
        if not args:
            console.print("[red]Please provide a file path: /docs <file>[/red]")
            console.print("[yellow]Example: /docs ./src/api.py[/yellow]\n")
            return

        file_content = read_file_content(args.strip())
        if file_content:
            console.print(f"\n[cyan]Generating documentation for:[/cyan] {args}\n")
            task_message = f"Generate comprehensive documentation for the following code:\n\n```\n{file_content}\n```"
            send_coding_task(self, "docs", task_message, self.current_model, self.provider)

    def handle_implement(self, args: str):
        """Handle /implement command."""
        if not args:
            console.print("[red]Please provide a feature specification: /implement <specification>[/red]")
            console.print("[yellow]Example: /implement a REST API endpoint for user authentication[/yellow]")
            console.print("[cyan]Tip: Use /spec to see specification guidelines and templates[/cyan]\n")
            return

        console.print(f"\n[cyan]Implementing feature:[/cyan] {args}\n")
        send_coding_task(self, "implement", args, self.current_model, self.provider)

    def handle_debug(self, args: str):
        """Handle /debug command."""
        if not args:
            console.print("[red]Please provide error details or paste your error message/stack trace[/red]")
            console.print("[yellow]Example: /debug TypeError: 'NoneType' object is not subscriptable at line 42[/yellow]\n")
            return

        console.print(f"\n[cyan]Analyzing error:[/cyan] {args[:100]}...\n")
        send_coding_task(self, "debug", args, self.current_model, self.provider)

    def handle_explain(self, args: str):
        """Handle /explain command."""
        if not args:
            console.print("[red]Please provide a file path: /explain <file>[/red]")
            console.print("[yellow]Example: /explain ./src/algorithm.py[/yellow]\n")
            return

        file_content = read_file_content(args.strip())
        if file_content:
            console.print(f"\n[cyan]Explaining code:[/cyan] {args}\n")
            task_message = f"Explain the following code in detail, including logic, design decisions, and how it works:\n\n```\n{file_content}\n```"
            send_coding_task(self, "explain", task_message, self.current_model, self.provider)

    def handle_convert(self, args: str):
        """Handle /convert command."""
        if not args:
            console.print("[red]Please provide: /convert <source-lang> <target-lang> <file-or-code>[/red]")
            console.print("[yellow]Example: /convert python javascript ./utils.py[/yellow]")
            console.print("[yellow]Example: /convert go rust 'func hello() { fmt.Println(\"Hi\") }'[/yellow]\n")
            return

        parts = args.split(maxsplit=2)
        if len(parts) < 3:
            console.print("[red]Invalid format. Use: /convert <source-lang> <target-lang> <file-or-code>[/red]\n")
            return

        source_lang, target_lang, code_or_file = parts

        # Check if it's a file or inline code
        if os.path.exists(code_or_file.strip('\'"')):
            file_content = read_file_content(code_or_file.strip('\'"'))
            if not file_content:
                return
            code_to_convert = file_content
        else:
            code_to_convert = code_or_file.strip('\'"')

        console.print(f"\n[cyan]Converting from {source_lang} to {target_lang}[/cyan]\n")
        task_message = f"Convert the following {source_lang} code to {target_lang}:\n\n```{source_lang}\n{code_to_convert}\n```"
        send_coding_task(self, "convert", task_message, self.current_model, self.provider)

    def handle_autoroute(self, args: str):
        """Handle /autoroute command."""
        coding_model = get_coding_model(self.provider)

        if not args:
            # v1.12.0: Use self.auto_route instead of legacy client
            status = "enabled" if self.auto_route else "disabled"
            console.print(f"\n[cyan]Auto-routing is currently:[/cyan] [bold]{status}[/bold]")
            console.print(f"[dim]Auto-routing uses {coding_model} for coding commands[/dim]")
            console.print("[yellow]Use /autoroute on or /autoroute off to change[/yellow]\n")
            return

        arg = args.strip().lower()
        if arg == "on":
            self.auto_route = True
            console.print(f"[green]Auto-routing enabled.[/green] Coding commands will use {coding_model}\n")
        elif arg == "off":
            self.auto_route = False
            console.print(f"[yellow]Auto-routing disabled.[/yellow] Manual model selection will be used\n")
        else:
            console.print("[red]Invalid option. Use /autoroute on or /autoroute off[/red]\n")

    def handle_spec(self, args: str):
        """Handle /spec command."""
        spec_type = args.strip().lower() if args else None
        display_spec_help(spec_type)

    def handle_tools(self, args: str):
        """Handle /tools command."""
        if not self.tools_available:
            console.print("[red]Error: Tool support not available.[/red]")
            console.print("[yellow]Missing dependencies. Check docs/TOOL_CREATION_GUIDE.md[/yellow]\n")
            return

        parts = args.strip().split() if args else []
        subcommand = parts[0].lower() if parts else "status"
        subargs = parts[1:] if len(parts) > 1 else []

        if subcommand in ("enable", "on"):
            self._enable_tools()
        elif subcommand in ("disable", "off"):
            self._disable_tools()
        elif subcommand == "list":
            self._list_tools()
        elif subcommand == "status":
            self._tools_status()
        elif subcommand == "config":
            self._tools_config(subargs)
        elif subcommand == "set":
            self._tools_set(subargs)
        elif subcommand == "help":
            if subargs:
                if subargs[0] == "editing":
                    display_file_editing_help()
                else:
                    # Show help for specific tool
                    self._show_tool_help(subargs[0])
            else:
                console.print("[yellow]Tool Help[/yellow]")
                console.print("[dim]Usage: /tools help <tool-name>  - Show help for a specific tool[/dim]")
                console.print("[dim]       /tools help editing      - Show file editing guide[/dim]\n")
        elif subcommand == "agent":
            # Agent mode control (v1.11.8)
            self._tools_agent(subargs)
        else:
            console.print(f"[red]Unknown subcommand: {subcommand}[/red]")
            console.print("[yellow]Available: on, off, list, status, config, set, help, agent[/yellow]\n")

    def _enable_tools(self):
        """Enable AI tools (including file editing tools with consent)."""
        # v1.11.4: Simplified - EngineClient already exists, just enable tools
        if not self.engine_client:
            console.print("[red]Error: Engine client not available[/red]\n")
            return

        if self.engine_client.tools_enabled:
            console.print("[yellow]Tools already enabled[/yellow]\n")
            return

        # v1.12.0: Enable tools in engine client only (no legacy client upgrade)
        console.print("[cyan]Enabling tools...[/cyan]")
        self.engine_client.enable_tools()

        console.print("[green]✓ Tools enabled![/green]")
        console.print("[dim]Includes file editing tools (apply_patch, replace_block, insert_text, delete_lines)[/dim]")
        console.print("[dim]Use '/tools list' to see available tools[/dim]\n")

    def _disable_tools(self):
        """Disable AI tools."""
        # v1.12.0: Engine only - no legacy client downgrade
        if not self.engine_client:
            console.print("[red]Error: Engine client not available[/red]\n")
            return

        if not self.engine_client.tools_enabled:
            console.print("[yellow]Tools not enabled[/yellow]\n")
            return

        # Disable tools in engine client (but keep engine client alive for @git/@tree)
        self.engine_client.disable_tools()
        console.print("[yellow]Tools disabled[/yellow]\n")

    def _list_tools(self):
        """List available tools."""
        # v1.12.0: Engine only
        if not self.engine_client or not self.engine_client.tools_enabled:
            console.print("[yellow]Tools not enabled. Use '/tools enable' first[/yellow]\n")
            return

        # Show engine tools (unified across all providers)
        if self.engine_client.tool_manager:
            engine_tools = self.engine_client.tool_manager.list_tools()
            if engine_tools:
                display_tools_table(engine_tools)
            else:
                console.print("[yellow]No tools available[/yellow]\n")

    def _tools_status(self):
        """Show tools status."""
        # v1.12.0: Engine only
        if self.engine_client and self.engine_client.tools_enabled:
            # Get tool count from engine
            tool_count = 0
            if self.engine_client.tool_manager:
                try:
                    tool_count = len(self.engine_client.tool_manager.list_tools())
                except Exception:
                    pass

            console.print(f"[green]✓ Tools enabled[/green] ({tool_count} tools available)")

            # Show consent mode
            try:
                consent_mode = self.engine_client.session.edit_consent_mode
                console.print(f"[dim]Consent mode: {consent_mode}[/dim]")
            except Exception:
                pass

            # v1.13.4: Show web search provider
            try:
                from ppxai.engine.tools.builtin import web_premium
                if web_premium.is_available():
                    provider = web_premium.get_premium_search_provider(self.provider)
                    if provider:
                        console.print(f"[dim]Web Search: {provider.title()} (premium)[/dim]")
                    else:
                        console.print(f"[dim]Web Search: DuckDuckGo (free)[/dim]")
                else:
                    console.print(f"[dim]Web Search: DuckDuckGo (free)[/dim]")
            except Exception:
                console.print(f"[dim]Web Search: DuckDuckGo (free)[/dim]")

            console.print("[dim]Use '/tools list' to see available tools[/dim]\n")
        else:
            console.print("[yellow]Tools not enabled[/yellow]")
            console.print("[dim]Use '/tools enable' to activate AI tools[/dim]\n")

    def _tools_config(self, args: list):
        """Configure tool settings."""
        # v1.12.0: Engine only
        if not self.engine_client or not self.engine_client.tools_enabled:
            console.print("[yellow]Tools not enabled. Use '/tools enable' first[/yellow]\n")
            return

        if not args:
            # Show current config
            max_iter = getattr(self.engine_client, 'tool_max_iterations', 15)
            console.print("[bold]Tool Configuration[/bold]")
            console.print(f"  max_iterations: {max_iter}")
            console.print()
            console.print("[dim]Usage: /tools config <setting> <value>[/dim]")
            console.print("[dim]Available settings:[/dim]")
            console.print("[dim]  max_iterations <number> - Max tool calls per query (1-50)[/dim]\n")
            return

        if len(args) < 2:
            console.print("[red]Usage: /tools config <setting> <value>[/red]\n")
            return

        setting = args[0].lower()
        value = args[1]

        if setting == "max_iterations":
            try:
                num = int(value)
                if num < 1 or num > 50:
                    console.print("[red]max_iterations must be between 1 and 50[/red]\n")
                    return
                self.engine_client.tool_max_iterations = num
                console.print(f"[green]✓ max_iterations set to {num}[/green]\n")
            except ValueError:
                console.print(f"[red]Invalid number: {value}[/red]\n")
        else:
            console.print(f"[red]Unknown setting: {setting}[/red]")
            console.print("[dim]Available: max_iterations[/dim]\n")

    def _tools_set(self, args: list):
        """Set tool settings (verbose mode)."""
        if not args:
            # Show current settings
            verbose_status = "enabled" if self.tools_verbose else "disabled"
            console.print("[bold]Tool Settings[/bold]")
            console.print(f"  verbose: {verbose_status}")
            console.print()
            console.print("[dim]Usage: /tools set <setting> <value>[/dim]")
            console.print("[dim]Available settings:[/dim]")
            console.print("[dim]  verbose on/off - Show tool inputs and outputs[/dim]\n")
            return

        if len(args) < 2:
            console.print("[red]Usage: /tools set <setting> <value>[/red]\n")
            return

        setting = args[0].lower()
        value = args[1].lower()

        if setting == "verbose":
            if value in ["on", "true", "1", "yes"]:
                self.tools_verbose = True
                console.print("[green]✓ Verbose tool logging enabled[/green]")
                console.print("[dim]Tool inputs and outputs will be displayed during execution[/dim]\n")
            elif value in ["off", "false", "0", "no"]:
                self.tools_verbose = False
                console.print("[yellow]Verbose tool logging disabled[/yellow]\n")
            else:
                console.print(f"[red]Invalid value: {value}[/red]")
                console.print("[dim]Use: on, off, true, false, 1, 0, yes, or no[/dim]\n")
        else:
            console.print(f"[red]Unknown setting: {setting}[/red]")
            console.print("[dim]Available: verbose[/dim]\n")

    def _tools_agent(self, args: list):
        """Control agent mode for autonomous task execution (v1.11.8)."""
        if not self.engine_client:
            console.print("[red]Error: Engine client not available[/red]\n")
            return

        if not args:
            # Show current agent mode status
            status = "[green]ON[/green]" if self.engine_client.agent_mode else "[dim]OFF[/dim]"
            console.print(f"[bold]Agent Mode:[/bold] {status}")
            console.print("[dim]Usage: /tools agent on|off[/dim]")
            console.print("[dim]       /agent <task>  - Run autonomous task[/dim]\n")
            return

        action = args[0].lower()
        if action in ["on", "enable"]:
            self.engine_client.enable_agent_mode()
            console.print("[green]Agent mode enabled[/green]")
            console.print("[dim]Tools auto-enabled. Use '/agent <task>' to start autonomous execution.[/dim]\n")
        elif action in ["off", "disable"]:
            self.engine_client.disable_agent_mode()
            console.print("[yellow]Agent mode disabled[/yellow]\n")
        else:
            console.print(f"[red]Unknown action: {action}[/red]")
            console.print("[yellow]Usage: /tools agent on|off[/yellow]\n")

    def _show_tool_help(self, tool_name: str):
        """Show detailed help for a specific tool.

        Args:
            tool_name: Name of the tool to show help for
        """
        if not self.engine_client or not self.engine_client.tools_enabled:
            console.print("[yellow]Tools not enabled. Use '/tools enable' first[/yellow]\n")
            return

        if not self.engine_client.tool_manager:
            console.print("[red]Tool manager not available[/red]\n")
            return

        # Get the tool
        tool = self.engine_client.tool_manager.get_tool(tool_name)
        if not tool:
            # Tool not found - show available tools
            available_tools = self.engine_client.tool_manager.list_tools()
            tool_names = [t['name'] for t in available_tools]

            console.print(f"[red]Tool not found: {tool_name}[/red]")
            console.print("[dim]Available tools:[/dim]")
            for name in sorted(tool_names):
                console.print(f"[dim]  - {name}[/dim]")
            console.print()
            return

        # Get tool definition and display help
        tool_info = tool.get_definition()
        display_tool_help(tool_name, tool_info)

    def handle_debug_log(self, args: str):
        """Handle /debug-log command to enable/disable debug logging."""
        # v1.12.1: Use common logger (same as main.py) to fix logging mismatch
        from ppxai.common.logger import get_logger
        from pathlib import Path

        logger = get_logger("tui")

        if not args:
            # Show status
            status = "enabled" if logger.enabled else "disabled"
            log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
            console.print(f"\n[bold]Debug Logging Status:[/bold] {status}")
            if logger.enabled:
                console.print(f"[dim]Log file: {log_file}[/dim]")
                console.print("[dim]Use '/debug-log off' to disable[/dim]\n")
            else:
                console.print(f"[dim]Log file: {log_file}[/dim]")
                console.print("[dim]Use '/debug-log on' to enable[/dim]")
                console.print("[dim]Or set PPXAI_DEBUG=1 environment variable[/dim]\n")
            return

        cmd = args.strip().lower()

        if cmd in ["on", "enable", "1", "true", "yes"]:
            logger.enable()
            log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
            console.print("[green]✓ Debug logging enabled[/green]")
            console.print(f"[dim]Logs will be written to: {log_file}[/dim]")
            console.print("[dim]All message flow, API requests, and tool executions will be logged[/dim]\n")
        elif cmd in ["off", "disable", "0", "false", "no"]:
            logger.disable()
            console.print("[yellow]Debug logging disabled[/yellow]\n")
        elif cmd in ["show", "view", "cat"]:
            # Show recent log entries
            log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
            if not log_file.exists():
                console.print("[yellow]No log file found[/yellow]\n")
                return

            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    # Show last 50 lines
                    recent_lines = lines[-50:]
                    console.print(f"\n[bold]Recent debug log entries:[/bold] (last 50 lines)\n")
                    for line in recent_lines:
                        console.print(line.rstrip())
                    console.print()
            except Exception as e:
                console.print(f"[red]Error reading log file: {e}[/red]\n")
        elif cmd in ["clear", "clean", "reset"]:
            # Clear log file
            log_file = Path.home() / '.ppxai' / 'logs' / 'tui-debug.log'
            if log_file.exists():
                log_file.unlink()
                console.print("[green]✓ Debug log cleared[/green]\n")
            else:
                console.print("[yellow]No log file to clear[/yellow]\n")
        else:
            console.print(f"[red]Unknown command: {cmd}[/red]")
            console.print("[yellow]Usage: /debug-log [on|off|show|clear][/yellow]\n")

    def _search_files(self, query: str, max_results: int = 10) -> list:
        """Search for files matching query in current directory."""
        from pathlib import Path
        import fnmatch

        # Remove @ prefix if present
        query = query.lstrip('@').strip()

        # Get search root (current working directory)
        root = Path.cwd()

        # Build search patterns
        patterns = []
        query_lower = query.lower()

        # If query looks like a path, try exact match first
        if '/' in query or '\\' in query:
            direct_path = root / query
            if direct_path.exists() and direct_path.is_file():
                return [direct_path]

        # Extract filename parts for fuzzy matching
        parts = query_lower.replace('-', ' ').replace('_', ' ').split()

        matches = []
        try:
            # Walk directory tree (skip hidden dirs and common ignore patterns)
            ignore_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', 'dist', 'build', '.eggs'}

            for path in root.rglob('*'):
                if path.is_file():
                    # Skip files in ignored directories
                    if any(ignored in path.parts for ignored in ignore_dirs):
                        continue

                    # Check if filename matches
                    filename_lower = path.name.lower()
                    path_str_lower = str(path.relative_to(root)).lower()

                    # Exact filename match
                    if query_lower == filename_lower:
                        return [path]  # Exact match, return immediately

                    # Check if all query parts are in the path
                    if all(part in path_str_lower for part in parts):
                        matches.append(path)
                    # Also check partial filename match
                    elif query_lower in filename_lower:
                        matches.append(path)

                    if len(matches) >= max_results * 2:  # Get more for sorting
                        break
        except PermissionError:
            pass

        # Sort by relevance (shorter paths and exact filename matches first)
        def score(p):
            name = p.name.lower()
            # Prefer exact filename matches
            if query_lower == name:
                return (0, len(str(p)))
            if query_lower in name:
                return (1, len(str(p)))
            return (2, len(str(p)))

        matches.sort(key=score)
        return matches[:max_results]

    def process_file_references(self, content: str) -> tuple[str, list[dict]]:
        """
        Process @filename references in a message and return augmented message with file contents.

        Returns:
            tuple: (augmented_message, list of {name, path} dicts for resolved files)
        """
        import re
        from pathlib import Path

        # Match @filename patterns (word characters, dots, hyphens, slashes)
        ref_pattern = r'@([\w.\-/]+)'
        matches = list(re.finditer(ref_pattern, content))

        if not matches:
            return content, []

        resolved_files = []
        processed_message = content

        for match in matches:
            ref = match.group(1)
            full_match = match.group(0)

            # Try to resolve the file
            files = self._search_files(ref, max_results=1)
            if files:
                file_path = files[0]
                try:
                    file_content = file_path.read_text()
                    filename = file_path.name

                    resolved_files.append({
                        'name': filename,
                        'path': str(file_path),
                        'content': file_content
                    })

                    # Replace @ref with just the filename in the message
                    processed_message = processed_message.replace(full_match, filename, 1)
                except Exception:
                    # File couldn't be read, leave reference as-is
                    pass

        if not resolved_files:
            return content, []

        # Build augmented message with file contents as context
        augmented_message = processed_message
        augmented_message += '\n\n---\n**Referenced Files:**\n'

        for f in resolved_files:
            ext = Path(f['name']).suffix.lstrip('.')
            augmented_message += f"\n**{f['name']}** (`{f['path']}`):\n```{ext}\n{f['content']}\n```\n"

        return augmented_message, [{'name': f['name'], 'path': f['path']} for f in resolved_files]

    def handle_show(self, args: str):
        """Display file contents locally without LLM call."""
        from pathlib import Path
        from rich.syntax import Syntax
        import time

        start_time = time.time()

        if not args.strip():
            console.print("[red]Usage: /show <filepath> or /show @<search-query>[/red]")
            console.print("[dim]Examples:[/dim]")
            console.print("[dim]  /show README.md[/dim]")
            console.print("[dim]  /show @architecture (searches for files)[/dim]")
            console.print("[dim]  /show docs/README.md[/dim]\n")
            return

        query = args.strip()

        # Extract @reference if present (ignore trailing words like "file", "in docs", etc.)
        import re
        at_match = re.search(r'@([\w.\-/]+)', query)
        if at_match:
            query = at_match.group(1)  # Use just the reference without @

        # Check if it's a direct path first
        direct_path = Path(query).expanduser()
        if not direct_path.is_absolute():
            direct_path = Path.cwd() / query

        if direct_path.exists() and direct_path.is_file():
            path = direct_path.resolve()
        else:
            # Search for files
            console.print(f"[dim]Searching for '{query}'...[/dim]")
            matches = self._search_files(query)

            if not matches:
                console.print(f"[red]No files found matching: {query}[/red]\n")
                return

            if len(matches) == 1:
                path = matches[0]
                console.print(f"[dim]Found: {path.relative_to(Path.cwd())}[/dim]\n")
            else:
                # Multiple matches - let user choose
                console.print(f"\n[yellow]Multiple files found ({len(matches)}):[/yellow]")
                for i, match in enumerate(matches, 1):
                    rel_path = match.relative_to(Path.cwd())
                    console.print(f"  [cyan]{i}[/cyan]. {rel_path}")

                console.print("\n[dim]Use exact path: /show <path>[/dim]\n")
                return

        if not path.is_file():
            console.print(f"[red]Not a file: {query}[/red]\n")
            return

        try:
            content = path.read_text(encoding='utf-8')
            lines = content.split('\n')

            # Detect language from extension
            ext_to_lang = {
                '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
                '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
                '.md': 'markdown', '.html': 'html', '.css': 'css',
                '.sh': 'bash', '.bash': 'bash', '.zsh': 'bash',
                '.rs': 'rust', '.go': 'go', '.java': 'java',
                '.c': 'c', '.cpp': 'cpp', '.h': 'c', '.hpp': 'cpp',
                '.rb': 'ruby', '.php': 'php', '.sql': 'sql',
                '.xml': 'xml', '.toml': 'toml', '.ini': 'ini',
            }
            lang = ext_to_lang.get(path.suffix.lower(), 'text')

            # Show file info
            size_kb = path.stat().st_size / 1024
            console.print(f"\n[bold cyan]{path.name}[/bold cyan] [dim]({size_kb:.1f} KB, {len(lines)} lines)[/dim]\n")

            # For markdown files, render them (including tables) instead of syntax highlighting
            if path.suffix.lower() in ['.md', '.markdown']:
                from .markdown_tables import render_markdown_with_tables
                # Pass the file's parent directory for resolving relative links
                render_markdown_with_tables(content, console, working_dir=str(path.parent))
            else:
                # Display with syntax highlighting (no truncation for local viewing)
                syntax = Syntax(content, lang, theme="monokai", line_numbers=True)
                console.print(syntax)

            # Show timing
            elapsed = time.time() - start_time
            console.print(f"\n[dim]({elapsed:.2f}s)[/dim]\n")

        except UnicodeDecodeError:
            console.print(f"[red]Cannot display binary file: {query}[/red]\n")
        except Exception as e:
            console.print(f"[red]Error reading file: {e}[/red]\n")

    def handle_undo(self):
        """Handle /undo command to revert last agent task (v1.12.0)."""
        if not self.engine_client:
            console.print("[red]Undo command requires engine client[/red]")
            return

        # v1.12.0: Allow undo regardless of agent mode - checkpoints from previous sessions should be undoable
        # Get checkpoint status
        status = self.engine_client.get_checkpoint_status()
        if not status.get("enabled"):
            console.print("[yellow]⚠️  Checkpoints are not enabled[/yellow]")
            console.print("[dim]Initialize a git repository to enable automatic checkpoints[/dim]\n")
            return

        last_checkpoint = status.get("last_checkpoint")
        if not last_checkpoint:
            console.print("[yellow]⚠️  No checkpoint to undo[/yellow]")
            console.print("[dim]Run an /agent task first to create a checkpoint[/dim]\n")
            return

        # v1.12.1: Check if checkpoint is still valid (not stale)
        is_valid = status.get("is_valid", True)  # Default True for backward compat
        if not is_valid:
            validity_reason = status.get("validity_reason", "Checkpoint is stale")
            console.print(f"[yellow]⚠️  Cannot undo: {validity_reason}[/yellow]")
            console.print("[dim]New commits have been made since the agent task.[/dim]")
            console.print(f"[dim]Use 'git revert {last_checkpoint[:8]}' manually if you still want to revert.[/dim]\n")
            return

        # v1.12.0: Check for uncommitted changes before undo (git revert requires clean working tree)
        backend = status.get("backend")
        if backend == "git":
            import subprocess
            try:
                working_dir = self.engine_client.context_injector.working_dir
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=working_dir,
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    console.print("[yellow]⚠️  Cannot undo: uncommitted changes in working directory[/yellow]")
                    console.print("[dim]Commit or stash your changes first, then try again[/dim]\n")
                    return
            except subprocess.CalledProcessError:
                pass  # If git status fails, let the undo attempt proceed

        # Show what will be undone
        console.print(f"\n[bold yellow]⚠️  Undo Last Agent Task[/bold yellow]")
        console.print(f"[cyan]Backend:[/cyan] {backend}")
        console.print(f"[cyan]Checkpoint:[/cyan] {last_checkpoint}")

        if backend == "git":
            console.print("\n[dim]This will:[/dim]")
            console.print("[dim]  • Create a git revert commit[/dim]")
            console.print("[dim]  • Restore all files to their pre-agent state[/dim]")
        else:
            console.print("\n[dim]This will:[/dim]")
            console.print("[dim]  • Restore files from snapshot[/dim]")
            console.print("[dim]  • Overwrite current file contents[/dim]")

        # Ask for confirmation
        try:
            from prompt_toolkit import prompt as pt_prompt
            response = pt_prompt("\nConfirm undo? (y/n): ")
            if response.lower() not in ["y", "yes"]:
                console.print("[yellow]Undo cancelled[/yellow]\n")
                return
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Undo cancelled[/yellow]\n")
            return

        # Perform undo
        console.print("\n[dim]Reverting changes...[/dim]")
        success = self.engine_client.undo_last_checkpoint()

        if success:
            console.print("[green]✓ Undo successful[/green]")
            if backend == "git":
                console.print("[dim]Check `git log` to see the revert commit[/dim]")
        else:
            console.print("[red]✗ Undo failed[/red]")
            console.print("[dim]Check checkpoint status with /agent or enable verbose tools logging[/dim]")

        console.print()

    def handle_checkpoint(self, args: str):
        """Handle /checkpoint command for checkpoint management (v1.12.4).

        Subcommands:
            /checkpoint              - Show checkpoint status (default)
            /checkpoint status       - Show checkpoint status
            /checkpoint list         - List recent checkpoints
            /checkpoint backend <x>  - Set backend (git/file/auto/none)
            /checkpoint clear        - Clear old file-based snapshots
            /checkpoint info <id>    - Show details about a checkpoint
            /checkpoint undo         - Alias for /undo
        """
        if not self.engine_client:
            console.print("[red]Checkpoint command requires engine client[/red]")
            return

        parts = args.strip().split() if args else []
        subcommand = parts[0].lower() if parts else "status"

        if subcommand == "status" or not parts:
            self._checkpoint_status()
        elif subcommand == "list":
            self._checkpoint_list()
        elif subcommand == "backend":
            backend = parts[1] if len(parts) > 1 else None
            self._checkpoint_backend(backend)
        elif subcommand == "clear":
            self._checkpoint_clear()
        elif subcommand == "info":
            checkpoint_id = parts[1] if len(parts) > 1 else None
            self._checkpoint_info(checkpoint_id)
        elif subcommand == "undo":
            self.handle_undo()  # Delegate to existing /undo handler
        else:
            console.print(f"[red]Unknown subcommand: {subcommand}[/red]")
            console.print("[dim]Available: status, list, backend, clear, info, undo[/dim]\n")

    def _checkpoint_status(self):
        """Show current checkpoint status."""
        status = self.engine_client.get_checkpoint_status()

        console.print("\n[bold cyan]━━━ Checkpoint Status ━━━[/bold cyan]")

        enabled = status.get("enabled", False)
        backend = status.get("backend", "none")
        last_checkpoint = status.get("last_checkpoint")
        is_valid = status.get("is_valid", False)
        validity_reason = status.get("validity_reason", "")

        # Backend status with color
        if backend == "git":
            backend_display = "[green]git[/green] (atomic)"
        elif backend == "file":
            backend_display = "[yellow]file[/yellow] (snapshot)"
        else:
            backend_display = "[red]none[/red] (disabled)"

        console.print(f"  [cyan]Backend:[/cyan] {backend_display}")
        console.print(f"  [cyan]Enabled:[/cyan] {'[green]Yes[/green]' if enabled else '[red]No[/red]'}")

        if last_checkpoint:
            checkpoint_display = last_checkpoint[:8] if len(last_checkpoint) > 8 else last_checkpoint
            if is_valid:
                console.print(f"  [cyan]Last checkpoint:[/cyan] {checkpoint_display} [green](valid)[/green]")
            else:
                console.print(f"  [cyan]Last checkpoint:[/cyan] {checkpoint_display} [yellow](stale)[/yellow]")
                console.print(f"  [dim]Reason: {validity_reason}[/dim]")
        else:
            console.print("  [cyan]Last checkpoint:[/cyan] [dim]None[/dim]")

        console.print()

    def _checkpoint_list(self):
        """List recent checkpoints."""
        checkpoints = self.engine_client.list_checkpoints(limit=10)

        console.print("\n[bold cyan]━━━ Recent Checkpoints ━━━[/bold cyan]")

        if not checkpoints:
            console.print("  [dim]No checkpoints found[/dim]")
            console.print("  [dim]Run an /agent task to create checkpoints[/dim]\n")
            return

        for i, cp in enumerate(checkpoints, 1):
            cp_id = cp.get("id", "")[:8]
            desc = cp.get("description", "")[:50]
            timestamp = cp.get("timestamp", "")[:19]  # Truncate to datetime
            console.print(f"  {i}. [cyan]{cp_id}[/cyan]  {timestamp}  {desc}")

        console.print()

    def _checkpoint_backend(self, backend: Optional[str]):
        """Set or show the checkpoint backend."""
        if not backend:
            # Show current backend
            status = self.engine_client.get_checkpoint_status()
            current = status.get("backend", "none")
            console.print(f"\n[cyan]Current backend:[/cyan] {current}")
            console.print("[dim]Usage: /checkpoint backend <git|file|auto|none>[/dim]\n")
            return

        valid_backends = ('git', 'file', 'auto', 'none')
        if backend not in valid_backends:
            console.print(f"[red]Invalid backend: {backend}[/red]")
            console.print(f"[dim]Valid options: {', '.join(valid_backends)}[/dim]\n")
            return

        success = self.engine_client.set_checkpoint_backend(backend)
        if success:
            status = self.engine_client.get_checkpoint_status()
            actual_backend = status.get("backend", "none")
            console.print(f"[green]✓ Checkpoint backend set to: {actual_backend}[/green]")

            if backend == "git" and actual_backend != "git":
                console.print("[yellow]Note: Git backend requested but no git repo found[/yellow]")
            elif backend == "auto":
                console.print(f"[dim]Auto-detected backend: {actual_backend}[/dim]")
        else:
            console.print("[red]✗ Failed to set checkpoint backend[/red]")

        console.print()

    def _checkpoint_clear(self):
        """Clear old file-based checkpoint snapshots."""
        status = self.engine_client.get_checkpoint_status()
        backend = status.get("backend", "none")

        if backend != "file":
            console.print("[yellow]Clear only applies to file-based checkpoints[/yellow]")
            console.print(f"[dim]Current backend: {backend}[/dim]\n")
            return

        # Ask for confirmation
        from prompt_toolkit import prompt as pt_prompt
        try:
            response = pt_prompt("Clear all file-based checkpoints? (y/n): ")
            if response.lower() not in ["y", "yes"]:
                console.print("[yellow]Clear cancelled[/yellow]\n")
                return
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Clear cancelled[/yellow]\n")
            return

        removed = self.engine_client.clear_file_checkpoints(keep_last=0)
        console.print(f"[green]✓ Cleared {removed} checkpoint(s)[/green]\n")

    def _checkpoint_info(self, checkpoint_id: Optional[str]):
        """Show details about a specific checkpoint."""
        if not checkpoint_id:
            console.print("[red]Usage: /checkpoint info <checkpoint_id>[/red]")
            console.print("[dim]Use /checkpoint list to see available checkpoints[/dim]\n")
            return

        checkpoints = self.engine_client.list_checkpoints(limit=20)

        # Find matching checkpoint (prefix match)
        matching = [cp for cp in checkpoints if cp.get("id", "").startswith(checkpoint_id)]

        if not matching:
            console.print(f"[red]Checkpoint not found: {checkpoint_id}[/red]")
            console.print("[dim]Use /checkpoint list to see available checkpoints[/dim]\n")
            return

        cp = matching[0]
        console.print("\n[bold cyan]━━━ Checkpoint Details ━━━[/bold cyan]")
        console.print(f"  [cyan]ID:[/cyan] {cp.get('id', '')}")
        console.print(f"  [cyan]Description:[/cyan] {cp.get('description', '')}")
        console.print(f"  [cyan]Timestamp:[/cyan] {cp.get('timestamp', '')}")

        # Check if this is the current checkpoint
        status = self.engine_client.get_checkpoint_status()
        if status.get("last_checkpoint", "").startswith(checkpoint_id):
            if status.get("is_valid"):
                console.print("  [cyan]Status:[/cyan] [green]Current (can undo)[/green]")
            else:
                console.print("  [cyan]Status:[/cyan] [yellow]Stale (cannot undo)[/yellow]")
        else:
            console.print("  [cyan]Status:[/cyan] [dim]Historical[/dim]")

        console.print()

    def _handle_agent_interrupt(self, checkpoint_id: Optional[str], checkpoint_backend: Optional[str]):
        """Handle agent interruption and offer automatic rollback (v1.12.0).

        Args:
            checkpoint_id: Checkpoint ID if one was created
            checkpoint_backend: Backend type ('git' or 'file')
        """
        console.print("[yellow]Agent task incomplete due to interrupt.[/yellow]\n")

        if not checkpoint_id:
            console.print("[dim]No checkpoint available. Any partial changes remain in place.[/dim]")
            console.print("[dim]Tip: Review changes manually and clean up as needed.[/dim]\n")
            return

        # Show current state
        console.print(f"[cyan]Checkpoint: {checkpoint_id[:8] if len(checkpoint_id) > 8 else checkpoint_id}[/cyan]")
        console.print(f"[cyan]Backend: {checkpoint_backend}[/cyan]\n")

        # Prompt for rollback
        console.print("[bold]Rollback all changes from this task?[/bold]")
        console.print("[dim]  y - Rollback to checkpoint (undo all changes)[/dim]")
        console.print("[dim]  n - Keep partial changes[/dim]\n")

        from prompt_toolkit import prompt as pt_prompt
        try:
            response = pt_prompt("Rollback? (y/n): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Keeping partial changes (no rollback)[/yellow]\n")
            return

        if response not in ['y', 'yes']:
            console.print("\n[yellow]Partial changes preserved[/yellow]")
            console.print("[dim]Use /undo later to rollback if needed[/dim]\n")
            return

        # Perform rollback
        console.print("\n[dim]Rolling back changes...[/dim]")
        success = self.engine_client.undo_last_checkpoint()

        if success:
            console.print("[green]✓ Checkpoint reverted successfully[/green]\n")

            # For git backend, check for uncommitted changes
            if checkpoint_backend == "git":
                import subprocess
                try:
                    result = subprocess.run(
                        ["git", "status", "--porcelain"],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        # Uncommitted changes detected
                        console.print("[yellow]⚠️  Uncommitted changes detected in working directory[/yellow]")
                        console.print("[dim]These are partial changes from the interrupted agent task.[/dim]\n")
                        console.print("[bold]Clean working directory?[/bold]")
                        console.print("[dim]  y - Remove all uncommitted changes (git reset --hard)[/dim]")
                        console.print("[dim]  n - Keep uncommitted changes for manual review[/dim]\n")

                        try:
                            clean_response = pt_prompt("Clean working directory? (y/n): ").strip().lower()
                        except (KeyboardInterrupt, EOFError):
                            console.print("\n[yellow]Keeping uncommitted changes[/yellow]\n")
                            return

                        if clean_response in ['y', 'yes']:
                            console.print("\n[dim]Running git reset --hard...[/dim]")
                            reset_result = subprocess.run(
                                ["git", "reset", "--hard", "HEAD"],
                                capture_output=True,
                                text=True,
                                check=False
                            )

                            if reset_result.returncode == 0:
                                console.print("[green]✓ Working directory cleaned[/green]")

                                # Also clean untracked files
                                console.print("[dim]Removing untracked files...[/dim]")
                                subprocess.run(
                                    ["git", "clean", "-fd"],
                                    capture_output=True,
                                    check=False
                                )
                                console.print("[green]✓ All changes removed[/green]\n")
                            else:
                                console.print(f"[red]✗ git reset failed: {reset_result.stderr}[/red]\n")
                        else:
                            console.print("\n[yellow]Uncommitted changes preserved[/yellow]")
                            console.print("[dim]Run 'git status' to see changes[/dim]")
                            console.print("[dim]Run 'git reset --hard' to clean manually[/dim]\n")
                except Exception as e:
                    console.print(f"[yellow]Could not check git status: {e}[/yellow]\n")
        else:
            console.print("[red]✗ Rollback failed[/red]")
            console.print("[dim]Check logs or try /undo manually[/dim]\n")

    def handle_agent(self, args: str):
        """Handle /agent command for autonomous task execution (v1.11.8).

        The agent loop runs autonomously until:
        - Task completes (AI signals TASK_COMPLETE)
        - Max iterations reached (default: 5)
        - User interrupts with Ctrl-C
        """
        if not args.strip():
            console.print("[red]Usage: /agent <task description>[/red]")
            console.print("[yellow]       /agent on|off - Toggle agent mode[/yellow]")
            console.print("[yellow]Example: /agent Fix the bug in auth.py[/yellow]")
            console.print("[yellow]         /agent Review @git changes and fix issues[/yellow]\n")
            return

        # v1.11.9: Redirect toggle commands to /tools agent handler (FIX)
        first_word = args.strip().split()[0].lower()
        if first_word in ["on", "off", "enable", "disable"]:
            self._tools_agent([first_word])
            return

        if not self.engine_client:
            console.print("[red]Error: Engine client not available[/red]\n")
            return

        task = args.strip()

        # v1.11.9: Handle /agent on|off as toggle commands
        if task.lower() in ['on', 'enable']:
            self.engine_client.enable_agent_mode()
            console.print("[green]Agent mode enabled[/green]")
            console.print("[dim]Tools auto-enabled. Use '/agent <task>' to start autonomous execution.[/dim]\n")
            return

        if task.lower() in ['off', 'disable']:
            self.engine_client.disable_agent_mode()
            console.print("[yellow]Agent mode disabled[/yellow]\n")
            return

        # v1.11.9: Get agent config from engine
        agent_config = self.engine_client.get_agent_config()
        min_words = agent_config.get("min_task_words", 3)
        max_iterations = agent_config.get("max_iterations", 10)

        # v1.11.9: Reject vague/ambiguous tasks for safety
        words = task.split()
        if len(words) < min_words:
            console.print(f"[red]Task too vague: \"{task}\"[/red]")
            console.print(f"\n[yellow]Agent tasks should be specific and descriptive (at least {min_words} words).[/yellow]")
            console.print("[yellow]Vague tasks can lead to unexpected AI interpretations.[/yellow]")
            console.print("\n[dim]Examples:[/dim]")
            console.print("[green]  ✓ /agent Fix the authentication bug in login.py[/green]")
            console.print("[green]  ✓ /agent Review @git changes and suggest improvements[/green]")
            console.print("[red]  ✗ /agent fix bug[/red]")
            console.print("[red]  ✗ /agent do it[/red]\n")
            return

        # Ensure agent mode is enabled (auto-enables tools)
        if not self.engine_client.agent_mode:
            console.print("[yellow]Enabling agent mode...[/yellow]")
            self.engine_client.enable_agent_mode()

        console.print(f"\n[cyan]🤖 Starting autonomous agent[/cyan]")
        console.print(f"[dim]Task: {task}[/dim]")
        console.print(f"[dim]Max iterations: {max_iterations}[/dim]")
        console.print(f"[dim]Press Ctrl-C to interrupt[/dim]\n")

        # Create checkpoint before agent task (v1.12.0)
        checkpoint_id = self.engine_client.create_checkpoint(task[:100])  # Truncate long tasks
        checkpoint_backend = None

        if checkpoint_id:
            # Notifications are emitted via events in create_checkpoint()
            status = self.engine_client.get_checkpoint_status()
            checkpoint_backend = status.get("backend")
        else:
            # If no checkpoint created, show warning if appropriate
            status = self.engine_client.get_checkpoint_status()
            if not status.get("enabled"):
                console.print("[yellow]⚠️  Running without checkpoints (no git repo)[/yellow]")
                console.print("[dim]Changes cannot be undone with /undo[/dim]\n")

        async def run_agent_loop():
            from .common.event_handler import TUIEventHandler

            iteration = 0
            task_complete = False

            while iteration < max_iterations and not task_complete:
                iteration += 1
                console.print(f"\n[yellow]━━━ Iteration {iteration}/{max_iterations} ━━━[/yellow]\n")

                # Build prompt for this iteration
                if iteration == 1:
                    prompt = self._build_agent_prompt(task, iteration)
                else:
                    prompt = self._build_continuation_prompt(task, iteration)

                # Run chat with event handling
                event_handler = TUIEventHandler(
                    console, self.logger,
                    verbose=self.tools_verbose,
                    emoji_mode=self.emoji_mode
                )

                try:
                    async for event in self.engine_client.chat(prompt, stream=True):
                        should_continue = await event_handler.handle_event(event)
                        if not should_continue:
                            break
                except KeyboardInterrupt:
                    console.print("\n[yellow]⚠️  Agent interrupted by user (Ctrl-C)[/yellow]\n")
                    raise  # Re-raise to outer handler

                response = event_handler.get_response()

                # Check for completion signal
                if "TASK_COMPLETE:" in response:
                    task_complete = True
                    # Extract summary after TASK_COMPLETE:
                    summary_parts = response.split("TASK_COMPLETE:", 1)
                    final_summary = summary_parts[1].strip() if len(summary_parts) > 1 else "Done"
                    console.print(f"\n[green]✅ Task completed![/green]")
                    console.print(f"[dim]Summary: {final_summary[:200]}{'...' if len(final_summary) > 200 else ''}[/dim]\n")
                    return

            if not task_complete:
                console.print(f"\n[yellow]⚠️  Max iterations ({max_iterations}) reached[/yellow]")
                console.print("[dim]Task may be incomplete. Review the output above.[/dim]\n")

        try:
            import asyncio
            asyncio.run(run_agent_loop())
        except KeyboardInterrupt:
            # Offer automatic rollback after interrupt (v1.12.0)
            self._handle_agent_interrupt(checkpoint_id, checkpoint_backend)

    def _build_agent_prompt(self, task: str, iteration: int) -> str:
        """Build initial prompt for agent (v1.11.8)."""
        return f"""Task: {task}

Work on this task autonomously. You have tools available for:
- Reading files (read_file, search_files, list_directory)
- Editing files (apply_patch, replace_block, insert_text, delete_lines)
- Running shell commands (execute_shell_command)
- Web search and fetch (if available for your provider)

Instructions:
1. Analyze the task and plan your approach
2. Use tools to gather information and make changes
3. After each action, assess progress

When the task is complete, respond with:
TASK_COMPLETE: <brief summary of what was done>

If you need to continue working, explain your progress and use the appropriate tools."""

    def _build_continuation_prompt(self, task: str, iteration: int) -> str:
        """Build continuation prompt for subsequent iterations (v1.11.8)."""
        return f"""Continue working on the task: {task}

Review your previous work and continue toward completion.

If the task is now complete, respond with:
TASK_COMPLETE: <brief summary of what was done>

If more work is needed, explain what you're doing next and use the appropriate tools."""

    def handle_command(self, user_input: str) -> Optional[bool]:
        """
        Handle a slash command.

        Returns:
            - True if should exit the application
            - False/None to continue
        """
        command_parts = user_input.split(maxsplit=1)
        command = command_parts[0].lower()
        args = command_parts[1] if len(command_parts) > 1 else ""

        if command in ["/quit", "/exit"]:
            return self.handle_quit()
        elif command == "/save":
            self.handle_save(args)
        elif command == "/export":
            self.handle_export(args)
        elif command == "/sessions":
            self.handle_sessions()
        elif command == "/load":
            self.handle_load(args)
        elif command == "/usage":
            self.handle_usage(args)
        elif command == "/clear":
            self.handle_clear()
        elif command == "/model":
            self.handle_model(args)
        elif command == "/provider":
            self.handle_provider(args)
        elif command == "/help":
            self.handle_help()
        elif command == "/theme":
            self.handle_theme(args)
        elif command == "/generate":
            self.handle_generate(args)
        elif command == "/test":
            self.handle_test(args)
        elif command == "/docs":
            self.handle_docs(args)
        elif command == "/implement":
            self.handle_implement(args)
        elif command == "/debug":
            self.handle_debug(args)
        elif command == "/debug-log":
            self.handle_debug_log(args)
        elif command == "/explain":
            self.handle_explain(args)
        elif command == "/convert":
            self.handle_convert(args)
        elif command == "/autoroute":
            self.handle_autoroute(args)
        elif command == "/spec":
            self.handle_spec(args)
        elif command == "/tools":
            self.handle_tools(args)
        elif command == "/show":
            self.handle_show(args)
        elif command == "/cat":
            self.handle_show(args)  # Alias for /show
        elif command == "/agent":
            self.handle_agent(args)
        elif command == "/undo":
            self.handle_undo()
        elif command == "/checkpoint":
            self.handle_checkpoint(args)
        elif command == "/status":
            self.handle_status(args)
        else:
            console.print(f"[red]Unknown command: {user_input}[/red]")
            console.print("[yellow]Type /help for available commands[/yellow]\n")

        return False

    def handle_status(self, args: str = ""):
        """Show comprehensive status information.

        Usage:
            /status              - Show all status info
            /status version      - Toggle version display in status bar
            /status cwd          - Toggle working directory display
            /status datetime     - Toggle date/time display
        """
        from ppxai.config import get_tui_config, get_provider_config
        from ppxai.version import __version__

        parts = args.strip().split() if args else []

        # Handle toggle subcommands
        if parts:
            subcommand = parts[0].lower()
            if subcommand in ("version", "cwd", "datetime"):
                # Toggle the setting - note these require config file modification
                # For now, just show current status and suggest config edit
                tui_config = get_tui_config()
                current_value = tui_config.get(f"show_{subcommand}", subcommand != "datetime")
                console.print(f"\n[cyan]show_{subcommand}:[/cyan] {'[green]true[/green]' if current_value else '[dim]false[/dim]'}")
                console.print(f"[dim]To change, edit ppxai-config.json: \"tui\": {{ \"show_{subcommand}\": {'false' if current_value else 'true'} }}[/dim]\n")
                return

        # Show comprehensive status
        console.print("\n[bold cyan]━━━ ppxai Status ━━━[/bold cyan]")

        # Version
        console.print(f"  [cyan]Version:[/cyan] v{__version__}")

        # Provider and model
        provider_config = get_provider_config(self.provider)
        console.print(f"  [cyan]Provider:[/cyan] {provider_config.get('name', self.provider)}")
        console.print(f"  [cyan]Model:[/cyan] {self.current_model}")

        # Working directory
        if self.engine_client:
            cwd = self.engine_client.working_dir or "[dim]not set[/dim]"
            console.print(f"  [cyan]Working Dir:[/cyan] {cwd}")

        # Tools status
        tools_status = "[green]enabled[/green]" if (self.engine_client and self.engine_client.tools_enabled) else "[dim]disabled[/dim]"
        console.print(f"  [cyan]Tools:[/cyan] {tools_status}")

        # Agent mode
        agent_status = "[green]active[/green]" if (self.engine_client and self.engine_client.agent_mode) else "[dim]inactive[/dim]"
        console.print(f"  [cyan]Agent Mode:[/cyan] {agent_status}")

        # Theme
        console.print(f"  [cyan]Theme:[/cyan] {self.current_theme_name}")

        # Session info
        if self.engine_client and self.engine_client.session:
            session = self.engine_client.session
            msg_count = len(session.history) if session.history else 0
            console.print(f"  [cyan]Messages:[/cyan] {msg_count}")

            # Usage stats
            total_usage = session.get_total_usage()
            if total_usage:
                console.print(f"  [cyan]Tokens:[/cyan] {total_usage.get('prompt_tokens', 0)}↓ / {total_usage.get('completion_tokens', 0)}↑")
                cost = total_usage.get('estimated_cost', 0.0)
                if cost > 0:
                    console.print(f"  [cyan]Cost:[/cyan] ${cost:.4f}")

        # Status bar display settings
        tui_config = get_tui_config()
        console.print("\n[bold dim]Status Bar Settings:[/bold dim]")
        console.print(f"  show_version: {'[green]true[/green]' if tui_config.get('show_version', True) else '[dim]false[/dim]'}")
        console.print(f"  show_cwd: {'[green]true[/green]' if tui_config.get('show_cwd', True) else '[dim]false[/dim]'}")
        console.print(f"  show_datetime: {'[green]true[/green]' if tui_config.get('show_datetime', False) else '[dim]false[/dim]'}")

        console.print()
