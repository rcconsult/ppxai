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
                    self.client.session_metadata["model"] = self.current_model
                    console.print(f"[green]✓ Switched to model: {model_id}[/green]\n")
                    found = True
                    break

            if not found:
                console.print(f"[red]Model not found: {args}[/red]")
                console.print("[dim]Use /model list to see available models[/dim]\n")
        else:
            # Interactive selection
            self.current_model = select_model(self.provider)
            self.client.session_metadata["model"] = self.current_model
            console.print()

    def handle_provider(self, args: str = ""):
        """Handle /provider command - switch between providers."""
        from .client import AIClient

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

        # Select model for new provider (auto-select default if direct switch)
        if args:
            self.current_model = new_config.get("default_model", "")
        else:
            self.current_model = select_model(new_provider)
        self.client.session_metadata["model"] = self.current_model
        self.client.session_metadata["provider"] = new_provider

        console.print(f"\n[green]Switched to:[/green] {new_config['name']} (model: {self.current_model})\n")

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

            # Display with syntax highlighting (no truncation for local viewing)
            syntax = Syntax(content, lang, theme="monokai", line_numbers=True)
            console.print(syntax)

            # Show timing
            elapsed = time.time() - start_time
            console.print(f"[dim]({elapsed:.2f}s)[/dim]\n")

        except UnicodeDecodeError:
            console.print(f"[red]Cannot display binary file: {query}[/red]\n")
        except Exception as e:
            console.print(f"[red]Error reading file: {e}[/red]\n")

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
            self.handle_model(args)
        elif command == "/provider":
            self.handle_provider(args)
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
        elif command == "/show":
            self.handle_show(args)
        elif command == "/cat":
            self.handle_show(args)  # Alias for /show
        else:
            console.print(f"[red]Unknown command: {user_input}[/red]")
            console.print("[yellow]Type /help for available commands[/yellow]\n")

        return False
