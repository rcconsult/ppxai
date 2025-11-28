"""
Main entry point for the ppxai application.
"""

import os
import sys
import asyncio

from prompt_toolkit import prompt
from prompt_toolkit.history import InMemoryHistory

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

    # Create prompt history
    history = InMemoryHistory()

    # Main loop
    console.print("\n[bold green]Ready to chat! Type your message or /help for commands.[/bold green]\n")
    console.print(f"[dim]Session: {client.session_name}[/dim]\n")

    while True:
        try:
            # Get user input with history support
            user_input = prompt(
                "You: ",
                history=history,
                multiline=False
            ).strip()

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
                response = asyncio.run(client.chat_with_tools(user_input, current_model))
            else:
                # Use regular chat
                response = client.chat(user_input, current_model, stream=True)

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
