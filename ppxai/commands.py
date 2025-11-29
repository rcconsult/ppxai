"""
Command handlers for the ppxai application.
"""

import os
import asyncio
from typing import Optional, TYPE_CHECKING

from rich.console import Console

from .config import CODING_MODEL, get_coding_model, get_provider_config, get_api_key, get_base_url, PROVIDERS
from .prompts import CODING_PROMPTS
from .utils import read_file_content
from .ui import (
    console,
    display_welcome,
    display_spec_help,
    select_model,
    select_provider,
    display_sessions,
    display_usage,
    display_global_usage,
    display_tools_table,
)

if TYPE_CHECKING:
    from .client import AIClient


def send_coding_task(client: 'AIClient', task_type: str, user_message: str, model: str, provider: str = None) -> Optional[str]:
    """Send a coding task with appropriate system prompt and optional auto-routing."""
    if task_type not in CODING_PROMPTS:
        console.print(f"[red]Unknown task type: {task_type}[/red]")
        return None

    # Auto-route to coding model if enabled (use provider-specific coding model)
    coding_model = get_coding_model(provider)
    if client.auto_route and model != coding_model:
        model = coding_model
        console.print(f"[dim]Auto-routed to {coding_model} for coding task (disable with /autoroute off)[/dim]")

    # Create a temporary message with system instruction
    system_prompt = CODING_PROMPTS[task_type]
    full_message = f"{system_prompt}\n\n{user_message}"

    # Send the message
    return client.chat(full_message, model, stream=True)


