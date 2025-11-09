#!/usr/bin/env python3
"""
Perplexity AI Text UI Application
A terminal-based interface for interacting with Perplexity AI models.
"""

import os
import sys
from typing import Optional
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.table import Table
from prompt_toolkit import prompt
from prompt_toolkit.history import InMemoryHistory
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Rich console
console = Console()

# Available Perplexity models
MODELS = {
    "1": {
        "id": "sonar",
        "name": "Sonar",
        "description": "Lightweight search model with real-time grounding"
    },
    "2": {
        "id": "sonar-pro",
        "name": "Sonar Pro",
        "description": "Advanced search model for complex queries"
    },
    "3": {
        "id": "sonar-reasoning",
        "name": "Sonar Reasoning",
        "description": "Fast reasoning model for problem-solving with search"
    },
    "4": {
        "id": "sonar-reasoning-pro",
        "name": "Sonar Reasoning Pro",
        "description": "Precision reasoning with Chain of Thought capabilities"
    },
    "5": {
        "id": "sonar-deep-research",
        "name": "Sonar Deep Research",
        "description": "Exhaustive research with comprehensive reports"
    },
}


class PerplexityClient:
    """Client for interacting with Perplexity API."""

    def __init__(self, api_key: str):
        """Initialize the Perplexity client."""
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )
        self.conversation_history = []

    def chat(self, message: str, model: str, stream: bool = True):
        """
        Send a chat message to Perplexity API.

        Args:
            message: The user's message
            model: The model ID to use
            stream: Whether to stream the response

        Returns:
            The assistant's response
        """
        self.conversation_history.append({
            "role": "user",
            "content": message
        })

        try:
            if stream:
                return self._stream_response(model)
            else:
                return self._get_response(model)
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            self.conversation_history.pop()  # Remove the failed message
            return None

    def _stream_response(self, model: str):
        """Stream the response from the API."""
        response_chunks = []
        citations = []
        last_chunk = None

        response_stream = self.client.chat.completions.create(
            model=model,
            messages=self.conversation_history,
            stream=True
        )

        console.print("\n[bold cyan]Assistant:[/bold cyan]")
        for chunk in response_stream:
            last_chunk = chunk

            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                response_chunks.append(content)
                console.print(content, end="")

            # Try to capture citations from various possible locations
            if hasattr(chunk, 'citations') and chunk.citations:
                citations = chunk.citations
            elif hasattr(chunk.choices[0], 'citations') and chunk.choices[0].citations:
                citations = chunk.choices[0].citations
            elif hasattr(chunk.choices[0].delta, 'citations') and chunk.choices[0].delta.citations:
                citations = chunk.choices[0].delta.citations

        console.print("\n")

        full_response = "".join(response_chunks)
        self.conversation_history.append({
            "role": "assistant",
            "content": full_response
        })

        # Display citations if available
        if citations:
            self._display_citations(citations)

        return full_response

    def _get_response(self, model: str):
        """Get a non-streaming response from the API."""
        response = self.client.chat.completions.create(
            model=model,
            messages=self.conversation_history,
            stream=False
        )

        assistant_message = response.choices[0].message.content
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        # Display citations if available
        if hasattr(response, 'citations') and response.citations:
            self._display_citations(response.citations)

        return assistant_message

    def _display_citations(self, citations):
        """Display citations as clickable links."""
        if not citations:
            return

        console.print("\n[bold yellow]Sources:[/bold yellow]")
        for idx, citation in enumerate(citations, 1):
            # Create clickable link using Rich's link markup
            clickable_link = f"[link={citation}]{citation}[/link]"
            console.print(f"[cyan]{idx}.[/cyan] {clickable_link}")
        console.print()

    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []


def display_welcome():
    """Display welcome message."""
    welcome_text = """
# Perplexity AI Text UI

Welcome to the Perplexity AI terminal interface!

Commands:
- Type your question or prompt to chat
- `/clear` - Clear conversation history
- `/model` - Change model
- `/help` - Show this help message
- `/quit` or `/exit` - Exit the application
"""
    console.print(Panel(Markdown(welcome_text), title="Welcome", border_style="cyan"))


def display_models():
    """Display available models in a table."""
    table = Table(title="Available Models", show_header=True, header_style="bold magenta")
    table.add_column("Choice", style="cyan", width=8)
    table.add_column("Name", style="green")
    table.add_column("Description", style="white")

    for choice, model in MODELS.items():
        table.add_row(choice, model["name"], model["description"])

    console.print(table)


def select_model() -> Optional[str]:
    """Prompt user to select a model."""
    display_models()

    choice = Prompt.ask(
        "\n[bold yellow]Select a model[/bold yellow]",
        choices=list(MODELS.keys()),
        default="2"
    )

    selected_model = MODELS[choice]
    console.print(f"\n[green]Selected:[/green] {selected_model['name']}")
    return selected_model["id"]


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

    # Create prompt history
    history = InMemoryHistory()

    # Main loop
    console.print("\n[bold green]Ready to chat! Type your message or /help for commands.[/bold green]\n")

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
                command = user_input.lower()

                if command in ["/quit", "/exit"]:
                    console.print("\n[yellow]Goodbye![/yellow]")
                    break

                elif command == "/clear":
                    client.clear_history()
                    console.print("\n[green]Conversation history cleared.[/green]\n")
                    continue

                elif command == "/model":
                    current_model = select_model()
                    console.print()
                    continue

                elif command == "/help":
                    display_welcome()
                    continue

                else:
                    console.print(f"[red]Unknown command: {user_input}[/red]")
                    console.print("[yellow]Type /help for available commands[/yellow]\n")
                    continue

            # Send message to API
            client.chat(user_input, current_model, stream=True)

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
