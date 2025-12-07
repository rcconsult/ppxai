"""
Main entry point for the ppxai application.
"""

import os
import sys
import asyncio
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from .client import AIClient
from .commands import CommandHandler
from .config import (
    MODEL_PROVIDER,
    PROVIDERS,
    get_api_key,
    get_base_url,
    get_provider_config,
)
from .ui import console, display_welcome, select_model, select_provider


class PPXAICompleter(Completer):
    """Custom completer for slash commands and @file references."""

    COMMANDS = [
        ('/help', 'Show available commands'),
        ('/model', 'Switch model'),
        ('/provider', 'Switch provider'),
        ('/clear', 'Clear conversation history'),
        ('/save', 'Save current session'),
        ('/load', 'Load a saved session'),
        ('/sessions', 'List saved sessions'),
        ('/new', 'Start new session'),
        ('/history', 'Show conversation history'),
        ('/tools', 'Manage AI tools'),
        ('/show', 'Display file contents'),
        ('/cat', 'Display file contents (alias)'),
        ('/usage', 'Show token usage stats'),
        ('/status', 'Show current status'),
        ('/explain', 'Explain code'),
        ('/test', 'Generate tests'),
        ('/review', 'Review code'),
        ('/debug', 'Debug code'),
        ('/optimize', 'Optimize code'),
        ('/quit', 'Exit the application'),
        ('/exit', 'Exit the application'),
    ]

    # Directories to ignore when searching for files
    IGNORE_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', 'dist', 'build', '.eggs', '.mypy_cache'}

    def __init__(self):
        self._file_cache = {}
        self._cache_time = 0

    def _get_files(self, max_files: int = 100) -> list[tuple[str, str]]:
        """Get files in the current directory for completion."""
        import time
        now = time.time()

        # Cache for 5 seconds
        if now - self._cache_time < 5 and self._file_cache:
            return list(self._file_cache.items())[:max_files]

        root = Path.cwd()
        files = {}

        try:
            for path in root.rglob('*'):
                if len(files) >= max_files * 2:
                    break
                if path.is_file():
                    # Skip files in ignored directories
                    if any(ignored in path.parts for ignored in self.IGNORE_DIRS):
                        continue
                    try:
                        rel_path = str(path.relative_to(root))
                        files[path.name] = rel_path
                    except ValueError:
                        pass
        except PermissionError:
            pass

        self._file_cache = files
        self._cache_time = now
        return list(files.items())[:max_files]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Check for @file reference anywhere in the text (priority over commands)
        at_pos = text.rfind('@')
        if at_pos >= 0:
            # Get the query after @
            query = text[at_pos + 1:].lower()

            # Show file completions
            for filename, filepath in self._get_files():
                if not query or query in filename.lower() or query in filepath.lower():
                    # Calculate how much to replace (from @ to cursor)
                    replace_len = len(text) - at_pos
                    yield Completion(
                        '@' + filename,
                        start_position=-replace_len,
                        display=filename,
                        display_meta=filepath
                    )
            return  # Don't show command completions when typing @file

        # Check for slash command at start of line (only if no @ in text)
        if text.startswith('/'):
            cmd_text = text.lower()
            for cmd, desc in self.COMMANDS:
                if cmd.lower().startswith(cmd_text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display_meta=desc
                    )

# Note: Environment variables are loaded in config.py


def main():
    """Main application loop."""
    # Check if provider selection is needed or use environment default
    provider = MODEL_PROVIDER

    # Allow provider selection at startup if multiple providers configured
    if len(PROVIDERS) > 1:
        console.print("\n[bold cyan]Available Providers:[/bold cyan]")
        for key, config in PROVIDERS.items():
            api_key_env = config["api_key_env"]
            has_key = bool(os.getenv(api_key_env))
            status = "[green]configured[/green]" if has_key else "[yellow]not configured[/yellow]"
            console.print(f"  - {key}: {config['name']} ({status})")

        # Check if user wants to change provider
        if os.getenv("MODEL_PROVIDER"):
            console.print(f"\n[dim]Using provider from MODEL_PROVIDER env: {provider}[/dim]")
        else:
            provider = select_provider()

    # Get provider configuration
    provider_config = get_provider_config(provider)
    api_key = get_api_key(provider)
    base_url = get_base_url(provider)

    if not api_key:
        api_key_env = provider_config["api_key_env"]
        console.print(f"[red]Error: {api_key_env} not found in environment variables.[/red]")
        console.print("[yellow]Please create a .env file with your API key (see .env.example)[/yellow]")
        sys.exit(1)

    # Initialize client with provider configuration
    client = AIClient(api_key, base_url, provider=provider)
    console.print(f"\n[green]Connected to:[/green] {provider_config['name']} ({base_url})")

    # Display welcome
    display_welcome()

    # Select initial model (from provider's available models)
    current_model = select_model(provider)
    client.session_metadata["model"] = current_model

    # Create command handler with provider info
    handler = CommandHandler(client, api_key, current_model, base_url, provider)

    # Create prompt session with history and completer
    completer = PPXAICompleter()
    session = PromptSession(
        history=InMemoryHistory(),
        completer=completer,
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
    )

    # Main loop
    console.print("\n[bold green]Ready to chat! Type your message or /help for commands.[/bold green]")
    console.print("[dim]Tab: autocomplete • @file: reference files • ↑/↓: history[/dim]\n")
    console.print(f"[dim]Session: {client.session_name}[/dim]\n")

    while True:
        try:
            # Get user input with history and completion support
            user_input = session.prompt("You: ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                should_exit = handler.handle_command(user_input)
                if should_exit:
                    break
                # Update references in case they changed
                client = handler.client
                current_model = handler.current_model
                continue

            # Process @filename references in the message
            augmented_input, resolved_files = handler.process_file_references(user_input)
            if resolved_files:
                file_names = ', '.join(f['name'] for f in resolved_files)
                console.print(f"[dim]Including {len(resolved_files)} file(s): {file_names}[/dim]")

            # Check if tools are enabled
            tools_enabled = (
                handler.tools_available and
                handler.PerplexityClientPromptTools and
                isinstance(client, handler.PerplexityClientPromptTools) and
                client.enable_tools
            )

            # Send message to API
            if tools_enabled:
                # Use async tool-enabled chat
                response = asyncio.run(client.chat_with_tools(augmented_input, current_model))
            else:
                # Use regular chat
                response = client.chat(augmented_input, current_model, stream=True)

            # Update session metadata
            if response:
                client.session_metadata["message_count"] = len(client.conversation_history)

                # Auto-save session after every 10 messages
                if len(client.conversation_history) % 10 == 0:
                    try:
                        client.save_session()
                    except Exception:
                        pass  # Silent fail on auto-save

        except KeyboardInterrupt:
            console.print("\n\n[yellow]Use /quit or /exit to exit the application[/yellow]\n")
            continue

        except EOFError:
            console.print("\n[yellow]Goodbye![/yellow]")
            break

        except Exception as e:
            console.print(f"\n[red]Unexpected error: {str(e)}[/red]\n")
            continue


if __name__ == "__main__":
    main()
