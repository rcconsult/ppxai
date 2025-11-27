"""
Main entry point for the ppxai application.
"""

import os
import sys
import asyncio

from dotenv import load_dotenv
from prompt_toolkit import prompt
from prompt_toolkit.history import InMemoryHistory

from .client import PerplexityClient
from .commands import CommandHandler
from .ui import console, display_welcome, select_model

# Load environment variables
load_dotenv()


def main():
    """Main application loop."""
    # Check for API key
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        console.print("[red]Error: PERPLEXITY_API_KEY not found in environment variables.[/red]")
        console.print("[yellow]Please create a .env file with your API key (see .env.example)[/yellow]")
        sys.exit(1)

    # Initialize client
    client = PerplexityClient(api_key)

    # Display welcome
    display_welcome()

    # Select initial model
    current_model = select_model()
    client.session_metadata["model"] = current_model

    # Create command handler
    handler = CommandHandler(client, api_key, current_model)

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