class CommandHandler:
    """Handles all slash commands for the application."""

    def __init__(self, client, api_key: str, current_model: str, base_url: str = None, provider: str = None):
        self.client = client
        self.api_key = api_key
        self.current_model = current_model
        self.base_url = base_url or "https://api.perplexity.ai"
        self.provider = provider or "perplexity"
        self.tools_available = False
        self.PerplexityClientPromptTools = None
        self.load_tool_config = None

        # Try to load tool support
        try:
            from perplexity_tools_prompt_based import PerplexityClientPromptTools
            from tool_manager import load_tool_config
            self.tools_available = True
            self.PerplexityClientPromptTools = PerplexityClientPromptTools
            self.load_tool_config = load_tool_config
        except ImportError:
            pass

    def handle_quit(self) -> bool:
        """Handle /quit or /exit command. Returns True if should exit."""
        if self.client.conversation_history:
            try:
                self.client.save_session()
                console.print(f"[dim]Session saved: {self.client.session_name}[/dim]")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not save session: {e}[/yellow]")
        console.print("\n[yellow]Goodbye![/yellow]")
        return True

    def handle_save(self, args: str):
        """Handle /save command."""
        try:
            filename = args.strip() if args else None
            filepath = self.client.export_conversation(filename)
            console.print(f"\n[green]Conversation exported to:[/green] {filepath}\n")
        except Exception as e:
            console.print(f"[red]Error exporting conversation: {e}[/red]\n")

    def handle_sessions(self):
        """Handle /sessions command."""
        from .client import AIClient
        sessions = AIClient.list_sessions()
        display_sessions(sessions)

    def handle_load(self, args: str):
        """Handle /load command."""
        from .client import AIClient

        if not args:
            console.print("[red]Please specify a session name: /load <session_name>[/red]\n")
            sessions = AIClient.list_sessions()
            display_sessions(sessions)
            return

        try:
            loaded_client = AIClient.load_session(args.strip(), self.api_key, self.base_url, self.provider)
            if loaded_client:
                self.client = loaded_client
                self.current_model = self.client.session_metadata.get("model", self.current_model)
                console.print(f"\n[green]Session loaded:[/green] {self.client.session_name}")
                console.print(f"[dim]Messages: {len(self.client.conversation_history)}[/dim]\n")
            else:
                console.print(f"[red]Session not found: {args.strip()}[/red]\n")
        except Exception as e:
            console.print(f"[red]Error loading session: {e}[/red]\n")

    def handle_usage(self):
        """Handle /usage command."""
        usage = self.client.get_usage_summary()
        display_usage(usage)
        display_global_usage()

    def handle_clear(self):
        """Handle /clear command."""
        self.client.clear_history()
        console.print("\n[green]Conversation history cleared.[/green]\n")

    def handle_model(self):
        """Handle /model command."""
        self.current_model = select_model(self.provider)
        self.client.session_metadata["model"] = self.current_model
        console.print()

    def handle_provider(self):
        """Handle /provider command - switch between providers."""
        from .client import AIClient

        console.print(f"\n[cyan]Current provider:[/cyan] {self.provider}")

        # Show available providers
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

        # Switch to new provider
        new_base_url = get_base_url(new_provider)
        new_config = get_provider_config(new_provider)

        # Create new client with the new provider
        new_client = AIClient(new_api_key, new_base_url, provider=new_provider)
        new_client.conversation_history = self.client.conversation_history
        new_client.current_session_usage = self.client.current_session_usage

        self.client = new_client
        self.api_key = new_api_key
        self.base_url = new_base_url
        self.provider = new_provider

        # Select model for new provider
        self.current_model = select_model(new_provider)
        self.client.session_metadata["model"] = self.current_model
        self.client.session_metadata["provider"] = new_provider

        console.print(f"\n[green]Switched to:[/green] {new_config['name']} ({new_base_url})\n")

    def handle_help(self):
        """Handle /help command."""
        display_welcome()

    def handle_generate(self, args: str):
        """Handle /generate command."""
        if not args:
            console.print("[red]Please provide a description: /generate <description>[/red]")
            console.print("[yellow]Example: /generate a function to validate email addresses in Python[/yellow]\n")
            return

        console.print(f"\n[cyan]Generating code for:[/cyan] {args}\n")
        send_coding_task(self.client, "generate", args, self.current_model)

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
            send_coding_task(self.client, "test", task_message, self.current_model)

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
            send_coding_task(self.client, "docs", task_message, self.current_model)

    def handle_implement(self, args: str):
        """Handle /implement command."""
        if not args:
            console.print("[red]Please provide a feature specification: /implement <specification>[/red]")
            console.print("[yellow]Example: /implement a REST API endpoint for user authentication[/yellow]")
            console.print("[cyan]Tip: Use /spec to see specification guidelines and templates[/cyan]\n")
            return

        console.print(f"\n[cyan]Implementing feature:[/cyan] {args}\n")
        send_coding_task(self.client, "implement", args, self.current_model)

    def handle_debug(self, args: str):
        """Handle /debug command."""
        if not args:
            console.print("[red]Please provide error details or paste your error message/stack trace[/red]")
            console.print("[yellow]Example: /debug TypeError: 'NoneType' object is not subscriptable at line 42[/yellow]\n")
            return

        console.print(f"\n[cyan]Analyzing error:[/cyan] {args[:100]}...\n")
        send_coding_task(self.client, "debug", args, self.current_model)

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
            send_coding_task(self.client, "explain", task_message, self.current_model)

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
        send_coding_task(self.client, "convert", task_message, self.current_model)

    def handle_autoroute(self, args: str):
        """Handle /autoroute command."""
        coding_model = get_coding_model(self.provider)

        if not args:
            status = "enabled" if self.client.auto_route else "disabled"
            console.print(f"\n[cyan]Auto-routing is currently:[/cyan] [bold]{status}[/bold]")
            console.print(f"[dim]Auto-routing uses {coding_model} for coding commands[/dim]")
            console.print("[yellow]Use /autoroute on or /autoroute off to change[/yellow]\n")
            return

        arg = args.strip().lower()
        if arg == "on":
            self.client.auto_route = True
            console.print(f"[green]Auto-routing enabled.[/green] Coding commands will use {coding_model}\n")
        elif arg == "off":
            self.client.auto_route = False
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

        if subcommand == "enable":
            self._enable_tools()
        elif subcommand == "disable":
            self._disable_tools()
        elif subcommand == "list":
            self._list_tools()
        elif subcommand == "status":
            self._tools_status()
        elif subcommand == "config":
            self._tools_config(subargs)
        else:
            console.print(f"[red]Unknown subcommand: {subcommand}[/red]")
            console.print("[yellow]Available: enable, disable, list, status, config[/yellow]\n")

    def _enable_tools(self):
        """Enable AI tools."""
        if isinstance(self.client, self.PerplexityClientPromptTools):
            console.print("[yellow]Tools already enabled[/yellow]\n")
            return

        # Upgrade client to tool-enabled version
        tool_client = self.PerplexityClientPromptTools(
            api_key=self.api_key,
            base_url=self.base_url,
            session_name=self.client.session_name,
            enable_tools=True,
            provider=self.provider
        )
        # Copy conversation history
        tool_client.conversation_history = self.client.conversation_history
        tool_client.session_metadata = self.client.session_metadata
        tool_client.current_session_usage = self.client.current_session_usage

        # Initialize tools (built-in only by default)
        console.print("[cyan]Initializing tools...[/cyan]")
        asyncio.run(tool_client.initialize_tools(mcp_servers=[]))

        # Replace client
        self.client = tool_client
        console.print("[green]✓ Tools enabled![/green]")
        console.print("[dim]Use '/tools list' to see available tools[/dim]\n")

    def _disable_tools(self):
        """Disable AI tools."""
        from .client import AIClient

        if not isinstance(self.client, self.PerplexityClientPromptTools):
            console.print("[yellow]Tools not enabled[/yellow]\n")
            return

        # Downgrade to regular client
        regular_client = AIClient(self.api_key, self.base_url, self.client.session_name, self.provider)
        regular_client.conversation_history = self.client.conversation_history
        regular_client.session_metadata = self.client.session_metadata
        regular_client.current_session_usage = self.client.current_session_usage

        # Cleanup tool client
        asyncio.run(self.client.cleanup())

        self.client = regular_client
        console.print("[yellow]Tools disabled[/yellow]\n")

    def _list_tools(self):
        """List available tools."""
        if not isinstance(self.client, self.PerplexityClientPromptTools):
            console.print("[yellow]Tools not enabled. Use '/tools enable' first[/yellow]\n")
            return

        if not self.client.tool_manager or not self.client.tool_manager.tools:
            console.print("[yellow]No tools available[/yellow]\n")
            return

        display_tools_table(self.client.tool_manager.list_tools())

    def _tools_status(self):
        """Show tools status."""
        if isinstance(self.client, self.PerplexityClientPromptTools):
            tool_count = len(self.client.tool_manager.tools) if self.client.tool_manager else 0
            max_iter = getattr(self.client, 'tool_max_iterations', 15)
            console.print(f"[green]✓ Tools enabled[/green] ({tool_count} tools available)")
            console.print(f"[dim]Max iterations: {max_iter}[/dim]")
            console.print("[dim]Use '/tools list' to see available tools[/dim]\n")
        else:
            console.print("[yellow]Tools not enabled[/yellow]")
            console.print("[dim]Use '/tools enable' to activate AI tools[/dim]\n")

    def _tools_config(self, args: list):
        """Configure tool settings."""
        if not isinstance(self.client, self.PerplexityClientPromptTools):
            console.print("[yellow]Tools not enabled. Use '/tools enable' first[/yellow]\n")
            return

        if not args:
            # Show current config
            max_iter = getattr(self.client, 'tool_max_iterations', 15)
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
                self.client.tool_max_iterations = num
                console.print(f"[green]✓ max_iterations set to {num}[/green]\n")
            except ValueError:
                console.print(f"[red]Invalid number: {value}[/red]\n")
        else:
            console.print(f"[red]Unknown setting: {setting}[/red]")
            console.print("[dim]Available: max_iterations[/dim]\n")

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
        elif command == "/sessions":
            self.handle_sessions()
        elif command == "/load":
            self.handle_load(args)
        elif command == "/usage":
            self.handle_usage()
        elif command == "/clear":
            self.handle_clear()
        elif command == "/model":
            self.handle_model()
        elif command == "/provider":
            self.handle_provider()
        elif command == "/help":
            self.handle_help()
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
        else:
            console.print(f"[red]Unknown command: {user_input}[/red]")
            console.print("[yellow]Type /help for available commands[/yellow]\n")

        return False
